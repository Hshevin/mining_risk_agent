"""
全局异常处理器

将业务异常映射为统一的 HTTP 响应结构，便于前端与监控消费。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mining_risk_serve.api.schemas.common import ErrorDetail, fail
from mining_risk_common.utils.exceptions import MiningRiskAgentException
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册统一异常处理器。

    Args:
        app: FastAPI 应用实例。
    """

    @app.exception_handler(MiningRiskAgentException)
    async def mining_risk_agent_handler(
        request: Request,
        exc: MiningRiskAgentException,
    ) -> JSONResponse:
        logger.warning("业务异常 %s %s: %s", request.method, request.url.path, exc)
        body = fail(code=exc.__class__.__name__, message=str(exc))
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        logger.warning("请求校验失败 %s: %s", request.url.path, exc.errors())
        body = fail(
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
        )
        return JSONResponse(status_code=422, content=body.model_dump())

