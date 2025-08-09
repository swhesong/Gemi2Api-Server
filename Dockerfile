# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台优化版)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# - 安装构建工具和所有 Python 依赖
# - 这一阶段会为每个目标平台 (amd64, arm64) 单独运行
# =================================================================
FROM python:3.12-slim-bookworm as builder

# 设置环境变量，避免交互式提示，并优化 Python 运行
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 更新系统并安装构建依赖
# curl 用于下载 uv，gcc/python3-dev 用于编译 lmdb 等需要C扩展的库
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        python3-dev \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

# 安装 uv 工具
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# 将 uv 加入 PATH，确保后续命令可以找到它
ENV PATH="/root/.cargo/bin:$PATH"

# 设置工作目录
WORKDIR /app

# --- 【关键步骤 1：复制依赖定义文件】 ---
# 只复制 pyproject.toml。这是为了充分利用 Docker 的缓存。
# 只有当这个文件发生变化时，下面的依赖安装步骤才会重新执行。
COPY pyproject.toml ./

# --- 【关键步骤 2：平台感知的依赖安装】 ---
# 使用 'uv pip install' 而不是 'uv sync'。
# 'uv pip install' 会根据当前构建的平台（TARGETPLATFORM）去解析和安装正确的依赖。
# 这就解决了之前 amd64 的锁文件在 arm64 上不兼容的问题。
# --no-dev: 不安装开发依赖。
# --system: 将包安装到系统 Python 环境中，这是在 Docker 中推荐的做法。
RUN uv pip install --no-cache-dir --no-dev --system .

# =================================================================
# STAGE 2: The Final Stage
# - 创建最终的、干净的、小体积的生产镜像
# =================================================================
FROM python:3.12-slim-bookworm

# 设置相同的环境变量以保持一致性
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 只安装运行应用所必需的系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 'builder' 阶段复制已经安装好的 Python 依赖库
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
# 复制可能由依赖安装的可执行文件
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# 复制应用程序的全部源代码
COPY . .

# 创建应用所需的目录，并为启动脚本添加执行权限
# 注意：这里我们创建一个普通用户 nobody 来运行程序，以增强安全性
RUN groupadd -g 1000 nobody && \
    useradd -u 1000 -g nobody -s /bin/false nobody && \
    mkdir -p /app/data /app/temp /app/cache && \
    chmod +x start.py && \
    chown -R nobody:nobody /app

# 切换到非 root 用户
USER nobody

# 暴露应用程序端口
EXPOSE 8000

# 定义健康检查，这和您原来的一样
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# 定义启动应用程序的命令
CMD ["python", "start.py"]
