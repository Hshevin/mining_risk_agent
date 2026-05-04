import type { HealthResponse, IterationStatus } from "../api/types";
import { SCENARIO_LABELS } from "../data/demoData";
import type { ScenarioId } from "../api/types";

interface Props {
  health: HealthResponse | null;
  scenario: ScenarioId;
  onScenarioChange: (s: ScenarioId) => void;
  iteration: IterationStatus | null;
  demoMode: boolean;
  onDemoToggle: (b: boolean) => void;
}

export default function Sidebar({
  health,
  scenario,
  onScenarioChange,
  iteration,
  demoMode,
  onDemoToggle,
}: Props) {
  const online = health?.status === "healthy";

  return (
    <aside className="sidebar">
      <div className="sidebar-title">🛡️ 风险预警智能体</div>
      <div className="sidebar-subtitle">SCADA DASHBOARD v1.0</div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 12,
          color: online ? "#10b981" : "#ef4444",
          marginBottom: 12,
        }}
      >
        <span className={`status-dot ${online ? "online" : "offline"}`}></span>
        {online ? "后端服务正常" : "后端离线 (Mock)"}
      </div>

      <div className="sidebar-divider" />
      <div className="sidebar-section-title">场景配置</div>
      <select
        className="scada-select"
        value={scenario}
        onChange={(e) => onScenarioChange(e.target.value as ScenarioId)}
      >
        {(Object.keys(SCENARIO_LABELS) as ScenarioId[]).map((s) => (
          <option key={s} value={s}>
            {SCENARIO_LABELS[s]}
          </option>
        ))}
      </select>

      <div className="sidebar-divider" />
      <div className="sidebar-section-title">系统状态</div>
      {iteration ? (
        <>
          <div
            style={{
              fontSize: 13,
              color: "#e5e7eb",
              fontWeight: 600,
              marginBottom: 4,
            }}
          >
            {iteration.current_state_cn || iteration.current_state || "未知"}
          </div>
          {iteration.pending_approvals && iteration.pending_approvals.length > 0 ? (
            <div style={{ fontSize: 11, color: "#eab308" }}>
              ⏳ 待审批: {iteration.pending_approvals.length} 项
            </div>
          ) : (
            <div style={{ fontSize: 11, color: "#6b7280" }}>无待审批事项</div>
          )}
        </>
      ) : (
        <div style={{ fontSize: 11, color: "#6b7280" }}>无法获取迭代状态</div>
      )}

      <div className="sidebar-divider" />
      <div className="sidebar-section-title">路演控制</div>
      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 13,
          color: "#e5e7eb",
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={demoMode}
          onChange={(e) => onDemoToggle(e.target.checked)}
        />
        演示模式
      </label>
      {demoMode && (
        <div style={{ fontSize: 11, color: "#3b82f6", marginTop: 4 }}>
          ✨ 自动轮播已启用
        </div>
      )}

      <div
        style={{
          marginTop: 24,
          fontSize: 10,
          color: "#374151",
          lineHeight: 1.6,
        }}
      >
        Harness 工程化管控
        <br />
        推荐 1920×1080 投影
      </div>
    </aside>
  );
}
