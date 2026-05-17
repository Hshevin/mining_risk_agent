"""
三维风险评估模块
后果严重度、利益相关性、执行不可逆性
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from mining_risk_common.utils.config import get_config
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


class RiskAssessmentResult(BaseModel):
    """三维风险评估结果"""
    severity: str = Field(description="后果严重度：极高/高/中/低")
    relevance: str = Field(description="利益相关性：极高/高/中/低")
    irreversibility: str = Field(description="执行不可逆性：极高/高/中/低")
    total_score: float = Field(description="加权风险总分（满分 4.0）")
    risk_level: str = Field(description="风险分级：EXTREME/HIGH/MEDIUM/LOW")
    blocked: bool = Field(description="是否触发阻断/分级审核")
    reason: str = Field(description="评估理由")


class RiskAssessor:
    """
    RiskAssessor：三维量化风险评估器
    结合 SOP 加权规则计算风险总分，超阈值触发分级审核
    """

    # 四维评分映射（极高/高/中/低）
    SCORE_MAP: Dict[str, int] = {"极高": 4, "高": 3, "中": 2, "低": 1}

    # SOP 加权规则（权重和为 1.0）
    SOP_WEIGHTS: Dict[str, float] = {
        "severity": 0.50,
        "relevance": 0.30,
        "irreversibility": 0.20,
    }

    # 阻断阈值（超过此值触发分级审核）
    BLOCK_THRESHOLD: float = 2.5

    def __init__(self, threshold: Optional[float] = None):
        self.threshold = threshold or self.BLOCK_THRESHOLD

    def assess(self, decision: Dict[str, Any]) -> RiskAssessmentResult:
        """
        对决策进行三维风险评估
        """
        level = decision.get("predicted_level", "四级")

        # 根据风险等级映射三维评分
        severity = self._map_level_to_dimension(level, "severity")
        relevance = self._map_level_to_dimension(level, "relevance")
        irreversibility = self._map_level_to_dimension(level, "irreversibility")

        # 加权总分（满分 4.0）
        total_score = (
            self.SCORE_MAP[severity] * self.SOP_WEIGHTS["severity"]
            + self.SCORE_MAP[relevance] * self.SOP_WEIGHTS["relevance"]
            + self.SCORE_MAP[irreversibility] * self.SOP_WEIGHTS["irreversibility"]
        )

        risk_level = self._score_to_level(total_score)
        blocked = total_score >= self.threshold

        reason = (
            f"三维风险评分 {total_score:.2f}（{severity}/{relevance}/{irreversibility}），"
            f"风险等级 {risk_level}"
            if blocked
            else f"三维风险评分 {total_score:.2f} 未达阻断阈值 {self.threshold}"
        )

        return RiskAssessmentResult(
            severity=severity,
            relevance=relevance,
            irreversibility=irreversibility,
            total_score=round(total_score, 2),
            risk_level=risk_level,
            blocked=blocked,
            reason=reason,
        )

    def assess_tool_call(self, tool_name: str, args: tuple, kwargs: dict) -> Dict[str, Any]:
        """
        对工具调用进行快速风险评估（供 ToolCallInterceptor 使用）
        """
        high_risk_tools = ["delete", "destroy", "shutdown", "rollback", "drop", "wipe"]
        medium_risk_tools = ["write", "update", "modify", "append"]

        tool_lower = tool_name.lower()

        if any(hrt in tool_lower for hrt in high_risk_tools):
            return {
                "blocked": True,
                "severity": "极高",
                "relevance": "高",
                "irreversibility": "极高",
                "reason": f"高风险工具调用被拦截: {tool_name}",
            }

        if any(mrt in tool_lower for mrt in medium_risk_tools):
            return {
                "blocked": False,
                "severity": "中",
                "relevance": "中",
                "irreversibility": "中",
                "reason": f"中风险工具调用已记录: {tool_name}",
            }

        return {
            "blocked": False,
            "severity": "低",
            "relevance": "低",
            "irreversibility": "低",
            "reason": f"低风险工具调用: {tool_name}",
        }

    def _map_level_to_dimension(self, level: str, dimension: str) -> str:
        """将风险等级映射到三维评分"""
        mapping = {
            "一级": {"severity": "极高", "relevance": "极高", "irreversibility": "极高"},
            "二级": {"severity": "高", "relevance": "高", "irreversibility": "高"},
            "三级": {"severity": "中", "relevance": "中", "irreversibility": "中"},
            "四级": {"severity": "低", "relevance": "低", "irreversibility": "低"},
            "红": {"severity": "极高", "relevance": "极高", "irreversibility": "极高"},
            "橙": {"severity": "高", "relevance": "高", "irreversibility": "高"},
            "黄": {"severity": "中", "relevance": "中", "irreversibility": "中"},
            "蓝": {"severity": "低", "relevance": "低", "irreversibility": "低"},
        }
        return mapping.get(level, {"severity": "中", "relevance": "中", "irreversibility": "中"})[dimension]

    def _score_to_level(self, score: float) -> str:
        """将加权总分映射到风险分级"""
        if score >= 3.5:
            return "EXTREME"
        elif score >= 2.5:
            return "HIGH"
        elif score >= 1.5:
            return "MEDIUM"
        else:
            return "LOW"
