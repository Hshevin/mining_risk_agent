import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchIterationStatus, triggerIteration, fetchIterationTracking } from "../api/client";
import type { IterationStatus, IterationRecord } from "../api/types";
import ReactECharts from "echarts-for-react";

const STATUS_MAP: Record<IterationRecord["status"], { label: string; color: string; bg: string }> = {
  draft: { label: "草稿", color: "#64748b", bg: "rgba(100,116,139,0.12)" },
  testing: { label: "测试中", color: "#3b82f6", bg: "rgba(59,130,246,0.12)" },
  pending_approval: { label: "待审批", color: "#f59e0b", bg: "rgba(245,158,11,0.12)" },
  approved: { label: "已批准", color: "#10b981", bg: "rgba(16,185,129,0.12)" },
  rejected: { label: "已驳回", color: "#ef4444", bg: "rgba(239,68,68,0.12)" },
  canary: { label: "灰度发布", color: "#8b5cf6", bg: "rgba(139,92,246,0.12)" },
  production: { label: "生产环境", color: "#06b6d4", bg: "rgba(6,182,212,0.12)" },
};

const WORKFLOW_STAGES = [
  { key: "draft", label: "版本创建", icon: "📝" },
  { key: "testing", label: "自动测试", icon: "🧪" },
  { key: "pending_approval", label: "审批流程", icon: "📋" },
  { key: "approved", label: "审批通过", icon: "✅" },
  { key: "canary", label: "灰度发布", icon: "🔄" },
  { key: "production", label: "正式上线", icon: "🚀" },
] as const;

const STAGES_ITER = [
  { name: "监控触发检查...", pct: 0.1 },
  { name: "数据清洗与特征工程...", pct: 0.25 },
  { name: "Stacking 模型训练（7基学习器+元学习器）...", pct: 0.45 },
  { name: "5折时序交叉验证...", pct: 0.6 },
  { name: "回归测试与 Drift 分析...", pct: 0.75 },
  { name: "两级终审流程...", pct: 0.85 },
  { name: "灰度发布 0.1 → 0.5 → 1.0...", pct: 0.95 },
  { name: "✅ 迭代完成，模型已上线", pct: 1.0 },
];

let _idCounter = 0;
function nextId() { return `iter_${Date.now()}_${++_idCounter}`; }

const DEMO_RECORDS: IterationRecord[] = [
  {
    id: "iter_v100", version: "v1.0.0", date: "2024-01-15", status: "production", f1: 0.842, samples: 12000,
    description: "初始版本，基于Stacking集成学习架构的风险预警模型",
    improvements: ["建立7基学习器+元学习器Stacking架构", "实现三级风险校验机制", "完成基础预警流程"],
    technical_details: "采用XGBoost、LightGBM、CatBoost等7个基学习器，LogisticRegression作为元学习器，5折时序交叉验证",
    expected_effect: "F1分数达到0.84以上，预警准确率>85%",
    approver: "张工", approval_comment: "满足上线标准，批准发布", approved_at: 1705276800000, created_at: 1704067200000,
  },
  {
    id: "iter_v110", version: "v1.1.0", date: "2024-03-20", status: "production", f1: 0.861, samples: 18500,
    description: "增强版，新增冶金场景支持与特征工程优化",
    improvements: ["新增冶金场景特征提取", "优化SHAP贡献度计算", "增加蒙特卡洛验证采样次数至2000"],
    technical_details: "新增温度场、炉压、气体成分等冶金特征，SHAP计算采用TreeExplainer加速，蒙特卡洛采样从1000提升至2000",
    expected_effect: "冶金场景F1提升至0.85，整体F1达到0.86",
    approver: "李工", approval_comment: "冶金场景验证通过，批准发布", approved_at: 1710892800000, created_at: 1709251200000,
  },
  {
    id: "iter_v200", version: "v2.0.0", date: "2024-06-10", status: "canary", f1: 0.878, samples: 25000,
    description: "重大升级，引入粉尘涉爆场景与三级风险增强",
    improvements: ["新增粉尘涉爆场景完整支持", "实现3D风险评估模型", "优化MARCH校验算法", "增加灰度发布机制"],
    technical_details: "粉尘场景采用专用特征集，3D风险评估整合严重性/相关性/不可逆性维度，MARCH校验增加重试机制",
    expected_effect: "粉尘场景F1>0.83，整体F1达到0.87+，红级预警误报率<8%",
    created_at: 1717977600000,
  },
  {
    id: "iter_v210", version: "v2.1.0", date: "2024-08-22", status: "pending_approval", f1: 0.891, samples: 32000,
    description: "优化版，增强模型泛化能力与实时推理性能",
    improvements: ["引入自适应特征选择机制", "优化推理延迟至<200ms", "增加增量学习支持", "完善预警日志自动生成"],
    technical_details: "自适应特征选择基于互信息增益，推理优化采用模型蒸馏+量化，增量学习支持在线更新权重",
    expected_effect: "推理延迟降低40%，F1达到0.89，支持在线增量更新",
    created_at: 1724284800000,
  },
];

const FALLBACK_STATUS: IterationStatus = {
  current_state: "CANARY",
  current_state_cn: "灰度发布中",
  monitor_summary: { total_samples: 25000, recent_f1: 0.878 },
  pending_approvals: [
    { record_id: "approval_v2_001", model_version: "v2.0.0", status: "SECURITY_APPROVED" },
  ],
};

export default function IterationPage() {
  const [activeSection, setActiveSection] = useState<"dashboard" | "tracking" | "lifecycle" | "approval" | "compare" | "changelog">("dashboard");

  return (
    <div>
      <div className="section-title">🔄 模型迭代全生命周期管理</div>
      <div className="sub-tab-bar">
        {[
          { key: "dashboard" as const, label: "📊 迭代仪表盘" },
          { key: "tracking" as const, label: "📈 准确性追踪" },
          { key: "lifecycle" as const, label: "🔧 生命周期管理" },
          { key: "approval" as const, label: "📋 审批工作流" },
          { key: "compare" as const, label: "📑 版本对比" },
          { key: "changelog" as const, label: "📝 变更日志" },
        ].map((t) => (
          <button key={t.key} type="button" className={`sub-tab ${activeSection === t.key ? "active" : ""}`} onClick={() => setActiveSection(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="divider" />
      {activeSection === "dashboard" && <DashboardSection />}
      {activeSection === "tracking" && <AccuracyTrackingSection />}
      {activeSection === "lifecycle" && <LifecycleSection />}
      {activeSection === "approval" && <ApprovalWorkflowSection />}
      {activeSection === "compare" && <CompareSection />}
      {activeSection === "changelog" && <ChangelogSection />}
    </div>
  );
}

function DashboardSection() {
  const [status, setStatus] = useState<IterationStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [stageIdx, setStageIdx] = useState(0);
  const [pct, setPct] = useState(0);
  const [resultMsg, setResultMsg] = useState<string | null>(null);
  const [records] = useState<IterationRecord[]>(DEMO_RECORDS);

  useEffect(() => { fetchIterationStatus().then((s) => setStatus(s ?? FALLBACK_STATUS)); }, []);

  const runIteration = useCallback(async () => {
    setRunning(true); setResultMsg(null); setStageIdx(0); setPct(0);
    for (let i = 0; i < STAGES_ITER.length; i++) { setStageIdx(i); setPct(STAGES_ITER[i].pct); await new Promise((r) => setTimeout(r, 500)); }
    setRunning(false);
    const real = await triggerIteration();
    if (real) setResultMsg(real.message ?? "后端迭代请求已下发");
    fetchIterationStatus().then((s) => s && setStatus(s));
  }, []);

  const cur = status ?? FALLBACK_STATUS;
  const totalSamples = cur.monitor_summary?.total_samples;
  const recentF1 = cur.monitor_summary?.recent_f1;
  const pending = cur.pending_approvals ?? [];
  const canaryRatio = cur.current_state === "CANARY" ? 0.5 : cur.current_state === "PRODUCTION" ? 1.0 : 0.0;

  const f1TrendOption = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" as const },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: { type: "category" as const, data: records.map((r) => r.version), axisLabel: { color: "#94a3b8", fontSize: 11 }, axisLine: { lineStyle: { color: "#1e293b" } } },
    yAxis: { type: "value" as const, min: 0.8, max: 0.95, axisLabel: { color: "#94a3b8", fontSize: 11 }, splitLine: { lineStyle: { color: "#1e293b" } } },
    series: [{
      type: "line" as const, data: records.map((r) => r.f1), smooth: true, lineStyle: { color: "#3b82f6", width: 3 }, itemStyle: { color: "#3b82f6" },
      areaStyle: { color: { type: "linear" as const, x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(59,130,246,0.3)" }, { offset: 1, color: "rgba(59,130,246,0.02)" }] } },
      markPoint: { data: [{ type: "max" as const, name: "最高" }], symbolSize: 40, label: { fontSize: 10 } },
    }],
  }), [records]);

  return (
    <div>
      <div className="row cols-4" style={{ marginBottom: 14 }}>
        <div className="scada-card" style={{ textAlign: "center", padding: 16 }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>当前状态</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#8b5cf6" }}>{cur.current_state_cn || cur.current_state}</div>
        </div>
        <div className="scada-card" style={{ textAlign: "center", padding: 16 }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>累计样本</div>
          <div className="font-mono" style={{ fontSize: 22, fontWeight: 800, color: "#3b82f6" }}>{typeof totalSamples === "number" ? totalSamples.toLocaleString() : "N/A"}</div>
        </div>
        <div className="scada-card" style={{ textAlign: "center", padding: 16 }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>F1 分数</div>
          <div className="font-mono" style={{ fontSize: 22, fontWeight: 800, color: "#10b981" }}>{typeof recentF1 === "number" ? recentF1.toFixed(3) : "N/A"}</div>
        </div>
        <div className="scada-card" style={{ textAlign: "center", padding: 16 }}>
          <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>待审批</div>
          <div className="font-mono" style={{ fontSize: 22, fontWeight: 800, color: pending.length > 0 ? "#f59e0b" : "#64748b" }}>{pending.length}</div>
        </div>
      </div>
      <div className="row cols-2" style={{ marginBottom: 14 }}>
        <div className="scada-card">
          <div className="risk-report-title" style={{ marginBottom: 10 }}>📈 F1分数趋势</div>
          <ReactECharts option={f1TrendOption} style={{ height: 220 }} />
        </div>
        <div className="scada-card">
          <div className="risk-report-title" style={{ marginBottom: 10 }}>🚀 灰度流量比例</div>
          <div style={{ padding: "20px 0" }}>
            <div className="scada-progress-track" style={{ height: 20 }}><div className="scada-progress-fill" style={{ width: `${canaryRatio * 100}%` }} /></div>
            <div className="font-mono" style={{ fontSize: 13, color: "#94a3b8", marginTop: 10 }}>当前灰度比例: {(canaryRatio * 100).toFixed(0)}%</div>
            <div style={{ marginTop: 16 }}>
              <div className="risk-report-title" style={{ marginBottom: 8 }}>审批状态</div>
              {pending.length === 0 ? <div style={{ color: "#64748b", fontSize: 12 }}>暂无待审批项</div> : pending.map((p, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span className="font-mono" style={{ fontSize: 12, color: "#94a3b8" }}>{p.model_version}</span>
                  <span className="tag" style={{ background: "rgba(245,158,11,0.12)", color: "#fde68a", fontSize: 10 }}>{p.status}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-title" style={{ marginBottom: 10 }}>📜 版本历史</div>
        <table className="scada-table">
          <thead><tr><th>版本</th><th>日期</th><th>状态</th><th>F1</th><th>样本</th><th>审批人</th></tr></thead>
          <tbody>
            {records.map((r) => { const st = STATUS_MAP[r.status]; return (
              <tr key={r.id}>
                <td className="font-mono" style={{ fontWeight: 700 }}>{r.version}</td>
                <td className="font-mono">{r.date}</td>
                <td><span className="tag" style={{ background: st.bg, color: st.color, fontWeight: 700 }}>{st.label}</span></td>
                <td className="font-mono" style={{ fontWeight: 700, color: "#10b981" }}>{r.f1.toFixed(3)}</td>
                <td className="font-mono">{r.samples.toLocaleString()}</td>
                <td style={{ color: "#94a3b8" }}>{r.approver ?? "—"}</td>
              </tr>
            ); })}
          </tbody>
        </table>
      </div>
      <div className="scada-card">
        <div className="risk-report-title" style={{ marginBottom: 10 }}>▶️ 触发模拟迭代</div>
        <button className="scada-btn full-width" type="button" onClick={runIteration} disabled={running}>{running ? "执行中..." : "🚀 触发模拟迭代流水线"}</button>
        {running && <div style={{ marginTop: 12 }}><div className="font-mono" style={{ fontSize: 13, color: "#3b82f6", marginBottom: 6 }}>{STAGES_ITER[stageIdx].name}</div><div className="scada-progress-track"><div className="scada-progress-fill" style={{ width: `${pct * 100}%` }} /></div></div>}
        {resultMsg && <div className="alert info" style={{ marginTop: 12 }}>{resultMsg}</div>}
      </div>
    </div>
  );
}

function AccuracyTrackingSection() {
  const [trackingData, setTrackingData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [periodFilter, setPeriodFilter] = useState("all");

  const loadTracking = useCallback(async () => { setLoading(true); const data = await fetchIterationTracking(); setTrackingData(data); setLoading(false); }, []);
  useEffect(() => { loadTracking(); }, [loadTracking]);

  const history = trackingData?.history || [];
  const filteredHistory = useMemo(() => {
    let items = [...history];
    if (periodFilter !== "all") {
      const now = Date.now() / 1000;
      const periods: Record<string, number> = { "7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400, "180d": 180 * 86400 };
      items = items.filter((i: any) => i.timestamp >= now - (periods[periodFilter] || 0));
    }
    return items;
  }, [history, periodFilter]);

  const accuracyTrendOption = useMemo(() => {
    if (!filteredHistory.length) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent", tooltip: { trigger: "axis" as const },
      legend: { data: ["准确率", "精确率", "召回率", "F1分数"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 55, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: filteredHistory.map((h: any) => h.version), axisLabel: { color: "#94a3b8", fontSize: 11 } },
      yAxis: { type: "value" as const, min: 0.6, max: 1.0, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [
        { name: "准确率", type: "line" as const, data: filteredHistory.map((h: any) => h.accuracy), smooth: true, lineStyle: { width: 3, color: "#3b82f6" }, itemStyle: { color: "#3b82f6" } },
        { name: "精确率", type: "line" as const, data: filteredHistory.map((h: any) => h.precision), smooth: true, lineStyle: { width: 2, color: "#10b981" }, itemStyle: { color: "#10b981" } },
        { name: "召回率", type: "line" as const, data: filteredHistory.map((h: any) => h.recall), smooth: true, lineStyle: { width: 2, color: "#f59e0b" }, itemStyle: { color: "#f59e0b" } },
        { name: "F1分数", type: "line" as const, data: filteredHistory.map((h: any) => h.f1_score), smooth: true, lineStyle: { width: 3, color: "#8b5cf6" }, itemStyle: { color: "#8b5cf6" } },
      ],
    };
  }, [filteredHistory]);

  const errorRateOption = useMemo(() => {
    if (!filteredHistory.length) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent", tooltip: { trigger: "axis" as const },
      legend: { data: ["误报率 (FPR)", "漏报率 (FNR)"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 55, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: filteredHistory.map((h: any) => h.version), axisLabel: { color: "#94a3b8" } },
      yAxis: { type: "value" as const, min: 0, max: 0.3, axisLabel: { color: "#94a3b8", formatter: (v: number) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [
        { name: "误报率 (FPR)", type: "bar" as const, data: filteredHistory.map((h: any) => h.false_positive_rate), itemStyle: { color: "#ef4444", borderRadius: [4, 4, 0, 0] }, barWidth: "30%" },
        { name: "漏报率 (FNR)", type: "bar" as const, data: filteredHistory.map((h: any) => h.false_negative_rate), itemStyle: { color: "#f97316", borderRadius: [4, 4, 0, 0] }, barWidth: "30%" },
      ],
    };
  }, [filteredHistory]);

  const heatmapOption = useMemo(() => {
    if (!filteredHistory.length) return { backgroundColor: "transparent" };
    const metrics = ["准确率", "精确率", "召回率", "F1", "误报率", "漏报率"];
    const versions = filteredHistory.map((h: any) => h.version);
    const data: number[][] = [];
    filteredHistory.forEach((h: any, vi: number) => {
      [h.accuracy, h.precision, h.recall, h.f1_score, 1 - h.false_positive_rate, 1 - h.false_negative_rate].forEach((v: number, mi: number) => { data.push([vi, mi, v]); });
    });
    return {
      backgroundColor: "transparent",
      tooltip: { formatter: (p: any) => `${versions[p.data[0]]} - ${metrics[p.data[1]]}: ${(p.data[2] * 100).toFixed(1)}%` },
      grid: { left: 70, right: 40, top: 10, bottom: 50 },
      xAxis: { type: "category" as const, data: versions, axisLabel: { color: "#94a3b8", fontSize: 10, rotate: 30 } },
      yAxis: { type: "category" as const, data: metrics, axisLabel: { color: "#94a3b8", fontSize: 11 } },
      visualMap: { min: 0.6, max: 1.0, show: true, orient: "vertical" as const, right: 0, top: "center", textStyle: { color: "#94a3b8", fontSize: 10 }, inRange: { color: ["#ef4444", "#f59e0b", "#10b981", "#06b6d4"] } },
      series: [{ type: "heatmap" as const, data, label: { show: true, color: "#fff", fontSize: 9, formatter: (p: any) => `${(p.data[2] * 100).toFixed(0)}%` }, itemStyle: { borderColor: "#0f172a", borderWidth: 2 } }],
    };
  }, [filteredHistory]);

  const comparisonOption = useMemo(() => {
    if (filteredHistory.length < 2) return { backgroundColor: "transparent" };
    const prev = filteredHistory[filteredHistory.length - 2];
    const curr = filteredHistory[filteredHistory.length - 1];
    const mLabels = ["准确率", "精确率", "召回率", "F1分数"];
    return {
      backgroundColor: "transparent", tooltip: { trigger: "axis" as const },
      legend: { data: [prev.version, curr.version], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 55, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: mLabels, axisLabel: { color: "#94a3b8", fontSize: 12 } },
      yAxis: { type: "value" as const, min: 0.6, max: 1.0, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [
        { name: prev.version, type: "bar" as const, data: [prev.accuracy, prev.precision, prev.recall, prev.f1_score], itemStyle: { color: "#64748b", borderRadius: [4, 4, 0, 0] }, barWidth: "25%" },
        { name: curr.version, type: "bar" as const, data: [curr.accuracy, curr.precision, curr.recall, curr.f1_score], itemStyle: { color: "#3b82f6", borderRadius: [4, 4, 0, 0] }, barWidth: "25%" },
      ],
    };
  }, [filteredHistory]);

  const latest = filteredHistory.length > 0 ? filteredHistory[filteredHistory.length - 1] : null;
  const prev = filteredHistory.length > 1 ? filteredHistory[filteredHistory.length - 2] : null;
  const computeDelta = (field: string) => latest && prev ? (latest as any)[field] - (prev as any)[field] : null;
  const deltaAcc = computeDelta("accuracy");
  const deltaF1 = computeDelta("f1_score");
  const deltaFPR = computeDelta("false_positive_rate");
  const deltaFNR = computeDelta("false_negative_rate");
  const ci95 = latest ? { accuracy: (1.96 * Math.sqrt(latest.accuracy * (1 - latest.accuracy) / latest.samples)).toFixed(4), f1: (1.96 * Math.sqrt(latest.f1_score * (1 - latest.f1_score) / latest.samples)).toFixed(4) } : null;

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📈 模型准确性变化追踪</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select className="scada-input" value={periodFilter} onChange={(e) => setPeriodFilter(e.target.value)} style={{ width: 120, fontSize: 12 }}>
              <option value="all">全部时间</option><option value="7d">近7天</option><option value="30d">近30天</option><option value="90d">近90天</option><option value="180d">近180天</option>
            </select>
            <button className="scada-btn secondary" type="button" onClick={loadTracking} disabled={loading}>🔄 刷新</button>
          </div>
        </div>
      </div>
      {latest && (
        <div className="row cols-4" style={{ marginBottom: 14 }}>
          <div className="scada-card" style={{ textAlign: "center", padding: 14 }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>准确率</div>
            <div className="font-mono" style={{ fontSize: 24, fontWeight: 800, color: "#3b82f6" }}>{(latest.accuracy * 100).toFixed(1)}%</div>
            {deltaAcc !== null && <div style={{ fontSize: 11, color: deltaAcc >= 0 ? "#10b981" : "#ef4444", fontWeight: 600 }}>{deltaAcc >= 0 ? "▲" : "▼"} {Math.abs(deltaAcc * 100).toFixed(2)}%</div>}
          </div>
          <div className="scada-card" style={{ textAlign: "center", padding: 14 }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>F1 分数</div>
            <div className="font-mono" style={{ fontSize: 24, fontWeight: 800, color: "#8b5cf6" }}>{(latest.f1_score * 100).toFixed(1)}%</div>
            {deltaF1 !== null && <div style={{ fontSize: 11, color: deltaF1 >= 0 ? "#10b981" : "#ef4444", fontWeight: 600 }}>{deltaF1 >= 0 ? "▲" : "▼"} {Math.abs(deltaF1 * 100).toFixed(2)}%</div>}
          </div>
          <div className="scada-card" style={{ textAlign: "center", padding: 14 }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>误报率 (FPR)</div>
            <div className="font-mono" style={{ fontSize: 24, fontWeight: 800, color: "#ef4444" }}>{(latest.false_positive_rate * 100).toFixed(1)}%</div>
            {deltaFPR !== null && <div style={{ fontSize: 11, color: deltaFPR <= 0 ? "#10b981" : "#ef4444", fontWeight: 600 }}>{deltaFPR <= 0 ? "▼" : "▲"} {Math.abs(deltaFPR * 100).toFixed(2)}%</div>}
          </div>
          <div className="scada-card" style={{ textAlign: "center", padding: 14 }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>漏报率 (FNR)</div>
            <div className="font-mono" style={{ fontSize: 24, fontWeight: 800, color: "#f97316" }}>{(latest.false_negative_rate * 100).toFixed(1)}%</div>
            {deltaFNR !== null && <div style={{ fontSize: 11, color: deltaFNR <= 0 ? "#10b981" : "#ef4444", fontWeight: 600 }}>{deltaFNR <= 0 ? "▼" : "▲"} {Math.abs(deltaFNR * 100).toFixed(2)}%</div>}
          </div>
        </div>
      )}
      {latest && ci95 && (
        <div className="scada-card" style={{ marginBottom: 14 }}>
          <div className="risk-report-title" style={{ marginBottom: 10 }}>📊 置信区间与统计显著性</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
            <div style={{ padding: 12, background: "rgba(15,23,42,0.5)", borderRadius: 8, border: "1px solid #1e293b" }}>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>95% 置信区间</div>
              <div style={{ fontSize: 13, color: "#e5e7eb" }}><div>准确率: {(latest.accuracy * 100).toFixed(1)}% ±{ci95.accuracy}</div><div>F1分数: {(latest.f1_score * 100).toFixed(1)}% ±{ci95.f1}</div></div>
            </div>
            <div style={{ padding: 12, background: "rgba(15,23,42,0.5)", borderRadius: 8, border: "1px solid #1e293b" }}>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>样本量</div>
              <div className="font-mono" style={{ fontSize: 20, fontWeight: 800, color: "#3b82f6" }}>{latest.samples?.toLocaleString()}</div>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>训练数据量</div>
            </div>
            <div style={{ padding: 12, background: "rgba(15,23,42,0.5)", borderRadius: 8, border: "1px solid #1e293b" }}>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>统计显著性</div>
              {deltaAcc !== null && (
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 20 }}>{Math.abs(deltaAcc) > 0.02 ? "✅" : "⚠️"}</span>
                  <div><div style={{ fontSize: 13, color: Math.abs(deltaAcc) > 0.02 ? "#10b981" : "#f59e0b" }}>{Math.abs(deltaAcc) > 0.02 ? "显著改善" : "变化不显著"}</div><div style={{ fontSize: 11, color: "#94a3b8" }}>p &lt; 0.05 阈值</div></div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      <div className="row cols-2" style={{ marginBottom: 14 }}>
        <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📈 准确性趋势（多指标）</div><ReactECharts option={accuracyTrendOption} style={{ height: 300 }} /></div>
        <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📊 误报/漏报率对比</div><ReactECharts option={errorRateOption} style={{ height: 300 }} /></div>
      </div>
      <div className="row cols-2" style={{ marginBottom: 14 }}>
        <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>🔥 迭代性能热力图</div><ReactECharts option={heatmapOption} style={{ height: 300 }} /></div>
        <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📊 迭代前后对比</div><ReactECharts option={comparisonOption} style={{ height: 300 }} /></div>
      </div>
      {filteredHistory.length > 0 && (
        <div className="scada-card">
          <div className="risk-report-title" style={{ marginBottom: 10 }}>📋 迭代追踪详细数据</div>
          <table className="scada-table">
            <thead><tr><th>版本</th><th>时间</th><th>准确率</th><th>精确率</th><th>召回率</th><th>F1</th><th>FPR</th><th>FNR</th><th>样本</th><th>改进</th></tr></thead>
            <tbody>
              {filteredHistory.map((h: any, i: number) => (
                <tr key={i}>
                  <td className="font-mono" style={{ fontWeight: 700 }}>{h.version}</td>
                  <td style={{ fontSize: 11, color: "#94a3b8" }}>{h.time}</td>
                  <td className="font-mono" style={{ color: "#3b82f6" }}>{(h.accuracy * 100).toFixed(1)}%</td>
                  <td className="font-mono" style={{ color: "#10b981" }}>{(h.precision * 100).toFixed(1)}%</td>
                  <td className="font-mono" style={{ color: "#f59e0b" }}>{(h.recall * 100).toFixed(1)}%</td>
                  <td className="font-mono" style={{ fontWeight: 700, color: "#8b5cf6" }}>{(h.f1_score * 100).toFixed(1)}%</td>
                  <td className="font-mono" style={{ color: "#ef4444" }}>{(h.false_positive_rate * 100).toFixed(1)}%</td>
                  <td className="font-mono" style={{ color: "#f97316" }}>{(h.false_negative_rate * 100).toFixed(1)}%</td>
                  <td className="font-mono">{h.samples?.toLocaleString()}</td>
                  <td>{h.improvements?.map((imp: string, j: number) => <span key={j} className="tag tag-cyan" style={{ fontSize: 9, margin: 1 }}>{imp}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function LifecycleSection() {
  const [records, setRecords] = useState<IterationRecord[]>(DEMO_RECORDS);
  const [showCreate, setShowCreate] = useState(false);
  const [newVersion, setNewVersion] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newImprovements, setNewImprovements] = useState("");
  const [newTechDetails, setNewTechDetails] = useState("");
  const [newExpectedEffect, setNewExpectedEffect] = useState("");
  const [selectedRecord, setSelectedRecord] = useState<IterationRecord | null>(null);
  const [testRunning, setTestRunning] = useState<string | null>(null);

  const createVersion = useCallback(() => {
    if (!newVersion.trim() || !newDesc.trim()) return;
    setRecords((p) => [{ id: nextId(), version: newVersion.trim(), date: new Date().toISOString().slice(0, 10), status: "draft" as const, f1: 0, samples: 0, description: newDesc.trim(), improvements: newImprovements.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean), technical_details: newTechDetails.trim(), expected_effect: newExpectedEffect.trim(), created_at: Date.now() }, ...p]);
    setNewVersion(""); setNewDesc(""); setNewImprovements(""); setNewTechDetails(""); setNewExpectedEffect(""); setShowCreate(false);
  }, [newVersion, newDesc, newImprovements, newTechDetails, newExpectedEffect]);

  const startTest = useCallback((id: string) => { setTestRunning(id); setTimeout(() => { setRecords((p) => p.map((r) => r.id === id ? { ...r, status: "testing" as const, f1: 0.85 + Math.random() * 0.05, samples: Math.floor(20000 + Math.random() * 15000) } : r)); setTestRunning(null); }, 2000); }, []);
  const submitForApproval = useCallback((id: string) => { setRecords((p) => p.map((r) => r.id === id ? { ...r, status: "pending_approval" as const } : r)); }, []);
  const getWorkflowProgress = useCallback((status: IterationRecord["status"]) => { return ["draft", "testing", "pending_approval", "approved", "canary", "production"].indexOf(status); }, []);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">🔧 版本全生命周期管理</div>
          <button className="scada-btn" type="button" onClick={() => setShowCreate(!showCreate)}>{showCreate ? "取消创建" : "➕ 创建新版本"}</button>
        </div>
        {showCreate && (
          <div style={{ marginTop: 14, padding: 16, background: "var(--bg-input)", borderRadius: 8, border: "1px solid var(--border-mid)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div><label className="scada-label">版本号</label><input className="scada-input" value={newVersion} onChange={(e) => setNewVersion(e.target.value)} placeholder="例如: v2.2.0" /></div>
              <div><label className="scada-label">预期效果</label><input className="scada-input" value={newExpectedEffect} onChange={(e) => setNewExpectedEffect(e.target.value)} placeholder="预期达到的效果" /></div>
            </div>
            <label className="scada-label" style={{ marginTop: 10 }}>版本描述</label>
            <textarea className="scada-input" style={{ minHeight: 50, resize: "vertical" }} value={newDesc} onChange={(e) => setNewDesc(e.target.value)} placeholder="描述本次迭代的主要内容..." />
            <label className="scada-label" style={{ marginTop: 10 }}>改进点（逗号或换行分隔）</label>
            <textarea className="scada-input" style={{ minHeight: 40, resize: "vertical" }} value={newImprovements} onChange={(e) => setNewImprovements(e.target.value)} placeholder="改进点1, 改进点2..." />
            <label className="scada-label" style={{ marginTop: 10 }}>技术实现方案</label>
            <textarea className="scada-input" style={{ minHeight: 50, resize: "vertical" }} value={newTechDetails} onChange={(e) => setNewTechDetails(e.target.value)} placeholder="详细的技术实现方案..." />
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}><button className="scada-btn" type="button" onClick={createVersion}>✅ 创建版本</button><button className="scada-btn secondary" type="button" onClick={() => setShowCreate(false)}>取消</button></div>
          </div>
        )}
      </div>
      {records.map((rec) => {
        const st = STATUS_MAP[rec.status]; const progress = getWorkflowProgress(rec.status);
        return (
          <div key={rec.id} className="scada-card" style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <span className="font-mono" style={{ fontSize: 16, fontWeight: 800, color: "#f1f5f9" }}>{rec.version}</span>
              <span className="tag" style={{ background: st.bg, color: st.color, fontWeight: 700 }}>{st.label}</span>
              <span style={{ color: "#64748b", fontSize: 11, fontFamily: "JetBrains Mono, monospace" }}>{rec.date}</span>
              {rec.f1 > 0 && <span className="tag tag-emerald" style={{ fontSize: 10 }}>F1: {rec.f1.toFixed(3)}</span>}
              {rec.samples > 0 && <span className="tag tag-blue" style={{ fontSize: 10 }}>样本: {rec.samples.toLocaleString()}</span>}
              <button className="icon-btn" style={{ marginLeft: "auto" }} type="button" onClick={() => setSelectedRecord(selectedRecord?.id === rec.id ? null : rec)} title="查看详情">{selectedRecord?.id === rec.id ? "▲" : "▼"}</button>
            </div>
            <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
              {WORKFLOW_STAGES.map((ws, i) => (<div key={ws.key} style={{ flex: 1, textAlign: "center" }}><div style={{ fontSize: 16, marginBottom: 2, opacity: i <= progress ? 1 : 0.3 }}>{ws.icon}</div><div style={{ fontSize: 9, color: i <= progress ? "#94a3b8" : "#475569", fontWeight: i <= progress ? 600 : 400 }}>{ws.label}</div></div>))}
            </div>
            <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>{rec.description}</div>
            {rec.improvements && rec.improvements.length > 0 && (<div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 8 }}>{rec.improvements.map((imp, i) => (<span key={i} className="tag tag-cyan" style={{ fontSize: 10 }}>{imp}</span>))}</div>)}
            {selectedRecord?.id === rec.id && (
              <div style={{ marginTop: 12, padding: 14, background: "rgba(15,23,42,0.5)", borderRadius: 8, border: "1px solid #1e293b" }}>
                {rec.technical_details && (<div style={{ marginBottom: 10 }}><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>技术实现方案</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{rec.technical_details}</div></div>)}
                {rec.expected_effect && (<div style={{ marginBottom: 10 }}><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>预期效果</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{rec.expected_effect}</div></div>)}
                {rec.approver && (<div><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>审批信息</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>审批人: {rec.approver} | 意见: {rec.approval_comment || "无"}</div></div>)}
              </div>
            )}
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              {rec.status === "draft" && (<button className="scada-btn" style={{ fontSize: 11, padding: "4px 10px" }} type="button" onClick={() => startTest(rec.id)} disabled={testRunning === rec.id}>{testRunning === rec.id ? "测试中..." : "🧪 开始测试"}</button>)}
              {rec.status === "testing" && (<button className="scada-btn" style={{ fontSize: 11, padding: "4px 10px" }} type="button" onClick={() => submitForApproval(rec.id)}>📋 提交审批</button>)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ApprovalWorkflowSection() {
  const [records, setRecords] = useState<IterationRecord[]>(DEMO_RECORDS);
  const [approvalComment, setApprovalComment] = useState<Record<string, string>>({});
  const pendingRecords = records.filter((r) => r.status === "pending_approval");
  const processedRecords = records.filter((r) => r.status === "approved" || r.status === "rejected");

  const handleApprove = useCallback((id: string) => { const comment = approvalComment[id] || "审批通过"; setRecords((prev) => prev.map((r) => r.id === id ? { ...r, status: "approved" as const, approver: "管理员", approval_comment: comment, approved_at: Date.now() } : r)); }, [approvalComment]);
  const handleReject = useCallback((id: string) => { const comment = approvalComment[id] || ""; if (!comment.trim()) return; setRecords((prev) => prev.map((r) => r.id === id ? { ...r, status: "rejected" as const, approver: "管理员", approval_comment: comment } : r)); }, [approvalComment]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📋 迭代审批工作流</div>
          <span className="tag tag-orange">待审批: {pendingRecords.length}</span>
        </div>
      </div>
      {pendingRecords.length === 0 ? (
        <div className="scada-card"><div className="empty-state"><div className="empty-state-icon">✅</div><div>暂无待审批的迭代版本</div></div></div>
      ) : (
        pendingRecords.map((rec) => {
          const prevRec = records.find((r) => r.id !== rec.id && r.f1 > 0);
          return (
            <div key={rec.id} className="scada-card" style={{ marginBottom: 14 }}>
              <div className="risk-report-title" style={{ marginBottom: 12 }}>审批请求: {rec.version} - {rec.description}</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 14 }}>
                <div style={{ padding: 14, background: "rgba(100,116,139,0.08)", borderRadius: 8, border: "1px solid #334155" }}>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8, fontWeight: 600 }}>当前生产版本</div>
                  {prevRec ? <div><div style={{ fontSize: 14, fontWeight: 700, color: "#94a3b8" }}>{prevRec.version}</div><div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>F1: {prevRec.f1.toFixed(3)} | 样本: {prevRec.samples.toLocaleString()}</div></div> : <div style={{ color: "#64748b", fontSize: 12 }}>无历史版本</div>}
                </div>
                <div style={{ padding: 14, background: "rgba(59,130,246,0.08)", borderRadius: 8, border: "1px solid rgba(59,130,246,0.3)" }}>
                  <div style={{ fontSize: 12, color: "#3b82f6", marginBottom: 8, fontWeight: 600 }}>待审批版本</div>
                  <div><div style={{ fontSize: 14, fontWeight: 700, color: "#3b82f6" }}>{rec.version}</div><div style={{ fontSize: 12, color: "#94a3b8", marginTop: 4 }}>F1: {rec.f1.toFixed(3)} | 样本: {rec.samples.toLocaleString()}</div></div>
                </div>
              </div>
              {rec.improvements && rec.improvements.length > 0 && (<div style={{ marginBottom: 12 }}><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>改进点</div><div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{rec.improvements.map((imp, i) => (<span key={i} className="tag tag-cyan" style={{ fontSize: 10 }}>{imp}</span>))}</div></div>)}
              {rec.technical_details && (<div style={{ marginBottom: 12 }}><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>技术方案</div><div style={{ fontSize: 12, color: "#e5e7eb" }}>{rec.technical_details}</div></div>)}
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>审批意见（必填）</div>
                <textarea className="scada-input" style={{ minHeight: 50, resize: "vertical" }} placeholder="请输入审批意见..." value={approvalComment[rec.id] || ""} onChange={(e) => setApprovalComment({ ...approvalComment, [rec.id]: e.target.value })} />
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="scada-btn" style={{ background: "#10b981" }} type="button" onClick={() => handleApprove(rec.id)}>✅ 批准发布</button>
                <button className="scada-btn" style={{ background: "#ef4444" }} type="button" onClick={() => handleReject(rec.id)} disabled={!approvalComment[rec.id]?.trim()}>❌ 驳回</button>
              </div>
            </div>
          );
        })
      )}
      {processedRecords.length > 0 && (
        <div className="scada-card">
          <div className="risk-report-title" style={{ marginBottom: 10 }}>📜 审批历史</div>
          <table className="scada-table">
            <thead><tr><th>版本</th><th>状态</th><th>审批人</th><th>审批意见</th><th>审批时间</th></tr></thead>
            <tbody>
              {processedRecords.map((rec) => { const st = STATUS_MAP[rec.status]; return (
                <tr key={rec.id}>
                  <td className="font-mono" style={{ fontWeight: 700 }}>{rec.version}</td>
                  <td><span className="tag" style={{ background: st.bg, color: st.color, fontWeight: 700 }}>{st.label}</span></td>
                  <td>{rec.approver || "—"}</td>
                  <td style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{rec.approval_comment || "—"}</td>
                  <td style={{ fontSize: 11, color: "#94a3b8" }}>{rec.approved_at ? new Date(rec.approved_at).toLocaleDateString("zh-CN") : "—"}</td>
                </tr>
              ); })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CompareSection() {
  const [records] = useState<IterationRecord[]>(DEMO_RECORDS);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const selectedRecords = records.filter((r) => selectedIds.includes(r.id));
  const toggleSelect = useCallback((id: string) => { setSelectedIds((prev) => { if (prev.includes(id)) return prev.filter((i) => i !== id); if (prev.length >= 3) return prev; return [...prev, id]; }); }, []);

  const radarOption = useMemo(() => {
    if (selectedRecords.length === 0) return { backgroundColor: "transparent" };
    const indicators = [{ name: "F1分数", max: 1.0 }, { name: "样本量(归一化)", max: 1.0 }, { name: "稳定性", max: 1.0 }, { name: "场景覆盖", max: 1.0 }, { name: "推理速度(归一化)", max: 1.0 }];
    const maxSamples = Math.max(...records.map((r) => r.samples), 1);
    const series = selectedRecords.map((r) => ({ value: [r.f1, r.samples / maxSamples, 0.7 + r.f1 * 0.3, r.improvements ? Math.min(r.improvements.length / 5, 1) : 0.3, 0.6 + Math.random() * 0.3], name: r.version }));
    return {
      backgroundColor: "transparent", tooltip: {},
      legend: { data: selectedRecords.map((r) => r.version), textStyle: { color: "#94a3b8", fontSize: 11 }, bottom: 0 },
      radar: { indicator: indicators, shape: "polygon" as const, splitNumber: 4, axisName: { color: "#94a3b8", fontSize: 11 }, splitLine: { lineStyle: { color: "#1e293b" } }, splitArea: { areaStyle: { color: ["rgba(15,23,42,0.3)", "rgba(15,23,42,0.6)"] } } },
      series: [{ type: "radar" as const, data: series, lineStyle: { width: 2 }, areaStyle: { opacity: 0.15 } }],
    };
  }, [selectedRecords, records]);

  const barCompareOption = useMemo(() => {
    if (selectedRecords.length === 0) return { backgroundColor: "transparent" };
    const versions = selectedRecords.map((r) => r.version);
    return {
      backgroundColor: "transparent", tooltip: { trigger: "axis" as const },
      legend: { data: versions, textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: ["F1分数", "样本量(千)"], axisLabel: { color: "#94a3b8" } },
      yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: selectedRecords.map((r, i) => ({ name: r.version, type: "bar" as const, data: [r.f1, r.samples / 1000], itemStyle: { color: ["#3b82f6", "#8b5cf6", "#10b981"][i % 3], borderRadius: [4, 4, 0, 0] }, barWidth: "20%" })),
    };
  }, [selectedRecords]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📑 版本对比分析</div>
          <span className="tag tag-blue">已选: {selectedIds.length}/3</span>
        </div>
        <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 8 }}>选择2-3个版本进行对比分析</div>
      </div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <table className="scada-table">
          <thead><tr><th>选择</th><th>版本</th><th>日期</th><th>状态</th><th>F1</th><th>样本</th><th>描述</th></tr></thead>
          <tbody>
            {records.map((r) => { const st = STATUS_MAP[r.status]; const selected = selectedIds.includes(r.id); return (
              <tr key={r.id} style={{ background: selected ? "rgba(59,130,246,0.08)" : undefined }}>
                <td><input type="checkbox" checked={selected} onChange={() => toggleSelect(r.id)} disabled={!selected && selectedIds.length >= 3} /></td>
                <td className="font-mono" style={{ fontWeight: 700 }}>{r.version}</td>
                <td className="font-mono">{r.date}</td>
                <td><span className="tag" style={{ background: st.bg, color: st.color, fontWeight: 700 }}>{st.label}</span></td>
                <td className="font-mono" style={{ fontWeight: 700, color: "#10b981" }}>{r.f1.toFixed(3)}</td>
                <td className="font-mono">{r.samples.toLocaleString()}</td>
                <td style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.description}</td>
              </tr>
            ); })}
          </tbody>
        </table>
      </div>
      {selectedRecords.length >= 2 && (
        <>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>🎯 雷达图对比</div><ReactECharts option={radarOption} style={{ height: 320 }} /></div>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📊 柱状图对比</div><ReactECharts option={barCompareOption} style={{ height: 320 }} /></div>
          </div>
          <div className="scada-card">
            <div className="risk-report-title" style={{ marginBottom: 10 }}>📋 详细对比表</div>
            <table className="scada-table">
              <thead><tr><th>指标</th>{selectedRecords.map((r) => (<th key={r.id} style={{ color: "#3b82f6" }}>{r.version}</th>))}</tr></thead>
              <tbody>
                <tr><td style={{ color: "#94a3b8" }}>F1分数</td>{selectedRecords.map((r) => <td key={r.id} className="font-mono" style={{ fontWeight: 700, color: "#8b5cf6" }}>{r.f1.toFixed(3)}</td>)}</tr>
                <tr><td style={{ color: "#94a3b8" }}>样本量</td>{selectedRecords.map((r) => <td key={r.id} className="font-mono">{r.samples.toLocaleString()}</td>)}</tr>
                <tr><td style={{ color: "#94a3b8" }}>状态</td>{selectedRecords.map((r) => { const st = STATUS_MAP[r.status]; return <td key={r.id}><span className="tag" style={{ background: st.bg, color: st.color, fontWeight: 700 }}>{st.label}</span></td>; })}</tr>
                <tr><td style={{ color: "#94a3b8" }}>描述</td>{selectedRecords.map((r) => <td key={r.id} style={{ fontSize: 12 }}>{r.description}</td>)}</tr>
                <tr><td style={{ color: "#94a3b8" }}>改进点</td>{selectedRecords.map((r) => <td key={r.id}>{r.improvements?.map((imp, i) => <span key={i} className="tag tag-cyan" style={{ fontSize: 9, margin: 1 }}>{imp}</span>)}</td>)}</tr>
                <tr><td style={{ color: "#94a3b8" }}>技术方案</td>{selectedRecords.map((r) => <td key={r.id} style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.technical_details || "—"}</td>)}</tr>
                <tr><td style={{ color: "#94a3b8" }}>审批人</td>{selectedRecords.map((r) => <td key={r.id}>{r.approver || "—"}</td>)}</tr>
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function ChangelogSection() {
  const [records] = useState<IterationRecord[]>(DEMO_RECORDS);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState("");
  const filteredRecords = useMemo(() => { if (!filterStatus) return records; return records.filter((r) => r.status === filterStatus); }, [records, filterStatus]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📝 迭代变更日志</div>
          <div style={{ display: "flex", gap: 8 }}>
            <select className="scada-input" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} style={{ width: 120, fontSize: 12 }}>
              <option value="">全部状态</option><option value="production">生产环境</option><option value="canary">灰度发布</option><option value="pending_approval">待审批</option><option value="approved">已批准</option><option value="rejected">已驳回</option>
            </select>
          </div>
        </div>
      </div>
      <div style={{ position: "relative", paddingLeft: 24 }}>
        <div style={{ position: "absolute", left: 10, top: 0, bottom: 0, width: 2, background: "linear-gradient(to bottom, #3b82f6, #8b5cf6, #10b981)" }} />
        {filteredRecords.map((rec) => {
          const st = STATUS_MAP[rec.status];
          return (
            <div key={rec.id} style={{ position: "relative", marginBottom: 16, paddingLeft: 20 }}>
              <div style={{ position: "absolute", left: -20, top: 12, width: 16, height: 16, borderRadius: "50%", background: st.color, border: "3px solid #0f172a", zIndex: 1 }} />
              <div className="scada-card" style={{ cursor: "pointer" }} onClick={() => setExpandedId(expandedId === rec.id ? null : rec.id)}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span className="font-mono" style={{ fontSize: 15, fontWeight: 800, color: "#f1f5f9" }}>{rec.version}</span>
                  <span className="tag" style={{ background: st.bg, color: st.color, fontWeight: 700 }}>{st.label}</span>
                  <span style={{ fontSize: 11, color: "#64748b" }}>{rec.date}</span>
                  {rec.f1 > 0 && <span className="tag tag-emerald" style={{ fontSize: 10 }}>F1: {rec.f1.toFixed(3)}</span>}
                  <span style={{ marginLeft: "auto", color: "#64748b", fontSize: 12 }}>{expandedId === rec.id ? "▼" : "▶"}</span>
                </div>
                <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 6 }}>{rec.description}</div>
                {rec.improvements && rec.improvements.length > 0 && (<div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>{rec.improvements.map((imp, i) => (<span key={i} className="tag tag-cyan" style={{ fontSize: 9 }}>{imp}</span>))}</div>)}
                {expandedId === rec.id && (
                  <div style={{ marginTop: 12, padding: 14, background: "rgba(15,23,42,0.5)", borderRadius: 8, border: "1px solid #1e293b" }}>
                    {rec.technical_details && (<div style={{ marginBottom: 10 }}><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>技术实现方案</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{rec.technical_details}</div></div>)}
                    {rec.expected_effect && (<div style={{ marginBottom: 10 }}><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>预期效果</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{rec.expected_effect}</div></div>)}
                    {rec.approver && (<div><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>审批信息</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>审批人: {rec.approver} | 意见: {rec.approval_comment || "无"} | 时间: {rec.approved_at ? new Date(rec.approved_at).toLocaleDateString("zh-CN") : "—"}</div></div>)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
