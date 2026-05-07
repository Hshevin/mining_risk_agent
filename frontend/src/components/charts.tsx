import ReactECharts from "echarts-for-react";
import type { ShapContribution } from "../api/types";

const LEVEL_COLORS: Record<string, string> = {
  红: "#ef4444",
  橙: "#f97316",
  黄: "#eab308",
  蓝: "#3b82f6",
};

interface ProbProps {
  probs: Record<string, number>;
  centerLevel?: string;
}

export function ProbabilityChart({ probs, centerLevel }: ProbProps) {
  const data = Object.entries(probs).map(([name, value]) => ({
    name,
    value: Number(value),
    itemStyle: { color: LEVEL_COLORS[name] ?? "#6b7280" },
  }));

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item" as const,
      formatter: "{b}: {d}%",
    },
    title: centerLevel
      ? {
          text: `${centerLevel}`,
          subtext: "判定等级",
          left: "center",
          top: "42%",
          textStyle: { color: LEVEL_COLORS[centerLevel] ?? "#fff", fontSize: 28, fontWeight: 700 },
          subtextStyle: { color: "#9ca3af", fontSize: 11 },
        }
      : undefined,
    series: [
      {
        type: "pie" as const,
        radius: ["55%", "80%"],
        avoidLabelOverlap: true,
        label: { color: "#e5e7eb", fontSize: 12, formatter: "{b}: {d}%" },
        labelLine: { lineStyle: { color: "#374151" } },
        data,
      },
    ],
  };

  return (
    <div className="scada-card" style={{ padding: 8 }}>
      <div className="scada-card-title" style={{ padding: "8px 8px 0" }}>
        概率分布
      </div>
      <ReactECharts option={option} style={{ height: 280 }} />
    </div>
  );
}

interface ShapProps {
  contributions: ShapContribution[];
  topN?: number;
}

export function ShapChart({ contributions, topN = 5 }: ShapProps) {
  const sorted = [...contributions]
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, topN)
    .reverse();

  const option = {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" as const },
    grid: { left: 100, right: 30, top: 30, bottom: 30 },
    xAxis: {
      type: "value" as const,
      axisLine: { lineStyle: { color: "#374151" } },
      axisLabel: { color: "#9ca3af", fontSize: 11 },
      splitLine: { lineStyle: { color: "#1f2937" } },
    },
    yAxis: {
      type: "category" as const,
      data: sorted.map((s) => s.feature),
      axisLine: { lineStyle: { color: "#374151" } },
      axisLabel: { color: "#e5e7eb", fontSize: 11 },
    },
    series: [
      {
        type: "bar" as const,
        data: sorted.map((s) => ({
          value: s.contribution,
          itemStyle: {
            color: s.contribution >= 0 ? "#ef4444" : "#10b981",
          },
        })),
        label: {
          show: true,
          position: "right" as const,
          color: "#e5e7eb",
          formatter: (p: { value: number }) => p.value.toFixed(2),
        },
      },
    ],
  };

  return (
    <div className="scada-card" style={{ padding: 8 }}>
      <div className="scada-card-title" style={{ padding: "8px 8px 0" }}>
        SHAP TOP{topN} 归因
      </div>
      <ReactECharts option={option} style={{ height: 280 }} />
    </div>
  );
}
