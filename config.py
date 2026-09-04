# encoding:utf-8

import logging
import os
import signal
import sys
import time

from channel import channel_factory
from common import const
from common.log import logger
from common.ssl_certs import ensure_ca_bundle
from config import load_config, conf
from plugins import *
import threading


_channel_mgr = None

# Desktop mode: a lighter runtime for the packaged Electron client. Plugins are
# loaded in a background thread (so command plugins like cow_cli/godcmd work
# without slowing startup), while MCP warmup is still skipped to keep it fast.
DESKTOP_MODE = os.environ.get("COW_DESKTOP") == "1"


def get_channel_manager():
    return _channel_mgr


def _parse_channel_type(raw) -> list:
    """
    Parse channel_type config value into a list of channel names.
    Supports:
      - single string: "feishu"
      - comma-separated string: "feishu, dingtalk"
      - list: ["feishu", "dingtalk"]
    """
    if isinstance(raw, list):
        return [ch.strip() for ch in raw if ch.strip()]
    if isinstance(raw, str):
        return [ch.strip() for ch in raw.split(",") if ch.strip()]
    return []


def _has_web_entry(channel_names: list) -> bool:
    """True if the web console is already in the startup list (string or instance)."""
    from channel.channel_instances import ChannelInstance
    for entry in channel_names:
        if isinstance(entry, ChannelInstance):
            if entry.channel_type == "web":
                return True
        elif entry == "web":
            return True
    return False


def _resolve_startup_channels(raw_channel):
    """Startup channel list = config.json's channels plus team.json's instances,
    de-duplicated by channel *type* for multi-instance-ready types.

    config.json stays the source of truth for anything it configures: its
    ``channel_type`` list (dingtalk, wecom, ...) always starts, exactly as a
    legacy install expects. team.json's ``channel_instances`` carries the
    explicit multi-instance bots (feishu today), each with its own credentials
    and Agent binding.

    The subtlety is feishu: config.json's flat ``feishu`` entry and a
    ``channel_instances`` feishu record are the *same kind of connection*. Once
    team.json manages feishu (at least one feishu instance exists), feishu's
    single source of truth is ``channel_instances`` — the flat config entry is
    dropped so the same bot is not started twice on one websocket. This holds no
    matter which Agent the instances are bound to: rebinding every feishu
    instance away from the default Agent must NOT resurrect config.json's feishu
    as a stray default-bound bot. Non-multi-instance types are never managed by
    instances, so config keeps starting them untouched.

    A legacy single-Agent install has no team.json / no channel_instances and
    this returns exactly ``_parse_channel_type(raw_channel)`` as before.
    """
    from channel.channel_instances import MULTI_INSTANCE_READY, _normalize_type

    names = _parse_channel_type(raw_channel)

    instances = []
    try:
        from agent import team
        from channel.channel_instances import resolve_channel_instances

        settings = team.resolve(conf())
        raw_instances = settings.get("channel_instances")
        if isinstance(raw_instances, list) and raw_instances:
            instances = resolve_channel_instances(settings)
    except Exception as e:
        logger.warning(
            f"[App] Failed to resolve channel_instances, using config.json "
            f"channel_type only: {e}"
        )
        instances = []

    # Types now owned by channel_instances (feishu, ...). Drop config.json's
    # flat entry for these so the instance records are the only source.
    managed_types = {
        inst.channel_type
        for inst in instances
        if inst.channel_type in MULTI_INSTANCE_READY
    }

    entries = []
    for name in names:
        if _normalize_type(name) in managed_types:
            logger.info(
                f"[App] channel_type '{name}' is managed by channel_instances; "
                f"skipping the flat config.json entry to avoid a duplicate bot"
            )
            continue
        entries.append(name)

    if instances:
        logger.info(
            f"[App] Starting channel_instances: "
            f"{[(i.instance_id, i.channel_type, i.agent_id) for i in instances]}"
        )
        entries.extend(instances)

    if not entries:
        entries = ["web"]
    return entries


class ChannelManager:
    """
    Manage the lifecycle of multiple channels running concurrently.
    Each channel.startup() runs in its own daemon thread.
    The web channel is started as default console unless explicitly disabled.
    """

    def __init__(self):
        self._channels = {}        # channel_name -> channel instance
        self._threads = {}         # channel_name -> thread
        self._primary_channel = None
        self._lock = threading.Lock()
        self.cloud_mode = False    # set to True when cloud client is active

    @property
    def channel(self):
        """Return the primary (first non-web) channel for backward compatibility."""
        return self._primary_channel

    def get_channel(self, channel_name: str):
        return self._channels.get(channel_name)

    @staticmethod
    def _normalize_entry(entry):
        """Accept both a legacy channel-type string and a ChannelInstance.

        Returns (name, channel_type, factory_kwargs). For a plain string this
        reproduces the old behavior exactly: name == channel_type and no
        per-instance overrides. For a ChannelInstance, the registry key is the
        instance_id, and the factory receives credentials + binding so several
        instances of one type can coexist.
        """
        from channel.channel_instances import ChannelInstance

        if isinstance(entry, ChannelInstance):
            return (
                entry.instance_id,
                entry.channel_type,
                {
                    "instance_id": entry.instance_id,
                    "bound_agent_id": entry.agent_id,
                    "credentials": entry.credentials or None,
                    "members": entry.members or None,
                },
            )
        return (entry, entry, {})

    def start(self, channel_names: list, first_start: bool = False):
        """
        Create and start one or more channels in sub-threads.
        If first_start is True, plugins and linkai client will also be initialized.

        Each entry may be a legacy channel-type string or a ChannelInstance.
        """
        entries = [self._normalize_entry(e) for e in channel_names]

        # A concurrent path may have started this channel already (saving its
        # config restarts it, connecting it starts it). Overwriting the registry
        # entry below would orphan that instance: nothing holds it any more, yet
        # its connection stays up and keeps consuming events, so every inbound
        # message gets handled twice.
        for name, _ctype, _kw in entries:
            if self._channels.get(name) is not None:
                logger.warning(f"[ChannelManager] Channel '{name}' is already running, stopping it first")
                self.stop(name)

        with self._lock:
            channels = []
            for name, channel_type, factory_kwargs in entries:
                # One misconfigured channel (e.g. wechatcom_app without its
                # corp_id/token/aes_key) must not take the whole process down:
                # instantiating it can raise while parsing config. The web
                # console in particular has to come up so the desktop shell can
                # surface the error and let the user fix the config. Skip the
                # broken channel and keep the rest.
                try:
                    ch = channel_factory.create_channel(channel_type, **factory_kwargs)
                except Exception as e:
                    logger.error(f"[ChannelManager] Failed to create channel '{name}', skipping it: {e}")
                    logger.exception(e)
                    continue
                ch.cloud_mode = self.cloud_mode
                self._channels[name] = ch
                channels.append((name, ch))
                if self._primary_channel is None and name != "web":
                    self._primary_channel = ch

            if self._primary_channel is None and channels:
                self._primary_channel = channels[0][1]

            if first_start:
                if DESKTOP_MODE:
                    # Load plugins in the background so command plugins
                    # (cow_cli / godcmd, e.g. /status, #help) work
                    # without blocking web-service readiness.
                    threading.Thread(
                        target=PluginManager().load_plugins, daemon=True
                    ).start()
                else:
                    PluginManager().load_plugins()

                # Cloud client is optional. It is only started when
                # use_linkai=True AND cloud_deployment_id is set.
                # By default neither is configured, so the app runs
                # entirely locally without any remote connection.
                if conf().get("use_linkai") and (
                    os.environ.get("CLOUD_DEPLOYMENT_ID") or conf().get("cloud_deployment_id")
                ):
                    try:
                        from common import cloud_client
                        threading.Thread(
                            target=cloud_client.start,
                            args=(self._primary_channel, self),
                            daemon=True,
                        ).start()
                    except Exception:
                        pass

            # Start web console first so its logs print cleanly,
            # then start remaining channels after a brief pause.
            web_entry = None
            other_entries = []
            for entry in channels:
                if entry[0] == "web":
                    web_entry = entry
                else:
                    other_entries.append(entry)

            ordered = ([web_entry] if web_entry else []) + other_entries
            for i, (name, ch) in enumerate(ordered):
                if i > 0 and name != "web":
                    time.sleep(0.1)
                t = threading.Thread(target=self._run_channel, args=(name, ch), daemon=True)
                self._threads[name] = t
                t.start()
                logger.debug(f"[ChannelManager] Channel '{name}' started in sub-thread")

    def _run_channel(self, name: str, channel):
        try:
            channel.startup()
        except Exception as e:
            logger.error(f"[ChannelManager] Channel '{name}' startup error: {e}")
            logger.exception(e)
            # The desktop client IS the web channel: without it the Electron
            # shell polls a health endpoint that will never answer and, 90s
            # later, blames a generic "initialization failed". Exiting non-zero
            # lets the shell surface the real error immediately. Server
            # deployments keep the old behavior - other channels may still be
            # serving, so one broken channel must not take the process down.
            if DESKTOP_MODE and name == "web":
                logging.shutdown()
                os._exit(1)

    def stop(self, channel_name: str = None):
        """
        Stop channel(s). If channel_name is given, stop only that channel;
        otherwise stop all channels.
        """
        # Pop under lock, then stop outside lock to avoid deadlock
        with self._lock:
            names = [channel_name] if channel_name else list(self._channels.keys())
            to_stop = []
            for name in names:
                ch = self._channels.pop(name, None)
                th = self._threads.pop(name, None)
                to_stop.append((name, ch, th))
            if channel_name and self._primary_channel is self._channels.get(channel_name):
                self._primary_channel = None

        for name, ch, th in to_stop:
            if ch is None:
                logger.warning(f"[ChannelManager] Channel '{name}' not found in managed channels")
                if th and th.is_alive():
                    self._interrupt_thread(th, name)
                continue
            logger.info(f"[ChannelManager] Stopping channel '{name}'...")
            graceful = False
            if hasattr(ch, 'stop'):
                try:
                    ch.stop()
                    graceful = True
                except Exception as e:
                    logger.warning(f"[ChannelManager] Error during channel '{name}' stop: {e}")
            if th and th.is_alive():
                th.join(timeout=5)
                if th.is_alive():
                    if graceful:
                        logger.info(f"[ChannelManager] Channel '{name}' thread still alive after stop(), "
                                    "leaving daemon thread to finish on its own")
                    else:
                        logger.warning(f"[ChannelManager] Channel '{name}' thread did not exit in 5s, forcing interrupt")
                        self._interrupt_thread(th, name)

    @staticmethod
    def _interrupt_thread(th: threading.Thread, name: str):
        """Raise SystemExit in target thread to break blocking loops like start_forever."""
        import ctypes
        try:
            tid = th.ident
            if tid is None:
                return
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(tid), ctypes.py_object(SystemExit)
            )
            if res == 1:
                logger.info(f"[ChannelManager] Interrupted thread for channel '{name}'")
            elif res > 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
                logger.warning(f"[ChannelManager] Failed to interrupt thread for channel '{name}'")
        except Exception as e:
            logger.warning(f"[ChannelManager] Thread interrupt error for '{name}': {e}")

    def restart(self, new_channel):
        """
        Restart a single channel.
        Can be called from any thread (e.g. remote config callback).

        Accepts a channel-type string or a ChannelInstance. When a bare string
        names a known explicit instance, its record (binding + credentials) is
        looked up so the restart keeps its identity instead of falling back to
        the legacy global-config path.
        """
        from channel.channel_instances import ChannelInstance

        entry = new_channel
        if not isinstance(entry, ChannelInstance):
            entry = self._resolve_instance_entry(new_channel) or new_channel
        name = entry.instance_id if isinstance(entry, ChannelInstance) else entry
        logger.info(f"[ChannelManager] Restarting channel '{name}'...")
        self.stop(name)
        _clear_singleton_cache(name)
        time.sleep(1)
        self.start([entry], first_start=False)
        logger.info(f"[ChannelManager] Channel '{name}' restarted successfully")

    @staticmethod
    def _resolve_instance_entry(name: str):
        """Return the ChannelInstance stored for *name*, or None.

        Lets a restart/add triggered with a bare id recover the instance's
        binding and credentials from the roster file. Absent (legacy installs),
        returns None and the caller keeps the plain-string behavior.
        """
        try:
            from config import conf
            from channel.channel_instances import get_instance
            return get_instance(conf(), name)
        except Exception:
            return None

    def add_channel(self, channel):
        """
        Dynamically add and start a new channel.
        If the channel is already running, restart it instead.

        ``channel`` may be a legacy channel-type string (single-instance,
        credentials read from global config) or a ChannelInstance carrying its
        own id, binding and credentials (one of several instances of a type).
        """
        from channel.channel_instances import ChannelInstance

        channel_name = (
            channel.instance_id if isinstance(channel, ChannelInstance) else channel
        )
        with self._lock:
            if channel_name in self._channels:
                logger.info(f"[ChannelManager] Channel '{channel_name}' already exists, restarting")
        if self._channels.get(channel_name):
            self.restart(channel_name)
            return
        logger.info(f"[ChannelManager] Adding channel '{channel_name}'...")
        _clear_singleton_cache(channel_name)
        self.start([channel], first_start=False)
        logger.info(f"[ChannelManager] Channel '{channel_name}' added successfully")

    def remove_channel(self, channel_name: str):
        """
        Dynamically stop and remove a running channel.
        """
        with self._lock:
            if channel_name not in self._channels:
                logger.warning(f"[ChannelManager] Channel '{channel_name}' not found, nothing to remove")
                return
        logger.info(f"[ChannelManager] Removing channel '{channel_name}'...")
        self.stop(channel_name)
        logger.info(f"[ChannelManager] Channel '{channel_name}' removed successfully")


def _clear_singleton_cache(channel_name: str):
    """
    Clear the singleton cache for the channel class so that
    a new instance can be created with updated config.
    """
    cls_map = {
        "web": "channel.web.web_channel.WebChannel",
        "wechatmp": "channel.wechatmp.wechatmp_channel.WechatMPChannel",
    }
    try:
        path = cls_map.get(channel_name)
        if not path:
            return
        module_name, cls_name = path.rsplit('.', 1)
        module = __import__(module_name, fromlist=[cls_name])
        cls = getattr(module, cls_name, None)
        if cls is not None and hasattr(cls, "_instance"):
            cls._instance = None
    except Exception:
        pass


# Keep the rest of the application file unchanged below this point.
