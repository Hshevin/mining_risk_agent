"""
迭代数据源与记忆统计工具函数测试。
"""

from __future__ import annotations

import pytest

from harness.memory_statistics import iso_from_timestamp, parse_time
from iteration.data_source import BatchMetadata, EnterpriseDataBatch


class TestBatchMetadata:
    def test_from_dict_minimal(self):
        m = BatchMetadata.from_dict(
            {
                "batch_id": "b1",
                "sample_count": 10,
                "risk_sample_count": 2,
                "recent_f1": 0.88,
                "description": "unit",
            }
        )
        assert m.batch_id == "b1"
        assert m.scenario == "unspecified"

    def test_from_dict_missing_field_raises(self):
        with pytest.raises(ValueError) as ei:
            BatchMetadata.from_dict({"batch_id": "b1"})
        assert "missing required" in str(ei.value).lower()

    def test_enterprise_batch_to_dict_exclude_records(self):
        m = BatchMetadata(
            batch_id="b",
            sample_count=1,
            risk_sample_count=0,
            recent_f1=1.0,
            description="d",
        )
        batch = EnterpriseDataBatch(metadata=m, records=[{"a": 1}], source="demo")
        d = batch.to_dict(include_records=False)
        assert "records" not in d
        assert d["record_count"] == 1


class TestMemoryStatisticsParseTime:
    def test_parse_none_and_empty(self):
        assert parse_time(None) is None
        assert parse_time("") is None

    def test_parse_float_string(self):
        assert parse_time("123.45") == 123.45

    def test_parse_iso_z(self):
        ts = parse_time("2024-01-02T03:04:05Z")
        assert ts is not None

    def test_iso_from_timestamp(self):
        assert iso_from_timestamp(None) == ""
        s = iso_from_timestamp(1_700_000_000.0)
        assert len(s) > 0
