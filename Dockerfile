# =============================================================================
# 工矿企业风险预警智能体 — 后端镜像（FastAPI + 模型推理）
# 构建上下文：mining_risk_agent/  →  COPY . .  把代码铺到 /app
# 默认安装 requirements.txt 的精简 API 依赖，避免把训练/RAG/旧前端重依赖放进服务镜像。
# 如需完整能力：docker build --build-arg REQUIREMENTS_FILE=requirements-full.txt .
# =============================================================================
FROM python:3.10-slim

WORKDIR /app

# 系统依赖
# - git: GitPython 与 AgentFS 快照需要
# - build-essential: 部分 wheel 需要本地编译
# - curl: docker compose healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 优先复制依赖清单以利用层缓存
ARG REQUIREMENTS_FILE=requirements.txt
COPY requirements*.txt ./
RUN pip install --no-cache-dir uv

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r "${REQUIREMENTS_FILE}"
# 复制 monorepo 包与配置
COPY packages/ ./packages/
COPY pyproject.toml config.yaml ./
RUN pip install --no-cache-dir \
    -e packages/mining_risk_common \
    -e packages/mining_risk_train \
    -e packages/mining_risk_serve

# 其余仓库文件（知识库模板、脚本、提示词等；前端目录由 .dockerignore 排除）
COPY . .

# 运行时目录
RUN mkdir -p artifacts/models artifacts/pipelines \
             datasets/raw/public datasets/interim/merged datasets/demo \
             var/memory var/chroma var/agentfs var/uploads var/audit var/snapshots \
             logs knowledge_base

ENV PYTHONUNBUFFERED=1 \
    MINING_PROJECT_ROOT=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "mining_risk_serve.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
