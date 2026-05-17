"""
服务层抽象接口（Protocol）

通过 Protocol 定义依赖边界，便于测试替换与降低 router 对具体实现的耦合。
"""

from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class RiskPredictor(Protocol):
  """风险预测模型接口。"""

  def predict(self, features: Any) -> Dict[str, Any]:
    """对特征矩阵执行推理。

    Args:
        features: 经特征工程后的输入。

    Returns:
        含 ``predicted_level``、``probability_distribution``、``shap_contributions`` 的字典。
    """

    ...

  def load(self, path: str) -> None:
    """从磁盘加载模型权重。

    Args:
        path: 模型文件路径。
    """

    ...


@runtime_checkable
class FeaturePipeline(Protocol):
  """特征工程流水线接口。"""

  def transform(self, df: Any) -> Any:
    """将原始 DataFrame 转为模型输入。

    Args:
        df: 原始企业数据表。

    Returns:
        模型可用的特征矩阵。
    """

    ...

  def load(self, path: str) -> None:
    """从磁盘加载流水线状态。"""

    ...


@runtime_checkable
class DecisionWorkflowPort(Protocol):
  """决策工作流接口。"""

  scenario: Any

  async def run_async(
    self,
    enterprise_id: str,
    raw_data: Dict[str, Any],
  ) -> Dict[str, Any]:
    """异步执行完整决策图。

    Args:
        enterprise_id: 企业 ID。
        raw_data: 原始输入数据。

    Returns:
        工作流终态字典。
    """

    ...


@runtime_checkable
class KnowledgeRepository(Protocol):
  """知识库持久化接口。"""

  def list_files(self) -> List[str]:
    """列出所有知识库文件名。"""

    ...

  def read(self, filename: str) -> str:
    """读取指定文件内容。

    Args:
        filename: 文件名。

    Returns:
        文件全文。

    Raises:
        FileNotFoundError: 文件不存在时。
    """

    ...

  def write(self, filename: str, content: str, agent_id: Optional[str] = None) -> None:
    """覆盖写入文件。"""

    ...

  def append(self, filename: str, content: str, agent_id: Optional[str] = None) -> None:
    """追加内容到文件末尾。"""

    ...

  def snapshot(self, commit_message: str, agent_id: Optional[str] = None) -> str:
    """创建版本快照。

    Returns:
        快照标识或提交说明。
    """

    ...


@runtime_checkable
class DecisionStreamPort(Protocol):
  """决策 SSE 流接口。"""

  async def stream(
    self,
    enterprise_id: str,
    raw_data: Dict[str, Any],
    scenario_id: str,
  ) -> AsyncIterator[str]:
    """产出 SSE ``data:`` 行。

    Yields:
        符合 SSE 格式的字符串块。
    """

    ...
