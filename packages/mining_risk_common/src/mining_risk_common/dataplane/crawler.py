"""
网络爬虫模块：定向爬取政府公开法规数据
基于 requests + BeautifulSoup4，预留 Scrapy-Redis 扩展接口
合规要求：
  - 检查 robots.txt
  - 请求间隔 ≥ 1.5s
  - User-Agent 轮换
  - 仅爬取公开政府数据
"""

import os
import re
import time
import urllib.robotparser
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from mining_risk_common.utils.config import get_config
from mining_risk_common.utils.exceptions import DataLoadingError
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)

# 合规的 User-Agent 池
DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]

# 政府域名白名单（仅允许爬取这些域名下的公开数据）
GOVERNMENT_DOMAINS = [
    "mem.gov.cn",           # 应急管理部
    "safety.gov.cn",        # 国家安全监管总局（历史）
    "gov.cn",               # 中国政府网及各级政府部门
    "jiangsu.gov.cn",       # 江苏省
]


class RegulationCrawler:
    """
    法规爬虫类
    
    用法：
        crawler = RegulationCrawler(output_dir="knowledge_base/raw_texts")
        results = crawler.crawl_regulations(seed_urls=["https://www.mem.gov.cn/..."], max_pages=50)
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        delay: float = 1.5,
        user_agents: Optional[List[str]] = None,
        timeout: int = 30,
    ):
        self.delay = delay
        self.timeout = timeout
        self.user_agents = user_agents or DEFAULT_USER_AGENTS
        self.session = requests.Session()
        self.visited: set = set()
        self.results: List[Dict] = []
        self._ua_index = 0

        if output_dir is None:
            output_dir = os.path.join("knowledge_base", "raw_texts")
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_headers(self) -> Dict[str, str]:
        """轮换 User-Agent"""
        ua = self.user_agents[self._ua_index % len(self.user_agents)]
        self._ua_index += 1
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def _is_government_domain(self, url: str) -> bool:
        """检查是否为允许的政府域名"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # 允许所有 .gov.cn 域名
        if domain.endswith(".gov.cn"):
            return True
        return any(domain.endswith(d) for d in GOVERNMENT_DOMAINS)

    def _check_robots_txt(self, url: str) -> bool:
        """检查 robots.txt 是否允许爬取"""
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch("*", url)
        except Exception as e:
            logger.warning(f"robots.txt 检查失败 {robots_url}: {e}，默认允许")
            return True

    def _fetch(self, url: str) -> Optional[str]:
        """发送 HTTP 请求并返回 HTML 文本"""
        try:
            headers = self._get_headers()
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            # 尝试检测编码
            if resp.encoding == "ISO-8859-1":
                resp.encoding = resp.apparent_encoding
            return resp.text
        except requests.RequestException as e:
            logger.warning(f"请求失败 {url}: {e}")
            return None

    def _extract_text(self, html: str, url: str) -> Dict:
        """从 HTML 中提取标题和正文"""
        soup = BeautifulSoup(html, "html.parser")

        # 尝试提取标题
        title = ""
        for tag in [soup.find("h1"), soup.find("h2"), soup.find("title")]:
            if tag and tag.get_text(strip=True):
                title = tag.get_text(strip=True)
                break

        # 移除脚本和样式
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # 提取正文：优先尝试 article 或 main 标签，否则取 body
        content_area = soup.find("article") or soup.find("main") or soup.find("body") or soup
        paragraphs = content_area.find_all(["p", "div", "li", "td"])
        texts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 10:
                texts.append(text)

        body = "\n\n".join(texts)
        # 简单去重行
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        body = "\n".join(lines)

        return {
            "url": url,
            "title": title,
            "content": body,
            "crawl_time": datetime.now().isoformat(),
        }

    def _save_markdown(self, data: Dict) -> str:
        """将爬取结果保存为 Markdown 文件"""
        parsed = urlparse(data["url"])
        source = parsed.netloc.replace(".", "_")
        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"{source}_{date_str}.md"
        filepath = os.path.join(self.output_dir, filename)

        # 如果文件已存在，追加内容
        if os.path.exists(filepath):
            mode = "a"
            header = "\n\n---\n\n"
        else:
            mode = "w"
            header = f"# 爬取法规原文 - {source}\n\n> 爬取时间: {data['crawl_time']}\n\n"

        with open(filepath, mode, encoding="utf-8") as f:
            f.write(header)
            f.write(f"## {data['title']}\n\n")
            f.write(f"来源: {data['url']}\n\n")
            f.write(data["content"])
            f.write("\n")

        logger.info(f"已保存 Markdown: {filepath}")
        return filepath

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        """从页面中提取同域链接"""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"])
            # 只保留同域链接
            if urlparse(href).netloc == urlparse(base_url).netloc:
                links.append(href)
        return links

    def crawl_regulations(
        self,
        seed_urls: List[str],
        max_pages: int = 50,
    ) -> List[Dict]:
        """
        定向爬取法规页面
        
        Args:
            seed_urls: 起始 URL 列表
            max_pages: 最大爬取页面数
        
        Returns:
            爬取结果列表，每个元素为 {"url", "title", "content", "crawl_time", "filepath"}
        """
        if not seed_urls:
            logger.warning("seed_urls 为空，无页面可爬取")
            return []

        queue = list(seed_urls)
        self.visited = set()
        self.results = []

        while queue and len(self.visited) < max_pages:
            url = queue.pop(0)
            if url in self.visited:
                continue

            # 域名合规检查
            if not self._is_government_domain(url):
                logger.info(f"跳过非政府域名: {url}")
                continue

            # robots.txt 检查
            if not self._check_robots_txt(url):
                logger.info(f"robots.txt 禁止爬取: {url}")
                continue

            logger.info(f"开始爬取: {url}")
            html = self._fetch(url)
            if html is None:
                continue

            self.visited.add(url)
            data = self._extract_text(html, url)
            filepath = self._save_markdown(data)
            data["filepath"] = filepath
            self.results.append(data)

            # 提取新链接（广度优先，限制在同域）
            if len(self.visited) < max_pages:
                new_links = self._extract_links(html, url)
                for link in new_links:
                    if link not in self.visited and link not in queue:
                        queue.append(link)

            # 合规间隔
            time.sleep(self.delay)

        logger.info(f"爬取完成，共访问 {len(self.visited)} 个页面，成功 {len(self.results)} 条")
        return self.results


class Crawler:
    """
    爬虫兼容接口（与任务描述中的类名保持一致）
    """

    @staticmethod
    def crawl_regulations(
        seed_urls: List[str],
        max_pages: int = 50,
        output_dir: Optional[str] = None,
    ) -> List[Dict]:
        """
        静态便捷方法，直接调用 RegulationCrawler
        """
        crawler = RegulationCrawler(output_dir=output_dir)
        return crawler.crawl_regulations(seed_urls=seed_urls, max_pages=max_pages)
