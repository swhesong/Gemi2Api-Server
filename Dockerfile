# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台最终版)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# =================================================================
FROM python:3.12-slim-bookworm as builder

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装构建依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        python3-dev \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制依赖定义文件
COPY pyproject.toml ./

# --- 【关键修复】 ---
# 在同一层中安装 uv，并使用其绝对路径 /root/.cargo/bin/uv 来执行，彻底避免 "command not found" (exit 127) 错误。
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    /root/.cargo/bin/uv pip install --no-cache-dir --no-dev --system .

# =================================================================
# STAGE 2: The Final Stage (这部分无需改动)
# =================================================================
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY . .

RUN groupadd -g 1000 nobody && \
    useradd -u 1000 -g nobody -s /bin/false nobody && \
    mkdir -p /app/data /app/temp /app/cache && \
    chmod +x start.py && \
    chown -R nobody:nobody /app

USER nobody
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "start.py"]
