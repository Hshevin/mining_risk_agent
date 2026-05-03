# 工矿企业风险预警智能体系统 Docker 镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建必要目录
RUN mkdir -p models data logs knowledge_base

# 暴露端口
EXPOSE 8000 8501

# 启动命令（默认启动 API 服务）
CMD ["uvicorn", "mining_risk_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
