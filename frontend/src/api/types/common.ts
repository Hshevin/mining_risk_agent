/**
 * 统一 API 契约类型（与后端 api/schemas/common.py 对齐）
 */

/** 业务错误详情 */
export interface ApiErrorBody {
  code: string;
  message: string;
  field?: string;
}

/** 统一响应信封（新接口推荐；历史接口可能直接返回 data） */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: ApiErrorBody;
  message?: string;
}

/** 分页数据载荷 */
export interface PaginatedData<T> {
  total: number;
  items: T[];
  offset: number;
  limit: number;
}

/** 分页列表响应 */
export type PaginatedResponse<T> = ApiResponse<PaginatedData<T>>;

/** 健康检查载荷 */
export interface HealthPayload {
  status: string;
  version?: string;
}
