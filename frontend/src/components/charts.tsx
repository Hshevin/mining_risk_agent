import ReactECharts from "echarts-for-react";
import type { ReactNode } from "react";
import type { MemoryChartItem, MemoryHeatmap, MemoryTrendPoint, ShapContribution } from "../api/types";

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

const MEMORY_COLORS = ["#ef4444", "#f97316", "#eab308", "#3b82f6", "#10b981", "#06b6d4", "#a855f7"];

interface ChartShellProps {
  title: string;
  children: ReactNode;
}

function ChartShell({ title, children }: ChartShellProps) {
  return (
    <div className="scada-card chart-card">
      <div className="scada-card-title">{title}</div>
      {children}
    </div>
  );
}

export function MemoryTrendChart({
  data,
  onSeriesClick,
}: {
  data: MemoryTrendPoint[];
  onSeriesClick?: (seriesName: string) => void;
}) {
  const option = {
    backgroundColor: "transparent",
    color: ["#3b82f6", "#10b981", "#f97316", "#eab308"],
    tooltip: { trigger: "axis" as const },
    legend: { top: 0, textStyle: { color: "#cbd5e1", fontSize: 11 } },
    grid: { left: 42, right: 18, top: 48, bottom: 44 },
    dataZoom: [{ type: "inside" as const }, { type: "slider" as const, height: 18, bottom: 8 }],
    xAxis: {
      type: "category" as const,
      data: data.map((item) => item.date),
      axisLine: { lineStyle: { color: "#374151" } },
      axisLabel: { color: "#9ca3af", fontSize: 11 },
    },
    yAxis: {
      type: "value" as const,
      axisLine: { lineStyle: { color: "#374151" } },
      axisLabel: { color: "#9ca3af", fontSize: 11 },
      splitLine: { lineStyle: { color: "#1f2937" } },
    },
    series: [
      { name: "short_term", type: "line" as const, smooth: true, data: data.map((item) => item.short_term) },
      { name: "long_term", type: "line" as const, smooth: true, data: data.map((item) => item.long_term) },
      { name: "warning_experience", type: "line" as const, smooth: true, data: data.map((item) => item.warning_experience) },
      { name: "agentfs_write", type: "line" as const, smooth: true, data: data.map((item) => item.agentfs_write) },
    ],
  };
  return (
    <ChartShell title="记忆写入 / 归档趋势">
      <ReactECharts
        option={option}
        style={{ height: 310 }}
        onEvents={{ click: (params: { seriesName?: string }) => params.seriesName && onSeriesClick?.(params.seriesName) }}
      />
    </ChartShell>
  );
}

export function MemoryBarChart({
  title,
  data,
  onClick,
}: {
  title: string;
  data: MemoryChartItem[];
  onClick?: (name: string) => void;
}) {
  const option = {
    backgroundColor: "transparent",
    color: MEMORY_COLORS,
    tooltip: { trigger: "axis" as const },
    grid: { left: 42, right: 18, top: 24, bottom: 58 },
    dataZoom: data.length > 8 ? [{ type: "inside" as const }, { type: "slider" as const, height: 18, bottom: 8 }] : undefined,
    xAxis: {
      type: "category" as const,
      data: data.map((item) => item.name),
      axisLine: { lineStyle: { color: "#374151" } },
      axisLabel: { color: "#9ca3af", fontSize: 11, interval: 0, rotate: data.length > 5 ? 28 : 0 },
    },
    yAxis: {
      type: "value" as const,
      axisLine: { lineStyle: { color: "#374151" } },
      axisLabel: { color: "#9ca3af", fontSize: 11 },
      splitLine: { lineStyle: { color: "#1f2937" } },
    },
    series: [
      {
        type: "bar" as const,
        barMaxWidth: 34,
        data: data.map((item) => ({
          value: item.value,
          itemStyle: { color: LEVEL_COLORS[item.name] ?? (item.name === "P0" ? "#ef4444" : item.name === "P1" ? "#f97316" : undefined) },
        })),
      },
    ],
  };
  return (
    <ChartShell title={title}>
      <ReactECharts
        option={option}
        style={{ height: 300 }}
        onEvents={{ click: (params: { name?: string }) => params.name && onClick?.(params.name) }}
      />
    </ChartShell>
  );
}

export function MemoryDonutChart({
  title,
  data,
  onClick,
}: {
  title: string;
  data: MemoryChartItem[];
  onClick?: (name: string) => void;
}) {
  const option = {
    backgroundColor: "transparent",
    color: MEMORY_COLORS,
    tooltip: { trigger: "item" as const, formatter: "{b}: {c} ({d}%)" },
    legend: { bottom: 0, textStyle: { color: "#cbd5e1", fontSize: 11 } },
    series: [
      {
        type: "pie" as const,
        radius: ["46%", "72%"],
        center: ["50%", "44%"],
        avoidLabelOverlap: true,
        label: { color: "#e5e7eb", fontSize: 11, formatter: "{b}\n{d}%" },
        labelLine: { lineStyle: { color: "#374151" } },
        data,
      },
    ],
  };
  return (
    <ChartShell title={title}>
      <ReactECharts
        option={option}
        style={{ height: 300 }}
        onEvents={{ click: (params: { name?: string }) => params.name && onClick?.(params.name) }}
      />
    </ChartShell>
  );
}

export function MemoryHeatmapChart({
  data,
  onClick,
}: {
  data: MemoryHeatmap;
  onClick?: (riskType: string, priority: string) => void;
}) {
  const values = data.data.map((item) => item.value);
  const option = {
    backgroundColor: "transparent",
    tooltip: { position: "top" as const },
    grid: { left: 78, right: 20, top: 28, bottom: 46 },
    xAxis: {
      type: "category" as const,
      data: data.xAxis,
      splitArea: { show: true },
      axisLabel: { color: "#9ca3af", fontSize: 11, interval: 0, rotate: data.xAxis.length > 4 ? 25 : 0 },
      axisLine: { lineStyle: { color: "#374151" } },
    },
    yAxis: {
      type: "category" as const,
      data: data.yAxis,
      splitArea: { show: true },
      axisLabel: { color: "#e5e7eb", fontSize: 11 },
      axisLine: { lineStyle: { color: "#374151" } },
    },
    visualMap: {
      min: 0,
      max: Math.max(1, ...values),
      calculable: true,
      orient: "horizontal" as const,
      left: "center",
      bottom: 0,
      textStyle: { color: "#9ca3af" },
      inRange: { color: ["#0f172a", "#3b82f6", "#eab308", "#f97316", "#ef4444"] },
    },
    series: [
      {
        name: "关联强度",
        type: "heatmap" as const,
        data: data.data.map((item) => [data.xAxis.indexOf(item.x), data.yAxis.indexOf(item.y), item.value]),
        label: { show: true, color: "#e5e7eb", fontSize: 11 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0, 0, 0, 0.5)" } },
      },
    ],
  };
  return (
    <ChartShell title="风险类型 × 优先级关联热力图">
      <ReactECharts
        option={option}
        style={{ height: 310 }}
        onEvents={{
          click: (params: { data?: [number, number, number] }) => {
            const point = params.data;
            if (!point) return;
            onClick?.(data.xAxis[point[0]], data.yAxis[point[1]]);
          },
        }}
      />
    </ChartShell>
  );
}
