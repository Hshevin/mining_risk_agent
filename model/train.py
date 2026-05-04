"""
模型训练脚本
执行数据加载、特征工程、Stacking 训练、评估、保存
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix,
                             f1_score, precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import TimeSeriesSplit

from data.loader import DataLoader
from data.preprocessor import FeatureEngineeringPipeline
from utils.config import get_config
from utils.exceptions import ModelTrainingError
from utils.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from model.stacking import StackingRiskModel


class StrictTimeSeriesSplit:
    """
    严格时序交叉验证分割器
    
    按指定时间列排序后，将数据切分为 n_splits+1 份，
    第 i 折使用前面所有份的数据训练，预测第 i 份数据。
    禁止未来信息泄露。
    """

    def __init__(self, n_splits: int = 5, time_col: Optional[str] = None):
        self.n_splits = n_splits
        self.time_col = time_col

    def split(self, X: pd.DataFrame, y=None, groups=None):
        """生成时序交叉验证的 train/test 索引"""
        n_samples = len(X)
        if n_samples < self.n_splits + 1:
            raise ValueError(f"样本数 {n_samples} 必须大于 n_splits+1={self.n_splits+1}")

        # 若指定了时间列，先按时间排序并返回排序后的索引
        if self.time_col and self.time_col in X.columns:
            sorted_idx = X[self.time_col].argsort().values
        else:
            sorted_idx = np.arange(n_samples)

        fold_sizes = np.full(self.n_splits + 1, n_samples // (self.n_splits + 1), dtype=int)
        fold_sizes[:n_samples % (self.n_splits + 1)] += 1
        fold_boundaries = np.cumsum(fold_sizes)

        for i in range(1, self.n_splits + 1):
            train_idx = sorted_idx[:fold_boundaries[i - 1]]
            test_idx = sorted_idx[fold_boundaries[i - 1]:fold_boundaries[i]]
            yield train_idx, test_idx

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits


def load_and_merge_data(raw_path: Optional[str] = None) -> pd.DataFrame:
    """加载并合并企业多表数据"""
    loader = DataLoader(raw_data_path=raw_path)
    tables = loader.load_directory()
    if not tables:
        raise ModelTrainingError("未加载到任何数据")
    
    # 注意：公开数据中各表主键无交集，无法直接关联。
    # 策略：以字段最丰富的表（szs_enterprise_safety）为主表。
    # 若存在关联键则尝试合并，否则独立使用各表
    primary_table = None
    for name, df in tables.items():
        if "安全生产标准化建设情况" in df.columns:
            primary_table = df.copy()
            break
    
    if primary_table is None:
        # fallback：使用第一个表
        primary_table = list(tables.values())[0].copy()
    
    # 尝试合并其他表（按报告历史ID等潜在关联键）
    join_candidates = ["报告历史ID", "报告历史id", "主键ID", "主键id", "统一社会信用代码", "统一信用代码"]
    for name, df in tables.items():
        if df is primary_table:
            continue
        for key in join_candidates:
            if key in primary_table.columns and key in df.columns:
                overlap = len(set(primary_table[key].dropna()) & set(df[key].dropna()))
                if overlap > 0:
                    overlap_cols = [c for c in df.columns if c in primary_table.columns and c != key]
                    rename_map = {c: f"{name}_{c}" for c in overlap_cols}
                    df_renamed = df.rename(columns=rename_map)
                    primary_table = pd.merge(primary_table, df_renamed, on=key, how="left")
                    break
    
    return primary_table


def sort_by_time(df: pd.DataFrame, preferred_time_col: Optional[str] = None) -> pd.DataFrame:
    """按时间列严格排序，确保时序一致性"""
    time_candidates = [preferred_time_col] if preferred_time_col else []
    time_candidates.extend(["report_time", "时间戳", "创建时间", "登记时间", "检查时间", "timestamp", "create_time"])
    # 去重并过滤空值
    seen = set()
    time_candidates = [c for c in time_candidates if c and not (c in seen or seen.add(c))]
    for col in time_candidates:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
            df = df.sort_values(by=col, ascending=True).reset_index(drop=True)
            logger.info(f"数据已按时间列 '{col}' 严格排序")
            return df
    logger.warning("未找到时间列，按原始顺序处理")
    return df.reset_index(drop=True)


def prepare_features(df: pd.DataFrame, pipeline_path: Optional[str] = None) -> Tuple[pd.DataFrame, pd.Series]:
    """
    执行特征工程

    Returns:
        (特征矩阵, 目标向量)
    """
    config = get_config()
    target_col = config.features.target_column
    if target_col not in df.columns:
        raise ModelTrainingError(f"数据中缺少目标列: {target_col}")

    raw_target = df[target_col]
    label_map = {"A": 0, "B": 1, "C": 2, "D": 3}

    if pd.api.types.is_numeric_dtype(raw_target):
        y = pd.to_numeric(raw_target, errors="coerce")
        y = y.where(y.isin([0, 1, 2, 3]))
    else:
        normalized = raw_target.astype(str).str.strip().str.upper()
        normalized = normalized.where(~raw_target.isna(), None)
        y = normalized.map(label_map)

    valid_mask = y.notna()
    dropped_rows = int((~valid_mask).sum())
    if dropped_rows > 0:
        logger.warning("目标列 '%s' 中有 %d 行无效标签，训练阶段将剔除", target_col, dropped_rows)

    if not valid_mask.any():
        raise ModelTrainingError(f"目标列 {target_col} 无有效标签，无法训练")

    y = y.loc[valid_mask].astype(int)
    feature_df = df.loc[valid_mask].copy()
    
    # 特征工程
    pipeline = FeatureEngineeringPipeline()
    X = pipeline.fit_transform(feature_df)
    
    # 保存 Pipeline
    if pipeline_path:
        os.makedirs(os.path.dirname(pipeline_path) or ".", exist_ok=True)
        pipeline.save(pipeline_path)
    
    return X, y


def split_data(
    X: pd.DataFrame,
    y: pd.Series,
    train_ratio: float = 0.7,
    val_ratio: float = 0.2,
) -> Dict[str, pd.DataFrame]:
    """
    按时序划分数据集

    Returns:
        {"train": (X_train, y_train), "val": (X_val, y_val), "test": (X_test, y_test)}
    """
    n = len(X)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    
    splits = {
        "train": (X.iloc[:train_end], y.iloc[:train_end]),
        "val": (X.iloc[train_end:val_end], y.iloc[train_end:val_end]),
        "test": (X.iloc[val_end:], y.iloc[val_end:]),
    }
    
    logger.info(
        f"数据集划分: 训练集: {len(splits['train'][0])}, "
        f"验证集: {len(splits['val'][0])}, 测试集: {len(splits['test'][0])}"
    )
    return splits


def evaluate_model(
    model: "StackingRiskModel",
    X: pd.DataFrame,
    y: pd.Series,
    dataset_name: str = "test",
) -> Dict[str, float]:
    """评估模型性能"""
    results = model.predict(X)
    if isinstance(results, dict):
        results = [results]
    
    y_pred = []
    for r in results:
        level = r["predicted_level"]
        pred_idx = model.risk_levels.index(level)
        y_pred.append(pred_idx)
    
    y_pred = np.array(y_pred)
    y_true = y.values[:len(y_pred)]
    
    metrics = {
        f"{dataset_name}_accuracy": accuracy_score(y_true, y_pred),
        f"{dataset_name}_precision": precision_score(y_true, y_pred, average="macro", zero_division=0),
        f"{dataset_name}_recall": recall_score(y_true, y_pred, average="macro", zero_division=0),
        f"{dataset_name}_f1": f1_score(y_true, y_pred, average="macro", zero_division=0),
    }
    
    logger.info(f"{dataset_name} 集评估结果")
    for k, v in metrics.items():
        logger.info(f"  {k}: {v:.4f}")
    
    # 混淆矩阵
    cm = confusion_matrix(y_true, y_pred, labels=list(range(4)))
    logger.info(f"混淆矩阵:\n{cm}")
    
    return metrics


def train_and_save(
    raw_data_path: Optional[str] = None,
    model_path: Optional[str] = None,
    pipeline_path: Optional[str] = None,
) -> "StackingRiskModel":
    """
    完整训练流程

    Returns:
        训练好的 StackingRiskModel
    """
    config = get_config()
    raw_data_path = raw_data_path or config.data.raw_data_path
    model_path = model_path or config.model.stacking.model_path
    pipeline_path = pipeline_path or config.model.stacking.pipeline_path
    
    # 1. 加载数据
    logger.info("Step 1: 加载数据...")
    loader = DataLoader(raw_data_path=raw_data_path)
    df = loader.load_merged_dataset()
    
    # 2. 严格时序排序
    logger.info("Step 2: 时序排序...")
    special_features = getattr(config.features, "special_features", {}) or {}
    preferred_time_col = special_features.get("time_col", "report_time")
    df = sort_by_time(df, preferred_time_col=preferred_time_col)
    
    # 3. 特征工程
    logger.info("Step 3: 特征工程...")
    X, y = prepare_features(df, pipeline_path=pipeline_path)
    
    # 4. 划分数据（时序）
    logger.info("Step 4: 划分数据...")
    splits = split_data(
        X, y,
        train_ratio=config.model.stacking.split_ratio.train,
        val_ratio=config.model.stacking.split_ratio.val,
    )
    
    X_train, y_train = splits["train"]
    X_val, y_val = splits["val"]
    X_test, y_test = splits["test"]
    
    # 合并训练+验证集用于最终训练
    X_train_full = pd.concat([X_train, X_val])
    y_train_full = pd.concat([y_train, y_val])
    
    # 5. 训练模型（内部使用 5 折时序 CV 生成 OOF 元特征）
    logger.info("Step 5: 训练 Stacking 模型...")
    from model.stacking import StackingRiskModel

    model = StackingRiskModel()
    model.fit(X_train_full, y_train_full)
    
    # 6. 评估
    logger.info("Step 6: 模型评估...")
    if len(X_test) > 0:
        evaluate_model(model, X_test, y_test, "test")
    
    # 7. 保存
    logger.info("Step 7: 保存模型...")
    os.makedirs(os.path.dirname(model_path) or ".", exist_ok=True)
    model.save(model_path)
    
    logger.info("训练流程完成")
    return model


if __name__ == "__main__":
    train_and_save()
