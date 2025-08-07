import asyncio
import json
from datetime import datetime, timezone
import os
import base64
import re
import tempfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
import time
import uuid
import logging

# 添加 dotenv 支持
from dotenv import load_dotenv

from gemini_webapi import GeminiClient, set_log_level, logger
from gemini_webapi.constants import Model
from gemini_webapi.exceptions import AuthError, APIError, TimeoutError

# 加载 .env 文件
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
set_log_level("INFO")

app = FastAPI(title="Gemini API FastAPI Server", version="0.2.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global client with better management
gemini_client = None
client_last_used = None
CLIENT_IDLE_TIMEOUT = 300  # 5 minutes idle timeout

# Authentication credentials - 支持多种环境变量格式
SECURE_1PSID = os.environ.get("SECURE_1PSID") or os.environ.get("CONFIG_GEMINI__CLIENTS__0__SECURE_1PSID", "")
SECURE_1PSIDTS = os.environ.get("SECURE_1PSIDTS") or os.environ.get("CONFIG_GEMINI__CLIENTS__0__SECURE_1PSIDTS", "")
API_KEY = os.environ.get("API_KEY") or os.environ.get("CONFIG_SERVER__API_KEY", "")

# Proxy support
GEMINI_PROXY = os.environ.get("GEMINI_PROXY", "")

# Client configuration - 使用完整的配置选项
CLIENT_CONFIG = {
    "timeout": 300,
    "auto_close": True,
    "close_delay": CLIENT_IDLE_TIMEOUT,
    "auto_refresh": True,
    "refresh_interval": 540,  # 9 minutes
}

# 如果有代理配置，添加到客户端配置中
if GEMINI_PROXY:
    CLIENT_CONFIG["proxy"] = GEMINI_PROXY

# 启动时的配置检查和优化
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting Gemini API FastAPI Server v0.2.0")
    
    if not SECURE_1PSID:
        if not SECURE_1PSIDTS:
            logger.warning("⚠️ No Gemini credentials provided. Will attempt to use browser cookies if available.")
        else:
            logger.warning("⚠️ Only SECURE_1PSIDTS provided. SECURE_1PSID is required.")
    else:
        logger.info(f"✅ Credentials found. SECURE_1PSID starts with: {SECURE_1PSID[:5]}...")
        if SECURE_1PSIDTS:
            logger.info(f"✅ SECURE_1PSIDTS starts with: {SECURE_1PSIDTS[:5]}...")

    if not API_KEY:
        logger.warning("⚠️ API_KEY is not set or empty! API authentication will not work.")
        logger.warning("Make sure API_KEY is correctly set in your .env file or environment.")
    else:
        logger.info(f"✅ API_KEY found. API_KEY starts with: {API_KEY[:5]}...")

    if GEMINI_PROXY:
        logger.info(f"🌐 Proxy configured: {GEMINI_PROXY}")

@app.on_event("shutdown")
async def shutdown_event():
    global gemini_client
    if gemini_client:
        try:
            await gemini_client.close()
            logger.info("👋 Gemini client closed on shutdown")
        except Exception as e:
            logger.warning(f"Error during client shutdown: {e}")


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


# Pydantic models for API requests and responses
class ContentItem(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None


class Message(BaseModel):
    role: str
    content: Union[str, List[ContentItem]]
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0
    frequency_penalty: Optional[float] = 0
    user: Optional[str] = None


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage


class ModelData(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "google"


class ModelList(BaseModel):
    object: str = "list"
    data: List[ModelData]


# Authentication dependency
async def verify_api_key(authorization: str = Header(None)):
    if not API_KEY:
        # If API_KEY is not set in environment, skip validation (for development)
        logger.warning("API key validation skipped - no API_KEY set in environment")
        return

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme. Use Bearer token")
        
        if token != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization format. Use 'Bearer YOUR_API_KEY'")
    
    return token


# Simple error handler middleware
@app.middleware("http")
async def error_handling(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f"Request failed: {str(e)}")
        return JSONResponse(status_code=500, content={"error": {"message": str(e), "type": "internal_server_error"}})


# Health check endpoint for Docker
@app.get("/health")
async def health_check():
    """Health check endpoint for container orchestration"""
    return {"status": "healthy", "timestamp": datetime.now(tz=timezone.utc).isoformat()}


# Root endpoint
@app.get("/")
async def root():
    return {
        "status": "online", 
        "message": "Gemini API FastAPI Server is running",
        "version": "0.2.0",
        "health": "/health"
    }


# Get list of available models
@app.get("/v1/models")
async def list_models():
    """返回 gemini_webapi 中声明的模型列表"""
    now = int(datetime.now(tz=timezone.utc).timestamp())
    data = [
        {
            "id": m.model_name,  # 如 "gemini-2.5-flash"
            "object": "model",
            "created": now,
            "owned_by": "google-gemini-web",
        }
        for m in Model
    ]
    logger.info(f"Available models: {[d['id'] for d in data]}")
    return {"object": "list", "data": data}


# Helper to convert between Gemini and OpenAI model names
def map_model_name(openai_model_name: str) -> Model:
    """根据模型名称字符串查找匹配的 Model 枚举值"""
    # 打印所有可用模型以便调试
    all_models = [m.model_name if hasattr(m, "model_name") else str(m) for m in Model]
    logger.info(f"Available models: {all_models}")

    # 首先尝试直接查找匹配的模型名称
    for m in Model:
        model_name = m.model_name if hasattr(m, "model_name") else str(m)
        if openai_model_name.lower() in model_name.lower():
            return m

    # 如果找不到匹配项，使用新的映射规则（基于最新的模型）
    model_keywords = {
        # 新的模型映射
        "gemini-2.5-flash": ["2.5", "flash"],
        "gemini-2.5-pro": ["2.5", "pro"],
        # 兼容旧的映射
        "gemini-2.0-flash": ["2.0", "flash"],
        "gemini-2.0-flash-thinking": ["2.0", "thinking"],
        "gemini-pro": ["pro"],
        "gemini-pro-vision": ["vision", "pro"],
        "gemini-1.5-pro": ["1.5", "pro"],
        "gemini-1.5-flash": ["1.5", "flash"],
    }

    # 根据关键词匹配
    keywords = model_keywords.get(openai_model_name, ["flash"])  # 默认使用flash模型

    for m in Model:
        model_name = m.model_name if hasattr(m, "model_name") else str(m)
        if all(kw.lower() in model_name.lower() for kw in keywords):
            return m

    # 如果还是找不到，返回默认模型
    try:
        return Model.G_2_5_FLASH  # 优先使用最新的模型
    except AttributeError:
        return next(iter(Model))


# Prepare conversation history from OpenAI messages format
def prepare_conversation(messages: List[Message]) -> tuple:
    conversation = ""
    temp_files = []

    for msg in messages:
        if isinstance(msg.content, str):
            # String content handling
            if msg.role == "system":
                conversation += f"System: {msg.content}\n\n"
            elif msg.role == "user":
                conversation += f"Human: {msg.content}\n\n"
            elif msg.role == "assistant":
                conversation += f"Assistant: {msg.content}\n\n"
        else:
            # Mixed content handling
            if msg.role == "user":
                conversation += "Human: "
            elif msg.role == "system":
                conversation += "System: "
            elif msg.role == "assistant":
                conversation += "Assistant: "

            for item in msg.content:
                if item.type == "text":
                    conversation += item.text or ""
                elif item.type == "image_url" and item.image_url:
                    # Handle image - 使用 tempfile.NamedTemporaryFile 更稳定的方式
                    image_url = item.image_url.get("url", "")
                    if image_url.startswith("data:image/"):
                        # Process base64 encoded image
                        try:
                            # Extract the base64 part
                            base64_data = image_url.split(",")[1]
                            image_data = base64.b64decode(base64_data)

                            # Create temporary file to hold the image
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                                tmp.write(image_data)
                                temp_files.append(tmp.name)
                        except Exception as e:
                            logger.error(f"Error processing base64 image: {str(e)}")

            conversation += "\n\n"

    # Add a final prompt for the assistant to respond to
    conversation += "Assistant: "

    return conversation, temp_files


async def get_gemini_client():
    global gemini_client, client_last_used
    
    current_time = time.time()
    
    # Check if client needs reinitialization
    if (gemini_client is None or 
        not hasattr(gemini_client, 'running') or
        not gemini_client.running or
        (client_last_used and current_time - client_last_used > CLIENT_IDLE_TIMEOUT)):
        
        # Clean up existing client
        if gemini_client:
            try:
                await gemini_client.close()
            except Exception as e:
                logger.warning(f"Error closing existing client: {str(e)}")
        
        try:
            # Initialize with better error handling and auto-refresh
            if SECURE_1PSID or SECURE_1PSIDTS:
                gemini_client = GeminiClient(
                    secure_1psid=SECURE_1PSID or None,
                    secure_1psidts=SECURE_1PSIDTS or None
                )
            else:
                # 尝试使用浏览器cookie
                gemini_client = GeminiClient()
                
            await gemini_client.init(**CLIENT_CONFIG)
            logger.info("✅ Gemini client initialized successfully with enhanced features")
        except AuthError as e:
            logger.error(f"❌ Authentication failed: {str(e)}")
            raise HTTPException(
                status_code=401, 
                detail="Authentication failed. Please check your cookies."
            )
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {str(e)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to initialize Gemini client: {str(e)}"
            )
    
    client_last_used = current_time
    return gemini_client


@app.post("/v1/chat/completions")
async def create_chat_completion(request: ChatCompletionRequest, api_key: str = Depends(verify_api_key)):
    temp_files = []
    try:
        # 使用改进的客户端获取函数
        gemini_client_local = await get_gemini_client()
        
        # 转换消息为对话格式
        conversation, temp_files = prepare_conversation(request.messages)
        logger.info(f"📝 Prepared conversation: {conversation[:200]}...")
        logger.info(f"🖼️ Temp files: {temp_files}")
        
        # 获取适当的模型
        model = map_model_name(request.model)
        logger.info(f"🤖 Using model: {model}")
        
        # 生成响应，使用重试机制
        logger.info("🚀 Sending request to Gemini...")
        max_retries = 3
        response = None
        
        for attempt in range(max_retries):
            try:
                if temp_files:
                    # With files
                    response = await gemini_client_local.generate_content(
                        conversation, files=temp_files, model=model
                    )
                else:
                    # Text only
                    response = await gemini_client_local.generate_content(conversation, model=model)
                break
            except (AuthError, APIError, TimeoutError) as e:
                logger.warning(f"⚠️ Request attempt {attempt + 1} failed: {str(e)}")
                if attempt == max_retries - 1:
                    # 对于特定的异常类型，抛出相应的HTTP异常
                    if isinstance(e, AuthError):
                        raise HTTPException(status_code=401, detail="Authentication failed")
                    elif isinstance(e, TimeoutError):
                        raise HTTPException(status_code=408, detail=f"Request timeout: {str(e)}")
                    else:
                        raise HTTPException(status_code=502, detail=f"API error: {str(e)}")
                # 重新初始化客户端
                global gemini_client
                gemini_client = None
                gemini_client_local = await get_gemini_client()
                await asyncio.sleep(1)  # 短暂延迟

        if response is None:
            raise HTTPException(status_code=500, detail="Failed to get response after retries")

        # 处理响应内容 - 使用清晰的逻辑
        reply_text = ""
        
        # 提取思考内容
        if hasattr(response, "thoughts") and response.thoughts:
            reply_text += f"<think>{response.thoughts}</think>\n\n"
        
        # 处理主要响应内容
        if hasattr(response, "text"):
            reply_text += response.text
        else:
            reply_text += str(response)
        
        # 字符转义处理
        reply_text = reply_text.replace("&lt;", "<").replace("\\<", "<").replace("\\_", "_").replace("\\>", ">")
        
        # 应用自定义的markdown修正
        reply_text = correct_markdown(reply_text)
        
        logger.info(f"💬 Response generated: {len(reply_text)} characters")

        if not reply_text or reply_text.strip() == "":
            logger.warning("⚠️ Empty response received from Gemini")
            reply_text = "服务器返回了空响应。请检查 Gemini API 凭据是否有效。"

        # 创建响应对象
        completion_id = f"chatcmpl-{uuid.uuid4()}"
        created_time = int(time.time())

        # 检查客户端是否请求流式响应
        if request.stream:
            # 实现流式响应
            async def generate_stream():
                # 创建 SSE 格式的流式响应
                # 先发送开始事件
                data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(data)}\n\n"

                # 模拟流式输出 - 将文本按字符分割发送
                for char in reply_text:
                    data = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": request.model,
                        "choices": [{"index": 0, "delta": {"content": char}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    # 可选：添加短暂延迟以模拟真实的流式输出
                    await asyncio.sleep(0.01)

                # 发送结束事件
                data = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(data)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(generate_stream(), media_type="text/event-stream")
        else:
            # 非流式响应（原来的逻辑）
            result = {
                "id": completion_id,
                "object": "chat.completion",
                "created": created_time,
                "model": request.model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": reply_text}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": len(conversation.split()),
                    "completion_tokens": len(reply_text.split()),
                    "total_tokens": len(conversation.split()) + len(reply_text.split()),
                },
            }

            logger.info(f"✅ Returning response with {result['usage']['total_tokens']} tokens")
            return result
            
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error generating completion: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    finally:
        # 临时文件清理
        cleaned_files = []
        failed_cleanups = []
        
        for temp_file in temp_files:
            try:
                os.unlink(temp_file)
                cleaned_files.append(temp_file)
            except Exception as e:
                failed_cleanups.append((temp_file, str(e)))
                logger.warning(f"⚠️ Failed to delete temp file {temp_file}: {str(e)}")
        
        # 记录清理结果
        if cleaned_files:
            logger.info(f"🧹 Successfully cleaned up {len(cleaned_files)} temporary files")
            
        if failed_cleanups:
            logger.warning(f"⚠️ Failed to clean up {len(failed_cleanups)} temporary files")


# Entry point for running with uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")
