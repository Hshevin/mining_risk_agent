"""
数据预处理与特征工程单元测试
覆盖特殊逻辑：干湿除尘比例、有限空间 OR、危化品 OR、时间衰减加权、
地理围栏、企业聚合、数据可信度系数等
"""

import numpy as np
import pandas as pd
import pytest

from mining_risk_common.dataplane.preprocessor import (
    BinaryEncoder,
    ConfinedSpaceORTransformer,
    DataCredibilityTransformer,
    DustRemovalRatioTransformer,
    EnterpriseAggregator,
    EnumRiskMapper,
    FeatureEngineeringPipeline,
    GeoFenceTransformer,
    HazardousChemicalORTransformer,
    IndustryRiskCoefficient,
    MissingValueHandler,
    NumericTransformer,
    TextRiskExtractor,
    TimeDecayWeightTransformer,
)


class TestBinaryEncoder:
    def test_encode(self):
        df = pd.DataFrame({"col": ["是", "否", "1", "0", "有", "无", None]})
        enc = BinaryEncoder()
        result = enc.fit_transform(df)
        assert result["col"].tolist() == [1, 0, 1, 0, 1, 0, 0]


class TestNumericTransformer:
    def test_transform(self):
        df = pd.DataFrame({"col": [1.0, 2.0, 3.0, 100.0, np.nan]})
        trans = NumericTransformer(clip_quantile=0.99)
        result = trans.fit_transform(df)
        assert result.shape == (5, 1)
        assert result["col"].max() <= 1.0
        assert result["col"].min() >= 0.0


class TestTextRiskExtractor:
    def test_extract(self):
        df = pd.DataFrame({"col": ["正常生产", "", None, "发生瓦斯爆炸事故"]})
        ext = TextRiskExtractor()
        result = ext.fit_transform(df)
        assert "col_completeness" in result.columns
        assert "col_risk_words" in result.columns
        assert result.loc[1, "col_completeness"] == 1.0
        assert result.loc[3, "col_risk_words"] > 0


class TestIndustryRiskCoefficient:
    def test_map(self):
        df = pd.DataFrame({"行业": ["采矿业", "制造业", "化工", "其他"]})
        mapper = IndustryRiskCoefficient()
        result = mapper.fit_transform(df)
        assert "industry_risk_coefficient" in result.columns
        assert result.loc[0, "industry_risk_coefficient"] == 1.5
        assert result.loc[1, "industry_risk_coefficient"] == 1.0


class TestMissingValueHandler:
    def test_handle(self):
        df = pd.DataFrame({
            "management": [1.0, np.nan, 2.0],
            "objective": [10.0, 20.0, np.nan],
        })
        handler = MissingValueHandler(
            management_fields=["management"],
            objective_fields=["objective"],
            management_score=0.7,
        )
        result = handler.fit_transform(df)
        assert result.loc[1, "management"] == 0.7
        assert not pd.isna(result.loc[2, "objective"])


class TestDustRemovalRatioTransformer:
    def test_ratio(self):
        df = pd.DataFrame({
            "干式除尘": [10, 0, 5],
            "湿式除尘": [5, 10, 5],
        })
        trans = DustRemovalRatioTransformer()
        result = trans.fit_transform(df)
        assert "dry_removal_ratio" in result.columns
        assert "wet_removal_ratio" in result.columns
        assert result.loc[0, "dry_removal_ratio"] == pytest.approx(10 / 15, abs=1e-5)
        assert result.loc[0, "wet_removal_ratio"] == pytest.approx(5 / 15, abs=1e-5)


class TestConfinedSpaceORTransformer:
    def test_or_logic(self):
        df = pd.DataFrame({
            "是否有限空间": [0, 1, 0],
            "密闭空间作业": [0, 0, 1],
            "其他字段": [1, 2, 3],
        })
        trans = ConfinedSpaceORTransformer()
        result = trans.fit_transform(df)
        assert "confined_space_flag" in result.columns
        assert result["confined_space_flag"].tolist() == [0, 1, 1]


class TestHazardousChemicalORTransformer:
    def test_or_logic(self):
        df = pd.DataFrame({
            "是否使用危化品": [0, 0, 1],
            "危险化学品存储": [0, 1, 0],
        })
        trans = HazardousChemicalORTransformer()
        result = trans.fit_transform(df)
        assert "hazardous_chemical_flag" in result.columns
        assert result["hazardous_chemical_flag"].tolist() == [0, 1, 1]


class TestTimeDecayWeightTransformer:
    def test_decay(self):
        df = pd.DataFrame({
            "检查时间": pd.to_datetime(["2024-01-01", "2023-01-01", "2022-01-01"]),
            "隐患数量": [10, 20, 30],
        })
        trans = TimeDecayWeightTransformer(value_cols=["隐患数量"], reference_year=2024)
        result = trans.fit_transform(df)
        assert "隐患数量_decay_weighted" in result.columns
        assert result.loc[0, "隐患数量_decay_weighted"] == pytest.approx(10.0, abs=1e-5)
        assert result.loc[1, "隐患数量_decay_weighted"] == pytest.approx(14.0, abs=1e-5)  # 20*0.7
        assert result.loc[2, "隐患数量_decay_weighted"] == pytest.approx(15.0, abs=1e-5)  # 30*0.5


class TestGeoFenceTransformer:
    def test_inside(self):
        # 构造一个简单矩形围栏
        polygon = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
        df = pd.DataFrame({
            "经度": [0.5, 2.0],
            "纬度": [0.5, 2.0],
        })
        trans = GeoFenceTransformer(fence_polygons=[polygon])
        result = trans.fit_transform(df)
        assert "in_chemical_park" in result.columns
        assert result.loc[0, "in_chemical_park"] == 1
        assert result.loc[1, "in_chemical_park"] == 0


class TestEnterpriseAggregator:
    def test_aggregation(self):
        df = pd.DataFrame({
            "企业ID": ["A", "A", "B"],
            "隐患数": [2, 3, 5],
            "立案数": [1, 0, 2],
            "检查数": [5, 5, 10],
        })
        trans = EnterpriseAggregator(
            enterprise_id_col="企业ID",
            hazard_cols=["隐患数"],
            document_cols=["立案数", "检查数"],
        )
        result = trans.fit_transform(df)
        assert "enterprise_hazard_score" in result.columns
        assert "enterprise_doc_score" in result.columns
        # 行级保留
        assert result.loc[0, "enterprise_hazard_score"] == 2.0
        assert result.loc[0, "enterprise_doc_score"] == 1.0 * 3.0 + 5.0 * 1.0  # 立案权重3，检查权重1


class TestDataCredibilityTransformer:
    def test_credibility(self):
        df = pd.DataFrame({
            "数据来源": ["企业自报", "执法", "日常检查", None],
        })
        trans = DataCredibilityTransformer()
        result = trans.fit_transform(df)
        assert "data_credibility" in result.columns
        assert result.loc[0, "data_credibility"] == 1.0
        assert result.loc[1, "data_credibility"] == 4.0
        assert result.loc[2, "data_credibility"] == 2.0
        assert result.loc[3, "data_credibility"] == 1.0


class TestFeatureEngineeringPipeline:
    """测试特征工程全流程管道（覆盖≥10个代表性字段处理结果）"""

    def test_pipeline(self):
        df = pd.DataFrame({
            "above_designated": [1, 0, 1],
            "staff_num": [100, 200, np.nan],
            "indus_type_large": ["采矿业", "制造业", "化工"],
            "dust_ganshi_num": [10, 0, 5],
            "dust_shishi_num": [5, 10, 5],
            "is_finite_space": [0, 1, 0],
            "confined_spaces_enterprise": [0, 0, 1],
            "dangerous_chemical_enterprise": [0, 0, 1],
            "is_ammonia_refrigerating": [0, 1, 0],
            "report_time": pd.to_datetime(["2024-01-01", "2023-06-01", None]),
            "trouble_total_count": [10, 20, 30],
            "risk_total_count": [5, 3, 1],
            "check_total_count": [20, 10, 5],
            "dir_longitude": [120.5, 121.0, 120.3],
            "dir_latitude": [31.1, 31.2, 31.0],
            "enterprise_id": ["E1", "E1", "E2"],
            "trouble_level_2_count": [1, 0, 2],
            "risk_with_accident_count": [0, 1, 0],
            "writ_total_count": [3, 2, 1],
            "writ_from_case_count": [1, 0, 2],
            "writ_from_check_count": [2, 2, 0],
            "cf_source": ["企业自报", "执法", "日常检查"],
        })
        pipeline = FeatureEngineeringPipeline()
        result = pipeline.fit_transform(df)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == 3

        # 验证至少10个代表性字段处理正确
        assert "industry_risk_coefficient" in result.columns
        assert result.loc[0, "industry_risk_coefficient"] == 1.5  # 采矿业

        assert "dry_removal_ratio" in result.columns
        assert result.loc[0, "dry_removal_ratio"] == pytest.approx(10 / 15, abs=1e-5)

        assert "confined_space_flag" in result.columns
        assert result["confined_space_flag"].tolist() == [0, 1, 1]

        assert "hazardous_chemical_flag" in result.columns
        assert result["hazardous_chemical_flag"].tolist() == [0, 1, 1]

        assert "trouble_total_count_decay_weighted" in result.columns

        assert "in_chemical_park" in result.columns
        # 默认无围栏配置时输出0

        assert "enterprise_hazard_score" in result.columns
        assert result.loc[0, "enterprise_hazard_score"] == 11.0

        assert "data_credibility" in result.columns
        assert result.loc[1, "data_credibility"] == 4.0

        assert "above_designated" in result.columns
        assert result["above_designated"].tolist() == [1, 0, 1]

    def test_save_load(self):
        df = pd.DataFrame({
            "是否发生事故": ["是", "否"],
            "企业职工总人数": [100, 200],
        })
        pipeline = FeatureEngineeringPipeline()
        pipeline.fit_transform(df)
        
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            tmp = f.name
        try:
            pipeline.save(tmp)
            pipeline2 = FeatureEngineeringPipeline()
            pipeline2.load(tmp)
            result = pipeline2.transform(df)
            assert result.shape[0] == 2
        finally:
            os.unlink(tmp)
