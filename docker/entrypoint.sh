#!/bin/bash
set -e

# build prefix
CHATGPT_ON_WECHAT_PREFIX=${CHATGPT_ON_WECHAT_PREFIX:-""}
# path to config.json
CHATGPT_ON_WECHAT_CONFIG_PATH=${CHATGPT_ON_WECHAT_CONFIG_PATH:-""}
# execution command line
CHATGPT_ON_WECHAT_EXEC=${CHATGPT_ON_WECHAT_EXEC:-""}

# use environment variables to pass parameters
# if you have not defined environment variables, set them below
# export OPEN_AI_API_KEY=${OPEN_AI_API_KEY:-'YOUR API KEY'}
# export OPEN_AI_PROXY=${OPEN_AI_PROXY:-""}
# export SINGLE_CHAT_PREFIX=${SINGLE_CHAT_PREFIX:-'["bot", "@bot"]'}
# export SINGLE_CHAT_REPLY_PREFIX=${SINGLE_CHAT_REPLY_PREFIX:-'"[bot] "'}
# export GROUP_CHAT_PREFIX=${GROUP_CHAT_PREFIX:-'["@bot"]'}
# export GROUP_NAME_WHITE_LIST=${GROUP_NAME_WHITE_LIST:-'["ChatGPT测试群", "ChatGPT测试群2"]'}
# export IMAGE_CREATE_PREFIX=${IMAGE_CREATE_PREFIX:-'["画", "看", "找"]'}
# export CONVERSATION_MAX_TOKENS=${CONVERSATION_MAX_TOKENS:-"1000"}
# export SPEECH_RECOGNITION=${SPEECH_RECOGNITION:-"False"}
# export CHARACTER_DESC=${CHARACTER_DESC:-"你是ChatGPT, 一个由OpenAI训练的大型语言模型, 你旨在回答并解决人们的任何问题，并且可以使用多种语言与人交流。"}
# export EXPIRES_IN_SECONDS=${EXPIRES_IN_SECONDS:-"3600"}

# CHATGPT_ON_WECHAT_PREFIX is empty, use /app
if [ "$CHATGPT_ON_WECHAT_PREFIX" == "" ] ; then
    CHATGPT_ON_WECHAT_PREFIX=/app
fi

# Keep the legacy variable for compatibility, but make the mounted data root
# the source of truth for deployments using Render Persistent Disk.
DATA_ROOT=${COW_DATA_DIR:-/var/data}
AGENT_WORKSPACE=${AGENT_WORKSPACE:-$DATA_ROOT/cow}
export COW_DATA_DIR="$DATA_ROOT"
export AGENT_WORKSPACE

# CHATGPT_ON_WECHAT_CONFIG_PATH is empty, use the persistent config location.
if [ "$CHATGPT_ON_WECHAT_CONFIG_PATH" == "" ] ; then
    CHATGPT_ON_WECHAT_CONFIG_PATH="$DATA_ROOT/config.json"
fi
export CHATGPT_ON_WECHAT_CONFIG_PATH

# CHATGPT_ON_WECHAT_EXEC is empty, use ‘python app.py’
if [ "$CHATGPT_ON_WECHAT_EXEC" == "" ] ; then
    CHATGPT_ON_WECHAT_EXEC="python app.py"
fi

# modify content in config.json
# if [ "$OPEN_AI_API_KEY" == "YOUR API KEY" ] || [ "$OPEN_AI_API_KEY" == "" ]; then
#     echo -e "\033[31m[Warning] You need to set OPEN_AI_API_KEY before running!\033[0m"
# fi


# apply runtime timezone from TZ env so datetime.now() uses local time
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime 2>/dev/null || true
    echo "$TZ" > /etc/timezone 2>/dev/null || true
fi

# fix ownership of mounted volumes then drop to non-root user
if [ "$(id -u)" = "0" ]; then
    # Both config/data and the default agent workspace must be on the mounted
    # disk. Do not copy or delete legacy data here: preserve existing files and
    # leave any migration decision explicit and reversible.
    mkdir -p "$DATA_ROOT" "$AGENT_WORKSPACE"
    chown agent:agent "$DATA_ROOT" "$AGENT_WORKSPACE"
    exec su agent -s /bin/bash -c "cd \"$CHATGPT_ON_WECHAT_PREFIX\" && $CHATGPT_ON_WECHAT_EXEC"
fi

mkdir -p "$DATA_ROOT" "$AGENT_WORKSPACE"

# fallback: already running as agent
cd "$CHATGPT_ON_WECHAT_PREFIX"
$CHATGPT_ON_WECHAT_EXEC


