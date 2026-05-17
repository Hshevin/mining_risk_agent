"""
NLP 管道单元测试
"""

import pytest

from mining_risk_serve.harness.nlp_pipeline import NERPipeline, bio_decode, bio_encode


class TestBIOConversion:
    """测试 BIO 编码/解码"""

    def test_bio_encode_decode(self):
        tokens = list("高炉煤气泄漏需立即停炉")
        entities = [
            {"text": "高炉", "label": "高风险设备", "start": 0, "end": 2},
            {"text": "煤气泄漏", "label": "风险属性", "start": 2, "end": 6},
            {"text": "停炉", "label": "动作", "start": 9, "end": 11},
        ]
        labels = bio_encode(tokens, entities)
        # 验证标签长度
        assert len(labels) == len(tokens)
        # 验证 BIO 格式
        assert labels[0] == "B-高风险设备"
        assert labels[1] == "I-高风险设备"
        assert labels[2] == "B-风险属性"
        assert labels[5] == "I-风险属性"
        assert labels[-2] == "B-动作"
        assert labels[-1] == "I-动作"
        
        # 解码验证
        decoded = bio_decode(tokens, labels)
        assert len(decoded) >= 2

    def test_bio_decode_empty(self):
        tokens = list("正常生产")
        labels = ["O", "O", "O", "O"]
        decoded = bio_decode(tokens, labels)
        assert decoded == []


class TestNERPipeline:
    """测试 NER 管道"""

    def test_rule_extract(self):
        pipeline = NERPipeline()
        text = "高炉煤气泄漏需立即停炉"
        entities = pipeline.extract_entities(text)
        assert isinstance(entities, list)
        # 规则应能命中至少几个实体
        labels = {e["label"] for e in entities}
        assert "高风险设备" in labels or "风险属性" in labels or "动作" in labels

    def test_extract_entities_empty(self):
        pipeline = NERPipeline()
        assert pipeline.extract_entities("") == []
        assert pipeline.extract_entities("   ") == []

    def test_extract_entities_with_regulation(self):
        pipeline = NERPipeline()
        text = "根据安全生产法第三十六条，压力容器需定期检验"
        entities = pipeline.extract_entities(text)
        labels = {e["label"] for e in entities}
        # 至少命中法规条款或高风险设备
        assert len(labels) > 0

    def test_batch_extract(self):
        pipeline = NERPipeline()
        texts = ["高炉超温", "储罐泄漏", "启动应急预案"]
        results = pipeline.extract_entities_batch(texts)
        assert len(results) == 3
        for r in results:
            assert isinstance(r, list)

    def test_entity_fields(self):
        pipeline = NERPipeline()
        text = "煤气柜压力超标应立即切断气源"
        entities = pipeline.extract_entities(text)
        for e in entities:
            assert "text" in e
            assert "label" in e
            assert "start" in e
            assert "end" in e
            assert "source" in e
            assert isinstance(e["start"], int)
            assert isinstance(e["end"], int)
