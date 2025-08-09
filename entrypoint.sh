#!/bin/sh
# entrypoint.sh

# 检查并设置挂载目录的所有权
# /app/data, /app/temp 等都是在 docker-compose.yml 中定义的卷
chown -R appuser:appgroup /app/data /app/temp /app/.venv

# 使用 exec "$@" 来执行 Dockerfile 中 CMD 定义的命令
# 这样可以确保 python 进程是主进程 (PID 1)，能正确接收信号
exec "$@"