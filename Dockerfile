# =================================================================
# Gemi2Api-Server Dockerfile (最终修正版)
# =================================================================

# =================================================================
# STAGE 1: The Builder Stage
# =================================================================
FROM python:3.12-slim-bookworm as builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装构建依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        g++ \
        python3-dev \
        build-essential \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 升级 pip 和基础工具
RUN python -m pip install --upgrade pip setuptools wheel

# 复制项目配置文件
COPY pyproject.toml ./

# 【修正的核心问题】使用更可靠的依赖安装方法
RUN python -c "
import sys
import subprocess

# 安装必要的解析工具
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'tomli'])

try:
    import tomli
    print('📦 Parsing pyproject.toml...')
    
    with open('pyproject.toml', 'rb') as f:
        data = tomli.load(f)
    
    dependencies = data.get('project', {}).get('dependencies', [])
    
    if dependencies:
        print(f'Found {len(dependencies)} dependencies:')
        for i, dep in enumerate(dependencies, 1):
            print(f'  {i}. {dep}')
        
        # 分批安装，提高成功率
        success_count = 0
        failed_deps = []
        
        for dep in dependencies:
            try:
                print(f'Installing: {dep}')
                subprocess.check_call([
                    sys.executable, '-m', 'pip', 'install', 
                    '--no-cache-dir', '--timeout=300', dep
                ])
                success_count += 1
                print(f'✅ Successfully installed: {dep}')
            except subprocess.CalledProcessError as e:
                print(f'❌ Failed to install {dep}: {e}')
                failed_deps.append(dep)
                continue
        
        print(f'\\n📊 Installation Summary:')
        print(f'  ✅ Successful: {success_count}/{len(dependencies)}')
        if failed_deps:
            print(f'  ❌ Failed: {len(failed_deps)}')
            for dep in failed_deps:
                print(f'    - {dep}')
            
            # 对于失败的包，尝试安装替代版本或跳过可选依赖
            print(f'\\n🔄 Attempting fallback for critical dependencies...')
            critical_fallbacks = {
                'lmdb': 'lmdb==1.4.1',  # 使用稳定版本
                'orjson': 'orjson==3.9.0',  # 使用稳定版本
                'uvloop': None  # Windows平台会失败，可以跳过
            }
            
            for failed_dep in failed_deps:
                dep_name = failed_dep.split('>=')[0].split('==')[0]
                if dep_name in critical_fallbacks:
                    fallback = critical_fallbacks[dep_name]
                    if fallback:
                        try:
                            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', fallback])
                            print(f'✅ Fallback successful: {fallback}')
                        except:
                            print(f'⚠️ Fallback failed for {dep_name}')
    else:
        print('No dependencies found')
        
except Exception as e:
    print(f'❌ Error processing pyproject.toml: {e}')
    print('Installing essential dependencies as fallback...')
    
    # 安装最基础的依赖
    essential_deps = [
        'fastapi>=0.115.0',
        'uvicorn[standard]>=0.35.0',
        'pydantic>=2.10.0',
        'httpx>=0.25.0',
        'python-dotenv>=1.0.0',
        'PyYAML>=6.0.0'
    ]
    
    for dep in essential_deps:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', dep])
            print(f'✅ Essential dependency installed: {dep}')
        except:
            print(f'❌ Failed to install essential: {dep}')
            continue
"

# =================================================================
# STAGE 2: The Final Stage
# =================================================================
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装运行时依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# 复制应用代码
COPY . .

# 【修正用户创建问题】
# 使用标准的非特权用户创建方式
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /app/data /app/temp /app/cache && \
    chmod +x start.py && \
    chown -R appuser:appgroup /app

# 切换到非特权用户
USER appuser

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["python", "start.py"]
