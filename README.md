# 🚀 Gemi2Api-Server

<div align="center">

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-red.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)](https://docker.com)
[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen.svg)]()

**高性能 Gemini Web API 服务器**

基于 [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API) 构建的企业级 FastAPI 服务端实现

---

**✨ 支持所有最新 Gemini 模型 | 🔄 智能连接池 | 🍪 Cookie 自动刷新 | 📊 健康监控**

</div>

---

## 🌟 核心特性

### 🔥 **高级功能**
- 🎯 **智能模型映射** - 支持所有 Gemini 2.0/2.5 系列模型，自动映射 OpenAI 兼容接口
- 🔄 **智能连接池** - 自动管理客户端连接，提供最佳性能和稳定性
- 🍪 **Cookie 自动管理** - 智能刷新 SECURE_1PSIDTS，支持浏览器 Cookie 自动获取
- 🏥 **健康监控** - 后台健康检查，自动清理异常连接
- 📊 **流式响应** - 支持 Server-Sent Events 实时流式输出
- 🖼️ **多媒体支持** - 完整支持图片处理，智能文件管理

### 🛡️ **企业级特性**
- 🔒 **安全认证** - API Key 验证，CORS 配置
- ⚡ **性能优化** - 异步处理，智能缓存，连接复用
- 🎨 **Markdown 修正** - 自动修正 Google 搜索链接，优化输出格式
- 🔧 **配置灵活** - 环境变量配置，Docker 部署支持
- 📝 **完整日志** - 详细的操作日志和错误追踪

---

## 🚀 快捷部署

### 🌟 一键部署服务

<table>
<tr>
<td align="center">

**Render**

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/zhiyu1998/Gemi2Api-Server)

</td>
<td align="center">

**HuggingFace**

[![Deploy to HuggingFace](https://img.shields.io/badge/%E7%82%B9%E5%87%BB%E9%83%A8%E7%BD%B2-%F0%9F%A4%97-fff?style=for-the-badge)](https://huggingface.co/spaces/ykl45/gmn2a)

</td>
</tr>
</table>

---

## 🐳 Docker 部署（推荐）

### 快速启动

```bash
# 1. 克隆项目
git clone https://github.com/swhesong/Gemi2Api-Server.git
cd Gemi2Api-Server

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的 Cookie 值

# 3. 启动服务
docker-compose up -d

# 🎉 服务已启动！访问 http://localhost:8000
```

### 环境变量配置

创建 `.env` 文件：

```env
# 必填：Gemini Cookie 凭据
SECURE_1PSID=g.a000zxxxxxx
SECURE_1PSIDTS=sidts-yyyyy

# 可选：API 访问密钥
API_KEY=your-api-key-here

# 可选：代理设置
GEMINI_PROXY=http://ip:8080

# 可选：日志级别
LOG_LEVEL=info

# 可选：时区设置
TZ=Asia/Shanghai
```

### Docker 管理命令

```bash
# 查看服务状态
docker-compose ps

# 查看实时日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 重建并启动
docker-compose up -d --build

# 查看资源使用
docker stats gemi2api-server_gemini-api_1
```

---

## 💻 本地开发

### 使用 uv（推荐）

```bash
# 安装 uv（如果未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目
git clone https://github.com/swhesong/Gemi2Api-Server.git
cd Gemi2Api-Server

# 创建环境和安装依赖
uv sync

# 激活环境
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate.bat  # Windows

# 启动开发服务器
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 使用传统 pip

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 启动服务
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 📚 API 文档

### 🔍 核心端点

| 方法 | 端点 | 描述 | 认证 |
|------|------|------|------|
| `GET` | `/` | 服务状态和功能列表 | ❌ |
| `GET` | `/health` | 详细健康检查 | ❌ |
| `GET` | `/v1/models` | 获取支持的模型列表 | ✅ |
| `POST` | `/v1/chat/completions` | 聊天对话（OpenAI 兼容） | ✅ |

### 🎯 支持的模型

**Gemini 原生模型：**
- `gemini-2.5-pro` - 最强推理能力
- `gemini-2.5-flash` - 快速响应
- `gemini-2.5-advanced` - 高级功能（如可用）
- `gemini-2.0-flash` - 新一代快速模型
- `gemini-2.0-flash-thinking` - 带思考过程的模型

**OpenAI 兼容映射：**
- `gpt-4` → `gemini-2.5-pro`
- `gpt-4-turbo` → `gemini-2.5-pro`
- `gpt-3.5-turbo` → `gemini-2.5-flash`

### 💬 聊天对话示例

```bash
curl -X POST "http://localhost:8000/v1/chat/completions" \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {
        "role": "user",
        "content": "解释什么是量子计算"
      }
    ],
    "stream": false,
    "temperature": 0.7
  }'
```

### 🖼️ 图片对话示例

```bash
curl -X POST "http://localhost:8000/v1/chat/completions" \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "这张图片里有什么？"
          },
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEA..."
            }
          }
        ]
      }
    ]
  }'
```

---

## 🔧 高级配置

### 客户端池配置

在 `main.py` 中调整连接池设置：

```python
# 客户端池配置
client_pool_size = 3                  # 最大客户端数量
CLIENT_IDLE_TIMEOUT = 900             # 空闲超时（15分钟）
CLIENT_MAX_LIFETIME = 1800            # 最大生命周期（30分钟）
CLIENT_HEALTH_CHECK_INTERVAL = 60     # 健康检查间隔
CLIENT_COOKIE_REFRESH_THRESHOLD = 540 # Cookie 刷新阈值
```

### Docker Compose 高级配置

```yaml
version: '3.8'

services:
  gemini-api:
    image: devinglaw/genmini2api:latest
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./cache:/app/cache
    environment:
      - LOG_LEVEL=debug
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

---

## 🛠️ 故障排除

### ❗ 常见问题与解决方案

#### 🚨 500 内部服务器错误

**原因：** IP 限制或请求过于频繁

**解决步骤：**

1. **刷新 Cookie：**
   ```bash
   # 使用隐身模式访问 https://gemini.google.com/
   # 登录后获取新的 Cookie 值
   ```

2. **获取新 Cookie：**
   - 打开浏览器开发工具 (F12)
   - 进入 Application/应用程序 → Cookies → gemini.google.com
   - 复制 `__Secure-1PSID` 和 `__Secure-1PSIDTS` 值
   - 更新 `.env` 文件

3. **重启服务：**
   ```bash
   docker-compose down
   docker-compose up -d --build
   ```

#### 🔐 认证失败

```bash
# 检查 Cookie 有效性
curl -X GET "http://localhost:8000/health"

# 检查服务日志
docker-compose logs -f gemini-api
```

#### 📊 性能优化

```bash
# 监控资源使用
docker stats

# 调整连接池大小（在 main.py 中）
client_pool_size = 5  # 根据需要调整
```

---

## 🧪 开发与测试

### 运行测试

```bash
# 安装测试依赖
uv add --dev pytest pytest-asyncio httpx

# 运行测试
pytest tests/

# 代码格式检查
ruff check .
ruff format .
```

### 本地调试

```bash
# 启用详细日志
export LOG_LEVEL=debug

# 启动调试模式
uvicorn main:app --reload --log-level debug
```

---

## 📈 监控与日志

### 健康检查端点

```bash
curl http://localhost:8000/health
```

**响应示例：**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-09T10:30:45Z",
  "version": "0.4.0",
  "client_pool": {
    "total": 2,
    "healthy": 2,
    "max_size": 3
  },
  "cookie_cache": {
    "size": 1,
    "cache_file_exists": true
  }
}
```

### 日志监控

```bash
# 实时查看日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs gemini-api

# 搜索错误日志
docker-compose logs | grep ERROR
```

---

## 🔮 高级功能

### 🧠 思考模式支持

```python
# 使用 thinking 模型获取推理过程
{
  "model": "gemini-2.0-flash-thinking",
  "messages": [
    {
      "role": "user", 
      "content": "解决这个数学问题：2x + 5 = 13"
    }
  ]
}
```

### 🔄 自动 Cookie 刷新

服务器自动管理 Cookie 生命周期：
- 智能检测 Cookie 过期
- 自动刷新 SECURE_1PSIDTS
- 缓存机制提高性能
- 浏览器 Cookie 备用方案

### 📝 Markdown 增强

自动修正和优化输出：
- 修复 Google 搜索链接格式
- 优化代码块展示
- 智能文本转义处理

---

## 🤝 贡献指南

我们欢迎所有形式的贡献！

### 🎯 如何贡献

1. **Fork 项目**
2. **创建功能分支** (`git checkout -b feature/AmazingFeature`)
3. **提交更改** (`git commit -m 'Add some AmazingFeature'`)
4. **推送分支** (`git push origin feature/AmazingFeature`)
5. **创建 Pull Request**

### 📋 开发规范

- 遵循 [PEP 8](https://pep8.org/) 代码规范
- 使用 `ruff` 进行代码格式化
- 添加必要的测试用例
- 更新相关文档

---

## 🙏 贡献者

感谢所有为 `Gemi2Api-Server` 作出贡献的开发者：

<a href="https://github.com/zhiyu1998/Gemi2Api-Server/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=zhiyu1998/Gemi2Api-Server&max=1000" />
</a>

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源许可证。

---

## 🔗 相关链接

- 📚 [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- 🔧 [Gemini-API 原项目](https://github.com/HanaokaYuzu/Gemini-API)
- 🐳 [Docker 官方文档](https://docs.docker.com/)
- 🚀 [uv 包管理器](https://github.com/astral-sh/uv)

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给我们一个星标！**

[![GitHub stars](https://img.shields.io/github/stars/zhiyu1998/Gemi2Api-Server.svg?style=social&label=Star)](https://github.com/zhiyu1998/Gemi2Api-Server)
[![GitHub forks](https://img.shields.io/github/forks/zhiyu1998/Gemi2Api-Server.svg?style=social&label=Fork)](https://github.com/zhiyu1998/Gemi2Api-Server/fork)

---

**Made with ❤️ by the Gemi2Api-Server Community**

</div>
