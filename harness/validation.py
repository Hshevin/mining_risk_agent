"""
三重校验与高风险阻断机制
MARCH 声明级孤立验证 + 蒙特卡洛置信度检验 + LangGraph 物理隔离 Checker 节点
"""

import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from harness.knowledge_base import KnowledgeBaseManager
from harness.monte_carlo import MonteCarloValidator
from harness.proposer import Proposer
from harness.risk_assessment import RiskAssessor
from utils.config import get_config
from utils.exceptions import HighRiskBlockedError, ValidationError
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Pydantic 模型
# =============================================================================

class ValidationResult(BaseModel):
    """
    MARCH 校验结果 Pydantic 模型
    字段命名兼容：pass_ 在 Python 侧，序列化/构造时可用 pass
    """
    model_config = ConfigDict(populate_by_name=True)

    pass_: bool = Field(
        default=False,
        alias="pass",
        description="是否通过校验",
    )
    violated_propositions: List[str] = Field(
        default_factory=list,
        description="被违反的原子命题 ID 列表",
    )
    reason: str = Field(
        default="",
        description="结构化修正反馈",
    )


# =============================================================================
# 信息隔离辅助函数
# =============================================================================

def _get_isolated_propositions(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    信息隔离：仅提取 state["atomic_propositions"]
    明确禁止访问 state["raw_data"] 与 state["decision"]
    """
    if "atomic_propositions" not in state:
        raise ValidationError(
            "state 中缺少 atomic_propositions，无法执行 MARCH 校验"
        )
    return state["atomic_propositions"]


# =============================================================================
# LangGraph 物理隔离 Checker 节点（3 个独立函数）
# =============================================================================

def compliance_checker(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph 合规红线 Checker 节点
    信息隔离：仅允许读取 state["atomic_propositions"]
    """
    propositions = _get_isolated_propositions(state)
    violated: List[Dict[str, str]] = []

    # 扩展合规红线规则库
    red_lines = [
        "瓦斯浓度超限",
        "通风系统停运",
        "无证上岗",
        "超能力生产",
        "隐瞒事故",
        "销毁监控记录",
        "破坏安全监控",
        "关闭报警设备",
        "屏蔽传感器",
        "删除日志",
        "伪造数据",
    ]

    for prop in propositions:
        text = prop.get("proposition", "")
        prop_id = prop.get("id", "unknown")

        # 关键词红线匹配
        for line in red_lines:
            if line in text:
                violated.append({
                    "id": prop_id,
                    "proposition": text,
                    "violation": f"触发合规红线：{line}",
                })
                break

        # 特殊规则：建议销毁监控记录（即使未命中关键词，也做语义兜底）
        if "销毁" in text and ("监控" in text or "记录" in text or "视频" in text):
            # 避免重复记录
            if not any(v["id"] == prop_id for v in violated):
                violated.append({
                    "id": prop_id,
                    "proposition": text,
                    "violation": "严禁销毁监控记录，违反《安全生产法》第三十六条及合规执行书",
                })

    passed = len(violated) == 0
    reason = (
        "合规红线校验通过"
        if passed
        else "[合规红线] " + "; ".join(
            f"[{v['id']}] {v['violation']}: {v['proposition']}"
            for v in violated
        )
    )

    return {
        "validation_result": ValidationResult(
            pass_=passed,
            violated_propositions=[v["id"] for v in violated],
            reason=reason,
        )
    }


def logic_checker(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph 工况逻辑 Checker 节点
    信息隔离：仅允许读取 state["atomic_propositions"]
    """
    propositions = _get_isolated_propositions(state)
    violated: List[Dict[str, str]] = []

    for prop in propositions:
        text = prop.get("proposition", "")
        prop_id = prop.get("id", "unknown")

        # 物理常识冲突
        if "温度" in text and ("超过 100°C 正常" in text or "100度正常" in text):
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": "与物理常识冲突：环境温度不可能超过 100°C 仍正常",
            })

        # 传感器逻辑异常
        if "瓦斯浓度" in text and ("0%" in text or "无瓦斯" in text) and "正常生产" in text:
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": "逻辑错误：瓦斯浓度为 0% 时无法判定为正常生产（可能存在传感器故障）",
            })

        # 压力逻辑
        if "负压" in text and "正常" in text and "管道" in text:
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": "逻辑错误：管道负压异常，需检查泄漏或风机故障",
            })

    passed = len(violated) == 0
    reason = (
        "工况逻辑校验通过"
        if passed
        else "[工况逻辑] " + "; ".join(
            f"[{v['id']}] {v['violation']}: {v['proposition']}"
            for v in violated
        )
    )

    return {
        "validation_result": ValidationResult(
            pass_=passed,
            violated_propositions=[v["id"] for v in violated],
            reason=reason,
        )
    }


def feasibility_checker(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph 处置可行性 Checker 节点
    信息隔离：仅允许读取 state["atomic_propositions"]
    """
    propositions = _get_isolated_propositions(state)
    violated: List[Dict[str, str]] = []

    for prop in propositions:
        text = prop.get("proposition", "")
        prop_id = prop.get("id", "unknown")

        if "立即停产" in text and "微型" in text:
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": "微型企业可能不具备立即停产的应急条件，需核实",
            })

        if "撤离" in text and "全员" in text and "微型" in text:
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": "微型企业人员疏散能力有限，建议分批次撤离",
            })

        if "购置" in text and ("大型设备" in text or "成套系统" in text) and "微型" in text:
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": "微型企业可能不具备购置大型设备的资金与场地条件",
            })

    passed = len(violated) == 0
    reason = (
        "处置可行性校验通过"
        if passed
        else "[处置可行性] " + "; ".join(
            f"[{v['id']}] {v['violation']}: {v['proposition']}"
            for v in violated
        )
    )

    return {
        "validation_result": ValidationResult(
            pass_=passed,
            violated_propositions=[v["id"] for v in violated],
            reason=reason,
        )
    }


# =============================================================================
# 分级顺序执行：合规红线 → 工况逻辑 → 处置可行性
# =============================================================================

def run_march_validation(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    按分级顺序执行 MARCH 校验：
    合规红线 → 工况逻辑 → 处置可行性
    任意一级不通过即暂停并返回结构化修正反馈
    """
    # Level 1: 合规红线
    result = compliance_checker(state)
    if not result["validation_result"].pass_:
        logger.warning(
            f"MARCH 合规红线拦截: {result['validation_result'].reason}"
        )
        return result

    # Level 2: 工况逻辑
    result = logic_checker(state)
    if not result["validation_result"].pass_:
        logger.warning(
            f"MARCH 工况逻辑拦截: {result['validation_result'].reason}"
        )
        return result

    # Level 3: 处置可行性
    result = feasibility_checker(state)
    if not result["validation_result"].pass_:
        logger.warning(
            f"MARCH 处置可行性拦截: {result['validation_result'].reason}"
        )
        return result

    return {
        "validation_result": ValidationResult(
            pass_=True,
            reason="MARCH 三重校验全部通过",
        )
    }


# =============================================================================
# ToolCallInterceptor：拦截所有工具调用请求，注入风险评估
# =============================================================================

class ToolCallInterceptor:
    """
    工具调用拦截器：对所有工具调用注入风险评估
    """

    def __init__(self, risk_assessor: Optional[RiskAssessor] = None):
        self.risk_assessor = risk_assessor or RiskAssessor()
        self.intercepted_calls: List[Dict[str, Any]] = []

    def intercept(
        self, tool_name: str, tool_func: Callable, *args: Any, **kwargs: Any
    ) -> Any:
        """
        拦截工具调用：先评估风险，通过后再执行原函数
        """
        risk = self.risk_assessor.assess_tool_call(tool_name, args, kwargs)
        self.intercepted_calls.append({
            "tool_name": tool_name,
            "args": args,
            "kwargs": kwargs,
            "risk": risk,
            "timestamp": time.time(),
        })

        if risk.get("blocked"):
            logger.error(
                f"工具调用被拦截: {tool_name}, 原因: {risk.get('reason')}"
            )
            raise HighRiskBlockedError(
                f"工具调用 {tool_name} 被风险拦截: {risk.get('reason')}"
            )

        logger.info(f"工具调用通过风险评估: {tool_name}")
        return tool_func(*args, **kwargs)

    def wrap(self, tool_name: str, tool_func: Callable) -> Callable:
        """返回一个被拦截器包装的工具函数"""
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.intercept(tool_name, tool_func, *args, **kwargs)
        return wrapper


# =============================================================================
# 向后兼容的包装类（保留旧接口）
# =============================================================================

class Checker:
    """
    兼容旧接口的 Checker 包装类
    test_harness.py 仍可直接 from harness.validation import Checker
    """

    def __init__(self, knowledge_base: Optional[KnowledgeBaseManager] = None):
        self.kb = knowledge_base or KnowledgeBaseManager()

    def check(self, propositions: List[Dict[str, str]]) -> Dict[str, Any]:
        state = {"atomic_propositions": propositions}
        result = run_march_validation(state)
        vr = result["validation_result"]
        return {
            "passed": vr.pass_,
            "level": "PASS" if vr.pass_ else "BLOCK",
            "details": [],
            "feedback": vr.reason,
            "timestamp": time.time(),
        }


class ValidationPipeline:
    """
    兼容旧接口的完整校验流水线
    test_harness.py 仍可直接 from harness.validation import ValidationPipeline
    """

    def __init__(self):
        self.kb = KnowledgeBaseManager()
        self.checker = Checker(self.kb)
        self.mc_validator = MonteCarloValidator()
        self.risk_assessor = RiskAssessor()

    def run(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        # Step 1: MARCH 声明级孤立验证
        propositions = Proposer.decompose(decision)
        march_result = self.checker.check(propositions)

        if not march_result["passed"]:
            logger.warning(f"MARCH 校验未通过: {march_result['feedback']}")
            return {
                "march_result": march_result,
                "monte_carlo_result": None,
                "final_decision": "REJECT",
                "routing": {
                    "action": "反馈修正",
                    "target": "智能体重生成",
                    "feedback": march_result["feedback"],
                },
            }

        # Step 2: 蒙特卡洛置信度检验
        mc_result = self.mc_validator.validate(decision, self.checker)

        if not mc_result["passed"]:
            logger.warning(
                f"蒙特卡洛置信度不足: {mc_result['confidence']} < {mc_result['threshold']}"
            )
            return {
                "march_result": march_result,
                "monte_carlo_result": mc_result,
                "final_decision": "BLOCK",
                "routing": {
                    "action": "高风险阻断",
                    "target": self._route_by_risk(decision),
                    "reason": f"置信度 {mc_result['confidence']} 低于阈值 {mc_result['threshold']}",
                },
            }

        # Step 3: 三维高风险阻断判断
        risk = self.risk_assessor.assess(decision)
        if risk.blocked:
            return {
                "march_result": march_result,
                "monte_carlo_result": mc_result,
                "final_decision": "MANUAL_REVIEW",
                "routing": {
                    "action": "转人工审核",
                    "target": self._route_by_risk(decision),
                    "reason": f"三维风险评估阻断: {risk.reason}",
                },
            }

        return {
            "march_result": march_result,
            "monte_carlo_result": mc_result,
            "final_decision": "APPROVE",
            "routing": {
                "action": "执行",
                "target": "预警推送系统",
            },
        }

    def _route_by_risk(self, decision: Dict[str, Any]) -> str:
        """根据风险等级路由到对应审核部门"""
        level = decision.get("predicted_level", "四级")
        routing_map = {
            "一级": "属地应急管理局 + 省级监管部门",
            "二级": "属地应急管理局 + 行业主管部门",
            "三级": "区县级安监部门",
            "四级": "企业安全管理部门",
            "红": "属地应急管理局 + 省级监管部门",
            "橙": "属地应急管理局 + 行业主管部门",
            "黄": "区县级安监部门",
            "蓝": "企业安全管理部门",
        }
        return routing_map.get(level, "企业安全管理部门")
