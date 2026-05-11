"""
代码/模型 Drift 分析模块
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
from sklearn.pipeline import Pipeline

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


class DriftAnalyzer:
    """
    Drift 分析器
    对比新旧模型权重、元学习器权重、预处理 Pipeline 逻辑变更
    """

    def __init__(
        self,
        old_model_path: Optional[str] = None,
        new_model_path: Optional[str] = None,
        old_pipeline_path: Optional[str] = None,
        new_pipeline_path: Optional[str] = None,
    ):
        config = get_config()
        self.old_model_path = old_model_path or config.model.stacking.model_path
        self.new_model_path = new_model_path
        self.old_pipeline_path = old_pipeline_path or config.model.stacking.pipeline_path
        self.new_pipeline_path = new_pipeline_path

    def _load_model(self, path: str) -> Dict[str, Any]:
        """加载模型字典"""
        return joblib.load(path)

    def _load_pipeline(self, path: str) -> Any:
        """加载预处理 Pipeline"""
        return joblib.load(path)

    def analyze_model_weights(self) -> Dict:
        """
        分析模型权重差异
        """
        if not os.path.exists(self.old_model_path) or not os.path.exists(self.new_model_path):
            return {"error": "模型路径不存在"}

        old_data = self._load_model(self.old_model_path)
        new_data = self._load_model(self.new_model_path)

        old_learners = old_data.get("base_learners", {})
        new_learners = new_data.get("base_learners", {})

        learner_diffs = []
        for name in set(list(old_learners.keys()) + list(new_learners.keys())):
            old_model = old_learners.get(name)
            new_model = new_learners.get(name)
            status = "unchanged"
            if old_model is None:
                status = "added"
            elif new_model is None:
                status = "removed"
            elif type(old_model).__name__ != type(new_model).__name__:
                status = "type_changed"
            learner_diffs.append({
                "name": name,
                "status": status,
                "old_type": type(old_model).__name__ if old_model else None,
                "new_type": type(new_model).__name__ if new_model else None,
            })

        # 元学习器权重变化
        old_meta = old_data.get("meta_learner")
        new_meta = new_data.get("meta_learner")
        meta_diff = {"status": "unknown"}
        if hasattr(old_meta, "coef_") and hasattr(new_meta, "coef_"):
            old_coef = np.asarray(old_meta.coef_)
            new_coef = np.asarray(new_meta.coef_)
            diff = np.abs(new_coef - old_coef)
            meta_diff = {
                "status": "analyzed",
                "mean_abs_change": float(np.mean(diff)),
                "max_abs_change": float(np.max(diff)),
                "shape": list(old_coef.shape),
            }

        return {
            "base_learners": learner_diffs,
            "meta_learner": meta_diff,
        }

    def analyze_pipeline_drift(self) -> Dict:
        """
        分析预处理 Pipeline 逻辑变更
        """
        if not os.path.exists(self.old_pipeline_path) or not os.path.exists(self.new_pipeline_path):
            return {"error": "Pipeline 路径不存在"}

        old_pipe = self._load_pipeline(self.old_pipeline_path)
        new_pipe = self._load_pipeline(self.new_pipeline_path)

        # 提取步骤名称
        def _steps(pipe):
            if isinstance(pipe, Pipeline):
                return [name for name, _ in pipe.steps]
            return ["unknown"]

        old_steps = _steps(old_pipe)
        new_steps = _steps(new_pipe)

        return {
            "old_steps": old_steps,
            "new_steps": new_steps,
            "changed": old_steps != new_steps,
            "step_diff": {
                "added": [s for s in new_steps if s not in old_steps],
                "removed": [s for s in old_steps if s not in new_steps],
            },
        }

    def run(self, output_path: str = "drift_report.md") -> str:
        """
        执行完整 Drift 分析，输出 Markdown 报告
        """
        logger.info("===== Drift 分析开始 =====")

        model_drift = self.analyze_model_weights()
        pipeline_drift = self.analyze_pipeline_drift()

        lines = [
            "# 模型与代码 Drift 分析报告",
            "",
            "## 模型权重差异",
            "",
        ]

        # 基学习器差异
        lines.append("### 基学习器变更")
        lines.append("")
        lines.append("| 学习器 | 状态 | 旧类型 | 新类型 |")
        lines.append("|--------|------|--------|--------|")
        for d in model_drift.get("base_learners", []):
            lines.append(f"| {d['name']} | {d['status']} | {d['old_type']} | {d['new_type']} |")
        lines.append("")

        # 元学习器差异
        meta = model_drift.get("meta_learner", {})
        lines.append("### 元学习器权重变化")
        lines.append("")
        if meta.get("status") == "analyzed":
            lines.append(f"- 平均绝对变化: {meta['mean_abs_change']:.6f}")
            lines.append(f"- 最大绝对变化: {meta['max_abs_change']:.6f}")
            lines.append(f"- 权重形状: {meta['shape']}")
        else:
            lines.append(f"- 状态: {meta.get('status', 'unknown')}")
        lines.append("")

        # Pipeline 差异
        lines.append("## 预处理 Pipeline 变更")
        lines.append("")
        pipe = pipeline_drift
        lines.append(f"- 是否变更: {'是' if pipe.get('changed') else '否'}")
        if pipe.get("step_diff", {}).get("added"):
            lines.append(f"- 新增步骤: {pipe['step_diff']['added']}")
        if pipe.get("step_diff", {}).get("removed"):
            lines.append(f"- 移除步骤: {pipe['step_diff']['removed']}")
        lines.append("")

        report = "\n".join(lines)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info(f"Drift 分析报告已保存: {output_path}")
        return report
