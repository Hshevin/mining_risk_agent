"""
模型可视化与可解释性报告生成模块
包含 SHAP 蜂群图、力导向图、混淆矩阵、ROC/PR 曲线、训练曲线、元学习器权重图
"""

import os
import warnings
from typing import Any, Dict, List, Optional

import joblib
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.metrics import (auc, average_precision_score, confusion_matrix,
                             precision_recall_curve, roc_curve)
from sklearn.preprocessing import label_binarize

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)

# 尝试设置中文字体
_try_fonts = ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei", "Arial Unicode MS"]
_font_set = False
for _font in _try_fonts:
    try:
        matplotlib.rcParams["font.family"] = [_font]
        matplotlib.rcParams["axes.unicode_minus"] = False
        _font_set = True
        break
    except Exception:
        continue
if not _font_set:
    logger.warning("未找到合适的中文字体，图表中文可能显示为方块")

warnings.filterwarnings("ignore")

try:
    import shap
except ImportError:
    shap = None


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _build_meta_feature_names(model) -> List[str]:
    """构建元学习器输入特征名"""
    feature_names = []
    for name in model.base_learners.keys():
        for lvl in model.risk_levels:
            feature_names.append(f"{name}_{lvl}")
    return feature_names


def _prepare_shap_explanation(model, meta_features: np.ndarray):
    """准备适用于可视化的 SHAP Explanation 对象（处理 multiclass）"""
    explainer = shap.Explainer(model.meta_learner, meta_features)
    shap_values = explainer(meta_features)
    feature_names = _build_meta_feature_names(model)

    if shap_values.values.ndim == 3:
        # multiclass: (samples, features, classes)
        pred_classes = np.argmax(model.meta_learner.predict_proba(meta_features), axis=1)
        values = np.zeros((shap_values.values.shape[0], shap_values.values.shape[1]))
        base = np.zeros(values.shape[0])
        for i in range(len(values)):
            values[i] = shap_values.values[i, :, pred_classes[i]]
            base[i] = shap_values.base_values[i, pred_classes[i]]
        return shap.Explanation(
            values,
            base_values=base,
            data=meta_features,
            feature_names=feature_names,
        )
    else:
        return shap_values


def plot_shap_summary(
    model,
    X_test: pd.DataFrame,
    output_dir: str = "reports/figures",
) -> str:
    """SHAP 全局蜂群图（基于元学习器）"""
    output_path = os.path.join(output_dir, "shap_summary_beeswarm.png")
    _ensure_dir(output_dir)

    if shap is None:
        logger.warning("SHAP 未安装，跳过蜂群图")
        return ""

    try:
        meta_features = model._generate_meta_features(X_test)
        if meta_features is None or meta_features.shape[0] == 0:
            logger.warning("元特征为空，无法绘制 SHAP 蜂群图")
            return ""

        exp = _prepare_shap_explanation(model, meta_features)

        fig = plt.figure(figsize=(12, 8))
        shap.plots.beeswarm(exp, show=False)
        plt.title("SHAP 全局蜂群图 (基学习器输出)", fontsize=14)
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"SHAP 蜂群图已保存至 {output_path}")
        return output_path
    except Exception as e:
        logger.warning(f"SHAP 蜂群图生成失败: {e}")
        return ""


def plot_shap_force_single(
    model,
    X_test: pd.DataFrame,
    output_dir: str = "reports/figures",
    sample_idx: int = 0,
) -> str:
    """单样本 SHAP 力导向图 (HTML)"""
    output_path = os.path.join(output_dir, f"shap_force_sample_{sample_idx}.html")
    _ensure_dir(output_dir)

    if shap is None:
        logger.warning("SHAP 未安装，跳过力导向图")
        return ""

    try:
        meta_features = model._generate_meta_features(X_test)
        if meta_features is None or meta_features.shape[0] == 0:
            return ""

        exp = _prepare_shap_explanation(model, meta_features)
        feature_names = _build_meta_feature_names(model)

        if sample_idx >= meta_features.shape[0]:
            sample_idx = 0

        base_val = float(exp.base_values[sample_idx])
        sv = exp.values[sample_idx]
        viz = shap.plots.force(
            base_val,
            sv,
            feature_names=feature_names,
            matplotlib=False,
            show=False,
        )
        html = viz.html() if hasattr(viz, "html") else str(viz)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"SHAP 力导向图已保存至 {output_path}")
        return output_path
    except Exception as e:
        logger.warning(f"SHAP 力导向图生成失败: {e}")
        return ""


def plot_confusion_matrix_heatmap(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    labels: Optional[List[str]] = None,
    output_dir: str = "reports/figures",
) -> str:
    """混淆矩阵热力图"""
    output_path = os.path.join(output_dir, "confusion_matrix_heatmap.png")
    _ensure_dir(output_dir)

    labels = labels or ["蓝", "黄", "橙", "红"]
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(labels))))

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt="d", cmap="YlOrRd",
                xticklabels=labels, yticklabels=labels, ax=ax)
    ax.set_title("混淆矩阵热力图", fontsize=14)
    ax.set_xlabel("预测标签", fontsize=12)
    ax.set_ylabel("真实标签", fontsize=12)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"混淆矩阵热力图已保存至 {output_path}")
    return output_path


def plot_roc_pr_curves(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    labels: Optional[List[str]] = None,
    output_dir: str = "reports/figures",
) -> List[str]:
    """ROC 与 PR 曲线 (4 类 OvR)"""
    labels = labels or ["蓝", "黄", "橙", "红"]
    n_classes = len(labels)
    y_true_bin = label_binarize(y_true, classes=list(range(n_classes)))

    paths = []

    # ROC 曲线
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = ["#3498db", "#f1c40f", "#e67e22", "#e74c3c"]
    for i in range(n_classes):
        if y_true_bin[:, i].sum() == 0:
            continue
        fpr, tpr, _ = roc_curve(y_true_bin[:, i], y_prob[:, i])
        roc_auc = auc(fpr, tpr)
        ax.plot(fpr, tpr, color=colors[i], lw=2,
                label=f"{labels[i]} (AUC={roc_auc:.2f})")
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel("假正例率", fontsize=12)
    ax.set_ylabel("真正例率", fontsize=12)
    ax.set_title("ROC 曲线 (OvR)", fontsize=14)
    ax.legend(loc="lower right")
    plt.tight_layout()
    roc_path = os.path.join(output_dir, "roc_curve_ovr.png")
    fig.savefig(roc_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(roc_path)

    # PR 曲线
    fig, ax = plt.subplots(figsize=(8, 6))
    for i in range(n_classes):
        if y_true_bin[:, i].sum() == 0:
            continue
        precision, recall, _ = precision_recall_curve(y_true_bin[:, i], y_prob[:, i])
        ap = average_precision_score(y_true_bin[:, i], y_prob[:, i])
        ax.plot(recall, precision, color=colors[i], lw=2,
                label=f"{labels[i]} (AP={ap:.2f})")
    ax.set_xlabel("召回率", fontsize=12)
    ax.set_ylabel("精确率", fontsize=12)
    ax.set_title("PR 曲线 (OvR)", fontsize=14)
    ax.legend(loc="lower left")
    plt.tight_layout()
    pr_path = os.path.join(output_dir, "pr_curve_ovr.png")
    fig.savefig(pr_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(pr_path)

    logger.info(f"ROC/PR 曲线已保存")
    return paths


def plot_training_curves(
    history: Optional[Dict[str, List[float]]] = None,
    output_dir: str = "reports/figures",
) -> str:
    """训练曲线（深度学习基学习器）"""
    output_path = os.path.join(output_dir, "training_curves.png")
    _ensure_dir(output_dir)

    fig, ax = plt.subplots(figsize=(8, 5))
    if history and "loss" in history:
        epochs = range(1, len(history["loss"]) + 1)
        ax.plot(epochs, history["loss"], "b-", label="训练损失")
        if "val_loss" in history:
            ax.plot(epochs, history["val_loss"], "r--", label="验证损失")
        ax.set_xlabel("Epoch")
        ax.set_ylabel("Loss")
        ax.set_title("深度学习基学习器训练曲线")
        ax.legend()
    else:
        ax.text(0.5, 0.5, "暂无训练历史数据", ha="center", va="center", fontsize=14)
        ax.set_title("训练曲线")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"训练曲线已保存至 {output_path}")
    return output_path


def plot_meta_learner_weights(
    model,
    output_dir: str = "reports/figures",
) -> str:
    """元学习器权重柱状图"""
    output_path = os.path.join(output_dir, "meta_learner_weights.png")
    _ensure_dir(output_dir)

    if not hasattr(model.meta_learner, "coef_"):
        logger.warning("元学习器无 coef_ 属性，跳过权重图")
        return ""

    coef = model.meta_learner.coef_  # shape: (n_classes, n_features) or (1, n_features)
    if coef.ndim == 1:
        coef = coef.reshape(1, -1)

    feature_names = []
    for name in model.base_learners.keys():
        for lvl in model.risk_levels:
            feature_names.append(f"{name}_{lvl}")

    n_classes = coef.shape[0]
    n_features = min(coef.shape[1], len(feature_names))
    x = np.arange(n_features)
    width = 0.2

    fig, ax = plt.subplots(figsize=(14, 6))
    colors = ["#3498db", "#f1c40f", "#e67e22", "#e74c3c"]
    for i in range(n_classes):
        label = model.risk_levels[i] if i < len(model.risk_levels) else f"class_{i}"
        ax.bar(x + i * width, coef[i, :n_features], width, label=label, color=colors[i % len(colors)])

    ax.set_xticks(x + width * (n_classes - 1) / 2)
    ax.set_xticklabels(feature_names[:n_features], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("权重系数", fontsize=12)
    ax.set_title("元学习器权重柱状图", fontsize=14)
    ax.legend()
    ax.axhline(0, color="black", linewidth=0.8)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"元学习器权重图已保存至 {output_path}")
    return output_path


def generate_all_reports(
    model,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    preprocessor: Optional[Any] = None,
    output_dir: str = "reports/figures",
    history: Optional[Dict[str, List[float]]] = None,
) -> Dict[str, str]:
    """
    生成全部可视化报告

    Args:
        model: 训练好的 StackingRiskModel
        X_test: 测试特征
        y_test: 测试标签
        preprocessor: 预处理管道（可选）
        output_dir: 输出目录
        history: 训练历史（可选）

    Returns:
        图表路径字典
    """
    _ensure_dir(output_dir)
    reports = {}

    # 1. SHAP 蜂群图
    reports["shap_summary"] = plot_shap_summary(model, X_test, output_dir)

    # 2. SHAP 力导向图
    reports["shap_force"] = plot_shap_force_single(model, X_test, output_dir, sample_idx=0)

    # 3. 混淆矩阵
    results = model.predict(X_test)
    if isinstance(results, dict):
        results = [results]
    y_pred = []
    y_prob = []
    for r in results:
        level = r["predicted_level"]
        pred_idx = model.risk_levels.index(level)
        y_pred.append(pred_idx)
        prob_vec = [r["probability_distribution"].get(lvl, 0.0) for lvl in model.risk_levels]
        y_prob.append(prob_vec)
    y_pred = np.array(y_pred)
    y_prob = np.array(y_prob)

    reports["confusion_matrix"] = plot_confusion_matrix_heatmap(
        y_test.values[:len(y_pred)], y_pred, model.risk_levels, output_dir
    )

    # 4. ROC/PR 曲线
    roc_pr_paths = plot_roc_pr_curves(
        y_test.values[:len(y_pred)], y_prob, model.risk_levels, output_dir
    )
    reports["roc_curve"] = roc_pr_paths[0] if roc_pr_paths else ""
    reports["pr_curve"] = roc_pr_paths[1] if len(roc_pr_paths) > 1 else ""

    # 5. 训练曲线
    reports["training_curves"] = plot_training_curves(history, output_dir)

    # 6. 元学习器权重
    reports["meta_weights"] = plot_meta_learner_weights(model, output_dir)

    logger.info(f"全部报告已生成，输出目录: {output_dir}")
    return reports


if __name__ == "__main__":
    # 示例运行：加载模型与测试数据后生成报告
    import sys
    from data.preprocessor import FeatureEngineeringPipeline

    config = get_config()
    model_path = config.model.stacking.model_path
    pipeline_path = config.model.stacking.pipeline_path

    if not os.path.exists(model_path):
        logger.error(f"模型文件不存在: {model_path}，请先运行 train.py 训练模型")
        sys.exit(1)

    logger.info("加载模型...")
    model_data = joblib.load(model_path)
    from model.stacking import StackingRiskModel
    model = StackingRiskModel()
    model.base_learners = model_data["base_learners"]
    model.meta_learner = model_data["meta_learner"]
    model.config = model_data["config"]
    model.risk_levels = model_data["risk_levels"]

    # 构造伪测试数据用于演示（实际应从真实数据生成）
    # 注意：需与训练时特征维度一致（示例数据为 19 维）
    np.random.seed(42)
    X_test = pd.DataFrame(np.random.randn(50, 19))
    y_test = pd.Series(np.random.randint(0, 4, size=50))

    reports = generate_all_reports(model, X_test, y_test)
    print("生成报告列表:")
    for k, v in reports.items():
        print(f"  {k}: {v}")
