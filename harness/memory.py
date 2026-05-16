"""
长短期混合记忆系统
严格对齐《研究方案》技术路线

核心特性：
- ShortTermMemory：P0(永久保留) 至 P3(最先移除)，tiktoken 精确计数，LRU 动态清理
- LongTermMemory：基于 AgentFS 读写 4 个 Markdown 长期记忆库，VectorStore SelfQuery + BGE-Reranker 精排
- 全部 IO 方法使用 async/await
"""

import asyncio
import json
import os
import time
import warnings
from typing import Any, Callable, Dict, List, Optional

from harness.agentfs import AgentFS
from harness.knowledge_base import KnowledgeBaseManager
from harness.vector_store import VectorStore
from harness.reranker import Reranker
from utils.config import get_config
from utils.exceptions import MemoryManagerError
from utils.logger import get_logger

logger = get_logger(__name__)


def _env_bool(names: List[str], default: Optional[bool] = None) -> Optional[bool]:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return default


def _risk_type_filter(value: Optional[str]) -> Optional[Dict[str, str]]:
    if not value:
        return None
    normalized = value.strip()
    if normalized in {"红", "橙", "黄", "蓝", "A", "B", "C", "D", "高", "中", "低"}:
        return None
    if any(token in normalized for token in ("粉尘", "涉爆", "除尘")):
        return {"risk_type": "粉尘涉爆"}
    if any(token in normalized for token in ("危化", "危险化学", "储罐", "泄漏")):
        return {"risk_type": "危化品"}
    if any(token in normalized for token in ("煤气", "冶金", "熔融", "高炉", "转炉")):
        return {"risk_type": "冶金煤气"}
    if any(token in normalized for token in ("有限空间", "受限空间", "中毒窒息", "缺氧")):
        return {"risk_type": "有限空间"}
    if any(token in normalized for token in ("火灾", "爆炸")):
        return {"risk_type": "火灾爆炸"}
    return None

try:
    import tiktoken
except ImportError:
    tiktoken = None

# ---------------------------------------------------------------------------
# LangChain 兼容性：ConversationSummaryMemory 在部分环境中不可用，
# 因此提供轻量级兼容实现，行为与原版一致。
# ---------------------------------------------------------------------------
try:
    from langchain.memory import ConversationSummaryMemory
    HAS_LANGCHAIN_MEMORY = True
except ImportError:
    HAS_LANGCHAIN_MEMORY = False


class _CompatibleSummaryMemory:
    """
    ConversationSummaryMemory 的轻量级兼容实现。
    支持 LangChain 0.x (predict) 与 1.x (invoke) 两种 LLM 接口。
    """

    def __init__(self, llm: Any):
        self.llm = llm
        self._buffer = ""

    def clear(self) -> None:
        self._buffer = ""

    def save_context(self, inputs: Dict[str, str], outputs: Dict[str, str]) -> None:
        text = inputs.get("input", "")
        if text:
            self._buffer += f"\n{text}"

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, str]:
        if not self._buffer.strip():
            return {"history": ""}
        prompt = f"请对以下内容进行摘要：\n{self._buffer.strip()}\n摘要："
        try:
            if hasattr(self.llm, "invoke"):
                result = self.llm.invoke(prompt)
                if hasattr(result, "content"):
                    result = result.content
            elif hasattr(self.llm, "predict"):
                result = self.llm.predict(prompt)
            else:
                result = str(self.llm(prompt))
            return {"history": str(result).strip()}
        except Exception:
            # 极端降级：直接截断
            text = self._buffer.strip()
            if len(text) > 100:
                return {"history": text[:100] + "...[摘要]"}
            return {"history": text + "...[摘要]"}


class _SimpleSummarizer:
    """当无 LLM 可用时的纯文本降级摘要器"""

    def summarize(self, text: str) -> str:
        if not text:
            return "...[摘要]"
        max_len = min(100, max(1, len(text) // 2))
        return text[:max_len] + "...[摘要]"


# ---------------------------------------------------------------------------
# async 线程池兼容（Python < 3.9 回退）
# ---------------------------------------------------------------------------
def _to_thread(func, *args, **kwargs):
    if hasattr(asyncio, "to_thread"):
        return asyncio.to_thread(func, *args, **kwargs)
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(executor, lambda: func(*args, **kwargs))


class ShortTermMemory:
    """
    短期记忆管理
    P0-P3 四级优先级 + tiktoken 计数 + LRU 动态清理
    """

    def __init__(
        self,
        max_tokens: int = 180000,
        safety_threshold: float = 0.8,
        llm: Optional[Any] = None,
        token_counter: Optional[Callable[[str], int]] = None,
    ):
        config = get_config()
        self.max_tokens = max_tokens
        self.safety_threshold = safety_threshold
        self.token_limit = max(1, int(max_tokens * safety_threshold))
        self.memory: List[Dict[str, Any]] = []
        self.priority_order = {"P3": 0, "P2": 1, "P1": 2, "P0": 3}
        self._summarized_p1: List[Dict[str, Any]] = []
        self._token_counter = token_counter
        self._encoder = None
        if tiktoken is not None:
            try:
                self._encoder = tiktoken.get_encoding("cl100k_base")
            except Exception:
                pass

        # 初始化摘要器
        self._summarizer = self._init_summarizer(llm)

    def _init_summarizer(self, llm: Optional[Any]) -> Any:
        if llm is not None:
            if HAS_LANGCHAIN_MEMORY:
                try:
                    return ConversationSummaryMemory(llm=llm, return_messages=False)
                except Exception as e:
                    logger.warning(f"ConversationSummaryMemory 初始化失败: {e}，使用兼容层")
            return _CompatibleSummaryMemory(llm=llm)
        return _SimpleSummarizer()

    def _count_tokens(self, text: str) -> int:
        if self._token_counter is not None:
            return max(0, int(self._token_counter(text)))
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        if not text:
            return 0

        # fallback：英文近似按 4 字符/token，CJK 字符按 1 token 计。
        # 这样在缺少 tiktoken 的环境下不会严重低估中文短期记忆体量。
        tokens = 0
        ascii_run = 0
        for ch in text:
            code = ord(ch)
            is_cjk = (
                0x4E00 <= code <= 0x9FFF
                or 0x3400 <= code <= 0x4DBF
                or 0x20000 <= code <= 0x2A6DF
                or 0x2A700 <= code <= 0x2B73F
                or 0x2B740 <= code <= 0x2B81F
                or 0x2B820 <= code <= 0x2CEAF
                or 0xF900 <= code <= 0xFAFF
            )
            if is_cjk:
                if ascii_run:
                    tokens += (ascii_run + 3) // 4
                    ascii_run = 0
                tokens += 1
            elif ch.isspace():
                if ascii_run:
                    tokens += (ascii_run + 3) // 4
                    ascii_run = 0
            else:
                ascii_run += 1
        if ascii_run:
            tokens += (ascii_run + 3) // 4
        return max(1, tokens)

    def _summarize_text(self, text: str) -> str:
        """使用 ConversationSummaryMemory（或兼容层）生成摘要"""
        if HAS_LANGCHAIN_MEMORY and isinstance(self._summarizer, ConversationSummaryMemory):
            try:
                self._summarizer.clear()
                self._summarizer.save_context({"input": text}, {"output": ""})
                summary = self._summarizer.load_memory_variables({}).get("history", "")
                if summary and len(summary) > 10:
                    if len(summary) > 200:
                        summary = summary[:200] + "...[摘要]"
                    elif "...[摘要]" not in summary:
                        summary = summary + "...[摘要]"
                    return summary
            except Exception as e:
                logger.warning(f"ConversationSummaryMemory 摘要生成失败: {e}")
        elif isinstance(self._summarizer, _CompatibleSummaryMemory):
            self._summarizer.clear()
            self._summarizer.save_context({"input": text}, {"output": ""})
            summary = self._summarizer.load_memory_variables({}).get("history", "")
            if summary and len(summary) > 10:
                if len(summary) > 200:
                    summary = summary[:200] + "...[摘要]"
                elif "...[摘要]" not in summary:
                    summary = summary + "...[摘要]"
                return summary
        # 最终降级
        return self._summarizer.summarize(text)

    def add(self, content: str, priority: str = "P2", metadata: Optional[Dict] = None) -> None:
        """添加记忆条目（同步接口，保持向后兼容）"""
        if priority not in self.priority_order:
            raise MemoryManagerError(f"无效的优先级: {priority}")

        tokens = self._count_tokens(content)
        entry = {
            "content": content,
            "priority": priority,
            "timestamp": time.time(),
            "tokens": tokens,
            "metadata": metadata or {},
        }
        self.memory.append(entry)
        self._maybe_cleanup()

    def _maybe_cleanup(self) -> None:
        """检查并触发清理：清 P3 → P1 摘要降级 → P2 无损压缩"""
        total = sum(e["tokens"] for e in self.memory)
        if total <= self.token_limit:
            return

        logger.info(f"短期记忆 Token 超限 ({total}/{self.token_limit})，触发清理")

        # 按优先级排序（P3 最先处理），同优先级按时间戳 LRU（最老的先处理）
        sorted_entries = sorted(
            self.memory,
            key=lambda e: (self.priority_order[e["priority"]], e["timestamp"])
        )

        current_total = total

        # 阶段 1：清 P3
        to_remove = []
        for entry in sorted_entries:
            if current_total <= self.token_limit:
                break
            if entry["priority"] == "P3" and entry in self.memory:
                to_remove.append(entry)
                current_total -= entry["tokens"]

        for entry in to_remove:
            self.memory.remove(entry)
            logger.debug(f"删除 P3 记忆: {entry['content'][:50]}...")

        # 阶段 2：P1 摘要降级（ConversationSummaryMemory）
        if current_total > self.token_limit:
            p1_entries = [e for e in sorted_entries if e["priority"] == "P1" and e in self.memory]
            for entry in p1_entries:
                if current_total <= self.token_limit:
                    break
                if entry.get("summarized"):
                    continue
                idx = self.memory.index(entry)
                original = entry["content"]
                original_tokens = entry["tokens"]
                summary = self._summarize_text(original)
                summary_tokens = self._count_tokens(summary)

                # 记录摘要以供后续归档
                self._summarized_p1.append({
                    "original": original,
                    "summary": summary,
                    "metadata": entry.get("metadata", {}),
                    "timestamp": entry["timestamp"],
                })

                self.memory[idx]["content"] = summary
                self.memory[idx]["tokens"] = summary_tokens
                self.memory[idx]["summarized"] = True
                current_total = current_total - original_tokens + summary_tokens
                logger.debug(f"摘要 P1 记忆: {original[:50]}...")

        # 阶段 3：P2 无损压缩
        if current_total > self.token_limit:
            p2_entries = [e for e in sorted_entries if e["priority"] == "P2" and e in self.memory]
            for entry in p2_entries:
                if current_total <= self.token_limit:
                    break
                if entry.get("compressed"):
                    continue
                idx = self.memory.index(entry)
                original = entry["content"]
                original_tokens = entry["tokens"]
                half_len = max(10, len(original) // 2)
                compressed = original[:half_len] + "...[压缩]"
                compressed_tokens = self._count_tokens(compressed)

                self.memory[idx]["content"] = compressed
                self.memory[idx]["tokens"] = compressed_tokens
                self.memory[idx]["compressed"] = True
                current_total = current_total - original_tokens + compressed_tokens
                logger.debug(f"压缩 P2 记忆: {original[:50]}...")

    def get_context(self, max_tokens: Optional[int] = None) -> str:
        """获取当前上下文（按优先级排序，高优先级在前）"""
        limit = max_tokens or self.token_limit
        sorted_entries = sorted(
            self.memory,
            key=lambda e: (-self.priority_order[e["priority"]], e["timestamp"])
        )

        result = []
        current_tokens = 0
        for entry in sorted_entries:
            if current_tokens + entry["tokens"] > limit:
                break
            result.append(entry["content"])
            current_tokens += entry["tokens"]

        return "\n".join(result)

    def get_all(self) -> List[Dict[str, Any]]:
        return self.memory.copy()

    def get_p1_summaries(self) -> List[Dict[str, Any]]:
        """获取已摘要的 P1 记忆（供归档使用）"""
        return self._summarized_p1.copy()

    def clear_p1_summaries(self) -> None:
        """清空已记录的 P1 摘要"""
        self._summarized_p1 = []

    def clear(self) -> None:
        self.memory = []
        self._summarized_p1 = []


class LongTermMemory:
    """
    长期记忆管理
    基于 AgentFS 读写 4 个 Markdown 长期记忆库
    RAG 检索：VectorStore SelfQuery + BGE-Reranker 精排
    """

    DEFAULT_MEMORY_FILES = [
        "memory/核心指令归档.md",
        "memory/风险事件归档.md",
        "memory/处置经验归档.md",
        "memory/系统日志归档.md",
    ]

    def __init__(
        self,
        knowledge_base: Optional[KnowledgeBaseManager] = None,
        agentfs: Optional[AgentFS] = None,
        vector_store: Optional[VectorStore] = None,
        reranker: Optional[Reranker] = None,
    ):
        """
        Args:
            knowledge_base: 已弃用，仅保留用于向后兼容
            agentfs: AgentFS 实例，默认新建
            vector_store: VectorStore 实例，默认 None（按需创建）
            reranker: Reranker 实例，默认新建
        """
        if knowledge_base is not None:
            warnings.warn(
                "knowledge_base 参数已弃用，LongTermMemory 现在直接使用 AgentFS",
                DeprecationWarning,
                stacklevel=2,
            )

        config = get_config()
        self.agentfs = agentfs or AgentFS()
        self._vector_store = vector_store
        self._reranker = reranker
        self._top_k_retrieval = config.harness.memory.long_term.rag.get("top_k_retrieval", 10)
        self._legacy_initialized = False
        # 优先从配置读取归档文件列表，否则使用默认值
        cfg_archive = getattr(config.harness.memory.long_term, "archive_files", None)
        self.memory_files = cfg_archive if cfg_archive else self.DEFAULT_MEMORY_FILES
        self._ensure_memory_files()

    # ------------------------------------------------------------------
    # 旧版兼容属性 / 方法（基于 KnowledgeBaseManager 的稠密检索）
    # ------------------------------------------------------------------
    def _init_legacy_models(self) -> None:
        """初始化旧版嵌入模型（仅用于 retrieve 兼容方法）"""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            SentenceTransformer = None

        self._embedding_model = None
        self._legacy_reranker_model = None
        if SentenceTransformer is None:
            return

        try:
            self._embedding_model = SentenceTransformer("BAAI/bge-large-zh-v1.5")
        except Exception as e:
            logger.warning(f"旧版 Embedding 模型加载失败: {e}")

        try:
            self._legacy_reranker_model = SentenceTransformer("BAAI/bge-reranker-large")
        except Exception as e:
            logger.warning(f"旧版 Reranker 模型加载失败: {e}")

    def _build_legacy_index(self) -> None:
        """构建旧版知识库索引（仅用于 retrieve 兼容方法）"""
        self._chunks: List[str] = []
        self._embeddings: Optional[Any] = None
        self._chunk_sources: List[str] = []

        kb_files = [
            "工矿风险预警智能体合规执行书.md",
            "工业物理常识及传感器时间序列逻辑.md",
            "企业已具备的执行条件.md",
            "类似事故处理案例.md",
        ]

        for filename in kb_files:
            path = f"knowledge_base/{filename}"
            try:
                content = self.agentfs.read(path).decode("utf-8")
            except Exception:
                continue
            chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 20]
            for chunk in chunks:
                self._chunks.append(chunk[:500])
                self._chunk_sources.append(filename)

        if self._embedding_model is not None and self._chunks:
            try:
                import numpy as np
                self._embeddings = self._embedding_model.encode(self._chunks, normalize_embeddings=True)
                logger.info(f"旧版知识库索引构建完成，共 {len(self._chunks)} 个文本块")
            except Exception as e:
                logger.warning(f"旧版嵌入计算失败: {e}")

    def _ensure_legacy_initialized(self) -> None:
        if not self._legacy_initialized:
            self._init_legacy_models()
            self._build_legacy_index()
            self._legacy_initialized = True

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        旧版 RAG 检索（向后兼容）
        建议使用新的 recall() 方法以获得 SelfQuery + BGE-Reranker 精排能力
        """
        self._ensure_legacy_initialized()
        if not self._chunks:
            return []

        try:
            import numpy as np
            if self._embedding_model is not None and self._embeddings is not None:
                query_emb = self._embedding_model.encode([query], normalize_embeddings=True)
                similarities = np.dot(self._embeddings, query_emb.T).flatten()
                top_indices = np.argsort(-similarities)[:top_k * 2]
                candidates = [(idx, similarities[idx]) for idx in top_indices]
            else:
                candidates = []
                for i, chunk in enumerate(self._chunks):
                    score = sum(1 for w in query.split() if w in chunk)
                    candidates.append((i, score))
                candidates.sort(key=lambda x: -x[1])
                candidates = candidates[:top_k * 2]

            if self._legacy_reranker_model is not None:
                candidate_chunks = [self._chunks[idx] for idx, _ in candidates]
                pairs = [[query, chunk] for chunk in candidate_chunks]
                try:
                    scores = self._legacy_reranker_model.encode(pairs, convert_to_numpy=True)
                    if scores.ndim > 1:
                        scores = scores[:, 0]
                    reranked = sorted(zip(candidates, scores), key=lambda x: -x[1])
                    final_candidates = [x[0] for x in reranked[:top_k]]
                except Exception as e:
                    logger.warning(f"旧版 Reranker 失败，使用原始排序: {e}")
                    final_candidates = candidates[:top_k]
            else:
                final_candidates = candidates[:top_k]

            results = []
            for idx, score in final_candidates:
                results.append({
                    "content": self._chunks[idx],
                    "source": self._chunk_sources[idx],
                    "score": float(score),
                })
            return results
        except Exception as e:
            logger.error(f"旧版 RAG 检索失败: {e}")
            return []

    def add_experience(self, content: str) -> None:
        """旧版：添加经验到长期记忆（向后兼容）"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"\n\n## 记录 {timestamp}\n{content}\n"
        path = "knowledge_base/预警历史经验与短期记忆摘要.md"
        try:
            existing = self.agentfs.read(path).decode("utf-8")
        except Exception:
            existing = ""
        new_content = existing + entry
        self.agentfs.write(path, new_content.encode("utf-8"))
        self._build_legacy_index()

    # ------------------------------------------------------------------
    # 新版核心方法（基于 AgentFS + VectorStore + Reranker）
    # ------------------------------------------------------------------
    def _ensure_memory_files(self) -> None:
        """确保 4 个长期记忆库文件存在"""
        for path in self.memory_files:
            if not self.agentfs.exists(path):
                header = (
                    f"# {path.split('/')[-1].replace('.md', '')}\n\n"
                    "> 本文件由系统在运行时自动写入，记录长期记忆归档内容。\n\n"
                )
                self.agentfs.write(path, header.encode("utf-8"))

    def _get_vector_store(self) -> VectorStore:
        """延迟初始化 VectorStore"""
        if self._vector_store is None:
            self._vector_store = VectorStore()
        return self._vector_store

    def _get_reranker(self) -> Reranker:
        """延迟初始化 Reranker"""
        if self._reranker is None:
            self._reranker = Reranker()
        return self._reranker

    def is_rag_enabled(self) -> bool:
        """长期记忆 RAG 开关，默认开启；部署配置可显式关闭以隔离 native 依赖。"""
        try:
            env_override = _env_bool(["RAG_ENABLED", "MINING_RAG_ENABLED", "HARNESS_RAG_ENABLED"])
            if env_override is not None:
                return env_override
            config = get_config()
            return bool(config.harness.memory.long_term.rag.get("enabled", True))
        except Exception as e:
            logger.warning(f"读取 RAG 开关失败，默认关闭长期记忆召回: {e}")
            return False

    async def summarize_and_archive(
        self,
        p1_memories: List[Dict[str, Any]],
        target_file: Optional[str] = None,
    ) -> None:
        """
        将 P1 摘要追加写入长期记忆

        Args:
            p1_memories: P1 摘要记忆列表，每个元素应包含 summary / content、metadata、timestamp
            target_file: 目标归档文件路径（AgentFS 路径），默认使用 memory/风险事件归档.md
        """
        if not p1_memories:
            return

        archive_path = target_file or self.memory_files[1]  # memory/风险事件归档.md

        def _do_archive():
            try:
                existing = self.agentfs.read(archive_path).decode("utf-8")
            except Exception:
                existing = ""

            entries = []
            for mem in p1_memories:
                ts = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(mem.get("timestamp", time.time())),
                )
                summary = mem.get("summary", mem.get("content", ""))
                meta = json.dumps(mem.get("metadata", {}), ensure_ascii=False)
                entries.append(
                    f"## 归档记录 {ts}\n"
                    f"**原文摘要**: {summary}\n"
                    f"**元数据**: {meta}\n"
                )

            new_content = existing + "\n\n" + "\n\n".join(entries)
            self.agentfs.write(archive_path, new_content.encode("utf-8"))
            logger.info(f"已归档 {len(p1_memories)} 条 P1 摘要到 {archive_path}")

        await _to_thread(_do_archive)

    async def recall(
        self,
        query: str,
        risk_level: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        长期记忆召回

        1. VectorStore SelfQuery 检索（含 risk_level 元数据过滤）
        2. BGE-Reranker 精排，返回 top_k

        Args:
            query: 查询文本
            risk_level: 风险等级/类型，用于 SelfQuery 元数据过滤
            top_k: 返回结果数量

        Returns:
            检索结果列表，每个元素包含 text / metadata / id / rerank_score
        """
        if not query or not query.strip():
            return []
        if not self.is_rag_enabled():
            logger.info("长期记忆 RAG 已关闭，跳过向量召回")
            return []

        def _do_recall():
            # 构建 SelfQuery 过滤器
            filters = _risk_type_filter(risk_level)

            # 阶段 1：VectorStore 检索
            vs = self._get_vector_store()
            candidates = vs.self_query_retrieve(
                query=query,
                filters=filters if filters else None,
                top_k=self._top_k_retrieval,
            )
            if not candidates and filters:
                logger.info("带 risk_type 过滤未召回结果，降级为无过滤召回")
                candidates = vs.self_query_retrieve(
                    query=query,
                    filters=None,
                    top_k=self._top_k_retrieval,
                )

            if not candidates:
                return []

            # 阶段 2：BGE-Reranker 精排
            passages = []
            for c in candidates:
                passages.append({
                    "text": c.get("text", ""),
                    "metadata": c.get("metadata", {}),
                    "id": c.get("id", ""),
                    "distance": c.get("distance"),
                })

            reranker = self._get_reranker()
            ranked = reranker.rerank(query, passages, top_k=top_k)
            return ranked

        try:
            return await _to_thread(_do_recall)
        except ImportError:
            raise
        except Exception as e:
            logger.warning(f"长期记忆 RAG 召回失败，降级为空结果: {e}")
            return []

    def trace_event(self, commit_id: str) -> Dict[str, Any]:
        """事故溯源：通过 Commit ID 回滚到历史状态"""
        self.agentfs.rollback(commit_id)
        return {
            "commit_id": commit_id,
            "status": "rollback_completed",
            "timestamp": time.time(),
        }


class HybridMemoryManager:
    """
    长短期混合记忆管理器
    """

    def __init__(
        self,
        short_term: Optional[ShortTermMemory] = None,
        long_term: Optional[LongTermMemory] = None,
    ):
        config = get_config()
        self.short_term = short_term or ShortTermMemory(
            max_tokens=config.harness.memory.short_term.max_tokens,
            safety_threshold=config.harness.memory.short_term.safety_threshold,
        )
        self.long_term = long_term or LongTermMemory()

    def add_short_term(self, content: str, priority: str = "P2", metadata: Optional[Dict] = None) -> None:
        """添加短期记忆（同步）"""
        self.short_term.add(content, priority, metadata)

    def query_long_term(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        旧版长期记忆查询（向后兼容）
        建议使用 recall_long_term() 以获得 SelfQuery + BGE-Reranker 能力
        """
        return self.long_term.retrieve(query, top_k=top_k)

    async def recall_long_term(
        self,
        query: str,
        risk_level: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """新版长期记忆召回（异步，含 SelfQuery + BGE-Reranker）"""
        return await self.long_term.recall(query, risk_level=risk_level, top_k=top_k)

    def is_long_term_rag_enabled(self) -> bool:
        """返回长期记忆 RAG 是否启用，供工作流输出更准确的节点状态。"""
        return self.long_term.is_rag_enabled()

    def get_combined_context(self, query: str, max_tokens: Optional[int] = None) -> str:
        """获取组合上下文：短期记忆 + 长期记忆查询提示"""
        short_context = self.short_term.get_context(max_tokens=max_tokens)
        return f"【短期记忆】\n{short_context}\n\n【长期记忆查询】\n{query}"

    async def archive_experience(self) -> None:
        """将短期记忆中 P1 摘要归档到长期记忆（异步）"""
        p1_summaries = self.short_term.get_p1_summaries()
        if p1_summaries:
            await self.long_term.summarize_and_archive(p1_summaries)
            self.short_term.clear_p1_summaries()
            logger.info(f"已归档 {len(p1_summaries)} 条 P1 摘要到长期记忆")
