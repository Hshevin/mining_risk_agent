import { useEffect, useState } from "react";
import { listKnowledge, readKnowledge } from "../api/client";

interface MemoryItem {
  text: string;
  priority: "P0" | "P1" | "P2" | "P3";
  time: string;
}

const PRIO_COLORS: Record<MemoryItem["priority"], string> = {
  P0: "#ef4444",
  P1: "#f97316",
  P2: "#3b82f6",
  P3: "#10b981",
};

interface RagResult {
  text: string;
  source: string;
  rerank_score: number;
}

const DEMO_RAG: RagResult[] = [
  {
    text: "《工矿风险预警智能体合规执行书》第3.2条：瓦斯浓度超过1.0%时必须立即撤人断电",
    source: "合规执行书.md",
    rerank_score: 0.94,
  },
  {
    text: "类似事故案例：2023年某煤矿瓦斯超限未撤人导致3人死亡，涉事企业被吊销安全生产许可证",
    source: "类似事故处理案例.md",
    rerank_score: 0.91,
  },
  {
    text: "处置经验归档：瓦斯泄漏应急响应SOP——切断电源→撤人→通风→检测→复电",
    source: "处置经验归档.md",
    rerank_score: 0.88,
  },
  {
    text: "工业物理常识：甲烷爆炸极限5%-15%，一氧化碳浓度超过0.0024%即对人体有害",
    source: "工业物理常识.md",
    rerank_score: 0.85,
  },
];

export default function KnowledgeMemoryPage() {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [content, setContent] = useState<string>("");
  const [loadingContent, setLoadingContent] = useState(false);

  const [memText, setMemText] = useState("发现3号储罐可燃气体浓度异常");
  const [memPrio, setMemPrio] = useState<MemoryItem["priority"]>("P2");
  const [memories, setMemories] = useState<MemoryItem[]>([]);

  const [query, setQuery] = useState("瓦斯泄漏");
  const [ragResults, setRagResults] = useState<RagResult[]>([]);

  useEffect(() => {
    listKnowledge().then((list) => {
      setFiles(list);
      if (list.length > 0) setSelected(list[0]);
    });
  }, []);

  useEffect(() => {
    if (!selected) {
      setContent("");
      return;
    }
    setLoadingContent(true);
    readKnowledge(selected).then((c) => {
      setContent(c ?? "无法读取文件内容");
      setLoadingContent(false);
    });
  }, [selected]);

  function addMemory() {
    setMemories((prev) => [
      ...prev,
      {
        text: memText,
        priority: memPrio,
        time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      },
    ]);
  }

  function purgeMemory() {
    let p2Count = memories.filter((m) => m.priority === "P2").length;
    const kept: MemoryItem[] = [];
    for (const m of memories) {
      if (m.priority === "P3") continue;
      if (m.priority === "P2" && p2Count > 1) {
        p2Count -= 1;
        continue;
      }
      kept.push(m);
    }
    setMemories(kept);
  }

  function recallRag() {
    if (!query.trim()) {
      setRagResults(DEMO_RAG.slice(0, 2));
      return;
    }
    const tokens = query.split(/\s+/).filter(Boolean);
    const filtered = DEMO_RAG.filter(
      (r) =>
        r.text.includes(query) || tokens.some((kw) => r.text.includes(kw)),
    );
    setRagResults(filtered.length > 0 ? filtered : DEMO_RAG.slice(0, 2));
  }

  const preview = content.length > 1200 ? content.slice(0, 1200) + "\n\n..." : content;

  return (
    <div>
      <div className="section-title">
        📚 知识库与记忆系统 — AgentFS + Git 版本控制 + 长短期混合记忆
      </div>

      <div className="subtitle">📁 六大核心知识库</div>
      <div style={{ fontSize: 12, color: "#10b981", marginBottom: 10 }}>
        共发现 {files.length} 个知识库文件
      </div>
      <div className="row cols-2">
        <div className="kb-list">
          {files.length === 0 && (
            <div style={{ padding: 12, color: "#6b7280", fontSize: 12 }}>
              未连接到知识库 API
            </div>
          )}
          {files.map((f) => (
            <button
              key={f}
              type="button"
              className={`kb-item ${f === selected ? "active" : ""}`}
              onClick={() => setSelected(f)}
            >
              {f}
            </button>
          ))}
        </div>
        <div>
          {loadingContent ? (
            <div style={{ color: "#6b7280", fontSize: 12 }}>加载中...</div>
          ) : (
            <pre className="json-code-block">{preview || "请选择文件预览"}</pre>
          )}
        </div>
      </div>

      <div className="divider" />

      <div className="subtitle">🧠 短期记忆系统（P0-P3 优先级 + LRU 清理）</div>
      <div className="row cols-2">
        <div>
          <label className="scada-label">记忆内容</label>
          <input
            className="scada-input"
            value={memText}
            onChange={(e) => setMemText(e.target.value)}
          />
          <label className="scada-label" style={{ marginTop: 8 }}>
            优先级
          </label>
          <select
            className="scada-select"
            value={memPrio}
            onChange={(e) => setMemPrio(e.target.value as MemoryItem["priority"])}
          >
            <option value="P0">P0 (最高)</option>
            <option value="P1">P1</option>
            <option value="P2">P2</option>
            <option value="P3">P3 (最低)</option>
          </select>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="scada-btn" type="button" onClick={addMemory}>
              ➕ 添加记忆
            </button>
            <button className="scada-btn secondary" type="button" onClick={purgeMemory}>
              🧹 触发清理
            </button>
          </div>
        </div>
        <div>
          {memories.length === 0 ? (
            <div className="empty-state">暂无记忆，请在左侧添加</div>
          ) : (
            memories.map((m, idx) => (
              <div
                key={idx}
                className="memory-card"
                style={{ borderLeftColor: PRIO_COLORS[m.priority] }}
              >
                <span
                  style={{
                    color: PRIO_COLORS[m.priority],
                    fontWeight: 700,
                    fontSize: 11,
                  }}
                >
                  {m.priority}
                </span>
                <span style={{ color: "#e5e7eb", fontSize: 13 }}>{m.text}</span>
                <span
                  style={{
                    color: "#374151",
                    fontSize: 11,
                    fontFamily: "JetBrains Mono, monospace",
                    marginLeft: "auto",
                  }}
                >
                  {m.time}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="divider" />

      <div className="subtitle">
        🔍 长期记忆召回（RAG: SelfQuery + BGE-Reranker 精排）
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input
          className="scada-input"
          style={{ flex: 1 }}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="查询词"
        />
        <button className="scada-btn" type="button" onClick={recallRag}>
          🔎 召回记忆
        </button>
      </div>
      {ragResults.map((r, idx) => {
        const color =
          r.rerank_score >= 0.9
            ? "#10b981"
            : r.rerank_score >= 0.85
            ? "#3b82f6"
            : "#9ca3af";
        return (
          <div className="advice-card" key={idx}>
            <div style={{ fontSize: 13, color: "#e5e7eb" }}>{r.text}</div>
            <div
              style={{
                fontSize: 11,
                color: "#6b7280",
                marginTop: 6,
                fontFamily: "JetBrains Mono, monospace",
              }}
            >
              📄 {r.source} | RERANK:{" "}
              <span style={{ color, fontWeight: 700 }}>
                {r.rerank_score.toFixed(2)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
