# 服务器部署指南

## 一、系统要求

- **操作系统**：Linux (Ubuntu 20.04+ / CentOS 8+) / macOS / Windows + WSL2
- **Docker**：≥ 24.x，自带 `docker compose` 插件
- **内存**：≥ 8 GB（推荐 16 GB；模型推理与向量检索较吃内存）
- **磁盘**：≥ 50 GB 可用空间
- **网络**：构建期需要访问 PyPI / npm / Docker Hub

## 二、Docker 一键部署（推荐）

前端已从 Streamlit 重写为独立的 React SPA，前后端各自独立成镜像，
通过 `docker-compose.yml` 一键启动两个容器：

| 服务 | 镜像 | 端口 | 说明 |
|---|---|---|---|
| `api` | `mining-risk-agent-api:latest` | 8000 → 8000 | FastAPI + Uvicorn |
| `frontend` | `mining-risk-agent-frontend:latest` | 80 → **8501** | Vite 构建的 React SPA + Nginx 反向代理 |

容器网络拓扑：

```
浏览器  ──>  http://localhost:8501  (frontend / Nginx)
                       │
                       │  /api/* /health /docs   (proxy_pass http://api:8000)
                       ▼
                 mining_risk_api  (FastAPI :8000)
```

### 1. 安装 Docker

```bash
# Ubuntu
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### 2. （可选）配置环境变量

```bash
cd mining_risk_agent
cp .env.example .env
<<<<<<< HEAD
# 按需设置 LLM_PROVIDER，并填写 LLM_API_KEY 或 config.yaml 中对应 provider 的 api_key_env。
# 为空时后端自动走 Mock 降级。
# 设置 MRA_ADMIN_TOKEN 保护 LLM 配置、知识库写入、审计查询、模型迭代等管理接口。
# 生产环境建议设置 MRA_ENABLE_MOCK_FALLBACK=false，使决策故障返回 503 而不是 Mock。
# 生产环境请将 MRA_CORS_ORIGINS 收窄为真实前端 Origin。
# API_REQUIREMENTS_FILE 默认是 requirements-deploy.txt（API + 当前模型推理依赖）。
=======
# 按需填写 GLM5_API_KEY 或 OPENAI_API_KEY；为空时后端自动走 Mock 降级。
# API_REQUIREMENTS_FILE 默认是 requirements.txt（精简 API 依赖）。
>>>>>>> e7cc200 (some changes)
# 如需把训练/RAG/旧 Streamlit 依赖也打进后端镜像，可改为 requirements-full.txt。
```

### 3. 构建并启动

```bash
cd mining_risk_agent
docker compose up -d --build
```

首次构建会下载 Python / Node / Nginx 基础镜像并安装依赖（约 5 ~ 15 分钟，取决于网络）。
<<<<<<< HEAD
`docker-compose.yml` 默认通过 `API_REQUIREMENTS_FILE=requirements-deploy.txt` 安装 API 与当前
Stacking pkl 推理依赖；如需 RAG/长期记忆依赖可改为 `requirements-deploy-rag.txt`，完整训练与旧
Streamlit 依赖使用 `requirements-full.txt`。
=======
后端 Dockerfile 默认只安装 `requirements.txt` 中的 API 运行时依赖，不再安装
Streamlit、Plotly、TensorFlow、PyTorch、ChromaDB、sentence-transformers 等重依赖；
因此后端服务镜像会明显小于完整研发环境镜像。
>>>>>>> e7cc200 (some changes)

### 4. 验证部署

```bash
# 服务状态 + 健康检查
docker compose ps

# 后端日志（含 Uvicorn 启动信息）
docker compose logs -f api

# 前端日志（Nginx access/error log）
docker compose logs -f frontend

# 直接调用接口
curl http://localhost:8000/health        # 直连后端
curl http://localhost:8501/health        # 经前端 Nginx 反向代理
```

浏览器打开：

- 前端 SPA：<http://localhost:8501>
- Swagger UI（同源代理）：<http://localhost:8501/docs>
- Swagger UI（直连后端）：<http://localhost:8000/docs>

### 5. 停止 / 清理

```bash
docker compose down            # 停止并移除容器，保留 volume 与本地目录
docker compose down -v         # 同时移除匿名 volume
docker compose build --no-cache frontend   # 强制重建前端镜像
```

## 三、本地开发模式

### 后端

```bash
cd mining_risk_agent
python -m venv venv && source venv/bin/activate
# 默认 API 运行时依赖
pip install -r requirements.txt
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

如果要在本地训练模型、运行 RAG/NLP 或旧 Streamlit 前端，请安装完整依赖：

```bash
pip install -r requirements-full.txt
```

### 前端

```bash
cd mining_risk_agent/frontend
npm install
npm run dev          # 监听 http://localhost:5173
```

`vite.config.ts` 已配置开发态代理：`/api/*` 与 `/health` 自动转发到 `http://localhost:8000`，
可用 `VITE_DEV_API_TARGET=http://其他后端:8000 npm run dev` 改写。

## 四、生产部署的注意事项

### 4.1 反向代理 / TLS

`docker-compose.yml` 默认把前端 Nginx 暴露在宿主机 8501。生产环境建议在更外层放一台
反向代理（Nginx / Caddy / Traefik）做 HTTPS 卸载：

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # SSE 透传
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

<<<<<<< HEAD
### 4.2 CORS 与管理接口

后端 `api/main.py` 通过 `MRA_CORS_ORIGINS` 配置 CORS 白名单，默认只包含本地前端地址。
生产环境如果要把前端容器放在另一个域名/反向代理后，请把该变量收窄为前端真实 Origin。

LLM 配置、知识库写入、审计查询和模型迭代等管理接口需要请求头 `X-Admin-Token`，值来自
`MRA_ADMIN_TOKEN`。不要把生产 Token 编译进公开前端包；管理操作应走受控内网客户端或临时本地管理页面。
本地路演如确需无鉴权操作，可临时设置 `MRA_ALLOW_UNAUTHENTICATED_ADMIN=true`。
=======
### 4.2 CORS

后端 `api/main.py` 当前 `allow_origins=["*"]`，开发期方便。
生产环境如果要把前端容器放在另一个域名/反向代理后，请把 `allow_origins`
收窄为前端真实 Origin。
>>>>>>> e7cc200 (some changes)

### 4.3 数据持久化

`docker-compose.yml` 把以下目录作为 bind mount 挂入 `api` 容器：

| 容器路径 | 宿主机路径 | 说明 |
|---|---|---|
| `/app/data` | `./data` | AgentFS / 审批 / 审计 SQLite |
| `/app/models` | `./models` | Stacking 训练结果 |
| `/app/logs` | `./logs` | 运行时日志 |
| `/app/knowledge_base` | `./knowledge_base` | 6 大法规文本与知识库 |
| `/app/memory` | `./memory` | 长期记忆归档 |

升级镜像后这些目录的数据保留。

### 4.4 备份

```bash
# 备份 AgentFS / 审计 SQLite
cp data/agentfs.db backup/agentfs_$(date +%Y%m%d).db
cp data/audit.db backup/audit_$(date +%Y%m%d).db

# 备份知识库 Git 仓库
tar czf backup/kb_$(date +%Y%m%d).tar.gz data/agentfs_git knowledge_base
```

## 五、配置说明

编辑 `config.yaml` 可调整：

- **数据路径**：`data.raw_data_path`
- **模型参数**：`model.stacking.*`
- **API 端口**：`api.port`（如改动需同步修改 `docker-compose.yml`）
- **Token 阈值**：`harness.memory.short_term.max_tokens`
- **蒙特卡洛采样次数**：`harness.validation.monte_carlo.n_samples`

## 六、故障排查

| 现象 | 排查方向 |
|---|---|
| 前端 502 / 网关错误 | `docker compose logs api` 看 Uvicorn 是否就绪；`api` healthcheck 是否 healthy |
| `/api/v1/agent/decision/stream` 卡住 | 反向代理的 `proxy_buffering` 是否关闭、`proxy_read_timeout` 是否够长 |
<<<<<<< HEAD
| LLM 请求 401 | `.env` 中 `LLM_PROVIDER` 是否对应 `llm.providers`，`LLM_API_KEY` 或 provider 的 `api_key_env` 是否已注入 compose |
| 管理接口 401/503 | 检查 `MRA_ADMIN_TOKEN` 是否设置，并在请求中提供 `X-Admin-Token`；本地演示可临时启用 `MRA_ALLOW_UNAUTHENTICATED_ADMIN=true` |
=======
| GLM-5 / OpenAI 请求 401 | `.env` 中 `GLM5_API_KEY` / `OPENAI_API_KEY` 是否已注入 compose |
>>>>>>> e7cc200 (some changes)
| 模型未训练 → 返回 Mock | 把训练好的 `.pkl` 放入 `models/`，或先跑 `scripts/train.py` |
| 知识库为空 | 确认 `knowledge_base/` 目录中存在 `.md` 文件，或重新挂载 |

## 七、安全建议

<<<<<<< HEAD
1. 生产环境不要把 8000 端口直接暴露到公网；当前 compose 已将 8000 绑定到 `127.0.0.1`，前端只走 8501 → 反向代理 → 443。
2. 启用 HTTPS（Let's Encrypt / 商业证书）。
3. 把 `MRA_CORS_ORIGINS` 设为前端真实域名而非 `*`。
4. `.env` 文件不要提交到 Git，也不要打进镜像；`.dockerignore` 已排除 `.env` 与 `.env.*`。
5. 为 `MRA_ADMIN_TOKEN` 使用强随机值，并避免把生产 Token 暴露给浏览器端代码。
6. 定期回查 `data/audit.db`，巡检 `iteration` 触发与审批历史。
=======
1. 生产环境不要把 8000 端口直接暴露到公网；前端只走 8501 → 反向代理 → 443。
2. 启用 HTTPS（Let's Encrypt / 商业证书）。
3. 把 `allow_origins` 设为前端真实域名而非 `*`。
4. `.env` 文件不要提交到 Git（`.env.example` 已提供模板）。
5. 定期回查 `data/audit.db`，巡检 `iteration` 触发与审批历史。
>>>>>>> e7cc200 (some changes)
