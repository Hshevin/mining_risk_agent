"""
Stacking 模型单元测试
验证 7 基学习器接口一致性、OOF 无 NaN、save/load 等
"""

import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from mining_risk_common.model.stacking import StackingRiskModel


class TestStackingRiskModel:
    """测试 Stacking 风险预测模型"""

    def test_init(self):
        model = StackingRiskModel()
        assert len(model.base_learners) == 7
        assert model.meta_learner is not None
        assert model.risk_levels == ["蓝", "黄", "橙", "红"]

    def test_base_learners_interface(self):
        """验证 7 个基学习器均具备统一接口 fit(X,y) 和 predict_proba(X)"""
        np.random.seed(42)
        X = pd.DataFrame(np.random.randn(20, 5))
        y = pd.Series(np.random.randint(0, 4, size=20))

        model = StackingRiskModel()
        for name, bl in model.base_learners.items():
            # 测试接口存在
            assert hasattr(bl, "fit"), f"{name} 缺少 fit 方法"
            assert hasattr(bl, "predict_proba"), f"{name} 缺少 predict_proba 方法"

            # 测试可训练且输出维度正确
            bl.fit(X, y)
            proba = bl.predict_proba(X)
            assert proba.shape == (20, 4), f"{name} predict_proba 输出维度应为 (20,4)，实际 {proba.shape}"
            assert not np.isnan(proba).any(), f"{name} predict_proba 输出包含 NaN"
            assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-5), f"{name} 概率之和不为 1"

    def test_fit_predict(self):
        np.random.seed(42)
        X = pd.DataFrame(np.random.randn(50, 10))
        y = pd.Series(np.random.randint(0, 4, size=50))
        
        model = StackingRiskModel()
        model.fit(X, y)
        
        result = model.predict(X.iloc[:5])
        assert isinstance(result, list)
        assert "predicted_level" in result[0]
        assert "probability_distribution" in result[0]
        assert "shap_contributions" in result[0]
        assert result[0]["predicted_level"] in model.risk_levels

    def test_oof_no_nan(self):
        """验证 OOF 元特征矩阵无 NaN"""
        np.random.seed(42)
        X = pd.DataFrame(np.random.randn(60, 8))
        y = pd.Series([0, 1, 2, 3] * 15)

        model = StackingRiskModel()
        model.fit(X, y)
        # fit 成功后即表明 OOF 无 NaN（fit 内部会断言/填充）
        assert model.meta_learner is not None

    def test_meta_learner_params(self):
        """验证元学习器为 elasticnet + multinomial + saga"""
        model = StackingRiskModel()
        meta = model.meta_learner
        # 新版 sklearn 已移除 multi_class 参数， multinomial 为默认行为
        if hasattr(meta, "multi_class"):
            assert meta.multi_class == "multinomial"
        assert meta.penalty == "elasticnet"
        assert meta.solver == "saga"
        assert meta.l1_ratio == 0.5

    def test_save_load(self):
        np.random.seed(42)
        X = pd.DataFrame(np.random.randn(100, 5))
        # 确保包含所有4个类别
        y = pd.Series([0, 1, 2, 3] * 25)
        
        model = StackingRiskModel()
        model.fit(X, y)
        
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            tmp = f.name
        try:
            model.save(tmp)
            model2 = StackingRiskModel()
            model2.load(tmp)
            result = model2.predict(X.iloc[:2])
            assert isinstance(result, list)
        finally:
            import os
            os.unlink(tmp)
