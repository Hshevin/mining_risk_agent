# mining_risk_agent 架构全面排查报告

生成时间：2026-05-04

## 结论摘要

当前项目的主体架构可以跑通：React/Vite 前端通过 Nginx 代理到 FastAPI，后端提供传统预测链路和 LangGraph 决策智能体链路，配置以 `config.yaml` 和环境变量合并为主。代码结构与 README 的大方向一致，但实际实现更偏“路演可用、失败自动演示降级”，距离生产级风险预警系统还有明显差距。

最高优先级问题集中在四类：失败语义被 Mock 掩盖、配置/知识库/迭代接口缺少鉴权、`.env` 可能被打进后端镜像、前端一次预测可能触发两次完整决策工作流。

## 系统拓扑

- 前端：`frontend/Dockerfile` 构建 React/Vite SPA，`frontend/nginx.conf` 托管静态资源并代理 `/api/`、`/health`、`/docs`、`/redoc`、`/openapi.json` 到 `api:8000`。
- 后端：`api/main.py` 注册数据、预测、知识库、审计、智能体、模型迭代路由。
- 决策链路：`api/routers/prediction.py` 的 `/api/v1/agent/decision` 调用 `agent/workflow.py` 中 `DecisionWorkflow.run_async()`。
- 模型链路：传统预测和智能体工作流分别在 `api/routers/prediction.py` 与 `agent/workflow.py` 内维护 `_model`、`_pipeline`、`_memory` 懒加载全局变量。
- 配置链路：`utils/config.py` 从 `config.yaml` 读取配置，再用 `LLM_*`、`GLM5_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY` 等环境变量覆盖。
- 持久化：`docker-compose.yml` 将 `data`、`models`、`logs`、`knowledge_base`、`memory` 挂载到后端容器。

## 高风险问题

### 1. 决策失败会返回 HTTP 200 + Mock

证据：`api/routers/prediction.py` 中 `/api/v1/agent/decision` 在 workflow 返回不完整或抛异常时，返回 `_generate_mock_decision()`，并只设置 `mock=true`。

影响：调用方、监控、审计很难区分“真实风险决策”与“演示降级数据”。如果上层只看 HTTP 200 或 `final_status`，会把故障当成成功。

建议：生产模式下默认返回 5xx 或明确的业务错误；演示模式可以保留 Mock，但需要通过显式配置开启，并在响应头、日志、审计中标记降级原因。

### 2. 运行时敏感配置接口无鉴权

证据：`api/main.py` 注册了 `/api/v1/agent/llm`、`/api/v1/knowledge/write`、`/api/v1/knowledge/append`、`/api/v1/iteration/trigger`、`/api/v1/audit/query` 等路由；`api/` 目录内未发现 `Depends`、`Security`、`Authorization`、Bearer token 等鉴权实现。

影响：只要服务可达，就能切换 LLM provider、提交 API Key、修改知识库、触发训练、查询审计数据。`docker-compose.yml` 同时暴露了 `8000:8000`，风险更高。

建议：至少为配置、知识库写入、迭代、审计接口增加 API token 或内网访问控制；生产环境不直接暴露 8000，只从前端反代或内网网关进入。

### 3. `.env` 可能进入后端镜像层

证据：`.gitignore` 忽略 `.env`，但 `.dockerignore` 没有排除 `.env`；`Dockerfile` 使用 `COPY . .`。`docker compose config` 也确认本地环境会展开真实 LLM Key，本报告不展示密钥值。

影响：如果本地存在 `.env`，构建后端镜像时可能把密钥文件复制到 `/app/.env`，即使容器运行时不用，也会留在镜像层中。

建议：在 `.dockerignore` 中加入 `.env`、`.env.*`、`!.env.example`；避免发布本地构建镜像；必要时轮换已暴露密钥。

### 4. 前端流式预测会再次调用普通决策

证据：`frontend/src/pages/RiskPredictionPage.tsx` 在 `useStream` 开启时先 `await streamDecision(...)`，随后无论成功与否都会 `postDecision(...)`。后端 `_decision_stream()` 注释明确写着“避免再次 run_async 造成重复日志与重复模型调用”，但前端仍触发了第二次普通决策。

影响：同一次点击可能执行两遍 LangGraph、两次模型推理、两次 LLM 调用，并产生两套不完全一致的状态与日志。

建议：让 SSE 最后一条消息携带完整 `DecisionResponse`，或前端在 SSE 成功后不再调用普通接口；保留普通接口只作为 SSE 失败后的回退。

## 中风险问题

### 5. CORS 配置不适合生产

证据：`api/main.py` 使用 `allow_origins=["*"]` 与 `allow_credentials=True`。

影响：该组合语义不清，生产环境容易误判跨域策略。虽然当前推荐浏览器走前端 Nginx 同源代理，但直连 8000 时配置仍过宽。

建议：按部署域名收窄 `allow_origins`，或者生产环境关闭跨域凭据。

### 6. async 路由中执行同步重任务

证据：`api/routers/prediction.py` 的 `predict()` 在 `async def` 中直接执行 pandas、pipeline、模型推理；`api/routers/iteration.py` 的 `trigger_iteration()` 直接调用 `TrainingPipeline.run()`；`api/routers/audit.py` 在 async 路由中使用同步 sqlite3。

影响：高并发或训练触发时会阻塞事件循环，影响 SSE、健康检查和其他请求。

建议：将模型推理和训练放入线程池、任务队列或独立 worker；SQLite 审计至少封装到同步依赖或后台任务，避免在主事件循环里执行重 IO。

### 7. 场景状态依赖全局工作流实例

证据：`DecisionWorkflow.run_async()` 的 `scenario_id` 来自 `self.scenario.scenario_id`，而不是请求体；场景切换通过 `/api/v1/agent/scenario/{scenario_id}` 修改全局 `_workflow`。

影响：多用户并发时，一个用户切换场景会影响其他用户的后续决策。前端虽然本地保存 `scenario`，但后端实际场景是全局状态。

建议：将 `scenario_id` 作为 `DecisionRequest` 的显式字段，并为每次请求创建或选择对应场景配置，避免全局可变状态。

### 8. 配置和部署文档存在漂移

证据：`docker-compose.yml` 默认构建参数受本地 `.env` 影响；本次 `docker compose config` 解析为 `requirements-deploy-rag.txt`，而 `.env.example` 写默认 `requirements-deploy.txt`，`DEPLOY.md` 部分段落仍描述“默认只安装 requirements.txt”。

影响：不同机器构建出的镜像依赖层不同，RAG、TensorFlow、模型加载能力和镜像体积都会变化。

建议：统一 README、DEPLOY、Dockerfile 注释、`.env.example` 中的默认依赖说明；在启动日志中输出当前 `REQUIREMENTS_FILE` 和 RAG 开关。

### 9. 容器内训练数据路径不可用

证据：`config.yaml` 的 `data.raw_data_path`、`reference_data_path`、`merged_data_path` 默认指向 `datasets/...`，compose 已挂载 `./datasets:/app/datasets`。

影响：容器内 API 推理可依赖 `models/`，但训练、合并、迭代触发中依赖公开数据路径的流程会失败。

建议：将训练数据挂载为显式 volume，或把训练能力从 API 镜像拆到独立训练环境。

## 低风险和维护性问题

- `api/routers/audit.py` 在模块 import 时初始化 SQLite，测试和脚本 import 也会产生副作用。
- `utils/exceptions.py` 定义了业务异常，但 API 层多数路径没有统一异常映射。
- `frontend/src/api/types.ts` 中 `DecisionResponse` 的核心嵌套字段比后端 Pydantic 更宽松，短期兼容但弱化了契约约束。
- `LLMConfigResponse` 返回 `has_api_key`，不泄露具体值，但仍暴露了密钥是否配置的信息。
- 前端已经定义 `queryAudit()`，但页面没有实际接线，审计能力更像后端预留接口。

## 验证结果

- `DecisionWorkflow` 专项测试：通过，`13 passed in 15.67s`。
- LLM 配置与字段标准化测试：通过，`6 passed in 0.05s`。
- FastAPI 路由枚举：成功，确认注册了 `/api/v1/agent/llm`、`/api/v1/knowledge/write`、`/api/v1/iteration/trigger`、`/api/v1/audit/query` 等接口。
- `docker compose config`：成功，确认端口、挂载、健康检查和真实环境变量展开；输出中包含本地 LLM Key，本报告不展示值。
- 前端 `npm run build`：失败。原因是本机 `node_modules` 中 Rollup native optional dependency 被 macOS 系统策略拒绝加载，并提示 npm optional dependency 相关问题。需要重装依赖后再验证。
- 完整 pytest：未稳定完成。运行过程中已出现若干失败标记，随后在 `tests/test_iteration.py::TestRegressionTester::test_regression_report` 附近触发 XGBoost/TensorFlow/原生扩展相关段错误。
- `test_iteration.py` 跳过重模型回归测试后：通过，`13 passed, 1 deselected in 3.27s`。
- 单独运行 `test_regression_report`：120 秒无输出后结束状态未知，说明重模型训练测试存在稳定性或性能问题。

## 建议优先级

第一优先级：修复 `.dockerignore` 密钥打包风险；为 LLM 配置、知识库写、迭代、审计接口加鉴权；调整生产环境端口暴露和 CORS。

第二优先级：拆分演示 Mock 与生产错误语义；修复前端 SSE 成功后重复调用普通决策；将 `scenario_id` 改为请求级参数。

第三优先级：统一模型和 Pipeline 加载服务，减少两套全局缓存；将训练/回归测试从 API 请求线程中移出；补齐 HTTP 级契约测试。

第四优先级：清理部署文档漂移；重装前端依赖并恢复构建验证；隔离重 ML 测试，避免完整测试套件被原生扩展段错误拖垮。
