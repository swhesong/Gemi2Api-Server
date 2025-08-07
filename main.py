import asyncio
import base64
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import List, Optional, Union
from pathlib import Path
import re

import orjson as json
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from gemini_webapi import GeminiClient
from gemini_webapi.constants import Model
from gemini_webapi.exceptions import AuthError, APIError, TimeoutError, UsageLimitExceeded, ModelInvalid, TemporarilyBlocked

# Environment variables
SECURE_1PSID = os.getenv("SECURE_1PSID")
SECURE_1PSIDTS = os.getenv("SECURE_1PSIDTS")  
API_KEY = os.getenv("API_KEY")
GEMINI_PROXY = os.getenv("GEMINI_PROXY")

app = FastAPI(title="Enhanced Gemini API FastAPI Server", version="0.4.0")

# Enhanced client management with connection pooling
gemini_clients = {}
client_pool_size = 3
client_last_used = {}
client_creation_time = {}  # 新增：追踪客户端创建时间
CLIENT_IDLE_TIMEOUT = 900  # 15 minutes
CLIENT_MAX_LIFETIME = 1800  # 30 minutes maximum lifetime
CLIENT_HEALTH_CHECK_INTERVAL = 60  # 1 minute health check
CLIENT_COOKIE_REFRESH_THRESHOLD = 540  # 9 minutes - cookie refresh threshold

# Cookie cache management - 新增
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

# 新增：Cookie缓存管理函数
async def load_cookie_cache():
    """Load cookie cache from file"""
    global cookie_cache
    try:
        if cookie_cache_file.exists():
            with open(cookie_cache_file, 'r') as f:
                cookie_cache = json.loads(f.read())
            print(f"📦 Loaded cookie cache with {len(cookie_cache)} entries")
    except Exception as e:
        print(f"⚠️ Failed to load cookie cache: {str(e)}")
        cookie_cache = {}

async def save_cookie_cache():
    """Save cookie cache to file"""
    try:
        with open(cookie_cache_file, 'w') as f:
            f.write(json.dumps(cookie_cache).decode())
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

def cache_cookies(secure_1psid: str, cookies: dict):
    """Cache cookies for a given SECURE_1PSID"""
    cache_key = f"cookies_{secure_1psid[:10]}"
    cookie_cache[cache_key] = {
        "cookies": cookies,
        "timestamp": time.time()
    }
    # 异步保存，不阻塞主流程
    asyncio.create_task(save_cookie_cache())

# 新增：浏览器Cookie加载支持
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
        try:
            import browser_cookie3 as bc3
            
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
        except ImportError:
            print("📦 Neither gemini_webapi.utils nor browser_cookie3 available, skipping browser cookie loading")
            return {}
    except Exception as e:
        print(f"⚠️ Error loading browser cookies: {str(e)}")
        return {}

async def monitor_client_health():
    """Background task to monitor and cleanup unhealthy clients"""
    while True:
        try:
            current_time = time.time()
            clients_to_remove = []
            cookies_to_refresh = []
            
            for client_id, client in gemini_clients.items():
                last_used = client_last_used.get(client_id, current_time)
                creation_time = client_creation_time.get(client_id, current_time)
                
                # Check if client has exceeded maximum lifetime or is idle
                if (current_time - last_used > CLIENT_IDLE_TIMEOUT or 
                    current_time - creation_time > CLIENT_MAX_LIFETIME or
                    not hasattr(client, 'running') or 
                    not client.running):
                    
                    clients_to_remove.append(client_id)
                    print(f"🧹 Scheduling client {client_id} for cleanup")
                
                # Check if cookies need refresh - 新增逻辑
                elif (current_time - creation_time > CLIENT_COOKIE_REFRESH_THRESHOLD and 
                      client_id not in cookies_to_refresh):
                    cookies_to_refresh.append(client_id)
            
            # Clean up unhealthy clients
            for client_id in clients_to_remove:
                await cleanup_client(client_id)
            
            # Refresh cookies for clients that need it - 新增
            for client_id in cookies_to_refresh:
                await refresh_client_cookies(client_id)
            
            # Sleep for the next health check
            await asyncio.sleep(CLIENT_HEALTH_CHECK_INTERVAL)
            
        except Exception as e:
            print(f"❌ Error in client health monitor: {str(e)}")
            await asyncio.sleep(CLIENT_HEALTH_CHECK_INTERVAL)

# 新增：Cookie刷新函数
async def refresh_client_cookies(client_id: str):
    """Refresh cookies for a specific client"""
    if client_id not in gemini_clients:
        return
    
    try:
        client = gemini_clients[client_id]
        if hasattr(client, 'cookies') and client.cookies.get("__Secure-1PSID"):
            # 尝试刷新SECURE_1PSIDTS
            # from gemini_webapi.utils import rotate_1psidts
            
            new_1psidts = await rotate_1psidts(client.cookies, GEMINI_PROXY)
            if new_1psidts:
                client.cookies["__Secure-1PSIDTS"] = new_1psidts
                cache_cookies(client.cookies["__Secure-1PSID"], client.cookies)
                print(f"🔄 Refreshed cookies for client {client_id}")
                
                # 重置创建时间
                client_creation_time[client_id] = time.time()
            
    except Exception as e:
        print(f"⚠️ Failed to refresh cookies for client {client_id}: {str(e)}")
        # Cookie刷新失败，标记客户端需要重建
        await cleanup_client(client_id)

async def cleanup_client(client_id: str):
    """Safely cleanup a specific client"""
    if client_id in gemini_clients:
        try:
            client = gemini_clients[client_id]
            await client.close()
            del gemini_clients[client_id]
            if client_id in client_last_used:
                del client_last_used[client_id]
            if client_id in client_creation_time:  # 新增
                del client_creation_time[client_id]
            print(f"🗑️ Client {client_id} cleaned up successfully")
        except Exception as e:
            print(f"⚠️ Error cleaning up client {client_id}: {str(e)}")

@app.on_event("startup")
async def startup():
    global health_monitor_task
    
    print("🚀 Starting Enhanced Gemini API FastAPI Server v0.4.0")
    
    # Load cookie cache - 新增
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
    
    # Save cookie cache before shutdown - 新增
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
def verify_api_key(api_key: str = None):
    if API_KEY:
        if not api_key or api_key != f"Bearer {API_KEY}":
            raise HTTPException(status_code=401, detail="Invalid API key")

# Enhanced error handler middleware with better error classification
@app.middleware("http")
async def error_handler_middleware(request, call_next):
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
            "smart_cookie_refresh"
        ],
    }

# Get list of available models
@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "gpt-4", "object": "model", "created": 0, "owned_by": "google-gemini"},
            {"id": "gpt-4-turbo", "object": "model", "created": 0, "owned_by": "google-gemini"}, 
            {"id": "gpt-3.5-turbo", "object": "model", "created": 0, "owned_by": "google-gemini"},
            {"id": "gemini-2.5-flash", "object": "model", "created": 0, "owned_by": "google-gemini"},
            {"id": "gemini-2.5-pro", "object": "model", "created": 0, "owned_by": "google-gemini"},
        ]
    }

# Enhanced model mapping with better error handling and fixed mappings
def map_openai_to_gemini_model(openai_model_name: str) -> Model:
    """Map OpenAI model names to Gemini models with improved logic"""
    
    # Direct model name mappings (most reliable)
    direct_mappings = {
        "gemini-2.5-pro": Model.G_2_5_PRO,
        "gemini-2.5-flash": Model.G_2_5_FLASH,
        "gemini-2.0-flash": Model.G_2_0_FLASH,
        "gemini-2.0-flash-thinking": Model.G_2_0_FLASH_THINKING,
    }
    
    # Check direct mappings first
    if openai_model_name in direct_mappings:
        return direct_mappings[openai_model_name]
    
    # OpenAI to Gemini model mappings for compatibility
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
    
    # Fallback: partial matching for flexibility
    model_name_lower = openai_model_name.lower()
    
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
    conversation_parts = []
    temp_files = []
    
    for message in messages:
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
                                
                                # Extract image format from header
                                image_format = re.search(r"image/(\w+)", header)
                                suffix = f".{image_format.group(1)}" if image_format else ".png"
                                
                                # Create temporary file with proper extension
                                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="gemini_img_") as temp_file:
                                    temp_file.write(image_data)
                                    temp_files.append(temp_file.name)
                                    print(f"📷 Processed image: {len(image_data)} bytes -> {temp_file.name}")
                                    
                            except Exception as e:
                                print(f"⚠️ Failed to process image: {str(e)}")
                
                if text_parts:
                    conversation_parts.append(" ".join(text_parts))
    
    # Join all conversation parts
    conversation = "\n".join(conversation_parts)
    return conversation, temp_files

# Enhanced client management with connection pooling and health monitoring  
async def get_gemini_client() -> GeminiClient:
    """Get a healthy client from the pool or create a new one"""
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
        client_creation_time[client_id] = time.time()  # 新增
        
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
async def chat_completions(request: ChatRequest, api_key: str = Depends(verify_api_key)):
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
       
       # 处理响应内容
       reply_text = response.text if response and response.text else ""
       
       # 字符转义处理和markdown修正
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
                   yield f"data: {json.dumps(chunk).decode()}\n\n"
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
               yield f"data: {json.dumps(final_chunk).decode()}\n\n"
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
