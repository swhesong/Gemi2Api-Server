# =================================================================
# Gemi2Api-Server Dockerfile (最终优化版)
#
# 该版本结合了版本A和版本B的优点，并遵循了最佳实践：
# - [源自 B] 依赖安装: 严格、可靠，强制使用 pyproject.toml。
# - [源自 B] 安全性: 使用无登录shell的系统用户。
# - [源自 B] 简洁性: 移除了不必要的 chmod +x。
# - [源自 A] 优化: 添加了 PIP_* 环境变量以提升构建效率。
# - [源自 A] 语法糖: 使用 brace expansion 创建目录，更简洁。
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# 任务：编译和安装所有 Python 依赖
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

# 仅复制 pyproject.toml 以利用Docker层缓存
# 只有当此文件变动时，下面的依赖安装层才会重新构建
COPY pyproject.toml ./

# 从 pyproject.toml 安装所有项目依赖
# 这是唯一、可靠的依赖来源。如果失败，构建将中止。
RUN pip install .

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

# 复制应用程序的源代码
# 这应该在依赖安装之后，以优化层缓存
COPY . .

# 创建一个安全的、无登录权限的系统用户来运行应用
# 并将应用目录的所有权赋予该用户
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -s /bin/false appuser && \
    mkdir -p /app/{data,temp,cache} && \
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
