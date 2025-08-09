# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台 - 最终修正方案)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage (这部分已验证成功，无需改动)
# =================================================================
FROM python:3.12-slim-bookworm as builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml pyproject.toml

# 使用 --no-cache-dir 减少镜像大小
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# =================================================================
# STAGE 2: The Final Stage (最终修正此处)
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

# --- 【最终修正】 ---
# 1. 创建一个全新的、专用的、不会冲突的用户'appuser'和组'appgroup'
#    -r 选项表示创建一个系统用户/组
# 2. 将相关目录的所有权赋予这个新用户
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /bin/false appuser && \
    mkdir -p /app/data /app/temp /app/cache && \
    chown -R appuser:appgroup /app

# 使用新创建的非root用户运行应用
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "start.py"]
