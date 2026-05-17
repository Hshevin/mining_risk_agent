"""
知识库管理路由：支持 MD 文件的增删改查与版本回滚
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from mining_risk_serve.api.schemas.knowledge import KnowledgeAppendRequest, KnowledgeUpdateRequest
from mining_risk_serve.api.security import require_admin_token
from mining_risk_serve.harness.validation import EvidenceRetriever
from mining_risk_serve.harness.vector_store import VectorStore
from mining_risk_serve.harness.knowledge_base import KnowledgeBaseManager
from mining_risk_common.utils.config import resolve_project_path
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

REPORT_DIR = resolve_project_path("reports")
RAG_REPORT_PATH = REPORT_DIR / "rag_index_rebuild_run.json"
AUDIT_REPORT_PATH = REPORT_DIR / "knowledge_system_audit_run.json"
AGENTFS_REPORT_PATH = REPORT_DIR / "agentfs_kb_sync_run.json"
RULE_REPORT_PATH = REPORT_DIR / "rule_kbs_rebuild_run.json"
ACCIDENT_REPORT_PATH = REPORT_DIR / "accident_cases_kb_rebuild_run.json"

KB_HIGHLIGHTS: Dict[str, Dict[str, Any]] = {
    "工矿风险预警智能体合规执行书.md": {
        "type": "compliance",
        "highlight": "COM 合规红线、必须上报/停产/撤人/整改/复查规则",
        "summary": "面向工矿风险预警的合规执行底座，包含红线、处置动作、审计留痕和三类规则锚点。",
        "key_sections": ["合规红线规则表", "必须上报、停产、撤人、整改、复查和数据审计规则", "机器可读摘要"],
        "data_sources": ["安全生产法", "工贸重大事故隐患判定标准", "项目审计规则"],
    },
    "部门分级审核SOP.md": {
        "type": "sop",
        "highlight": "SOP 分级路由、协同、退回、闭环和联系人占位",
        "summary": "记录监管部门分级审核流程、协同部门、时限和闭环要求，供路由配置和审计展示引用。",
        "key_sections": ["分级路由、协同、退回和闭环 SOP 表", "机器可读摘要"],
        "data_sources": ["部门/人员/监管主体公开字段", "项目 SOP"],
    },
    "工业物理常识及传感器时间序列逻辑.md": {
        "type": "physics",
        "highlight": "PHY 工况逻辑、传感器时间序列、粉尘/危化/冶金/有限空间规则",
        "summary": "沉淀工况物理约束和传感器逻辑，支撑异常解释、阈值复核和跨指标一致性检查。",
        "key_sections": ["数据来源与事实边界", "工况逻辑和时间序列规则表", "机器可读摘要"],
        "data_sources": ["公开字段映射", "传感器逻辑规则", "国家/行业标准"],
    },
    "企业已具备的执行条件.md": {
        "type": "conditions",
        "highlight": "公开数据重建的企业执行条件事实库",
        "summary": "基于公开数据整理企业人员、设备、资质、隐患、处罚、行业、位置和生产状态等执行条件。",
        "key_sections": ["公开数据统计", "粉尘涉爆执行条件", "冶金执行条件", "危化品执行条件"],
        "data_sources": ["public_data_inventory.json", "public_data_field_mapping.csv", "公开数据 67 个文件/sheet"],
    },
    "类似事故处理案例.md": {
        "type": "cases",
        "highlight": "36 个真实公开数据 B/C/D 类案例与 3 个模板案例",
        "summary": "从隐患闭环、处罚、风险组合中沉淀可追溯案例，明确不把未确认事件表述为真实事故。",
        "key_sections": ["重大隐患与未整改闭环案例", "行政处罚案例", "高风险企业风险组合案例"],
        "data_sources": ["accident_cases_kb_rebuild_run.json", "公开检查/隐患/处罚/风险表"],
    },
    "预警历史经验与短期记忆摘要.md": {
        "type": "history_memory",
        "highlight": "预警历史经验、短期记忆摘要和归档入口",
        "summary": "保留预警经验和短期记忆摘要，为 P0-P3 记忆机制提供可展示的归档视图。",
        "key_sections": ["历史经验摘要", "短期记忆摘要"],
        "data_sources": ["memory/*.md", "AgentFS memory archive"],
    },
}

AUDIT_WARNINGS = [
    "AgentFS deprecated 乱码路径仍保留",
    "当前仍使用 fallback embedding/reranker",
    "本地公开数据无法确认 A 类真实事故详案",
    "法条编号/标准条款需法务复核",
    "阈值需按企业设备/SDS/SOP 校准",
    "部门真实联系人仍需部署配置",
]

MEMORY_ARCHIVES = [
    {
        "path": "memory/风险事件归档.md",
        "priority": "P1",
        "strategy": "摘要归档",
        "description": "沉淀已核验的风险事件摘要和后续复查线索。",
    },
    {
        "path": "memory/核心指令归档.md",
        "priority": "P0",
        "strategy": "永久保留",
        "description": "保存系统边界、禁止项和核心运行约束。",
    },
    {
        "path": "memory/处置经验归档.md",
        "priority": "P1",
        "strategy": "摘要归档",
        "description": "归档经过复盘的处置经验和现场操作注意事项。",
    },
    {
        "path": "memory/系统日志归档.md",
        "priority": "P2",
        "strategy": "压缩保留",
        "description": "保存可压缩的系统运行摘要和审计索引。",
    },
]

def _get_kb() -> KnowledgeBaseManager:
    """每次都创建新实例，确保代码热更新后立即可见。"""
    return KnowledgeBaseManager()


@router.get("/list")
async def list_knowledge() -> List[str]:
    """列出所有知识库文件"""
    kb = _get_kb()
    return kb.list_files()


@router.get("/read/{filename}")
async def read_knowledge(filename: str) -> Dict[str, str]:
    """读取知识库文件内容"""
    kb = _get_kb()
    try:
        content = kb.read(filename)
        return {"filename": filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/write")
async def write_knowledge(
    request: KnowledgeUpdateRequest,
    _: None = Depends(require_admin_token),
) -> Dict[str, str]:
    """写入知识库文件"""
    kb = _get_kb()
    kb.write(request.filename, request.content, agent_id=request.agent_id)
    return {"status": "success", "filename": request.filename}


@router.post("/append")
async def append_knowledge(
    request: KnowledgeAppendRequest,
    _: None = Depends(require_admin_token),
) -> Dict[str, str]:
    """追加内容到知识库文件"""
    kb = _get_kb()
    kb.append(request.filename, request.content, agent_id=request.agent_id)
    return {"status": "success", "filename": request.filename}


@router.post("/snapshot")
async def snapshot_knowledge(
    commit_message: str,
    agent_id: Optional[str] = None,
    _: None = Depends(require_admin_token),
) -> Dict[str, str]:
    """生成知识库快照"""
    kb = _get_kb()
    commit_id = kb.snapshot(commit_message, agent_id=agent_id)
    return {"status": "success", "commit_id": commit_id}


@router.post("/rollback/{commit_id}")
async def rollback_knowledge(
    commit_id: str,
    _: None = Depends(require_admin_token),
) -> Dict[str, str]:
    """回滚知识库到指定版本"""
    kb = _get_kb()
    kb.rollback(commit_id)
    return {"status": "success", "commit_id": commit_id}
