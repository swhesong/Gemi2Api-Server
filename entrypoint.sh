#!/bin/sh

# 立即退出，如果任何命令失败
set -e

# 打印一条日志，确认脚本已开始执行
echo "Entrypoint script started..."

# 检查 config.yaml 是否存在。这个文件应该由 volumes 挂载进来
# if [ ! -f /app/config.yaml ]; then
#     echo "Error: config.yaml not found in /app/. Please make sure it is mounted as a volume."
#     exit 1
# fi

# 修复 /app 目录权限
# 这个 chown 非常重要，特别是当你挂载了本地目录作为 volume 时
echo "Fixing permissions for mounted volumes..."
chown -R appuser:appgroup /app/data
chown -R appuser:appgroup /app/temp
chown -R appuser:appgroup /app/.venv/lib/python3.12/site-packages/gemini_webapi/utils/temp

# 最关键的一步：
# 使用 exec "$@" 来执行 docker-compose.yml 中定义的 command。
# exec 会用新的进程替换当前的 shell 进程，
# 这使得你的应用（如 gunicorn）成为容器的 PID 1 进程，
# 能正确接收和处理来自 Docker deamon 的信号（如 SIGTERM），实现优雅停机。
echo "Executing command as user 'appuser': $@"
exec su-exec appuser "$@"
