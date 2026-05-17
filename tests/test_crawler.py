"""
爬虫模块单元测试（Mock HTTP）
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from mining_risk_common.dataplane.crawler import Crawler, RegulationCrawler


class TestRegulationCrawler:
    """测试法规爬虫核心逻辑"""

    def test_user_agent_rotation(self):
        crawler = RegulationCrawler()
        headers1 = crawler._get_headers()
        headers2 = crawler._get_headers()
        assert headers1["User-Agent"] != headers2["User-Agent"]
        assert "Mozilla" in headers1["User-Agent"]

    def test_is_government_domain(self):
        crawler = RegulationCrawler()
        assert crawler._is_government_domain("https://www.mem.gov.cn/xxx")
        assert crawler._is_government_domain("https://jssafety.jiangsu.gov.cn/xxx")
        assert not crawler._is_government_domain("https://www.example.com/xxx")

    def test_extract_text(self):
        html = """
        <html><head><title>测试标题</title></head>
        <body>
            <h1>主标题</h1>
            <p>这是第一段正文内容，长度超过十个字符。</p>
            <p>这是第二段正文内容。</p>
            <script>alert(1)</script>
        </body></html>
        """
        crawler = RegulationCrawler()
        result = crawler._extract_text(html, "http://test.gov.cn/1")
        assert result["title"] == "主标题"
        assert "这是第一段正文内容" in result["content"]
        assert "alert" not in result["content"]
        assert result["url"] == "http://test.gov.cn/1"

    def test_save_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = RegulationCrawler(output_dir=tmpdir)
            data = {
                "url": "https://www.mem.gov.cn/test",
                "title": "测试法规",
                "content": "正文内容",
                "crawl_time": "2024-01-01T00:00:00",
            }
            path = crawler._save_markdown(data)
            assert os.path.exists(path)
            content = open(path, "r", encoding="utf-8").read()
            assert "测试法规" in content
            assert "正文内容" in content

    @patch("data.crawler.requests.Session.get")
    def test_fetch(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>test</body></html>"
        mock_resp.encoding = "utf-8"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        crawler = RegulationCrawler()
        html = crawler._fetch("https://www.mem.gov.cn/")
        assert html == "<html><body>test</body></html>"

    @patch("data.crawler.requests.Session.get")
    def test_crawl_regulations_mock(self, mock_get):
        """Mock 完整爬取流程"""
        mock_resp = MagicMock()
        mock_resp.text = """
        <html><head><title>安全生产法</title></head>
        <body>
            <h1>中华人民共和国安全生产法</h1>
            <p>第一条 为了加强安全生产工作，防止和减少生产安全事故，保障人民群众生命和财产安全，促进经济社会持续健康发展，制定本法。</p>
            <p>第二条 在中华人民共和国领域内从事生产经营活动的单位的安全生产，适用本法。</p>
        </body></html>
        """
        mock_resp.encoding = "utf-8"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = RegulationCrawler(output_dir=tmpdir, delay=0.1)
            results = crawler.crawl_regulations(
                seed_urls=["https://www.mem.gov.cn/test1.html"],
                max_pages=2,
            )
            assert len(results) >= 1
            assert "安全生产法" in results[0]["title"]
            assert os.path.exists(results[0]["filepath"])


class TestCrawlerStatic:
    """测试 Crawler 静态接口"""

    @patch("data.crawler.requests.Session.get")
    def test_crawl_regulations_static(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><h1>标题</h1><p>内容内容内容</p></body></html>"
        mock_resp.encoding = "utf-8"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            results = Crawler.crawl_regulations(
                seed_urls=["https://www.mem.gov.cn/page1.html"],
                max_pages=1,
                output_dir=tmpdir,
            )
            assert len(results) == 1
            assert "标题" in results[0]["title"]
