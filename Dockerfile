FROM ghcr.io/zhayujie/chatgpt-on-wechat:latest

# Keep HOME as the container/user home; use the mounted disk only for app data.
ENV COW_DATA_DIR=/var/data \
    AGENT_WORKSPACE=/var/data/cow

ENTRYPOINT ["/entrypoint.sh"]
