"""
模型模块单元测试
"""

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
