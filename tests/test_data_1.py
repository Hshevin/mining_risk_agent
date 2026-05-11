"""
数据模块单元测试
覆盖率目标：≥80%
"""

import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.routers import data as data_router
from data.loader import DataLoader, DataUploadRequest
from data.preprocessor import (BinaryEncoder, EnumRiskMapper, FeatureEngineeringPipeline,
                                                   IndustryRiskCoefficient, MissingValueHandler, NumericTransformer,
                                                   TextRiskExtractor)
from utils.config import get_config, resolve_project_path
from utils.exceptions import DataLoadingError


class TestDataLoader:
    """测试数据加载器"""

    def test_upload_api_persists_file_and_records(self, monkeypatch, tmp_path):
        monkeypatch.setattr(data_router, "UPLOAD_DIR", tmp_path)
        client = TestClient(create_app())

        response = client.post(
            "/api/v1/data/upload",
            files={"file": ("sample.csv", b"col1,col2\n1,2\n3,4\n", "text/csv")},
            data={"enterprise_id": "ENT001"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["persisted"] is True
        assert body["rows"] == 2
        assert body["record_count"] == 2
        assert body["checksum"]
        assert Path(body["saved_path"]).exists()
        assert Path(body["record_path"]).exists()

    def test_load_csv(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8-sig") as f:
            f.write("col1,col2\n1,2\n3,4\n")
            tmp = f.name
        try:
            loader = DataLoader()
            df = loader.load_file(tmp)
            assert df.shape == (2, 2)
            assert list(df.columns) == ["col1", "col2"]
        finally:
            os.unlink(tmp)

    def test_load_from_api_csv(self):
        request = DataUploadRequest(
            enterprise_id="ENT001",
            data_format="csv",
            content="col1,col2\n1,2\n",
        )
        loader = DataLoader()
        df = loader.load_from_api(request)
        assert df.shape == (1, 2)

    def test_load_from_api_json(self):
        request = DataUploadRequest(
            enterprise_id="ENT001",
            data_format="json",
            content={"records": [{"a": 1, "b": 2}]},
        )
        loader = DataLoader()
        df = loader.load_from_api(request)
        assert len(df) == 1

    def test_configured_public_data_paths_exist(self):
        config = get_config()
        paths = [
            config.data.public_data_root,
            config.data.raw_data_path,
            config.data.reference_data_path,
            config.data.merged_data_path,
        ]

        for configured_path in paths:
            assert configured_path is not None
            assert resolve_project_path(configured_path).exists()

        assert resolve_project_path(config.data.merged_data_path).suffix == ".xlsx"

    def test_configured_raw_reference_and_merged_data_load(self):
        loader = DataLoader()

        raw_tables = loader.load_directory(loader.raw_data_path, nrows=2)
        reference_tables = loader.load_directory(loader.reference_data_path, nrows=2)
        merged = loader.load_merged_dataset(nrows=2)

        assert len(raw_tables) >= 19
        assert len(reference_tables) >= 20
        assert merged.shape[0] == 2
        assert "enterprise_id" in merged.columns
        assert "new_level" in merged.columns

    def test_public_data_scan_reads_majority_and_skips_bad_xlsx(self, caplog):
        loader = DataLoader()
        caplog.set_level("WARNING")

        tables = loader.load_public_data(nrows=1)

        assert len(tables) >= 60
        assert "new_已清洗" in tables
        assert "数据补充/enterprise_routine_check_log" not in tables
        assert any(
            "enterprise_routine_check_log.xlsx" in record.message
            and "跳过无法读取的数据文件" in record.message
            for record in caplog.records
        )

    def test_duplicate_field_csv_deduplicates_columns(self, caplog):
        loader = DataLoader()
        duplicate_csv = resolve_project_path(
            "../公开数据/公开数据/新数据/ds_aczf_accessory_3_202603181744.csv"
        )
        caplog.set_level("WARNING")

        df = loader.load_file(duplicate_csv, nrows=5)

        assert "地区编码" in df.columns
        assert "地区编码__dup2" in df.columns
        assert any("重复字段已追加 __dupN 后缀" in record.message for record in caplog.records)

    def test_bad_xlsx_can_be_strict_or_skipped(self, caplog):
        loader = DataLoader()
        bad_xlsx = resolve_project_path("../公开数据/公开数据/数据补充/enterprise_routine_check_log.xlsx")
        caplog.set_level("WARNING")

        with pytest.raises(DataLoadingError):
            loader.load_file(bad_xlsx)

        tables = loader.load_directory(Path(loader.raw_data_path), nrows=1)

        assert "enterprise_routine_check_log" not in tables
        assert any("enterprise_routine_check_log.xlsx" in record.message for record in caplog.records)


class TestBinaryEncoder:
    """测试二值型编码器"""

    def test_encode(self):
        df = pd.DataFrame({"col": ["是", "否", "1", "0", "有", "无", None]})
        enc = BinaryEncoder()
        result = enc.fit_transform(df)
        assert result["col"].tolist() == [1, 0, 1, 0, 1, 0, 0]


class TestNumericTransformer:
    """测试数值型变换器"""

    def test_transform(self):
        df = pd.DataFrame({"col": [1.0, 2.0, 3.0, 100.0, np.nan]})
        trans = NumericTransformer(clip_quantile=0.99)
        result = trans.fit_transform(df)
        assert result.shape == (5, 1)
        assert result["col"].max() <= 1.0
        assert result["col"].min() >= 0.0


class TestTextRiskExtractor:
    """测试文本型风险提取器"""

    def test_extract(self):
        df = pd.DataFrame({"col": ["正常生产", "", None, "发生瓦斯爆炸事故"]})
        ext = TextRiskExtractor()
        result = ext.fit_transform(df)
        assert "col_completeness" in result.columns
        assert "col_risk_words" in result.columns
        # 空值完整性评分应为 1.0
        assert result.loc[1, "col_completeness"] == 1.0
        # 瓦斯爆炸应命中高危词
        assert result.loc[3, "col_risk_words"] > 0


class TestIndustryRiskCoefficient:
    """测试行业风险系数映射器"""

    def test_map(self):
        df = pd.DataFrame({"行业": ["采矿业", "制造业", "化工", "其他"]})
        mapper = IndustryRiskCoefficient()
        result = mapper.fit_transform(df)
        assert "industry_risk_coefficient" in result.columns
        assert result.loc[0, "industry_risk_coefficient"] == 1.5
        assert result.loc[1, "industry_risk_coefficient"] == 1.0


class TestMissingValueHandler:
    """测试缺失值处理器"""

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


class TestCsvToMarkdownTable:
    """测试 CSV 转 Markdown 表格"""

    def test_conversion(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8-sig", newline="") as f:
            f.write("name,age\nAlice,30\nBob,25\n")
            tmp = f.name
        try:
            from data.preprocessor import csv_to_markdown_table
            md = csv_to_markdown_table(tmp)
            assert "| name | age |" in md
            assert "| Alice | 30 |" in md
            assert "| Bob | 25 |" in md
        finally:
            os.unlink(tmp)

    def test_max_rows(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8-sig", newline="") as f:
            f.write("a\n1\n2\n3\n4\n")
            tmp = f.name
        try:
            from data.preprocessor import csv_to_markdown_table
            md = csv_to_markdown_table(tmp, max_rows=3)
            lines = md.splitlines()
            assert len(lines) == 4  # header + separator + 2 data rows
        finally:
            os.unlink(tmp)

    def test_empty_csv(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8-sig", newline="") as f:
            f.write("")
            tmp = f.name
        try:
            from data.preprocessor import csv_to_markdown_table
            assert csv_to_markdown_table(tmp) == ""
        finally:
            os.unlink(tmp)


class TestFeatureEngineeringPipeline:
    """测试特征工程全流程管道"""

    def test_pipeline(self):
        df = pd.DataFrame({
            "主键ID": ["A", "B", "C"],
            "是否发生事故": ["是", "否", "否"],
            "企业职工总人数": [100, 200, np.nan],
            "管理类别": [1001, 1002, 1003],
            "具体风险描述": ["正常", "", "瓦斯泄漏"],
            "行业监管大类": ["采矿业", "制造业", "化工"],
        })
        pipeline = FeatureEngineeringPipeline()
        result = pipeline.fit_transform(df)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == 3

    def test_save_load(self):
        df = pd.DataFrame({
            "是否发生事故": ["是", "否"],
            "企业职工总人数": [100, 200],
        })
        pipeline = FeatureEngineeringPipeline()
        pipeline.fit_transform(df)
        
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
