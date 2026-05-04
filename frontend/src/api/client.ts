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
  IterationStatus,
  IterationTriggerResponse,
  LLMConfigResponse,
  LLMProvider,
  LLMUpdateRequest,
  NodeStatus,
  ScenarioSwitchResponse,
} from "./types";

const RAW_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
// 去掉末尾斜杠以保证拼接稳定
const API_BASE = RAW_BASE.replace(/\/$/, "");

function url(path: string): string {
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status} ${resp.statusText} ${text}`);
  }
  return (await resp.json()) as T;
}

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
    });
    if (!resp.ok) return null;
    return (await resp.json()) as ScenarioSwitchResponse;
  } catch {
    return null;
  }
}

export async function fetchLLMConfig(): Promise<LLMConfigResponse | null> {
  try {
    const resp = await fetch(url("/api/v1/agent/llm"), { method: "GET" });
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
      headers: { "Content-Type": "application/json" },
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
): Promise<DecisionResponse | null> {
  try {
    const resp = await fetch(url("/api/v1/agent/decision"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enterprise_id: enterpriseId, data }),
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
): Promise<void> {
  const resp = await fetch(url("/api/v1/agent/decision/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enterprise_id: enterpriseId, data }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`SSE failed: HTTP ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
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
        onMessage(obj);
      } catch {
        // 忽略非 JSON 行
      }
    }
  }
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
      headers: { "Content-Type": "application/json" },
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
    const resp = await fetch(url(`/api/v1/audit/query?${usp.toString()}`));
    if (!resp.ok) return [];
    return jsonOrThrow<AuditLogEntry[]>(resp);
  } catch {
    return [];
  }
}

export const apiBase = API_BASE || "(同源)";
