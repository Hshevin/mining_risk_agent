# 工矿企业风险预警智能体系统

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev)
[![Vite](https://img.shields.io/badge/Vite-5-646CFF.svg)](https://vitejs.dev)
[![License](https://img.shields.io/badge/license-Research-orange.svg)]()

> **一句话介绍**：基于 Harness 工程化管控的工矿企业风险预警 LLM 智能体系统，支持 Stacking 集成学习预测、GLM-5 决策智能体 Workflow、三重校验风控拦截、模型自动迭代 CI/CD；前后端独立部署 —— FastAPI 后端 + React/Vite SCADA 风格 SPA 前端，`docker compose up --build` 一键启动。

## 快速开始

```bash
# Docker 一键启动（API + 前端，分别打镜像）
git clone <repository-url>
cd mining_risk_agent
docker compose up -d --build

# 访问前端演示界面
open http://localhost:8501
```

| 服务 | 地址 | 说明 |
|------|------|------|
| React SPA 前端 | `http://localhost:8501` | 4 标签页 SCADA Dashboard（Vite 构建 + Nginx 托管） |
| Swagger UI（同源） | `http://localhost:8501/docs` | 经前端 Nginx 代理到后端 |
| FastAPI 直连 | `http://localhost:8000/docs` | 直接访问后端 |
| 健康检查 | `http://localhost:8000/health` | API 服务状态 |

**无需准备数据、无需训练模型、无需配置 API Key**：系统内置 3 组场景化 Mock 数据，后端不可用时自动降级，确保路演演示永不中断。

## 目录

- [一、项目介绍](#一项目介绍)
- [二、技术栈](#二技术栈)
- [三、环境搭建](#三环境搭建)
- [四、启动步骤](#四启动步骤)
- [五、接口文档](#五接口文档)
- [六、模型架构](#六模型架构)
- [七、NLP 与 RAG 基础设施](#七nlp-与-rag-基础设施)
- [八、三重校验与高风险阻断机制](#八三重校验与高风险阻断机制step-5)
- [九、GLM-5 决策智能体 Workflow](#九glm-5-决策智能体-workflowstep-6)
- [十、模型自动迭代与 CI/CD](#十模型自动迭代与-cicd-工程化step-7)
- [十一、特征工程](#十一特征工程)
- [十二、项目结构](#十二项目结构)
- [十三、前端演示指南](#十三前端演示指南)
- [十四、检查点验证](#十四检查点验证)
- [十五、运行测试](#十五运行测试)
- [Demo Replay 数据源（模型迭代路演）](#demo-replay-数据源模型迭代路演)
- [十六、常见问题](#十六常见问题)
- [十七、许可证](#十七许可证)

## 一、项目介绍

本项目严格对齐《工矿企业风险预警智能体建设方案》与《Harness 研究方案》中的技术路线与功能要求，构建了一套完整可落地的工矿企业风险预警智能体系统。

### 核心特性

- **数据接入与特征工程**：支持 CSV/Excel/JSON 批量导入，全类型数据处理（二值型、数值型、枚举型、文本型、行业分类），缺失值与异常值处理；覆盖特征汇总表全部字段的特殊逻辑（干湿除尘比例、有限空间/危化品 OR 逻辑、时间衰减加权、地理围栏、企业聚合、数据可信度系数）
- **Stacking 集成学习风险预测**：7 个异构基学习器（Multinomial LR/XGBoost/LightGBM/CatBoost/Random Forest/MLP/1D-CNN）+ 弹性网络逻辑回归元学习器，5 折严格时序交叉验证防泄露
- **可解释性与可视化**：SHAP 全局蜂群图、单样本力导向图、混淆矩阵热力图、ROC/PR 曲线（4 类 OvR）、训练曲线、元学习器权重柱状图
- **Harness 多维知识库**：6 个核心 Markdown 知识库文件，AgentFS 虚拟文件系统（SQLite + Git 版本控制，路径沙箱仅允许 `knowledge_base/` 与 `memory/` 为根，POSIX-like `read/write/ls/stat/delete/exists` 接口，操作审计日志 `operation_log`）
- **长短期混合记忆系统**：P0-P3 四级优先级 + tiktoken（cl100k_base）精确计数 + LRU 动态清理；短期记忆超限后依次执行「清P3 → P1摘要降级（ConversationSummaryMemory）→ P2无损压缩」；长期记忆基于 AgentFS 读写 4 个 Markdown 归档库，支持 VectorStore SelfQuery 过滤 + BGE-Reranker 精排；全部 IO 使用 async/await
- **NLP 实体抽取与 RAG 检索**：BERT-BiLSTM-CRF 实体识别（高风险设备 / 风险属性 / 动作 / 法规条款），SelfQuery 元数据预过滤 + BGE-Reranker-large 精排
- **知识库自动构建**：网络爬虫抓取公开法规 + 企业 CSV 自动融合生成 6 大知识库 Markdown
- **三重校验与高风险阻断**：MARCH 声明级孤立验证（LangGraph 物理隔离 Checker 节点，信息隔离仅允许 `atomic_propositions`），蒙特卡洛置信度检验（独立 LLM 实例 20 次采样，`<0.85` 触发 `HUMAN_REVIEW`），三维风险评估（后果严重度/利益相关性/执行不可逆性，SOP 加权规则），`ToolCallInterceptor` 工具调用风险注入，分级审核路由
- **递归知识合成（RKS）**：人工审核驳回后自动提取「问题场景-错误决策-正确决策-依据条款」四元组，追加写入知识库并触发 AgentFS Git 快照
- **GLM-5 决策智能体 Workflow（Step 6）**：LangGraph 5 节点 DAG（data_ingestion → risk_assessment → memory_recall → decision_generation → result_push），MARCH 校验回环重试（最多 3 次），蒙特卡洛置信度检验，三维风险路由阻断
- **场景化配置驱动**：支持 chemical（危化品）/ metallurgy（冶金）/ dust（粉尘涉爆）三场景动态切换，场景化 Prompt 模板、知识库子集、校验阈值自动适配
- **模型自动迭代与 CI/CD 工程化（Step 7）**：监控触发（样本>5000 或 F1<0.85）→ 自动训练流水线 → Git Flow 分支管理 → 回归测试（准确率/精确率/召回率/F1/AUC/SHAP Kendall Tau）→ Drift 分析 → 两级终审（安全负责人 → 技术负责人）→ 24h 预生产试运行 → 灰度发布（0.1→0.5→1.0 阶梯）
- **演示级前端 Dashboard**：独立 React/Vite SPA（4 Tab）+ ECharts 可视化 + Nginx 反向代理，SCADA 工业控制室风格暗色主题；支持场景切换、风险仪表盘、SHAP 归因、决策卡片、POST SSE 节点流、知识库预览、记忆系统演示、CI/CD 迭代动画；后端不可用时自动调用本地 Mock 降级，确保路演永不中断

## 二、技术栈

- Python 3.10+
- FastAPI 0.100+, Uvicorn
- LangChain 0.2+ / LangGraph 0.2+
- SQLite 3 + GitPython
- scikit-learn, XGBoost, LightGBM, CatBoost, TensorFlow/Keras, SHAP
- transformers, torch, pytorch-crf, sentence-transformers
- chromadb, requests, beautifulsoup4
- seaborn, matplotlib, plotly, plotly-express
- joblib, tiktoken, pydantic 2.0+, pytest
- openai, langchain-openai, jinja2
- 前端 SPA：React 18 + Vite 5 + TypeScript 5 + ECharts 5（独立 Node 构建，Nginx 托管）
- 数据处理：pandas, numpy

## 三、环境搭建

### 1. 克隆项目

```bash
git clone <repository-url>
cd mining_risk_agent
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### 3. 安装依赖

```bash
# 默认只安装后端 API 运行时依赖（Docker 后端镜像同样使用这一层）
pip install -r requirements.txt

# 如需模型训练、RAG/NLP、旧 Streamlit 前端、测试工具：
pip install -r requirements-full.txt
```

### 4. 准备数据

将 `公开数据(1).zip` 解压到项目同级目录，确保路径为 `../公开数据/公开数据/数据补充`（可在 `config.yaml` 中修改 `data.raw_data_path`）。

### 5. 初始化知识库（可选，首次运行建议执行）

```bash
python scripts/init_knowledge_base.py --data-dir ../公开数据/
```

该脚本会自动读取企业 CSV 数据，一键生成/增量填充 6 个核心 Markdown 知识库文件，并输出到 `knowledge_base/` 目录。

## 四、启动步骤

### 方式一：本地启动

#### 启动 API 服务

```bash
python -m mining_risk_agent.api.main
```

或直接使用 uvicorn：

```bash
uvicorn mining_risk_agent.api.main:app --host 0.0.0.0 --port 8000 --reload
```

API 文档地址：`http://localhost:8000/docs`

#### 启动前端（开发模式）

```bash
cd mining_risk_agent/frontend
npm install
npm run dev          # 监听 http://localhost:5173
```

Vite 已配置开发态代理：`/api/*` 与 `/health` 自动转发到 `http://localhost:8000`。
可用 `VITE_DEV_API_TARGET=http://其他后端:8000 npm run dev` 改写后端地址。

前端地址：开发态 `http://localhost:5173` ；通过 Docker 部署后为 `http://localhost:8501`。

> 💡 **路演提示**：推荐在 1920×1080 分辨率下全屏演示，界面已针对投影优化，无横向滚动条。详见 [前端演示指南](#十三前端演示指南)。

#### 训练模型

```bash
python -m mining_risk_agent.model.train
```

训练完成后，模型文件将保存至 `models/stacking_risk_v1_stable.pkl`，预处理 Pipeline 保存至 `models/preprocessing_pipeline.pkl`。

#### 训练 NER 实体抽取模型

```bash
python scripts/train_ner.py --data data/ner_train.json --output models/ner_model.pt --epochs 10
```

数据格式：`[{ "text": "...", "entities": [{"text": "...", "label": "高风险设备", "start": 0, "end": 2}] }]`

支持 BIO 标签自动转换。

#### 生成可视化报告

```bash
python -m mining_risk_agent.model.visualization
```

#### 触发模型自动迭代流水线（Step 7）

```bash
# 自动训练并产出候选模型
python -m iteration.pipeline

# 执行回归测试
python -m iteration.regression_test --old models/stacking_risk_v1.pkl --new models/stacking_risk_v2.pkl --test data/test.csv

# 启动监控（定时扫描，建议配合 crontab/systemd 使用）
python -c "from iteration.monitor import ModelMonitor; ModelMonitor().should_retrain()"
```

报告将输出至 `reports/figures/`，包含 SHAP 蜂群图、力导向图、混淆矩阵、ROC/PR 曲线、训练曲线、元学习器权重图等。

### 方式二：Docker 一键部署（推荐）

前后端各自独立成镜像，通过 `docker-compose.yml` 一键启动两个容器：

```bash
cd mining_risk_agent
cp .env.example .env       # 可选：设置 LLM_PROVIDER、LLM API Key、MRA_ADMIN_TOKEN 等
docker compose up -d --build
```

- 浏览器入口（前端 SPA）：`http://localhost:8501`
- 直连后端 Swagger：`http://localhost:8000/docs`
- 经前端反向代理的 Swagger：`http://localhost:8501/docs`

启动后访问 `http://localhost:8501` 即可看到完整 4 标签页演示界面，包含企业风险预测、知识库与记忆系统、模型迭代 CI/CD、系统配置。

**Docker 服务说明：**
| 服务 | 镜像 | 容器名 | 端口映射 | 说明 |
|------|------|--------|----------|------|
| api | `mining-risk-agent-api` | `mining_risk_api` | `127.0.0.1:8000:8000` | FastAPI + Uvicorn（Python 3.10-slim，仅本机直连） |
| frontend | `mining-risk-agent-frontend` | `mining_risk_frontend` | `8501:80` | React/Vite SPA（多阶段：node:20-alpine 构建 → nginx:alpine 托管 + 反向代理 `/api`、`/health`、`/docs` 至 `api`） |

> **架构提示**：前端容器内 Nginx 监听 80 端口，把 `/api/*`、`/health`、`/docs`、`/redoc`、`/openapi.json` 反向代理至 `http://api:8000`，并关闭 `proxy_buffering` 以保留 SSE 流式节点输出；浏览器只与前端同源通信，从而避免 CORS 与跨域 Cookie 问题。详见 `mining_risk_agent/frontend/nginx.conf`。

## 五、接口文档

### 核心 API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/v1/data/upload` | POST | 数据文件上传 |
| `/api/v1/data/upload/batch` | POST | 批量数据上传 |
| `/api/v1/knowledge/list` | GET | 知识库文件列表 |
| `/api/v1/knowledge/read/{filename}` | GET | 读取知识库 |
| `/api/v1/knowledge/write` | POST | 写入知识库 |
| `/api/v1/agent/decision` | POST | 触发完整决策工作流（Step 6） |
| `/api/v1/agent/decision/stream` | POST | SSE 流式输出节点状态 |
| `/api/v1/agent/scenario/{scenario_id}` | POST | 切换场景配置（chemical/metallurgy/dust） |
| `/api/v1/audit/log` | POST | 写入审计日志 |
| `/api/v1/audit/query` | GET | 查询审计日志 |
| `/api/v1/iteration/trigger` | POST | 手动触发迭代流水线 |
| `/api/v1/iteration/status` | GET | 查询当前迭代状态（监控/训练中/审批中/试运行中） |
| `/api/v1/iteration/approve` | POST | 审批人提交审批结果（security/tech 两级） |
| `/api/v1/iteration/canary` | POST | 调整灰度流量比例（0.0/0.1/0.5/1.0） |

> 管理接口说明：LLM 配置、知识库写入/快照/回滚、审计查询、模型迭代触发/审批/灰度/回归等敏感接口需要 `X-Admin-Token`，值来自 `MRA_ADMIN_TOKEN`。本地路演如需无鉴权管理操作，可临时设置 `MRA_ALLOW_UNAUTHENTICATED_ADMIN=true`；生产环境建议设置 `MRA_ENABLE_MOCK_FALLBACK=false`，使决策工作流故障返回 503 而不是 Mock 演示数据。

### 记忆系统接口示例

**短期记忆（P0-P3 优先级 + 自动清理）：**

```python
from harness.memory import ShortTermMemory

# 默认 max_tokens=180000, safety_threshold=0.8（实际限制 144k）
mem = ShortTermMemory()
mem.add("严禁瓦斯浓度超限作业", priority="P0")      # 永久保留
mem.add("高优先级处置经验...", priority="P1")       # 摘要降级
mem.add("中优先级巡检记录...", priority="P2")       # 无损压缩
mem.add("低优先级冗余日志...", priority="P3")       # 最先移除

context = mem.get_context(max_tokens=5000)
```

**长期记忆归档与召回（异步）：**

```python
import asyncio
from harness.memory import LongTermMemory

ltm = LongTermMemory()

# 将 P1 摘要归档到 AgentFS 长期记忆库
p1_memories = [
    {"summary": "瓦斯浓度超限处置经验", "metadata": {"risk": "高"}, "timestamp": 0}
]
await ltm.summarize_and_archive(p1_memories)

# RAG 召回：SelfQuery 元数据过滤 + BGE-Reranker 精排
results = await ltm.recall(
    query="瓦斯浓度超限如何处理",
    risk_level="火灾爆炸",
    top_k=5
)
# 返回: [{"text": "...", "metadata": {...}, "rerank_score": 0.95}, ...]
```

**混合记忆管理器（端到端）：**

```python
from harness.memory import HybridMemoryManager

manager = HybridMemoryManager()
manager.add_short_term("新的预警事件", priority="P1")

# 异步归档 P1 摘要到长期记忆
await manager.archive_experience()

# 异步召回长期记忆
results = await manager.recall_long_term(
    query="瓦斯泄漏",
    risk_level="火灾爆炸",
    top_k=5
)
```

### RAG 与 NLP 接口示例

**向量检索（SelfQuery + 元数据过滤）：**

```python
from harness.vector_store import VectorStore

store = VectorStore()
store.load_from_kb("knowledge_base")

results = store.self_query_retrieve(
    query="高炉煤气泄漏",
    filters={"risk_type": "火灾爆炸", "industry": "钢铁"},
    top_k=5
)
```

**实体抽取：**

```python
from harness.nlp_pipeline import NERPipeline

ner = NERPipeline()
entities = ner.extract_entities("高炉煤气泄漏需立即停炉")
# [{'text': '高炉', 'label': '高风险设备', 'start': 0, 'end': 2, 'source': 'rule'}, ...]
```

**重排序精排：**

```python
from harness.reranker import Reranker

reranker = Reranker()
ranked = reranker.rerank("高炉煤气泄漏", passages, top_k=5)
```

### 预测接口示例

**请求：**

```json
POST /api/v1/prediction/predict
{
  "enterprise_id": "ENT-001",
  "data": {
    "管理类别": 1003,
    "是否发生事故": 0,
    "企业职工总人数": 150
  }
}
```

**响应：**

```json
{
  "enterprise_id": "ENT-001",
  "predicted_level": "黄",
  "probability_distribution": {
    "蓝": 0.05,
    "黄": 0.75,
    "橙": 0.15,
    "红": 0.05
  },
  "shap_contributions": [
    {"feature": "企业职工总人数", "contribution": 0.32}
  ],
  "validation_result": {...},
  "suggestions": {...}
}
```

### 决策智能体 Workflow 接口示例（Step 6）

**触发完整工作流：**

```bash
POST /api/v1/agent/decision
Content-Type: application/json

{
  "enterprise_id": "ENT-001",
  "data": {
    "管理类别": 1003,
    "是否发生事故": 0,
    "瓦斯浓度": 1.2,
    "通风系统状态": 0
  }
}
```

**响应（结构化决策 JSON）：**

```json
{
  "enterprise_id": "ENT-001",
  "scenario_id": "chemical",
  "final_status": "APPROVE",
  "predicted_level": "红",
  "probability_distribution": {"红": 0.85, "橙": 0.12, "黄": 0.02, "蓝": 0.01},
  "shap_contributions": [{"feature": "瓦斯浓度", "contribution": 0.45}],
  "risk_level_and_attribution": {
    "level": "红",
    "root_cause": "瓦斯浓度超限且通风系统异常"
  },
  "government_intervention": {
    "department_primary": {
      "name": "属地应急管理局-危化品安全监督管理科",
      "contact_role": "科长",
      "action": "立即签发《重大事故隐患整改通知书》"
    },
    "actions": ["24小时内组织联合执法小组登门核查"],
    "deadline_hours": 24,
    "follow_up": "整改完成后3个工作日内复查"
  },
  "enterprise_control": {
    "equipment_id": "2号、3号涉危化品合成反应釜",
    "operation": "立即通过DCS控制系统执行紧急停车",
    "parameters": {
      "dcs_tag": "FIC-201A/B/C",
      "target_values": "进料流量=0 t/h, 反应温度≤60°C",
      "monitoring_interval_minutes": 30
    }
  },
  "march_result": {"passed": true, "retry_count": 0},
  "monte_carlo_result": {"passed": true, "confidence": 0.95},
  "three_d_risk": {"blocked": false, "total_score": 1.8}
}
```

**SSE 流式输出节点状态：**

```bash
POST /api/v1/agent/decision/stream
```

返回 `text/event-stream`，每行格式：

```
data: {"node": "risk_assessment", "status": "completed", "timestamp": 1714620000.0, "detail": "预测等级: 红"}
data: {"node": "memory_recall", "status": "completed", ...}
data: {"node": "workflow", "status": "completed", "final_status": "APPROVE"}
```

**切换场景配置：**

```bash
POST /api/v1/agent/scenario/metallurgy
```

响应：

```json
{
  "scenario_id": "metallurgy",
  "scenario_name": "冶金",
  "message": "场景已切换至 冶金，对应知识库子集与校验阈值已更新"
}
```

切换后，Workflow 自动加载 `knowledge_base/metallurgy/` 子集知识库，并将蒙特卡洛阈值调整为 0.85（chemical 场景为 0.90，更严格）。

## 六、模型架构

### Stacking 双层架构

**第一层：7 个异构基学习器**

| 基学习器 | 核心特点 | 关键参数 |
|---------|---------|---------|
| Multinomial LR | L1 正则化 + Softmax 多分类 | `penalty=l1`, `solver=saga`, `multi_class=multinomial` |
| XGBoost | Level-wise 贪婪策略 | `tree_method=hist`, `grow_policy=depthwise` |
| LightGBM | EFB + GOSS 抽样 | `data_sample_strategy=goss`, `enable_bundle=true` |
| CatBoost | 对称树 + 有序提升 | `grow_policy=SymmetricTree` |
| Random Forest | Bagging + 随机特征子集 | `max_features=sqrt` |
| MLP | Dense(128)→64→4, Dropout0.3, ReLU | `epochs=20`, `early_stopping_patience=5` |
| 1D-CNN | Conv1D64→MaxPool→Conv1D128→MaxPool→Flatten→Dense64 | `dropout_rate=0.3` |

**第二层：弹性网络逻辑回归元学习器**

- `LogisticRegression(multi_class='multinomial', penalty='elasticnet', solver='saga', l1_ratio=0.5)`
- 输入维度：28 维（7 模型 × 4 类概率输出）
- OOF（Out-of-Fold）元特征通过 5 折严格时序交叉验证生成，禁止未来信息泄露

### 严格时序交叉验证

`StrictTimeSeriesSplit(n_splits=5)` 按时间列排序后将数据切分为 6 份，第 i 折使用前面所有份训练、预测第 i 份，确保训练数据时间严格早于测试数据。

## 七、NLP 与 RAG 基础设施

### 7.1 实体抽取（BERT-BiLSTM-CRF）

- 架构：`BERT-Base-Chinese` + `BiLSTM` + `CRF`
- 实体标签：
  - `高风险设备`：高炉、转炉、煤气柜、反应釜、储罐等
  - `风险属性`：泄漏、爆炸、火灾、超压、堵塞等
  - `动作`：停炉、撤离、切断、通风、泄压等
  - `法规条款`：安全生产法、判定标准、三同时等
- 训练脚本：`scripts/train_ner.py`，支持 BIO 自动转换
- 回退机制：无预训练模型时自动启用规则词典匹配

### 7.2 向量检索引擎（ChromaDB + SelfQuery）

- 文档切分：按 Markdown 标题层级切分，chunk ≤ 300 字
- 元数据过滤：每个 chunk 携带 `source_file`、`risk_type`、`industry`、`publish_date`、`doc_type`
- SelfQuery：`self_query_retrieve(query, filters, top_k)` 先按元数据预过滤，再执行向量相似度检索
- 嵌入模型：默认 `BAAI/bge-large-zh-v1.5`（可通过 `config.yaml` 配置）

### 7.3 重排序（BGE-Reranker-large）

- 使用 `CrossEncoder` 对向量检索的候选结果进行精排
- 模型：`BAAI/bge-reranker-large`（可通过 `config.yaml` 配置）
- 模型加载失败时自动回退到原始顺序

### 7.4 知识库自动构建

**网络爬虫**（`data/crawler.py`）：
- 基于 `requests + BeautifulSoup4` 定向爬取政府公开法规
- 合规机制：检查 `robots.txt`、请求间隔 ≥1.5s、User-Agent 轮换、仅允许政府域名
- 输出：`knowledge_base/raw_texts/{source}_{date}.md`

**CSV 数据融合**（`scripts/init_knowledge_base.py`）：
- 读取企业 CSV（information / industry_category / safety / risk / aczf_enterprise 等）
- 一键生成 6 个核心知识库文件：
  1. 《工矿风险预警智能体合规执行书.md》— 合规红线 / 工况逻辑 / 处置可行性
  2. 《部门分级审核SOP.md》— 两级终审流程与路由规则
  3. 《工业物理常识及传感器时间序列逻辑.md》— 基于 CSV 设备字段生成阈值/联动/判异规则
  4. 《企业已具备的执行条件.md》— 提取安全设施字段，按企业 ID 聚合为 Markdown 表格
  5. 《类似事故处理案例.md》— 提取 ACCIDENT=1 记录 + 爬取事故调查报告
  6. 《预警历史经验与短期记忆摘要.md》— 预置 P0-P3 归档格式

## 八、三重校验与高风险阻断机制（Step 5）

### 8.1 MARCH 声明级孤立验证

**物理隔离 Checker 节点（LangGraph 风格）**：

```python
from harness.validation import compliance_checker, logic_checker, feasibility_checker, run_march_validation

state = {
    "atomic_propositions": [
        {"id": "p1", "proposition": "企业风险等级判定为红级", "category": "风险定级"},
        {"id": "p2", "proposition": "建议企业加强通风管理", "category": "企业管控"},
    ],
    "raw_data": {...},      # Checker 明确禁止访问
    "decision": {...},      # Checker 明确禁止访问
}

# 分级顺序执行：合规红线 → 工况逻辑 → 处置可行性
# 任意一级不通过即暂停并返回结构化修正反馈
result = run_march_validation(state)
print(result["validation_result"].pass_)   # True / False
print(result["validation_result"].reason)  # 校验详情
```

**独立 Checker 函数**：

| Checker | 职责 | 失败示例 |
|---------|------|---------|
| `compliance_checker` | 合规红线校验 | `"建议企业自行销毁监控记录"` → 拦截 |
| `logic_checker` | 工况逻辑校验 | `"温度超过 100°C 正常"` → 拦截 |
| `feasibility_checker` | 处置可行性校验 | `"建议微型企业立即停产"` → 拦截 |

### 8.2 蒙特卡洛置信度检验

**SamplingNode**：固定输入，独立 LLM 实例执行 20 次采样，每次送 MARCH 校验。

```python
from harness.monte_carlo import SamplingNode

node = SamplingNode(n_samples=20, confidence_threshold=0.85)
result = node.sample(decision={"predicted_level": "红", ...})

print(result.confidence)  # passed / n
print(result.status)      # "APPROVE" 或 "HUMAN_REVIEW"
```

- `confidence >= 0.85` → `APPROVE`
- `confidence < 0.85` → `HUMAN_REVIEW`

### 8.3 三维风险评估

**RiskAssessor**：后果严重度 × 利益相关性 × 执行不可逆性，各分 `极高/高/中/低`，SOP 加权规则计算总分。

```python
from harness.risk_assessment import RiskAssessor

assessor = RiskAssessor()
risk = assessor.assess({"predicted_level": "红"})

print(risk.severity)         # "极高"
print(risk.relevance)        # "极高"
print(risk.irreversibility)  # "极高"
print(risk.total_score)      # 加权总分（满分 4.0）
print(risk.blocked)          # True → 触发分级审核
```

| 维度 | 权重 | 说明 |
|------|------|------|
| 后果严重度 | 0.50 | 一级/红 → 极高 |
| 利益相关性 | 0.30 | 二级/橙 → 高 |
| 执行不可逆性 | 0.20 | 三级/黄 → 中 |

### 8.4 ToolCallInterceptor

拦截所有工具调用请求，注入风险评估，高风险操作自动阻断：

```python
from harness.validation import ToolCallInterceptor

interceptor = ToolCallInterceptor()

# 包装工具函数
safe_delete = interceptor.wrap("delete_file", os.remove)
safe_delete("temp.txt")  # 中风险，允许执行

# 高风险工具调用将被拦截
interceptor.intercept("drop_database", drop_db_func)
# → 抛出 HighRiskBlockedError
```

### 8.5 递归知识合成（RKS）

人工审核驳回后，自动提取四元组并追加写入知识库：

```python
from harness.rks import RecursiveKnowledgeSynthesizer

rks = RecursiveKnowledgeSynthesizer()
result = rks.synthesize_rejection(
    scenario="瓦斯超限未撤人",
    wrong_decision="继续作业",
    correct_decision="立即断电撤人",
    basis_clause="《安全生产法》第四十一条",
    agent_id="review_agent",
)

print(result["commit_id"])  # Git 快照 Commit ID
# 自动追加至：
# - knowledge_base/类似事故处理案例.md
# - knowledge_base/预警历史经验与短期记忆摘要.md
```

## 九、GLM-5 决策智能体 Workflow（Step 6）

### 9.1 架构概览

基于 LangGraph `StateGraph` 构建 5 节点 DAG，全流程异步执行：

```
data_ingestion → risk_assessment → memory_recall → decision_generation → result_push
```

| 节点 | 职责 | 关键输出 |
|------|------|---------|
| `data_ingestion` | 构造 DataFrame，执行特征工程 | `features` |
| `risk_assessment` | Stacking 模型前向推理 | `predicted_level`、`probability_distribution`、`shap_contributions` |
| `memory_recall` | 基于 Top3 SHAP 特征生成 query，调用 `memory.recall_long_term()`（含 SelfQuery 过滤 + BGE-Reranker 精排） | `memory_results` |
| `decision_generation` | 加载 Jinja2 Prompt 模板 → 注入变量 → 调用 GLM-5 生成 JSON → MARCH 回环校验（最多 3 次）→ 蒙特卡洛采样 → 三维风险评估 | `decision`、`final_status` |
| `result_push` | 封装最终输出，确保 `government_intervention` 与 `enterprise_control` 结构完整 | 标准 DecisionResponse |

### 9.2 MARCH 校验回环

决策生成后自动进入 MARCH 孤立验证，不通过时注入修正反馈并回环重生成，最多 3 次：

```python
from agent.workflow import DecisionWorkflow

wf = DecisionWorkflow(scenario_id="chemical")
result = await wf.run_async(enterprise_id="E001", raw_data={...})

print(result["march_result"]["passed"])   # True / False
print(result["march_result"]["retry_count"])  # 0~3
```

### 9.3 蒙特卡洛与三维风险路由

| 条件 | 结果 | 路由 |
|------|------|------|
| MARCH 最终未通过 | `REJECT` | 返回拦截原因 |
| 蒙特卡洛 `confidence < threshold` | `HUMAN_REVIEW` | 转人工审核 |
| 三维风险 `total_score >= threshold` | `HUMAN_REVIEW` | 转分级审核 |
| 全部通过 | `APPROVE` | 正常推送 |

> chemical 场景阈值更严格：`confidence_threshold=0.90`、`risk_threshold=2.2`；metallurgy/dust 为 `0.85` / `2.5`。

### 9.4 场景化配置驱动

```python
from agent.workflow import DecisionWorkflow, ScenarioConfig

# 初始化时指定场景
wf = DecisionWorkflow(scenario_id="dust")

# 运行时切换场景（重建状态图）
wf.set_scenario("metallurgy")

# 场景配置明细
scenarios:
  chemical:      # 危化品：阈值严格
    kb_subdir: "knowledge_base/chemical"
    prompt_template: "prompts/decision_v1_chemical.txt"
    confidence_threshold: 0.90
    risk_threshold: 2.2
  metallurgy:    # 冶金：标准阈值
    kb_subdir: "knowledge_base/metallurgy"
    prompt_template: "prompts/decision_v1_metallurgy.txt"
    confidence_threshold: 0.85
    risk_threshold: 2.5
  dust:          # 粉尘涉爆：标准阈值
    kb_subdir: "knowledge_base/dust"
    prompt_template: "prompts/decision_v1_dust.txt"
    confidence_threshold: 0.85
    risk_threshold: 2.5
```

### 9.5 LLM 客户端（OpenAI 兼容）

```python
from llm.glm5_client import OpenAICompatibleClient

client = OpenAICompatibleClient()

# 普通文本生成
text = await client.generate("请分析以下风险数据...", temperature=0.3, max_tokens=4096)

# 强制 JSON 结构化输出
json_data = await client.generate_json(
    prompt="请输出 JSON 格式的决策建议...",
    output_schema=MyPydanticModel,  # 可选校验
    temperature=0.3
)
```

- 当前 provider 由 `llm.provider` 或 `LLM_PROVIDER` 决定
- 可在 `llm.providers` 中新增任意 OpenAI Chat Completions 兼容模型
- 当前 provider 可用 `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` 临时覆盖
- provider 专属覆盖遵循 `LLM_<PROVIDER>_API_KEY` / `MODEL` / `BASE_URL`
- 3 次重试 + 指数退避

## 十、模型自动迭代与 CI/CD 工程化（Step 7）

### 10.1 整体流程

```
监控触发 → 自动训练流水线 → Git Flow 分支 → 回归测试 → Drift 分析 → 两级终审 → 预生产试运行 → 灰度发布
```

| 阶段 | 模块 | 关键动作 |
|------|------|---------|
| **监控触发** | `iteration.monitor` | 新增样本 >5000 或近期 F1<0.85 触发 `should_retrain()` |
| **自动训练** | `iteration.pipeline` | 数据清洗 → 特征工程 → 时序 CV → 候选模型序列化 |
| **Git Flow** | `iteration.gitflow` | 从 `main` 创建 `feature/model_v{x}`，生成 PR 模板，配置分支保护 |
| **回归测试** | `iteration.regression_test` | 同源测试集对比：准确率/精确率/召回率/F1/AUC + SHAP Kendall Tau 稳定性 |
| **Drift 分析** | `iteration.drift_analysis` | 基学习器权重差异、元学习器系数变化、Pipeline 步骤变更检测 |
| **两级终审** | `iteration.approval_fsm` | `PENDING_REVIEW → SECURITY_APPROVED → TECH_APPROVED → STAGING → PRODUCTION → ARCHIVED` |
| **预生产监控** | `iteration.staging_monitor` | 每 5 分钟采样：延迟 P99、异常率、置信度分布、输入漂移；24h 后自动出报告 |
| **灰度发布** | `iteration.canary` | 流量比例阶梯切换：`0.0 → 0.1 → 0.5 → 1.0` |

### 10.2 监控触发

```python
from iteration.monitor import ModelMonitor

monitor = ModelMonitor()

# 记录新增样本批次
monitor.record_new_samples(batch_size=5001, source="api_upload")

# 记录模型评估性能
monitor.record_performance("v1", accuracy=0.82, precision=0.81, recall=0.80, f1_score=0.84)

# 判断是否触发重训练
should, reason, details = monitor.should_retrain()
# → (True, "SAMPLE_THRESHOLD_EXCEEDED", {"cumulative_samples": 5001, "threshold": 5000})
# 或 (True, "PERFORMANCE_DEGRADED", {"recent_f1": 0.84, "threshold": 0.85})
```

### 10.3 自动训练流水线

```bash
# 命令行入口
python -m iteration.pipeline
```

```python
from iteration.pipeline import TrainingPipeline

pipeline = TrainingPipeline()
result = pipeline.run(model_version="v2")
# result → {"model_version": "v2", "model_path": "models/stacking_risk_v2.pkl", "metrics": {...}, "status": "SUCCESS"}
```

### 10.4 Git Flow 分支管理

```python
from iteration.gitflow import GitFlowManager

gm = GitFlowManager()

# 从 main 创建 feature 分支
branch = gm.create_feature_branch("v2")  # → feature/model_v2

# 自动生成 PR 描述（含新旧模型性能对比与 SHAP 稳定性）
pr_body = gm.generate_pr_template(old_metrics={"test_f1": 0.84}, new_metrics={"test_f1": 0.87}, shap_stability=0.82)

# 配置 main 分支保护（禁止直接推送，强制 PR 审核）
gm.protect_main_branch()
```

### 10.5 回归测试

```bash
python -m iteration.regression_test \
  --old models/stacking_risk_v1.pkl \
  --new models/stacking_risk_v2.pkl \
  --test data/test.csv \
  --output regression_report.json
```

报告输出示例：

```json
{
  "status": "PASS",
  "old_metrics": {"accuracy": 0.85, "precision": 0.84, "recall": 0.83, "f1": 0.84, "auc": 0.92},
  "new_metrics": {"accuracy": 0.88, "precision": 0.87, "recall": 0.86, "f1": 0.87, "auc": 0.94},
  "shap_stability": {"kendall_tau": 0.82, "passed": true}
}
```

### 10.6 两级终审状态机

```python
from iteration.approval_fsm import ApprovalFSM

fsm = ApprovalFSM()
rec = fsm.create_record("approval-001", "v2")

# 安全监管负责人审批
rec = fsm.approve("approval-001", "security", "张三")
# → status: SECURITY_APPROVED

# 技术管理负责人审批
rec = fsm.approve("approval-001", "tech", "李四")
# → status: TECH_APPROVED

# 推进到预生产试运行
rec = fsm.promote_to_staging("approval-001")
# → status: STAGING

# 试运行通过后推进到生产
rec = fsm.promote_to_production("approval-001")
# → status: PRODUCTION
```

审批节点变更时自动发送邮件/Webhook 通知，全流程写入 AgentFS `memory/approval_{record_id}.log`。

### 10.7 预生产试运行监控

```python
from iteration.staging_monitor import StagingMonitor

monitor = StagingMonitor(model_version="v2", duration_hours=24)
monitor.start()

# 每 5 分钟采样（实际部署中由定时任务触发）
monitor.record_sample(latency_ms=230, is_anomaly=False, confidence=0.92)

# 24h 后生成报告
report = monitor.generate_report()
# report["status"] → "CANARY_READY" 或 "ROLLBACK"
```

### 10.8 灰度发布

```python
from iteration.canary import CanaryDeployment

cd = CanaryDeployment()

# 阶梯切换流量比例
cd.set_traffic_ratio("v2", 0.1, operator="ops")   # 10% 流量
cd.set_traffic_ratio("v2", 0.5, operator="ops")   # 50% 流量
cd.set_traffic_ratio("v2", 1.0, operator="ops")   # 100% 流量

# 自动晋升到下一阶梯
cd.promote("v2")

# 回滚
cd.rollback("v2")
```

### 10.9 CI/CD 配置

`.github/workflows/ci.yml` 已配置 GitHub Actions：

- **代码规范**：flake8 语法检查 + black 格式检查
- **单元测试**：pytest 全量测试
- **回归测试**：自动调用 `iteration.regression_test` 对比新旧模型

## 十一、特征工程

### 基础处理

- **二值型**：统一映射为 0/1，1=存在风险/高风险状态
- **数值型**：99% 分位数截断 → 对数变换 → Min-Max 归一化
- **枚举型**：自动推断风险顺序并映射至 [0,1]
- **文本型**：完整性评分（空值/短文本赋高分）+ 高危词命中统计
- **行业分类**：按行业风险基准表映射系数（采矿/危化品/金属冶炼 1.5，制造业 1.0 等）

### 特殊逻辑（覆盖特征汇总表全部字段）

| 特殊逻辑 | 说明 | 对应 Transformer |
|---------|------|----------------|
| 干湿除尘比例 | 基于除尘记录计算干式/湿式除尘占比 | `DustRemovalRatioTransformer` |
| 有限空间 OR 逻辑 | 三字段（有限空间/密闭空间/受限空间）取 OR | `ConfinedSpaceORTransformer` |
| 危化品 OR 逻辑 | 多字段（危化品/危险化学品/化学品）取 OR | `HazardousChemicalORTransformer` |
| 时间衰减加权 | 当年 1.0 / 前一年 0.7 / 前两年 0.5 | `TimeDecayWeightTransformer` |
| 地理围栏 | 经纬度射线法比对化工园区边界 | `GeoFenceTransformer` |
| 按企业聚合 | 隐患加权、文书加权（立案权重 3 > 检查权重 1） | `EnterpriseAggregator` |
| 数据可信度系数 | 检查来源映射：执法/专项检查 4 > 整改复查/立案 3 > 日常检查 2 > 企业自报 1 | `DataCredibilityTransformer` |

## 十二、项目结构

```
mining_risk_agent/
├── api/                  # FastAPI 接口层
│   ├── main.py
│   └── routers/
│       ├── data.py
│       ├── prediction.py   # 风险预测 + 决策智能体 Workflow 路由
│       ├── knowledge.py
│       └── audit.py
├── agent/                # LangGraph 决策工作流（Step 6）
│   ├── __init__.py
│   └── workflow.py       # 5节点DAG / 场景化配置 / MARCH回环 / 蒙特卡洛 / 三维风险
├── llm/                  # 大模型客户端
│   ├── __init__.py
│   └── glm5_client.py    # OpenAI兼容LLM / async生成 / JSON强制输出 / 指数退避重试
├── data/                 # 数据模块
│   ├── loader.py
│   ├── preprocessor.py   # 特征工程（含7个特殊逻辑Transformer + csv_to_markdown_table）
│   └── crawler.py        # 政府法规定向爬虫
├── model/                # 模型模块
│   ├── stacking.py       # 7基学习器 + StackingRiskModel
│   ├── train.py          # 严格时序CV训练流程
│   └── visualization.py  # SHAP/混淆矩阵/ROC/PR/训练曲线/权重图
├── iteration/            # 模型自动迭代与 CI/CD 工程化（Step 7）
│   ├── monitor.py        # 样本/F1 双阈值监控，should_retrain() 触发信号
│   ├── pipeline.py       # 自动训练流水线：清洗→特征工程→时序CV→序列化
│   ├── gitflow.py        # Git Flow 分支管理 + PR 模板 + 分支保护
│   ├── regression_test.py # 新旧模型背靠背对比（准确率/精确率/召回率/F1/AUC/SHAP稳定性）
│   ├── drift_analysis.py # 模型权重与 Pipeline 逻辑变更检测
│   ├── approval_fsm.py   # 两级终审状态机（SECURITY→TECH→STAGING→PRODUCTION→ARCHIVED）
│   ├── staging_monitor.py # 预生产 24h 试运行监控（延迟/异常率/置信度/漂移）
│   └── canary.py         # 灰度发布流量控制（0.1→0.5→1.0 阶梯）
├── harness/              # Harness 核心管控
│   ├── agentfs.py        # SQLite 虚拟文件系统 + Git 版本控制
│   ├── knowledge_base.py # 6 大 Markdown 知识库管理
│   ├── memory.py         # 长短期混合记忆（P0-P3 / RAG）
│   ├── proposer.py       # 决策 → JSON 原子命题列表
│   ├── validation.py     # MARCH 三重校验 + LangGraph Checker 节点 + ToolCallInterceptor
│   ├── monte_carlo.py    # MonteCarloValidator + SamplingNode（独立 LLM 20 次采样）
│   ├── risk_assessment.py # RiskAssessor 三维风险评估（极高/高/中/低 + SOP 加权）
│   ├── rks.py            # 递归知识合成（四元组提取 + 知识库追加 + Git 快照）
│   ├── model_iteration.py # 旧版 Git Flow + CI + 联合终审（iteration/ 模块已替代并扩展）
│   ├── nlp_pipeline.py   # BERT-BiLSTM-CRF 实体抽取
│   ├── vector_store.py   # ChromaDB + SelfQuery 检索
│   └── reranker.py       # BGE-Reranker-large 精排
├── scripts/              # 工具脚本
│   ├── init_knowledge_base.py  # 企业CSV → 6大知识库Markdown
│   ├── snapshot_agentfs.py # AgentFS 快照（WAL checkpoint → Git 提交 → index.json）
│   ├── validate_memory.py    # Step 4 长短期混合记忆系统手动验证
│   ├── train_ner.py      # NER模型训练（支持BIO自动转换）
│   └── train_model.py
├── frontend/             # 前端 SPA（React + Vite + ECharts）
│   ├── Dockerfile        # 多阶段：node 构建 → nginx 托管 + 反向代理
│   ├── nginx.conf        # /api、/health、/docs 反向代理 + SSE 透传
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/          # API 客户端、TS 类型、POST SSE 解析
│   │   ├── components/   # SCADA 通用组件（StatusBar/Sidebar/Tabs/ScadaCard 等）
│   │   ├── pages/        # 4 个 Tab 页面
│   │   ├── data/         # demoData.ts（与后端 demo_data.py 同步）
│   │   └── styles/       # SCADA 暗色主题
│   ├── demo_data.py      # 后端 Mock 降级仍依赖此模块（保留）
│   ├── __init__.py
│   └── app_legacy_streamlit.py  # 旧 Streamlit 单文件实现（已停用，仅供参考）
├── utils/                # 工具模块
│   ├── config.py
│   ├── logger.py
│   └── exceptions.py
├── tests/                # 单元测试
│   ├── test_data.py
│   ├── test_model.py
│   ├── test_harness.py
│   ├── test_validation.py    # Step 5 三重校验（合规拦截 / 蒙特卡洛 / 三维风险 / RKS）
│   ├── test_memory.py        # 长短期混合记忆系统（P0-P3 / tiktoken / LRU / 归档 / RAG）
│   ├── test_agentfs.py       # AgentFS 沙箱 / POSIX接口 / 快照回滚测试
│   ├── test_crawler.py       # Mock HTTP 爬虫测试
│   ├── test_nlp_pipeline.py  # BIO编解码 + 实体抽取测试
│   ├── test_vector_store.py  # 文档切分 + SelfQuery 元数据过滤测试
│   ├── test_reranker.py      # 重排序回退逻辑测试
│   └── test_agent_workflow.py # Step 6 决策智能体Workflow（正常流 / MARCH回环 / 蒙特卡洛阻断 / 场景切换）
├── prompts/              # Jinja2 Prompt 模板（场景化）
│   ├── decision_v1_chemical.txt
│   ├── decision_v1_metallurgy.txt
│   └── decision_v1_dust.txt
├── models/               # 训练产出模型
│   ├── stacking_risk_v1_stable.pkl
│   └── preprocessing_pipeline.pkl
├── reports/figures/      # 可视化报告输出目录
├── knowledge_base/       # Markdown 知识库（运行时生成）
│   ├── chemical/         # 危化品场景知识库子集
│   ├── metallurgy/       # 冶金场景知识库子集
│   ├── dust/             # 粉尘涉爆场景知识库子集
│   └── raw_texts/        # 爬虫抓取的原始法规文本
├── memory/               # 长期记忆归档库（运行时生成）
│   ├── 核心指令归档.md
│   ├── 风险事件归档.md
│   ├── 处置经验归档.md
│   └── 系统日志归档.md
├── config.yaml           # 全局配置（含 llm.provider / llm.providers + scenarios 配置节）
├── requirements.txt      # 后端 API 精简运行时依赖（Docker 默认）
├── requirements-api.txt  # requirements.txt 的别名，便于 CI/文档引用
├── requirements-ml.txt   # 训练 / SHAP / XGBoost / LightGBM / CatBoost / TensorFlow
├── requirements-rag.txt  # RAG / NLP / ChromaDB / sentence-transformers / PyTorch
├── requirements-legacy-frontend.txt # 旧 Streamlit 前端依赖（可选）
├── requirements-dev.txt  # 测试、爬虫、文档与开发工具
├── requirements-full.txt # 聚合完整 Python 依赖
├── Dockerfile
├── docker-compose.yml
├── README.md
├── DEPLOY.md
└── KNOWLEDGE_BASE.md
```

## 十三、前端演示指南

### 13.1 界面概览

启动前端后访问 `http://localhost:8501`，可见 **4 个标签页**：

| 标签页 | 核心功能 | 路演亮点 |
|--------|----------|----------|
| 🎯 企业风险预测 | 企业ID输入、场景选择、模拟数据填充、CSV/Excel上传、风险仪表盘、概率分布图、SHAP Top3、政府干预/企业管控决策卡片、三重校验拦截状态、SSE节点日志 | **核心演示页**，5秒内完成从数据输入到决策输出的完整闭环 |
| 📚 知识库与记忆系统 | 6大知识库文件列表、Markdown内容预览（限前1000字）、短期记忆P0-P3优先级演示与LRU清理、长期记忆RAG召回（含来源文件与重排序分数） | 技术亮点：AgentFS + 长短期混合记忆 + RAG精排 |
| 🔄 模型迭代与CI/CD | 模型版本时间线（v1→v2→v3）、迭代状态仪表盘、审批流程可视化、灰度流量比例进度条、触发模拟迭代按钮（8阶段动画） | 工程化亮点：自动训练→回归测试→两级终审→灰度发布 |
| ⚙️ 系统配置与API文档 | GLM-5连通状态检测、当前场景配置参数展示、Swagger文档内嵌链接、核心接口速查表 | 系统可观测性，方便回答评委技术问题 |

### 13.2 演示截图占位

> 以下截图请在路演前补充替换：

```
assets/
├── screenshots/
│   ├── tab1_risk_prediction.png      # 企业风险预测页（红级风险+决策卡片）
│   ├── tab2_knowledge_memory.png     # 知识库与记忆系统页
│   ├── tab3_iteration_cicd.png       # 模型迭代与CI/CD页
│   ├── tab4_system_config.png        # 系统配置与API文档页
│   └── dashboard_overview.png        # 整体界面概览（1920×1080）
```

### 13.3 快速演示脚本（路演3分钟版）

**第1分钟：核心预测闭环**
1. 打开「🎯 企业风险预测」标签页
2. 选择场景：🧪 危险化学品 → 点击「🎲 模拟数据填充」→ 点击「🚀 执行预测」
3. 展示：**红色风险等级闪烁警告**、概率分布饼图、SHAP Top3 归因
4. 展开**政府干预卡片**（蓝色边框）：24小时内携带气体检测仪登门核查
5. 展开**企业管控卡片**（橙色边框）：DCS紧急停车、设备编号、压力设定值
6. 展示**三重校验状态**：MARCH通过、蒙特卡洛置信度进度条、三维风险评分

**第2分钟：场景切换与技术深度**
1. 左侧边栏切换场景为 🔩 冶金 → 重新执行预测
2. 对比返回JSON中 `scenario_id` 变化，阈值从 0.90/2.2 变为 0.85/2.5
3. 切换至「📚 知识库与记忆系统」
4. 展示6大知识库文件列表，点击预览《类似事故处理案例.md》
5. 演示短期记忆：添加P0/P1/P2/P3记忆 → 点击「触发清理」→ 展示清理日志
6. 演示长期记忆召回：输入"瓦斯泄漏" → 展示RAG召回结果与重排序分数

**第3分钟：工程化与系统可信度**
1. 切换至「🔄 模型迭代与CI/CD」
2. 展示模型版本时间线 v1→v2→v3，F1分数持续提升
3. 展示审批流程：安全负责人✓ / 技术负责人状态
4. 点击「🚀 触发模拟迭代」→ 观看8阶段流水线动画
5. 切换至「⚙️ 系统配置与API文档」
6. 展示GLM-5连通状态、场景配置参数、Swagger链接
7. **收尾金句**："即使GLM-5 API不可用，系统也会自动Mock降级，保证路演绝不中断"

### 13.4 Mock 降级机制

当后端服务或 GLM-5 API 不可用时，系统会自动启用 **两级降级**：

1. **后端 Mock**：`api/routers/prediction.py` 中 `_generate_mock_decision()` 根据当前场景返回差异化 Mock 数据（仍走 HTTP 200，并附 `mock=true`）
2. **前端本地 Mock**：`frontend/src/data/demoData.ts` 中 `generateMockDecision(scenarioId)` 提供与后端格式完全一致的兜底 JSON；后端不可达时由前端 `RiskPredictionPage` 直接调用，路演不中断

**仅启动前端（无后端模式）**：
```bash
cd mining_risk_agent/frontend
npm install
npm run dev
# 浏览器打开 http://localhost:5173 ；当 /api 调用失败时，
# 页面会自动调用本地 generateMockDecision() 显示场景化 Mock 决策
# 所有预测请求将自动使用 frontend/demo_data.py 中的本地 Mock 数据
```

三组场景化Mock数据特征对比：

| 场景 | 预测等级 | 最终状态 | 置信度 | 风险阈值 | 决策差异 |
|------|----------|----------|--------|----------|----------|
| chemical（危化品） | 红 | HUMAN_REVIEW | 0.78 < 0.90 | 3.8 ≥ 2.2 | 24小时联合执法、紧急停车、转人工审核 |
| metallurgy（冶金） | 橙 | APPROVE | 0.88 ≥ 0.85 | 2.4 < 2.5 | 72小时专项检查、降低鼓风量、正常推送 |
| dust（粉尘涉爆） | 红 | REJECT | 0.72 < 0.85 | 3.9 ≥ 2.5 | 立即全面停产、MARCH 3次重试失败、阻断推送 |

### 13.5 前端技术实现

| 技术 | 用途 | 关键实现 |
|------|------|----------|
| React 18 + TypeScript 5 | 页面框架 | `App.tsx` 中以 `useState` 维护 scenario / health / iteration 全局状态，`Tabs` 组件控制 4 个 Page |
| Vite 5 | 构建与开发态代理 | `vite.config.ts` 中 `server.proxy` 把 `/api`、`/health` 转发到 `http://localhost:8000`，热更新 < 1s |
| ECharts 5 | 数据可视化 | `ProbabilityChart` 环形概率分布、`ShapChart` SHAP Top5 水平条形图，全部走 `echarts-for-react` |
| 自定义 SCADA CSS | 投影级样式 | `src/styles/scada.css` 内置 SCADA 暗色主题、`risk-red-pulse` 脉冲动画、`glow-red/orange/yellow/blue` 风险光晕、Timeline / Validation / Memory 卡片样式 |
| `fetch + ReadableStream` | POST SSE 流式节点 | `api/client.ts:streamDecision` 自行解析 `data:` 行，弥补 `EventSource` 不支持 POST 的限制 |
| 本地 Mock 兜底 | 后端离线降级 | `src/data/demoData.ts` 镜像后端 `frontend/demo_data.py` 的三场景 Mock 决策；`/api/v1/agent/decision` 失败时由前端直接渲染本地 Mock |
| Nginx 反向代理 | 同源避免跨域 | 前端容器内 Nginx 把 `/api`、`/health`、`/docs` 转发到 `api:8000`，并关闭 `proxy_buffering` 以保留 SSE 流 |

### 13.6 演示数据字段说明

`frontend/demo_data.py`（后端 Mock 路径）与 `frontend/src/data/demoData.ts`（前端 Mock 路径）中预置的 3 组高危企业数据，字段保持一致；每组均包含以下核心字段：

| 字段类别 | 示例字段 | 说明 |
|----------|----------|------|
| 企业基础信息 | `企业ID`、`企业名称`、`管理类别`、`风险等级` | 用于唯一标识与基础分类 |
| 人员与经营 | `企业职工总人数`、`专职安全生产管理人员数`、`上一年经营收入`、`固定资产` | 规模与投入指标 |
| 风险状态 | `是否发生事故`、`是否发现问题隐患`、`具体风险描述` | 直接驱动风险等级的关键输入 |
| 场景专属字段 | `危化品储罐数量`（chemical）、`高炉容积`（metallurgy）、`抛光工位数量`（dust） | 各场景特有的高风险设备/工艺指标 |
| 安全设施 | `消防设施完好率`、`气体检测仪在线率`、`防爆电气覆盖率` | 体现企业本质安全水平 |

## 十四、检查点验证

以下检查点可用于路演前功能验证与评委问答准备：

| 检查点 | 验证方法 | 预期结果 |
|--------|----------|----------|
| 1. 4个标签页正常切换 | 启动前端后点击各标签页 | 无报错，内容正常渲染 |
| 2. 模拟数据填充 + 预测 | 「企业风险预测」页点击「🎲 模拟数据填充」→「🚀 执行预测」 | 5秒内返回风险等级与决策建议（Mock或真实） |
| 3. 可视化组件完整展示 | 查看预测结果区域 | 概率分布饼图、SHAP Top3 水平条形图、政府干预卡片（蓝边框）、企业管控卡片（橙边框）全部可见 |
| 4. 场景切换有差异 | 侧边栏切换 chemical→metallurgy→dust，分别执行预测 | 返回JSON中 `scenario_id` 与阈值不同：chemical(0.90/2.2)、metallurgy(0.85/2.5)、dust(0.85/2.5) |
| 5. 知识库文件列表与预览 | 「知识库与记忆系统」页 | 列出6个md文件，选择后可预览前1000字Markdown内容 |
| 6. 记忆系统演示 | 短期记忆添加P0-P3 → 触发清理；长期记忆输入"瓦斯泄漏"查询 | 清理日志展示优先级移除规则；RAG召回展示来源文件与重排序分数 |
| 7. 模型迭代动画 | 「模型迭代与CI/CD」页点击「🚀 触发模拟迭代」 | 8阶段进度条动画播放，从监控触发到灰度发布 |
| 8. 投影适配性 | 在1920×1080分辨率下全屏查看 | 无横向滚动条，字体清晰，布局不重叠 |

**Mock降级验证**：关闭后端服务（`docker stop mining_risk_api`或直接不启动API），刷新前端页面，点击「执行预测」仍能返回完整的场景化Mock决策JSON，证明路演不会因API或网络问题中断。

## 十五、运行测试

```bash
# AgentFS 虚拟文件系统测试（沙箱 / ls / stat / 快照 / 回滚）
pytest tests/test_agentfs.py -v

# Harness 测试（知识库 / 记忆 / 校验）
pytest tests/test_harness.py -v

# 记忆系统测试（P0-P3 清理 / P1 摘要归档 / RAG 召回）
pytest tests/test_memory.py -v

# 爬虫测试（Mock HTTP 爬取与 Markdown 转换）
pytest tests/test_crawler.py -v

# NLP 实体抽取测试（BIO 编解码、规则/模型抽取）
pytest tests/test_nlp_pipeline.py -v

# 向量检索测试（文档切分、SelfQuery 元数据过滤）
pytest tests/test_vector_store.py -v

# 重排序测试
pytest tests/test_reranker.py -v

# 三重校验与高风险阻断测试（Step 5：合规拦截 / 蒙特卡洛 / 三维风险 / RKS）
pytest tests/test_validation.py -v

# 决策智能体 Workflow 测试（Step 6：正常流 / MARCH回环 / 蒙特卡洛阻断 / 场景切换）
pytest tests/test_agent_workflow.py -v

# 模型迭代与 CI/CD 测试（Step 7：监控阈值 / Git Flow / 回归测试 / 审批状态机 / 灰度切换）
pytest tests/test_iteration.py -v

# 全部测试（含覆盖率）
pytest tests/ -v --cov=mining_risk_agent --cov-report=html
```

### Demo Replay 数据源（模型迭代路演）

当前模型迭代系统默认使用 `DemoReplayDataSource`，从 `data/demo/*.json` 读取可回放演示批次。每个批次都包含 `metadata.batch_id`、`sample_count`、`risk_sample_count`、`recent_f1` 和 `description`，后端会基于这些元信息和批次内的门禁结果生成真实接口响应、回放报告和可追踪记录，而不是把触发逻辑写死在前端。

已内置 5 类路演场景：

| batch_id | 场景 |
|----------|------|
| `normal_batch` | 正常批次，不触发重训 |
| `risk_spike_retrain` | 新增风险样本超过 5000，触发重训 |
| `f1_drop_retrain` | 近期 F1 低于 0.85，触发重训 |
| `regression_block` | 新模型退化，回归测试门禁阻断 |
| `drift_high_block` | Drift 高风险，Drift 门禁阻断 |

接口：

| 接口 | 说明 |
|------|------|
| `GET /api/v1/iteration/data-source` | 查看当前迭代数据源配置 |
| `GET /api/v1/iteration/demo-batches` | 列出所有演示批次元信息 |
| `GET /api/v1/iteration/demo-batches/{batch_id}` | 加载某个演示批次和样本预览 |
| `POST /api/v1/iteration/demo-batches/{batch_id}/load` | 回放批次，更新后端迭代状态，写入 `demo_replay_runs` 和 `reports/demo_replay/{batch_id}_report.json` |

未来接入真实企业数据库时，只需实现 `EnterpriseDataSource` 的 `list_batches()` 与 `load_batch(batch_id)`，并在 `config.yaml` 的 `iteration.data_source.type` 中切换工厂实现；监控阈值、回放报告和门禁判断仍由后端迭代模块统一处理。

## 十六、常见问题

**Q1：路演现场没有网络/API Key 怎么办？**
> 系统支持 **零配置运行**。`docker compose up -d --build` 启动后即使后端 GLM-5 不可用，前端也会自动调用本地 `src/data/demoData.ts` 的 Mock 决策 JSON。仅启动前端开发态：`cd mining_risk_agent/frontend && npm run dev`，浏览器打开 <http://localhost:5173> 即可。

**Q2：如何切换演示场景？**
> 左侧边栏「场景配置」下拉框选择 chemical / metallurgy / dust，点击「执行预测」即可看到不同场景的差异化决策结果（阈值、风险等级、处置建议均不同）。

**Q3：界面在投影仪上显示不清晰？**
> 已针对 1920×1080 投影优化：全局使用系统无衬线字体、`layout="wide"` 铺满屏幕、无横向滚动条。建议浏览器按 F11 进入全屏模式。

**Q4：如何添加自定义企业数据？**
> 在「企业风险预测」页左侧 JSON 输入框中直接编辑，或通过「上传 CSV/Excel」组件导入。系统会自动合并上传文件的第一行数据到预测请求中。

**Q5：知识库文件显示乱码？**
> 知识库文件统一使用 UTF-8 编码。Windows 环境下如遇乱码，请确保编辑器/终端编码设置为 UTF-8。

## 十七、许可证

本项目仅供研究与学习使用。
