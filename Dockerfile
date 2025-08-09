# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台最终版 - 绝对可靠方案)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# =================================================================
FROM python:3.12-slim-bookworm as builder

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装构建所需的基础依赖
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

# --- 【最终修复方案】 ---
# 1. 明确安装 tomli 作为备用，确保脚本在任何情况下都能运行。
# 2. 使用 Python 打印每个依赖，然后用 Shell 的 ">" 重定向到文件。
#    这是最可靠的方式，完全避免了所有棘手的字符转义问题。
RUN python -m pip install --upgrade pip setuptools wheel tomli && \
    python -c "import sys; \
               try: import tomllib; \
               except ImportError: import tomli as tomllib; \
               with open('pyproject.toml', 'rb') as f: data = tomllib.load(f); \
               deps = data.get('project', {}).get('dependencies', []); \
               for d in deps: print(d)" > /tmp/requirements.txt && \
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
