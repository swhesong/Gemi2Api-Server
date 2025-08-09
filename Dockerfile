# =================================================================
# Gemi2Api-Server Dockerfile (最终精简、正确版本)
#
# 该版本移除了不必要的安装步骤，直接运行源码，解决了构建失败问题。
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

# =================================================================
# ▼▼▼ 核心修正 ▼▼▼
#
# RUN pip install --no-cache-dir --no-deps .  <-- 删除这一行！
#
# 原因：此项目通过 `python start.py` 直接运行，
# 无需将自身作为包安装，此步骤不仅多余，而且是导致错误的根源。
#
# =================================================================


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
COPY entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["entrypoint.sh"]
# 创建用户 (注意：这里我们先不切换用户，让 entrypoint.sh 以 root 身份运行)
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /bin/false appuser
    # 注意：chown 的逻辑移到了 entrypoint.sh 中，这里可以简化或保留

# 切换到这个非root用户
USER appuser

# 暴露应用程序端口
EXPOSE 8000

# 设置健康检查，以确保容器能够正常提供服务
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# 设置容器的默认启动命令
CMD ["python", "start.py"]

