/**
 * 统一 API 客户端
 * - 默认调用同源 `/api/v1/...` 与 `/health`，由前端容器内 Nginx 反向代理到后端
 * - 开发模式由 Vite proxy 代理到 FastAPI
 * - 可通过 VITE_API_BASE 环境变量覆盖（用于直接指向远程后端）
 */

import type {
  AuditLogEntry,
  DataUploadResponse,
  DecisionResponse,
  HealthResponse,
  IterationRecord,
  IterationStatus,
  IterationTriggerResponse,
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

export async function fetchIterationStatus(): Promise<IterationStatus | null> {
  try {
    const resp = await fetch(url("/api/v1/iteration/status"));
    if (!resp.ok) return null;
    return (await resp.json()) as IterationStatus;
  } catch {
    return null;
  }
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

export async function queryShortTermMemory(
  params: Partial<{
    enterprise_id: string;
    category: string;
    priority: string;
    search: string;
    time_from: number;
    time_to: number;
    limit: number;
    offset: number;
  }>,
): Promise<ShortTermMemory[]> {
  try {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/memory/short-term?${usp.toString()}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return [];
    return jsonOrThrow<ShortTermMemory[]>(resp);
  } catch {
    return [];
  }
}

export async function addShortTermMemory(
  payload: Omit<ShortTermMemory, "id" | "time" | "timestamp">,
): Promise<ShortTermMemory | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/short-term"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    return jsonOrThrow<ShortTermMemory>(resp);
  } catch {
    return null;
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

export async function queryLongTermMemory(
  params: Partial<{
    enterprise_id: string;
    category: string;
    priority: string;
    search: string;
    limit: number;
    offset: number;
  }>,
): Promise<LongTermMemory[]> {
  try {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/memory/long-term?${usp.toString()}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return [];
    return jsonOrThrow<LongTermMemory[]>(resp);
  } catch {
    return [];
  }
}

export async function addLongTermMemory(
  payload: Omit<LongTermMemory, "id" | "time" | "timestamp">,
): Promise<LongTermMemory | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/long-term"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    return jsonOrThrow<LongTermMemory>(resp);
  } catch {
    return null;
  }
}

export async function migrateToLongTerm(
  shortTermIds: string[],
): Promise<LongTermMemory[]> {
  try {
    const resp = await fetch(url("/api/v1/memory/migrate"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ short_term_ids: shortTermIds }),
    });
    if (!resp.ok) return [];
    return jsonOrThrow<LongTermMemory[]>(resp);
  } catch {
    return [];
  }
}

export async function queryWarningLogs(
  params: Partial<{
    enterprise_id: string;
    risk_level: string;
    status: string;
    time_from: number;
    time_to: number;
    limit: number;
    offset: number;
  }>,
): Promise<WarningLog[]> {
  try {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/warning/logs?${usp.toString()}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return [];
    return jsonOrThrow<WarningLog[]>(resp);
  } catch {
    return [];
  }
}

export async function resolveWarningLog(
  id: string,
  resolution: string,
): Promise<WarningLog | null> {
  try {
    const resp = await fetch(url(`/api/v1/warning/logs/${encodeURIComponent(id)}/resolve`), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ resolution }),
    });
    if (!resp.ok) return null;
    return jsonOrThrow<WarningLog>(resp);
  } catch {
    return null;
  }
}

export async function importEnterpriseData(
  source: "folder" | "file",
  path?: string,
  file?: File,
): Promise<DataUploadResponse | null> {
  try {
    if (source === "file" && file) {
      return importExcelFile(file);
    }
    const resp = await fetch(url("/api/v1/memory/import-new-data"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
    });
    if (!resp.ok) return null;
    const data = await jsonOrThrow<{
      success: boolean;
      message: string;
      files_scanned: number;
      files_imported: number;
      total_rows: number;
      total_entries: number;
      details: Array<Record<string, unknown>>;
    }>(resp);
    return {
      success: data.success,
      message: data.message,
      rows: data.total_rows,
      columns: data.files_imported,
      preview: data.details as unknown as Array<Record<string, unknown>>,
    };
  } catch {
    return null;
  }
}

export async function importExcelFile(
  file: File,
  enterpriseId?: string,
): Promise<DataUploadResponse | null> {
  try {
    const form = new FormData();
    form.append("file", file);
    if (enterpriseId) form.append("enterprise_id", enterpriseId);
    const resp = await fetch(url("/api/v1/memory/import-excel"), {
      method: "POST",
      body: form,
    });
    
    const text = await resp.text();
    if (!resp.ok) {
      console.error("Excel导入失败:", resp.status, text);
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    
    const data = JSON.parse(text) as {
      success: boolean;
      message: string;
      filename: string;
      rows: number;
      columns: number;
      entries_stored: number;
      preview?: Array<Record<string, unknown>>;
    };
    
    return {
      success: data.success,
      message: data.message,
      rows: data.rows,
      columns: data.columns,
      preview: data.preview,
    };
  } catch (e) {
    console.error("importExcelFile异常:", e);
    throw e;
  }
}

export async function assessEnterpriseFile(
  file: File,
): Promise<{
  success: boolean;
  message: string;
  filename: string;
  total_rows: number;
  results: Array<{
    enterprise_id: string;
    enterprise_name: string;
    risk_score: number;
    risk_level: string;
    scenario: string;
    assessment_time: string;
    key_factors: Array<{ name: string; value: number; color: string }>;
    inference_stored: boolean;
  }>;
} | null> {
  try {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(url("/api/v1/memory/assess-enterprise"), {
      method: "POST",
      body: form,
    });
    
    const text = await resp.text();
    if (!resp.ok) {
      console.error("预测分析失败:", resp.status, text);
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    
    return JSON.parse(text);
  } catch (e) {
    console.error("assessEnterpriseFile异常:", e);
    throw e;
  }
}

export async function batchRiskAssessment(): Promise<{
  success: boolean;
  message: string;
  results: Array<{
    enterprise_id: string;
    enterprise_name: string;
    risk_score: number;
    risk_level: string;
    scenario: string;
    assessment_time: string;
    key_factors: Array<{ name: string; value: number; color: string }>;
    inference_stored: boolean;
  }>;
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
    const resp = await fetch(url("/api/v1/memory/enterprise-data-summary"), {
      headers: adminHeaders(),
    });
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
    const resp = await fetch(url("/api/v1/memory/stats"), {
      headers: adminHeaders(),
    });
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
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/memory/warning-experiences?${usp.toString()}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchEnterpriseRiskHistory(enterpriseId: string): Promise<{
  enterprise_id: string;
  history: Array<{
    time: string;
    timestamp: number;
    risk_score: number;
    risk_level: string;
    scenario: string;
    key_factors: Array<{ name: string; value: number; color: string }>;
  }>;
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
    const resp = await fetch(url("/api/v1/memory/iteration-tracking"), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function fetchApprovals(params: Partial<{
  status: string;
  limit: number;
  offset: number;
}> = {}): Promise<{ total: number; items: any[]; offset: number; limit: number } | null> {
  try {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/memory/approvals?${usp.toString()}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function createApproval(payload: {
  target_id: string;
  action: string;
  actor?: string;
  comment?: string;
}): Promise<any | null> {
  try {
    const resp = await fetch(url("/api/v1/memory/approvals"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function decideApproval(
  approvalId: string,
  decision: string,
  actor: string = "admin",
  comment: string = "",
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
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/memory/audit-logs?${usp.toString()}`), {
      headers: adminHeaders(),
    });
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
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/memory/short-term?${usp.toString()}`), {
      headers: adminHeaders(),
    });
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
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
    const resp = await fetch(url(`/api/v1/memory/long-term?${usp.toString()}`), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return null;
    return jsonOrThrow(resp);
  } catch {
    return null;
  }
}

export async function generateModelEvaluation(): Promise<ModelEvaluationReport | null> {
  try {
    const resp = await fetch(url("/api/v1/model/evaluate"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
    });
    if (!resp.ok) return null;
    return jsonOrThrow<ModelEvaluationReport>(resp);
  } catch {
    return null;
  }
}

export async function listIterationRecords(): Promise<IterationRecord[]> {
  try {
    const resp = await fetch(url("/api/v1/iteration/records"), {
      headers: adminHeaders(),
    });
    if (!resp.ok) return [];
    return jsonOrThrow<IterationRecord[]>(resp);
  } catch {
    return [];
  }
}

export async function createIterationRecord(
  payload: Partial<IterationRecord>,
): Promise<IterationRecord | null> {
  try {
    const resp = await fetch(url("/api/v1/iteration/records"), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return null;
    return jsonOrThrow<IterationRecord>(resp);
  } catch {
    return null;
  }
}

export async function approveIteration(
  id: string,
  approver: string,
  comment: string,
  approved: boolean,
): Promise<IterationRecord | null> {
  try {
    const resp = await fetch(url(`/api/v1/iteration/records/${encodeURIComponent(id)}/approve`), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ approver, comment, approved }),
    });
    if (!resp.ok) return null;
    return jsonOrThrow<IterationRecord>(resp);
  } catch {
    return null;
  }
}

export async function promoteIteration(
  id: string,
  targetStatus: IterationRecord["status"],
): Promise<IterationRecord | null> {
  try {
    const resp = await fetch(url(`/api/v1/iteration/records/${encodeURIComponent(id)}/promote`), {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ target_status: targetStatus }),
    });
    if (!resp.ok) return null;
    return jsonOrThrow<IterationRecord>(resp);
  } catch {
    return null;
  }
}

export const apiBase = apiBaseLabel;
