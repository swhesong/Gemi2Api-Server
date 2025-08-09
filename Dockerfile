# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台 - 最终修正方案)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage (这部分已验证成功，无需改动)
# =================================================================
FROM python:3.12-slim-bookworm as builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_USE_PEP517=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml pyproject.toml

RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# =================================================================
# STAGE 2: The Final Stage (修正此处)
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
# 移除了不必要的 `chmod +x start.py` 命令，因为它导致了失败。
# `CMD ["python", "start.py"]` 不需要文件具有可执行权限。
RUN groupadd -g 1000 nobody && \
    useradd -u 1000 -g nobody -s /bin/false nobody && \
    mkdir -p /app/data /app/temp /app/cache && \
    chown -R nobody:nobody /app

USER nobody
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "start.py"]
