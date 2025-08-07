# 使用官方 uv 基础镜像
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 设置工作目录
WORKDIR /app

# 复制 pyproject.toml 文件
# 这样做可以利用 Docker 的层缓存，只有当 pyproject.toml 变化时才重新安装依赖
COPY pyproject.toml .

# 安装依赖
# 使用 uv pip install . 来安装当前项目及其在 pyproject.toml 中定义的依赖
# 使用 --system 标志告诉 uv 在容器的系统 Python 环境中安装
# 使用 --no-cache-dir 避免缓存增加镜像大小
# 添加 --retry 3 增加网络稳定性
RUN uv pip install --system --no-cache-dir .

# 复制应用程序代码
COPY main.py .
# 如果你的代码在 src 目录，使用: COPY ./src ./src

# 暴露端口
EXPOSE 8000

# 运行 uvicorn 服务器
# 确保 main.py 在 /app 目录下，或者调整为模块路径，例如 src.main:app
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

