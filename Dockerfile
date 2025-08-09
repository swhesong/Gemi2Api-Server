# 使用官方 uv 基础镜像
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 复制 pyproject.toml 文件
# 这样做可以利用 Docker 的层缓存，只有当 pyproject.toml 变化时才重新安装依赖
COPY pyproject.toml .

# 安装依赖
# 使用 uv pip install . 来安装当前项目及其在 pyproject.toml 中定义的依赖
# 使用 --system 标志告诉 uv 在容器的系统 Python 环境中安装
# 使用 --no-cache-dir 避免缓存增加镜像大小
# 安装系统依赖（包括编译工具和curl），然后安装Python包，最后清理编译工具
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        curl && \
    uv pip install --system --no-cache-dir --retry 3 . && \
    apt-get purge -y --auto-remove build-essential python3-dev && \
    rm -rf /var/lib/apt/lists/*


# 复制所有应用程序文件
COPY . .

# 创建必要的目录
RUN mkdir -p /app/data /app/temp /app/cache

# 设置权限
RUN chmod +x start.py

# 暴露端口
EXPOSE 8000

# 添加健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 使用 start.py 启动应用，它包含了更好的配置检查和初始化
CMD ["python", "start.py"]
