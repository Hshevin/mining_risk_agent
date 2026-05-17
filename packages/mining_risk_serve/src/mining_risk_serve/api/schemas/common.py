"""
统一 API 契约模型（通用响应与分页）

所有路由层应优先使用本模块定义的响应结构，以保持前后端接口一致。
"""

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
  """业务错误详情。

  Attributes:
      code: 机器可读错误码，如 ``VALIDATION_ERROR``。
      message: 面向调用方的人类可读说明。
      field: 可选，出错的请求字段名。
  """

  code: str = Field(..., description="错误码")
  message: str = Field(..., description="错误说明")
  field: Optional[str] = Field(default=None, description="关联字段")


class ApiResponse(BaseModel, Generic[T]):
  """统一成功/失败响应信封。

  新接口推荐使用 ``success + data/error`` 结构；历史接口可保持直接返回
  ``data`` 模型以兼容现有前端。

  Attributes:
      success: 请求是否成功。
      data: 成功时的业务载荷。
      error: 失败时的错误详情。
      message: 可选的补充说明。
  """

  success: bool = Field(..., description="是否成功")
  data: Optional[T] = Field(default=None, description="业务数据")
  error: Optional[ErrorDetail] = Field(default=None, description="错误信息")
  message: str = Field(default="", description="附加说明")


class PaginatedData(BaseModel, Generic[T]):
  """分页数据载荷。

  Attributes:
      total: 符合条件的总记录数。
      items: 当前页记录列表。
      offset: 当前偏移量。
      limit: 每页条数上限。
  """

  total: int = Field(..., ge=0, description="总记录数")
  items: List[T] = Field(default_factory=list, description="当前页数据")
  offset: int = Field(default=0, ge=0, description="偏移量")
  limit: int = Field(default=50, ge=1, description="每页条数")


class PaginatedResponse(ApiResponse[PaginatedData[T]], Generic[T]):
  """分页列表的统一响应信封。"""

  pass


class HealthPayload(BaseModel):
  """健康检查载荷。"""

  status: str = Field(..., description="服务状态，如 healthy")
  version: str = Field(default="", description="应用版本号")


def ok(data: T, message: str = "") -> ApiResponse[T]:
  """构造成功响应。

  Args:
      data: 业务数据。
      message: 可选说明。

  Returns:
      填充了 ``success=True`` 的 ``ApiResponse``。
  """
  return ApiResponse(success=True, data=data, message=message)


def fail(code: str, message: str, field: Optional[str] = None) -> ApiResponse[Any]:
  """构造失败响应。

  Args:
      code: 错误码。
      message: 错误说明。
      field: 可选关联字段。

  Returns:
      填充了 ``success=False`` 的 ``ApiResponse``。
  """
  return ApiResponse(
    success=False,
    error=ErrorDetail(code=code, message=message, field=field),
  )
