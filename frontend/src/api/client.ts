/**
 * 统一 API 客户端
 * - 默认调用同源 `/api/v1/...` 与 `/health`，由前端容器内 Nginx 反向代理到后端
 * - 开发模式由 Vite proxy 代理到 FastAPI
 * - 可通过 VITE_API_BASE 环境变量覆盖（用于直接指向远程后端）
 */

import type {
  AuditLogEntry,
  DataUploadResponse,
  DatasetKind,
  DemoResetResponse,
  DecisionResponse,
  DemoBatch,
  DemoIterationStepResponse,
  DemoReplayLoadResponse,
  HealthResponse,
  IterationRecord,
  IterationStatus,
  IterationTimelineResponse,
  IterationTriggerResponse,
  KnowledgeRagSearchResponse,
  KnowledgeSystemOverview,
  IterationUploadBatchResponse,
  LLMConfigResponse,
  LLMProvider,
  LLMUpdateRequest,
  LongTermMemory,
  ModelEvaluationReport,
  NodeStatus,
  ScenarioSwitchResponse,
  ShortTermMemory,
  WarningLog,
} from "./types";
import {
  adminHeaders,
  apiBaseLabel,
  buildUrl,
  parseJsonOrThrow as jsonOrThrow,
} from "./http";

const url = buildUrl;

export async function fetchHealth(): Promise<HealthResponse> {
  try {
    const resp = await fetch(url("/health"), { method: "GET" });
    if (!resp.ok) return { status: "error", detail: `HTTP ${resp.status}` };
    return (await resp.json()) as HealthResponse;
  } catch (e) {
    return { status: "error", detail: (e as Error).message };
  }
}

export async function switchScenario(
  scenarioId: string,
): Promise<ScenarioSwitchResponse | null> {
  try {
    const resp = await fetch(url(`/api/v1/agent/scenario/${scenarioId}`), {
      method: "POST",
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as ScenarioSwitchResponse;
  } catch {
    return null;
  }
}

export async function fetchLLMConfig(): Promise<LLMConfigResponse | null> {
  try {
    const resp = await fetch(url("/api/v1/agent/llm"), {
      method: "GET",
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as LLMConfigResponse;
  } catch {
    return null;
  }
}

export async function switchLLMProvider(
  provider: LLMProvider,
): Promise<LLMConfigResponse | null> {
  try {
    const resp = await fetch(url(`/api/v1/agent/llm/${provider}`), {
      method: "POST",
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as LLMConfigResponse;
  } catch {
    return null;
  }
}

export async function updateLLMConfig(
  payload: LLMUpdateRequest,
): Promise<LLMConfigResponse | null> {
  try {
    const resp = await fetch(url("/api/v1/agent/llm"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as LLMConfigResponse;
  } catch {
    return null;
  }
}

export async function postDecision(
  enterpriseId: string,
  data: Record<string, unknown>,
  scenarioId?: string,
): Promise<DecisionResponse | null> {
  try {
    const resp = await fetch(url("/api/v1/agent/decision"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enterprise_id: enterpriseId, data, scenario_id: scenarioId }),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as DecisionResponse;
  } catch {
    return null;
  }
}

/**
 * SSE 流式决策接口（POST + text/event-stream）
 * 浏览器原生 EventSource 不支持 POST，因此用 fetch + ReadableStream 解析 `data:` 行
 */
export async function streamDecision(
  enterpriseId: string,
  data: Record<string, unknown>,
  onMessage: (msg: NodeStatus) => void,
  signal?: AbortSignal,
  scenarioId?: string,
): Promise<DecisionResponse | null> {
  const resp = await fetch(url("/api/v1/agent/decision/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enterprise_id: enterpriseId, data, scenario_id: scenarioId }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`SSE failed: HTTP ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalDecision: DecisionResponse | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const raw of lines) {
      const line = raw.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        const obj = JSON.parse(payload) as NodeStatus;
        if (obj.decision_response) finalDecision = obj.decision_response;
        onMessage(obj);
      } catch {
        // 忽略非 JSON 行
      }
    }
  }
  return finalDecision;
}

export async function uploadDataFile(
  file: File,
  enterpriseId?: string,
): Promise<DataUploadResponse | null> {
  try {
    const form = new FormData();
    form.append("file", file);
    if (enterpriseId) form.append("enterprise_id", enterpriseId);
    const resp = await fetch(url("/api/v1/data/upload"), {
      method: "POST",
      body: form,
    });
    if (!resp.ok) return null;
    return (await resp.json()) as DataUploadResponse;
  } catch {
    return null;
  }
}

export async function listKnowledge(): Promise<string[]> {
  try {
    const resp = await fetch(url("/api/v1/knowledge/list"));
    if (!resp.ok) return [];
    return (await resp.json()) as string[];
  } catch {
    return [];
  }
}

export async function readKnowledge(
  filename: string,
): Promise<string | null> {
  try {
    const resp = await fetch(
      url(`/api/v1/knowledge/read/${encodeURIComponent(filename)}`),
    );
    if (!resp.ok) return null;
    const j = (await resp.json()) as { content?: string };
    return j.content ?? "";
  } catch {
    return null;
  }
}

export async function fetchKnowledgeSystemOverview(): Promise<KnowledgeSystemOverview | null> {
  try {
    const resp = await fetch(url("/api/v1/knowledge/system/overview"));
    if (!resp.ok) return null;
    return (await resp.json()) as KnowledgeSystemOverview;
  } catch {
    return null;
  }
}

export async function searchKnowledgeRag(
  query: string,
  topK = 6,
): Promise<KnowledgeRagSearchResponse | null> {
  try {
    const usp = new URLSearchParams();
    usp.set("q", query);
    usp.set("top_k", String(topK));
    const resp = await fetch(url(`/api/v1/knowledge/rag/search?${usp.toString()}`));
    if (!resp.ok) return null;
    return (await resp.json()) as KnowledgeRagSearchResponse;
  } catch {
    return null;
  }
}

function appendParams(usp: URLSearchParams, params: Record<string, unknown>) {
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      usp.set(key, String(value));
    }
  });
}

export async function fetchMemoryStatistics(
  params: MemoryStatisticsParams = {},
): Promise<MemoryStatisticsResponse | null> {
  try {
    const usp = new URLSearchParams();
    appendParams(usp, params as Record<string, unknown>);
    const suffix = usp.toString();
    const resp = await fetch(url(`/api/v1/memory/statistics${suffix ? `?${suffix}` : ""}`));
    if (!resp.ok) return null;
    return (await resp.json()) as MemoryStatisticsResponse;
  } catch {
    return null;
  }
}

export async function downloadMemoryExport(
  params: MemoryStatisticsParams = {},
  format: "csv" | "xlsx" | "pdf" = "csv",
): Promise<void> {
  const usp = new URLSearchParams();
  appendParams(usp, { ...params, format });
  const resp = await fetch(url(`/api/v1/memory/export?${usp.toString()}`));
  if (!resp.ok) {
    throw new Error(await responseError(resp));
  }
  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const disposition = resp.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1];
  anchor.href = objectUrl;
  anchor.download = encoded ? decodeURIComponent(encoded) : `memory_${params.module || "all"}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function fetchIterationStatus(): Promise<IterationStatus | null> {
  try {
    const resp = await fetch(url("/api/v1/iteration/status"));
    if (!resp.ok) return null;
    return (await resp.json()) as IterationStatus;
  } catch {
    return null;
  }
}

export async function fetchDemoBatches(): Promise<DemoBatch[]> {
  return fetchJsonStrict<DemoBatch[]>("/api/v1/iteration/demo-batches");
}

export async function loadDemoBatch(
  batchId: string,
): Promise<DemoReplayLoadResponse | null> {
  return fetchJsonStrict<DemoReplayLoadResponse>(
    `/api/v1/iteration/demo-batches/${encodeURIComponent(batchId)}/load`,
    { method: "POST" },
  );
}

export async function fetchLatestIteration(): Promise<IterationRecord | null> {
  return fetchJsonNullable404<IterationRecord>("/api/v1/iteration/latest");
}

export async function fetchIterationRecord(
  iterationId: string,
): Promise<IterationRecord | null> {
  return fetchJsonNullable404<IterationRecord>(
    `/api/v1/iteration/${encodeURIComponent(iterationId)}`,
  );
}

export async function fetchIterationTimeline(
  iterationId: string,
): Promise<IterationTimelineResponse | null> {
  return fetchJsonNullable404<IterationTimelineResponse>(
    `/api/v1/iteration/${encodeURIComponent(iterationId)}/timeline`,
  );
}

export async function fetchBatchLatestIteration(
  batchId: string,
): Promise<IterationRecord | null> {
  return fetchJsonNullable404<IterationRecord>(
    `/api/v1/iteration/batches/${encodeURIComponent(batchId)}/latest-run`,
  );
}

export async function uploadIterationBatch(
  file: File,
  datasetKind: DatasetKind = "auto",
  recentF1Override?: string,
): Promise<IterationUploadBatchResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("dataset_kind", datasetKind);
  if (recentF1Override?.trim()) {
    form.append("recent_f1_override", recentF1Override.trim());
  }
  return fetchJsonStrict<IterationUploadBatchResponse>(
    "/api/v1/iteration/upload-batch",
    {
      method: "POST",
      body: form,
    },
  );
}

export async function resetIterationDemoState(): Promise<DemoResetResponse> {
  return fetchJsonStrict<DemoResetResponse>("/api/v1/iteration/demo/reset", {
    method: "POST",
  });
}

export type DemoIterationAction =
  | "train"
  | "regression-test"
  | "drift-analysis"
  | "pr/create"
  | "ci/run"
  | "approve/safety"
  | "approve/tech"
  | "staging/start"
  | "staging/complete-demo"
  | "canary/advance"
  | "demo/run-next-step"
  | "demo/run-to-end";

export async function runDemoIterationAction(
  iterationId: string,
  action: DemoIterationAction,
  body?: Record<string, unknown>,
): Promise<DemoIterationStepResponse> {
  return fetchJsonStrict<DemoIterationStepResponse>(
    `/api/v1/iteration/${encodeURIComponent(iterationId)}/${action}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
}

export async function fetchIterationAudit(
  iterationId: string,
): Promise<IterationAuditResponse | null> {
  return fetchJsonNullable404<IterationAuditResponse>(
    `/api/v1/iteration/${encodeURIComponent(iterationId)}/audit`,
  );
}

export async function fetchIterationReports(
  iterationId: string,
): Promise<IterationReportsResponse | null> {
  return fetchJsonNullable404<IterationReportsResponse>(
    `/api/v1/iteration/${encodeURIComponent(iterationId)}/reports`,
  );
}

export async function fetchIterationReport(
  iterationId: string,
  reportType: string,
): Promise<IterationReportResponse | null> {
  return fetchJsonNullable404<IterationReportResponse>(
    `/api/v1/iteration/${encodeURIComponent(iterationId)}/reports/${encodeURIComponent(reportType)}`,
  );
}

export async function downloadIterationReport(
  iterationId: string,
  reportType: string,
): Promise<void> {
  const resp = await fetch(
    url(
      `/api/v1/iteration/${encodeURIComponent(iterationId)}/reports/${encodeURIComponent(
        reportType,
      )}/download`,
    ),
  );
  if (!resp.ok) {
    throw new Error(await responseError(resp));
  }
  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = `${iterationId}_${reportType}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function triggerIteration(): Promise<IterationTriggerResponse | null> {
  try {
    const resp = await fetch(url("/api/v1/iteration/trigger"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({}),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as IterationTriggerResponse;
  } catch {
    return null;
  }
}

export async function queryAudit(
  params: Partial<{
    event_type: string;
    enterprise_id: string;
    risk_level: string;
    limit: number;
    offset: number;
  }>,
): Promise<AuditLogEntry[]> {
  try {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/audit/query?${usp.toString()}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return [];
    return jsonOrThrow<AuditLogEntry[]>(resp);
  } catch {
    return [];
  }
}

export async function deleteShortTermMemory(id: string): Promise<boolean> {
  try {
    const resp = await fetch(url(`/api/v1/memory/short-term/${encodeURIComponent(id)}`), {
      method: "DELETE",
      headers: adminHeaders(),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

export async function migrateToLongTerm(shortTermIds: string[]): Promise<any[]> {
  try {
    const resp = await fetch(url("/api/v1/memory/migrate"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ short_term_ids: shortTermIds }),
    });
    if (!resp.ok) return [];
    return jsonOrThrow<any[]>(resp);
  } catch {
    return [];
  }
}

export async function importEnterpriseData(
  source: "folder" | "file",
  _path?: string,
  file?: File,
): Promise<DataUploadResponse | null> {
  try {
    if (source === "file" && file) return importExcelFile(file);
    const resp = await fetch(url("/api/v1/memory/import-new-data"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
    });
    if (!resp.ok) return null;
    const data = await jsonOrThrow<{
      success: boolean;
      message: string;
      files_imported: number;
      total_rows: number;
      details: Array<Record<string, unknown>>;
    }>(resp);
    return {
      success: data.success,
      message: data.message,
      rows: data.total_rows,
      columns: data.files_imported,
      preview: data.details,
    };
  } catch {
    return null;
  }
}

export async function importExcelFile(file: File, enterpriseId?: string): Promise<DataUploadResponse | null> {
  const form = new FormData();
  form.append("file", file);
  if (enterpriseId) form.append("enterprise_id", enterpriseId);
  const resp = await fetch(url("/api/v1/memory/import-excel"), { method: "POST", body: form });
  if (!resp.ok) throw new Error(await responseError(resp));
  const data = await resp.json() as {
    success: boolean;
    message: string;
    rows: number;
    columns: number;
    preview?: Array<Record<string, unknown>>;
  };
  return { success: data.success, message: data.message, rows: data.rows, columns: data.columns, preview: data.preview };
}

export async function assessEnterpriseFile(file: File): Promise<{
  success: boolean;
  message: string;
  filename: string;
  total_rows: number;
  results: any[];
} | null> {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(url("/api/v1/memory/assess-enterprise"), { method: "POST", body: form });
  if (!resp.ok) throw new Error(await responseError(resp));
  return (await resp.json()) as {
    success: boolean;
    message: string;
    filename: string;
    total_rows: number;
    results: any[];
  };
}

export async function batchRiskAssessment(): Promise<{
  success: boolean;
  message: string;
  results: any[];
  inference_count: number;
} | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/batch-assess"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchEnterpriseDataSummary(): Promise<{
  total_entries: number;
  table_count: number;
  sources: string[];
  enterprise_names: string[];
  enterprise_count: number;
} | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/enterprise-data-summary"), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchMemoryStats(): Promise<{
  short_term: { total: number; by_category: Record<string, number>; by_priority: Record<string, number>; by_enterprise: Record<string, number>; timeline: Record<string, number> };
  long_term: { total: number; by_category: Record<string, number>; by_priority: Record<string, number>; by_source: Record<string, number>; by_enterprise: Record<string, number>; timeline: Record<string, number>; verified_count: number };
  warning_experiences: { total: number; by_level: Record<string, number>; by_scenario: Record<string, number>; financial_total: number; timeline: Record<string, number> };
  iteration_count: number;
  pending_approvals: number;
  audit_log_count: number;
} | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/stats"), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchWarningExperiences(params: Partial<{
  enterprise_id: string;
  risk_level: string;
  search: string;
  sort_by: string;
  sort_order: string;
  limit: number;
  offset: number;
}> = {}): Promise<{ total: number; items: any[]; offset: number; limit: number } | null> {
  try {
    const usp = new URLSearchParams();
    appendParams(usp, params);
    const resp = await fetch(url(`/api/v1/memory/warning-experiences?${usp.toString()}`), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchEnterpriseRiskHistory(enterpriseId: string): Promise<{
  enterprise_id: string;
  history: Array<Record<string, unknown>>;
  total: number;
} | null> {
  try {
    const resp = await fetch(url(`/api/v1/memory/enterprise-risk-history/${encodeURIComponent(enterpriseId)}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchIterationTracking(): Promise<{
  history: Array<{
    version: string;
    timestamp: number;
    time: string;
    accuracy: number;
    precision: number;
    recall: number;
    f1_score: number;
    false_positive_rate: number;
    false_negative_rate: number;
    samples: number;
    improvements: string[];
    status: string;
  }>;
  latest: any;
  total_iterations: number;
} | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/iteration-tracking"), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchApprovals(params: Partial<{ status: string; limit: number; offset: number }> = {}): Promise<{
  total: number;
  items: any[];
  offset: number;
  limit: number;
} | null> {
  try {
    const usp = new URLSearchParams();
    appendParams(usp, params);
    const resp = await fetch(url(`/api/v1/memory/approvals?${usp.toString()}`), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function decideApproval(
  approvalId: string,
  decision: string,
  actor = "admin",
  comment = "",
): Promise<any | null> {
  try {
    const usp = new URLSearchParams({ decision, actor, comment });
    const resp = await fetch(url(`/api/v1/memory/approvals/${encodeURIComponent(approvalId)}/decide?${usp.toString()}`), {
      method: "POST",
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchAuditLogs(params: Partial<{
  action: string;
  actor: string;
  search: string;
  limit: number;
  offset: number;
}> = {}): Promise<{ total: number; items: any[]; offset: number; limit: number } | null> {
  try {
    const usp = new URLSearchParams();
    appendParams(usp, params);
    const resp = await fetch(url(`/api/v1/memory/audit-logs?${usp.toString()}`), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function exportMemoryData(payload: {
  memory_type: string;
  format: string;
  filters?: Record<string, any>;
  selected_ids?: string[];
  time_from?: number;
  time_to?: number;
}): Promise<Blob | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/export"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    return await resp.blob();
  } catch {
    return null;
  }
}

export async function queryShortTermMemoryPaginated(params: Partial<{
  enterprise_id: string;
  category: string;
  priority: string;
  search: string;
  tags: string;
  sort_by: string;
  sort_order: string;
  limit: number;
  offset: number;
}> = {}): Promise<{ total: number; items: any[]; offset: number; limit: number } | null> {
  try {
    const usp = new URLSearchParams();
    appendParams(usp, params);
    const resp = await fetch(url(`/api/v1/memory/short-term?${usp.toString()}`), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function queryLongTermMemoryPaginated(params: Partial<{
  enterprise_id: string;
  category: string;
  priority: string;
  search: string;
  data_source: string;
  tags: string;
  sort_by: string;
  sort_order: string;
  limit: number;
  offset: number;
}> = {}): Promise<{ total: number; items: any[]; offset: number; limit: number } | null> {
  try {
    const usp = new URLSearchParams();
    appendParams(usp, params);
    const resp = await fetch(url(`/api/v1/memory/long-term?${usp.toString()}`), { headers: adminHeaders() });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export const apiBase = API_BASE || "(同源)";
