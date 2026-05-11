"""
训练入口与预处理关键回归测试
"""

import numpy as np
import pandas as pd

from data.preprocessor import NumericTransformer, TimeDecayWeightTransformer
from model.train import prepare_features, sort_by_time
from utils.config import ConfigManager


def _reset_config_state() -> None:
    ConfigManager._instance = None
    ConfigManager._config = None


def test_prepare_features_uses_target_column_and_drops_invalid_labels(monkeypatch):
    monkeypatch.setenv("GLM5_API_KEY", "test-key")
    _reset_config_state()

    df = pd.DataFrame(
        {
            "new_level": ["A", "B", None, "X", "D"],
            "above_designated": [1, 0, 1, 1, 0],
            "report_time": ["2024-01-01"] * 5,
        }
    )

    X, y = prepare_features(df)

    assert len(X) == 3
    assert y.tolist() == [0, 1, 3]


def test_sort_by_time_uses_preferred_time_column():
    df = pd.DataFrame(
        {
            "report_time": ["2024-01-03", "2024-01-01", "2024-01-02"],
            "value": [3, 1, 2],
        }
    )
    sorted_df = sort_by_time(df, preferred_time_col="report_time")
    assert sorted_df["value"].tolist() == [1, 2, 3]


def test_numeric_transformer_uses_fit_fill_values_in_transform():
    train_df = pd.DataFrame({"col": [1.0, 2.0, np.nan]})
    trans = NumericTransformer()
    trans.fit(train_df)

    expected_fill = trans.fill_values_["col"]
    expected = trans.transform(pd.DataFrame({"col": [expected_fill]})).iloc[0, 0]
    actual = trans.transform(pd.DataFrame({"col": [np.nan]})).iloc[0, 0]

    assert actual == expected
    assert expected_fill > 0


def test_time_decay_missing_time_weight_defaults_to_high_risk():
    df = pd.DataFrame(
        {
            "report_time": [None, "2023-01-01"],
            "trouble_total_count": [10, 10],
        }
    )
    transformer = TimeDecayWeightTransformer(
        time_col="report_time",
        value_cols=["trouble_total_count"],
        reference_year=2024,
        missing_time_weight=1.0,
    )
    result = transformer.fit_transform(df)

    assert result["trouble_total_count_decay_weighted"].tolist() == [10.0, 7.0]
