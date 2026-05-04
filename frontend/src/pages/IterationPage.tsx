import { useEffect, useState } from "react";
import { fetchIterationStatus, triggerIteration } from "../api/client";
import type { IterationStatus } from "../api/types";
import ScadaCard from "../components/ScadaCard";

interface VersionRow {
  version: string;
  date: string;
  status: string;
  f1: string;
  samples: string;
}

const TIMELINE: VersionRow[] = [
  { version: "v1.0.0", date: "2024-01-15", status: "✅ 生产", f1: "0.842", samples: "12,000" },
  { version: "v1.1.0", date: "2024-03-20", status: "✅ 生产", f1: "0.861", samples: "18,500" },
  { version: "v2.0.0", date: "2024-06-10", status: "🔄 灰度发布中", f1: "0.878", samples: "25,000" },
];

const FALLBACK_STATUS: IterationStatus = {
  current_state: "CANARY",
  current_state_cn: "灰度发布中",
  monitor_summary: { total_samples: 25000, recent_f1: 0.878 },
  pending_approvals: [
    { record_id: "approval_v2_001", model_version: "v2.0.0", status: "SECURITY_APPROVED" },
  ],
};

const STAGES = [
  { name: "监控触发检查...", pct: 0.1 },
  { name: "数据清洗与特征工程...", pct: 0.25 },
  { name: "Stacking 模型训练（7基学习器+元学习器）...", pct: 0.45 },
  { name: "5折时序交叉验证...", pct: 0.6 },
  { name: "回归测试与 Drift 分析...", pct: 0.75 },
  { name: "两级终审流程...", pct: 0.85 },
  { name: "灰度发布 0.1 → 0.5 → 1.0...", pct: 0.95 },
  { name: "✅ 迭代完成，模型已上线", pct: 1.0 },
];

export default function IterationPage() {
  const [status, setStatus] = useState<IterationStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [stageIdx, setStageIdx] = useState(0);
  const [pct, setPct] = useState(0);
  const [resultMsg, setResultMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchIterationStatus().then((s) => setStatus(s ?? FALLBACK_STATUS));
  }, []);

  async function runIteration() {
    setRunning(true);
    setResultMsg(null);
    setStageIdx(0);
    setPct(0);
    for (let i = 0; i < STAGES.length; i++) {
      setStageIdx(i);
      setPct(STAGES[i].pct);
      await new Promise((r) => setTimeout(r, 500));
    }
    setRunning(false);

    const real = await triggerIteration();
    if (real) setResultMsg(real.message ?? "后端迭代请求已下发");
    fetchIterationStatus().then((s) => s && setStatus(s));
  }

  const cur = status ?? FALLBACK_STATUS;
  const totalSamples = cur.monitor_summary?.total_samples;
  const recentF1 = cur.monitor_summary?.recent_f1;
  const totalSamplesStr =
    typeof totalSamples === "number" ? totalSamples.toLocaleString() : "N/A";
  const recentF1Str = typeof recentF1 === "number" ? recentF1.toFixed(3) : "N/A";

  const pending = cur.pending_approvals ?? [];
  const secOk = pending.some((p) =>
    ["SECURITY_APPROVED", "TECH_APPROVED", "STAGING", "CANARY", "PRODUCTION"].includes(
      p.status,
    ),
  );
  const techOk = pending.some((p) =>
    ["TECH_APPROVED", "STAGING", "CANARY", "PRODUCTION"].includes(p.status),
  );

  const canaryRatio =
    cur.current_state === "CANARY"
      ? 0.5
      : cur.current_state === "PRODUCTION"
      ? 1.0
      : 0.0;

  return (
    <div>
      <div className="section-title">
        🔄 模型迭代与 CI/CD — 监控触发 → 训练 → 回归测试 → 两级终审 → 灰度发布
      </div>

      <div className="subtitle">📜 模型版本时间线</div>
      <table className="scada-table">
        <thead>
          <tr>
            <th>版本</th>
            <th>日期</th>
            <th>状态</th>
            <th>F1</th>
            <th>样本</th>
          </tr>
        </thead>
        <tbody>
          {TIMELINE.map((r) => (
            <tr key={r.version}>
              <td className="font-mono">{r.version}</td>
              <td className="font-mono">{r.date}</td>
              <td>{r.status}</td>
              <td className="font-mono">{r.f1}</td>
              <td className="font-mono">{r.samples}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="divider" />

      <div className="subtitle">📊 迭代状态仪表盘</div>
      <div className="row cols-4">
        <ScadaCard title="当前状态" value={cur.current_state_cn || cur.current_state} />
        <ScadaCard title="累计样本" value={totalSamplesStr} glowClass="glow-blue" />
        <ScadaCard title="F1 分数" value={recentF1Str} glowClass="glow-green" />
        <ScadaCard
          title="待审批"
          value={pending.length}
          glowClass={pending.length > 0 ? "glow-yellow" : "glow-white"}
        />
      </div>

      <div style={{ marginTop: 16 }}>
        <div className="subtitle">📝 审批流程</div>
        <div className="row cols-2">
          <ApprovalBadge ok={secOk} label="安全负责人" />
          <ApprovalBadge ok={techOk} label="技术负责人" />
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <div className="subtitle">🚀 灰度流量比例</div>
        <div className="scada-progress-track">
          <div
            className="scada-progress-fill"
            style={{ width: `${canaryRatio * 100}%` }}
          />
        </div>
        <div
          style={{
            fontSize: 12,
            color: "#9ca3af",
            marginTop: 6,
            fontFamily: "JetBrains Mono, monospace",
          }}
        >
          当前灰度比例: {(canaryRatio * 100).toFixed(0)}%
        </div>
      </div>

      <div className="divider" />

      <div className="subtitle">▶️ 触发模拟迭代</div>
      <button
        className="scada-btn full-width"
        type="button"
        onClick={runIteration}
        disabled={running}
      >
        {running ? "执行中..." : "🚀 触发模拟迭代流水线"}
      </button>

      {running && (
        <div style={{ marginTop: 12 }}>
          <div
            className="font-mono"
            style={{ fontSize: 13, color: "#3b82f6", marginBottom: 6 }}
          >
            {STAGES[stageIdx].name}
          </div>
          <div className="scada-progress-track">
            <div className="scada-progress-fill" style={{ width: `${pct * 100}%` }} />
          </div>
        </div>
      )}

      {resultMsg && <div className="alert info" style={{ marginTop: 12 }}>{resultMsg}</div>}
    </div>
  );
}

function ApprovalBadge({ ok, label }: { ok: boolean; label: string }) {
  const color = ok ? "#10b981" : "#ef4444";
  const bg = ok ? "rgba(16,185,129,0.08)" : "rgba(239,68,68,0.08)";
  return (
    <div
      style={{
        padding: 14,
        borderRadius: 8,
        background: bg,
        border: `1px solid ${color}44`,
        fontSize: 13,
        fontWeight: 600,
        color,
      }}
    >
      {ok ? `✅ ${label}已审批` : `⏳ ${label}待审批`}
    </div>
  );
}
