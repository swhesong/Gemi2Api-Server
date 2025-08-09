# =================================================================
# Gemi2Api-Server Dockerfile (多阶段 & 多平台 - 最终正确方案)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# =================================================================
FROM python:3.12-slim-bookworm as builder

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # 确保 pip 使用 build isolation，这是处理 pyproject.toml 的最佳实践
    PIP_USE_PEP517=1

# 更新系统并安装最基础的构建工具
# gcc 和 build-essential 是为了编译某些Python包的C扩展
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制定义项目元数据和依赖的文件
COPY pyproject.toml pyproject.toml

# --- 【最终正确方案】 ---
# 抛弃所有复杂的脚本。直接让 pip 从 pyproject.toml 安装依赖。
# pip 本身就具备解析此文件的能力。这是最直接、最可靠的方法。
# `.` 指的是当前目录，pip 会自动查找该目录下的 pyproject.toml 文件。
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

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

# 从 builder 阶段复制已经安装好的依赖包
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# 复制应用程序代码
COPY . .

# 设置用户和权限
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
