/**
 * 统一 HTTP 传输层
 *
 * 封装 base URL、管理令牌与 JSON 解析，供上层 API 服务函数复用。
 */

import type { ApiErrorBody, ApiResponse } from "./types/common";

const RAW_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
/** 去掉末尾斜杠以保证路径拼接稳定 */
export const API_BASE = RAW_BASE.replace(/\/$/, "");
const ADMIN_TOKEN = (import.meta.env.VITE_ADMIN_API_TOKEN as string | undefined) ?? "";

/**
 * 拼接完整请求 URL。
 *
 * @param path - 以 `/` 开头的相对路径或绝对 URL
 */
export function buildUrl(path: string): string {
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

/**
 * 构造带管理令牌的请求头。
 *
 * @param extra - 额外请求头
 */
export function adminHeaders(extra?: HeadersInit): HeadersInit {
  return ADMIN_TOKEN ? { ...extra, "X-Admin-Token": ADMIN_TOKEN } : { ...extra };
}

/**
 * 解析 JSON 响应，非 2xx 时抛出包含状态码与正文的 Error。
 *
 * @param resp - fetch 返回的 Response
 * @throws Error 当 HTTP 状态非成功时
 */
export async function parseJsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status} ${resp.statusText} ${text}`);
  }
  return (await resp.json()) as T;
}

/**
 * 尝试将错误响应解析为统一 ApiResponse 信封。
 */
export async function parseApiError(resp: Response): Promise<ApiErrorBody | null> {
  try {
    const body = (await resp.json()) as ApiResponse<unknown>;
    if (body && body.success === false && body.error) {
      return body.error;
    }
  } catch {
    // 非 JSON 或旧格式错误体
  }
  return null;
}

/**
 * 通用 GET JSON 请求。
 */
export async function getJson<T>(
  path: string,
  options?: { admin?: boolean; params?: Record<string, string | number | undefined> },
): Promise<T> {
  const usp = new URLSearchParams();
  if (options?.params) {
    Object.entries(options.params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
    });
  }
  const qs = usp.toString();
  const resp = await fetch(buildUrl(qs ? `${path}?${qs}` : path), {
    method: "GET",
    headers: options?.admin ? adminHeaders() : undefined,
  });
  return parseJsonOrThrow<T>(resp);
}

/**
 * 通用 POST JSON 请求。
 */
export async function postJson<T>(
  path: string,
  body?: unknown,
  options?: { admin?: boolean },
): Promise<T> {
  const resp = await fetch(buildUrl(path), {
    method: "POST",
    headers: options?.admin
      ? adminHeaders({ "Content-Type": "application/json" })
      : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parseJsonOrThrow<T>(resp);
}

export const apiBaseLabel = API_BASE || "(同源)";

/** 将失败响应转为可读错误信息。 */
export async function responseError(resp: Response): Promise<string> {
  const apiErr = await parseApiError(resp);
  if (apiErr?.message) return apiErr.message;
  const text = await resp.text().catch(() => "");
  return `HTTP ${resp.status} ${resp.statusText}${text ? ` ${text}` : ""}`;
}

type FetchJsonOptions = RequestInit & { admin?: boolean };

/** GET/POST JSON，非 2xx 时抛出 Error。 */
export async function fetchJsonStrict<T>(
  path: string,
  options: FetchJsonOptions = {},
): Promise<T> {
  const { admin, headers, ...rest } = options;
  const resp = await fetch(buildUrl(path), {
    ...rest,
    headers: admin ? adminHeaders(headers) : headers,
  });
  if (!resp.ok) {
    throw new Error(await responseError(resp));
  }
  return (await resp.json()) as T;
}

/** GET JSON；404 返回 null，其它非 2xx 抛出 Error。 */
export async function fetchJsonNullable404<T>(path: string): Promise<T | null> {
  const resp = await fetch(buildUrl(path), { method: "GET" });
  if (resp.status === 404) return null;
  if (!resp.ok) {
    throw new Error(await responseError(resp));
  }
  return (await resp.json()) as T;
}
