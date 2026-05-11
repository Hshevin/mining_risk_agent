import { useEffect, useMemo, useRef, useState } from "react";
import { postDecision, streamDecision, uploadDataFile } from "../api/client";
import type {
  DecisionResponse,
  EvidenceAnchor,
  NodeStatus,
  ScenarioId,
} from "../api/types";
import {
  SCENARIO_NAMES,
  generateMockDecision,
  getDemoDataJson,
} from "../data/demoData";
import ScadaCard from "../components/ScadaCard";
import { ProbabilityChart, ShapChart } from "../components/charts";
import JsonView from "../components/JsonView";
import Tabs from "../components/Tabs";

interface Props {
  scenario: ScenarioId;
}

interface DataQualitySummary {
  valid: boolean;
  fieldCount: number;
  missing: string[];
  message: string;
}

interface MarchCheckRow {
  id: "compliance" | "logic" | "feasibility";
  label: string;
  passed: boolean;
  reason: string;
  evidence?: EvidenceAnchor;
}

interface HumanReviewRoute {
  primaryDepartment: string;
  assistDepartment: string;
  triggers: string[];
  deadline: string;
  status: string;
  demo: boolean;
}

const RESULT_TABS = [
  { id: "overview", label: "预测概览" },
  { id: "evidence", label: "RAG 证据" },
  { id: "advice", label: "决策建议" },
  { id: "march", label: "MARCH 校验" },
  { id: "blocking", label: "置信与阻断" },
  { id: "review", label: "人工审核" },
  { id: "raw", label: "日志 / JSON" },
];

const REQUIRED_FIELDS = ["企业名称", "行业监管大类", "具体风险描述", "管控措施"];

const LEVEL_HEX: Record<string, string> = {
  红: "#ef4444",
  橙: "#f97316",
  黄: "#eab308",
  蓝: "#3b82f6",
};

const LEVEL_GLOW: Record<string, string> = {
  红: "glow-red",
  橙: "glow-orange",
  黄: "glow-yellow",
  蓝: "glow-blue",
};

const DEMO_EVIDENCE_BY_SCENARIO: Record<ScenarioId, EvidenceAnchor[]> = {
  chemical: [
    {
      source_file: "knowledge_base/工矿风险预警智能体合规执行书.md",
      section_title: "合规红线规则表",
      rule_id: "COM-RED-001",
      doc_type: "compliance",
      layer: "compliance",
      score: 0.91,
      distance: 0.09,
      matched_text: "红级预警或重大隐患不得仅建议观察，必须升级人工审核；必要时停产、撤人、隔离危险源。",
    },
    {
      source_file: "knowledge_base/工业物理常识及传感器时间序列逻辑.md",
      section_title: "危化品工况逻辑",
      rule_id: "PHY-CHEM-002",
      doc_type: "physics",
      layer: "logic",
      score: 0.84,
      distance: 0.16,
      matched_text: "可燃气体浓度上升叠加通风失效时，应优先切断点火源、通风稀释并持续检测。",
    },
    {
      source_file: "knowledge_base/部门分级审核SOP.md",
      section_title: "分级路由、协同、退回和闭环 SOP 表",
      sop_id: "SOP-ROUTE-RED",
      doc_type: "sop",
      layer: "feasibility",
      score: 0.88,
      distance: 0.12,
      matched_text: "红级路由由属地应急管理部门牵头，企业主要负责人同步签收，必要时联动消防等协同部门。",
    },
  ],
  metallurgy: [
    {
      source_file: "knowledge_base/工矿风险预警智能体合规执行书.md",
      section_title: "必须上报、停产、撤人、整改、复查和数据审计规则",
      rule_id: "COM-ACT-002",
      doc_type: "compliance",
      layer: "compliance",
      score: 0.86,
      distance: 0.14,
      matched_text: "橙级或高风险异常需组织专项核查、限期整改，并记录复查闭环。",
    },
    {
      source_file: "knowledge_base/工业物理常识及传感器时间序列逻辑.md",
      section_title: "工况逻辑和时间序列规则表",
      rule_id: "PHY-MET-001",
      doc_type: "physics",
      layer: "logic",
      score: 0.89,
      distance: 0.11,
      matched_text: "煤气压力、温度和报警信号需相互解释；压力波动叠加报警器异常时应组织煤气专项检查。",
    },
    {
      source_file: "knowledge_base/部门分级审核SOP.md",
      section_title: "分级路由、协同、退回和闭环 SOP 表",
      sop_id: "SOP-CHECK-002",
      doc_type: "sop",
      layer: "feasibility",
      score: 0.81,
      distance: 0.19,
      matched_text: "专项检查需明确主责部门、协同技术支持、整改期限和复查证据。",
    },
  ],
  dust: [
    {
      source_file: "knowledge_base/工矿风险预警智能体合规执行书.md",
      section_title: "合规红线规则表",
      rule_id: "COM-RED-001",
      doc_type: "compliance",
      layer: "compliance",
      score: 0.93,
      distance: 0.07,
      matched_text: "红级预警或重大隐患不得仅建议观察，必须立即升级人工审核。",
    },
    {
      source_file: "knowledge_base/工业物理常识及传感器时间序列逻辑.md",
      section_title: "工况逻辑和时间序列规则表",
      rule_id: "PHY-DUST-002",
      doc_type: "physics",
      layer: "logic",
      score: 0.9,
      distance: 0.1,
      matched_text: "除尘系统压差、电流和粉尘浓度必须相互解释，粉尘浓度上升叠加除尘失效需立即核查。",
    },
    {
      source_file: "knowledge_base/类似事故处理案例.md",
      section_title: "高风险企业风险组合案例",
      case_id: "D-008",
      doc_type: "cases",
      layer: "feasibility",
      score: 0.79,
      distance: 0.21,
      matched_text: "粉尘涉爆风险组合显示，湿式除尘器、清扫记录和防爆电气条件需同时满足后才可恢复作业。",
    },
  ],
};

export default function RiskPredictionPage({ scenario }: Props) {
  const [enterpriseId, setEnterpriseId] = useState("ENT-DEMO-001");
  const [dataText, setDataText] = useState(() => getDemoDataJson(scenario));
  const [uploadInfo, setUploadInfo] = useState<string>("");
  const [uploadedRow, setUploadedRow] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [streamLog, setStreamLog] = useState<NodeStatus[]>([]);
  const [useStream, setUseStream] = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setDataText(getDemoDataJson(scenario));
    setDecision(null);
    setStreamLog([]);
    setError(null);
  }, [scenario]);

  const dataQuality = useMemo(() => summarizeDataQuality(dataText), [dataText]);

  async function handleUpload(file: File) {
    setUploadInfo(`正在上传 ${file.name} ...`);
    const resp = await uploadDataFile(file, enterpriseId);
    if (!resp || !resp.success) {
      setUploadInfo(`上传失败: ${resp?.message ?? "后端无响应"}`);
      setUploadedRow(null);
      return;
    }
    setUploadInfo(`已加载 ${resp.rows} 行 x ${resp.columns} 列`);
    setUploadedRow(resp.preview && resp.preview.length > 0 ? resp.preview[0] : null);
  }

  async function handlePredict() {
    setError(null);
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(dataText);
    } catch {
      setError("JSON 格式错误，请检查输入");
      return;
    }
    if (uploadedRow) {
      Object.entries(uploadedRow).forEach(([key, value]) => {
        if (value !== null && value !== undefined) payload[key] = value;
      });
    }
    payload.scenario_id = scenario;

    setLoading(true);
    setStreamLog([]);
    setDecision(null);

    let result: DecisionResponse | null = null;
    if (useStream) {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        result = await streamDecision(
          enterpriseId,
          payload,
          (msg) => setStreamLog((prev) => [...prev, msg]),
          ctrl.signal,
          scenario,
        );
      } catch (event) {
        console.warn("SSE 失败，回退至普通请求", event);
      }
    }

    if (!result) {
      result = await postDecision(enterpriseId, payload, scenario);
    }
    if (result) {
      setDecision(result);
    } else {
      setError("后端无响应，启用本地 Mock 数据");
      setDecision(generateMockDecision(scenario, enterpriseId));
    }
    setLoading(false);
  }

  return (
    <div>
      <div className="section-title">企业风险事故预警与决策链路</div>

      <div className="row predict">
        <div className="input-panel">
          <div className="subtitle">企业基础字段</div>
          <label className="scada-label">企业 ID</label>
          <input
            className="scada-input"
            value={enterpriseId}
            onChange={(event) => setEnterpriseId(event.target.value)}
          />

          <div className="form-note">
            当前场景：<b>{SCENARIO_NAMES[scenario]}</b>
          </div>

          <button
            className="scada-btn secondary"
            type="button"
            onClick={() => setDataText(getDemoDataJson(scenario))}
            style={{ marginBottom: 10 }}
          >
            填充演示数据
          </button>

          <label className="scada-label">企业数据 JSON</label>
          <textarea
            className="scada-textarea"
            rows={12}
            value={dataText}
            onChange={(event) => setDataText(event.target.value)}
          />

          <DataQualityPanel summary={dataQuality} uploaded={!!uploadedRow} />

          <label className="scada-label" style={{ marginTop: 8 }}>
            或上传 CSV/Excel
          </label>
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleUpload(file);
            }}
            style={{ color: "#9ca3af", fontSize: 12 }}
          />
          {uploadInfo && <div className="upload-status">{uploadInfo}</div>}

          <label className="toggle-line">
            <input
              type="checkbox"
              checked={useStream}
              onChange={(event) => setUseStream(event.target.checked)}
            />
            使用 SSE 实时节点流
          </label>

          <button
            className="scada-btn full-width"
            type="button"
            onClick={handlePredict}
            disabled={loading}
          >
            {loading ? "执行中..." : "执行预测"}
          </button>

          {error && <div className="alert error" style={{ marginTop: 10 }}>{error}</div>}
        </div>

        <div>
          {loading && streamLog.length === 0 && <SpinnerBox />}
          {!loading && !decision && streamLog.length === 0 && (
            <div className="empty-state">在左侧输入企业数据并执行预测后查看结果</div>
          )}
          {streamLog.length > 0 && !decision && (
            <div className="scada-card" style={{ marginBottom: 12 }}>
              <div className="scada-card-title">SSE 实时节点</div>
              <TimelineLogs nodes={streamLog} />
            </div>
          )}
          {decision && (
            <DecisionView
              decision={decision}
              streamLog={streamLog}
              scenario={scenario}
              dataQuality={dataQuality}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function SpinnerBox() {
  return (
    <div className="spinner-box">
      <div className="tech-spinner" />
      <div className="spinner-label">SYSTEM INITIALIZING WORKFLOW...</div>
    </div>
  );
}

function DataQualityPanel({
  summary,
  uploaded,
}: {
  summary: DataQualitySummary;
  uploaded: boolean;
}) {
  return (
    <div className={`data-quality ${summary.valid ? "ok" : "warn"}`}>
      <div className="data-quality-head">
        <span>数据质量提示</span>
        <StatusBadge tone={summary.valid ? "success" : "warning"} label={summary.valid ? "PASS" : "WARN"} />
      </div>
      <div>{summary.message}</div>
      <div className="mini-list">
        <span>字段数 {summary.fieldCount}</span>
        {uploaded && <span>已叠加上传预览行</span>}
        {summary.missing.map((field) => <span key={field}>缺少 {field}</span>)}
      </div>
    </div>
  );
}

function DecisionView({
  decision,
  streamLog,
  scenario,
  dataQuality,
}: {
  decision: DecisionResponse;
  streamLog: NodeStatus[];
  scenario: ScenarioId;
  dataQuality: DataQualitySummary;
}) {
  const [activeResultTab, setActiveResultTab] = useState("overview");
  const level = decision.predicted_level || "未知";
  const hex = LEVEL_HEX[level] ?? "#6b7280";
  const glow = LEVEL_GLOW[level] ?? "glow-white";
  const isRed = level === "红";
  const isMock = !!decision.mock;
  const evidence = getDecisionEvidence(decision, scenario);
  const marchChecks = buildMarchChecks(decision, scenario, evidence);
  const humanRoute = buildHumanReviewRoute(decision, marchChecks);

  const finalNodes = useMemo(() => {
    if (streamLog.length > 0) return streamLog;
    return decision.node_status ?? [];
  }, [streamLog, decision.node_status]);

  return (
    <div>
      <div
        className={`scada-card ${isRed ? "risk-red-pulse" : ""}`}
        style={{
          textAlign: "center",
          padding: 20,
          background: "#111827",
          border: `1px solid ${hex}`,
          marginBottom: 16,
        }}
      >
        <div className="risk-hero-meta">
          {decision.enterprise_id} | {SCENARIO_NAMES[decision.scenario_id as ScenarioId] ?? decision.scenario_id}
          {isMock && <span className="mock-tag">MOCK</span>}
        </div>
        <div className={glow} style={{ fontSize: 40, fontWeight: 800, fontFamily: "JetBrains Mono, monospace", lineHeight: 1 }}>
          {level}级风险
        </div>
        <div className="final-status-row">
          <span style={{ background: statusColor(decision.final_status), color: "#fff" }}>
            {decision.final_status}
          </span>
        </div>
      </div>

      {isMock && (
        <div className="alert info">
          当前为 Mock / demo 模式数据，用于在无外部 LLM 或后端工作流不可用时演示完整链路。
        </div>
      )}

      <KpiCards decision={decision} />

      <Tabs tabs={RESULT_TABS} active={activeResultTab} onChange={setActiveResultTab} />

      {activeResultTab === "overview" && (
        <PredictionOverview decision={decision} level={level} dataQuality={dataQuality} />
      )}
      {activeResultTab === "evidence" && <EvidencePanel evidence={evidence} isDemo={isMock || !decision.rag_evidence} />}
      {activeResultTab === "advice" && <DecisionAdvicePanel decision={decision} />}
      {activeResultTab === "march" && <MarchPanel checks={marchChecks} retryCount={decision.march_result?.retry_count} />}
      {activeResultTab === "blocking" && <BlockingPanel decision={decision} />}
      {activeResultTab === "review" && <HumanReviewPanel route={humanRoute} />}
      {activeResultTab === "raw" && (
        <RawPanel decision={decision} nodes={finalNodes} />
      )}
    </div>
  );
}

function PredictionOverview({
  decision,
  level,
  dataQuality,
}: {
  decision: DecisionResponse;
  level: string;
  dataQuality: DataQualitySummary;
}) {
  return (
    <div>
      <div className="row cols-2">
        <div className="advice-card">
          <div className="advice-card-title">风险等级预测</div>
          <div className="risk-root-cause">
            <strong>{decision.risk_level_and_attribution?.level ?? decision.predicted_level}</strong>
            <span>{decision.risk_level_and_attribution?.root_cause ?? "根因待后端返回"}</span>
          </div>
        </div>
        <div className={`data-quality ${dataQuality.valid ? "ok" : "warn"}`}>
          <div className="data-quality-head">
            <span>数据质量提示</span>
            <StatusBadge tone={dataQuality.valid ? "success" : "warning"} label={dataQuality.valid ? "PASS" : "WARN"} />
          </div>
          <div>{dataQuality.message}</div>
        </div>
      </div>

      <div className="row cols-2" style={{ marginTop: 16 }}>
        {decision.probability_distribution && (
          <ProbabilityChart probs={decision.probability_distribution} centerLevel={level} />
        )}
        {decision.shap_contributions && decision.shap_contributions.length > 0 && (
          <ShapChart contributions={decision.shap_contributions} topN={5} />
        )}
      </div>
    </div>
  );
}

function EvidencePanel({ evidence, isDemo }: { evidence: EvidenceAnchor[]; isDemo: boolean }) {
  return (
    <div>
      {isDemo && <div className="alert info">后端未返回完整证据数组时，这里使用演示证据补齐展示结构。</div>}
      <div className="scada-table-wrap">
        <table className="scada-table dense evidence-table">
          <thead>
            <tr>
              <th>source_file</th>
              <th>section_title</th>
              <th>ID</th>
              <th>doc_type</th>
              <th>score</th>
              <th>distance</th>
              <th>matched_text</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((item, index) => (
              <tr key={`${item.source_file}-${item.section_title}-${index}`}>
                <td className="mono-cell">{item.source_file || "—"}</td>
                <td>{item.section_title || "—"}</td>
                <td className="mono-cell">{item.rule_id || item.sop_id || item.case_id || "—"}</td>
                <td>{item.doc_type || "—"}</td>
                <td className="mono-cell">{formatNumber(item.score)}</td>
                <td className="mono-cell">{formatNumber(item.distance)}</td>
                <td>{item.matched_text || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DecisionAdvicePanel({ decision }: { decision: DecisionResponse }) {
  return (
    <div>
      <DecisionAdviceCards decision={decision} />
      <div className="subtitle">决策建议 JSON</div>
      <JsonView
        data={{
          final_status: decision.final_status,
          risk_level_and_attribution: decision.risk_level_and_attribution,
          government_intervention: decision.government_intervention,
          enterprise_control: decision.enterprise_control,
        }}
      />
    </div>
  );
}

function MarchPanel({
  checks,
  retryCount,
}: {
  checks: MarchCheckRow[];
  retryCount?: number;
}) {
  return (
    <div>
      <div className="table-caption">retry_count={retryCount ?? 0}；每层显示 pass/fail、reason 和证据锚点。</div>
      <div className="scada-table-wrap">
        <table className="scada-table dense march-table">
          <thead>
            <tr>
              <th>校验层</th>
              <th>pass/fail</th>
              <th>reason</th>
              <th>source_file</th>
              <th>rule_id / sop_id / case_id</th>
            </tr>
          </thead>
          <tbody>
            {checks.map((check) => (
              <tr key={check.id}>
                <td>{check.label}</td>
                <td><StatusBadge tone={check.passed ? "success" : "danger"} label={check.passed ? "pass" : "fail"} /></td>
                <td>{check.reason}</td>
                <td className="mono-cell">{check.evidence?.source_file || "—"}</td>
                <td className="mono-cell">{check.evidence?.rule_id || check.evidence?.sop_id || check.evidence?.case_id || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BlockingPanel({ decision }: { decision: DecisionResponse }) {
  const mc = decision.monte_carlo_result;
  const tdr = decision.three_d_risk;
  const nSamples = mc?.n_samples ?? mc?.total_samples;
  return (
    <div className="row cols-2">
      <div className={`validation-card ${mc?.passed ? "passed" : "failed"}`}>
        <div className="v-title">蒙特卡洛置信度</div>
        <div className="detail-grid">
          <span>n_samples</span><strong>{nSamples ?? "—"}</strong>
          <span>confidence</span><strong>{formatNumber(mc?.confidence)}</strong>
          <span>threshold</span><strong>{formatNumber(mc?.threshold)}</strong>
          <span>passed</span><strong>{mc?.passed === undefined ? "未执行" : mc.passed ? "true" : "false"}</strong>
          <span>status</span><strong>{mc?.status || "—"}</strong>
        </div>
        {mc?.passed === false && <div className="v-detail">低置信度时转人工审核。</div>}
      </div>
      <div className={`validation-card ${tdr?.blocked ? "failed" : "passed"}`}>
        <div className="v-title">三维高风险阻断</div>
        <div className="detail-grid">
          <span>severity</span><strong>{tdr?.severity || "—"}</strong>
          <span>relevance</span><strong>{tdr?.relevance || "—"}</strong>
          <span>irreversibility</span><strong>{tdr?.irreversibility || "—"}</strong>
          <span>total_score</span><strong>{tdr?.total_score ?? "—"}</strong>
          <span>blocked</span><strong>{tdr?.blocked === undefined ? "未执行" : tdr.blocked ? "true" : "false"}</strong>
        </div>
        {tdr?.reason && <div className="v-detail">{tdr.reason}</div>}
      </div>
    </div>
  );
}

function HumanReviewPanel({ route }: { route: HumanReviewRoute }) {
  return (
    <div className="advice-card">
      <div className="advice-card-title">人工审核路由 {route.demo && <span className="mock-tag">DEMO</span>}</div>
      <div className="detail-grid">
        <span>主责部门</span><strong>{route.primaryDepartment}</strong>
        <span>协同部门</span><strong>{route.assistDepartment}</strong>
        <span>触发原因</span><strong>{route.triggers.join("；") || "未触发"}</strong>
        <span>时限</span><strong>{route.deadline}</strong>
        <span>审核状态</span><strong>{route.status}</strong>
      </div>
    </div>
  );
}

function RawPanel({
  decision,
  nodes,
}: {
  decision: DecisionResponse;
  nodes: NodeStatus[];
}) {
  return (
    <div>
      <details open>
        <summary className="detail-summary">SSE 实时日志</summary>
        <TimelineLogs nodes={nodes} />
      </details>
      <details style={{ marginTop: 12 }}>
        <summary className="detail-summary">原始决策 JSON</summary>
        <JsonView data={decision} />
      </details>
    </div>
  );
}

function KpiCards({ decision }: { decision: DecisionResponse }) {
  const probs = decision.probability_distribution || {};
  const top = Object.entries(probs).sort(([, a], [, b]) => b - a)[0];
  const confidence = top ? `${(top[1] * 100).toFixed(0)}%` : "—";
  const tdr = decision.three_d_risk;
  const mc = decision.monte_carlo_result;

  return (
    <div className="row cols-4" style={{ marginBottom: 16 }}>
      <ScadaCard
        title="最终状态"
        value={<span className="compact-card-value">{decision.final_status || "—"}</span>}
        glowClass={decision.final_status === "REJECT" ? "glow-red" : decision.final_status === "HUMAN_REVIEW" ? "glow-orange" : "glow-green"}
      />
      <ScadaCard title="模型置信度" value={confidence} glowClass="glow-green" />
      <ScadaCard
        title="三维风险"
        value={<span className="compact-card-value">{tdr?.risk_level ?? "—"}</span>}
        sub={tdr?.total_score !== undefined ? `score=${tdr.total_score}` : undefined}
        glowClass={tdr?.blocked ? "glow-red" : "glow-yellow"}
      />
      <ScadaCard
        title="蒙特卡洛"
        value={mc?.confidence !== undefined ? mc.confidence.toFixed(2) : "—"}
        sub={mc ? `valid ${mc.valid_count}/${mc.total_samples ?? mc.n_samples}` : undefined}
        glowClass={mc?.passed ? "glow-green" : "glow-orange"}
      />
    </div>
  );
}

function DecisionAdviceCards({ decision }: { decision: DecisionResponse }) {
  const gov = decision.government_intervention;
  const ent = decision.enterprise_control;
  if (!gov && !ent) return null;
  return (
    <div className="row cols-2" style={{ marginBottom: 12 }}>
      {gov && (
        <div className="advice-card" style={{ borderLeftColor: "#ef4444" }}>
          <div className="advice-card-title">政府干预建议</div>
          {gov.department_primary?.name && (
            <div className="strong-line">
              <b>{gov.department_primary.name}</b>
              {gov.department_primary.contact_role && <span>({gov.department_primary.contact_role})</span>}
            </div>
          )}
          {gov.department_primary?.action && <div className="muted-line">{gov.department_primary.action}</div>}
          {gov.actions && gov.actions.length > 0 && (
            <ul className="compact-list">
              {gov.actions.map((action, index) => <li key={index}>{action}</li>)}
            </ul>
          )}
          {gov.deadline_hours !== undefined && (
            <div className="deadline-line">处置期限: {gov.deadline_hours} 小时</div>
          )}
        </div>
      )}
      {ent && (
        <div className="advice-card" style={{ borderLeftColor: "#3b82f6" }}>
          <div className="advice-card-title">企业管控建议</div>
          {ent.equipment_id && <div className="strong-line"><b>设备:</b><span>{ent.equipment_id}</span></div>}
          {ent.operation && <div className="muted-line">{ent.operation}</div>}
          {ent.parameters && (
            <pre className="mini-json">{JSON.stringify(ent.parameters, null, 2)}</pre>
          )}
          {ent.personnel_actions && ent.personnel_actions.length > 0 && (
            <ul className="compact-list">
              {ent.personnel_actions.map((action, index) => <li key={index}>{action}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function TimelineLogs({ nodes }: { nodes: NodeStatus[] }) {
  if (!nodes || nodes.length === 0) {
    return <div style={{ color: "#6b7280", fontSize: 12 }}>暂无节点数据</div>;
  }
  return (
    <div className="timeline-container">
      {nodes.map((ns, index) => {
        const cls = ns.status === "completed"
          ? "completed"
          : ns.status === "failed"
          ? "failed"
          : ns.status === "running"
          ? "running"
          : "";
        const icon = ns.status === "completed" ? "✓" : ns.status === "failed" ? "✗" : "⟳";
        return (
          <div className={`timeline-node ${cls}`} key={`${ns.node}-${index}`}>
            <div>
              <div className="node-name">{icon} {ns.node}</div>
              {ns.detail && <div className="node-detail">{ns.detail}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function summarizeDataQuality(dataText: string): DataQualitySummary {
  try {
    const payload = JSON.parse(dataText) as Record<string, unknown>;
    const keys = Object.keys(payload);
    const missing = REQUIRED_FIELDS.filter((field) => payload[field] === undefined || payload[field] === "");
    return {
      valid: missing.length === 0,
      fieldCount: keys.length,
      missing,
      message: missing.length === 0
        ? "基础字段可解析，满足演示预测输入。"
        : "基础字段可解析，但存在缺失项，结果应标注为需复核。",
    };
  } catch {
    return {
      valid: false,
      fieldCount: 0,
      missing: REQUIRED_FIELDS,
      message: "JSON 无法解析，暂不能执行预测。",
    };
  }
}

function getDecisionEvidence(decision: DecisionResponse, scenario: ScenarioId): EvidenceAnchor[] {
  const direct = decision.rag_evidence ?? [];
  const march = [
    ...(decision.march_result?.evidence ?? []),
    ...(decision.march_result?.supporting_evidence ?? []),
  ];
  const merged = [...direct, ...march].filter((item) => item.source_file || item.matched_text);
  return merged.length > 0 ? dedupeEvidence(merged).slice(0, 8) : DEMO_EVIDENCE_BY_SCENARIO[scenario];
}

function dedupeEvidence(items: EvidenceAnchor[]): EvidenceAnchor[] {
  const seen = new Set<string>();
  const output: EvidenceAnchor[] = [];
  items.forEach((item) => {
    const key = `${item.source_file}-${item.section_title}-${item.rule_id || item.sop_id || item.case_id}-${item.matched_text}`;
    if (seen.has(key)) return;
    seen.add(key);
    output.push(item);
  });
  return output;
}

function buildMarchChecks(
  decision: DecisionResponse,
  scenario: ScenarioId,
  evidence: EvidenceAnchor[],
): MarchCheckRow[] {
  const failureEvidence = decision.march_result?.evidence ?? [];
  const overallPassed = decision.march_result?.passed;
  const layerConfig: Array<Pick<MarchCheckRow, "id" | "label">> = [
    { id: "compliance", label: "合规红线校验" },
    { id: "logic", label: "工况逻辑校验" },
    { id: "feasibility", label: "处置可行性校验" },
  ];

  return layerConfig.map((layer) => {
    const layerEvidence =
      evidence.find((item) => inferEvidenceLayer(item) === layer.id) ??
      DEMO_EVIDENCE_BY_SCENARIO[scenario].find((item) => inferEvidenceLayer(item) === layer.id);
    const failedByEvidence = failureEvidence.some((item) => inferEvidenceLayer(item) === layer.id);
    const demoDustFeasibilityFail = scenario === "dust" && layer.id === "feasibility" && overallPassed === false;
    const passed = failedByEvidence || demoDustFeasibilityFail ? false : overallPassed ?? true;
    return {
      id: layer.id,
      label: layer.label,
      passed,
      reason: passed
        ? `${layer.label}通过，证据锚点可追溯。`
        : decision.march_result?.reason || `${layer.label}未通过，需要改写或人工复核。`,
      evidence: layerEvidence,
    };
  });
}

function inferEvidenceLayer(item: EvidenceAnchor): MarchCheckRow["id"] {
  if (item.layer === "compliance" || item.doc_type === "compliance" || item.rule_id?.startsWith("COM-")) {
    return "compliance";
  }
  if (item.layer === "logic" || item.doc_type === "physics" || item.rule_id?.startsWith("PHY-")) {
    return "logic";
  }
  return "feasibility";
}

function buildHumanReviewRoute(
  decision: DecisionResponse,
  checks: MarchCheckRow[],
): HumanReviewRoute {
  const gov = decision.government_intervention;
  const mc = decision.monte_carlo_result;
  const tdr = decision.three_d_risk;
  const triggers = [
    ...(checks.some((item) => !item.passed) ? ["MARCH 校验未通过"] : []),
    ...(mc?.passed === false ? ["蒙特卡洛置信度低于阈值"] : []),
    ...(tdr?.blocked ? ["三维高风险阻断"] : []),
    ...(decision.final_status === "HUMAN_REVIEW" ? ["最终状态转人工审核"] : []),
    ...(decision.final_status === "REJECT" ? ["最终状态拒绝自动执行"] : []),
  ];
  return {
    primaryDepartment: gov?.department_primary?.name || "属地应急管理部门",
    assistDepartment: gov?.department_assist?.name || "行业主管部门 / 专家组",
    triggers,
    deadline: gov?.deadline_hours !== undefined ? `${gov.deadline_hours} 小时` : "按场景配置",
    status: decision.final_status === "APPROVE"
      ? "未触发人工审核"
      : decision.final_status === "REJECT"
      ? "已阻断，等待人工复核"
      : "待人工审核",
    demo: !!decision.mock,
  };
}

function statusColor(status: string): string {
  if (status === "REJECT") return "#ef4444";
  if (status === "HUMAN_REVIEW") return "#f97316";
  if (status === "APPROVE") return "#10b981";
  return "#6b7280";
}

function StatusBadge({ label, tone }: { label: string; tone: "success" | "warning" | "danger" }) {
  return <span className={`status-badge ${tone}`}>{label}</span>;
}

function formatNumber(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}
