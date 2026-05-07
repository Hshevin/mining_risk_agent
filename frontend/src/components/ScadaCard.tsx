import type { ReactNode } from "react";

interface Props {
  title: string;
  value: ReactNode;
  sub?: string;
  glowClass?: string;
  pulse?: boolean;
}

export default function ScadaCard({ title, value, sub, glowClass, pulse }: Props) {
  return (
    <div className={`scada-card ${pulse ? "risk-red-pulse" : ""}`}>
      <div className="scada-card-title">{title}</div>
      <div className={`scada-card-value ${glowClass ?? "glow-white"}`}>{value}</div>
      {sub && <div className="scada-card-sub">{sub}</div>}
    </div>
  );
}
