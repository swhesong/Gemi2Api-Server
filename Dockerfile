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
        python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Install the uv tool itself using the official script
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Set the working directory
WORKDIR /app

# Copy only the dependency definition file first to leverage Docker cache
COPY pyproject.toml .

# Use uv to install all Python dependencies defined in pyproject.toml
# --system installs them to the global site-packages directory
RUN uv pip install --system --no-cache-dir .


# =================================================================
# STAGE 2: The Final Stage
# - Creates the final, clean, and small production image
# =================================================================
FROM python:3.12-slim-bookworm

# Set the same environment variables for consistency
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only the runtime dependencies. In this case, only 'curl' for the healthcheck.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed Python packages from the 'builder' stage
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/

# Copy the rest of the application code
COPY . .

# Create necessary directories and set executable permission for the start script
RUN mkdir -p /app/data /app/temp /app/cache && \
    chmod +x start.py

# Expose the application port
EXPOSE 8000

# Define a healthcheck to ensure the application is running correctly
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Define the command to run the application
CMD ["python", "start.py"]

