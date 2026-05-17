"""
审计日志路由
查询全流程审计记录
"""

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from mining_risk_serve.api.schemas.audit import AuditLogEntry, AuditLogRequest
from mining_risk_serve.api.security import require_admin_token
from mining_risk_common.utils.config import get_config
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _get_audit_db() -> str:
    """获取审计 SQLite 数据库路径。"""
    config = get_config()
    return config.audit.db_path


def _init_audit_db() -> None:
    """初始化审计表结构（幂等）。"""
    db_path = _get_audit_db()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            agent_id TEXT,
            enterprise_id TEXT,
            details TEXT,
            risk_level TEXT,
            validation_status TEXT
        )
    """)
    conn.commit()
    conn.close()


_init_audit_db()


@router.post("/log")
async def log_audit(
    request: AuditLogRequest,
    _: None = Depends(require_admin_token),
) -> Dict[str, str]:
    """写入审计日志。"""
    db_path = _get_audit_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_logs (timestamp, event_type, agent_id, enterprise_id, details, risk_level, validation_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            time.time(),
            request.event_type,
            request.agent_id,
            request.enterprise_id,
            request.details,
            request.risk_level,
            request.validation_status,
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "logged"}


@router.get("/query")
async def query_audit(
    event_type: Optional[str] = None,
    enterprise_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_admin_token),
) -> List[AuditLogEntry]:
    """按条件分页查询审计日志。"""
    db_path = _get_audit_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    conditions: List[str] = []
    params: List[Any] = []
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if enterprise_id:
        conditions.append("enterprise_id = ?")
        params.append(enterprise_id)
    if risk_level:
        conditions.append("risk_level = ?")
        params.append(risk_level)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"SELECT * FROM audit_logs{where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [AuditLogEntry(**dict(row)) for row in rows]
