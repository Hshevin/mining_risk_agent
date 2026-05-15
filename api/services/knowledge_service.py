"""
知识库业务服务层
"""

from typing import List

from fastapi import HTTPException

from api.interfaces import KnowledgeRepository
from api.schemas.knowledge import (
    KnowledgeAppendRequest,
    KnowledgeFileContent,
    KnowledgeMutationResponse,
    KnowledgeUpdateRequest,
)
from api.services.dependencies import get_knowledge_repository
from utils.exceptions import KnowledgeBaseError
from utils.logger import get_logger

logger = get_logger(__name__)


class KnowledgeService:
    """知识库读写与版本管理服务。

    Args:
        repository: 知识库持久化实现，默认每次从工厂获取新实例以支持热更新。
    """

    def __init__(self, repository: KnowledgeRepository | None = None) -> None:
        self._repository = repository

    def _repo(self) -> KnowledgeRepository:
        return self._repository or get_knowledge_repository()

    def list_files(self) -> List[str]:
        """列出所有知识库 Markdown 文件名。"""
        return self._repo().list_files()

    def read_file(self, filename: str) -> KnowledgeFileContent:
        """读取指定知识库文件。

        Args:
            filename: 文件名。

        Returns:
            文件名与内容。

        Raises:
            HTTPException: 文件不存在或读取失败时 404。
        """
        try:
            content = self._repo().read(filename)
            return KnowledgeFileContent(filename=filename, content=content)
        except Exception as exc:
            logger.warning("读取知识库失败: %s", exc)
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def write_file(self, request: KnowledgeUpdateRequest) -> KnowledgeMutationResponse:
        """覆盖写入知识库文件。"""
        try:
            self._repo().write(request.filename, request.content, agent_id=request.agent_id)
            return KnowledgeMutationResponse(status="success", filename=request.filename)
        except KnowledgeBaseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def append_file(self, request: KnowledgeAppendRequest) -> KnowledgeMutationResponse:
        """追加内容到知识库文件末尾。"""
        try:
            self._repo().append(request.filename, request.content, agent_id=request.agent_id)
            return KnowledgeMutationResponse(status="success", filename=request.filename)
        except KnowledgeBaseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def snapshot(self, commit_message: str, agent_id: str | None = None) -> KnowledgeMutationResponse:
        """创建知识库版本快照。"""
        try:
            commit_id = self._repo().snapshot(commit_message, agent_id=agent_id)
            return KnowledgeMutationResponse(status="success", commit_id=commit_id)
        except KnowledgeBaseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def rollback(self, commit_id: str) -> KnowledgeMutationResponse:
        """回滚知识库到指定快照版本。

        Args:
            commit_id: 快照提交 ID。

        Returns:
            回滚操作结果。
        """
        try:
            self._repo().rollback(commit_id)
            return KnowledgeMutationResponse(status="success", commit_id=commit_id)
        except KnowledgeBaseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_knowledge_service() -> KnowledgeService:
    """FastAPI 依赖：知识库服务。"""
    return KnowledgeService()
