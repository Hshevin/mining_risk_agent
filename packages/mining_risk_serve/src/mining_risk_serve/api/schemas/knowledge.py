"""
知识库 API 契约模型
"""

from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeUpdateRequest(BaseModel):
  """知识库文件写入请求。

  Attributes:
      filename: 目标文件名（含扩展名）。
      content: 完整文件内容。
      agent_id: 可选，记录操作智能体 ID。
  """

  filename: str = Field(..., min_length=1, description="文件名")
  content: str = Field(..., description="文件内容")
  agent_id: Optional[str] = Field(default=None, description="操作智能体 ID")


class KnowledgeAppendRequest(BaseModel):
  """知识库文件追加请求。"""

  filename: str = Field(..., min_length=1, description="文件名")
  content: str = Field(..., description="追加内容")
  agent_id: Optional[str] = Field(default=None, description="操作智能体 ID")


class KnowledgeFileContent(BaseModel):
  """知识库文件读取响应。"""

  filename: str
  content: str


class KnowledgeMutationResponse(BaseModel):
  """知识库写入/追加/快照/回滚操作响应。"""

  status: str = Field(default="success", description="操作状态")
  filename: str = Field(default="", description="受影响文件名")
  message: str = Field(default="", description="附加说明")
  commit_id: str = Field(default="", description="快照或回滚关联的提交 ID")
