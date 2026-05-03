"""
自动训练流水线
数据清洗 -> 特征工程 -> 时序CV训练 -> 候选模型产出 -> 自动序列化
"""

import os
import time
from pathlib import Path
from typing import Dict, Optional

import joblib

from data.preprocessor import FeatureEngineeringPipeline
from model.stacking import StackingRiskModel
from model.train import evaluate_model, load_and_merge_data, prepare_features, split_data
from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


class TrainingPipeline:
    """
    自动训练流水线
    """

    def __init__(
        self,
        raw_data_path: Optional[str] = None,
        models_dir: Optional[str] = None,
    ):
        config = get_config()
        self.raw_data_path = raw_data_path or config.data.raw_data_path
        self.models_dir = models_dir or "models"
        self.config = config

    def _next_model_version(self) -> str:
        """生成下一个模型版本号"""
        existing = list(Path(self.models_dir).glob("stacking_risk_v*.pkl"))
        max_v = 0
        for f in existing:
            try:
                v = int(f.stem.split("_v")[-1])
                max_v = max(max_v, v)
            except ValueError:
                continue
        return f"v{max_v + 1}"

    def run(
        self,
        model_version: Optional[str] = None,
        save_pipeline: bool = True,
    ) -> Dict:
        """
        执行完整训练流水线

        Returns:
            {
                "model_version": str,
                "model_path": str,
                "pipeline_path": str,
                "metrics": dict,
                "status": str,
            }
        """
        model_version = model_version or self._next_model_version()
        model_path = os.path.join(self.models_dir, f"stacking_risk_{model_version}.pkl")
        pipeline_path = os.path.join(self.models_dir, f"preprocessing_pipeline_{model_version}.pkl")

        logger.info(f"===== 自动训练流水线启动: {model_version} =====")

        # 1. 加载数据
        logger.info("Step 1: 加载并合并数据...")
        df = load_and_merge_data(self.raw_data_path)

        # 2. 特征工程
        logger.info("Step 2: 特征工程...")
        X, y = prepare_features(df, pipeline_path=pipeline_path if save_pipeline else None)

        # 3. 划分数据
        logger.info("Step 3: 划分数据集...")
        splits = split_data(
            X, y,
            train_ratio=self.config.model.stacking.split_ratio.train,
            val_ratio=self.config.model.stacking.split_ratio.val,
        )
        X_train, y_train = splits["train"]
        X_val, y_val = splits["val"]
        X_test, y_test = splits["test"]

        X_train_full = __import__("pandas", fromlist=["concat"]).concat([X_train, X_val])
        y_train_full = __import__("pandas", fromlist=["concat"]).concat([y_train, y_val])

        # 4. 时序CV训练
        logger.info("Step 4: 训练 Stacking 模型（时序CV）...")
        model = StackingRiskModel()
        model.fit(X_train_full, y_train_full)

        # 5. 评估
        logger.info("Step 5: 模型评估...")
        metrics = {}
        if len(X_test) > 0:
            metrics = evaluate_model(model, X_test, y_test, dataset_name="test")

        # 6. 序列化
        logger.info("Step 6: 序列化模型...")
        os.makedirs(self.models_dir, exist_ok=True)
        model.save(model_path)

        # 同时更新默认模型路径的软链接/副本（兼容旧接口）
        default_model_path = self.config.model.stacking.model_path
        default_pipeline_path = self.config.model.stacking.pipeline_path
        try:
            import shutil
            shutil.copy2(model_path, default_model_path)
            if save_pipeline and os.path.exists(pipeline_path):
                shutil.copy2(pipeline_path, default_pipeline_path)
            logger.info(f"已同步到默认路径: {default_model_path}")
        except Exception as e:
            logger.warning(f"同步到默认路径失败: {e}")

        logger.info(f"===== 训练流水线完成: {model_version} =====")

        return {
            "model_version": model_version,
            "model_path": model_path,
            "pipeline_path": pipeline_path if save_pipeline else None,
            "metrics": metrics,
            "status": "SUCCESS",
            "timestamp": time.time(),
        }


def main():
    """命令行入口：python -m mining_risk_agent.iteration.pipeline"""
    pipeline = TrainingPipeline()
    result = pipeline.run()
    print(result)


if __name__ == "__main__":
    main()
