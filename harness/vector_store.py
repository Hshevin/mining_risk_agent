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

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

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

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


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
        collection_name: str = "knowledge_base",
        embedding_model: Optional[str] = None,
        persist_directory: Optional[str] = None,
        embedding_fn: Optional[callable] = None,
    ):
        config = get_config()
        self.embedding_model_name = embedding_model or config.harness.memory.long_term.rag.get(
            "embedding_model", "BAAI/bge-large-zh-v1.5"
        )
        self.chunk_size = config.harness.memory.long_term.rag.get("chunk_size", 300)
        self.chunk_overlap = config.harness.memory.long_term.rag.get("chunk_overlap", 50)
        self._embedding_fn = embedding_fn
        
        # ChromaDB 客户端
        if persist_directory is None:
            persist_directory = "data/chroma_db"
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)

        if chromadb is None or Settings is None:
            detail = f" 原始错误: {_CHROMADB_IMPORT_ERROR}" if _CHROMADB_IMPORT_ERROR else ""
            raise ImportError(
                "VectorStore 需要可选依赖 chromadb。"
                "请安装 `pip install -r requirements-rag.txt` 或 `pip install -r requirements-full.txt`。"
                f"{detail}"
            )
        
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name=collection_name)
        
        # 嵌入模型（延迟加载）
        self._embedding_model: Optional[Any] = None

    def _get_embedding_model(self) -> Any:
        if SentenceTransformer is None:
            detail = (
                f" 原始错误: {_SENTENCE_TRANSFORMERS_IMPORT_ERROR}"
                if _SENTENCE_TRANSFORMERS_IMPORT_ERROR else ""
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
        model = self._get_embedding_model()
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()

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
