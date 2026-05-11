import { useEffect, useMemo, useState } from "react";
import {
  downloadMemoryExport,
  fetchMemoryStatistics,
  fetchKnowledgeSystemOverview,
  searchKnowledgeRag,
} from "../api/client";
import type {
  KnowledgeBaseStatus,
  KnowledgeRagResult,
  KnowledgeSystemOverview,
  MemoryModule,
  MemoryPriority,
  MemoryRecord,
  MemoryStatisticsParams,
  MemoryStatisticsResponse,
} from "../api/types";
import {
  MemoryBarChart,
  MemoryDonutChart,
  MemoryHeatmapChart,
  MemoryTrendChart,
} from "../components/charts";
import ScadaCard from "../components/ScadaCard";
import Tabs from "../components/Tabs";

const SECTION_TABS = [
  { id: "overview", label: "总览" },
  { id: "kbs", label: "六库状态" },
  { id: "agentfs", label: "AgentFS 同步" },
  { id: "rag", label: "RAG 检索" },
  { id: "memory", label: "记忆系统" },
  { id: "audit", label: "审计告警" },
];

const PRESET_QUERIES = [
  "粉尘涉爆除尘系统异常",
  "危化品泄漏处置",
  "冶金煤气报警",
  "有限空间作业中毒窒息",
  "合规红线规则",
  "企业执行条件",
];

const FALLBACK_OVERVIEW: KnowledgeSystemOverview = {
  overview: {
    audit_status: "PASS_WITH_WARNINGS",
    pass_count: 15,
    warn_count: 6,
    fail_count: 0,
    kb_file_count: 6,
    rag_chunks: 639,
    real_public_data_cases: 36,
    rule_count: 65,
    agentfs_sync_status: "match",
    embedding_backend: "fallback",
  },
  knowledge_bases: [
    {
      filename: "工矿风险预警智能体合规执行书.md",
      type: "compliance",
      highlight: "COM 合规红线、上报、停产、撤人、整改和审计规则",
      agentfs_match: true,
      rag_chunks: 60,
      source_commit_short: "2f0819487bda",
      quality_status: "PASS",
      summary: "合规规则与审计留痕知识底座。",
      key_sections: ["合规红线规则表", "必须上报、停产、撤人、整改、复查和数据审计规则"],
      data_sources: ["安全生产法", "工贸重大事故隐患判定标准", "项目审计规则"],
    },
    {
      filename: "部门分级审核SOP.md",
      type: "sop",
      highlight: "分级路由、协同、退回和闭环 SOP",
      agentfs_match: true,
      rag_chunks: 54,
      source_commit_short: "2f0819487bda",
      quality_status: "PASS",
      summary: "监管部门分级审核和闭环流程知识库。",
      key_sections: ["分级路由、协同、退回和闭环 SOP 表", "机器可读摘要"],
      data_sources: ["部门/人员公开字段", "项目 SOP"],
    },
    {
      filename: "工业物理常识及传感器时间序列逻辑.md",
      type: "physics",
      highlight: "PHY 工况逻辑、传感器时间序列和场景阈值",
      agentfs_match: true,
      rag_chunks: 62,
      source_commit_short: "2f0819487bda",
      quality_status: "PASS",
      summary: "粉尘、危化、冶金、有限空间工况逻辑知识库。",
      key_sections: ["数据来源与事实边界", "工况逻辑和时间序列规则表"],
      data_sources: ["公开字段映射", "传感器逻辑规则", "国家/行业标准"],
    },
    {
      filename: "企业已具备的执行条件.md",
      type: "conditions",
      highlight: "公开数据重建的企业执行条件事实库",
      agentfs_match: true,
      rag_chunks: 221,
      source_commit_short: "2f0819487bda",
      quality_status: "PASS",
      summary: "人员、设备、资质、隐患、处罚、行业和位置等条件摘要。",
      key_sections: ["公开数据统计", "粉尘涉爆执行条件", "冶金执行条件", "危化品执行条件"],
      data_sources: ["public_data_inventory.json", "public_data_field_mapping.csv"],
    },
    {
      filename: "类似事故处理案例.md",
      type: "cases",
      highlight: "36 个真实公开数据 B/C/D 类案例",
      agentfs_match: true,
      rag_chunks: 216,
      source_commit_short: "2f0819487bda",
      quality_status: "PASS",
      summary: "隐患闭环、行政处罚、风险组合案例卡片。",
      key_sections: ["重大隐患与未整改闭环案例", "行政处罚案例", "高风险企业风险组合案例"],
      data_sources: ["accident_cases_kb_rebuild_run.json", "公开检查/隐患/处罚/风险表"],
    },
    {
      filename: "预警历史经验与短期记忆摘要.md",
      type: "history_memory",
      highlight: "预警历史经验与短期记忆摘要",
      agentfs_match: true,
      rag_chunks: 9,
      source_commit_short: "2f0819487bda",
      quality_status: "PASS",
      summary: "保留历史经验摘要和记忆归档入口。",
      key_sections: ["历史经验摘要", "短期记忆摘要"],
      data_sources: ["memory/*.md", "AgentFS memory archive"],
    },
  ],
  agentfs: {
    snapshot_commit_id: "2f0819487bdaf2a8495f15c260015cbf932d29d3",
    snapshot_commit_short: "2f0819487bda",
    fs_agentfs_match: true,
    backup_path: "data/snapshots/agentfs_pre_kb_sync_20260510_175314.db",
    deprecated_entries: [
      { path: "/knowledge_base/预警历史经验与短期记忆摘?md", status_note: "deprecated_malformed_path" },
    ],
    deprecated_warning: "deprecated 乱码路径仍保留，按审计要求不在本轮删除",
    sync_script_name: "scripts/sync_kb_to_agentfs.py",
    db_path: "data/agentfs.db",
    agent_id: "kb_sync",
  },
  rag_index: {
    persist_directory: "data/chroma_db",
    collection_name: "knowledge_base",
    collection_count: 639,
    embedding_backend: "fallback",
    fallback_embedding_used: true,
    source_commit_short: "2f0819487bda",
  },
  memory_archives: [
    { path: "memory/风险事件归档.md", priority: "P1", strategy: "摘要归档", description: "沉淀已核验的风险事件摘要和复查线索。" },
    { path: "memory/核心指令归档.md", priority: "P0", strategy: "永久保留", description: "保存系统边界、禁止项和核心运行约束。" },
    { path: "memory/处置经验归档.md", priority: "P1", strategy: "摘要归档", description: "归档经过复盘的处置经验和现场操作注意事项。" },
    { path: "memory/系统日志归档.md", priority: "P2", strategy: "压缩保留", description: "保存可压缩的系统运行摘要和审计索引。" },
  ],
  audit_warnings: [
    "AgentFS deprecated 乱码路径仍保留",
    "当前仍使用 fallback embedding/reranker",
    "本地公开数据无法确认 A 类真实事故详案",
    "法条编号/标准条款需法务复核",
    "阈值需按企业设备/SDS/SOP 校准",
    "部门真实联系人仍需部署配置",
  ],
};

const DEMO_RAG_RESULTS: KnowledgeRagResult[] = [
  {
    source_file: "knowledge_base/企业已具备的执行条件.md",
    section_title: "粉尘涉爆执行条件",
    rule_id: "",
    sop_id: "",
    case_id: "",
    doc_type: "conditions",
    distance: 0.18,
    score: 0.82,
    matched_text: "企业存在粉尘涉爆标识、粉尘类型、干/湿式除尘系统数量、涉粉作业人数或除尘清扫记录任一证据，即纳入粉尘涉爆场景。",
  },
  {
    source_file: "knowledge_base/工业物理常识及传感器时间序列逻辑.md",
    section_title: "工况逻辑和时间序列规则表",
    rule_id: "PHY-DUST-002",
    sop_id: "",
    case_id: "",
    doc_type: "physics",
    distance: 0.24,
    score: 0.76,
    matched_text: "除尘系统压差、电流和粉尘浓度必须相互解释；粉尘浓度上升叠加风机电流下降或压差异常，应核查风机、滤袋、清灰和管道堵塞。",
  },
  {
    source_file: "knowledge_base/类似事故处理案例.md",
    section_title: "高风险企业风险组合案例",
    rule_id: "",
    sop_id: "",
    case_id: "D-008",
    doc_type: "cases",
    distance: 0.31,
    score: 0.69,
    matched_text: "粉尘涉爆风险组合：可燃性粉尘爆炸；风险点包含湿式除尘器，来源为公开数据风险表。",
  },
];

const MEMORY_RULES = [
  { priority: "P0", mechanism: "永久保留", lifecycle: "核心指令、边界条件、不可覆盖约束" },
  { priority: "P1", mechanism: "摘要归档", lifecycle: "高价值风险事件、复盘经验、可追溯摘要" },
  { priority: "P2", mechanism: "压缩", lifecycle: "运行日志、普通检索上下文、可再生成材料" },
  { priority: "P3", mechanism: "最先删除", lifecycle: "临时提示、中间草稿、低价值缓存" },
];

export default function KnowledgeMemoryPage() {
  const [activeTab, setActiveTab] = useState("overview");
  const [system, setSystem] = useState<KnowledgeSystemOverview>(FALLBACK_OVERVIEW);
  const [selectedKbName, setSelectedKbName] = useState(FALLBACK_OVERVIEW.knowledge_bases[0].filename);
  const [query, setQuery] = useState(PRESET_QUERIES[0]);
  const [ragResults, setRagResults] = useState<KnowledgeRagResult[]>(DEMO_RAG_RESULTS);
  const [ragMode, setRagMode] = useState("demo");
  const [ragLoading, setRagLoading] = useState(false);
  const [memoryStats, setMemoryStats] = useState<MemoryStatisticsResponse | null>(null);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryError, setMemoryError] = useState("");
  const [memoryModule, setMemoryModule] = useState<MemoryModule>("all");
  const [memoryPriority, setMemoryPriority] = useState<MemoryPriority | "">("");
  const [memoryKeyword, setMemoryKeyword] = useState("");
  const [memoryStart, setMemoryStart] = useState("");
  const [memoryEnd, setMemoryEnd] = useState("");
  const [memoryRiskType, setMemoryRiskType] = useState("");
  const [memoryOffset, setMemoryOffset] = useState(0);
  const memoryLimit = 25;

  useEffect(() => {
    fetchKnowledgeSystemOverview().then((payload) => {
      if (!payload) return;
      setSystem(payload);
      if (payload.knowledge_bases.length > 0) {
        setSelectedKbName(payload.knowledge_bases[0].filename);
      }
    });
  }, []);

  useEffect(() => {
    if (activeTab !== "memory") return;
    let cancelled = false;
    const params: MemoryStatisticsParams = {
      module: memoryModule,
      priority: memoryPriority,
      keyword: memoryKeyword,
      start_time: memoryStart,
      end_time: memoryEnd,
      risk_type: memoryRiskType,
      limit: memoryLimit,
      offset: memoryOffset,
    };
    async function load(refresh = false) {
      setMemoryLoading(true);
      const payload = await fetchMemoryStatistics({ ...params, refresh });
      if (cancelled) return;
      if (payload) {
        setMemoryStats(payload);
        setMemoryError("");
      } else {
        setMemoryError("记忆统计接口暂不可用");
      }
      setMemoryLoading(false);
    }
    load(false);
    const timer = window.setInterval(() => load(true), 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    activeTab,
    memoryModule,
    memoryPriority,
    memoryKeyword,
    memoryStart,
    memoryEnd,
    memoryRiskType,
    memoryOffset,
  ]);

  const selectedKb = useMemo(
    () =>
      system.knowledge_bases.find((item) => item.filename === selectedKbName) ??
      system.knowledge_bases[0],
    [selectedKbName, system.knowledge_bases],
  );

  async function runRagSearch(nextQuery = query) {
    const trimmed = nextQuery.trim();
    if (!trimmed) {
      setRagResults(DEMO_RAG_RESULTS);
      setRagMode("demo");
      return;
    }
    setQuery(trimmed);
    setRagLoading(true);
    const payload = await searchKnowledgeRag(trimmed, 6);
    if (payload && payload.results.length > 0) {
      setRagResults(payload.results);
      setRagMode(payload.mode || "chroma");
    } else {
      setRagResults(DEMO_RAG_RESULTS);
      setRagMode("demo");
    }
    setRagLoading(false);
  }

  return (
    <div className="knowledge-page">
      <div className="section-title">知识库与记忆系统</div>
      <Tabs tabs={SECTION_TABS} active={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && <OverviewPanel system={system} />}
      {activeTab === "kbs" && (
        <KnowledgeBasePanel
          items={system.knowledge_bases}
          selected={selectedKb}
          onSelect={setSelectedKbName}
        />
      )}
      {activeTab === "agentfs" && <AgentFSPanel system={system} />}
      {activeTab === "rag" && (
        <RagPanel
          query={query}
          onQueryChange={setQuery}
          onSearch={runRagSearch}
          results={ragResults}
          loading={ragLoading}
          mode={ragMode}
          system={system}
        />
      )}
      {activeTab === "memory" && (
        <MemoryPanel
          stats={memoryStats}
          loading={memoryLoading}
          error={memoryError}
          filters={{
            module: memoryModule,
            priority: memoryPriority,
            keyword: memoryKeyword,
            start: memoryStart,
            end: memoryEnd,
            riskType: memoryRiskType,
            offset: memoryOffset,
            limit: memoryLimit,
          }}
          onFilterChange={(patch) => {
            if (patch.module !== undefined) setMemoryModule(patch.module);
            if (patch.priority !== undefined) setMemoryPriority(patch.priority);
            if (patch.keyword !== undefined) setMemoryKeyword(patch.keyword);
            if (patch.start !== undefined) setMemoryStart(patch.start);
            if (patch.end !== undefined) setMemoryEnd(patch.end);
            if (patch.riskType !== undefined) setMemoryRiskType(patch.riskType);
            if (patch.offset !== undefined) setMemoryOffset(patch.offset);
            if (patch.offset === undefined) setMemoryOffset(0);
          }}
        />
      )}
      {activeTab === "audit" && <AuditPanel system={system} />}
    </div>
  );
}

function OverviewPanel({ system }: { system: KnowledgeSystemOverview }) {
  const overview = system.overview;
  return (
    <div>
      <div className="row cols-4">
        <ScadaCard
          title="审计状态"
          value={<span className="compact-card-value">{overview.audit_status}</span>}
          sub={`PASS/WARN/FAIL ${overview.pass_count}/${overview.warn_count}/${overview.fail_count}`}
          glowClass="glow-yellow"
        />
        <ScadaCard title="知识库文件数" value={overview.kb_file_count} sub="六个主知识库" glowClass="glow-green" />
        <ScadaCard title="RAG chunks" value={overview.rag_chunks} sub={system.rag_index.collection_name} glowClass="glow-blue" />
        <ScadaCard title="公开数据案例" value={overview.real_public_data_cases} sub="真实公开数据 B/C/D 类" glowClass="glow-green" />
      </div>
      <div className="row cols-4" style={{ marginTop: 12 }}>
        <ScadaCard title="COM/PHY/SOP 规则" value={overview.rule_count} sub="证据型规则" glowClass="glow-white" />
        <ScadaCard title="AgentFS 同步状态" value={<span className="compact-card-value">{overview.agentfs_sync_status}</span>} sub="FS 与 AgentFS 六库一致" glowClass="glow-green" />
        <ScadaCard title="Embedding backend" value={<span className="compact-card-value">{overview.embedding_backend}</span>} sub="deterministic fallback" glowClass="glow-orange" />
        <ScadaCard title="Source commit" value={<span className="compact-card-value">{system.rag_index.source_commit_short || "—"}</span>} sub="RAG / AgentFS snapshot" glowClass="glow-blue" />
      </div>

      <div className="knowledge-summary-band">
        <div>
          <div className="subtitle">当前边界</div>
          <p>
            本页只展示知识库、AgentFS、RAG 索引、P0-P3 记忆机制和审计结果。检索演示只读访问现有索引或 Markdown 证据，不触发同步、重建或正文改写。
          </p>
        </div>
        <div>
          <div className="subtitle">公开数据底座</div>
          <p>
            公开数据全量盘点已完成，企业执行条件库、案例库和三份规则库均已基于公开数据与证据锚点重建。
          </p>
        </div>
      </div>
    </div>
  );
}

function KnowledgeBasePanel({
  items,
  selected,
  onSelect,
}: {
  items: KnowledgeBaseStatus[];
  selected?: KnowledgeBaseStatus;
  onSelect: (filename: string) => void;
}) {
  return (
    <div className="row cols-2 knowledge-split">
      <div className="scada-table-wrap">
        <table className="scada-table dense kb-status-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>类型</th>
              <th>内容亮点</th>
              <th>AgentFS</th>
              <th>Chunks</th>
              <th>Commit</th>
              <th>质量</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.filename}
                className={item.filename === selected?.filename ? "selected-row" : ""}
                onClick={() => onSelect(item.filename)}
              >
                <td className="mono-cell">{item.filename}</td>
                <td>{item.type}</td>
                <td>{item.highlight}</td>
                <td><StatusBadge tone={item.agentfs_match ? "success" : "danger"} label={item.agentfs_match ? "match" : "diff"} /></td>
                <td className="mono-cell">{item.rag_chunks}</td>
                <td className="mono-cell">{item.source_commit_short || "—"}</td>
                <td><StatusBadge tone="success" label={item.quality_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="knowledge-detail-drawer">
        {selected ? (
          <>
            <div className="drawer-kicker">{selected.type}</div>
            <h3>{selected.filename}</h3>
            <p>{selected.summary}</p>
            <div className="detail-grid">
              <span>AgentFS</span><strong>{selected.agentfs_match ? "一致" : "存在差异"}</strong>
              <span>RAG chunks</span><strong>{selected.rag_chunks}</strong>
              <span>source_commit</span><strong>{selected.source_commit || selected.source_commit_short || "—"}</strong>
              <span>文件大小</span><strong>{selected.fs_size ? `${selected.fs_size} bytes` : "—"}</strong>
              <span>更新时间</span><strong>{selected.updated_at || "—"}</strong>
            </div>
            <div className="subtitle">关键章节</div>
            <div className="tag-cloud">
              {selected.key_sections.map((section) => <span key={section}>{section}</span>)}
            </div>
            <div className="subtitle">数据来源</div>
            <div className="tag-cloud muted">
              {selected.data_sources.map((source) => <span key={source}>{source}</span>)}
            </div>
          </>
        ) : (
          <div className="empty-state">请选择一个知识库</div>
        )}
      </div>
    </div>
  );
}

function AgentFSPanel({ system }: { system: KnowledgeSystemOverview }) {
  const agentfs = system.agentfs;
  return (
    <div>
      <div className="row cols-4">
        <ScadaCard title="Snapshot commit" value={<span className="compact-card-value">{agentfs.snapshot_commit_short || "—"}</span>} sub={agentfs.snapshot_commit_id} glowClass="glow-blue" />
        <ScadaCard title="FS / AgentFS" value={<span className="compact-card-value">{agentfs.fs_agentfs_match ? "match" : "diff"}</span>} sub="六库逐字节校验" glowClass={agentfs.fs_agentfs_match ? "glow-green" : "glow-orange"} />
        <ScadaCard title="Sync script" value={<span className="compact-card-value">{agentfs.sync_script_name}</span>} sub={agentfs.agent_id} glowClass="glow-white" />
        <ScadaCard title="Deprecated path" value={agentfs.deprecated_entries.length} sub="保留 warning" glowClass="glow-orange" />
      </div>

      <div className="row cols-2" style={{ marginTop: 12 }}>
        <div className="advice-card">
          <div className="advice-card-title">同步快照</div>
          <div className="detail-grid">
            <span>db_path</span><strong>{agentfs.db_path || "—"}</strong>
            <span>backup_path</span><strong>{agentfs.backup_path || "—"}</strong>
            <span>说明</span><strong>当前页面不提供写入或重新同步能力。</strong>
          </div>
          <button className="scada-btn secondary" type="button" disabled style={{ marginTop: 12 }}>
            重新同步不可用
          </button>
        </div>
        <div className="alert warning">
          {agentfs.deprecated_warning}
          <div className="mini-list">
            {agentfs.deprecated_entries.map((entry, index) => (
              <span key={index}>{String(entry.path ?? "deprecated_malformed_path")}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function RagPanel({
  query,
  onQueryChange,
  onSearch,
  results,
  loading,
  mode,
  system,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  onSearch: (value?: string) => void;
  results: KnowledgeRagResult[];
  loading: boolean;
  mode: string;
  system: KnowledgeSystemOverview;
}) {
  return (
    <div>
      <div className="row cols-3">
        <ScadaCard title="Collection" value={<span className="compact-card-value">{system.rag_index.collection_name}</span>} sub={system.rag_index.persist_directory} glowClass="glow-blue" />
        <ScadaCard title="Chunks" value={system.rag_index.collection_count} sub="正式 RAG 索引" glowClass="glow-green" />
        <ScadaCard title="Backend" value={<span className="compact-card-value">{system.rag_index.embedding_backend}</span>} sub={system.rag_index.fallback_embedding_used ? "fallback enabled" : "external embedding"} glowClass="glow-orange" />
      </div>

      <div className="preset-query-bar">
        {PRESET_QUERIES.map((item) => (
          <button
            key={item}
            type="button"
            className={`preset-query ${item === query ? "active" : ""}`}
            onClick={() => onSearch(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <div className="inline-search">
        <input
          className="scada-input"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="输入知识库检索词"
        />
        <button className="scada-btn" type="button" onClick={() => onSearch()} disabled={loading}>
          {loading ? "检索中..." : "检索"}
        </button>
      </div>
      <div className="table-caption">mode={mode}，结果字段来自 source_file / section_title / rule_id / sop_id / case_id / doc_type / distance / score。</div>

      <div className="scada-table-wrap">
        <table className="scada-table dense evidence-table">
          <thead>
            <tr>
              <th>source_file</th>
              <th>section_title</th>
              <th>ID</th>
              <th>doc_type</th>
              <th>score</th>
              <th>distance</th>
              <th>matched_text 摘要</th>
            </tr>
          </thead>
          <tbody>
            {results.map((item, index) => (
              <tr key={`${item.source_file}-${item.section_title}-${index}`}>
                <td className="mono-cell">{item.source_file}</td>
                <td>{item.section_title || "—"}</td>
                <td className="mono-cell">{item.rule_id || item.sop_id || item.case_id || "—"}</td>
                <td>{item.doc_type || "—"}</td>
                <td className="mono-cell">{formatNumber(item.score)}</td>
                <td className="mono-cell">{formatNumber(item.distance)}</td>
                <td>{item.matched_text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface MemoryFilterState {
  module: MemoryModule;
  priority: MemoryPriority | "";
  keyword: string;
  start: string;
  end: string;
  riskType: string;
  offset: number;
  limit: number;
}

function MemoryPanel({
  stats,
  loading,
  error,
  filters,
  onFilterChange,
}: {
  stats: MemoryStatisticsResponse | null;
  loading: boolean;
  error: string;
  filters: MemoryFilterState;
  onFilterChange: (patch: Partial<MemoryFilterState>) => void;
}) {
  const [view, setView] = useState<"short_term" | "long_term" | "warning_experience">("short_term");
  const exportParams: MemoryStatisticsParams = {
    module: filters.module,
    priority: filters.priority,
    keyword: filters.keyword,
    start_time: filters.start,
    end_time: filters.end,
    risk_type: filters.riskType,
  };
  const records = stats?.recent_records ?? [];
  const total = stats?.total_records ?? 0;
  const canPrev = filters.offset > 0;
  const canNext = filters.offset + filters.limit < total;

  async function runExport(format: "csv" | "xlsx" | "pdf") {
    await downloadMemoryExport(exportParams, format);
  }

  return (
    <div className="memory-dashboard">
      {error && <div className="alert error">{error}</div>}
      {loading && <div className="table-caption">正在刷新记忆统计...</div>}

      <div className="row cols-4 memory-kpi-grid">
        {(stats?.kpis ?? []).map((kpi) => (
          <ScadaCard
            key={kpi.key}
            title={kpi.label}
            value={<span className="compact-card-value">{String(kpi.value)}{kpi.unit ? ` ${kpi.unit}` : ""}</span>}
            sub={kpi.key === "last_write_time" ? "AgentFS operation_log" : stats?.generated_at}
            glowClass={kpi.status === "warning" ? "glow-orange" : kpi.status === "danger" ? "glow-red" : "glow-green"}
          />
        ))}
      </div>

      <div className="memory-filter-panel">
        <label>
          <span className="scada-label">模块</span>
          <select
            className="scada-select"
            value={filters.module}
            onChange={(event) => onFilterChange({ module: event.target.value as MemoryModule })}
          >
            <option value="all">全部</option>
            <option value="short_term">短期记忆</option>
            <option value="long_term">长期记忆</option>
            <option value="warning_experience">预警经验</option>
          </select>
        </label>
        <label>
          <span className="scada-label">优先级</span>
          <select
            className="scada-select"
            value={filters.priority}
            onChange={(event) => onFilterChange({ priority: event.target.value as MemoryPriority | "" })}
          >
            <option value="">全部</option>
            {MEMORY_RULES.map((item) => <option key={item.priority} value={item.priority}>{item.priority}</option>)}
          </select>
        </label>
        <label>
          <span className="scada-label">开始时间</span>
          <input className="scada-input" type="date" value={filters.start} onChange={(event) => onFilterChange({ start: event.target.value })} />
        </label>
        <label>
          <span className="scada-label">结束时间</span>
          <input className="scada-input" type="date" value={filters.end} onChange={(event) => onFilterChange({ end: event.target.value })} />
        </label>
        <label>
          <span className="scada-label">关键词</span>
          <input className="scada-input" value={filters.keyword} onChange={(event) => onFilterChange({ keyword: event.target.value })} placeholder="摘要、路径、metadata" />
        </label>
        <label>
          <span className="scada-label">风险类型</span>
          <input className="scada-input" value={filters.riskType} onChange={(event) => onFilterChange({ riskType: event.target.value })} placeholder="粉尘涉爆 / 危化品" />
        </label>
        <div className="memory-export-actions">
          <button className="scada-btn secondary" type="button" onClick={() => onFilterChange({ module: "all", priority: "", keyword: "", start: "", end: "", riskType: "", offset: 0 })}>
            清空筛选
          </button>
          <button className="scada-btn" type="button" onClick={() => runExport("csv")}>CSV</button>
          <button className="scada-btn" type="button" onClick={() => runExport("xlsx")}>Excel</button>
          <button className="scada-btn" type="button" onClick={() => runExport("pdf")}>PDF</button>
        </div>
      </div>

      <div className="memory-view-tabs">
        {[
          ["short_term", "短期记忆"],
          ["long_term", "长期记忆"],
          ["warning_experience", "预警经验"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`preset-query ${view === id ? "active" : ""}`}
            onClick={() => setView(id as "short_term" | "long_term" | "warning_experience")}
          >
            {label}
          </button>
        ))}
      </div>

      {stats ? (
        <>
          <div className="row cols-2">
            <MemoryTrendChart
              data={stats.charts.trend}
              onSeriesClick={(series) => {
                if (series === "short_term" || series === "long_term" || series === "warning_experience") {
                  onFilterChange({ module: series as MemoryModule });
                }
              }}
            />
            <MemoryHeatmapChart
              data={stats.charts.heatmap}
              onClick={(riskType, priority) => onFilterChange({ riskType, priority: priority as MemoryPriority })}
            />
          </div>

          {view === "short_term" && <ShortTermDashboard stats={stats} onFilterChange={onFilterChange} />}
          {view === "long_term" && <LongTermDashboard stats={stats} onFilterChange={onFilterChange} />}
          {view === "warning_experience" && <WarningExperienceDashboard stats={stats} onFilterChange={onFilterChange} />}

          <MemoryRecordsTable
            records={records}
            total={total}
            offset={filters.offset}
            limit={filters.limit}
            canPrev={canPrev}
            canNext={canNext}
            onPrev={() => onFilterChange({ offset: Math.max(0, filters.offset - filters.limit) })}
            onNext={() => onFilterChange({ offset: filters.offset + filters.limit })}
          />
        </>
      ) : (
        <div className="empty-state">等待记忆统计接口返回数据</div>
      )}
    </div>
  );
}

function ShortTermDashboard({
  stats,
  onFilterChange,
}: {
  stats: MemoryStatisticsResponse;
  onFilterChange: (patch: Partial<MemoryFilterState>) => void;
}) {
  const short = stats.short_term;
  const tokenRatio = short.token_limit ? Math.round((short.token_usage / short.token_limit) * 100) : 0;
  return (
    <div className="memory-subpanel">
      <div className="row cols-4">
        <ScadaCard title="短期记忆总数" value={short.total} sub="runtime ShortTermMemory" glowClass="glow-blue" />
        <ScadaCard title="Token 使用" value={`${short.token_usage}/${short.token_limit}`} sub={`${tokenRatio}% of limit`} glowClass={tokenRatio > 80 ? "glow-orange" : "glow-green"} />
        <ScadaCard title="P1 摘要/待归档" value={short.summary_count} sub={`待归档 ${short.p1_pending_archive}`} glowClass="glow-orange" />
        <ScadaCard title="压缩数量" value={short.compressed_count} sub="P2/P1 清理痕迹" glowClass="glow-white" />
      </div>
      <div className="row cols-2" style={{ marginTop: 12 }}>
        <MemoryBarChart
          title="P0-P3 优先级分布"
          data={Object.entries(short.priority_distribution).map(([name, value]) => ({ name, value }))}
          onClick={(name) => onFilterChange({ priority: name as MemoryPriority })}
        />
        <div className="scada-table-wrap">
          <table className="scada-table dense memory-rules-table">
            <thead>
              <tr><th>优先级</th><th>机制</th><th>生命周期</th></tr>
            </thead>
            <tbody>
              {MEMORY_RULES.map((item) => (
                <tr key={item.priority}>
                  <td><PriorityBadge priority={item.priority} /></td>
                  <td>{item.mechanism}</td>
                  <td>{item.lifecycle}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function LongTermDashboard({
  stats,
  onFilterChange,
}: {
  stats: MemoryStatisticsResponse;
  onFilterChange: (patch: Partial<MemoryFilterState>) => void;
}) {
  const fileBars = stats.long_term.files.map((item) => ({ name: item.label || item.path, value: item.entry_count }));
  return (
    <div className="memory-subpanel">
      <div className="row cols-2">
        <MemoryBarChart title="长期归档文件条目数" data={fileBars} onClick={(name) => onFilterChange({ keyword: name })} />
        <MemoryDonutChart
          title="长期记忆风险类型"
          data={Object.entries(stats.long_term.risk_type_distribution).map(([name, value]) => ({ name, value }))}
          onClick={(name) => onFilterChange({ riskType: name })}
        />
      </div>
      <div className="scada-table-wrap" style={{ marginTop: 12 }}>
        <table className="scada-table dense memory-archive-table">
          <thead>
            <tr>
              <th>归档文件</th>
              <th>优先级</th>
              <th>条目</th>
              <th>大小</th>
              <th>更新时间</th>
              <th>Checksum</th>
            </tr>
          </thead>
          <tbody>
            {stats.long_term.files.map((file) => (
              <tr key={file.path} onClick={() => onFilterChange({ keyword: file.label || file.path })}>
                <td className="mono-cell">{file.path}</td>
                <td>{file.priority ? <PriorityBadge priority={file.priority} /> : "—"}</td>
                <td className="mono-cell">{file.entry_count}</td>
                <td className="mono-cell">{formatBytes(file.size)}</td>
                <td className="mono-cell">{file.updated_at || "—"}</td>
                <td className="mono-cell">{file.checksum?.slice(0, 12) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WarningExperienceDashboard({
  stats,
  onFilterChange,
}: {
  stats: MemoryStatisticsResponse;
  onFilterChange: (patch: Partial<MemoryFilterState>) => void;
}) {
  return (
    <div className="memory-subpanel">
      <div className="row cols-4">
        <ScadaCard title="预警经验记录" value={stats.warning_experience.total} sub="历史经验 + 案例" glowClass="glow-orange" />
        <ScadaCard title="RAG 命中片段" value={stats.warning_experience.rag_hit_count} sub={`collection ${stats.warning_experience.rag_collection_count}`} glowClass="glow-blue" />
        <ScadaCard title="AgentFS WRITE" value={stats.agentfs_operations.counts.WRITE || 0} sub={stats.agentfs_operations.last_write_time || "无写入"} glowClass="glow-green" />
        <ScadaCard title="DELETE/SNAPSHOT" value={`${stats.agentfs_operations.counts.DELETE || 0}/${stats.agentfs_operations.counts.SNAPSHOT || 0}`} sub="operation_log" glowClass="glow-white" />
      </div>
      <div className="row cols-2" style={{ marginTop: 12 }}>
        <MemoryDonutChart
          title="预警经验类型"
          data={Object.entries(stats.warning_experience.type_distribution).map(([name, value]) => ({ name, value }))}
          onClick={(name) => onFilterChange({ keyword: name })}
        />
        <MemoryDonutChart
          title="风险类型占比"
          data={Object.entries(stats.warning_experience.risk_type_distribution).map(([name, value]) => ({ name, value }))}
          onClick={(name) => onFilterChange({ riskType: name })}
        />
      </div>
    </div>
  );
}

function MemoryRecordsTable({
  records,
  total,
  offset,
  limit,
  canPrev,
  canNext,
  onPrev,
  onNext,
}: {
  records: MemoryRecord[];
  total: number;
  offset: number;
  limit: number;
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="memory-records">
      <div className="memory-table-head">
        <div className="subtitle">明细记录</div>
        <div className="table-caption">第 {offset + 1}-{Math.min(offset + limit, total)} 条 / 共 {total} 条</div>
      </div>
      <div className="scada-table-wrap">
        <table className="scada-table dense memory-detail-table">
          <thead>
            <tr>
              <th>模块</th>
              <th>优先级</th>
              <th>风险类型</th>
              <th>来源 / 路径</th>
              <th>更新时间</th>
              <th>Token/Size</th>
              <th>关联度</th>
              <th>摘要</th>
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id}>
                <td>{moduleLabel(record.module)}</td>
                <td><PriorityBadge priority={record.priority} /></td>
                <td>{record.risk_type || "未标注"}</td>
                <td className="mono-cell">{record.source}<br />{record.path}</td>
                <td className="mono-cell">{record.updated_at || record.created_at || "—"}</td>
                <td className="mono-cell">{record.tokens ?? "—"} / {formatBytes(record.size)}</td>
                <td className="mono-cell">{formatNumber(record.association_score)}</td>
                <td>{record.summary || record.content}</td>
              </tr>
            ))}
            {records.length === 0 && (
              <tr>
                <td colSpan={8}><div className="empty-state">当前筛选没有匹配记录</div></td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="memory-pagination">
        <button className="scada-btn secondary" type="button" disabled={!canPrev} onClick={onPrev}>上一页</button>
        <button className="scada-btn secondary" type="button" disabled={!canNext} onClick={onNext}>下一页</button>
      </div>
    </div>
  );
}

function AuditPanel({ system }: { system: KnowledgeSystemOverview }) {
  return (
    <div>
      <div className="row cols-4">
        <ScadaCard title="总体结论" value={<span className="compact-card-value">{system.overview.audit_status}</span>} sub="知识库系统审计" glowClass="glow-yellow" />
        <ScadaCard title="PASS" value={system.overview.pass_count} glowClass="glow-green" />
        <ScadaCard title="WARN" value={system.overview.warn_count} glowClass="glow-orange" />
        <ScadaCard title="FAIL" value={system.overview.fail_count} glowClass="glow-green" />
      </div>
      <div className="warn-grid">
        {system.audit_warnings.map((warning) => (
          <div className="warn-item" key={warning}>
            <StatusBadge tone="warning" label="WARN" />
            <span>{warning}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ label, tone }: { label: string; tone: "success" | "warning" | "danger" }) {
  return <span className={`status-badge ${tone}`}>{label}</span>;
}

function PriorityBadge({ priority }: { priority: string }) {
  const tone = priority === "P0" ? "danger" : priority === "P1" ? "warning" : "success";
  return <span className={`status-badge ${tone}`}>{priority}</span>;
}

function moduleLabel(module: string): string {
  if (module === "short_term") return "短期记忆";
  if (module === "long_term") return "长期记忆";
  if (module === "warning_experience") return "预警经验";
  return module || "未知";
}

function formatBytes(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatNumber(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}
