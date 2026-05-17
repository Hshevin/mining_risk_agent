import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  importEnterpriseData,
  importExcelFile,
  assessEnterpriseFile,
  batchRiskAssessment,
  fetchEnterpriseDataSummary,
  fetchMemoryStats,
  fetchWarningExperiences,
  fetchEnterpriseRiskHistory,
  fetchApprovals,
  decideApproval,
  fetchAuditLogs,
  exportMemoryData,
  queryShortTermMemoryPaginated,
  queryLongTermMemoryPaginated,
  migrateToLongTerm,
  deleteShortTermMemory,
} from "../api/client";
import ReactECharts from "echarts-for-react";

const PRIO_COLORS: Record<string, string> = { P0: "#ef4444", P1: "#f97316", P2: "#3b82f6", P3: "#10b981" };
const PRIO_BG: Record<string, string> = { P0: "rgba(239,68,68,0.15)", P1: "rgba(249,115,22,0.15)", P2: "rgba(59,130,246,0.15)", P3: "rgba(16,185,129,0.15)" };
const LEVEL_COLORS: Record<string, string> = { 红: "#ef4444", 橙: "#f97316", 黄: "#eab308", 蓝: "#3b82f6" };
const LEVEL_BG: Record<string, string> = { 红: "rgba(239,68,68,0.12)", 橙: "rgba(249,115,22,0.12)", 黄: "rgba(234,179,8,0.12)", 蓝: "rgba(59,130,246,0.12)" };
const CAT_LABELS: Record<string, string> = {
  inference: "推理过程", warning: "预警记录", experience: "预警经验", context: "上下文",
  enterprise_data: "企业数据", knowledge: "知识库", regulation: "法规标准",
  accident_case: "事故案例", warning_experience: "预警经验",
};
const CAT_COLORS: Record<string, string> = {
  inference: "#3b82f6", warning: "#ef4444", experience: "#8b5cf6", context: "#64748b",
  enterprise_data: "#10b981", knowledge: "#06b6d4", regulation: "#f59e0b",
  accident_case: "#f97316", warning_experience: "#ec4899",
};

interface EnterpriseRiskResult {
  enterprise_id: string;
  enterprise_name: string;
  risk_score: number;
  risk_level: string;
  scenario: string;
  assessment_time: string;
  key_factors: Array<{ name: string; value: number; color: string }>;
  inference_stored: boolean;
}

function StatCard({ value, label, color, icon }: { value: number; label: string; color: string; icon?: string }) {
  return (
    <div className="scada-card" style={{ textAlign: "center", padding: 16, position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: -10, right: -10, fontSize: 40, opacity: 0.08, color }}>{icon || "📊"}</div>
      <div style={{ fontSize: 28, fontWeight: 800, color, fontFamily: "JetBrains Mono", position: "relative" }}>{value.toLocaleString()}</div>
      <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4, position: "relative" }}>{label}</div>
    </div>
  );
}

function ExportDialog({ memoryType, onClose }: { memoryType: string; onClose: () => void }) {
  const [format, setFormat] = useState("xlsx");
  const [timeFrom, setTimeFrom] = useState("");
  const [timeTo, setTimeTo] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [filterEnterprise, setFilterEnterprise] = useState("");
  const [exporting, setExporting] = useState(false);
  const [msg, setMsg] = useState("");

  const handleExport = useCallback(async () => {
    setExporting(true);
    setMsg("正在导出...");
    const payload: any = { memory_type: memoryType, format };
    if (timeFrom) payload.time_from = new Date(timeFrom).getTime() / 1000;
    if (timeTo) payload.time_to = new Date(timeTo).getTime() / 1000;
    const filters: Record<string, any> = {};
    if (filterCategory) filters.category = filterCategory;
    if (filterPriority) filters.priority = filterPriority;
    if (filterEnterprise) filters.enterprise_id = filterEnterprise;
    if (Object.keys(filters).length > 0) payload.filters = filters;
    const blob = await exportMemoryData(payload);
    if (!blob) { setMsg("❌ 导出失败"); setExporting(false); return; }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${memoryType}_export_${new Date().toISOString().slice(0, 10)}.${format}`;
    a.click();
    URL.revokeObjectURL(url);
    setMsg("✅ 导出成功");
    setExporting(false);
  }, [format, timeFrom, timeTo, filterCategory, filterPriority, filterEnterprise, memoryType]);

  const typeLabel = memoryType === "short" ? "短期记忆" : memoryType === "long" ? "长期记忆" : "预警经验";

  return (
    <div className="scada-card" style={{ marginBottom: 14, border: "1px solid #3b82f6" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div className="risk-report-title">📤 导出 {typeLabel}</div>
        <button className="scada-btn secondary" style={{ fontSize: 11, padding: "2px 8px" }} type="button" onClick={onClose}>✕ 关闭</button>
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4 }}>导出格式</div>
          <select className="scada-input" value={format} onChange={(e) => setFormat(e.target.value)} style={{ width: 120 }}>
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="csv">CSV (.csv)</option>
            <option value="pdf">PDF (.pdf)</option>
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4 }}>起始时间</div>
          <input className="scada-input" type="date" value={timeFrom} onChange={(e) => setTimeFrom(e.target.value)} style={{ width: 150 }} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4 }}>截止时间</div>
          <input className="scada-input" type="date" value={timeTo} onChange={(e) => setTimeTo(e.target.value)} style={{ width: 150 }} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4 }}>分类筛选</div>
          <select className="scada-input" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)} style={{ width: 120 }}>
            <option value="">全部分类</option>
            <option value="inference">推理过程</option>
            <option value="warning">预警记录</option>
            <option value="experience">预警经验</option>
            <option value="context">上下文</option>
            <option value="enterprise_data">企业数据</option>
            <option value="knowledge">知识库</option>
            <option value="regulation">法规标准</option>
            <option value="accident_case">事故案例</option>
            <option value="warning_experience">预警经验</option>
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4 }}>优先级</div>
          <select className="scada-input" value={filterPriority} onChange={(e) => setFilterPriority(e.target.value)} style={{ width: 100 }}>
            <option value="">全部</option>
            <option value="P0">P0</option>
            <option value="P1">P1</option>
            <option value="P2">P2</option>
            <option value="P3">P3</option>
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 4 }}>企业ID</div>
          <input className="scada-input" placeholder="输入企业ID..." value={filterEnterprise} onChange={(e) => setFilterEnterprise(e.target.value)} style={{ width: 130 }} />
        </div>
        <button className="scada-btn" type="button" onClick={handleExport} disabled={exporting}>{exporting ? "导出中..." : "📥 执行导出"}</button>
      </div>
      {msg && <div className={`alert ${msg.includes("✅") ? "success" : msg.includes("❌") ? "error" : "info"}`} style={{ marginTop: 10 }}>{msg}</div>}
    </div>
  );
}

export default function KnowledgeMemoryPage() {
  const [activeSection, setActiveSection] = useState<"overview" | "data" | "risk" | "import" | "short" | "long" | "experience" | "approval" | "audit">("overview");

  return (
    <div>
      <div className="section-title">📚 预警经验管理系统</div>
      <div className="sub-tab-bar">
        {[
          { key: "overview" as const, label: "📊 总览仪表盘" },
          { key: "data" as const, label: "📊 数据管理" },
          { key: "risk" as const, label: "🎯 风险评估" },
          { key: "import" as const, label: "📥 导入预测" },
          { key: "experience" as const, label: "⚡ 预警经验" },
          { key: "short" as const, label: "🧠 短期记忆" },
          { key: "long" as const, label: "💾 长期记忆" },
          { key: "approval" as const, label: "📋 审批管理" },
          { key: "audit" as const, label: "🔍 审计日志" },
        ].map((t) => (
          <button key={t.key} type="button" className={`sub-tab ${activeSection === t.key ? "active" : ""}`} onClick={() => setActiveSection(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="divider" />
      {activeSection === "overview" && <OverviewDashboard />}
      {activeSection === "data" && <DataManagementSection />}
      {activeSection === "risk" && <RiskVisualizationSection />}
      {activeSection === "import" && <ExcelImportSection />}
      {activeSection === "experience" && <WarningExperienceSection />}
      {activeSection === "short" && <ShortTermMemorySection />}
      {activeSection === "long" && <LongTermMemorySection />}
      {activeSection === "approval" && <ApprovalSection />}
      {activeSection === "audit" && <AuditLogSection />}
    </div>
  );
}

function OverviewDashboard() {
  const [memStats, setMemStats] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const loadStats = useCallback(async () => {
    setLoading(true);
    const stats = await fetchMemoryStats();
    if (stats) setMemStats(stats);
    setLoading(false);
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  const shortTotal = memStats?.short_term?.total ?? 0;
  const longTotal = memStats?.long_term?.total ?? 0;
  const weTotal = memStats?.warning_experiences?.total ?? 0;
  const grandTotal = shortTotal + longTotal + weTotal;

  const combinedTimelineOption = useMemo(() => {
    const st = memStats?.short_term?.timeline || {};
    const lt = memStats?.long_term?.timeline || {};
    const wt = memStats?.warning_experiences?.timeline || {};
    const allDays = new Set([...Object.keys(st), ...Object.keys(lt), ...Object.keys(wt)]);
    const sorted = [...allDays].sort();
    if (!sorted.length) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      legend: { data: ["短期记忆", "长期记忆", "预警经验"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 55, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: sorted.map((d) => d.slice(5)), axisLabel: { color: "#94a3b8", fontSize: 10 } },
      yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      dataZoom: [{ type: "inside", start: 0, end: 100 }, { type: "slider", start: 0, end: 100, height: 20, bottom: 5, borderColor: "#334155", backgroundColor: "#0f172a", dataBackground: { lineStyle: { color: "#334155" }, areaStyle: { color: "#1e293b" } }, selectedDataBackground: { lineStyle: { color: "#3b82f6" }, areaStyle: { color: "rgba(59,130,246,0.2)" } }, textStyle: { color: "#94a3b8" } }],
      series: [
        { name: "短期记忆", type: "line", data: sorted.map((d) => st[d] || 0), smooth: true, lineStyle: { color: "#3b82f6", width: 2 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(59,130,246,0.25)" }, { offset: 1, color: "rgba(59,130,246,0.02)" }] } }, itemStyle: { color: "#3b82f6" } },
        { name: "长期记忆", type: "line", data: sorted.map((d) => lt[d] || 0), smooth: true, lineStyle: { color: "#10b981", width: 2 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(16,185,129,0.25)" }, { offset: 1, color: "rgba(16,185,129,0.02)" }] } }, itemStyle: { color: "#10b981" } },
        { name: "预警经验", type: "line", data: sorted.map((d) => wt[d] || 0), smooth: true, lineStyle: { color: "#8b5cf6", width: 2 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(139,92,246,0.25)" }, { offset: 1, color: "rgba(139,92,246,0.02)" }] } }, itemStyle: { color: "#8b5cf6" } },
      ],
    };
  }, [memStats]);

  const radarOption = useMemo(() => {
    const st = memStats?.short_term || {};
    const lt = memStats?.long_term || {};
    const we = memStats?.warning_experiences || {};
    const maxVal = Math.max(st.total || 1, lt.total || 1, we.total || 1, 1);
    return {
      backgroundColor: "transparent",
      tooltip: {},
      legend: { data: ["短期记忆", "长期记忆", "预警经验"], bottom: 0, textStyle: { color: "#94a3b8", fontSize: 10 } },
      radar: {
        center: ["50%", "45%"],
        radius: "60%",
        indicator: [
          { name: "总量规模", max: maxVal },
          { name: "分类多样性", max: 10 },
          { name: "企业覆盖", max: Math.max(Object.keys(st.by_enterprise || {}).length || 1, Object.keys(lt.by_enterprise || {}).length || 1, 1) },
          { name: "P0紧急度", max: Math.max(st.by_priority?.P0 || 1, lt.by_priority?.P0 || 1, 1) },
          { name: "时间跨度(天)", max: Math.max(Object.keys(st.timeline || {}).length || 1, Object.keys(lt.timeline || {}).length || 1, Object.keys(we.timeline || {}).length || 1, 1) },
        ],
        axisName: { color: "#94a3b8", fontSize: 10 },
        splitArea: { areaStyle: { color: ["rgba(59,130,246,0.02)", "rgba(59,130,246,0.02)"] } },
        splitLine: { lineStyle: { color: "#1e293b" } },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [{
        type: "radar",
        data: [
          { value: [st.total || 0, Object.keys(st.by_category || {}).length, Object.keys(st.by_enterprise || {}).length, st.by_priority?.P0 || 0, Object.keys(st.timeline || {}).length], name: "短期记忆", lineStyle: { color: "#3b82f6", width: 2 }, areaStyle: { color: "rgba(59,130,246,0.15)" }, itemStyle: { color: "#3b82f6" } },
          { value: [lt.total || 0, Object.keys(lt.by_category || {}).length, Object.keys(lt.by_enterprise || {}).length, lt.by_priority?.P0 || 0, Object.keys(lt.timeline || {}).length], name: "长期记忆", lineStyle: { color: "#10b981", width: 2 }, areaStyle: { color: "rgba(16,185,129,0.15)" }, itemStyle: { color: "#10b981" } },
          { value: [we.total || 0, Object.keys(we.by_scenario || {}).length, 0, we.by_level?.["红"] || 0, Object.keys(we.timeline || {}).length], name: "预警经验", lineStyle: { color: "#8b5cf6", width: 2 }, areaStyle: { color: "rgba(139,92,246,0.15)" }, itemStyle: { color: "#8b5cf6" } },
        ],
      }],
    };
  }, [memStats]);

  const sunburstOption = useMemo(() => {
    const stCat = memStats?.short_term?.by_category || {};
    const ltCat = memStats?.long_term?.by_category || {};
    const weLvl = memStats?.warning_experiences?.by_level || {};
    const data: any[] = [];
    const stChildren = Object.entries(stCat).filter(([, v]) => (v as number) > 0).map(([k, v]) => ({ name: CAT_LABELS[k] || k, value: v as number, itemStyle: { color: CAT_COLORS[k] || "#64748b" } }));
    const ltChildren = Object.entries(ltCat).filter(([, v]) => (v as number) > 0).map(([k, v]) => ({ name: CAT_LABELS[k] || k, value: v as number, itemStyle: { color: CAT_COLORS[k] || "#64748b" } }));
    const weChildren = Object.entries(weLvl).filter(([, v]) => (v as number) > 0).map(([k, v]) => ({ name: `${k}级预警`, value: v as number, itemStyle: { color: LEVEL_COLORS[k] || "#64748b" } }));
    if (stChildren.length) data.push({ name: "短期记忆", itemStyle: { color: "#3b82f6" }, children: stChildren });
    if (ltChildren.length) data.push({ name: "长期记忆", itemStyle: { color: "#10b981" }, children: ltChildren });
    if (weChildren.length) data.push({ name: "预警经验", itemStyle: { color: "#8b5cf6" }, children: weChildren });
    if (!data.length) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent",
      tooltip: { formatter: (p: any) => `${p.name}: ${p.value}条` },
      series: [{ type: "sunburst", data, radius: ["15%", "85%"], label: { color: "#e5e7eb", fontSize: 11, fontWeight: 600 }, itemStyle: { borderColor: "#0f172a", borderWidth: 2 }, emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.5)" } } }],
    };
  }, [memStats]);

  const gaugeOption = useMemo(() => {
    const p0Total = (memStats?.short_term?.by_priority?.P0 || 0) + (memStats?.long_term?.by_priority?.P0 || 0);
    const redWarnings = memStats?.warning_experiences?.by_level?.["红"] || 0;
    return {
      backgroundColor: "transparent",
      series: [
        { type: "gauge", center: ["25%", "55%"], radius: "75%", min: 0, max: Math.max(grandTotal, 1), splitNumber: 5, axisLine: { lineStyle: { width: 8, color: [[0.3, "#10b981"], [0.6, "#f59e0b"], [1, "#ef4444"]] } }, pointer: { length: "60%", width: 4, itemStyle: { color: "#94a3b8" } }, detail: { formatter: "{value}", color: "#f1f5f9", fontSize: 18, fontWeight: 800, offsetCenter: [0, "70%"] }, title: { offsetCenter: [0, "90%"], color: "#94a3b8", fontSize: 10 }, data: [{ value: grandTotal, name: "总记忆量" }] },
        { type: "gauge", center: ["75%", "55%"], radius: "75%", min: 0, max: Math.max(p0Total + redWarnings, 1), splitNumber: 5, axisLine: { lineStyle: { width: 8, color: [[0.3, "#3b82f6"], [0.6, "#f97316"], [1, "#ef4444"]] } }, pointer: { length: "60%", width: 4, itemStyle: { color: "#94a3b8" } }, detail: { formatter: "{value}", color: "#f1f5f9", fontSize: 18, fontWeight: 800, offsetCenter: [0, "70%"] }, title: { offsetCenter: [0, "90%"], color: "#94a3b8", fontSize: 10 }, data: [{ value: p0Total + redWarnings, name: "紧急事项" }] },
      ],
    };
  }, [memStats, grandTotal]);

  const stackedBarOption = useMemo(() => {
    const stCat = memStats?.short_term?.by_category || {};
    const ltCat = memStats?.long_term?.by_category || {};
    const allCats = new Set([...Object.keys(stCat), ...Object.keys(ltCat)]);
    const sortedCats = [...allCats].sort();
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      legend: { data: ["短期记忆", "长期记忆"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 60, right: 20, top: 40, bottom: 40 },
      xAxis: { type: "category" as const, data: sortedCats.map((c) => CAT_LABELS[c] || c), axisLabel: { color: "#94a3b8", fontSize: 10, rotate: 20 } },
      yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [
        { name: "短期记忆", type: "bar", stack: "total", data: sortedCats.map((c) => stCat[c] || 0), itemStyle: { color: "#3b82f6", borderRadius: 0 }, barWidth: "50%" },
        { name: "长期记忆", type: "bar", stack: "total", data: sortedCats.map((c) => ltCat[c] || 0), itemStyle: { color: "#10b981", borderRadius: [4, 4, 0, 0] } },
      ],
    };
  }, [memStats]);

  const priorityCompareOption = useMemo(() => {
    const stPrio = memStats?.short_term?.by_priority || {};
    const ltPrio = memStats?.long_term?.by_priority || {};
    const prios = ["P0", "P1", "P2", "P3"];
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      legend: { data: ["短期记忆", "长期记忆"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category" as const, data: prios, axisLabel: { color: "#94a3b8", fontSize: 11 } },
      yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [
        { name: "短期记忆", type: "bar", data: prios.map((p) => ({ value: stPrio[p] || 0, itemStyle: { color: PRIO_COLORS[p] + "aa" } })), barWidth: "30%", barGap: "10%" },
        { name: "长期记忆", type: "bar", data: prios.map((p) => ({ value: ltPrio[p] || 0, itemStyle: { color: PRIO_COLORS[p] } })), barWidth: "30%" },
      ],
    };
  }, [memStats]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📊 记忆系统总览仪表盘</div>
          <button className="scada-btn secondary" type="button" onClick={loadStats} disabled={loading}>🔄 刷新</button>
        </div>
      </div>

      {memStats && (
        <>
          <div className="row cols-4" style={{ marginBottom: 14 }}>
            <StatCard value={grandTotal} label="记忆总量" color="#f1f5f9" icon="📚" />
            <StatCard value={shortTotal} label="短期记忆" color="#3b82f6" icon="🧠" />
            <StatCard value={longTotal} label="长期记忆" color="#10b981" icon="💾" />
            <StatCard value={weTotal} label="预警经验" color="#8b5cf6" icon="⚡" />
          </div>

          <div className="row cols-4" style={{ marginBottom: 14 }}>
            <StatCard value={memStats.pending_approvals ?? 0} label="待审批" color="#f59e0b" icon="📋" />
            <StatCard value={memStats.iteration_count ?? 0} label="迭代次数" color="#06b6d4" icon="🔄" />
            <StatCard value={memStats.audit_log_count ?? 0} label="审计日志" color="#64748b" icon="🔍" />
            <StatCard value={memStats.warning_experiences?.financial_total ?? 0} label="财务影响(万元)" color="#ef4444" icon="💰" />
          </div>

          <div className="scada-card" style={{ marginBottom: 14 }}>
            <div className="risk-report-title" style={{ marginBottom: 10 }}>📈 三模块时间趋势对比（支持拖拽缩放）</div>
            <ReactECharts option={combinedTimelineOption} style={{ height: 350 }} />
          </div>

          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>🎯 多维度雷达对比</div>
              <ReactECharts option={radarOption} style={{ height: 350 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>🌐 记忆结构旭日图</div>
              <ReactECharts option={sunburstOption} style={{ height: 350 }} />
            </div>
          </div>

          <div className="scada-card" style={{ marginBottom: 14 }}>
            <div className="risk-report-title" style={{ marginBottom: 10 }}>⏱️ 系统状态仪表盘</div>
            <ReactECharts option={gaugeOption} style={{ height: 250 }} />
          </div>

          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📊 三模块分类对比（堆叠柱状图）</div>
              <ReactECharts option={stackedBarOption} style={{ height: 300 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📈 优先级分布对比</div>
              <ReactECharts option={priorityCompareOption} style={{ height: 300 }} />
            </div>
          </div>

          <div className="row cols-3" style={{ marginBottom: 14 }}>
            <div className="scada-card" style={{ padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#3b82f6", marginBottom: 10 }}>🧠 短期记忆分类</div>
              {Object.entries(memStats.short_term?.by_category || {}).sort(([, a], [, b]) => (b as number) - (a as number)).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: "#cbd5e1" }}>{CAT_LABELS[k] || k}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: CAT_COLORS[k] || "#94a3b8" }}>{v as number}</span>
                </div>
              ))}
            </div>
            <div className="scada-card" style={{ padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#10b981", marginBottom: 10 }}>💾 长期记忆分类</div>
              {Object.entries(memStats.long_term?.by_category || {}).sort(([, a], [, b]) => (b as number) - (a as number)).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: "#cbd5e1" }}>{CAT_LABELS[k] || k}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: CAT_COLORS[k] || "#94a3b8" }}>{v as number}</span>
                </div>
              ))}
            </div>
            <div className="scada-card" style={{ padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#8b5cf6", marginBottom: 10 }}>⚡ 预警等级分布</div>
              {Object.entries(memStats.warning_experiences?.by_level || {}).sort(([, a], [, b]) => (b as number) - (a as number)).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: "#cbd5e1" }}>{k}级预警</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: LEVEL_COLORS[k] || "#94a3b8" }}>{v as number}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {!memStats && !loading && (
        <div className="scada-card"><div className="empty-state"><div className="empty-state-icon">📊</div><div>点击刷新加载统计数据</div></div></div>
      )}
    </div>
  );
}

function DataManagementSection() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [stats, setStats] = useState<any>(null);
  const [memoryStats, setMemoryStats] = useState<any>(null);

  const importFromNewData = useCallback(async () => {
    setLoading(true);
    setStatus("正在扫描并导入 datasets/raw/public 目录...");
    try {
      const result = await importEnterpriseData("folder");
      if (result?.success) {
        setStatus(`✅ 导入完成：${result.rows} 行数据`);
        refreshStats();
      } else {
        setStatus(`❌ 导入失败: ${result?.message || "未知错误"}`);
      }
    } catch (e) {
      setStatus(`❌ 导入失败: ${(e as Error).message}`);
    }
    setLoading(false);
  }, []);

  const refreshStats = useCallback(async () => {
    const [summary, memStats] = await Promise.all([fetchEnterpriseDataSummary(), fetchMemoryStats()]);
    setStats(summary);
    setMemoryStats(memStats);
  }, []);

  useEffect(() => { refreshStats(); }, [refreshStats]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📊 数据实时更新流式清洗 Pipeline</div>
          <div style={{ display: "flex", gap: 8 }}>
            <span className="tag tag-emerald">数据表: {stats?.table_count ?? 0}</span>
            <span className="tag tag-blue">企业数: {stats?.enterprise_count ?? 0}</span>
            <span className="tag tag-violet">长期记忆: {memoryStats?.long_term.total ?? 0}</span>
            <span className="tag tag-orange">短期记忆: {memoryStats?.short_term.total ?? 0}</span>
            <span className="tag" style={{ background: "rgba(139,92,246,0.15)", color: "#8b5cf6" }}>预警经验: {memoryStats?.warning_experiences?.total ?? 0}</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <button className="scada-btn" type="button" onClick={importFromNewData} disabled={loading}>
            {loading ? "导入中..." : "📁 从 datasets/raw/public 导入Excel数据"}
          </button>
          <button className="scada-btn secondary" type="button" onClick={refreshStats}>🔄 刷新统计</button>
        </div>
        {status && <div className={`alert ${status.includes("✅") ? "success" : status.includes("❌") ? "error" : "info"}`} style={{ marginTop: 10 }}>{status}</div>}
      </div>

      {stats && (
        <div className="row cols-4" style={{ marginBottom: 14 }}>
          {[
            { v: stats.total_entries, l: "记忆条目", c: "#10b981" },
            { v: stats.table_count, l: "数据表", c: "#3b82f6" },
            { v: stats.enterprise_count, l: "企业数量", c: "#f59e0b" },
            { v: memoryStats?.warning_experiences?.total ?? 0, l: "预警经验", c: "#8b5cf6" },
          ].map((item) => (
            <div key={item.l} className="scada-card" style={{ textAlign: "center", padding: 16 }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: item.c, fontFamily: "JetBrains Mono" }}>{item.v}</div>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4 }}>{item.l}</div>
            </div>
          ))}
        </div>
      )}

      {stats?.sources?.length > 0 && (
        <div className="scada-card">
          <div className="risk-report-title" style={{ marginBottom: 10 }}>📁 已导入数据源</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {stats.sources.map((src: string, i: number) => (
              <span key={i} className="tag tag-cyan" style={{ fontSize: 11 }}>{src}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RiskVisualizationSection() {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<EnterpriseRiskResult[]>([]);
  const [message, setMessage] = useState("");
  const [selectedEnterprise, setSelectedEnterprise] = useState<string | null>(null);
  const [riskHistory, setRiskHistory] = useState<any>(null);

  const runBatchAssessment = useCallback(async () => {
    setLoading(true);
    setMessage("正在执行批量风险评估...");
    try {
      const resp = await batchRiskAssessment();
      if (resp?.success && resp.results) {
        setResults(resp.results);
        setMessage(`✅ 完成 ${resp.results.length} 家企业风险评估，预警经验已自动生成`);
      } else {
        setMessage(`❌ 评估失败: ${resp?.message || "未知错误"}`);
      }
    } catch (e) {
      setMessage(`❌ 评估失败: ${(e as Error).message}`);
    }
    setLoading(false);
  }, []);

  const viewEnterpriseHistory = useCallback(async (eid: string) => {
    setSelectedEnterprise(eid);
    const hist = await fetchEnterpriseRiskHistory(eid);
    setRiskHistory(hist);
  }, []);

  const levelDistribution = useMemo(() => {
    const dist: Record<string, number> = { 红: 0, 橙: 0, 黄: 0, 蓝: 0 };
    results.forEach((r) => { dist[r.risk_level] = (dist[r.risk_level] || 0) + 1; });
    return dist;
  }, [results]);

  const pieOption = useMemo(() => {
    const data = Object.entries(levelDistribution).filter(([, v]) => v > 0).map(([k, v]) => ({ name: `${k}级`, value: v, itemStyle: { color: LEVEL_COLORS[k] } }));
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "item" as const },
      legend: { bottom: 0, textStyle: { color: "#94a3b8", fontSize: 11 } },
      series: [{ type: "pie", radius: ["40%", "70%"], center: ["50%", "45%"], data, label: { color: "#e5e7eb", fontSize: 12, fontWeight: 600 } }],
    };
  }, [levelDistribution]);

  const trendOption = useMemo(() => {
    const categories = results.slice(0, 20).map((r) => r.enterprise_name.slice(0, 6));
    const scores = results.slice(0, 20).map((r) => r.risk_score);
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      grid: { left: 50, right: 20, top: 30, bottom: 40 },
      xAxis: { type: "category" as const, data: categories, axisLabel: { color: "#94a3b8", fontSize: 10, rotate: 30 } },
      yAxis: { type: "value" as const, min: 0, max: 1, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [{
        type: "line" as const, data: scores, smooth: true,
        lineStyle: { color: "#3b82f6", width: 3 },
        areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(59,130,246,0.3)" }, { offset: 1, color: "rgba(59,130,246,0.05)" }] } },
        itemStyle: { color: "#3b82f6" },
        markLine: { data: [{ yAxis: 0.8, lineStyle: { color: "#ef4444", type: "dashed" }, label: { formatter: "红级阈值", color: "#ef4444" } }, { yAxis: 0.6, lineStyle: { color: "#f97316", type: "dashed" }, label: { formatter: "橙级阈值", color: "#f97316" } }] },
      }],
    };
  }, [results]);

  const heatmapOption = useMemo(() => {
    const topResults = results.slice(0, 15);
    const categories = topResults.map((r) => r.enterprise_name.slice(0, 8));
    const indicators = ["可燃气体", "通风系统", "消防设施", "安全管理"];
    const data: number[][] = [];
    topResults.forEach((r, i) => { r.key_factors.forEach((kf, j) => { data.push([j, i, kf.value]); }); });
    return {
      backgroundColor: "transparent",
      tooltip: { position: "top" as const },
      grid: { left: 80, right: 30, top: 10, bottom: 60 },
      xAxis: { type: "category" as const, data: indicators, axisLabel: { color: "#94a3b8" } },
      yAxis: { type: "category" as const, data: categories, axisLabel: { color: "#94a3b8", fontSize: 10 } },
      visualMap: { min: 0, max: 1, show: false, inRange: { color: ["#10b981", "#f59e0b", "#ef4444"] } },
      series: [{ type: "heatmap" as const, data, label: { show: true, color: "#fff", fontSize: 10 }, itemStyle: { borderColor: "#0f172a", borderWidth: 1 } }],
    };
  }, [results]);

  const historyChartOption = useMemo(() => {
    if (!riskHistory?.history?.length) return null;
    const times = riskHistory.history.map((h: any) => h.time.slice(5, 16));
    const scores = riskHistory.history.map((h: any) => h.risk_score);
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      grid: { left: 50, right: 20, top: 30, bottom: 30 },
      xAxis: { type: "category" as const, data: times, axisLabel: { color: "#94a3b8", fontSize: 10 } },
      yAxis: { type: "value" as const, min: 0, max: 1, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [{
        type: "line" as const, data: scores, smooth: true,
        lineStyle: { color: "#8b5cf6", width: 3 },
        areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(139,92,246,0.3)" }, { offset: 1, color: "rgba(139,92,246,0.05)" }] } },
        itemStyle: { color: "#8b5cf6" },
      }],
    };
  }, [riskHistory]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">🎯 批量风险评估与预警经验生成</div>
          <button className="scada-btn" type="button" onClick={runBatchAssessment} disabled={loading}>
            {loading ? "评估中..." : "🚀 执行批量风险评估"}
          </button>
        </div>
        {message && <div className={`alert ${message.includes("✅") ? "success" : message.includes("❌") ? "error" : "info"}`} style={{ marginTop: 10 }}>{message}</div>}
      </div>

      {results.length === 0 ? (
        <div className="scada-card"><div className="empty-state"><div className="empty-state-icon">🎯</div><div>点击"执行批量风险评估"开始风险分析</div></div></div>
      ) : (
        <>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📊 风险等级分布</div>
              <ReactECharts option={pieOption} style={{ height: 280 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📈 风险评分趋势</div>
              <ReactECharts option={trendOption} style={{ height: 280 }} />
            </div>
          </div>

          <div className="scada-card" style={{ marginBottom: 14 }}>
            <div className="risk-report-title" style={{ marginBottom: 10 }}>🔥 企业风险热力图</div>
            <ReactECharts option={heatmapOption} style={{ height: 400 }} />
          </div>

          {selectedEnterprise && historyChartOption && (
            <div className="scada-card" style={{ marginBottom: 14 }}>
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📈 企业风险历史 - {selectedEnterprise}</div>
              <ReactECharts option={historyChartOption} style={{ height: 250 }} />
            </div>
          )}

          <div className="scada-card">
            <div className="risk-report-title" style={{ marginBottom: 10 }}>📋 详细评估结果</div>
            <table className="scada-table">
              <thead>
                <tr><th>企业ID</th><th>企业名称</th><th>场景</th><th>风险评分</th><th>风险等级</th><th>评估时间</th><th>预警经验</th><th>历史</th></tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.enterprise_id} className={r.risk_level === "红" ? "risk-score-table-row-red" : r.risk_level === "橙" ? "risk-score-table-row-orange" : r.risk_level === "黄" ? "risk-score-table-row-yellow" : ""}>
                    <td className="font-mono" style={{ fontSize: 11 }}>{r.enterprise_id}</td>
                    <td style={{ fontWeight: 600 }}>{r.enterprise_name}</td>
                    <td><span className="tag tag-cyan" style={{ fontSize: 10 }}>{r.scenario}</span></td>
                    <td className="font-mono" style={{ fontWeight: 700, color: LEVEL_COLORS[r.risk_level] }}>{r.risk_score.toFixed(4)}</td>
                    <td><span className="tag" style={{ background: LEVEL_BG[r.risk_level], color: LEVEL_COLORS[r.risk_level], fontWeight: 700 }}>{r.risk_level}级</span></td>
                    <td style={{ fontSize: 11, color: "#94a3b8" }}>{r.assessment_time}</td>
                    <td>{r.inference_stored ? <span style={{ color: "#10b981" }}>✅ 已生成</span> : <span style={{ color: "#64748b" }}>—</span>}</td>
                    <td><button className="scada-btn secondary" style={{ fontSize: 10, padding: "2px 8px" }} type="button" onClick={() => viewEnterpriseHistory(r.enterprise_id)}>📈</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function ExcelImportSection() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [results, setResults] = useState<EnterpriseRiskResult[]>([]);
  const predictFileRef = useRef<HTMLInputElement>(null);
  const memoryFileRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setStatus(`正在导入 ${file.name} 并执行预测分析...`);
    try {
      const result = await assessEnterpriseFile(file);
      if (result?.success && result.results) {
        setResults(result.results);
        setStatus(`✅ 完成 ${result.total_rows} 条数据预测分析，预警经验已自动生成`);
      } else {
        setStatus(`❌ 预测分析失败: ${result?.message || "未知错误"}`);
      }
    } catch (err) {
      setStatus(`❌ 预测分析失败: ${(err as Error).message}`);
    }
    setLoading(false);
    if (predictFileRef.current) predictFileRef.current.value = "";
  }, []);

  const handleImportToMemory = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setStatus(`正在将 ${file.name} 导入长期记忆库...`);
    try {
      const result = await importExcelFile(file);
      if (result?.success) {
        setStatus(`✅ ${file.name} 导入成功：${result.rows}行 × ${result.columns}列`);
      } else {
        setStatus(`❌ 导入失败: ${result?.message || "未知错误"}`);
      }
    } catch (err) {
      setStatus(`❌ 导入失败: ${(err as Error).message}`);
    }
    setLoading(false);
    if (memoryFileRef.current) memoryFileRef.current.value = "";
  }, []);

  const handleExport = useCallback(async (memoryType: string, format: string) => {
    const blob = await exportMemoryData({ memory_type: memoryType, format });
    if (!blob) { setStatus("❌ 导出失败"); return; }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${memoryType}_export.${format}`;
    a.click();
    URL.revokeObjectURL(url);
    setStatus(`✅ 导出成功`);
  }, []);

  const levelDistribution = useMemo(() => {
    const dist: Record<string, number> = { 红: 0, 橙: 0, 黄: 0, 蓝: 0 };
    results.forEach((r) => { dist[r.risk_level] = (dist[r.risk_level] || 0) + 1; });
    return dist;
  }, [results]);

  const pieOption = useMemo(() => {
    const data = Object.entries(levelDistribution).filter(([, v]) => v > 0).map(([k, v]) => ({ name: `${k}级`, value: v, itemStyle: { color: LEVEL_COLORS[k] } }));
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "item" as const },
      series: [{ type: "pie", radius: ["30%", "60%"], data, label: { color: "#94a3b8", fontSize: 11 } }],
    };
  }, [levelDistribution]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📥 Excel文件导入与预测分析</div>
        </div>
        <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
          <label className="scada-btn" style={{ cursor: "pointer" }}>
            🔍 选择文件进行预测分析
            <input ref={predictFileRef} type="file" accept=".xlsx,.xls,.csv" style={{ display: "none" }} onChange={handleFileUpload} disabled={loading} />
          </label>
          <label className="scada-btn secondary" style={{ cursor: "pointer" }}>
            💾 导入到长期记忆库
            <input ref={memoryFileRef} type="file" accept=".xlsx,.xls,.csv" style={{ display: "none" }} onChange={handleImportToMemory} disabled={loading} />
          </label>
          <button className="scada-btn secondary" type="button" onClick={() => handleExport("long", "xlsx")}>📤 导出长期记忆</button>
          <button className="scada-btn secondary" type="button" onClick={() => handleExport("short", "csv")}>📤 导出短期记忆</button>
        </div>
        {status && <div className={`alert ${status.includes("✅") ? "success" : status.includes("❌") ? "error" : "info"}`} style={{ marginTop: 10 }}>{status}</div>}
      </div>

      {results.length > 0 && (
        <>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📊 风险等级分布</div>
              <ReactECharts option={pieOption} style={{ height: 250 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📋 预测结果摘要</div>
              <div style={{ fontSize: 13, lineHeight: 2 }}>
                <div>总企业数: <b style={{ color: "#f1f5f9" }}>{results.length}</b></div>
                <div style={{ color: "#ef4444" }}>红色预警: <b>{levelDistribution["红"]}</b> 家</div>
                <div style={{ color: "#f97316" }}>橙色预警: <b>{levelDistribution["橙"]}</b> 家</div>
                <div style={{ color: "#eab308" }}>黄色预警: <b>{levelDistribution["黄"]}</b> 家</div>
                <div style={{ color: "#3b82f6" }}>蓝色预警: <b>{levelDistribution["蓝"]}</b> 家</div>
              </div>
            </div>
          </div>
          <div className="scada-card">
            <div className="risk-report-title" style={{ marginBottom: 10 }}>📋 详细预测结果</div>
            <table className="scada-table">
              <thead><tr><th>企业名称</th><th>风险评分</th><th>风险等级</th><th>场景</th><th>关键指标</th></tr></thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} className={r.risk_level === "红" ? "risk-score-table-row-red" : r.risk_level === "橙" ? "risk-score-table-row-orange" : ""}>
                    <td style={{ fontWeight: 600 }}>{r.enterprise_name}</td>
                    <td className="font-mono" style={{ fontWeight: 700, color: LEVEL_COLORS[r.risk_level] }}>{r.risk_score.toFixed(4)}</td>
                    <td><span className="tag" style={{ background: LEVEL_BG[r.risk_level], color: LEVEL_COLORS[r.risk_level], fontWeight: 700 }}>{r.risk_level}级</span></td>
                    <td><span className="tag tag-cyan" style={{ fontSize: 10 }}>{r.scenario}</span></td>
                    <td>{r.key_factors.map((f) => <span key={f.name} className="tag" style={{ fontSize: 10, background: "rgba(100,116,139,0.15)", color: "#cbd5e1", margin: 1 }}>{f.name}:{f.value.toFixed(2)}</span>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function WarningExperienceSection() {
  const [experiences, setExperiences] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterLevel, setFilterLevel] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [memStats, setMemStats] = useState<any>(null);
  const [showExport, setShowExport] = useState(false);
  const pageSize = 20;

  const loadExperiences = useCallback(async () => {
    setLoading(true);
    const [resp, stats] = await Promise.all([
      fetchWarningExperiences({ search: search || undefined, risk_level: filterLevel || undefined, limit: pageSize, offset: page * pageSize }),
      fetchMemoryStats(),
    ]);
    if (resp) { setExperiences(resp.items || []); setTotal(resp.total); }
    if (stats) setMemStats(stats);
    setLoading(false);
  }, [search, filterLevel, page]);

  useEffect(() => { loadExperiences(); }, [loadExperiences]);

  const levelDist = useMemo(() => {
    const d: Record<string, number> = { 红: 0, 橙: 0, 黄: 0, 蓝: 0 };
    experiences.forEach((e) => { d[e.risk_level] = (d[e.risk_level] || 0) + 1; });
    return d;
  }, [experiences]);

  const pieOption = useMemo(() => {
    const data = Object.entries(levelDist).filter(([, v]) => v > 0).map(([k, v]) => ({ name: `${k}级`, value: v, itemStyle: { color: LEVEL_COLORS[k] } }));
    if (!data.length) data.push({ name: "暂无", value: 1, itemStyle: { color: "#334155" } });
    return { backgroundColor: "transparent", tooltip: { trigger: "item" as const, formatter: "{b}: {c} ({d}%)" }, legend: { bottom: 0, textStyle: { color: "#94a3b8", fontSize: 10 } }, series: [{ type: "pie", radius: ["35%", "65%"], center: ["50%", "45%"], data, label: { color: "#94a3b8", fontSize: 11, formatter: "{b}\n{c}条" }, emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.5)" } } }] };
  }, [levelDist]);

  const weStatsTimelineOption = useMemo(() => {
    const tl = memStats?.warning_experiences?.timeline || {};
    const entries = Object.entries(tl).sort(([a], [b]) => a.localeCompare(b));
    if (!entries.length) return { backgroundColor: "transparent" };
    return { backgroundColor: "transparent", tooltip: { trigger: "axis" as const }, grid: { left: 50, right: 20, top: 20, bottom: 50 }, xAxis: { type: "category" as const, data: entries.map(([d]) => d.slice(5)), axisLabel: { color: "#94a3b8", fontSize: 10 } }, yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } }, dataZoom: [{ type: "inside", start: 0, end: 100 }, { type: "slider", start: 0, end: 100, height: 20, bottom: 5, borderColor: "#334155", backgroundColor: "#0f172a", dataBackground: { lineStyle: { color: "#334155" }, areaStyle: { color: "#1e293b" } }, selectedDataBackground: { lineStyle: { color: "#8b5cf6" }, areaStyle: { color: "rgba(139,92,246,0.2)" } }, textStyle: { color: "#94a3b8" } }], series: [{ type: "line" as const, data: entries.map(([, v]) => v), smooth: true, lineStyle: { color: "#8b5cf6", width: 3 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(139,92,246,0.3)" }, { offset: 1, color: "rgba(139,92,246,0.05)" }] } }, itemStyle: { color: "#8b5cf6" } }] };
  }, [memStats]);

  const scenarioBarOption = useMemo(() => {
    const bySc = memStats?.warning_experiences?.by_scenario || {};
    const top = Object.entries(bySc).sort(([, a], [, b]) => (b as number) - (a as number));
    if (!top.length) return { backgroundColor: "transparent" };
    const scenarioLabels: Record<string, string> = { chemical: "化工", metallurgy: "冶金", dust: "粉尘", mining: "矿山" };
    return { backgroundColor: "transparent", tooltip: { trigger: "axis" as const }, grid: { left: 60, right: 20, top: 20, bottom: 30 }, xAxis: { type: "category" as const, data: top.map(([k]) => scenarioLabels[k] || k), axisLabel: { color: "#94a3b8" } }, yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } }, series: [{ type: "bar" as const, data: top.map(([, v]) => ({ value: v as number, itemStyle: { color: { type: "linear", x: 0, y: 1, x2: 0, y2: 0, colorStops: [{ offset: 0, color: "#8b5cf6" + "88" }, { offset: 1, color: "#8b5cf6" }] }, borderRadius: [6, 6, 0, 0] } })), barWidth: "40%" }] };
  }, [memStats]);

  const financialGaugeOption = useMemo(() => {
    const ft = memStats?.warning_experiences?.financial_total ?? 0;
    const maxVal = Math.max(ft * 1.5, 100);
    return {
      backgroundColor: "transparent",
      series: [{
        type: "gauge", center: ["50%", "55%"], radius: "80%",
        min: 0, max: maxVal, splitNumber: 5,
        axisLine: { lineStyle: { width: 10, color: [[0.3, "#10b981"], [0.6, "#f59e0b"], [1, "#ef4444"]] } },
        pointer: { length: "60%", width: 5, itemStyle: { color: "#94a3b8" } },
        axisTick: { distance: -8, length: 6, lineStyle: { color: "#475569", width: 1 } },
        splitLine: { distance: -10, length: 12, lineStyle: { color: "#64748b", width: 2 } },
        axisLabel: { color: "#94a3b8", fontSize: 9, distance: 16 },
        detail: { formatter: "{value}万元", color: "#f1f5f9", fontSize: 16, fontWeight: 800, offsetCenter: [0, "60%"] },
        title: { offsetCenter: [0, "80%"], color: "#94a3b8", fontSize: 10 },
        data: [{ value: ft, name: "财务影响" }],
      }],
    };
  }, [memStats]);

  const weLevelScenarioHeatmapOption = useMemo(() => {
    const byLevel = memStats?.warning_experiences?.by_level || {};
    const bySc = memStats?.warning_experiences?.by_scenario || {};
    const levels = Object.keys(byLevel);
    const scenarios = Object.keys(bySc);
    if (!levels.length || !scenarios.length) return { backgroundColor: "transparent" };
    const data: number[][] = [];
    const levelOrder = ["红", "橙", "黄", "蓝"].filter((l) => levels.includes(l));
    const scOrder = scenarios.slice(0, 6);
    const scenarioLabels: Record<string, string> = { chemical: "化工", metallurgy: "冶金", dust: "粉尘", mining: "矿山" };
    levelOrder.forEach((lv, li) => {
      scOrder.forEach((sc, si) => {
        const count = experiences.filter((e) => e.risk_level === lv && e.scenario === sc).length;
        data.push([si, li, count]);
      });
    });
    if (!data.some((d) => d[2] > 0)) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent",
      tooltip: { formatter: (p: any) => `${scenarioLabels[scOrder[p.data[0]]] || scOrder[p.data[0]]} × ${levelOrder[p.data[1]]}级: ${p.data[2]}条` },
      grid: { left: 60, right: 40, top: 10, bottom: 40 },
      xAxis: { type: "category" as const, data: scOrder.map((s) => scenarioLabels[s] || s), axisLabel: { color: "#94a3b8", fontSize: 10 } },
      yAxis: { type: "category" as const, data: levelOrder.map((l) => `${l}级`), axisLabel: { color: "#94a3b8", fontSize: 11 } },
      visualMap: { min: 0, max: Math.max(...data.map((d) => d[2]), 1), show: true, orient: "vertical" as const, right: 0, top: "center", textStyle: { color: "#94a3b8", fontSize: 10 }, inRange: { color: ["#1e293b", "#8b5cf6", "#a78bfa", "#c4b5fd"] } },
      series: [{ type: "heatmap" as const, data, label: { show: true, color: "#fff", fontSize: 11, formatter: (p: any) => p.data[2] || "" }, itemStyle: { borderColor: "#0f172a", borderWidth: 2 } }],
    };
  }, [memStats, experiences]);

  const financialTotal = memStats?.warning_experiences?.financial_total ?? 0;

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">⚡ 预警经验库</div>
          <div style={{ display: "flex", gap: 8 }}>
            <span className="tag tag-violet">总计: {total} 条</span>
            <button className="scada-btn secondary" style={{ fontSize: 11, padding: "2px 8px" }} type="button" onClick={() => setShowExport(!showExport)}>📤 导出</button>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input className="scada-input" placeholder="搜索预警经验..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} style={{ width: 200 }} />
          <select className="scada-input" value={filterLevel} onChange={(e) => { setFilterLevel(e.target.value); setPage(0); }} style={{ width: 120 }}>
            <option value="">全部等级</option><option value="红">红色</option><option value="橙">橙色</option><option value="黄">黄色</option><option value="蓝">蓝色</option>
          </select>
          <button className="scada-btn secondary" type="button" onClick={loadExperiences}>🔍 搜索</button>
        </div>
      </div>

      {showExport && <ExportDialog memoryType="warning_experience" onClose={() => setShowExport(false)} />}

      {memStats && (
        <>
          <div className="row cols-4" style={{ marginBottom: 14 }}>
            <StatCard value={memStats.warning_experiences?.total ?? 0} label="预警经验总数" color="#8b5cf6" icon="⚡" />
            <StatCard value={memStats.warning_experiences?.by_level?.["红"] ?? 0} label="红色预警" color="#ef4444" icon="🔴" />
            <StatCard value={Object.keys(memStats.warning_experiences?.by_scenario || {}).length} label="场景类型" color="#f59e0b" icon="🎯" />
            <StatCard value={financialTotal} label="财务影响(万元)" color="#10b981" icon="💰" />
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📊 风险等级分布</div><ReactECharts option={pieOption} style={{ height: 280 }} /></div>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📈 预警生成趋势</div><ReactECharts option={weStatsTimelineOption} style={{ height: 280 }} /></div>
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>💰 财务影响仪表盘</div><ReactECharts option={financialGaugeOption} style={{ height: 220 }} /></div>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>🎯 场景分布</div><ReactECharts option={scenarioBarOption} style={{ height: 220 }} /></div>
          </div>
          <div className="scada-card" style={{ marginBottom: 14 }}>
            <div className="risk-report-title" style={{ marginBottom: 10 }}>🔥 等级×场景关联热力图</div>
            <ReactECharts option={weLevelScenarioHeatmapOption} style={{ height: 250 }} />
          </div>
        </>
      )}

      <div className="scada-card">
        {experiences.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">⚡</div><div>暂无预警经验，执行风险评估后自动生成</div></div>
        ) : (
          experiences.map((exp) => (
            <div key={exp.id} style={{ border: "1px solid #1e293b", borderRadius: 8, marginBottom: 8, overflow: "hidden" }}>
              <div
                style={{ padding: "10px 14px", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", background: LEVEL_BG[exp.risk_level] || "rgba(100,116,139,0.08)" }}
                onClick={() => setExpandedId(expandedId === exp.id ? null : exp.id)}
              >
                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <span className="tag" style={{ background: LEVEL_BG[exp.risk_level], color: LEVEL_COLORS[exp.risk_level], fontWeight: 700 }}>{exp.risk_level}级</span>
                  <span style={{ fontWeight: 600, color: "#f1f5f9" }}>{exp.enterprise_name}</span>
                  <span style={{ fontSize: 11, color: "#94a3b8" }}>评分: {exp.risk_score?.toFixed(4)}</span>
                  <span style={{ fontSize: 11, color: "#94a3b8" }}>{exp.generated_at}</span>
                </div>
                <span style={{ color: "#64748b", fontSize: 12 }}>{expandedId === exp.id ? "▼" : "▶"}</span>
              </div>
              {expandedId === exp.id && (
                <div style={{ padding: 14, background: "rgba(15,23,42,0.5)" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                    <div><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>根本原因</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{exp.root_cause}</div></div>
                    <div><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>运营影响</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{exp.operational_impact}</div></div>
                    <div><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>财务影响</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{exp.financial_impact} 万元</div></div>
                    <div><div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>行业基准</div><div style={{ fontSize: 13, color: "#e5e7eb" }}>{exp.industry_benchmark}</div></div>
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>处置措施</div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {exp.actions_taken?.map((a: string, i: number) => (<span key={i} className="tag tag-cyan" style={{ fontSize: 11 }}>{a}</span>))}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>关键风险因素</div>
                    <table className="scada-table" style={{ fontSize: 12 }}>
                      <thead><tr><th>指标</th><th>数值</th><th>风险贡献</th></tr></thead>
                      <tbody>
                        {exp.key_factors_summary?.map((f: any, i: number) => (
                          <tr key={i}><td>{f.name}</td><td className="font-mono">{f.value?.toFixed(3)}</td><td><span className="tag" style={{ background: f.risk_contribution === "高" ? "rgba(239,68,68,0.15)" : f.risk_contribution === "中" ? "rgba(249,115,22,0.15)" : "rgba(59,130,246,0.15)", color: f.risk_contribution === "高" ? "#ef4444" : f.risk_contribution === "中" ? "#f97316" : "#3b82f6" }}>{f.risk_contribution}</span></td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ))
        )}
        {total > pageSize && (
          <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 12 }}>
            <button className="scada-btn secondary" type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button>
            <span style={{ color: "#94a3b8", lineHeight: "32px" }}>第 {page + 1} 页 / 共 {Math.ceil(total / pageSize)} 页</span>
            <button className="scada-btn secondary" type="button" disabled={(page + 1) * pageSize >= total} onClick={() => setPage(page + 1)}>下一页</button>
          </div>
        )}
      </div>
    </div>
  );
}

function MemoryDetailModal({ item, onClose }: { item: any; onClose: () => void }) {
  if (!item) return null;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onClose}>
      <div style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 12, padding: 24, maxWidth: 700, width: "90%", maxHeight: "80vh", overflow: "auto" }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#f1f5f9" }}>📋 记忆详情</div>
          <button className="scada-btn secondary" style={{ fontSize: 11, padding: "4px 10px" }} type="button" onClick={onClose}>✕ 关闭</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
          <div><span style={{ color: "#64748b", fontSize: 11 }}>ID: </span><span className="font-mono" style={{ color: "#94a3b8", fontSize: 11 }}>{item.id}</span></div>
          <div><span style={{ color: "#64748b", fontSize: 11 }}>优先级: </span><span className="tag" style={{ background: PRIO_BG[item.priority] || PRIO_BG.P2, color: PRIO_COLORS[item.priority] || PRIO_COLORS.P2, fontWeight: 700, fontSize: 10 }}>{item.priority}</span></div>
          <div><span style={{ color: "#64748b", fontSize: 11 }}>分类: </span><span className="tag tag-cyan" style={{ fontSize: 10 }}>{CAT_LABELS[item.category] || item.category}</span></div>
          <div><span style={{ color: "#64748b", fontSize: 11 }}>类型: </span><span style={{ color: "#cbd5e1", fontSize: 12 }}>{item.type === "short" ? "短期记忆" : "长期记忆"}</span></div>
          <div><span style={{ color: "#64748b", fontSize: 11 }}>企业ID: </span><span className="font-mono" style={{ color: "#94a3b8", fontSize: 11 }}>{item.enterprise_id || "—"}</span></div>
          <div><span style={{ color: "#64748b", fontSize: 11 }}>时间: </span><span style={{ color: "#94a3b8", fontSize: 11 }}>{item.time}</span></div>
          {item.data_source && <div><span style={{ color: "#64748b", fontSize: 11 }}>数据源: </span><span style={{ color: "#94a3b8", fontSize: 11 }}>{item.data_source}</span></div>}
          {item.verified !== undefined && <div><span style={{ color: "#64748b", fontSize: 11 }}>已验证: </span><span style={{ color: item.verified ? "#10b981" : "#ef4444", fontSize: 11 }}>{item.verified ? "✅ 是" : "❌ 否"}</span></div>}
        </div>
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: "#64748b", fontSize: 11, marginBottom: 6 }}>完整内容:</div>
          <div style={{ background: "rgba(30,41,59,0.5)", borderRadius: 8, padding: 12, color: "#e5e7eb", fontSize: 13, lineHeight: 1.7, maxHeight: 200, overflow: "auto", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{item.text}</div>
        </div>
        {item.tags?.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ color: "#64748b", fontSize: 11, marginBottom: 6 }}>标签:</div>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {item.tags.map((t: string, i: number) => <span key={i} className="tag" style={{ fontSize: 10, background: "rgba(100,116,139,0.15)", color: "#cbd5e1" }}>{t}</span>)}
            </div>
          </div>
        )}
        {item.row_data && (
          <div>
            <div style={{ color: "#64748b", fontSize: 11, marginBottom: 6 }}>行数据:</div>
            <div style={{ background: "rgba(30,41,59,0.5)", borderRadius: 8, padding: 12, maxHeight: 200, overflow: "auto" }}>
              {Object.entries(item.row_data).map(([k, v]) => (
                <div key={k} style={{ display: "flex", gap: 8, marginBottom: 4, fontSize: 12 }}>
                  <span style={{ color: "#64748b", minWidth: 100 }}>{k}:</span>
                  <span style={{ color: "#e5e7eb" }}>{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ShortTermMemorySection() {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterCat, setFilterCat] = useState("");
  const [page, setPage] = useState(0);
  const [memStats, setMemStats] = useState<any>(null);
  const [showExport, setShowExport] = useState(false);
  const [detailItem, setDetailItem] = useState<any>(null);
  const pageSize = 20;

  const loadData = useCallback(async () => {
    setLoading(true);
    const [resp, stats] = await Promise.all([
      queryShortTermMemoryPaginated({ search: search || undefined, category: filterCat || undefined, limit: pageSize, offset: page * pageSize }),
      fetchMemoryStats(),
    ]);
    if (resp) { setItems(resp.items || []); setTotal(resp.total); }
    if (stats) setMemStats(stats);
    setLoading(false);
  }, [search, filterCat, page]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleMigrate = useCallback(async (ids: string[]) => { await migrateToLongTerm(ids); loadData(); }, [loadData]);
  const handleDelete = useCallback(async (id: string) => { await deleteShortTermMemory(id); loadData(); }, [loadData]);

  const catPieOption = useMemo(() => {
    const byCat = memStats?.short_term?.by_category || {};
    const data = Object.entries(byCat).filter(([, v]) => (v as number) > 0).map(([k, v]) => ({ name: CAT_LABELS[k] || k, value: v as number, itemStyle: { color: CAT_COLORS[k] || "#64748b" } }));
    if (!data.length) data.push({ name: "暂无数据", value: 1, itemStyle: { color: "#334155" } });
    return { backgroundColor: "transparent", tooltip: { trigger: "item" as const, formatter: "{b}: {c} ({d}%)" }, legend: { bottom: 0, textStyle: { color: "#94a3b8", fontSize: 10 } }, series: [{ type: "pie", radius: ["35%", "65%"], center: ["50%", "45%"], data, label: { color: "#94a3b8", fontSize: 10, formatter: "{b}\n{c}条" }, emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.5)" } } }] };
  }, [memStats]);

  const prioBarOption = useMemo(() => {
    const byPrio = memStats?.short_term?.by_priority || {};
    const prios = ["P0", "P1", "P2", "P3"];
    return { backgroundColor: "transparent", tooltip: { trigger: "axis" as const }, grid: { left: 50, right: 20, top: 20, bottom: 30 }, xAxis: { type: "category" as const, data: prios, axisLabel: { color: "#94a3b8" } }, yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } }, series: [{ type: "bar" as const, data: prios.map((p) => ({ value: byPrio[p] || 0, itemStyle: { color: { type: "linear", x: 0, y: 1, x2: 0, y2: 0, colorStops: [{ offset: 0, color: PRIO_COLORS[p] + "88" }, { offset: 1, color: PRIO_COLORS[p] }] }, borderRadius: [6, 6, 0, 0] } })), barWidth: "40%" }] };
  }, [memStats]);

  const timelineOption = useMemo(() => {
    const tl = memStats?.short_term?.timeline || {};
    const entries = Object.entries(tl).sort(([a], [b]) => a.localeCompare(b));
    if (!entries.length) return { backgroundColor: "transparent" };
    return { backgroundColor: "transparent", tooltip: { trigger: "axis" as const }, grid: { left: 50, right: 20, top: 20, bottom: 50 }, xAxis: { type: "category" as const, data: entries.map(([d]) => d.slice(5)), axisLabel: { color: "#94a3b8", fontSize: 10 } }, yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } }, dataZoom: [{ type: "inside", start: 0, end: 100 }, { type: "slider", start: 0, end: 100, height: 20, bottom: 5, borderColor: "#334155", backgroundColor: "#0f172a", dataBackground: { lineStyle: { color: "#334155" }, areaStyle: { color: "#1e293b" } }, selectedDataBackground: { lineStyle: { color: "#3b82f6" }, areaStyle: { color: "rgba(59,130,246,0.2)" } }, textStyle: { color: "#94a3b8" } }], series: [{ type: "line" as const, data: entries.map(([, v]) => v), smooth: true, lineStyle: { color: "#3b82f6", width: 3 }, areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(59,130,246,0.3)" }, { offset: 1, color: "rgba(59,130,246,0.05)" }] } }, itemStyle: { color: "#3b82f6" } }] };
  }, [memStats]);

  const enterpriseBarOption = useMemo(() => {
    const byEnt = memStats?.short_term?.by_enterprise || {};
    const top = Object.entries(byEnt).sort(([, a], [, b]) => (b as number) - (a as number)).slice(0, 8);
    if (!top.length) return { backgroundColor: "transparent" };
    return { backgroundColor: "transparent", tooltip: { trigger: "axis" as const }, grid: { left: 80, right: 20, top: 20, bottom: 30 }, xAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } }, yAxis: { type: "category" as const, data: top.map(([k]) => k.slice(0, 10)), axisLabel: { color: "#94a3b8", fontSize: 10 } }, series: [{ type: "bar" as const, data: top.map(([, v]) => ({ value: v as number, itemStyle: { color: { type: "linear", x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: "#06b6d4" }, { offset: 1, color: "#22d3ee" }] }, borderRadius: [0, 6, 6, 0] } })), barWidth: "50%" }] };
  }, [memStats]);

  const heatmapOption = useMemo(() => {
    const byCat = memStats?.short_term?.by_category || {};
    const byPrio = memStats?.short_term?.by_priority || {};
    const cats = Object.keys(byCat);
    const prios = ["P0", "P1", "P2", "P3"].filter((p) => byPrio[p]);
    if (!cats.length || !prios.length) return { backgroundColor: "transparent" };
    const data: number[][] = [];
    cats.forEach((cat, ci) => { prios.forEach((prio, pi) => { const count = items.filter((i) => i.category === cat && i.priority === prio).length; data.push([pi, ci, count]); }); });
    return { backgroundColor: "transparent", tooltip: { formatter: (p: any) => `${CAT_LABELS[cats[p.data[1]]] || cats[p.data[1]]} × ${prios[p.data[0]]}: ${p.data[2]}条` }, grid: { left: 90, right: 40, top: 10, bottom: 40 }, xAxis: { type: "category" as const, data: prios, axisLabel: { color: "#94a3b8", fontSize: 11 } }, yAxis: { type: "category" as const, data: cats.map((c) => CAT_LABELS[c] || c), axisLabel: { color: "#94a3b8", fontSize: 10 } }, visualMap: { min: 0, max: Math.max(...data.map((d) => d[2]), 1), show: true, orient: "vertical" as const, right: 0, top: "center", textStyle: { color: "#94a3b8", fontSize: 10 }, inRange: { color: ["#1e293b", "#3b82f6", "#06b6d4"] } }, series: [{ type: "heatmap" as const, data, label: { show: true, color: "#fff", fontSize: 10, formatter: (p: any) => p.data[2] || "" }, itemStyle: { borderColor: "#0f172a", borderWidth: 2 } }] };
  }, [memStats, items]);

  const importanceGaugeOption = useMemo(() => {
    const total = memStats?.short_term?.total || 0;
    const p0 = memStats?.short_term?.by_priority?.P0 || 0;
    const p1 = memStats?.short_term?.by_priority?.P1 || 0;
    const importanceScore = total > 0 ? ((p0 * 100 + p1 * 60) / total) : 0;
    return {
      backgroundColor: "transparent",
      series: [{
        type: "gauge", center: ["50%", "55%"], radius: "80%",
        min: 0, max: 100, splitNumber: 5,
        axisLine: { lineStyle: { width: 10, color: [[0.25, "#10b981"], [0.5, "#f59e0b"], [0.75, "#f97316"], [1, "#ef4444"]] } },
        pointer: { length: "60%", width: 5, itemStyle: { color: "#94a3b8" } },
        axisTick: { distance: -8, length: 6, lineStyle: { color: "#475569", width: 1 } },
        splitLine: { distance: -10, length: 12, lineStyle: { color: "#64748b", width: 2 } },
        axisLabel: { color: "#94a3b8", fontSize: 9, distance: 16 },
        detail: { formatter: "{value}分", color: "#f1f5f9", fontSize: 16, fontWeight: 800, offsetCenter: [0, "60%"] },
        title: { offsetCenter: [0, "80%"], color: "#94a3b8", fontSize: 10 },
        data: [{ value: Math.round(importanceScore), name: "记忆重要度" }],
      }],
    };
  }, [memStats]);

  const associationScatterOption = useMemo(() => {
    const byCat = memStats?.short_term?.by_category || {};
    const byPrio = memStats?.short_term?.by_priority || {};
    const cats = Object.keys(byCat);
    if (!cats.length) return { backgroundColor: "transparent" };
    const scatterData = cats.map((cat, i) => {
      const count = byCat[cat] as number || 0;
      const p0Count = items.filter((item) => item.category === cat && item.priority === "P0").length;
      return [i, count, p0Count, CAT_LABELS[cat] || cat];
    });
    return {
      backgroundColor: "transparent",
      tooltip: { formatter: (p: any) => `${p.data[3]}: ${p.data[1]}条 (P0: ${p.data[2]}条)` },
      grid: { left: 50, right: 30, top: 30, bottom: 50 },
      xAxis: { type: "category" as const, data: cats.map((c) => CAT_LABELS[c] || c), axisLabel: { color: "#94a3b8", fontSize: 10, rotate: 20 } },
      yAxis: { type: "value" as const, name: "记忆数量", nameTextStyle: { color: "#94a3b8", fontSize: 10 }, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      visualMap: { min: 0, max: Math.max(...scatterData.map((d) => d[2] as number), 1), show: false, inRange: { color: ["#3b82f6", "#f59e0b", "#ef4444"] } },
      series: [{
        type: "scatter" as const, data: scatterData,
        symbolSize: (d: any[]) => Math.max(10, Number(d[1]) * 3),
        itemStyle: { borderColor: "#0f172a", borderWidth: 1 },
        label: { show: true, formatter: (p: any) => `${p.data[1]}条`, color: "#e5e7eb", fontSize: 10, position: "top" as const },
      }],
    };
  }, [memStats, items]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">🧠 短期记忆库</div>
          <div style={{ display: "flex", gap: 8 }}>
            <span className="tag tag-blue">总计: {total} 条</span>
            <button className="scada-btn secondary" style={{ fontSize: 11, padding: "2px 8px" }} type="button" onClick={() => handleMigrate(items.map((i) => i.id))}>⬆️ 全部迁移</button>
            <button className="scada-btn secondary" style={{ fontSize: 11, padding: "2px 8px" }} type="button" onClick={() => setShowExport(!showExport)}>📤 导出</button>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <input className="scada-input" placeholder="搜索..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} style={{ width: 200 }} />
          <select className="scada-input" value={filterCat} onChange={(e) => { setFilterCat(e.target.value); setPage(0); }} style={{ width: 140 }}>
            <option value="">全部分类</option>
            <option value="inference">推理过程</option><option value="warning">预警记录</option><option value="experience">预警经验</option><option value="context">上下文</option>
          </select>
          <button className="scada-btn secondary" type="button" onClick={loadData}>🔄 刷新</button>
        </div>
      </div>

      {showExport && <ExportDialog memoryType="short" onClose={() => setShowExport(false)} />}

      {memStats && (
        <>
          <div className="row cols-4" style={{ marginBottom: 14 }}>
            <StatCard value={memStats.short_term?.total ?? 0} label="短期记忆总数" color="#3b82f6" icon="🧠" />
            <StatCard value={memStats.short_term?.by_priority?.P0 ?? 0} label="P0 紧急" color="#ef4444" icon="🔴" />
            <StatCard value={Object.keys(memStats.short_term?.by_category || {}).length} label="分类数量" color="#10b981" icon="📂" />
            <StatCard value={Object.keys(memStats.short_term?.by_enterprise || {}).length} label="关联企业" color="#f59e0b" icon="🏢" />
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📊 分类分布</div><ReactECharts option={catPieOption} style={{ height: 280 }} /></div>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📈 优先级分布</div><ReactECharts option={prioBarOption} style={{ height: 280 }} /></div>
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>📈 入库时间趋势</div><ReactECharts option={timelineOption} style={{ height: 280 }} /></div>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>🏢 企业关联TOP8</div><ReactECharts option={enterpriseBarOption} style={{ height: 280 }} /></div>
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>⏱️ 记忆重要度评分</div><ReactECharts option={importanceGaugeOption} style={{ height: 220 }} /></div>
            <div className="scada-card"><div className="risk-report-title" style={{ marginBottom: 10 }}>🎯 分类关联强度散点图</div><ReactECharts option={associationScatterOption} style={{ height: 220 }} /></div>
          </div>
          <div className="scada-card" style={{ marginBottom: 14 }}>
            <div className="risk-report-title" style={{ marginBottom: 10 }}>🔥 分类×优先级关联热力图</div>
            <ReactECharts option={heatmapOption} style={{ height: Math.max(200, Object.keys(memStats.short_term?.by_category || {}).length * 40 + 80) }} />
          </div>
        </>
      )}

      <div className="scada-card">
        {items.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">🧠</div><div>短期记忆库为空</div></div>
        ) : (
          <table className="scada-table">
            <thead><tr><th>优先级</th><th>分类</th><th>内容</th><th>企业ID</th><th>时间</th><th>标签</th><th>操作</th></tr></thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td><span className="tag" style={{ background: PRIO_BG[item.priority] || PRIO_BG.P2, color: PRIO_COLORS[item.priority] || PRIO_COLORS.P2, fontWeight: 700, fontSize: 10 }}>{item.priority}</span></td>
                  <td><span className="tag tag-cyan" style={{ fontSize: 10 }}>{CAT_LABELS[item.category] || item.category}</span></td>
                  <td style={{ maxWidth: 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 12 }}>{item.text}</td>
                  <td className="font-mono" style={{ fontSize: 11 }}>{item.enterprise_id || "—"}</td>
                  <td style={{ fontSize: 11, color: "#94a3b8" }}>{item.time}</td>
                  <td>{(item.tags || []).slice(0, 2).map((t: string) => <span key={t} className="tag" style={{ fontSize: 9, background: "rgba(100,116,139,0.15)", color: "#94a3b8", margin: 1 }}>{t}</span>)}</td>
                  <td>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="scada-btn secondary" style={{ fontSize: 10, padding: "2px 6px" }} type="button" onClick={() => setDetailItem(item)}>📋 详情</button>
                      <button className="scada-btn secondary" style={{ fontSize: 10, padding: "2px 6px" }} type="button" onClick={() => handleMigrate([item.id])}>⬆️ 迁移</button>
                      <button className="scada-btn secondary" style={{ fontSize: 10, padding: "2px 6px", color: "#ef4444" }} type="button" onClick={() => handleDelete(item.id)}>🗑️</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {total > pageSize && (
          <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 12 }}>
            <button className="scada-btn secondary" type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button>
            <span style={{ color: "#94a3b8", lineHeight: "32px" }}>第 {page + 1} 页 / 共 {Math.ceil(total / pageSize)} 页</span>
            <button className="scada-btn secondary" type="button" disabled={(page + 1) * pageSize >= total} onClick={() => setPage(page + 1)}>下一页</button>
          </div>
        )}
      </div>
      {detailItem && <MemoryDetailModal item={detailItem} onClose={() => setDetailItem(null)} />}
    </div>
  );
}

function LongTermMemorySection() {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterCat, setFilterCat] = useState("");
  const [page, setPage] = useState(0);
  const [memStats, setMemStats] = useState<any>(null);
  const [showExport, setShowExport] = useState(false);
  const [detailItem, setDetailItem] = useState<any>(null);
  const pageSize = 20;

  const loadData = useCallback(async () => {
    setLoading(true);
    const [resp, stats] = await Promise.all([
      queryLongTermMemoryPaginated({
        search: search || undefined,
        category: filterCat || undefined,
        limit: pageSize,
        offset: page * pageSize,
      }),
      fetchMemoryStats(),
    ]);
    if (resp) { setItems(resp.items || []); setTotal(resp.total); }
    if (stats) setMemStats(stats);
    setLoading(false);
  }, [search, filterCat, page]);

  useEffect(() => { loadData(); }, [loadData]);

  const catPieOption = useMemo(() => {
    const byCat = memStats?.long_term?.by_category || {};
    const data = Object.entries(byCat).filter(([, v]) => (v as number) > 0).map(([k, v]) => ({
      name: CAT_LABELS[k] || k, value: v as number, itemStyle: { color: CAT_COLORS[k] || "#64748b" },
    }));
    if (!data.length) data.push({ name: "暂无数据", value: 1, itemStyle: { color: "#334155" } });
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "item" as const, formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { color: "#94a3b8", fontSize: 10 } },
      series: [{
        type: "pie", radius: ["35%", "65%"], center: ["50%", "45%"], data,
        label: { color: "#94a3b8", fontSize: 10, formatter: "{b}\n{c}条" },
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.5)" } },
      }],
    };
  }, [memStats]);

  const prioBarOption = useMemo(() => {
    const byPrio = memStats?.long_term?.by_priority || {};
    const prios = ["P0", "P1", "P2", "P3"];
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      grid: { left: 50, right: 20, top: 20, bottom: 30 },
      xAxis: { type: "category" as const, data: prios, axisLabel: { color: "#94a3b8" } },
      yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      series: [{
        type: "bar" as const,
        data: prios.map((p) => ({
          value: byPrio[p] || 0,
          itemStyle: { color: { type: "linear", x: 0, y: 1, x2: 0, y2: 0, colorStops: [{ offset: 0, color: PRIO_COLORS[p] + "88" }, { offset: 1, color: PRIO_COLORS[p] }] }, borderRadius: [6, 6, 0, 0] },
        })),
        barWidth: "40%",
      }],
    };
  }, [memStats]);

  const timelineOption = useMemo(() => {
    const tl = memStats?.long_term?.timeline || {};
    const entries = Object.entries(tl).sort(([a], [b]) => a.localeCompare(b));
    if (!entries.length) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      grid: { left: 50, right: 20, top: 20, bottom: 50 },
      xAxis: { type: "category" as const, data: entries.map(([d]) => d.slice(5)), axisLabel: { color: "#94a3b8", fontSize: 10 } },
      yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      dataZoom: [{ type: "inside", start: 0, end: 100 }, { type: "slider", start: 0, end: 100, height: 20, bottom: 5, borderColor: "#334155", backgroundColor: "#0f172a", dataBackground: { lineStyle: { color: "#334155" }, areaStyle: { color: "#1e293b" } }, selectedDataBackground: { lineStyle: { color: "#10b981" }, areaStyle: { color: "rgba(16,185,129,0.2)" } }, textStyle: { color: "#94a3b8" } }],
      series: [{
        type: "line" as const, data: entries.map(([, v]) => v), smooth: true,
        lineStyle: { color: "#10b981", width: 3 },
        areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(16,185,129,0.3)" }, { offset: 1, color: "rgba(16,185,129,0.05)" }] } },
        itemStyle: { color: "#10b981" },
      }],
    };
  }, [memStats]);

  const sourceBarOption = useMemo(() => {
    const bySource = memStats?.long_term?.by_source || {};
    const top = Object.entries(bySource).sort(([, a], [, b]) => (b as number) - (a as number)).slice(0, 10);
    if (!top.length) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      grid: { left: 100, right: 20, top: 20, bottom: 30 },
      xAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      yAxis: { type: "category" as const, data: top.map(([k]) => k.length > 15 ? k.slice(0, 15) + "..." : k), axisLabel: { color: "#94a3b8", fontSize: 10 } },
      series: [{
        type: "bar" as const,
        data: top.map(([, v]) => ({
          value: v as number,
          itemStyle: { color: { type: "linear", x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: "#10b981" }, { offset: 1, color: "#34d399" }] }, borderRadius: [0, 6, 6, 0] },
        })),
        barWidth: "50%",
      }],
    };
  }, [memStats]);

  const enterpriseBarOption = useMemo(() => {
    const byEnt = memStats?.long_term?.by_enterprise || {};
    const top = Object.entries(byEnt).sort(([, a], [, b]) => (b as number) - (a as number)).slice(0, 8);
    if (!top.length) return { backgroundColor: "transparent" };
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const },
      grid: { left: 80, right: 20, top: 20, bottom: 30 },
      xAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
      yAxis: { type: "category" as const, data: top.map(([k]) => k.slice(0, 10)), axisLabel: { color: "#94a3b8", fontSize: 10 } },
      series: [{
        type: "bar" as const,
        data: top.map(([, v]) => ({
          value: v as number,
          itemStyle: { color: { type: "linear", x: 0, y: 0, x2: 1, y2: 0, colorStops: [{ offset: 0, color: "#f59e0b" }, { offset: 1, color: "#fbbf24" }] }, borderRadius: [0, 6, 6, 0] },
        })),
        barWidth: "50%",
      }],
    };
  }, [memStats]);

  const heatmapOption = useMemo(() => {
    const byCat = memStats?.long_term?.by_category || {};
    const byPrio = memStats?.long_term?.by_priority || {};
    const cats = Object.keys(byCat);
    const prios = ["P0", "P1", "P2", "P3"].filter((p) => byPrio[p]);
    if (!cats.length || !prios.length) return { backgroundColor: "transparent" };
    const data: number[][] = [];
    cats.forEach((cat, ci) => {
      prios.forEach((prio, pi) => {
        const count = items.filter((i) => i.category === cat && i.priority === prio).length;
        data.push([pi, ci, count]);
      });
    });
    return {
      backgroundColor: "transparent",
      tooltip: { formatter: (p: any) => `${CAT_LABELS[cats[p.data[1]]] || cats[p.data[1]]} × ${prios[p.data[0]]}: ${p.data[2]}条` },
      grid: { left: 90, right: 40, top: 10, bottom: 40 },
      xAxis: { type: "category" as const, data: prios, axisLabel: { color: "#94a3b8", fontSize: 11 } },
      yAxis: { type: "category" as const, data: cats.map((c) => CAT_LABELS[c] || c), axisLabel: { color: "#94a3b8", fontSize: 10 } },
      visualMap: { min: 0, max: Math.max(...data.map((d) => d[2]), 1), show: true, orient: "vertical" as const, right: 0, top: "center", textStyle: { color: "#94a3b8", fontSize: 10 }, inRange: { color: ["#1e293b", "#10b981", "#f59e0b"] } },
      series: [{ type: "heatmap" as const, data, label: { show: true, color: "#fff", fontSize: 10, formatter: (p: any) => p.data[2] || "" }, itemStyle: { borderColor: "#0f172a", borderWidth: 2 } }],
    };
  }, [memStats, items]);

  const SOURCE_COLORS = ["#10b981", "#34d399", "#06b6d4", "#22d3ee", "#3b82f6", "#6366f1", "#8b5cf6", "#a78bfa", "#f59e0b", "#f97316", "#ef4444", "#ec4899"];

  const ltImportanceGaugeOption = useMemo(() => {
    const total = memStats?.long_term?.total || 0;
    const verified = memStats?.long_term?.verified_count || 0;
    const verifiedRatio = total > 0 ? Math.round((verified / total) * 100) : 0;
    return {
      backgroundColor: "transparent",
      series: [{
        type: "gauge", center: ["50%", "55%"], radius: "80%",
        min: 0, max: 100, splitNumber: 5,
        axisLine: { lineStyle: { width: 10, color: [[0.25, "#10b981"], [0.5, "#f59e0b"], [0.75, "#f97316"], [1, "#ef4444"]] } },
        pointer: { length: "60%", width: 5, itemStyle: { color: "#94a3b8" } },
        axisTick: { distance: -8, length: 6, lineStyle: { color: "#475569", width: 1 } },
        splitLine: { distance: -10, length: 12, lineStyle: { color: "#64748b", width: 2 } },
        axisLabel: { color: "#94a3b8", fontSize: 9, distance: 16 },
        detail: { formatter: "{value}%", color: "#f1f5f9", fontSize: 16, fontWeight: 800, offsetCenter: [0, "60%"] },
        title: { offsetCenter: [0, "80%"], color: "#94a3b8", fontSize: 10 },
        data: [{ value: verifiedRatio, name: "验证覆盖率" }],
      }],
    };
  }, [memStats]);

  const ltSourcePieOption = useMemo(() => {
    const bySource = memStats?.long_term?.by_source || {};
    const entries = Object.entries(bySource).filter(([, v]) => (v as number) > 0);
    const data = entries.map(([k, v], i) => ({
      name: k.length > 20 ? k.slice(0, 20) + "..." : k,
      value: v as number,
      itemStyle: { color: SOURCE_COLORS[i % SOURCE_COLORS.length] },
    }));
    if (!data.length) data.push({ name: "暂无数据", value: 1, itemStyle: { color: "#334155" } });
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "item" as const, formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { color: "#94a3b8", fontSize: 9 }, type: "scroll" as const },
      series: [{
        type: "pie", radius: ["30%", "60%"], center: ["50%", "45%"], data,
        label: { color: "#94a3b8", fontSize: 9, formatter: "{b}" },
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.5)" } },
      }],
    };
  }, [memStats]);

  const ltEnterpriseHeatmapOption = useMemo(() => {
    const byEnt = memStats?.long_term?.by_enterprise || {};
    const byCat = memStats?.long_term?.by_category || {};
    const topEnts = Object.entries(byEnt).sort(([, a], [, b]) => (b as number) - (a as number)).slice(0, 8).map(([k]) => k);
    const cats = Object.keys(byCat);
    if (!topEnts.length || !cats.length) return { backgroundColor: "transparent" };
    const data: number[][] = [];
    cats.forEach((cat, ci) => {
      topEnts.forEach((ent, ei) => {
        const count = items.filter((i) => i.category === cat && i.enterprise_id === ent).length;
        data.push([ei, ci, count]);
      });
    });
    return {
      backgroundColor: "transparent",
      tooltip: { formatter: (p: any) => `${CAT_LABELS[cats[p.data[1]]] || cats[p.data[1]]} × ${topEnts[p.data[0]].slice(0, 10)}: ${p.data[2]}条` },
      grid: { left: 100, right: 40, top: 10, bottom: 60 },
      xAxis: { type: "category" as const, data: topEnts.map((e) => e.slice(0, 8)), axisLabel: { color: "#94a3b8", fontSize: 9, rotate: 30 } },
      yAxis: { type: "category" as const, data: cats.map((c) => CAT_LABELS[c] || c), axisLabel: { color: "#94a3b8", fontSize: 10 } },
      visualMap: { min: 0, max: Math.max(...data.map((d) => d[2]), 1), show: true, orient: "vertical" as const, right: 0, top: "center", textStyle: { color: "#94a3b8", fontSize: 10 }, inRange: { color: ["#1e293b", "#10b981", "#34d399", "#f59e0b"] } },
      series: [{ type: "heatmap" as const, data, label: { show: true, color: "#fff", fontSize: 9, formatter: (p: any) => p.data[2] || "" }, itemStyle: { borderColor: "#0f172a", borderWidth: 2 } }],
    };
  }, [memStats, items]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">💾 长期记忆库</div>
          <div style={{ display: "flex", gap: 8 }}>
            <span className="tag tag-emerald">总计: {total} 条</span>
            <button className="scada-btn secondary" style={{ fontSize: 11, padding: "2px 8px" }} type="button" onClick={() => setShowExport(!showExport)}>📤 导出</button>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <input className="scada-input" placeholder="搜索..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} style={{ width: 200 }} />
          <select className="scada-input" value={filterCat} onChange={(e) => { setFilterCat(e.target.value); setPage(0); }} style={{ width: 140 }}>
            <option value="">全部分类</option>
            <option value="enterprise_data">企业数据</option>
            <option value="warning_experience">预警经验</option>
            <option value="knowledge">知识库</option>
            <option value="regulation">法规标准</option>
            <option value="accident_case">事故案例</option>
          </select>
          <button className="scada-btn secondary" type="button" onClick={loadData}>🔄 刷新</button>
        </div>
      </div>

      {showExport && <ExportDialog memoryType="long" onClose={() => setShowExport(false)} />}

      {memStats && (
        <>
          <div className="row cols-4" style={{ marginBottom: 14 }}>
            <StatCard value={memStats.long_term?.total ?? 0} label="长期记忆总数" color="#10b981" icon="💾" />
            <StatCard value={memStats.long_term?.by_priority?.P0 ?? 0} label="P0 紧急" color="#ef4444" icon="🔴" />
            <StatCard value={Object.keys(memStats.long_term?.by_category || {}).length} label="分类数量" color="#3b82f6" icon="📂" />
            <StatCard value={Object.keys(memStats.long_term?.by_enterprise || {}).length} label="关联企业" color="#f59e0b" icon="🏢" />
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📊 分类分布</div>
              <ReactECharts option={catPieOption} style={{ height: 280 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📈 优先级分布</div>
              <ReactECharts option={prioBarOption} style={{ height: 280 }} />
            </div>
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📈 入库时间趋势</div>
              <ReactECharts option={timelineOption} style={{ height: 280 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📁 数据来源TOP10</div>
              <ReactECharts option={sourceBarOption} style={{ height: 280 }} />
            </div>
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>🏢 企业关联TOP8</div>
              <ReactECharts option={enterpriseBarOption} style={{ height: 280 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>⏱️ 验证覆盖率</div>
              <ReactECharts option={ltImportanceGaugeOption} style={{ height: 220 }} />
            </div>
          </div>
          <div className="row cols-2" style={{ marginBottom: 14 }}>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>📦 数据源分布</div>
              <ReactECharts option={ltSourcePieOption} style={{ height: 280 }} />
            </div>
            <div className="scada-card">
              <div className="risk-report-title" style={{ marginBottom: 10 }}>🔥 企业×分类关联热力图</div>
              <ReactECharts option={ltEnterpriseHeatmapOption} style={{ height: 280 }} />
            </div>
          </div>
          <div className="scada-card" style={{ marginBottom: 14 }}>
            <div className="risk-report-title" style={{ marginBottom: 10 }}>🔥 分类×优先级关联热力图</div>
            <ReactECharts option={heatmapOption} style={{ height: Math.max(200, Object.keys(memStats.long_term?.by_category || {}).length * 40 + 80) }} />
          </div>
        </>
      )}

      <div className="scada-card">
        {items.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">💾</div><div>长期记忆库为空</div></div>
        ) : (
          <table className="scada-table">
            <thead><tr><th>优先级</th><th>分类</th><th>内容</th><th>数据源</th><th>企业ID</th><th>时间</th><th>已验证</th><th>操作</th></tr></thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td><span className="tag" style={{ background: PRIO_BG[item.priority] || PRIO_BG.P1, color: PRIO_COLORS[item.priority] || PRIO_COLORS.P1, fontWeight: 700, fontSize: 10 }}>{item.priority}</span></td>
                  <td><span className="tag tag-cyan" style={{ fontSize: 10 }}>{CAT_LABELS[item.category] || item.category}</span></td>
                  <td style={{ maxWidth: 350, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 12 }}>{item.text}</td>
                  <td style={{ fontSize: 11, color: "#94a3b8" }}>{item.data_source || "—"}</td>
                  <td className="font-mono" style={{ fontSize: 11 }}>{item.enterprise_id || "—"}</td>
                  <td style={{ fontSize: 11, color: "#94a3b8" }}>{item.time}</td>
                  <td>{item.verified ? <span style={{ color: "#10b981" }}>✅</span> : <span style={{ color: "#64748b" }}>—</span>}</td>
                  <td><button className="scada-btn secondary" style={{ fontSize: 10, padding: "2px 6px" }} type="button" onClick={() => setDetailItem(item)}>📋 详情</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {total > pageSize && (
          <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 12 }}>
            <button className="scada-btn secondary" type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button>
            <span style={{ color: "#94a3b8", lineHeight: "32px" }}>第 {page + 1} 页 / 共 {Math.ceil(total / pageSize)} 页</span>
            <button className="scada-btn secondary" type="button" disabled={(page + 1) * pageSize >= total} onClick={() => setPage(page + 1)}>下一页</button>
          </div>
        )}
      </div>
      {detailItem && <MemoryDetailModal item={detailItem} onClose={() => setDetailItem(null)} />}
    </div>
  );
}

function ApprovalSection() {
  const [approvals, setApprovals] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    const resp = await fetchApprovals({ status: filterStatus || undefined, limit: 50 });
    if (resp) { setApprovals(resp.items || []); setTotal(resp.total); }
    setLoading(false);
  }, [filterStatus]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleDecide = useCallback(async (id: string, decision: string) => {
    const comment = decision === "approved" ? "审批通过" : "需要进一步修改";
    await decideApproval(id, decision, "admin", comment);
    loadData();
  }, [loadData]);

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">📋 管理员审批工作流</div>
          <div style={{ display: "flex", gap: 8 }}>
            <span className="tag tag-orange">待审批: {approvals.filter((a) => a.status === "pending").length}</span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <select className="scada-input" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} style={{ width: 120 }}>
            <option value="">全部状态</option>
            <option value="pending">待审批</option>
            <option value="approved">已批准</option>
            <option value="rejected">已驳回</option>
          </select>
          <button className="scada-btn secondary" type="button" onClick={loadData}>🔄 刷新</button>
        </div>
      </div>

      <div className="scada-card">
        {approvals.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">📋</div><div>暂无审批记录</div></div>
        ) : (
          <table className="scada-table">
            <thead><tr><th>ID</th><th>目标</th><th>操作</th><th>发起人</th><th>状态</th><th>创建时间</th><th>决策</th></tr></thead>
            <tbody>
              {approvals.map((a) => (
                <tr key={a.id}>
                  <td className="font-mono" style={{ fontSize: 11 }}>{a.id}</td>
                  <td style={{ fontSize: 12 }}>{a.target_id}</td>
                  <td style={{ fontSize: 12 }}>{a.action}</td>
                  <td style={{ fontSize: 12 }}>{a.actor}</td>
                  <td>
                    <span className="tag" style={{
                      background: a.status === "pending" ? "rgba(245,158,11,0.15)" : a.status === "approved" ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)",
                      color: a.status === "pending" ? "#f59e0b" : a.status === "approved" ? "#10b981" : "#ef4444",
                      fontWeight: 700,
                    }}>
                      {a.status === "pending" ? "待审批" : a.status === "approved" ? "已批准" : "已驳回"}
                    </span>
                  </td>
                  <td style={{ fontSize: 11, color: "#94a3b8" }}>{a.created_at}</td>
                  <td>
                    {a.status === "pending" && (
                      <div style={{ display: "flex", gap: 4 }}>
                        <button className="scada-btn" style={{ fontSize: 10, padding: "2px 8px", background: "#10b981" }} type="button" onClick={() => handleDecide(a.id, "approved")}>✅ 批准</button>
                        <button className="scada-btn" style={{ fontSize: 10, padding: "2px 8px", background: "#ef4444" }} type="button" onClick={() => handleDecide(a.id, "rejected")}>❌ 驳回</button>
                      </div>
                    )}
                    {a.decided_by && <span style={{ fontSize: 10, color: "#94a3b8" }}>审批人: {a.decided_by}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function AuditLogSection() {
  const [logs, setLogs] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterAction, setFilterAction] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 30;

  const loadData = useCallback(async () => {
    setLoading(true);
    const resp = await fetchAuditLogs({
      search: search || undefined,
      action: filterAction || undefined,
      limit: pageSize,
      offset: page * pageSize,
    });
    if (resp) { setLogs(resp.items || []); setTotal(resp.total); }
    setLoading(false);
  }, [search, filterAction, page]);

  useEffect(() => { loadData(); }, [loadData]);

  const actionColors: Record<string, string> = {
    import: "#3b82f6", batch_assess: "#f59e0b", assess_enterprise: "#f97316",
    migrate: "#8b5cf6", create_approval: "#6366f1", decide_approval: "#10b981",
  };

  return (
    <div>
      <div className="scada-card" style={{ marginBottom: 14 }}>
        <div className="risk-report-header">
          <div className="risk-report-title">🔍 审计日志</div>
          <span className="tag tag-blue">总计: {total} 条</span>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <input className="scada-input" placeholder="搜索日志..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} style={{ width: 200 }} />
          <select className="scada-input" value={filterAction} onChange={(e) => { setFilterAction(e.target.value); setPage(0); }} style={{ width: 140 }}>
            <option value="">全部操作</option>
            <option value="import">数据导入</option>
            <option value="batch_assess">批量评估</option>
            <option value="assess_enterprise">企业评估</option>
            <option value="migrate">记忆迁移</option>
            <option value="create_approval">创建审批</option>
            <option value="decide_approval">审批决策</option>
          </select>
          <button className="scada-btn secondary" type="button" onClick={loadData}>🔍 搜索</button>
        </div>
      </div>

      <div className="scada-card">
        {logs.length === 0 ? (
          <div className="empty-state"><div className="empty-state-icon">🔍</div><div>暂无审计日志</div></div>
        ) : (
          <table className="scada-table">
            <thead><tr><th>时间</th><th>操作</th><th>操作人</th><th>目标</th><th>详情</th></tr></thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td style={{ fontSize: 11, color: "#94a3b8", whiteSpace: "nowrap" }}>{log.time}</td>
                  <td><span className="tag" style={{ background: `${actionColors[log.action] || "#64748b"}22`, color: actionColors[log.action] || "#64748b", fontWeight: 600, fontSize: 10 }}>{log.action}</span></td>
                  <td style={{ fontSize: 12 }}>{log.actor}</td>
                  <td style={{ fontSize: 12 }}>{log.target}</td>
                  <td style={{ fontSize: 12, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{log.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {total > pageSize && (
          <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 12 }}>
            <button className="scada-btn secondary" type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页</button>
            <span style={{ color: "#94a3b8", lineHeight: "32px" }}>第 {page + 1} 页 / 共 {Math.ceil(total / pageSize)} 页</span>
            <button className="scada-btn secondary" type="button" disabled={(page + 1) * pageSize >= total} onClick={() => setPage(page + 1)}>下一页</button>
          </div>
        )}
      </div>
    </div>
  );
}
