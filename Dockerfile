# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台最终版 - 保险方案)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# =================================================================
FROM python:3.12-slim-bookworm as builder

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装构建依赖，并添加 ca-certificates, gzip, unzip 等工具，
# 以确保安装脚本在多平台环境下能正确运行。
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gzip \
        unzip \
        gcc \
        python3-dev \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制依赖定义文件
COPY pyproject.toml ./

# --- 【保险修复方案】 ---
# 如果 uv 仍有问题，回退到传统 pip 方式，但保持多阶段构建
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -c "
import sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib

with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
deps = data['project']['dependencies']
with open('/tmp/requirements.txt', 'w') as f:
    for dep in deps:
        f.write(f'{dep}\n')
" && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

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
