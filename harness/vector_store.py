"""
向量检索引擎
基于 ChromaDB，支持 SelfQuery 元数据过滤

用法：
    from harness.vector_store import VectorStore
    store = VectorStore()
    store.load_from_kb()
    results = store.self_query_retrieve(
        query="高炉煤气泄漏",
        filters={"risk_type": "火灾爆炸"},
        top_k=5
    )
"""

import hashlib
import math
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

try:
    import chromadb
    from chromadb.config import Settings

    _CHROMADB_IMPORT_ERROR = None
except Exception as e:
    chromadb = None
    Settings = None
    _CHROMADB_IMPORT_ERROR = e

try:
    from sentence_transformers import SentenceTransformer

    _SENTENCE_TRANSFORMERS_IMPORT_ERROR = None
except Exception as e:
    SentenceTransformer = None
    _SENTENCE_TRANSFORMERS_IMPORT_ERROR = e

from utils.config import get_config, resolve_project_path
from utils.logger import get_logger

logger = get_logger(__name__)


DEFAULT_FALLBACK_EMBEDDING_DIMENSIONS = 384


def _env_bool(names: Iterable[str], default: bool) -> bool:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return default


def _stable_hash(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def _fallback_features(text: str) -> Iterable[tuple[str, float]]:
    normalized = re.sub(r"\s+", "", text.lower())
    if not normalized:
        return

    domain_phrases = [
        "粉尘涉爆", "粉尘爆炸", "除尘", "除尘系统", "积尘", "动火",
        "危化品", "危险化学品", "泄漏", "储罐", "可燃气体", "有毒气体",
        "冶金", "煤气", "煤气报警", "co报警", "熔融金属", "高炉", "转炉",
        "有限空间", "受限空间", "中毒窒息", "中毒和窒息", "缺氧", "通风", "检测",
        "重大隐患", "红级", "橙级", "报警", "联锁", "传感器", "风险", "处置",
    ]
    for phrase in domain_phrases:
        if phrase in normalized:
            yield f"phrase:{phrase}", 3.0

    words = re.findall(r"[a-z0-9_]+", normalized)
    for word in words:
        yield f"word:{word}", 1.4

    # Chinese safety texts are short and terminology-heavy. Character n-grams
    # give deterministic lexical recall without external model files.
    for n, weight in ((1, 0.25), (2, 0.9), (3, 1.2), (4, 1.0)):
        if len(normalized) < n:
            continue
        for i in range(len(normalized) - n + 1):
            gram = normalized[i:i + n]
            if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", gram):
                yield f"ngram{n}:{gram}", weight


def deterministic_embedding(
    texts: List[str],
    dimensions: int = DEFAULT_FALLBACK_EMBEDDING_DIMENSIONS,
) -> List[List[float]]:
    """Return deterministic, normalized embeddings for offline indexing/tests."""
    embeddings: List[List[float]] = []
    for text in texts:
        vec = [0.0] * dimensions
        for feature, weight in _fallback_features(text):
            idx = _stable_hash(feature) % dimensions
            vec[idx] += weight
        norm = math.sqrt(sum(value * value for value in vec))
        if norm > 0:
            vec = [value / norm for value in vec]
        embeddings.append(vec)
    return embeddings


def split_by_headers(text: str, max_chunk_size: int = 300, overlap: int = 50) -> List[Dict]:
    """
    按 Markdown 标题层级切分文档
    
    Args:
        text: Markdown 文本
        max_chunk_size: 每个 chunk 最大字符数
        overlap: 相邻 chunk 重叠字符数
    
    Returns:
        chunk 列表，每个元素包含 text 和 metadata
    """
    lines = text.splitlines()
    chunks = []
    current_section = {"title": "", "level": 0, "lines": []}
    sections = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # 保存上一个 section
            if current_section["lines"]:
                sections.append(current_section)
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            current_section = {"title": title, "level": level, "lines": [line]}
        else:
            current_section["lines"].append(line)
    
    if current_section["lines"]:
        sections.append(current_section)
    
    # 将每个 section 进一步切分为不超过 max_chunk_size 的 chunk
    for sec in sections:
        sec_text = "\n".join(sec["lines"]).strip()
        if not sec_text:
            continue
        
        # 将 section 切分为不超过 max_chunk_size 的 chunk
        paragraphs = sec_text.split("\n\n")
        current_chunk = []
        current_len = 0
        
        for para in paragraphs:
            para_len = len(para)
            # 如果单个段落就超过限制，直接按句子切分
            if para_len > max_chunk_size:
                if current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append({
                        "text": chunk_text,
                        "metadata": {
                            "section_title": sec["title"],
                            "section_level": sec["level"],
                        },
                    })
                    current_chunk = []
                    current_len = 0
                # 按句子切分大段落
                sentences = para.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n")
                sub_chunk = []
                sub_len = 0
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    # 如果单个句子仍然超过限制，按固定长度切分
                    if len(sent) > max_chunk_size:
                        if sub_chunk:
                            chunks.append({
                                "text": "".join(sub_chunk),
                                "metadata": {
                                    "section_title": sec["title"],
                                    "section_level": sec["level"],
                                },
                            })
                            sub_chunk = []
                            sub_len = 0
                        for start in range(0, len(sent), max_chunk_size - overlap):
                            piece = sent[start:start + max_chunk_size]
                            chunks.append({
                                "text": piece,
                                "metadata": {
                                    "section_title": sec["title"],
                                    "section_level": sec["level"],
                                },
                            })
                        continue
                    if sub_len + len(sent) > max_chunk_size and sub_chunk:
                        chunks.append({
                            "text": "".join(sub_chunk),
                            "metadata": {
                                "section_title": sec["title"],
                                "section_level": sec["level"],
                            },
                        })
                        sub_chunk = [sent]
                        sub_len = len(sent)
                    else:
                        sub_chunk.append(sent)
                        sub_len += len(sent)
                if sub_chunk:
                    chunks.append({
                        "text": "".join(sub_chunk),
                        "metadata": {
                            "section_title": sec["title"],
                            "section_level": sec["level"],
                        },
                    })
                continue
            
            if current_len + para_len + 2 > max_chunk_size and current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "section_title": sec["title"],
                        "section_level": sec["level"],
                    },
                })
                # 保留重叠
                if overlap > 0:
                    overlap_text = chunk_text[-overlap:]
                    current_chunk = [overlap_text, para]
                    current_len = len(overlap_text) + para_len + 2
                else:
                    current_chunk = [para]
                    current_len = para_len
            else:
                current_chunk.append(para)
                current_len += para_len + 2
        
        if current_chunk:
            chunks.append({
                "text": "\n\n".join(current_chunk),
                "metadata": {
                    "section_title": sec["title"],
                    "section_level": sec["level"],
                },
            })
    
    return chunks


class VectorStore:
    """
    向量存储与检索引擎
    支持 SelfQuery 元数据预过滤 + 向量相似度检索
    """

    def __init__(
        self,
        collection_name: Optional[str] = None,
        embedding_model: Optional[str] = None,
        persist_directory: Optional[str] = None,
        embedding_fn: Optional[callable] = None,
        embedding_backend: Optional[str] = None,
    ):
        config = get_config()
        rag_config = config.harness.memory.long_term.rag
        self.collection_name = collection_name or rag_config.get("collection_name", "knowledge_base")
        self.embedding_model_name = embedding_model or rag_config.get(
            "embedding_model", "BAAI/bge-large-zh-v1.5"
        )
        self.chunk_size = rag_config.get("chunk_size", 300)
        self.chunk_overlap = rag_config.get("chunk_overlap", 50)
        self._embedding_fn = embedding_fn
        self.embedding_backend = (
            embedding_backend
            or os.getenv("RAG_EMBEDDING_BACKEND")
            or os.getenv("MINING_RAG_EMBEDDING_BACKEND")
            or rag_config.get("embedding_backend", "auto")
        ).strip().lower()
        self.allow_fallback_embedding = _env_bool(
            ("RAG_ALLOW_FALLBACK_EMBEDDING", "MINING_RAG_ALLOW_FALLBACK_EMBEDDING"),
            bool(rag_config.get("allow_fallback_embedding", True)),
        )
        self._fallback_warned = False
        
        # ChromaDB 客户端
        if persist_directory is None:
            persist_directory = rag_config.get("persist_directory", "data/chroma_db")
        if not os.path.isabs(str(persist_directory)):
            persist_directory = str(resolve_project_path(str(persist_directory)))
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)

        if chromadb is None or Settings is None:
            detail = f" 原始错误: {_CHROMADB_IMPORT_ERROR}" if _CHROMADB_IMPORT_ERROR else ""
            raise ImportError(
                "VectorStore 需要可选依赖 chromadb。"
                "请安装 `pip install -r requirements-rag.txt` 或 `pip install -r requirements-full.txt`。"
                f"{detail}"
            )
        
        client_settings = Settings(anonymized_telemetry=False)
        try:
            self.client = chromadb.PersistentClient(
                path=persist_directory,
                settings=client_settings,
            )
        except Exception as e:
            # Some tests and legacy callers stop Chroma's shared system directly.
            # In Chroma 1.5 that can leave a stale RustBindingsAPI in the process
            # cache; clearing the cache and retrying recreates the local client.
            try:
                from chromadb.api.client import SharedSystemClient

                SharedSystemClient.clear_system_cache()
                self.client = chromadb.PersistentClient(
                    path=persist_directory,
                    settings=client_settings,
                )
                logger.warning(f"Chroma shared system cache was stale; recreated client for {persist_directory}: {e}")
            except Exception:
                raise
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        
        # 嵌入模型（延迟加载）
        self._embedding_model: Optional[Any] = None

    def _get_embedding_model(self) -> Any:
        if SentenceTransformer is None:
            detail = (
                f" 原始错误: {_SENTENCE_TRANSFORMERS_IMPORT_ERROR}"
                if _SENTENCE_TRANSFORMERS_IMPORT_ERROR
                else ""
            )
            raise ImportError(
                "VectorStore.embed 需要可选依赖 sentence-transformers。"
                "请安装 `pip install -r requirements-rag.txt` 或 `pip install -r requirements-full.txt`。"
                f"{detail}"
            )
        if self._embedding_model is None:
            logger.info(f"加载嵌入模型: {self.embedding_model_name}")
            self._embedding_model = SentenceTransformer(self.embedding_model_name)
        return self._embedding_model

    def embed(self, texts: List[str]) -> List[List[float]]:
        """文本向量化"""
        if self._embedding_fn is not None:
            return self._embedding_fn(texts)
        if self.embedding_backend in {"fallback", "mock", "deterministic"}:
            return deterministic_embedding(texts)
        try:
            model = self._get_embedding_model()
            embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            self.embedding_backend = "sentence_transformers"
            return embeddings.tolist()
        except Exception as e:
            if self.allow_fallback_embedding and self.embedding_backend == "auto":
                if not self._fallback_warned:
                    logger.warning(f"真实 embedding 不可用，使用 deterministic fallback: {e}")
                    self._fallback_warned = True
                self.embedding_backend = "fallback"
                return deterministic_embedding(texts)
            raise

    def add_documents(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None,
    ) -> None:
        """
        添加文档到向量库
        
        Args:
            documents: 文本列表
            metadatas: 元数据列表
            ids: 文档ID列表
        """
        if not documents:
            return
        
        if ids is None:
            ids = [f"doc_{i}" for i in range(len(documents))]
        if metadatas is None:
            metadatas = [{} for _ in documents]
        
        embeddings = self.embed(documents)
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
            embeddings=embeddings,
        )
        logger.info(f"已向量化库添加 {len(documents)} 个文档")

    def load_from_kb(self, kb_dir: str = "knowledge_base") -> int:
        """
        从 knowledge_base 目录加载所有 Markdown 文件
        
        Returns:
            加载的 chunk 数量
        """
        if not os.path.exists(kb_dir):
            logger.warning(f"知识库目录不存在: {kb_dir}")
            return 0
        
        all_chunks = []
        for root, _, files in os.walk(kb_dir):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                filepath = os.path.join(root, fname)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception as e:
                    logger.warning(f"读取文件失败 {filepath}: {e}")
                    continue
                
                # 解析文件名作为基础元数据
                source_file = os.path.relpath(filepath, kb_dir)
                # 推断 doc_type
                doc_type = "general"
                if "合规" in fname:
                    doc_type = "compliance"
                elif "SOP" in fname or "审核" in fname:
                    doc_type = "sop"
                elif "物理" in fname or "传感器" in fname:
                    doc_type = "physics"
                elif "执行条件" in fname:
                    doc_type = "conditions"
                elif "事故" in fname:
                    doc_type = "cases"
                elif "历史" in fname or "记忆" in fname:
                    doc_type = "history"
                
                # 推断风险类型
                risk_type = "general"
                if any(k in content for k in ["瓦斯", "煤气", "爆炸"]):
                    risk_type = "火灾爆炸"
                elif any(k in content for k in ["粉尘", "涉爆"]):
                    risk_type = "粉尘爆炸"
                elif any(k in content for k in ["危化品", "化学品", "储罐"]):
                    risk_type = "危化品泄漏"
                elif any(k in content for k in ["高温", "熔融", "冶金"]):
                    risk_type = "高温灼烫"
                
                # 推断行业
                industry = "通用"
                if any(k in content for k in ["煤矿", "瓦斯", "掘进"]):
                    industry = "煤炭"
                elif any(k in content for k in ["钢铁", "高炉", "转炉"]):
                    industry = "钢铁"
                elif any(k in content for k in ["危化品", "化工", "反应釜"]):
                    industry = "危化品"
                elif any(k in content for k in ["铝加工", "深井铸造"]):
                    industry = "有色金属"
                
                # 切分文档
                chunks = split_by_headers(content, max_chunk_size=self.chunk_size, overlap=self.chunk_overlap)
                for i, chunk in enumerate(chunks):
                    metadata = {
                        "source_file": source_file,
                        "risk_type": risk_type,
                        "industry": industry,
                        "publish_date": datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d"),
                        "doc_type": doc_type,
                        **chunk["metadata"],
                    }
                    all_chunks.append({
                        "text": chunk["text"],
                        "metadata": metadata,
                        "id": f"{source_file}_{i}",
                    })
        
        if not all_chunks:
            logger.warning("未从知识库加载到任何文档")
            return 0
        
        # 批量添加到向量库
        batch_size = 100
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i + batch_size]
            self.add_documents(
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
                ids=[c["id"] for c in batch],
            )
        
        logger.info(f"从知识库加载了 {len(all_chunks)} 个 chunk")
        return len(all_chunks)

    def self_query_retrieve(
        self,
        query: str,
        filters: Optional[Dict] = None,
        top_k: int = 5,
    ) -> List[Dict]:
        """
        SelfQuery 检索：先按元数据过滤，再执行向量相似度检索
        
        Args:
            query: 查询文本
            filters: 元数据过滤条件，如 {"risk_type": "火灾爆炸", "industry": "危化品"}
            top_k: 返回结果数量
        
        Returns:
            检索结果列表，每个元素包含 text, metadata, distance
        """
        if not query or not query.strip():
            return []
        
        query_embedding = self.embed([query])[0]
        
        # 构建 where 过滤条件
        where_clause = None
        if filters:
            conditions = []
            for key, value in filters.items():
                conditions.append({key: {"$eq": value}})
            if len(conditions) == 1:
                where_clause = conditions[0]
            elif len(conditions) > 1:
                where_clause = {"$and": conditions}
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_clause,
        )
        
        output = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                output.append({
                    "id": doc_id,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None,
                })
        
        return output

    def similarity_search(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Dict]:
        """
        纯向量相似度检索（无元数据过滤）
        """
        return self.self_query_retrieve(query, filters=None, top_k=top_k)

    def clear(self) -> None:
        """清空集合"""
        ids = self.collection.get()["ids"]
        if ids:
            self.collection.delete(ids=ids)
            logger.info(f"已清空集合，删除 {len(ids)} 条记录")

    def reset_collection(self) -> None:
        """删除并重建集合，用于复跑索引时重置向量维度。"""
        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
