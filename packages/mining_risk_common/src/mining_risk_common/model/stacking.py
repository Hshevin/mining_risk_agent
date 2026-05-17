"""
Stacking 集成学习风险预测模型
严格对齐《建设方案》1.2-1.3 节
"""

import warnings
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit


def _create_logistic_regression(**params):
    """兼容新旧版本 sklearn 的 LogisticRegression 构造器"""
    try:
        return LogisticRegression(**params)
    except TypeError as e:
        if "multi_class" in str(e):
            params.pop("multi_class", None)
            return LogisticRegression(**params)
        raise

from mining_risk_common.utils.config import get_config
from mining_risk_common.utils.exceptions import ModelInferenceError, ModelTrainingError
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)

# 可选依赖延迟导入
try:
    import xgboost as xgb
except ImportError:
    xgb = None

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

try:
    import catboost as cb
except ImportError:
    cb = None

try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers
except ImportError:
    tf = None

try:
    import shap
except ImportError:
    shap = None

warnings.filterwarnings("ignore")


def _to_numpy(X: Union[pd.DataFrame, np.ndarray]) -> np.ndarray:
    """统一将输入转为 numpy 数组"""
    if isinstance(X, pd.DataFrame):
        return X.values.astype(np.float32)
    return np.asarray(X, dtype=np.float32)


class DeepLearningBaseLearner:
    """深度学习基学习器抽象基类"""

    def __init__(self, model_type: str, params: Dict[str, Any]):
        self.model_type = model_type
        self.params = params
        self.model: Optional[Any] = None
        self._input_dim: Optional[int] = None

    def _build_model(self, input_dim: int) -> None:
        raise NotImplementedError

    def fit(self, X: Union[pd.DataFrame, np.ndarray], y: Union[pd.Series, np.ndarray],
            X_val: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            y_val: Optional[Union[pd.Series, np.ndarray]] = None) -> None:
        raise NotImplementedError

    def predict_proba(self, X: Union[pd.DataFrame, np.ndarray]) -> np.ndarray:
        raise NotImplementedError


class MLPBaseLearner(DeepLearningBaseLearner):
    """MLP 基学习器：Dense(128)→Dense(64)→Dense(4) + Dropout0.3 + ReLU"""

    def _build_model(self, input_dim: int) -> None:
        if tf is None:
            self.model = None
            return
        hidden = self.params.get("hidden_layers", [128, 64])
        dropout = self.params.get("dropout_rate", 0.3)
        inputs = keras.Input(shape=(input_dim,))
        x = inputs
        for units in hidden:
            x = layers.Dense(units, activation="relu")(x)
            x = layers.Dropout(dropout)(x)
        outputs = layers.Dense(4, activation="softmax")(x)
        self.model = keras.Model(inputs, outputs)
        self.model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=self.params.get("learning_rate", 0.001)),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )

    def fit(self, X: Union[pd.DataFrame, np.ndarray], y: Union[pd.Series, np.ndarray],
            X_val: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            y_val: Optional[Union[pd.Series, np.ndarray]] = None) -> None:
        if tf is None:
            return
        X_arr = _to_numpy(X)
        y_arr = np.asarray(y, dtype=int)
        input_dim = X_arr.shape[1]
        if self.model is None or self._input_dim != input_dim:
            self._input_dim = input_dim
            self._build_model(input_dim)
        if self.model is None:
            return
        callbacks = [
            keras.callbacks.EarlyStopping(
                monitor="val_loss",
                patience=self.params.get("early_stopping_patience", 10),
                restore_best_weights=True,
            )
        ]
        X_val_arr = _to_numpy(X_val) if X_val is not None else None
        y_val_arr = np.asarray(y_val, dtype=int) if y_val is not None else None
        validation_data = (X_val_arr, y_val_arr) if X_val_arr is not None and y_val_arr is not None else None
        self.model.fit(
            X_arr, y_arr,
            epochs=self.params.get("epochs", 100),
            batch_size=self.params.get("batch_size", 32),
            validation_data=validation_data,
            callbacks=callbacks,
            verbose=0,
        )

    def predict_proba(self, X: Union[pd.DataFrame, np.ndarray]) -> np.ndarray:
        X_arr = _to_numpy(X)
        if self.model is None:
            return np.ones((X_arr.shape[0], 4)) / 4.0
        return self.model.predict(X_arr, verbose=0)


class CNN1DBaseLearner(DeepLearningBaseLearner):
    """1D-CNN 基学习器：Conv1D64→MaxPool→Conv1D128→MaxPool→Flatten→Dense64, Dropout0.3"""

    def _build_model(self, input_dim: int) -> None:
        if tf is None:
            self.model = None
            return
        conv_layers = self.params.get("conv_layers", [{"filters": 64, "kernel_size": 3},
                                                       {"filters": 128, "kernel_size": 3}])
        dropout = self.params.get("dropout_rate", 0.3)
        dense_units = self.params.get("dense_units", 64)

        inputs = keras.Input(shape=(input_dim, 1))
        x = inputs
        for conv in conv_layers:
            x = layers.Conv1D(conv["filters"], conv["kernel_size"], activation="relu", padding="same")(x)
            x = layers.MaxPooling1D(pool_size=2, padding="same")(x)
        x = layers.Flatten()(x)
        x = layers.Dense(dense_units, activation="relu")(x)
        x = layers.Dropout(dropout)(x)
        outputs = layers.Dense(4, activation="softmax")(x)
        self.model = keras.Model(inputs, outputs)
        self.model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=self.params.get("learning_rate", 0.001)),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )

    def fit(self, X: Union[pd.DataFrame, np.ndarray], y: Union[pd.Series, np.ndarray],
            X_val: Optional[Union[pd.DataFrame, np.ndarray]] = None,
            y_val: Optional[Union[pd.Series, np.ndarray]] = None) -> None:
        if tf is None:
            return
        X_arr = _to_numpy(X)
        y_arr = np.asarray(y, dtype=int)
        input_dim = X_arr.shape[1]
        if self.model is None or self._input_dim != input_dim:
            self._input_dim = input_dim
            self._build_model(input_dim)
        if self.model is None:
            return
        X_arr = np.expand_dims(X_arr, axis=-1)
        X_val_arr = _to_numpy(X_val) if X_val is not None else None
        X_val_arr = np.expand_dims(X_val_arr, axis=-1) if X_val_arr is not None else None
        y_val_arr = np.asarray(y_val, dtype=int) if y_val is not None else None
        callbacks = [
            keras.callbacks.EarlyStopping(
                monitor="val_loss",
                patience=self.params.get("early_stopping_patience", 10),
                restore_best_weights=True,
            )
        ]
        validation_data = (X_val_arr, y_val_arr) if X_val_arr is not None and y_val_arr is not None else None
        self.model.fit(
            X_arr, y_arr,
            epochs=self.params.get("epochs", 100),
            batch_size=self.params.get("batch_size", 32),
            validation_data=validation_data,
            callbacks=callbacks,
            verbose=0,
        )

    def predict_proba(self, X: Union[pd.DataFrame, np.ndarray]) -> np.ndarray:
        X_arr = _to_numpy(X)
        if self.model is None:
            return np.ones((X_arr.shape[0], 4)) / 4.0
        X_arr = np.expand_dims(X_arr, axis=-1)
        return self.model.predict(X_arr, verbose=0)


class StackingRiskModel:
    """
    双层 Stacking 风险预测模型

    第一层：7 个异构基学习器
    第二层：带 L1+L2 正则化的弹性网络逻辑回归
    """

    def __init__(self):
        config = get_config()
        self.config = config.model.stacking
        self.risk_levels = config.model.risk_levels
        self.n_classes = len(self.risk_levels)
        self.base_learners: Dict[str, Any] = {}
        self.meta_learner: Optional[Any] = None
        self.cv_splitter = TimeSeriesSplit(n_splits=self.config.cv.n_splits)
        self._build_base_learners()
        self._build_meta_learner()
        self.shap_explainer: Optional[Any] = None
        self.n_features_in_: Optional[int] = None
        self.feature_names_in_: Optional[List[str]] = None

    def _build_base_learners(self) -> None:
        """构建第一层基学习器"""
        for bl_config in self.config.base_learners:
            name = bl_config.name
            model_type = bl_config.type
            params = bl_config.params

            if model_type == "logistic_regression":
                model = _create_logistic_regression(**params)
            elif model_type == "xgboost":
                if xgb is None:
                    logger.warning("XGBoost 未安装，使用随机森林替代")
                    model = RandomForestClassifier(n_estimators=100)
                else:
                    model = xgb.XGBClassifier(**params)
            elif model_type == "lightgbm":
                if lgb is None:
                    logger.warning("LightGBM 未安装，使用随机森林替代")
                    model = RandomForestClassifier(n_estimators=100)
                else:
                    model = lgb.LGBMClassifier(**params)
            elif model_type == "catboost":
                if cb is None:
                    logger.warning("CatBoost 未安装，使用随机森林替代")
                    model = RandomForestClassifier(n_estimators=100)
                else:
                    model = cb.CatBoostClassifier(**params)
            elif model_type == "random_forest":
                model = RandomForestClassifier(**params)
            elif model_type == "mlp":
                model = MLPBaseLearner("mlp", params)
            elif model_type == "cnn1d":
                model = CNN1DBaseLearner("cnn1d", params)
            else:
                raise ModelTrainingError(f"未知的基学习器类型: {model_type}")

            self.base_learners[name] = model
            logger.info(f"基学习器 {name} ({model_type}) 已初始化")

    def _build_meta_learner(self) -> None:
        """构建第二层元学习器"""
        params = self.config.meta_learner.params
        self.meta_learner = _create_logistic_regression(**params)
        logger.info("元学习器已初始化")

    def fit(self, X: Union[pd.DataFrame, np.ndarray], y: Union[pd.Series, np.ndarray]) -> None:
        """
        训练 Stacking 模型

        采用 5 折时序交叉验证（OOF）防止数据泄露
        """
        try:
            X_arr = _to_numpy(X)
            y_arr = np.asarray(y, dtype=int)
            self.n_features_in_ = int(X_arr.shape[1])
            self.feature_names_in_ = list(X.columns) if isinstance(X, pd.DataFrame) else None

            n_samples = X_arr.shape[0]
            n_base = len(self.base_learners)

            # OOF 元特征矩阵: 28维 (7模型 × 4类)
            oof_meta_features = np.zeros((n_samples, n_base * self.n_classes))

            # 时序交叉验证
            fold_idx = 0
            for train_idx, val_idx in self.cv_splitter.split(X_arr):
                fold_idx += 1
                logger.info(f"时序交叉验证第 {fold_idx} 折")

                X_train, X_val = X_arr[train_idx], X_arr[val_idx]
                y_train, y_val = y_arr[train_idx], y_arr[val_idx]

                for bi, (name, model) in enumerate(self.base_learners.items()):
                    if isinstance(model, DeepLearningBaseLearner):
                        model.fit(X_train, y_train, X_val, y_val)
                        proba = model.predict_proba(X_val)
                    else:
                        model.fit(X_train, y_train)
                        proba = model.predict_proba(X_val)

                    # 确保概率矩阵维度为 n_classes
                    if proba.shape[1] != self.n_classes:
                        full_proba = np.zeros((proba.shape[0], self.n_classes))
                        unique_classes = np.unique(y_train)
                        for i, cls in enumerate(unique_classes):
                            if i < proba.shape[1] and cls < self.n_classes:
                                full_proba[:, cls] = proba[:, i]
                        row_sums = full_proba.sum(axis=1, keepdims=True)
                        row_sums[row_sums == 0] = 1
                        proba = full_proba / row_sums

                    col_start = bi * self.n_classes
                    col_end = col_start + self.n_classes
                    oof_meta_features[val_idx, col_start:col_end] = proba

            # 检查 OOF 无 NaN
            if np.isnan(oof_meta_features).any():
                logger.warning("OOF 元特征中存在 NaN，已填充为 0")
                oof_meta_features = np.nan_to_num(oof_meta_features, nan=0.0)

            # 在完整数据上重新训练基学习器（用于后续预测）
            logger.info("在完整数据上训练基学习器...")
            for name, model in self.base_learners.items():
                if isinstance(model, DeepLearningBaseLearner):
                    model.fit(X_arr, y_arr)
                else:
                    model.fit(X_arr, y_arr)

            # 训练元学习器
            logger.info("训练元学习器...")
            self.meta_learner.fit(oof_meta_features, y_arr)

            # 初始化 SHAP
            if shap is not None:
                try:
                    self.shap_explainer = shap.Explainer(self.meta_learner, oof_meta_features)
                    logger.info("SHAP explainer 已初始化")
                except Exception as e:
                    logger.warning(f"SHAP 初始化失败: {e}")

            logger.info("Stacking 模型训练完成")

        except Exception as e:
            raise ModelTrainingError(f"模型训练失败: {e}")

    def _generate_meta_features(self, X: Union[pd.DataFrame, np.ndarray]) -> np.ndarray:
        """生成元特征矩阵（用于元学习器输入和 SHAP 解释）"""
        X_arr = _to_numpy(X)
        n_samples = X_arr.shape[0]
        n_base = len(self.base_learners)
        meta_features = np.zeros((n_samples, n_base * self.n_classes))
        for bi, (name, model) in enumerate(self.base_learners.items()):
            if isinstance(model, DeepLearningBaseLearner):
                proba = model.predict_proba(X_arr)
            else:
                proba = model.predict_proba(X_arr)
            col_start = bi * self.n_classes
            col_end = col_start + self.n_classes
            meta_features[:, col_start:col_end] = proba
        meta_features = np.nan_to_num(meta_features, nan=0.0)
        return meta_features

    def _expected_input_dim(self) -> Optional[int]:
        """Return the feature dimension learned by this artifact, if available."""
        if self.n_features_in_ is not None:
            return int(self.n_features_in_)

        for model in self.base_learners.values():
            dim = getattr(model, "n_features_in_", None)
            if dim is not None:
                return int(dim)
            dim = getattr(model, "_input_dim", None)
            if dim is not None:
                return int(dim)
        return None

    def predict(self, X: Union[pd.DataFrame, np.ndarray]) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        预测风险等级

        Args:
            X: 特征矩阵

        Returns:
            包含预测结果的字典或列表
        """
        try:
            X_arr = _to_numpy(X)
            expected_dim = self._expected_input_dim()
            actual_dim = int(X_arr.shape[1])
            if expected_dim is not None and actual_dim != expected_dim:
                raise ValueError(
                    "input feature dimension mismatch: "
                    f"got {actual_dim}, expected {expected_dim}. "
                    "Check that model_path and pipeline_path come from the same training run."
                )
            n_samples = X_arr.shape[0]

            meta_features = self._generate_meta_features(X)

            # 元学习器预测
            proba = self.meta_learner.predict_proba(meta_features)
            pred_class = np.argmax(proba, axis=1)
            pred_labels = [self.risk_levels[i] for i in pred_class]

            # SHAP 归因
            shap_contributions = self._compute_shap(X, meta_features)

            results = []
            for i in range(n_samples):
                result = {
                    "predicted_level": pred_labels[i],
                    "probability_distribution": {
                        self.risk_levels[j]: round(float(proba[i][j]), 4)
                        for j in range(self.n_classes)
                    },
                    "shap_contributions": shap_contributions[i] if i < len(shap_contributions) else [],
                }
                results.append(result)

            return results[0] if n_samples == 1 else results

        except Exception as e:
            raise ModelInferenceError(f"模型推理失败: {e}")

    def _compute_shap(self, X: Union[pd.DataFrame, np.ndarray], meta_features: np.ndarray) -> List[List[Dict[str, Any]]]:
        """计算 SHAP 特征贡献度（Top3）"""
        contributions = []
        try:
            if self.shap_explainer is None and shap is not None:
                self.shap_explainer = shap.Explainer(self.meta_learner, meta_features)

            if self.shap_explainer is not None:
                shap_values = self.shap_explainer(meta_features)
                for i in range(meta_features.shape[0]):
                    sv = shap_values.values[i] if hasattr(shap_values, "values") else shap_values[i]
                    if isinstance(sv, np.ndarray) and sv.ndim > 1:
                        pred_class = int(np.argmax(self.meta_learner.predict_proba(meta_features[i:i+1])))
                        sv = sv[:, pred_class] if sv.shape[1] > 1 else sv.flatten()

                    feature_names = list(X.columns) if isinstance(X, pd.DataFrame) else [f"f{j}" for j in range(meta_features.shape[1])]
                    n_features = min(len(feature_names), len(sv))
                    agg_importance = np.abs(sv[:n_features])

                    top_idx = np.argsort(-agg_importance)[:3]
                    top_contrib = [
                        {"feature": feature_names[idx], "contribution": round(float(agg_importance[idx]), 4)}
                        for idx in top_idx if idx < len(feature_names)
                    ]
                    contributions.append(top_contrib)
            else:
                # fallback：使用元学习器系数
                if hasattr(self.meta_learner, "coef_"):
                    coef = np.abs(self.meta_learner.coef_).mean(axis=0)
                    feature_names = list(X.columns) if isinstance(X, pd.DataFrame) else [f"f{j}" for j in range(meta_features.shape[1])]
                    n_features = min(len(feature_names), len(coef))
                    agg = coef[:n_features]
                    top_idx = np.argsort(-agg)[:3]
                    top_contrib = [
                        {"feature": feature_names[idx], "contribution": round(float(agg[idx]), 4)}
                        for idx in top_idx if idx < len(feature_names)
                    ]
                    contributions.append(top_contrib)
                else:
                    contributions.append([])
        except Exception as e:
            logger.warning(f"SHAP 计算失败: {e}")
            contributions = [[] for _ in range(meta_features.shape[0])]

        # 确保返回与样本数一致的结果
        while len(contributions) < meta_features.shape[0]:
            contributions.append([])
        return contributions[:meta_features.shape[0]]

    def save(self, path: str) -> None:
        """保存模型"""
        joblib.dump({
            "base_learners": self.base_learners,
            "meta_learner": self.meta_learner,
            "config": self.config,
            "risk_levels": self.risk_levels,
            "n_features_in": self.n_features_in_,
            "feature_names_in": self.feature_names_in_,
        }, path)
        logger.info(f"模型已保存至 {path}")

    def load(self, path: str) -> None:
        """加载模型"""
        data = joblib.load(path)
        self.base_learners = data["base_learners"]
        self.meta_learner = data["meta_learner"]
        self.config = data["config"]
        self.risk_levels = data["risk_levels"]
        meta_fitted = hasattr(self.meta_learner, "coef_")
        base_summary = ", ".join(
            f"{name}={type(model).__name__}" for name, model in self.base_learners.items()
        )
        logger.info(
            f"模型已从 {path} 加载 (meta_fitted={meta_fitted}, base_learners=[{base_summary}])"
        )
        if not meta_fitted:
            logger.warning(
                "元学习器未 fitted，predict() 将抛 ModelInferenceError；请确认 pkl 是否由 train.py 完整训练后保存。"
            )
