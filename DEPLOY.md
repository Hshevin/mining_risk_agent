# 服务器部署指南

## 一、系统要求

- **操作系统**：Linux (Ubuntu 20.04+ / CentOS 8+) 或 Windows Server 2019+
- **Python**：3.10 或更高版本
- **内存**：≥ 8GB（推荐 16GB，用于深度学习模型）
- **磁盘**：≥ 50GB 可用空间
- **网络**：可访问互联网（用于模型下载与依赖安装）

## 二、Docker 部署（推荐）

### 1. 安装 Docker 与 Docker Compose

```bash
# Ubuntu
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Docker Compose
sudo apt-get install docker-compose-plugin
```

### 2. 构建并启动服务

```bash
cd mining_risk_agent
docker compose up -d --build
```

### 3. 验证部署

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f api
docker compose logs -f frontend

# 健康检查
curl http://localhost:8000/health
```

### 4. 停止服务

```bash
docker compose down
```

## 三、手动部署

### 1. 环境准备

```bash
# 安装 Python 3.10
sudo apt-get update
sudo apt-get install -y python3.10 python3.10-venv python3.10-dev

# 安装 Git
sudo apt-get install -y git
```

### 2. 项目部署

```bash
# 创建应用目录
mkdir -p /opt/mining_risk_agent
cd /opt/mining_risk_agent

# 复制项目代码
# （根据实际情况使用 git clone 或 scp）

# 创建虚拟环境
python3.10 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置系统服务

创建 API 服务 systemd 单元文件 `/etc/systemd/system/mining-risk-api.service`：

```ini
[Unit]
Description=Mining Risk Agent API
After=network.target

[Service]
Type=simple
User=mining-agent
WorkingDirectory=/opt/mining_risk_agent
Environment=PYTHONPATH=/opt/mining_risk_agent
ExecStart=/opt/mining_risk_agent/venv/bin/uvicorn mining_risk_agent.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

创建前端服务 systemd 单元文件 `/etc/systemd/system/mining-risk-frontend.service`：

```ini
[Unit]
Description=Mining Risk Agent Frontend
After=network.target

[Service]
Type=simple
User=mining-agent
WorkingDirectory=/opt/mining_risk_agent
Environment=PYTHONPATH=/opt/mining_risk_agent
ExecStart=/opt/mining_risk_agent/venv/bin/streamlit run mining_risk_agent/frontend/app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable mining-risk-api mining-risk-frontend
sudo systemctl start mining-risk-api mining-risk-frontend
```

### 4. Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:8501/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## 四、配置说明

编辑 `config.yaml` 可调整以下参数：

- **数据路径**：`data.raw_data_path`
- **模型参数**：`model.stacking.*`
- **API 端口**：`api.port`
- **前端端口**：`frontend.port`
- **Token 阈值**：`harness.memory.short_term.max_tokens`
- **蒙特卡洛采样次数**：`harness.validation.monte_carlo.n_samples`

## 五、备份与恢复

### 数据库备份

```bash
# 备份 AgentFS SQLite
cp data/agentfs.db backup/agentfs_$(date +%Y%m%d).db

# 备份审计日志 SQLite
cp data/audit.db backup/audit_$(date +%Y%m%d).db
```

### Git 快照

```bash
# 手动创建快照
cd data/agentfs_git
git log --oneline
```

## 六、故障排查

| 问题 | 排查方法 |
|------|---------|
| 模型加载失败 | 检查 `models/stacking_risk_v1.pkl` 是否存在 |
| 前端无法连接后端 | 检查 API 服务是否运行，CORS 配置是否正确 |
| 知识库文件丢失 | 使用 Git 回滚到历史 Commit |
| 内存不足 | 降低 `max_tokens` 或减少深度学习模型参数量 |

## 七、安全建议

1. **修改默认端口**：生产环境避免使用 8000/8501 等默认端口
2. **启用 HTTPS**：使用 Let's Encrypt 或商业证书
3. **访问控制**：配置防火墙规则，限制非授权 IP 访问
4. **数据加密**：敏感字段在传输和存储时加密
5. **定期审计**：定期检查审计日志，发现异常及时处理
