import asyncio
import base64
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import List, Optional, Union

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

app = FastAPI(title="Enhanced Gemini API FastAPI Server", version="0.3.1")

# Enhanced client management with connection pooling
gemini_clients = {}
client_pool_size = 3
client_last_used = {}
CLIENT_IDLE_TIMEOUT = 900  # 15 minutes
CLIENT_MAX_LIFETIME = 1800  # 30 minutes maximum lifetime
CLIENT_HEALTH_CHECK_INTERVAL = 60  # 1 minute health check

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

async def monitor_client_health():
    """Background task to monitor and cleanup unhealthy clients"""
    while True:
        try:
            current_time = time.time()
            clients_to_remove = []
            
            for client_id, client in gemini_clients.items():
                last_used = client_last_used.get(client_id, current_time)
                
                # Check if client has exceeded maximum lifetime or is idle
                if (current_time - last_used > CLIENT_IDLE_TIMEOUT or 
                    not hasattr(client, 'running') or 
                    not client.running):
                    
                    clients_to_remove.append(client_id)
                    print(f"🧹 Scheduling client {client_id} for cleanup")
            
            # Clean up unhealthy clients
            for client_id in clients_to_remove:
                await cleanup_client(client_id)
            
            # Sleep for the next health check
            await asyncio.sleep(CLIENT_HEALTH_CHECK_INTERVAL)
            
        except Exception as e:
            print(f"❌ Error in client health monitor: {str(e)}")
            await asyncio.sleep(CLIENT_HEALTH_CHECK_INTERVAL)

async def cleanup_client(client_id: str):
    """Safely cleanup a specific client"""
    if client_id in gemini_clients:
        try:
            client = gemini_clients[client_id]
            await client.close()
            del gemini_clients[client_id]
            if client_id in client_last_used:
                del client_last_used[client_id]
            print(f"🗑️ Client {client_id} cleaned up successfully")
        except Exception as e:
            print(f"⚠️ Error cleaning up client {client_id}: {str(e)}")

@app.on_event("startup")
async def startup():
    global health_monitor_task
    
    print("🚀 Starting Enhanced Gemini API FastAPI Server v0.3.1")
    # Validate credentials
    if SECURE_1PSID:
        print(f"✅ Credentials found. SECURE_1PSID starts with: {SECURE_1PSID[:10]}...")
        if SECURE_1PSIDTS:
            print(f"✅ SECURE_1PSIDTS starts with: {SECURE_1PSIDTS[:10]}...")
    if API_KEY:
        print(f"✅ API_KEY found. API_KEY starts with: {API_KEY[:10]}...")
    
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
        # If API_KEY is not set in environment, skip validation (for development)

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
    
    for client in gemini_clients.values():
        if hasattr(client, 'running') and client.running:
            healthy_clients += 1
    
    return {
        "status": "healthy", 
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "version": "0.3.1",
        "client_pool": {
            "total": total_clients,
            "healthy": healthy_clients,
            "max_size": client_pool_size
        }
    }

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Enhanced Gemini API FastAPI Server is running",
        "version": "0.3.1",
        "features": ["client_pooling", "auto_refresh", "health_monitoring", "advanced_error_handling", "improved_cookie_handling"],
    }

# Get list of available models
@app.get("/v1/models")
async def list_models():
    # Return available Gemini models mapped to OpenAI-style format
    return {
        "object": "list",
        "data": [
            {"id": "gpt-4", "object": "model", "created": 0, "owned_by": "google-gemini"},
            {"id": "gpt-4-turbo", "object": "model", "created": 0, "owned_by": "google-gemini"}, 
            {"id": "gpt-3.5-turbo", "object": "model", "created": 0, "owned_by": "google-gemini"},
            {"id": "gemini-2.5-flash", "object": "model", "created": 0, "owned_by": "google-gemini"},
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

# Prepare conversation history from OpenAI messages format
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
                        # Handle image - 使用 tempfile.NamedTemporaryFile 更稳定的方式
                        image_url = content_part.get("image_url", {}).get("url", "")
                        if image_url.startswith("data:image"):
                            # Process base64 encoded image
                            try:
                                header, data = image_url.split(",", 1)
                                # Extract the base64 part
                                image_data = base64.b64decode(data)
                                # Create temporary file to hold the image
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                                    temp_file.write(image_data)
                                    temp_files.append(temp_file.name)
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
            client_last_used.get(client_id, 0) + CLIENT_MAX_LIFETIME > current_time):
            
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
        if SECURE_1PSID or SECURE_1PSIDTS:
            client = GeminiClient(
                secure_1psid=SECURE_1PSID or None,
                secure_1psidts=SECURE_1PSIDTS or None,
                proxy=GEMINI_PROXY or None
            )
        else:
            # Try to use browser cookies as fallback
            client = GeminiClient(proxy=GEMINI_PROXY or None)
            
        # Initialize with enhanced configuration for better cookie handling
        await client.init(**CLIENT_CONFIG)
        
        gemini_clients[client_id] = client
        client_last_used[client_id] = time.time()
        
        print(f"✅ New client {client_id} created and initialized successfully")
        return client
        
    except AuthError as e:
        print(f"❌ Authentication failed for client {client_id}: {str(e)}")
        raise HTTPException(
            status_code=401, 
            detail="Authentication failed. Please check your cookies. SECURE_1PSIDTS may have expired."
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
