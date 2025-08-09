#!/usr/bin/env python3

import os
import sys
import asyncio
from pathlib import Path

# 确保配置文件模块可以被导入
sys.path.insert(0, str(Path(__file__).parent))

def setup_environment():
    """Setup environment and validate configuration"""
    print("🚀 Enhanced Gemini API Server v0.5.0+enhanced")
    print("=" * 50)
    
    # 检查Python版本 - 修复版本检查不一致的问题
    python_version = sys.version_info
    if python_version < (3, 10):
        print(f"❌ Python {python_version.major}.{python_version.minor} detected. Requires Python 3.10+")
        sys.exit(1)
    else:
        print(f"✅ Python {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # 检查配置文件
    config_file = Path("config.yaml")
    if config_file.exists():
        print(f"✅ Found YAML config: {config_file}")
        # 验证YAML文件格式
        try:
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                if config_data:
                    print("✅ YAML config validation passed")
                else:
                    print("⚠️ YAML config is empty")
        except ImportError:
            print("⚠️ PyYAML not available for validation")
        except Exception as e:
            print(f"⚠️ YAML config validation failed: {e}")
    else:
        print("ℹ️  No YAML config found, using environment variables")
    
    # 检查环境变量
    env_vars = ["SECURE_1PSID", "SECURE_1PSIDTS", "API_KEY", "GEMINI_PROXY"]
    found_credentials = False
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            if var in ["SECURE_1PSID", "SECURE_1PSIDTS"]:
                found_credentials = True
            if len(value) >= 10:
                print(f"✅ {var}: {value[:10]}...")
            else:
                print(f"✅ {var}: Set")
        else:
            print(f"⚪ {var}: Not set")
    
    if not found_credentials and not config_file.exists():
        print("⚠️ No credentials found in environment or config file")
        print("   The server will attempt to use browser cookies as fallback")
    
    # 检查依赖 - 添加更友好的错误处理
    dependencies = [
        ("lmdb", "Enhanced LMDB support", False),  # 可选依赖
        ("orjson", "Fast JSON serialization", False),  # 可选依赖
        ("browser_cookie3", "Browser cookie support", False),  # 可选依赖
        ("loguru", "Enhanced logging", True),  # 必需依赖
        ("pydantic_settings", "YAML configuration", True),  # 必需依赖
        ("gemini_webapi", "Gemini Web API client", False),  # 可选依赖
        ("fastapi", "FastAPI framework", True),  # 必需依赖
        ("uvicorn", "ASGI server", True),  # 必需依赖
    ]
    
    missing_critical_deps = []
    missing_optional_deps = []
    
    for module_name, description, is_required in dependencies:
        try:
            __import__(module_name)
            print(f"✅ {description} available")
        except ImportError:
            if is_required:
                print(f"❌ {description} not available (REQUIRED)")
                missing_critical_deps.append(module_name)
            else:
                print(f"⚠️ {description} not available (optional)")
                missing_optional_deps.append(module_name)
    
    # 只有缺少关键依赖时才退出
    if missing_critical_deps:
        print(f"❌ Missing critical dependencies: {', '.join(missing_critical_deps)}")
        print("   Install with: uv sync or pip install -r requirements.txt")
        sys.exit(1)
    
    # 警告可选依赖缺失，但不退出
    if missing_optional_deps:
        print(f"⚠️ Missing optional dependencies: {', '.join(missing_optional_deps)}")
        print("   Some features may be disabled.")
    
    print("=" * 50)

def main():
    """主启动函数"""
    setup_environment()
    
    # 导入并启动主应用
    try:
        import uvicorn
        from main import app
        
        # 从配置或环境变量读取端口
        host = "0.0.0.0"
        port = 8000
        
        try:
            from config import g_config
            if g_config:
                host = g_config.server.host
                port = g_config.server.port
                print(f"📋 Using enhanced config: {host}:{port}")
            else:
                raise ImportError("Config not available")
        except Exception as e:
            print(f"⚠️ Enhanced config failed: {e}")
            host = os.getenv("HOST", "0.0.0.0")
            try:
                port = int(os.getenv("PORT", "8000"))
            except (ValueError, TypeError):
                port = 8000
                print("⚠️ Invalid PORT environment variable, using default 8000")
            print(f"📋 Using environment config: {host}:{port}")
        
        # 验证端口范围
        if not (1 <= port <= 65535):
            print(f"⚠️ Invalid port {port}, using default 8000")
            port = 8000
        
        print(f"🌐 Starting server on {host}:{port}")
        uvicorn.run(
            "main:app", 
            host=host, 
            port=port, 
            log_level="info",
            reload=False,
            access_log=True,
            workers=1,  # 单工作进程避免并发问题
            timeout_keep_alive=30,
        )
        
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
        sys.exit(0)
    except ImportError as ie:
        print(f"❌ Import error: {ie}")
        print("请确保所有依赖已正确安装: pip install -r requirements.txt 或 uv sync")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
