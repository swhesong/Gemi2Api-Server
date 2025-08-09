# =================================================================
# Gemi2Api-Server Dockerfile (简化版本)
# =================================================================

FROM python:3.12-slim-bookworm as builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装构建依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        g++ \
        python3-dev \
        build-essential \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 升级 pip 和基础工具
RUN python -m pip install --upgrade pip setuptools wheel

# 复制项目配置文件
COPY pyproject.toml ./

# 安装 tomli 来解析 pyproject.toml
RUN pip install tomli

# 直接从 pyproject.toml 安装依赖
RUN pip install -e . || \
    (echo "Failed to install from pyproject.toml, trying fallback..." && \
     pip install fastapi>=0.115.0 uvicorn[standard]>=0.35.0 pydantic>=2.10.0 \
                 httpx>=0.25.0 python-dotenv>=1.0.0 PyYAML>=6.0.0)

# =================================================================
# STAGE 2: The Final Stage
# =================================================================
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装运行时依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# 复制应用代码
COPY . .

# 创建非特权用户
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /app/data /app/temp /app/cache && \
    chmod +x start.py && \
    chown -R appuser:appgroup /app

# 切换到非特权用户
USER appuser

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["python", "start.py"]
