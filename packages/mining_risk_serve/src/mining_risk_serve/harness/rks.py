"""
递归知识合成 (Recursive Knowledge Synthesis)
人工审核驳回后，提取四元组并写入知识库
"""

import time
from typing import Any, Dict, Optional

from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.knowledge_base import KnowledgeBaseManager
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


class RecursiveKnowledgeSynthesizer:
    """
    RKS：人工审核驳回后的知识提取与归档
    """

    def __init__(
        self,
        kb_manager: Optional[KnowledgeBaseManager] = None,
        agentfs: Optional[AgentFS] = None,
    ):
        self.kb = kb_manager or KnowledgeBaseManager(agentfs=agentfs)

    def synthesize_rejection(
        self,
        scenario: str,
        wrong_decision: str,
        correct_decision: str,
        basis_clause: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        人工审核驳回后，提取四元组并自动追加写入知识库

        Args:
            scenario: 问题场景
            wrong_decision: 错误决策
            correct_decision: 正确决策
            basis_clause: 依据条款
            agent_id: Agent 标识

        Returns:
            {quadruple, commit_id, files_updated}
        """
        quadruple = {
            "问题场景": scenario,
            "错误决策": wrong_decision,
            "正确决策": correct_decision,
            "依据条款": basis_clause,
            "timestamp": time.time(),
        }

        # 格式化并追加到两个知识库文件
        case_entry = self._format_case_entry(quadruple)
        history_entry = self._format_history_entry(quadruple)

        self.kb.append("类似事故处理案例.md", case_entry, agent_id=agent_id)
        self.kb.append("预警历史经验与短期记忆摘要.md", history_entry, agent_id=agent_id)

        # 调用 AgentFS write() 并触发 Git 快照
        commit_id = self.kb.snapshot(
            commit_message=f"RKS: 追加驳回案例 - {scenario[:30]}",
            agent_id=agent_id,
        )

        logger.info(f"递归知识合成完成，Git Commit: {commit_id}")

        return {
            "quadruple": quadruple,
            "commit_id": commit_id,
            "files_updated": [
                "knowledge_base/类似事故处理案例.md",
                "knowledge_base/预警历史经验与短期记忆摘要.md",
            ],
        }

    def _format_case_entry(self, q: Dict[str, Any]) -> str:
        """格式化为 类似事故处理案例.md 的条目"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(q["timestamp"]))
        return (
            f"\n\n## 案例：{q['问题场景']}\n"
            f"- **错误决策**：{q['错误决策']}\n"
            f"- **正确决策**：{q['正确决策']}\n"
            f"- **依据条款**：{q['依据条款']}\n"
            f"- **记录时间**：{ts}\n"
        )

    def _format_history_entry(self, q: Dict[str, Any]) -> str:
        """格式化为 预警历史经验与短期记忆摘要.md 的表格行"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(q["timestamp"]))
        record_id = f"RKS-{int(q['timestamp'])}"
        return (
            f"\n| {ts} | {record_id} | 驳回修正 | {q['问题场景']} | "
            f"{q['正确决策']} | 已归档 | {q['依据条款']} |"
        )
