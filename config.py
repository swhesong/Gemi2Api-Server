import os
import sys
from typing import Literal, Optional, List, Dict
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from pydantic_settings import YamlConfigSettingsSource
    HAS_YAML_CONFIG = True
except ImportError:
    HAS_YAML_CONFIG = False
    YamlConfigSettingsSource = None

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.yaml")


class ServerConfig(BaseModel):
    """Server configuration"""
    host: str = Field(default="0.0.0.0", description="Server host address")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port number")
    api_key: Optional[str] = Field(default=None, description="API key for authentication")


class GeminiClientSettings(BaseModel):
    """Credential set for one Gemini client"""
    id: str = Field(..., description="Unique identifier for the client")
    secure_1psid: str = Field(..., description="Gemini Secure 1PSID")
    secure_1psidts: Optional[str] = Field(None, description="Gemini Secure 1PSIDTS")


class GeminiConfig(BaseModel):
    """Gemini API configuration"""
    clients: List[GeminiClientSettings] = Field(default_factory=list)
    proxy: Optional[str] = Field(None, description="Proxy URL")
    timeout: int = Field(default=30, ge=1, description="Request timeout")
    auto_refresh: bool = Field(True, description="Enable auto-refresh for Gemini cookies")
    refresh_interval: int = Field(default=540, ge=1, description="Cookie refresh interval")
    verbose: bool = Field(False, description="Enable verbose logging")
    max_chars_per_request: int = Field(default=900000, ge=1, description="Max chars per request")


class StorageConfig(BaseModel):
    """LMDB Storage configuration"""
    path: str = Field(default="./data/lmdb", description="LMDB storage path")
    max_size: int = Field(default=134217728, ge=1, description="Maximum size in bytes")


class LoggingConfig(BaseModel):
    """Logging configuration"""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )

# ▼▼▼ 添加部分开始 ▼▼▼
class CORSConfig(BaseModel):
    """CORS configuration"""
    enabled: bool = Field(default=True, description="Enable CORS support")
    allow_origins: List[str] = Field(default_factory=lambda: ["*"], description="List of allowed origins")
    allow_credentials: bool = Field(default=True, description="Allow credentials in CORS requests")
    allow_methods: List[str] = Field(default_factory=lambda: ["*"], description="List of allowed HTTP methods")
    allow_headers: List[str] = Field(default_factory=lambda: ["*"], description="List of allowed headers")
# ▲▲▲ 添加部分结束 ▲▲▲


class EnhancedConfig(BaseSettings):
    """Enhanced configuration with YAML support"""
    
    server: ServerConfig = Field(default_factory=ServerConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


    cors: CORSConfig = Field(default_factory=CORSConfig)

    
    model_config = SettingsConfigDict(
        env_prefix="CONFIG_",
        env_nested_delimiter="__",
        yaml_file=CONFIG_PATH if Path(CONFIG_PATH).exists() else None,
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        """Prioritize: env -> yaml -> defaults"""
        sources = [env_settings]
        if HAS_YAML_CONFIG and Path(CONFIG_PATH).exists():
            sources.append(YamlConfigSettingsSource(settings_cls))
        return tuple(sources)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 从环境变量加载基本配置
        self._load_from_env()
        
    def _load_from_env(self):
        """Load configuration from environment variables (保持项目A兼容性)"""
        # Load Gemini client configuration
        if os.getenv("SECURE_1PSID"):
            client = GeminiClientSettings(
                id="env_client",
                secure_1psid=os.getenv("SECURE_1PSID"),
                secure_1psidts=os.getenv("SECURE_1PSIDTS")
            )
            if not self.gemini.clients:
                self.gemini.clients = [client]
        
        # Load server configuration
        if os.getenv("API_KEY"):
            self.server.api_key = os.getenv("API_KEY")
        
        if os.getenv("GEMINI_PROXY"):
            self.gemini.proxy = os.getenv("GEMINI_PROXY")
        
        if os.getenv("HOST"):
            self.server.host = os.getenv("HOST")
        
        if os.getenv("PORT"):
            try:
                port_val = int(os.getenv("PORT"))
                if 1 <= port_val <= 65535:
                    self.server.port = port_val
                else:
                    print(f"⚠️ PORT value out of range: {port_val}, using default")
            except (ValueError, TypeError):
                print(f"⚠️ Invalid PORT value: {os.getenv('PORT')}, using default")
        
        # Load storage configuration
        if os.getenv("LMDB_PATH"):
            self.storage.path = os.getenv("LMDB_PATH")
        
        if os.getenv("LMDB_MAX_SIZE"):
            try:
                size_val = int(os.getenv("LMDB_MAX_SIZE"))
                if size_val > 0:
                    self.storage.max_size = size_val
                else:
                    print(f"⚠️ LMDB_MAX_SIZE must be positive, using default")
            except (ValueError, TypeError):
                print(f"⚠️ Invalid LMDB_MAX_SIZE value: {os.getenv('LMDB_MAX_SIZE')}, using default")
        
        # Load Gemini configuration
        if os.getenv("MAX_CHARS_PER_REQUEST"):
            try:
                chars_val = int(os.getenv("MAX_CHARS_PER_REQUEST"))
                if chars_val > 0:
                    self.gemini.max_chars_per_request = chars_val
                else:
                    print(f"⚠️ MAX_CHARS_PER_REQUEST must be positive, using default")
            except (ValueError, TypeError):
                print(f"⚠️ Invalid MAX_CHARS_PER_REQUEST value: {os.getenv('MAX_CHARS_PER_REQUEST')}, using default")


# 全局配置实例
def create_config():
    """Create configuration instance with proper error handling"""
    try:
        return EnhancedConfig()
    except Exception as e:
        print(f"⚠️ Failed to load enhanced config, using fallback: {e}")
        # 创建基础配置作为回退
        fallback_clients = []
        if os.getenv("SECURE_1PSID"):
            fallback_clients = [GeminiClientSettings(
                id="fallback_client",
                secure_1psid=os.getenv("SECURE_1PSID"),
                secure_1psidts=os.getenv("SECURE_1PSIDTS")
            )]
        
        try:
            port = int(os.getenv("PORT", "8000"))
            if not (1 <= port <= 65535):
                port = 8000
        except (ValueError, TypeError):
            port = 8000
            
        try:
            max_size = int(os.getenv("LMDB_MAX_SIZE", "134217728"))
            if max_size <= 0:
                max_size = 134217728
        except (ValueError, TypeError):
            max_size = 134217728
        
        return EnhancedConfig(
            gemini=GeminiConfig(
                clients=fallback_clients,
                proxy=os.getenv("GEMINI_PROXY")
            ),
            server=ServerConfig(
                api_key=os.getenv("API_KEY"),
                host=os.getenv("HOST", "0.0.0.0"),
                port=port
            ),
            storage=StorageConfig(
                path=os.getenv("LMDB_PATH", "./data/lmdb"),
                max_size=max_size
            )
        )


# 全局配置实例
g_config = create_config()
