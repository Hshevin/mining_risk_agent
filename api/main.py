"""
FastAPI 主应用
提供异步接口服务
"""

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.routers import audit, data, iteration, knowledge, prediction
from api.routers.prediction import agent_router
from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


def _get_cors_origins() -> List[str]:
    raw = os.getenv(
        "MRA_CORS_ORIGINS",
        "http://localhost:8501,http://127.0.0.1:8501,http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    config = get_config()
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(f"{config.project.name} v{config.project.version} 启动中...")
        yield
        logger.info("应用关闭")
    
    app = FastAPI(
        title=config.project.name,
        version=config.project.version,
        docs_url=config.api.docs_url,
        openapi_url=config.api.openapi_url,
        lifespan=lifespan,
    )
    
    cors_origins = _get_cors_origins()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials="*" not in cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由
    app.include_router(data.router, prefix="/api/v1/data", tags=["数据管理"])
    app.include_router(prediction.router, prefix="/api/v1/prediction", tags=["风险预测"])
    app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["知识库"])
    app.include_router(audit.router, prefix="/api/v1/audit", tags=["审计日志"])
    app.include_router(agent_router, prefix="/api/v1/agent", tags=["决策智能体"])
    app.include_router(iteration.router, prefix="/api/v1/iteration", tags=["模型迭代"])
    
    @app.get("/health")
    async def health_check() -> Dict[str, str]:
        return {"status": "healthy", "version": config.project.version}
    
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    config = get_config()
    uvicorn.run(
        "api.main:app",
        host=config.api.host,
        port=config.api.port,
        reload=config.api.reload,
        workers=config.api.workers,
    )
