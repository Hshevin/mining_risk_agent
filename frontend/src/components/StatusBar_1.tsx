import { useEffect, useState } from "react";
import type { HealthResponse } from "../api/types";

interface Props {
  health: HealthResponse | null;
  scenarioName: string;
}

export default function StatusBar({ health, scenarioName }: Props) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const online = health?.status === "healthy";
  const statusText = online ? "ONLINE" : "OFFLINE";
  const dot = online ? "online" : "offline";
  const version = health?.version ?? "—";
  const time = now.toLocaleTimeString("zh-CN", { hour12: false });

  return (
    <div className="system-status-bar">
      <div className="status-bar-item">
        <span className={`status-dot ${dot}`}></span>
        <span className="font-mono">SYS {statusText}</span>
      </div>
      <div className="status-bar-item font-mono">v{version}</div>
      <div className="status-bar-item">场景: {scenarioName}</div>
      <div className="status-bar-item font-mono">{time}</div>
    </div>
  );
}
