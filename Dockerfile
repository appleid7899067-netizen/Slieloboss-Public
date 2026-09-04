FROM ghcr.io/zhayujie/chatgpt-on-wechat:latest

# Render: when a persistent disk is mounted at /var/data, keep both the
# CowAgent config/data root and ~/cow Agent workspace on that disk.
ENV HOME=/var/data \
    COW_DATA_DIR=/var/data

ENTRYPOINT ["/entrypoint.sh"]