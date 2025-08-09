#!/bin/sh

# 立即退出，如果任何命令失败
set -e

# 以 root 用户身份运行
echo "🚀 Entrypoint script started as user: $(whoami)"

# 检查 config.yaml 是否存在。这个文件应该由 volumes 挂载进来
# if [ ! -f /app/config.yaml ]; then
#     echo "Error: config.yaml not found in /app/. Please make sure it is mounted as a volume."
#     exit 1
# fi

# 修复 /app 目录权限
# 这个 chown 非常重要，特别是当你挂载了本地目录作为 volume 时
echo "🔧 Fixing permissions for mounted volumes..."
mkdir -p /app/data /app/temp /app/.venv/lib/python3.12/site-packages/gemini_webapi/utils/temp
chown -R appuser:appgroup /app/data
chown -R appuser:appgroup /app/temp
chown -R appgroup:appgroup /app/.venv/lib/python3.12/site-packages/gemini_webapi/utils/temp

# ▼▼▼ 核心安全步骤 ▼▼▼
# 使用 gosu 将执行权限从 root 切换到 appuser，然后运行 CMD 命令。
# "$@" 代表从 Dockerfile 的 CMD 或 docker-compose 的 command 传递过来的命令。
echo "🔐 Switching to 'appuser' to execute command: $@"
exec gosu appuser "$@"
