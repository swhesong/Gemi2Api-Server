# =================================================================
# Gemi2Api-Server Dockerfile (最终优化版 with lockfile)
#
# 该版本结合了所有优点，并使用锁文件实现100%可复现构建：
# - [可靠性] 使用 requirements.txt 锁文件，确保构建环境一致。
# - [效率] 优化了层缓存，只有依赖变更时才会重新安装。
# - [安全性] 使用无权限的系统用户运行。
# - [优化] 添加了 PIP_* 环境变量以提升构建效率。
# - [简洁] 代码清晰，职责明确。
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# 任务：基于锁文件安装所有 Python 依赖
# =================================================================
FROM python:3.12-slim-bookworm as builder

# 设置环境变量，优化构建过程
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装构建Python包所需的最小系统依赖
# 清理apt缓存以减小层的大小
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 升级 pip 自身
RUN python -m pip install --upgrade pip setuptools wheel

# 1. 仅复制 requirements.txt 锁文件
# 这一步利用了Docker层缓存。只要锁文件不变，下面的安装步骤就不会重新执行。
COPY requirements.txt ./

# 2. 从锁文件安装所有依赖。这是最耗时的一步，会被高度缓存。
RUN pip install --no-cache-dir -r requirements.txt

# 3. 复制项目所有剩余的代码文件
COPY . .

# 4. 安装您自己的项目代码（gemi2api-server）
# --no-deps 确保 pip 不会再去检查依赖，因为上一步已经全部装好了。
# 这一步非常快，因为它只处理您自己的代码。
RUN pip install --no-cache-dir --no-deps .

# =================================================================
# STAGE 2: The Final Stage
# 任务：构建轻量级、安全的最终运行镜像
# =================================================================
FROM python:3.12-slim-bookworm

# 设置运行时环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装运行时的最小系统依赖 (curl 用于健康检查)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 阶段复制已安装的Python包和可执行文件
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
# 复制您自己的项目代码
COPY --from=builder /app /app

# 创建一个安全的、无登录权限的系统用户来运行应用
# 并将应用目录的所有权赋予该用户
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /bin/false appuser && \
    chown -R appuser:appgroup /app

# 切换到这个非root用户
USER appuser

# 暴露应用程序端口
EXPOSE 8000

# 设置健康检查，以确保容器能够正常提供服务
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# 设置容器的默认启动命令
CMD ["python", "start.py"]

