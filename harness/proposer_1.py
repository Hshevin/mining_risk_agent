"""
Proposer 节点：将预警决策拆解为 JSON 原子命题列表
"""

import json
from typing import Any, Dict, List

from utils.logger import get_logger

logger = get_logger(__name__)


class Proposer:
    """
    Proposer：将 LLMChain 输出的决策拆分为 JSON 原子命题列表
    """

    @staticmethod
    def decompose(decision: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        将决策拆解为原子命题列表

        Returns:
            原子命题列表，每个包含 {id, proposition, category}
        """
        propositions = []

        # 拆解风险等级判定
        level = decision.get("predicted_level", "")
        if level:
            propositions.append({
                "id": "prop_001",
                "proposition": f"企业风险等级判定为{level}",
                "category": "风险定级",
            })

        # 拆解政府干预建议
        gov_advice = decision.get("government_advice", "")
        if gov_advice:
            propositions.append({
                "id": "prop_002",
                "proposition": f"建议政府部门采取以下措施：{gov_advice[:200]}",
                "category": "政府干预",
            })

        # 拆解企业管控建议
        ent_advice = decision.get("enterprise_advice", "")
        if ent_advice:
            propositions.append({
                "id": "prop_003",
                "proposition": f"建议企业采取以下措施：{ent_advice[:200]}",
                "category": "企业管控",
            })

        # 拆解特征归因
        shap = decision.get("shap_contributions", [])
        if shap:
            top_feature = shap[0].get("feature", "未知特征")
            propositions.append({
                "id": "prop_004",
                "proposition": f"核心风险驱动因素为：{top_feature}",
                "category": "特征归因",
            })

        # 拆解概率分布（如存在）
        prob_dist = decision.get("probability_distribution", {})
        if prob_dist:
            top_level = max(prob_dist, key=prob_dist.get)
            propositions.append({
                "id": "prop_005",
                "proposition": f"模型判定最高置信等级为：{top_level}（置信度 {prob_dist[top_level]:.2%}）",
                "category": "模型置信",
            })

        return propositions

    @staticmethod
    def to_json(propositions: List[Dict[str, str]]) -> str:
        """将原子命题列表序列化为 JSON 字符串"""
        return json.dumps(propositions, ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(json_str: str) -> List[Dict[str, str]]:
        """从 JSON 字符串反序列化为原子命题列表"""
        return json.loads(json_str)
