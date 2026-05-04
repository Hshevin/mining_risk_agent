import { useEffect, useMemo, useRef, useState } from "react";
import { postDecision, streamDecision, uploadDataFile } from "../api/client";
import type { DecisionResponse, NodeStatus, ScenarioId } from "../api/types";
import {
  SCENARIO_NAMES,
  generateMockDecision,
  getDemoDataJson,
} from "../data/demoData";
import ScadaCard from "../components/ScadaCard";
import { ProbabilityChart, ShapChart } from "../components/charts";
import JsonView from "../components/JsonView";

interface Props {
  scenario: ScenarioId;
}

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
  }, [scenario]);

  async function handleUpload(file: File) {
    setUploadInfo(`正在上传 ${file.name} ...`);
    const resp = await uploadDataFile(file, enterpriseId);
    if (!resp || !resp.success) {
      setUploadInfo(`上传失败: ${resp?.message ?? "后端无响应"}`);
      setUploadedRow(null);
      return;
    }
    setUploadInfo(`已加载 ${resp.rows} 行 × ${resp.columns} 列`);
    if (resp.preview && resp.preview.length > 0) {
      setUploadedRow(resp.preview[0]);
    } else {
      setUploadedRow(null);
    }
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
      Object.entries(uploadedRow).forEach(([k, v]) => {
        if (v !== null && v !== undefined) payload[k] = v;
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
      } catch (e) {
        // SSE 失败回退到普通请求
        console.warn("SSE 失败，回退至普通请求", e);
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
      <div className="section-title">
        🎯 企业风险预测 — 上传数据 → 模型预测 → 决策建议 → 三重风控拦截
      </div>

      <div className="row predict">
        {/* 左侧输入面板 */}
        <div>
          <div className="subtitle">输入面板</div>
          <label className="scada-label">企业 ID</label>
          <input
            className="scada-input"
            value={enterpriseId}
            onChange={(e) => setEnterpriseId(e.target.value)}
          />

          <div style={{ fontSize: 12, color: "#6b7280", margin: "10px 0" }}>
            当前场景:{" "}
            <b style={{ color: "#e5e7eb" }}>{SCENARIO_NAMES[scenario]}</b>
          </div>

          <button
            className="scada-btn secondary"
            type="button"
            onClick={() => setDataText(getDemoDataJson(scenario))}
            style={{ marginBottom: 10 }}
          >
            🎲 模拟数据填充
          </button>

          <label className="scada-label">企业数据（JSON）</label>
          <textarea
            className="scada-textarea"
            rows={12}
            value={dataText}
            onChange={(e) => setDataText(e.target.value)}
          />

          <label className="scada-label" style={{ marginTop: 8 }}>
            或上传 CSV/Excel
          </label>
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUpload(f);
            }}
            style={{ color: "#9ca3af", fontSize: 12 }}
          />
          {uploadInfo && (
            <div
              style={{
                fontSize: 11,
                color: "#10b981",
                marginTop: 4,
                fontFamily: "JetBrains Mono, monospace",
              }}
            >
              {uploadInfo}
            </div>
          )}

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 12,
              color: "#9ca3af",
              margin: "10px 0",
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={useStream}
              onChange={(e) => setUseStream(e.target.checked)}
            />
            使用 SSE 实时节点流
          </label>

          <button
            className="scada-btn full-width"
            type="button"
            onClick={handlePredict}
            disabled={loading}
          >
            {loading ? "执行中..." : "🚀 执行预测"}
          </button>

          {error && <div className="alert error" style={{ marginTop: 10 }}>{error}</div>}
        </div>

        {/* 右侧结果区 */}
        <div>
          {loading && streamLog.length === 0 && <SpinnerBox />}
          {!loading && !decision && streamLog.length === 0 && (
            <div className="empty-state">
              👈 在左侧输入企业数据并点击「执行预测」查看结果
            </div>
          )}
          {streamLog.length > 0 && !decision && (
            <div className="scada-card" style={{ marginBottom: 12 }}>
              <div className="scada-card-title">📡 SSE 实时节点</div>
              <TimelineLogs nodes={streamLog} />
            </div>
          )}
          {decision && <DecisionView decision={decision} streamLog={streamLog} />}
        </div>
      </div>
    </div>
  );
}

function SpinnerBox() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 60,
      }}
    >
      <div className="tech-spinner" />
      <div
        style={{
          marginTop: 16,
          fontSize: 13,
          color: "#9ca3af",
          fontFamily: "JetBrains Mono, monospace",
        }}
      >
        SYSTEM INITIALIZING WORKFLOW...
      </div>
    </div>
  );
}

interface DecisionProps {
  decision: DecisionResponse;
  streamLog: NodeStatus[];
}

function DecisionView({ decision, streamLog }: DecisionProps) {
  const level = decision.predicted_level || "未知";
  const hex = LEVEL_HEX[level] ?? "#6b7280";
  const glow = LEVEL_GLOW[level] ?? "glow-white";
  const isRed = level === "红";
  const isMock = !!decision.mock;

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
        <div
          style={{
            fontSize: 12,
            color: "#9ca3af",
            marginBottom: 8,
            fontFamily: "JetBrains Mono, monospace",
          }}
        >
          {decision.enterprise_id} | {SCENARIO_NAMES[decision.scenario_id as ScenarioId] ?? decision.scenario_id}
          {isMock && <span className="mock-tag">MOCK</span>}
        </div>
        <div
          className={glow}
          style={{
            fontSize: 40,
            fontWeight: 800,
            fontFamily: "JetBrains Mono, monospace",
            lineHeight: 1,
          }}
        >
          {level}级风险
        </div>
        <div style={{ marginTop: 12 }}>
          <span
            style={{
              display: "inline-block",
              padding: "6px 18px",
              borderRadius: 20,
              fontSize: 13,
              fontWeight: 600,
              color: "#fff",
              background: hex,
            }}
          >
            {decision.final_status}
          </span>
        </div>
      </div>

      {isMock && (
        <div className="alert info">
          当前返回为 Mock 降级数据（后端 Workflow 初始化失败或 GLM-5 API 不可用），用于路演演示。
        </div>
      )}

      <KpiCards decision={decision} />

      <div className="row cols-2" style={{ marginTop: 16 }}>
        {decision.probability_distribution && (
          <ProbabilityChart
            probs={decision.probability_distribution}
            centerLevel={level}
          />
        )}
        {decision.shap_contributions && decision.shap_contributions.length > 0 && (
          <ShapChart contributions={decision.shap_contributions} topN={5} />
        )}
      </div>

      <DecisionAdvice decision={decision} />

      <div className="subtitle" style={{ marginTop: 16 }}>
        🔒 风控拦截状态
      </div>
      <ValidationCards decision={decision} />

      <details open style={{ marginTop: 16 }}>
        <summary
          style={{
            cursor: "pointer",
            color: "#9ca3af",
            fontSize: 13,
            marginBottom: 8,
          }}
        >
          📡 SSE 实时日志（工作流节点执行状态）
        </summary>
        <TimelineLogs nodes={finalNodes} />
      </details>

      <details style={{ marginTop: 12 }}>
        <summary
          style={{
            cursor: "pointer",
            color: "#9ca3af",
            fontSize: 13,
            marginBottom: 8,
          }}
        >
          🔍 原始决策 JSON
        </summary>
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
    <div className="row cols-4">
      <ScadaCard
        title="判定状态"
        value={decision.final_status || "—"}
        glowClass="glow-blue"
      />
      <ScadaCard
        title="判定置信度"
        value={confidence}
        glowClass="glow-green"
      />
      <ScadaCard
        title="三维风险"
        value={tdr?.risk_level ?? "—"}
        sub={tdr?.total_score !== undefined ? `score=${tdr.total_score}` : undefined}
        glowClass={tdr?.blocked ? "glow-red" : "glow-yellow"}
      />
      <ScadaCard
        title="蒙特卡洛"
        value={mc?.confidence !== undefined ? mc.confidence.toFixed(2) : "—"}
        sub={mc ? `valid ${mc.valid_count}/${mc.total_samples}` : undefined}
        glowClass={mc?.passed ? "glow-green" : "glow-orange"}
      />
    </div>
  );
}

function DecisionAdvice({ decision }: { decision: DecisionResponse }) {
  const gov = decision.government_intervention;
  const ent = decision.enterprise_control;
  if (!gov && !ent) return null;
  return (
    <div className="row cols-2" style={{ marginTop: 12 }}>
      {gov && (
        <div className="advice-card" style={{ borderLeftColor: "#ef4444" }}>
          <div className="advice-card-title">🏛️ 政府干预建议</div>
          {gov.department_primary?.name && (
            <div style={{ fontSize: 13, color: "#e5e7eb", marginBottom: 4 }}>
              <b>{gov.department_primary.name}</b>
              {gov.department_primary.contact_role && (
                <span style={{ color: "#9ca3af", marginLeft: 6 }}>
                  ({gov.department_primary.contact_role})
                </span>
              )}
            </div>
          )}
          {gov.department_primary?.action && (
            <div style={{ fontSize: 12, color: "#9ca3af", marginBottom: 8 }}>
              {gov.department_primary.action}
            </div>
          )}
          {gov.actions && gov.actions.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#d1d5db" }}>
              {gov.actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          )}
          {gov.deadline_hours !== undefined && (
            <div
              style={{
                marginTop: 8,
                fontSize: 11,
                color: "#f97316",
                fontFamily: "JetBrains Mono, monospace",
              }}
            >
              ⏱ 处置期限: {gov.deadline_hours} 小时
            </div>
          )}
        </div>
      )}
      {ent && (
        <div className="advice-card" style={{ borderLeftColor: "#3b82f6" }}>
          <div className="advice-card-title">🏭 企业管控建议</div>
          {ent.equipment_id && (
            <div style={{ fontSize: 13, color: "#e5e7eb", marginBottom: 4 }}>
              <b>设备:</b> {ent.equipment_id}
            </div>
          )}
          {ent.operation && (
            <div style={{ fontSize: 12, color: "#9ca3af", marginBottom: 8 }}>
              {ent.operation}
            </div>
          )}
          {ent.parameters && (
            <pre
              style={{
                fontSize: 11,
                background: "#0f172a",
                padding: 8,
                borderRadius: 4,
                color: "#9ca3af",
                margin: 0,
                whiteSpace: "pre-wrap",
              }}
            >
              {JSON.stringify(ent.parameters, null, 2)}
            </pre>
          )}
          {ent.personnel_actions && ent.personnel_actions.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, color: "#d1d5db" }}>
              {ent.personnel_actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function ValidationCards({ decision }: { decision: DecisionResponse }) {
  const items = [
    {
      title: "MARCH 三重隔离校验",
      passed: decision.march_result?.passed,
      detail: decision.march_result?.reason,
      extra:
        decision.march_result?.retry_count !== undefined
          ? `retry: ${decision.march_result.retry_count}`
          : undefined,
    },
    {
      title: "蒙特卡洛置信采样",
      passed: decision.monte_carlo_result?.passed,
      detail: decision.monte_carlo_result?.status,
      extra:
        decision.monte_carlo_result?.confidence !== undefined
          ? `confidence: ${decision.monte_carlo_result.confidence.toFixed(2)} / threshold: ${
              decision.monte_carlo_result.threshold ?? "—"
            }`
          : undefined,
    },
    {
      title: "三维风险评估",
      passed: decision.three_d_risk?.blocked === false,
      detail: decision.three_d_risk?.risk_level,
      extra: decision.three_d_risk?.reason,
    },
  ];
  return (
    <div className="row cols-3">
      {items.map((it, idx) => {
        const cls =
          it.passed === undefined ? "" : it.passed ? "passed" : "failed";
        const status =
          it.passed === undefined
            ? "未执行"
            : it.passed
            ? "✅ 通过"
            : "❌ 拦截";
        const color =
          it.passed === undefined
            ? "#9ca3af"
            : it.passed
            ? "#10b981"
            : "#ef4444";
        return (
          <div className={`validation-card ${cls}`} key={idx}>
            <div className="v-title">{it.title}</div>
            <div className="v-status" style={{ color }}>
              {status}
            </div>
            {it.detail && <div className="v-detail">{it.detail}</div>}
            {it.extra && <div className="v-detail">{it.extra}</div>}
          </div>
        );
      })}
    </div>
  );
}

function TimelineLogs({ nodes }: { nodes: NodeStatus[] }) {
  if (!nodes || nodes.length === 0) {
    return <div style={{ color: "#6b7280", fontSize: 12 }}>暂无节点数据</div>;
  }
  return (
    <div className="timeline-container">
      {nodes.map((ns, idx) => {
        const cls = ns.status === "completed"
          ? "completed"
          : ns.status === "failed"
          ? "failed"
          : ns.status === "running"
          ? "running"
          : "";
        const icon = ns.status === "completed"
          ? "✓"
          : ns.status === "failed"
          ? "✗"
          : "⟳";
        return (
          <div className={`timeline-node ${cls}`} key={idx}>
            <div>
              <div className="node-name">
                {icon} {ns.node}
              </div>
              {ns.detail && <div className="node-detail">{ns.detail}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
