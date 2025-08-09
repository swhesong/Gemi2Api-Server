# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台优化版 v2)
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

# 设置工作目录
WORKDIR /app

# 复制依赖定义文件
COPY pyproject.toml ./

# --- 【关键步骤：在同一层中安装 uv 并使用它】 ---
# 将 uv 的安装和使用合并到一条 RUN 指令中，以确保 PATH 生效，避免 "command not found" (exit 127) 错误。
# 使用 '&& \' 连接命令。
# 1. 安装 uv
# 2. 将 uv 添加到 PATH
# 3. 使用 'uv pip install' 安装依赖
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    export PATH="/root/.cargo/bin:$PATH" && \
    uv pip install --no-cache-dir --no-dev --system .

# =================================================================
# STAGE 2: The Final Stage (这部分保持不变)
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
RUN groupadd -g 1000 nobody && \
    useradd -u 1000 -g nobody -s /bin/false nobody && \
    mkdir -p /app/data /app/temp /app/cache && \
    chmod +x start.py && \
    chown -R nobody:nobody /app

# 切换到非 root 用户
USER nobody

# 暴露应用程序端口
EXPOSE 8000

# 定义健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# 定义启动应用程序的命令
CMD ["python", "start.py"]
