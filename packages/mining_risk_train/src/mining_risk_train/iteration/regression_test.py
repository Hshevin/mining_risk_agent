"""
新旧模型背靠背对比测试（回归测试）
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from scipy.stats import kendalltau
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

from mining_risk_common.model.stacking import StackingRiskModel
from mining_risk_common.utils.config import get_config
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


def _model_predict_to_indices(model: StackingRiskModel, X: pd.DataFrame) -> np.ndarray:
    """将模型预测结果转为类别索引数组"""
    results = model.predict(X)
    if isinstance(results, dict):
        results = [results]
    y_pred = []
    for r in results:
        level = r["predicted_level"]
        pred_idx = model.risk_levels.index(level)
        y_pred.append(pred_idx)
    return np.array(y_pred)


class RegressionTester:
    """
    回归测试器
    在同源测试集上对比新旧模型性能
    """

    def __init__(
        self,
        old_model_path: Optional[str] = None,
        new_model_path: Optional[str] = None,
        test_data_path: Optional[str] = None,
    ):
        config = get_config()
        self.old_model_path = old_model_path or config.model.stacking.model_path
        self.new_model_path = new_model_path
        self.test_data_path = test_data_path

    def _load_model(self, path: str) -> StackingRiskModel:
        """加载模型"""
        model = StackingRiskModel()
        model.load(path)
        return model

    def _compute_shap_importance(self, model: StackingRiskModel, X: pd.DataFrame) -> np.ndarray:
        """计算 SHAP 特征重要性（取绝对值均值）"""
        try:
            meta_features = model._generate_meta_features(X)
            if model.shap_explainer is not None:
                import shap
                shap_values = model.shap_explainer(meta_features)
                sv = shap_values.values if hasattr(shap_values, "values") else shap_values
                if isinstance(sv, np.ndarray) and sv.ndim > 2:
                    sv = np.abs(sv).mean(axis=(0, 2))
                else:
                    sv = np.abs(sv).mean(axis=0)
                return sv
            else:
                # fallback: 使用元学习器系数
                if hasattr(model.meta_learner, "coef_"):
                    return np.abs(model.meta_learner.coef_).mean(axis=0)
        except Exception as e:
            logger.warning(f"SHAP 计算失败，使用 fallback: {e}")
            if hasattr(model.meta_learner, "coef_"):
                return np.abs(model.meta_learner.coef_).mean(axis=0)
        return np.ones(meta_features.shape[1])

    def run(
        self,
        X_test: Optional[pd.DataFrame] = None,
        y_test: Optional[pd.Series] = None,
        output_path: str = "regression_report.json",
    ) -> Dict:
        """
        执行回归测试

        Returns:
            回归测试报告字典
        """
        if self.new_model_path is None or not os.path.exists(self.new_model_path):
            raise FileNotFoundError(f"新模型不存在: {self.new_model_path}")
        if not os.path.exists(self.old_model_path):
            raise FileNotFoundError(f"旧模型不存在: {self.old_model_path}")

        logger.info("===== 回归测试开始 =====")

        # 加载模型
        old_model = self._load_model(self.old_model_path)
        new_model = self._load_model(self.new_model_path)

        # 测试数据
        if X_test is None or y_test is None:
            if self.test_data_path and os.path.exists(self.test_data_path):
                df = pd.read_csv(self.test_data_path)
                # 假设最后一列为标签
                X_test = df.iloc[:, :-1]
                y_test = df.iloc[:, -1]
            else:
                raise ValueError("未提供测试数据")

        y_true = y_test.values if hasattr(y_test, "values") else np.asarray(y_test)

        # 预测
        y_pred_old = _model_predict_to_indices(old_model, X_test)
        y_pred_new = _model_predict_to_indices(new_model, X_test)

        # 确保长度一致
        min_len = min(len(y_true), len(y_pred_old), len(y_pred_new))
        y_true = y_true[:min_len]
        y_pred_old = y_pred_old[:min_len]
        y_pred_new = y_pred_new[:min_len]

        # 计算指标
        def _metrics(y_pred):
            return {
                "accuracy": float(accuracy_score(y_true, y_pred)),
                "precision": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
                "recall": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
                "f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
                "auc": float(self._try_auc(y_true, y_pred)),
            }

        old_metrics = _metrics(y_pred_old)
        new_metrics = _metrics(y_pred_new)

        # SHAP 稳定性
        try:
            old_shap = self._compute_shap_importance(old_model, X_test)
            new_shap = self._compute_shap_importance(new_model, X_test)
            # Kendall Tau 需要排序后的索引
            old_ranks = np.argsort(np.argsort(-old_shap))
            new_ranks = np.argsort(np.argsort(-new_shap))
            tau, pvalue = kendalltau(old_ranks, new_ranks)
            shap_stability = float(tau) if tau is not None else 0.0
        except Exception as e:
            logger.warning(f"SHAP 稳定性计算失败: {e}")
            shap_stability = 0.0

        # 判定 PASS / DEGRADED
        config = get_config()
        min_f1 = config.harness.model_iteration.ci.regression.get("min_f1_score", 0.85)
        f1_ok = new_metrics["f1"] >= min_f1
        shap_ok = shap_stability >= 0.5  # 宽松阈值
        overall = "PASS" if (f1_ok and shap_ok) else "DEGRADED"

        report = {
            "status": overall,
            "old_model": self.old_model_path,
            "new_model": self.new_model_path,
            "test_samples": min_len,
            "old_metrics": old_metrics,
            "new_metrics": new_metrics,
            "shap_stability": {
                "kendall_tau": shap_stability,
                "threshold": 0.5,
                "passed": shap_ok,
            },
            "thresholds": {
                "min_f1": min_f1,
            },
            "timestamp": time.time(),
        }

        # 写入文件
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"回归测试完成: {overall}, 报告保存至 {output_path}")
        return report

    def _try_auc(self, y_true, y_pred) -> float:
        """尝试计算 AUC，多分类使用 OvR"""
        try:
            from sklearn.preprocessing import label_binarize
            classes = np.unique(y_true)
            if len(classes) < 2:
                return 0.0
            y_true_bin = label_binarize(y_true, classes=classes)
            # 对于多分类 AUC，简化处理
            if y_true_bin.ndim == 1:
                return float(roc_auc_score(y_true, y_pred))
            # 使用 macro OvR
            # 注意：这里 y_pred 是离散标签，AUC 用离散标签不够准确，但作为回归测试参考
            return float(roc_auc_score(y_true, y_pred, multi_class="ovo", average="macro"))
        except Exception as e:
            logger.debug(f"AUC 计算失败: {e}")
            return 0.0


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="回归测试")
    parser.add_argument("--old", required=True, help="旧模型路径")
    parser.add_argument("--new", required=True, help="新模型路径")
    parser.add_argument("--test", required=True, help="测试数据路径")
    parser.add_argument("--output", default="regression_report.json", help="输出报告路径")
    args = parser.parse_args()

    tester = RegressionTester(old_model_path=args.old, new_model_path=args.new, test_data_path=args.test)
    report = tester.run(output_path=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
