"""
知识库管理路由：支持 MD 文件的增删改查与版本回滚
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from harness.knowledge_base import KnowledgeBaseManager
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

def _get_kb() -> KnowledgeBaseManager:
    """每次都创建新实例，确保代码热更新后立即可见。"""
    return KnowledgeBaseManager()


class KnowledgeUpdateRequest(BaseModel):
    filename: str
    content: str
    agent_id: Optional[str] = None


class KnowledgeAppendRequest(BaseModel):
    filename: str
    content: str
    agent_id: Optional[str] = None


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
async def write_knowledge(request: KnowledgeUpdateRequest) -> Dict[str, str]:
    """写入知识库文件"""
    kb = _get_kb()
    kb.write(request.filename, request.content, agent_id=request.agent_id)
    return {"status": "success", "filename": request.filename}


@router.post("/append")
async def append_knowledge(request: KnowledgeAppendRequest) -> Dict[str, str]:
    """追加内容到知识库文件"""
    kb = _get_kb()
    kb.append(request.filename, request.content, agent_id=request.agent_id)
    return {"status": "success", "filename": request.filename}


@router.post("/snapshot")
async def snapshot_knowledge(commit_message: str, agent_id: Optional[str] = None) -> Dict[str, str]:
    """生成知识库快照"""
    kb = _get_kb()
    commit_id = kb.snapshot(commit_message, agent_id=agent_id)
    return {"status": "success", "commit_id": commit_id}


@router.post("/rollback/{commit_id}")
async def rollback_knowledge(commit_id: str) -> Dict[str, str]:
    """回滚知识库到指定版本"""
    kb = _get_kb()
    kb.rollback(commit_id)
    return {"status": "success", "commit_id": commit_id}
