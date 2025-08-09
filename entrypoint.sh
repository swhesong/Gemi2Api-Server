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

# ▼▼▼ 修改 1: 合并所有目录创建到一个命令中 ▼▼▼
# 我们将所有需要创建的目录（包括那个很深的路径）都放在这里，-p 会处理好一切。
# 这样更整洁，也避免了重复。
echo "🔧 Creating all necessary application directories..."
mkdir -p /app/data
mkdir -p /app/temp
mkdir -p /app/cache
mkdir -p /app/.venv/lib/python3.12/site-packages/gemini_webapi/utils/temp

# ▼▼▼ 修改 2: 统一修复所有相关目录的权限 ▼▼▼
# 我们将 chown 命令和 "Fixing permissions" 的日志信息放在一起，逻辑更清晰。
# 最重要的是，为之前创建的那个深层路径也添加了权限设置。
echo "🔧 Fixing permissions for application directories..."
chown -R appuser:appgroup /app/data
chown -R appuser:appgroup /app/temp
chown -R appuser:appgroup /app/cache
chown -R appuser:appgroup /app/.venv/lib/python3.12/site-packages/gemini_webapi/utils/temp

# ▼▼▼ 核心安全步骤 (保持不变) ▼▼▼
# 使用 gosu 将执行权限从 root 切换到 appuser，然后运行 CMD 命令。
# "$@" 代表从 Dockerfile 的 CMD 或 docker-compose 的 command 传递过来的命令。
echo "🔐 Switching to 'appuser' to execute command: $@"
exec gosu appuser "$@"
