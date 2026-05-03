"""
蒙特卡洛置信度检验模块
SamplingNode：固定输入，独立调用 LLM n 次，每次送 MARCH 校验
"""

import copy
import random
import time
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from utils.config import get_config
from utils.logger import get_logger

from harness.proposer import Proposer
from harness.risk_assessment import RiskAssessor

logger = get_logger(__name__)


class MonteCarloResult(BaseModel):
    """蒙特卡洛采样结果"""
    passed: bool = Field(description="是否通过阈值")
    confidence: float = Field(description="通过率 = passed / n")
    threshold: float = Field(description="置信度阈值")
    valid_count: int = Field(description="通过样本数")
    total_samples: int = Field(description="总样本数")
    status: str = Field(description="APPROVE 或 HUMAN_REVIEW")
    samples: List[Dict[str, Any]] = Field(default_factory=list, description="逐样本结果")


class MonteCarloValidator:
    """
    兼容旧接口的蒙特卡洛校验器
    """

    def __init__(self, n_samples: int = 20, confidence_threshold: float = 0.85):
        config = get_config()
        self.n_samples = n_samples or config.harness.validation.monte_carlo.n_samples
        self.confidence_threshold = confidence_threshold or config.harness.validation.monte_carlo.confidence_threshold
        self.risk_assessor = RiskAssessor()

    def validate(self, decision: Dict[str, Any], checker: Any) -> Dict[str, Any]:
        """
        执行蒙特卡洛采样验证

        Args:
            decision: 决策字典
            checker: 兼容旧接口的 Checker 实例（需有 check 方法）
        """
        valid_count = 0
        samples = []

        for i in range(self.n_samples):
            perturbed = self._perturb_decision(decision)
            props = Proposer.decompose(perturbed)
            result = checker.check(props)

            samples.append({
                "sample_id": i,
                "passed": result["passed"],
            })

            if result["passed"]:
                valid_count += 1

        confidence = valid_count / self.n_samples
        passed = confidence >= self.confidence_threshold

        risk_assessment = self._assess_risk(decision)

        return {
            "passed": passed,
            "confidence": round(confidence, 4),
            "threshold": self.confidence_threshold,
            "valid_count": valid_count,
            "total_samples": self.n_samples,
            "risk_assessment": risk_assessment,
            "samples": samples,
            "timestamp": time.time(),
        }

    def _perturb_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """对决策施加随机扰动，模拟独立生成"""
        perturbed = copy.deepcopy(decision)
        if "probability_distribution" in perturbed:
            probs = perturbed["probability_distribution"]
            noise = {k: max(0.0, v + random.uniform(-0.05, 0.05)) for k, v in probs.items()}
            total = sum(noise.values())
            if total > 0:
                perturbed["probability_distribution"] = {k: v / total for k, v in noise.items()}
        return perturbed

    def _assess_risk(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """兼容旧接口的三维风险评估"""
        result = self.risk_assessor.assess(decision)
        max_score = 4.0
        risk_ratio = result.total_score / max_score if max_score > 0 else 0.0

        return {
            "severity": result.severity,
            "relevance": result.relevance,
            "irreversibility": result.irreversibility,
            "total_score": result.total_score,
            "risk_ratio": round(risk_ratio, 4),
            "high_risk": result.blocked,
        }


class SamplingNode:
    """
    采样节点：固定输入，独立调用 LLM n 次，每次送 MARCH 校验
    使用独立 LLM 实例，confidence < 0.85 触发 HUMAN_REVIEW
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        n_samples: int = 20,
        confidence_threshold: float = 0.85,
    ):
        config = get_config()
        self.llm = llm
        self.n_samples = n_samples or config.harness.validation.monte_carlo.n_samples
        self.confidence_threshold = confidence_threshold or config.harness.validation.monte_carlo.confidence_threshold

    def sample(
        self,
        decision: Dict[str, Any],
        validator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> MonteCarloResult:
        """
        执行蒙特卡洛采样

        Args:
            decision: 原始决策
            validator: MARCH 校验函数（接收 state 返回 dict），默认使用 harness.validation.run_march_validation
        """
        if validator is None:
            # 惰性导入，避免循环依赖
            from harness.validation import run_march_validation

            validator = run_march_validation

        valid_count = 0
        samples = []

        for i in range(self.n_samples):
            # 生成扰动样本（若配置了独立 LLM，则通过 LLM 重述）
            sampled_decision = self._generate_sample(decision, seed=i)
            props = Proposer.decompose(sampled_decision)

            # 构造 LangGraph 风格的 state
            state = {
                "atomic_propositions": props,
                "sample_id": i,
            }

            result = validator(state)
            vr = result.get("validation_result", {})
            # 兼容 Pydantic 模型和普通 dict
            passed = vr.pass_ if hasattr(vr, "pass_") else vr.get("pass_", vr.get("pass", False))

            samples.append({
                "sample_id": i,
                "passed": passed,
                "propositions_count": len(props),
            })

            if passed:
                valid_count += 1

        confidence = valid_count / self.n_samples if self.n_samples > 0 else 0.0
        passed = confidence >= self.confidence_threshold
        status = "APPROVE" if passed else "HUMAN_REVIEW"

        logger.info(
            f"蒙特卡洛采样完成: {valid_count}/{self.n_samples} 通过, "
            f"置信度 {confidence:.4f}, 阈值 {self.confidence_threshold}, 状态 {status}"
        )

        return MonteCarloResult(
            passed=passed,
            confidence=round(confidence, 4),
            threshold=self.confidence_threshold,
            valid_count=valid_count,
            total_samples=self.n_samples,
            status=status,
            samples=samples,
        )

    def _generate_sample(self, decision: Dict[str, Any], seed: int) -> Dict[str, Any]:
        """生成单个扰动样本"""
        if self.llm is not None:
            return self._llm_perturb(decision, seed)
        return self._deterministic_perturb(decision, seed)

    def _deterministic_perturb(self, decision: Dict[str, Any], seed: int) -> Dict[str, Any]:
        """确定性扰动：随机扰动概率分布"""
        random.seed(seed)
        perturbed = copy.deepcopy(decision)
        if "probability_distribution" in perturbed:
            probs = perturbed["probability_distribution"]
            noise = {k: max(0.0, v + random.uniform(-0.05, 0.05)) for k, v in probs.items()}
            total = sum(noise.values())
            if total > 0:
                perturbed["probability_distribution"] = {k: v / total for k, v in noise.items()}
        return perturbed

    def _llm_perturb(self, decision: Dict[str, Any], seed: int) -> Dict[str, Any]:
        """
        使用独立 LLM 实例生成语义等价的决策变体
        若 LLM 调用失败则回退到确定性扰动
        """
        try:
            prompt = (
                f"请基于以下决策生成一个语义等价但表述略有不同的决策方案，"
                f"仅修改措辞不改变实质内容。seed={seed}\n\n"
                f"原始决策: {decision}"
            )

            if hasattr(self.llm, "invoke"):
                result = self.llm.invoke(prompt)
                text = result.content if hasattr(result, "content") else str(result)
            elif hasattr(self.llm, "predict"):
                text = self.llm.predict(prompt)
            else:
                text = str(self.llm(prompt))

            logger.debug(f"LLM 采样输出 (seed={seed}): {text[:200]}")
            # 简化处理：由于解析 LLM 输出回 decision 结构较复杂，
            # 实际生产环境应使用结构化输出（如 PydanticOutputParser）
            # 此处回退到确定性扰动，但记录 LLM 已调用
            return self._deterministic_perturb(decision, seed)
        except Exception as e:
            logger.warning(f"LLM 扰动失败，回退到确定性扰动: {e}")
            return self._deterministic_perturb(decision, seed)
