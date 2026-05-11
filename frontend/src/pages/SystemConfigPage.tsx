import { apiBase, fetchHealth } from "../api/client";
import { SCENARIO_CONFIG, SCENARIO_NAMES } from "../data/demoData";
import type { HealthResponse, ScenarioId } from "../api/types";
import { useEffect, useMemo, useState } from "react";
import JsonView from "../components/JsonView";

interface Props {
  scenario: ScenarioId;
  health: HealthResponse | null;
}

const WORKFLOW_NODES = [
  {
    name: "数据接入",
    tag: "HTTP / CSV / Excel",
    desc: "接收政府监管平台推送的企业动态数据，并读取 Harness 挂载的 Markdown 静态知识库。",
  },
  {
    name: "风险评估",
    tag: "Stacking + SHAP",
    desc: "加载序列化预警模型，输出红橙黄蓝四分类概率、置信度与 Top3 特征归因。",
  },
  {
    name: "记忆召回",
    tag: "AgentFS + RAG",
    desc: "从 SQLite/Git 快照与长期知识库召回相似案例，经重排序后压缩为决策上下文。",
  },
  {
    name: "决策生成",
    tag: "LangGraph DAG",
    desc: "按风险等级生成结构化处置建议，覆盖核心归因、政府协同干预与企业设施管控。",
  },
  {
    name: "合规校验",
    tag: "MARCH + Monte Carlo",
    desc: "执行合规红线、工况逻辑、处置可行性三重审核，并用置信度采样拦截高风险输出。",
  },
  {
    name: "结果推送",
    tag: "Audit Trail",
    desc: "将最终 Payload 写入审计链路；触发人工审核、驳回或准入等闭环状态。",
  },
];

const CAPABILITY_ROWS = [
  {
    module: "多源数据治理",
    basis: "方案一：特征工程预处理；方案二：多模态融合数据库",
    detail: "二值、数值、枚举、文本和行业分类统一归一化；动态数据与法规、SOP、案例文本进入同一知识底座。",
  },
  {
    module: "风险预测模型",
    basis: "方案一：防泄露 Stacking 集成学习",
    detail: "XGBoost、LightGBM、CatBoost、RF、LR、MLP、1D-CNN 作为基学习器，弹性网络逻辑回归融合输出。",
  },
  {
    module: "长短期记忆",
    basis: "方案二：AgentFS 与上下文召回机制",
    detail: "P0-P3 记忆优先级、Token 阈值、RAG 检索、BGE-Reranker 重排与 Git 快照回滚支撑全过程溯源。",
  },
  {
    module: "决策风控",
    basis: "方案二：三重校验与高风险阻断",
    detail: "MARCH 孤立验证拆解原子命题，蒙特卡洛采样要求置信度达标，低可信或不可逆动作转人工审核。",
  },
  {
    module: "迭代管控",
    basis: "方案一：动态迭代；方案二：PR/CI 联合终审",
    detail: "新增样本或 F1 下降触发重训，候选模型需经过回归测试、灰度/金丝雀和政企两级终审。",
  },
];

const KNOWLEDGE_FILES = [
  "工矿风险预警智能体合规执行书.md",
  "部门分级审核SOP.md",
  "工业物理常识及传感器时间序列逻辑.md",
  "企业已具备的执行条件.md",
  "类似事故处理案例.md",
  "预警历史经验与短期记忆摘要.md",
];

const API_TABLE = [
  {
    group: "健康与文档",
    path: "GET /health",
    desc: "后端连通性与版本检查",
  },
  {
    group: "智能体决策",
    path: "POST /api/v1/agent/decision",
    desc: "触发完整 LangGraph 决策工作流",
  },
  {
    group: "智能体决策",
    path: "POST /api/v1/agent/decision/stream",
    desc: "SSE 推送节点状态、最终决策与拦截结果",
  },
  {
    group: "场景配置",
    path: "POST /api/v1/agent/scenario/{id}",
    desc: "切换危化品、冶金、粉尘涉爆场景阈值与知识库子集",
  },
  {
    group: "风险预测",
    path: "POST /api/v1/prediction/predict",
    desc: "直接调用风险预测模型与校验器",
  },
  {
    group: "数据管理",
    path: "POST /api/v1/data/upload",
    desc: "上传单个 CSV/Excel 企业数据文件",
  },
  {
    group: "数据管理",
    path: "POST /api/v1/data/upload/batch",
    desc: "批量上传多份企业数据文件",
  },
  {
    group: "知识库",
    path: "GET /api/v1/knowledge/list",
    desc: "查询长期知识库文件列表",
  },
  {
    group: "知识库",
    path: "GET /api/v1/knowledge/read/{filename}",
    desc: "读取指定 Markdown 知识文件",
  },
  {
    group: "知识库",
    path: "POST /api/v1/knowledge/snapshot",
    desc: "生成 AgentFS 状态快照与 Commit ID",
  },
  {
    group: "迭代管控",
    path: "GET /api/v1/iteration/status",
    desc: "查询当前模型迭代与待审批状态",
  },
  {
    group: "迭代管控",
    path: "POST /api/v1/iteration/trigger",
    desc: "触发新数据训练、回归测试与候选版本生成",
  },
  {
    group: "迭代管控",
    path: "POST /api/v1/iteration/approve",
    desc: "提交模型候选版本审批结论",
  },
  {
    group: "迭代管控",
    path: "POST /api/v1/iteration/canary",
    desc: "执行候选模型金丝雀发布检查",
  },
  {
    group: "审计日志",
    path: "GET /api/v1/audit/query",
    desc: "按事件类型、企业、风险等级查询运行日志",
  },
];

export default function SystemConfigPage({ scenario, health }: Props) {
  const [latestHealth, setLatestHealth] = useState<HealthResponse | null>(health);

  useEffect(() => {
    fetchHealth().then(setLatestHealth);
  }, []);

  const cfg = SCENARIO_CONFIG[scenario];
  const online = latestHealth?.status === "healthy";
  const scenarioName = SCENARIO_NAMES[scenario];
  const contractSample = useMemo(
    () => ({
      request: {
        enterprise_id: "CHEM-2024-001",
        scenario_id: scenario,
        data: {
          企业名称: "示例工矿企业",
          行业监管大类: scenarioName,
          具体风险描述: "传感器异常、巡检记录与执法记录等原始字段",
        },
      },
      response: {
        enterprise_id: "CHEM-2024-001",
        predicted_level: "红 | 橙 | 黄 | 蓝",
        probability_distribution: {
          红: 0.82,
          橙: 0.13,
          黄: 0.03,
          蓝: 0.02,
        },
        shap_contributions: [
          { feature: "重大风险数量", contribution: 0.32 },
          { feature: "文本高危词命中", contribution: 0.21 },
          { feature: "消防设施完好率", contribution: -0.12 },
        ],
        decision_payload: [
          "风险等级与核心归因",
          "政府跨部门协同干预建议",
          "企业设施管控建议",
        ],
        guardrails: {
          march: "合规红线 / 工况逻辑 / 处置可行性",
          monte_carlo_confidence_threshold: cfg["置信度阈值"],
          audit: "全流程日志与 AgentFS 快照",
        },
      },
    }),
    [cfg, scenario, scenarioName],
  );

  return (
    <div>
      <div className="section-title">系统配置与 API 文档</div>

      <div className={`alert ${online ? "success" : "error"}`}>
        {online
          ? `FastAPI 后端已连通，当前版本 ${latestHealth?.version ?? "-"}；模型与大模型调用由后端统一调度。`
          : "后端未连通，前端将以本地 Mock 数据演示；请先启动 FastAPI 服务。"}
      </div>

      <div className="row cols-4 system-kpi-grid">
        <div className="scada-card">
          <div className="scada-card-title">API BASE</div>
          <div className="system-kpi-value font-mono">{apiBase}</div>
          <div className="scada-card-sub">同源代理或 VITE_API_BASE</div>
        </div>
        <div className="scada-card">
          <div className="scada-card-title">当前场景</div>
          <div className="system-kpi-value">{scenarioName}</div>
          <div className="scada-card-sub">阈值与知识库子集随场景切换</div>
        </div>
        <div className="scada-card">
          <div className="scada-card-title">决策链路</div>
          <div className="system-kpi-value">6 节点</div>
          <div className="scada-card-sub">接入、评估、召回、生成、校验、推送</div>
        </div>
        <div className="scada-card">
          <div className="scada-card-title">治理阈值</div>
          <div className="system-kpi-value font-mono">{String(cfg["置信度阈值"])}</div>
          <div className="scada-card-sub">蒙特卡洛置信度下限</div>
        </div>
      </div>

      <div className="subtitle">方案映射的系统能力</div>
      <table className="scada-table">
        <thead>
          <tr>
            <th>模块</th>
            <th>方案依据</th>
            <th>页面配置含义</th>
          </tr>
        </thead>
        <tbody>
          {CAPABILITY_ROWS.map((row) => (
            <tr key={row.module}>
              <td>{row.module}</td>
              <td>{row.basis}</td>
              <td>{row.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="subtitle">智能体后端工作流</div>
      <div className="workflow-strip">
        {WORKFLOW_NODES.map((node, index) => (
          <div className="workflow-node-card" key={node.name}>
            <div className="workflow-node-index font-mono">{index + 1}</div>
            <div>
              <div className="workflow-node-title">{node.name}</div>
              <div className="workflow-node-tag">{node.tag}</div>
              <div className="workflow-node-desc">{node.desc}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="row cols-2" style={{ marginTop: 12 }}>
        <div>
          <div className="subtitle">当前场景配置参数</div>
          <JsonView data={cfg} maxHeight={220} />
        </div>
        <div>
          <div className="subtitle">核心知识库矩阵</div>
          <div className="knowledge-matrix">
            {KNOWLEDGE_FILES.map((file) => (
              <div className="knowledge-file" key={file}>
                <span className="knowledge-file-dot" />
                <span>{file}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="divider" />

      <div className="subtitle">API 文档入口</div>
      <div className="doc-link-row">
        <a className="doc-link" href="/docs" target="_blank" rel="noreferrer">
          Swagger UI
        </a>
        <a className="doc-link" href="/redoc" target="_blank" rel="noreferrer">
          Redoc
        </a>
        <span className="doc-link muted font-mono">GET /health</span>
      </div>

      <div className="subtitle">接口输入输出契约</div>
      <JsonView data={contractSample} maxHeight={360} />

      <div className="subtitle" style={{ marginTop: 16 }}>
        核心接口速查
      </div>
      <table className="scada-table">
        <thead>
          <tr>
            <th>分组</th>
            <th>接口</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {API_TABLE.map((r) => (
            <tr key={r.path}>
              <td>{r.group}</td>
              <td className="font-mono">{r.path}</td>
              <td>{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="divider" />
      <div className="subtitle">系统运行信息</div>
      <JsonView
        data={{
          backend_status: latestHealth?.status ?? "unknown",
          version: latestHealth?.version ?? "unknown",
          api_base: apiBase,
          frontend: "React + Vite + ECharts (SCADA Theme)",
          backend: "Python + FastAPI + LangGraph",
          model_layer: "防泄露 Stacking 风险预警模型",
          memory_layer: "AgentFS + SQLite + Git + RAG",
          guardrails: "MARCH 三重校验 + Monte Carlo 高风险阻断",
          theme: "Industrial Control Room Dark",
        }}
      />
    </div>
  );
}
