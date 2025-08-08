import asyncio
import base64
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import List, Optional, Union, Dict
from pathlib import Path
import re

import json
from fastapi import FastAPI, HTTPException, Depends, Request, Header
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gemini_webapi import GeminiClient
from gemini_webapi.constants import Model
from gemini_webapi.exceptions import AuthError, APIError, TimeoutError, UsageLimitExceeded, ModelInvalid, TemporarilyBlocked
import httpx


try:
    import browser_cookie3 as bc3
    HAS_BROWSER_COOKIE3 = True
except ImportError:
    HAS_BROWSER_COOKIE3 = False
    bc3 = None

# Environment variables
SECURE_1PSID = os.getenv("SECURE_1PSID")
SECURE_1PSIDTS = os.getenv("SECURE_1PSIDTS")  
API_KEY = os.getenv("API_KEY")
GEMINI_PROXY = os.getenv("GEMINI_PROXY")

app = FastAPI(title="Enhanced Gemini API FastAPI Server", version="0.4.0")
# 新增：添加CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Enhanced client management with connection pooling
gemini_clients = {}
client_pool_size = 3
client_last_used = {}
client_creation_time = {}  # 追踪客户端创建时间
CLIENT_IDLE_TIMEOUT = 900  # 15 minutes
CLIENT_MAX_LIFETIME = 1800  # 30 minutes maximum lifetime
CLIENT_HEALTH_CHECK_INTERVAL = 60  # 1 minute health check
CLIENT_COOKIE_REFRESH_THRESHOLD = 540  # 9 minutes - cookie refresh threshold

model_cache = {}
model_cache_timestamp = 0
MODEL_CACHE_TTL = 300  # 5 minutes cache TTL

def get_cached_models() -> Dict[str, Model]:
    """获取缓存的模型列表，减少重复查询"""
    global model_cache, model_cache_timestamp
    current_time = time.time()
    
    # 检查缓存是否有效
    if model_cache and (current_time - model_cache_timestamp < MODEL_CACHE_TTL):
        return model_cache
    
    # 重新构建缓存
    try:
        models = {}
        # 使用更高效的枚举方式
        for m in Model:
            try:
                model_name = getattr(m, "model_name", str(m))
                models[model_name] = m
            except AttributeError:
                # 处理某些模型可能没有model_name属性的情况
                models[str(m)] = m
        
        # 原子更新缓存
        model_cache = models
        model_cache_timestamp = current_time
        print(f"🔄 Refreshed model cache with {len(models)} models")
        return models
        
    except Exception as e:
        print(f"⚠️ Failed to refresh model cache: {str(e)}")
        # 返回旧缓存或空字典
        return model_cache if model_cache else {}
        
# Cookie cache management
cookie_cache = {}
cookie_cache_file = Path("./temp/.cached_cookies.json")
cookie_cache_file.parent.mkdir(parents=True, exist_ok=True)

# Enhanced client configuration with all advanced features
CLIENT_CONFIG = {
    "timeout": 30,
    "auto_close": False,
    "close_delay": 300,
    "auto_refresh": True,
    "refresh_interval": 540,  # 9 minutes - matches gemini_webapi default
    "verbose": True,
}

# Background task for client health monitoring
health_monitor_task = None
# Enhanced client management with connection pooling and health monitoring  
# 添加客户端池锁
cache_lock = None
client_pool_lock = None  # 将在startup事件中初始化

async def init_locks():
    """Initialize async locks"""
    global cache_lock, client_pool_lock
    cache_lock = asyncio.Lock()
    client_pool_lock = asyncio.Lock()
# Cookie缓存管理函数
async def load_cookie_cache():
    """Load cookie cache from file"""
    global cookie_cache
    try:
        if cache_lock is None:
            # 如果锁还未初始化，直接加载而不使用锁
            if cookie_cache_file.exists():
                with open(cookie_cache_file, 'r') as f:
                    cookie_cache = json.loads(f.read())
                print(f"📦 Loaded cookie cache with {len(cookie_cache)} entries")
            else:
                print("📦 No existing cookie cache file found")
        else:
            # 使用锁保护
            async with cache_lock:
                if cookie_cache_file.exists():
                    with open(cookie_cache_file, 'r') as f:
                        cookie_cache = json.loads(f.read())
                    print(f"📦 Loaded cookie cache with {len(cookie_cache)} entries")
                else:
                    print("📦 No existing cookie cache file found")
    except Exception as e:
        print(f"⚠️ Failed to load cookie cache: {str(e)}")
        cookie_cache = {}

async def save_cookie_cache():
    """Save cookie cache to file"""
    try:
        if cache_lock is None:
            # 如果锁还未初始化，直接保存而不使用锁
            with open(cookie_cache_file, 'w') as f:
                f.write(json.dumps(cookie_cache))
            print(f"💾 Saved cookie cache with {len(cookie_cache)} entries")
        else:
            # 使用锁保护
            async with cache_lock:
                with open(cookie_cache_file, 'w') as f:
                    f.write(json.dumps(cookie_cache))
                print(f"💾 Saved cookie cache with {len(cookie_cache)} entries")
    except Exception as e:
        print(f"⚠️ Failed to save cookie cache: {str(e)}")

def get_cached_cookies(secure_1psid: str) -> dict:
    """Get cached cookies for a given SECURE_1PSID"""
    cache_key = f"cookies_{secure_1psid[:10]}"
    cached_data = cookie_cache.get(cache_key)
    
    if cached_data and time.time() - cached_data.get("timestamp", 0) < CLIENT_COOKIE_REFRESH_THRESHOLD:
        return cached_data.get("cookies", {})
    return {}

async def cache_cookies_async(secure_1psid: str, cookies: dict):
    """Cache cookies for a given SECURE_1PSID with proper async handling"""
    cache_key = f"cookies_{secure_1psid[:10]}"
    
    if cache_lock is not None:
        async with cache_lock:
            cookie_cache[cache_key] = {
                "cookies": cookies,
                "timestamp": time.time()
            }
        # 异步保存
        await save_cookie_cache()
    else:
        # 锁未初始化时的处理
        cookie_cache[cache_key] = {
            "cookies": cookies,
            "timestamp": time.time()
        }
        # 尝试保存但不等待
        try:
            await save_cookie_cache()
        except Exception as e:
            print(f"⚠️ Failed to save cookie cache without lock: {str(e)}")

def cache_cookies(secure_1psid: str, cookies: dict):
    """Synchronous wrapper for cache_cookies_async"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(cache_cookies_async(secure_1psid, cookies))
        else:
            loop.run_until_complete(cache_cookies_async(secure_1psid, cookies))
    except Exception as e:
        print(f"⚠️ Failed to cache cookies: {str(e)}")

# 浏览器Cookie加载支持
def load_browser_cookies_fallback() -> dict:
    """Try to load cookies from browser as fallback"""
    try:
        # 尝试使用gemini_webapi内置的load_browser_cookies函数
        from gemini_webapi.utils import load_browser_cookies
        cookies = load_browser_cookies(domain_name="google.com", verbose=False)
        if cookies.get("__Secure-1PSID"):
            print("🌐 Loaded cookies from browser using gemini_webapi")
            return cookies
        return {}
    except ImportError:
        # 如果gemini_webapi不可用，回退到browser_cookie3
        if HAS_BROWSER_COOKIE3 and bc3 is not None:
            try:
                cookies = {}
                browsers = [bc3.chrome, bc3.chromium, bc3.opera, bc3.brave, bc3.edge, bc3.firefox]
                
                for browser_fn in browsers:
                    try:
                        for cookie in browser_fn(domain_name="google.com"):
                            if cookie.name in ["__Secure-1PSID", "__Secure-1PSIDTS", "NID"]:
                                cookies[cookie.name] = cookie.value
                        if cookies.get("__Secure-1PSID"):
                            print(f"🌐 Loaded cookies from {browser_fn.__name__}")
                            return cookies
                    except Exception:
                        continue
                        
                return cookies
            except Exception as e:
                print(f"⚠️ Error loading browser cookies: {str(e)}")
                return {}
        else:
            print("📦 browser_cookie3 not available, skipping browser cookie loading")
            return {}
def correct_markdown(md_text: str) -> str:
    """
    修正Markdown文本，移除Google搜索链接包装器，并根据显示文本简化目标URL。
    """
    def simplify_link_target(text_content: str) -> str:
        match_colon_num = re.match(r"([^:]+:\d+)", text_content)
        if match_colon_num:
            return match_colon_num.group(1)
        return text_content

    def replacer(match: re.Match) -> str:
        outer_open_paren = match.group(1)
        display_text = match.group(2)

        new_target_url = simplify_link_target(display_text)
        new_link_segment = f"[`{display_text}`]({new_target_url})"

        if outer_open_paren:
            return f"{outer_open_paren}{new_link_segment})"
        else:
            return new_link_segment
            
    pattern = r"(\()?\[`([^`]+?)`\]\((https://www.google.com/search\?q=)(.*?)(?<!\\)\)\)*(\))?"
    
    fixed_google_links = re.sub(pattern, replacer, md_text)
    # fix wrapped markdownlink
    pattern = r"`(\[[^\]]+\]\([^\)]+\))`"
    return re.sub(pattern, r'\1', fixed_google_links)

# 简化的Cookie刷新函数 - 移除不存在的rotate_1psidts函数
async def rotate_1psidts(cookies: dict, proxy: str = None) -> Optional[str]:
    """Refresh 1PSIDTS token by making a request to Google"""
    try:
        if not cookies.get("__Secure-1PSID"):
            print("⚠️ No __Secure-1PSID found in cookies")
            return None
            
        # 构建刷新请求
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://gemini.google.com/",
            "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()])
        }
        
        async with httpx.AsyncClient(proxy=proxy, timeout=10) as client:
            response = await client.get("https://gemini.google.com/", headers=headers)
            
            # 从响应中提取新的1PSIDTS
            for cookie in response.cookies:
                if cookie.name == "__Secure-1PSIDTS":
                    print("✅ Successfully refreshed __Secure-1PSIDTS")
                    return cookie.value
                    
        print("⚠️ Failed to find new __Secure-1PSIDTS in response")
        return None
        
    except Exception as e:
        print(f"⚠️ Error refreshing 1PSIDTS: {str(e)}")
        return None

async def monitor_client_health():
    """Background task to monitor and cleanup unhealthy clients"""
    while True:
        try:
            current_time = time.time()
            clients_to_remove = []
            cookies_to_refresh = []

            # 获取客户端快照，使用异步锁保护
            if client_pool_lock is None:
                await asyncio.sleep(CLIENT_HEALTH_CHECK_INTERVAL)
                continue
                
            async with client_pool_lock:
                clients_snapshot = dict(gemini_clients)
            
            for client_id, client in clients_snapshot.items():
                # 再次检查客户端是否仍在池中
                async with client_pool_lock:
                    if client_id not in gemini_clients:
                        continue
                    current_client = gemini_clients[client_id]
                    if current_client != client:
                        continue  # 客户端已被替换

                last_used = client_last_used.get(client_id, current_time)
                creation_time = client_creation_time.get(client_id, current_time)
                
                # Check if client has exceeded maximum lifetime or is idle
                if (current_time - last_used > CLIENT_IDLE_TIMEOUT or 
                    current_time - creation_time > CLIENT_MAX_LIFETIME or
                    not hasattr(client, 'running') or 
                    not client.running):
                    
                    clients_to_remove.append(client_id)
                    print(f"🧹 Scheduling client {client_id} for cleanup")
                
                # Check if cookies need refresh
                elif (current_time - creation_time > CLIENT_COOKIE_REFRESH_THRESHOLD and 
                      client_id not in cookies_to_refresh):
                    cookies_to_refresh.append(client_id)
            
            # Clean up unhealthy clients
            for client_id in clients_to_remove:
                await cleanup_client(client_id)
            
            # Refresh cookies for clients that need it
            for client_id in cookies_to_refresh:
                if client_id in gemini_clients:  # 再次检查客户端是否存在
                    await refresh_client_cookies(client_id)
            
            # Sleep for the next health check
            await asyncio.sleep(CLIENT_HEALTH_CHECK_INTERVAL)
            
        except Exception as e:
            print(f"❌ Error in client health monitor: {str(e)}")
            await asyncio.sleep(CLIENT_HEALTH_CHECK_INTERVAL)

# Cookie刷新函数
async def refresh_client_cookies(client_id: str):
    """Refresh cookies for a specific client"""
    if client_pool_lock is None:
        return
        
    async with client_pool_lock:
        if client_id not in gemini_clients:
            return
        client = gemini_clients[client_id]
    
    try:
        if hasattr(client, 'cookies') and client.cookies.get("__Secure-1PSID"):
            # 尝试刷新SECURE_1PSIDTS
            new_1psidts = await rotate_1psidts(client.cookies, GEMINI_PROXY)
            if new_1psidts:
                client.cookies["__Secure-1PSIDTS"] = new_1psidts
                cache_cookies(client.cookies["__Secure-1PSID"], client.cookies)
                print(f"🔄 Refreshed cookies for client {client_id}")
                
                # 重置创建时间
                client_creation_time[client_id] = time.time()
            else:
                # Cookie刷新失败，仅记录警告，不立即删除客户端
                print(f"⚠️ Cookie refresh failed for client {client_id}, will be recreated on next health check")
            
    except Exception as e:
        print(f"⚠️ Failed to refresh cookies for client {client_id}: {str(e)}")
        # Cookie刷新失败，标记客户端需要重建
        await cleanup_client(client_id)

async def cleanup_client(client_id: str):
    """Safely cleanup a specific client"""
    if client_pool_lock is None:
        return
        
    client = None
    
    async with client_pool_lock:
        if client_id not in gemini_clients:
            return
            
        try:
            client = gemini_clients[client_id]
            
            # 先从字典中移除，避免并发访问
            del gemini_clients[client_id]
            
            # 清理相关的时间戳记录
            client_last_used.pop(client_id, None)
            client_creation_time.pop(client_id, None)
            
            print(f"🗑️ Client {client_id} removed from pool")
            
        except Exception as e:
            print(f"⚠️ Error removing client {client_id} from pool: {str(e)}")
            # 确保即使出错，客户端也从池中移除
            gemini_clients.pop(client_id, None)
            client_last_used.pop(client_id, None)
            client_creation_time.pop(client_id, None)
    
    # 在锁外关闭客户端，避免死锁
    if client and hasattr(client, 'close'):
        try:
            await client.close()
            print(f"✅ Client {client_id} closed successfully")
        except Exception as e:
            print(f"⚠️ Error closing client {client_id}: {str(e)}")


@app.on_event("startup")
async def startup():
    global health_monitor_task
    
    print("🚀 Starting Enhanced Gemini API FastAPI Server v0.4.0")
    # 初始化异步锁
    await init_locks()
    # Load cookie cache
    await load_cookie_cache()
    
    # Validate credentials with enhanced logic
    credentials_found = False
    if SECURE_1PSID:
        print(f"✅ Credentials found. SECURE_1PSID starts with: {SECURE_1PSID[:10]}...")
        if SECURE_1PSIDTS:
            print(f"✅ SECURE_1PSIDTS starts with: {SECURE_1PSIDTS[:10]}...")
        credentials_found = True
    elif API_KEY:
        print(f"✅ API_KEY found. API_KEY starts with: {API_KEY[:10]}...")
        credentials_found = True
    else:
        # Try to load from browser as fallback
        browser_cookies = load_browser_cookies_fallback()
        if browser_cookies.get("__Secure-1PSID"):
            print("✅ Found cookies in browser, will use as fallback")
            credentials_found = True
    
    if not credentials_found:
        print("⚠️ No credentials found. Server will attempt to use browser cookies if available.")
    
    # Start background health monitor
    health_monitor_task = asyncio.create_task(monitor_client_health())
    print("🏥 Client health monitor started")
    
    # Pre-warm one client with better error handling
    try:
        await get_gemini_client()
        print("🔥 Pre-warmed initial client successfully")
    except Exception as e:
        print(f"⚠️ Failed to pre-warm client: {str(e)}")

@app.on_event("shutdown")
async def shutdown():
    global health_monitor_task
    
    # Save cookie cache before shutdown
    await save_cookie_cache()
    
    # Cancel health monitor
    if health_monitor_task:
        health_monitor_task.cancel()
        try:
            await health_monitor_task
        except asyncio.CancelledError:
            pass
    
    # Cleanup all clients
    cleanup_tasks = []
    for client_id in list(gemini_clients.keys()):
        cleanup_tasks.append(cleanup_client(client_id))
    
    if cleanup_tasks:
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    
    print("👋 Enhanced Gemini server shutdown complete")

# Pydantic models for API requests and responses
class Message(BaseModel):
    role: str
    content: Union[str, List[dict]]

class ChatRequest(BaseModel):
    model: str = "gpt-3.5-turbo"
    messages: List[Message]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False

class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[dict]

class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "google"


# Authentication dependency
def verify_api_key(authorization: str = Header(None)):
    if API_KEY:
        if not authorization or authorization != f"Bearer {API_KEY}":
            raise HTTPException(status_code=401, detail="Invalid API key")

# Enhanced error handler middleware with better error classification
@app.middleware("http")
async def error_handler_middleware(request: Request, call_next) -> Response:
    try:
        response = await call_next(request)
        return response
    except AuthError as e:
        print(f"Authentication error: {str(e)}")
        return JSONResponse(
            status_code=401, 
            content={"error": {"message": f"Authentication failed: {str(e)}", "type": "auth_error"}}
        )
    except UsageLimitExceeded as e:
        print(f"Usage limit exceeded: {str(e)}")
        return JSONResponse(
            status_code=429, 
            content={"error": {"message": str(e), "type": "usage_limit_exceeded"}}
        )
    except ModelInvalid as e:
        print(f"Model invalid: {str(e)}")
        return JSONResponse(
            status_code=400, 
            content={"error": {"message": str(e), "type": "model_invalid"}}
        )
    except TemporarilyBlocked as e:
        print(f"Temporarily blocked: {str(e)}")
        return JSONResponse(
            status_code=429, 
            content={"error": {"message": str(e), "type": "temporarily_blocked"}}
        )
    except TimeoutError as e:
        print(f"Request timeout: {str(e)}")
        return JSONResponse(
            status_code=408, 
            content={"error": {"message": str(e), "type": "timeout_error"}}
        )
    except APIError as e:
        print(f"API error: {str(e)}")
        return JSONResponse(
            status_code=502, 
            content={"error": {"message": str(e), "type": "api_error"}}
        )
    except Exception as e:
        print(f"Unexpected error: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500, 
            content={"error": {"message": str(e), "type": "internal_server_error"}}
        )

# Health check endpoint with enhanced diagnostics
@app.get("/health")
async def health():
    """Enhanced health check endpoint with client pool status"""
    healthy_clients = 0
    total_clients = len(gemini_clients)
    cookie_cache_size = len(cookie_cache)
    
    for client in gemini_clients.values():
        if hasattr(client, 'running') and client.running:
            healthy_clients += 1
    
    return {
        "status": "healthy", 
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "version": "0.4.0",
        "client_pool": {
            "total": total_clients,
            "healthy": healthy_clients,
            "max_size": client_pool_size
        },
        "cookie_cache": {
            "size": cookie_cache_size,
            "cache_file_exists": cookie_cache_file.exists()
        }
    }

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Enhanced Gemini API FastAPI Server is running",
        "version": "0.4.0",
        "features": [
            "client_pooling", 
            "auto_refresh", 
            "health_monitoring", 
            "advanced_error_handling", 
            "improved_cookie_handling",
            "cookie_caching",
            "browser_cookie_fallback",
            "smart_cookie_refresh",
            "markdown_link_correction",
            "thinking_content_extraction",
            "cors_support"
        ],
    }

# Get list of available models - Enhanced with dynamic model discovery
@app.get("/v1/models")
async def list_models():
    """返回动态获取的gemini_webapi中声明的模型列表，同时保留OpenAI兼容性"""
    now = int(datetime.now(tz=timezone.utc).timestamp())
    
    # 动态获取所有Gemini模型
    gemini_models = []
    try:
        for m in Model:
            model_name = m.model_name if hasattr(m, "model_name") else str(m)
            gemini_models.append({
                "id": model_name,
                "object": "model",
                "created": now,
                "owned_by": "google-gemini-web",
            })
    except Exception as e:
        print(f"⚠️ Failed to get dynamic models, using fallback: {str(e)}")
    
    # OpenAI兼容性模型（保持原有功能）
    openai_compatible_models = [
        {"id": "gpt-4", "object": "model", "created": now, "owned_by": "google-gemini"},
        {"id": "gpt-4-turbo", "object": "model", "created": now, "owned_by": "google-gemini"}, 
        {"id": "gpt-3.5-turbo", "object": "model", "created": now, "owned_by": "google-gemini"},
    ]
    
    # 合并所有模型，去重
    all_models = openai_compatible_models + gemini_models
    
    # 去重处理（基于id）
    seen_ids = set()
    unique_models = []
    for model in all_models:
        if model["id"] not in seen_ids:
            seen_ids.add(model["id"])
            unique_models.append(model)
    
    return {
        "object": "list",
        "data": unique_models
    }

# Enhanced model mapping with better error handling and fixed mappings
def map_openai_to_gemini_model(openai_model_name: str) -> Model:
    """Map OpenAI model names to Gemini models with improved logic and dynamic model support"""
    
    # 动态构建直接映射表（项目Z的优势功能）
    direct_mappings = {}
    try:
        for m in Model:
            model_name = m.model_name if hasattr(m, "model_name") else str(m)
            direct_mappings[model_name] = m
    except Exception as e:
        print(f"⚠️ Failed to build dynamic mappings: {str(e)}")
    
    # 静态映射作为备份（保持原有功能）
    static_direct_mappings = {
        "gemini-2.5-pro": Model.G_2_5_PRO,
        "gemini-2.5-flash": Model.G_2_5_FLASH,
        "gemini-2.0-flash": Model.G_2_0_FLASH,
        "gemini-2.0-flash-thinking": Model.G_2_0_FLASH_THINKING,
    }
    
    # 合并动态和静态映射
    combined_direct_mappings = {**static_direct_mappings, **direct_mappings}
    
    # Check direct mappings first (现在支持动态模型如gemini-2.5-advanced)
    if openai_model_name in combined_direct_mappings:
        print(f"✅ Found direct model mapping for '{openai_model_name}'")
        return combined_direct_mappings[openai_model_name]
    
    # OpenAI to Gemini model mappings for compatibility（保持原有功能）
    openai_mappings = {
        "gpt-4": Model.G_2_5_PRO,           # Map GPT-4 to most capable Gemini model
        "gpt-4-turbo": Model.G_2_5_PRO,     # Map GPT-4 Turbo to Gemini 2.5 Pro  
        "gpt-4o": Model.G_2_5_PRO,          # Map GPT-4o to Gemini 2.5 Pro
        "gpt-3.5-turbo": Model.G_2_5_FLASH, # Map GPT-3.5 Turbo to Gemini 2.5 Flash
        "gpt-3.5": Model.G_2_5_FLASH,       # Map GPT-3.5 to Gemini 2.5 Flash
    }
    
    # Check OpenAI mappings
    if openai_model_name in openai_mappings:
        return openai_mappings[openai_model_name]
    
    # 增强的动态关键词匹配（项目Z的功能 + 原有逻辑）
    model_name_lower = openai_model_name.lower()
    
    # 尝试在所有可用模型中进行智能匹配
    best_match = None
    try:
        for m in Model:
            model_name = (m.model_name if hasattr(m, "model_name") else str(m)).lower()
            
            # 精确关键词匹配
            if "advanced" in model_name_lower and "advanced" in model_name:
                best_match = m
                print(f"✅ Found advanced model match: {model_name}")
                break
            elif "pro" in model_name_lower and "pro" in model_name:
                best_match = m
            elif "flash" in model_name_lower and "flash" in model_name:
                if best_match is None:  # 只在没找到更好匹配时使用flash
                    best_match = m
            elif "thinking" in model_name_lower and "thinking" in model_name:
                best_match = m
                break  # thinking模型优先级高
        
        if best_match:
            print(f"✅ Found dynamic model match for '{openai_model_name}': {best_match}")
            return best_match
            
    except Exception as e:
        print(f"⚠️ Dynamic model matching failed: {str(e)}")
    
    # 原有的静态回退逻辑（保持原有功能）
    if "pro" in model_name_lower or "gpt-4" in model_name_lower:
        return Model.G_2_5_PRO
    elif "flash" in model_name_lower or "gpt-3.5" in model_name_lower or "turbo" in model_name_lower:
        return Model.G_2_5_FLASH
    elif "thinking" in model_name_lower:
        return Model.G_2_0_FLASH_THINKING
        
    # Default to the latest flash model
    print(f"⚠️ Unknown model '{openai_model_name}', defaulting to gemini-2.5-flash")
    return Model.G_2_5_FLASH

# Enhanced file processing with better security and error handling
def prepare_conversation(messages: List[Message]) -> tuple[str, List[str]]:
    if not messages:
        raise ValueError("Messages cannot be empty")
    
    if len(messages) > 100:  # 限制消息数量
        raise ValueError("Too many messages (max 100)")
    
    conversation_parts = []
    temp_files = []
    
    for i, message in enumerate(messages):
        # 更严格的消息验证
        if not isinstance(message, Message):
            print(f"⚠️ Skipping invalid message at index {i}: not a Message instance")
            continue
            
        if not hasattr(message, 'role') or not hasattr(message, 'content'):
            print(f"⚠️ Skipping invalid message at index {i}: missing role or content")
            continue
            
        if message.role not in ["user", "assistant", "system"]:
            print(f"⚠️ Skipping message at index {i}: invalid role '{message.role}'")
            continue
            
        if message.role in ["user", "assistant"]:
            if isinstance(message.content, str):
                conversation_parts.append(message.content)
            elif isinstance(message.content, list):
                text_parts = []
                for content_part in message.content:
                    if content_part.get("type") == "text":
                        text_parts.append(content_part.get("text", ""))
                    elif content_part.get("type") == "image_url":
                        # Enhanced image handling with better validation
                        image_url = content_part.get("image_url", {}).get("url", "")
                        if image_url.startswith("data:image"):
                            try:
                                # Validate image format
                                if not re.match(r"data:image/(png|jpeg|jpg|gif|webp);base64,", image_url):
                                    print("⚠️ Unsupported image format, skipping")
                                    continue
                                
                                header, data = image_url.split(",", 1)
                                image_data = base64.b64decode(data)
                                
                                # Validate image size (max 10MB)
                                if len(image_data) > 10 * 1024 * 1024:
                                    print("⚠️ Image too large (>10MB), skipping")
                                    continue
                                # Validate minimum image size  
                                if len(image_data) < 100:
                                    print("⚠️ Image too small, likely invalid, skipping")
                                    continue
                                # Extract image format from header
                                image_format = re.search(r"image/(\w+)", header)
                                suffix = f".{image_format.group(1)}" if image_format else ".png"

                                # Create temporary file with proper extension
                                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="gemini_img_") as temp_file:
                                    temp_file.write(image_data)
                                    temp_file.flush()  # 确保数据写入磁盘
                                    temp_files.append(temp_file.name)
                                    print(f"📷 Processed image: {len(image_data)} bytes -> {temp_file.name}")
                            except Exception as e:
                                print(f"⚠️ Failed to process image: {str(e)}")
                                continue

                if text_parts:
                    conversation_parts.append(" ".join(text_parts))
    
    # Join all conversation parts
    conversation = "\n".join(conversation_parts)
    return conversation, temp_files

async def get_gemini_client() -> GeminiClient:
    """Get a healthy client from the pool or create a new one"""
    async with client_pool_lock:
        current_time = time.time()
        
        # Find a healthy client
        for client_id, client in gemini_clients.items():
            if (hasattr(client, 'running') and client.running and 
                client_last_used.get(client_id, 0) + CLIENT_MAX_LIFETIME > current_time and
                client_creation_time.get(client_id, 0) + CLIENT_MAX_LIFETIME > current_time):
                
                client_last_used[client_id] = current_time
                print(f"♻️ Reusing healthy client {client_id}")
                return client

        # Create new client if pool is not full
        if len(gemini_clients) < client_pool_size:
            client_id = f"client_{int(current_time)}_{len(gemini_clients)}"
            client = await create_new_client(client_id)
            return client
        
        # If pool is full, replace the oldest client
        oldest_client_id = min(client_last_used.keys(), key=client_last_used.get, default=None)
        if oldest_client_id:
            await cleanup_client(oldest_client_id)
        
        # Create new client
        client_id = f"client_{int(current_time)}"
        client = await create_new_client(client_id)
        return client

async def create_new_client(client_id: str) -> GeminiClient:
    """Create a new Gemini client with enhanced configuration and better cookie handling"""
    try:
        cookies_to_use = {}
        
        # Try environment variables first
        if SECURE_1PSID:
            cookies_to_use["__Secure-1PSID"] = SECURE_1PSID
            if SECURE_1PSIDTS:
                cookies_to_use["__Secure-1PSIDTS"] = SECURE_1PSIDTS
            
            # Try to get cached cookies for this PSID
            cached_cookies = get_cached_cookies(SECURE_1PSID)
            if cached_cookies:
                cookies_to_use.update(cached_cookies)
                print(f"📦 Using cached cookies for client {client_id}")
        else:
            # Fallback to browser cookies
            browser_cookies = load_browser_cookies_fallback()
            if browser_cookies.get("__Secure-1PSID"):
                cookies_to_use = browser_cookies
                print(f"🌐 Using browser cookies for client {client_id}")
        
        # Create client with enhanced cookie handling
        if cookies_to_use.get("__Secure-1PSID"):
            client = GeminiClient(
                secure_1psid=cookies_to_use.get("__Secure-1PSID"),
                secure_1psidts=cookies_to_use.get("__Secure-1PSIDTS"),
                proxy=GEMINI_PROXY or None
            )
        else:
            # Try with no explicit cookies (gemini_webapi will auto-load browser cookies)
            client = GeminiClient(proxy=GEMINI_PROXY or None)
            
        # Initialize with enhanced configuration
        await client.init(**CLIENT_CONFIG)
        
        # Cache the cookies after successful initialization
        if hasattr(client, 'cookies') and client.cookies.get("__Secure-1PSID"):
            cache_cookies(client.cookies["__Secure-1PSID"], client.cookies)
        
        gemini_clients[client_id] = client
        client_last_used[client_id] = time.time()
        client_creation_time[client_id] = time.time()
        
        print(f"✅ New client {client_id} created and initialized successfully")
        return client
        
    except AuthError as e:
        print(f"❌ Authentication failed for client {client_id}: {str(e)}")
        raise HTTPException(
            status_code=401, 
            detail="Authentication failed. Please check your cookies. SECURE_1PSIDTS may have expired or browser login required."
        )
    except Exception as e:
        print(f"❌ Failed to create client {client_id}: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to initialize Gemini client: {str(e)}"
        )

# Enhanced chat completions endpoint with better error handling and retry logic

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, _: str = Depends(verify_api_key)):

    temp_files = []
    client = None
    max_retries = 3
    
    try:
        # 准备对话内容
        conversation, temp_files = prepare_conversation(request.messages)
        model = map_openai_to_gemini_model(request.model)
        
        print(f"📝 Prepared conversation: {conversation[:200]}...")
        
        # 重试逻辑 - 使用不同的客户端进行重试
        for attempt in range(max_retries):
            try:
                client = await get_gemini_client()
                print(f"🚀 Sending request to Gemini (attempt {attempt + 1})")
                
                # 生成响应
                if temp_files:
                    response = await client.generate_content(
                        prompt=conversation, 
                        files=temp_files,
                        model=model
                    )
                else:
                    response = await client.generate_content(conversation, model=model)
                
                # 成功获取响应，跳出重试循环
                break
                
            except Exception as e:
                print(f"❌ Attempt {attempt + 1} failed: {str(e)}")
                
                # 如果是认证错误或者是最后一次尝试，直接抛出异常
                if isinstance(e, AuthError) or attempt == max_retries - 1:
                    raise e
                
                # 清理有问题的客户端
                if client:
                    for client_id, stored_client in list(gemini_clients.items()):
                        if stored_client is client:
                            await cleanup_client(client_id)
                            break
                
                # 短暂延迟后重试，使用指数退避
                await asyncio.sleep(min(2 ** attempt, 5))  # 指数退避，最大5秒
        
        # 处理响应内容 - 新增思考内容提取
        reply_text = ""
        
        # 新增：提取思考内容
        if hasattr(response, "thoughts"):
            reply_text += f"<think>{response.thoughts}</think>"
            
        if hasattr(response, "text"):
            reply_text += response.text
        else:
            reply_text += str(response)
            
        # 新增：字符转义处理和markdown修正
        reply_text = reply_text.replace("&lt;","<").replace("\\<","<").replace("\\_","_").replace("\\>",">")
        reply_text = correct_markdown(reply_text)
        
        if not reply_text.strip():
            reply_text = "Empty response received from Gemini. Please try again."

        # 流式响应处理
        if request.stream:
            async def generate_stream():
                # 流式输出文本
                for char in reply_text:
                    chunk = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": request.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": char},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                    await asyncio.sleep(0.01)  # 控制输出速度
                
                # 结束标记
                final_chunk = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk", 
                    "created": int(time.time()),
                    "model": request.model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }]
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"
            
            return StreamingResponse(generate_stream(), media_type="text/plain")
        else:
            # 非流式响应
            return ChatResponse(
                id=f"chatcmpl-{int(time.time())}",
                created=int(time.time()),
                model=request.model,
                choices=[{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": reply_text
                    },
                    "finish_reason": "stop"
                }]
            )
    
    except Exception as e:
        print(f"❌ Error generating completion: {str(e)}", exc_info=True)
        raise
    finally:
        # 清理临时文件
        await cleanup_temp_files(temp_files)

async def cleanup_temp_files(temp_files: List[str]):
    """Clean up temporary files safely"""
    if not temp_files:
        return
    
    cleaned_files = []
    failed_cleanups = []
    
    for temp_file in temp_files:
        try:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
                cleaned_files.append(temp_file)
        except Exception as e:
            failed_cleanups.append((temp_file, str(e)))
            print(f"⚠️ Failed to delete temp file {temp_file}: {str(e)}")
    
    if cleaned_files:
        print(f"🧹 Successfully cleaned up {len(cleaned_files)} temporary files")
        
    if failed_cleanups:
        print(f"⚠️ Failed to clean up {len(failed_cleanups)} temporary files")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")
