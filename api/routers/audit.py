"""
审计日志路由
查询全流程审计记?"""

import sqlite3
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _get_audit_db() -> str:
    config = get_config()
    return config.audit.db_path


def _init_audit_db() -> None:
    db_path = _get_audit_db()
    import os
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


class AuditLogRequest(BaseModel):
    event_type: str
    agent_id: Optional[str] = None
    enterprise_id: Optional[str] = None
    details: Optional[str] = None
    risk_level: Optional[str] = None
    validation_status: Optional[str] = None


@router.post("/log")
async def log_audit(request: AuditLogRequest) -> Dict[str, str]:
    """写入审计日志"""
    db_path = _get_audit_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_logs (timestamp, event_type, agent_id, enterprise_id, details, risk_level, validation_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (time.time(), request.event_type, request.agent_id, request.enterprise_id,
         request.details, request.risk_level, request.validation_status),
    )
    conn.commit()
    conn.close()
    return {"status": "logged"}


@router.get("/query")
async def query_audit(
    event_type: Optional[str] = None,
    enterprise_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> List[Dict[str, Any]]:
    """查询审计日志"""
    db_path = _get_audit_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if enterprise_id:
        query += " AND enterprise_id = ?"
        params.append(enterprise_id)
    if risk_level:
        query += " AND risk_level = ?"
        params.append(risk_level)
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    columns = ["id", "timestamp", "event_type", "agent_id", "enterprise_id", "details", "risk_level", "validation_status"]
    return [dict(zip(columns, row)) for row in rows]
