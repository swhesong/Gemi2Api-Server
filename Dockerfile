# =================================================================
# STAGE 1: The Builder Stage
# - Installs build tools and all Python dependencies
# =================================================================
FROM python:3.12-slim-bookworm as builder

# Set environment variables
# Set DEBIAN_FRONTEND to noninteractive to avoid prompts
# Set PATH to include the default location for pip/uv installed binaries
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

# Install system dependencies required for installing uv and building packages
# We need curl to fetch uv, and gcc/python3-dev to build C extensions like lmdb
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        python3-dev \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install the uv tool itself using the official script
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Set the working directory
WORKDIR /app

# --- 【关键步骤 1：复制依赖定义文件】 ---
# 这一步会复制 pyproject.toml 和 uv.lock 文件。
# 在我们的 GitHub Actions 流程中，uv.lock 是在上一步刚刚为 Linux 平台生成的。
# 所以这里复制进来的是一个 100% 正确和最新的锁文件。
COPY pyproject.toml uv.lock* ./

# --- 【关键步骤 2：确定性地安装依赖】 ---
# 使用 uv sync 命令，它比 'pip install' 更快、更可靠。
# --frozen: 这是一个非常重要的参数。它告诉 uv 严格按照 uv.lock 文件中的版本进行安装，
#           如果 uv.lock 和 pyproject.toml 不匹配，构建就会失败。
#           这保证了每次构建都是完全可复现的。
# --no-dev: 不安装开发依赖（如 ruff, pytest）。
# --system: 将包装安装到系统级的 Python环境中，而不是虚拟环境。这在 Docker 中是推荐做法。
RUN uv sync --frozen --no-dev --system

# =================================================================
# STAGE 2: The Final Stage
# - Creates the final, clean, and small production image

# =================================================================
FROM python:3.12-slim-bookworm

# Set the same environment variables for consistency
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only the runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed Python packages from the 'builder' stage
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy the rest of the application code
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p /app/data /app/temp /app/cache && \
    chmod +x start.py && \
    chown -R nobody:nogroup /app

# Switch to non-root user for security
USER nobody

# Expose the application port
EXPOSE 8000

# Define a healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Define the command to run the application
CMD ["python", "start.py"]
