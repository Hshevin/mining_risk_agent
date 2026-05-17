"""
三重校验与高风险阻断机制
MARCH 声明级孤立验证 + 蒙特卡洛置信度检验 + LangGraph 物理隔离 Checker 节点
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from mining_risk_serve.harness.knowledge_base import KnowledgeBaseManager
from mining_risk_serve.harness.monte_carlo import MonteCarloValidator
from mining_risk_serve.harness.proposer import Proposer
from mining_risk_serve.harness.risk_assessment import RiskAssessor
from mining_risk_common.utils.config import get_config, resolve_project_path
from mining_risk_common.utils.exceptions import HighRiskBlockedError, ValidationError
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Knowledge-base rule anchors
# =============================================================================

# These anchors keep the hard-coded safety gates traceable to the Markdown
# rule knowledge bases rebuilt by scripts/rebuild_rule_kbs.py.
COMPLIANCE_RULE_REFERENCES = [
    {"rule_id": "COM-RED-019", "keyword": "瓦斯浓度超限"},
    {"rule_id": "COM-RED-014", "keyword": "通风系统停运"},
    {"rule_id": "COM-RED-003", "keyword": "无证上岗"},
    {"rule_id": "COM-RED-001", "keyword": "超能力生产"},
    {"rule_id": "COM-RED-018", "keyword": "隐瞒事故"},
    {"rule_id": "COM-RED-018", "keyword": "销毁监控记录"},
    {"rule_id": "COM-RED-005", "keyword": "破坏安全监控"},
    {"rule_id": "COM-RED-005", "keyword": "关闭报警设备"},
    {"rule_id": "COM-RED-005", "keyword": "屏蔽传感器"},
    {"rule_id": "COM-RED-018", "keyword": "删除日志"},
    {"rule_id": "COM-RED-018", "keyword": "伪造数据"},
]

LOGIC_RULE_REFERENCES = {
    "temperature_impossible_normal": "PHY-GEN-002",
    "zero_sensor_not_safe": "PHY-GEN-003",
    "negative_pressure_conflict": "PHY-TS-006",
}

FEASIBILITY_RULE_REFERENCES = {
    "micro_shutdown": "SOP-ROUTE-RED",
    "micro_evacuation": "SOP-ROUTE-RED",
    "micro_large_purchase": "SOP-CHECK-001",
}

DOC_TYPE_FILES = {
    "compliance": ["工矿风险预警智能体合规执行书.md"],
    "physics": ["工业物理常识及传感器时间序列逻辑.md"],
    "conditions": ["企业已具备的执行条件.md"],
    "sop": ["部门分级审核SOP.md"],
    "cases": ["类似事故处理案例.md"],
}

VALIDATION_DOC_TYPES = {
    "compliance": ["compliance"],
    "logic": ["physics"],
    "feasibility": ["conditions", "sop", "cases"],
}

RAG_ENV_SWITCHES = (
    "HARNESS_RAG_ENABLED",
    "MINING_RAG_ENABLED",
    "RAG_ENABLED",
)


# =============================================================================
# Pydantic 模型
# =============================================================================

class Evidence(BaseModel):
    """单条校验证据，来自正式 RAG、Markdown 扫描或内置兜底规则。"""

    source_file: str = Field(default="", description="证据来源文件")
    section_title: str = Field(default="", description="证据所在章节")
    rule_id: str = Field(default="", description="COM/PHY 等规则 ID")
    sop_id: str = Field(default="", description="SOP ID")
    case_id: str = Field(default="", description="案例 ID")
    doc_type: str = Field(default="", description="知识库文档类型")
    matched_text: str = Field(default="", description="命中文本摘要")
    score: Optional[float] = Field(default=None, description="相似度或规则匹配分")
    distance: Optional[float] = Field(default=None, description="向量距离")
    layer: str = Field(default="", description="校验层级：compliance / logic / feasibility")
    proposition_id: str = Field(default="", description="关联原子命题 ID")


class ValidationResult(BaseModel):
    """
    MARCH 校验结果 Pydantic 模型
    字段命名兼容：pass_ 在 Python 侧，序列化/构造时可用 pass
    """
    model_config = ConfigDict(populate_by_name=True)

    pass_: bool = Field(
        default=False,
        alias="pass",
        description="是否通过校验",
    )
    violated_propositions: List[str] = Field(
        default_factory=list,
        description="被违反的原子命题 ID 列表",
    )
    reason: str = Field(
        default="",
        description="结构化修正反馈",
    )
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="失败或阻断时引用的结构化证据",
    )
    supporting_evidence: List[Evidence] = Field(
        default_factory=list,
        description="通过时用于审计的支持性证据",
    )


# =============================================================================
# 信息隔离辅助函数
# =============================================================================

def _get_isolated_propositions(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    信息隔离：仅提取 state["atomic_propositions"]
    明确禁止访问 state["raw_data"] 与 state["decision"]
    """
    if "atomic_propositions" not in state:
        raise ValidationError(
            "state 中缺少 atomic_propositions，无法执行 MARCH 校验"
        )
    return state["atomic_propositions"]


# =============================================================================
# 证据检索层：正式 Chroma/RAG -> Markdown 扫描 -> builtin fallback
# =============================================================================

def _env_bool(names: Iterable[str]) -> Optional[bool]:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return None


def _compact_text(text: str, limit: int = 260) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _extract_first(patterns: Sequence[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return ""


def _extract_rule_id(text: str) -> str:
    return _extract_first(
        [
            r"\b((?:COM|PHY)-[A-Z]+-\d{3})\b",
            r"\b((?:COM|PHY)-[A-Z]+-\d{3,})\b",
        ],
        text,
    )


def _extract_sop_id(text: str) -> str:
    return _extract_first([r"\b(SOP-[A-Z]+-\d{3})\b"], text)


def _extract_case_id(text: str) -> str:
    return _extract_first(
        [
            r"case_id[：:]\s*`?([A-E]-\d{3})`?",
            r"\b([A-E]-\d{3})[｜|]",
            r"\b([A-E]-\d{3})\b",
        ],
        text,
    )


def _identifier_field(identifier: str) -> Optional[str]:
    if identifier.startswith(("COM-", "PHY-")):
        return "rule_id"
    if identifier.startswith("SOP-"):
        return "sop_id"
    if re.match(r"^[A-E]-\d{3}$", identifier):
        return "case_id"
    return None


def _infer_doc_type_from_path(path: Path) -> str:
    name = path.name
    for doc_type, filenames in DOC_TYPE_FILES.items():
        if name in filenames:
            return doc_type
    return "general"


def _lexical_score(query: str, text: str, preferred_ids: Sequence[str] = ()) -> float:
    query_norm = re.sub(r"\s+", "", (query or "").lower())
    text_norm = re.sub(r"\s+", "", (text or "").lower())
    if not query_norm or not text_norm:
        return 0.0

    score = 0.0
    for identifier in preferred_ids:
        if identifier and identifier.lower() in text_norm:
            score += 20.0

    ascii_terms = re.findall(r"[a-z0-9_]+", query_norm)
    for term in ascii_terms:
        if len(term) > 1 and term in text_norm:
            score += 2.0

    for n, weight in ((4, 1.4), (3, 1.1), (2, 0.7)):
        if len(query_norm) < n:
            continue
        grams = {query_norm[i:i + n] for i in range(len(query_norm) - n + 1)}
        if not grams:
            continue
        hits = sum(1 for gram in grams if gram in text_norm)
        score += weight * hits / len(grams)
    return score


class EvidenceRetriever:
    """
    校验证据检索器。

    优先读取正式 var/chroma / knowledge_base collection；当 RAG 关闭、
    索引缺失或依赖不可用时，降级扫描 Markdown 文件。调用方仍可在没有
    外部模型的 deterministic fallback embedding 环境下稳定运行。
    """

    def __init__(
        self,
        kb_dir: str = "knowledge_base",
        persist_directory: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        self.kb_dir = self._resolve_path(kb_dir)
        config = get_config()
        rag_config = config.harness.memory.long_term.rag
        self.persist_directory = self._resolve_path(
            persist_directory or rag_config.get("persist_directory", "var/chroma")
        )
        self.collection_name = collection_name or rag_config.get("collection_name", "knowledge_base")
        self._vector_store: Optional[Any] = None
        self._cache: Dict[Tuple[Any, ...], List[Evidence]] = {}

    @staticmethod
    def _resolve_path(path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return resolve_project_path(path_value)

    def rag_enabled(self) -> bool:
        env_value = _env_bool(RAG_ENV_SWITCHES)
        if env_value is not None:
            return env_value
        try:
            return bool(get_config().harness.memory.long_term.rag.get("enabled", True))
        except Exception:
            return True

    def retrieve(
        self,
        query: str,
        layer: str,
        doc_types: Sequence[str],
        preferred_ids: Optional[Sequence[str]] = None,
        top_k: int = 3,
        proposition_id: str = "",
    ) -> List[Evidence]:
        preferred = tuple(i for i in (preferred_ids or []) if i)
        normalized_doc_types = tuple(doc_types)
        cache_key = (
            query,
            layer,
            normalized_doc_types,
            preferred,
            top_k,
            proposition_id,
            self.rag_enabled(),
            str(self.persist_directory),
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [item.model_copy() for item in cached]

        evidence: List[Evidence] = []
        if self.rag_enabled():
            evidence.extend(
                self._retrieve_from_chroma(
                    query=query,
                    layer=layer,
                    doc_types=normalized_doc_types,
                    preferred_ids=preferred,
                    top_k=top_k,
                    proposition_id=proposition_id,
                )
            )

        if len(evidence) < top_k:
            evidence.extend(
                self._retrieve_from_markdown(
                    query=query,
                    layer=layer,
                    doc_types=normalized_doc_types,
                    preferred_ids=preferred,
                    top_k=top_k,
                    proposition_id=proposition_id,
                )
            )

        deduped = self._dedupe(evidence)[:top_k]
        self._cache[cache_key] = [item.model_copy() for item in deduped]
        return deduped

    def _get_vector_store(self) -> Optional[Any]:
        if self._vector_store is not None:
            return self._vector_store
        if not (self.persist_directory / "chroma.sqlite3").exists():
            return None
        try:
            from mining_risk_serve.harness.vector_store import VectorStore

            self._vector_store = VectorStore(
                persist_directory=str(self.persist_directory),
                collection_name=self.collection_name,
                embedding_backend=os.getenv("VALIDATION_RAG_EMBEDDING_BACKEND", "fallback"),
            )
        except Exception as exc:
            logger.warning(f"校验证据 RAG 初始化失败，降级为 Markdown 扫描: {exc}")
            self._vector_store = None
        return self._vector_store

    def _retrieve_from_chroma(
        self,
        query: str,
        layer: str,
        doc_types: Sequence[str],
        preferred_ids: Sequence[str],
        top_k: int,
        proposition_id: str,
    ) -> List[Evidence]:
        store = self._get_vector_store()
        if store is None:
            return []

        output: List[Evidence] = []
        try:
            for identifier in preferred_ids:
                field = _identifier_field(identifier)
                if not field:
                    continue
                items = store.collection.get(
                    where={field: {"$eq": identifier}},
                    include=["documents", "metadatas"],
                    limit=max(top_k, 1),
                )
                ids = items.get("ids") or []
                documents = items.get("documents") or []
                metadatas = items.get("metadatas") or []
                for idx, _ in enumerate(ids):
                    text = documents[idx] if idx < len(documents) else ""
                    metadata = metadatas[idx] if idx < len(metadatas) else {}
                    doc_type = metadata.get("doc_type", "")
                    if doc_types and doc_type not in doc_types:
                        continue
                    output.append(
                        self._evidence_from_payload(
                            text=text,
                            metadata=metadata,
                            layer=layer,
                            proposition_id=proposition_id,
                            score=1.0,
                            distance=0.0,
                        )
                    )

            query_text = " ".join([query, *preferred_ids]).strip()
            for doc_type in doc_types:
                results = store.self_query_retrieve(
                    query=query_text,
                    filters={"doc_type": doc_type},
                    top_k=max(top_k, 3),
                )
                for result in results:
                    output.append(
                        self._evidence_from_payload(
                            text=result.get("text", ""),
                            metadata=result.get("metadata", {}),
                            layer=layer,
                            proposition_id=proposition_id,
                            score=result.get("rerank_score"),
                            distance=result.get("distance"),
                        )
                    )
        except Exception as exc:
            logger.warning(f"校验证据 RAG 检索失败，降级为 Markdown 扫描: {exc}")
            return []
        return output

    def _retrieve_from_markdown(
        self,
        query: str,
        layer: str,
        doc_types: Sequence[str],
        preferred_ids: Sequence[str],
        top_k: int,
        proposition_id: str,
    ) -> List[Evidence]:
        candidates: List[Tuple[float, Evidence]] = []
        for path, doc_type in self._iter_doc_paths(doc_types):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning(f"读取校验证据 Markdown 失败 {path}: {exc}")
                continue

            for section_title, fragment in self._iter_fragments(text, path.stem):
                if not fragment.strip():
                    continue
                score = _lexical_score(query, fragment, preferred_ids=preferred_ids)
                if preferred_ids and any(identifier in fragment for identifier in preferred_ids):
                    score += 20.0
                if score <= 0:
                    continue

                evidence = Evidence(
                    source_file=self._source_file(path),
                    section_title=section_title,
                    rule_id=_extract_rule_id(fragment),
                    sop_id=_extract_sop_id(fragment),
                    case_id=_extract_case_id(fragment),
                    doc_type=doc_type,
                    matched_text=_compact_text(fragment),
                    score=round(score, 4),
                    distance=None,
                    layer=layer,
                    proposition_id=proposition_id,
                )
                candidates.append((score, evidence))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in candidates[:top_k]]

    def _iter_doc_paths(self, doc_types: Sequence[str]) -> Iterable[Tuple[Path, str]]:
        seen: set[Path] = set()
        for doc_type in doc_types:
            filenames = DOC_TYPE_FILES.get(doc_type, [])
            for filename in filenames:
                path = self.kb_dir / filename
                if path.exists() and path not in seen:
                    seen.add(path)
                    yield path, doc_type
        if not seen and self.kb_dir.exists():
            for path in self.kb_dir.glob("*.md"):
                yield path, _infer_doc_type_from_path(path)

    def _source_file(self, path: Path) -> str:
        try:
            return path.relative_to(resolve_project_path(".")).as_posix()
        except Exception:
            return path.as_posix()

    def _iter_fragments(self, text: str, default_title: str) -> Iterable[Tuple[str, str]]:
        current_title = default_title
        paragraph: List[str] = []

        def flush_paragraph() -> Iterable[Tuple[str, str]]:
            if paragraph:
                joined = "\n".join(paragraph).strip()
                paragraph.clear()
                if joined:
                    yield current_title, joined

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                yield from flush_paragraph()
                continue
            if stripped.startswith("#"):
                yield from flush_paragraph()
                current_title = stripped.lstrip("#").strip() or current_title
                continue
            if stripped.startswith("|") or stripped.startswith("- ") or len(stripped) >= 80:
                yield from flush_paragraph()
                yield current_title, stripped
                continue
            paragraph.append(stripped)
        yield from flush_paragraph()

    def _evidence_from_payload(
        self,
        text: str,
        metadata: Dict[str, Any],
        layer: str,
        proposition_id: str,
        score: Optional[float],
        distance: Optional[float],
    ) -> Evidence:
        rule_id = metadata.get("rule_id") or _extract_rule_id(text)
        sop_id = metadata.get("sop_id") or _extract_sop_id(text)
        case_id = metadata.get("case_id") or _extract_case_id(text)
        if score is None and distance is not None:
            try:
                score = 1.0 - float(distance)
            except Exception:
                score = None
        return Evidence(
            source_file=metadata.get("source_file", ""),
            section_title=metadata.get("section_title", ""),
            rule_id=rule_id or "",
            sop_id=sop_id or "",
            case_id=case_id or "",
            doc_type=metadata.get("doc_type", ""),
            matched_text=_compact_text(text),
            score=float(score) if score is not None else None,
            distance=float(distance) if distance is not None else None,
            layer=layer,
            proposition_id=proposition_id,
        )

    def _dedupe(self, evidence: Sequence[Evidence]) -> List[Evidence]:
        deduped: List[Evidence] = []
        seen: set[Tuple[str, str, str, str, str]] = set()
        for item in evidence:
            key = (
                item.source_file,
                item.section_title,
                item.rule_id or item.sop_id or item.case_id,
                item.doc_type,
                item.matched_text[:120],
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped


_EVIDENCE_RETRIEVER: Optional[EvidenceRetriever] = None


def get_validation_evidence_retriever() -> EvidenceRetriever:
    global _EVIDENCE_RETRIEVER
    if _EVIDENCE_RETRIEVER is None:
        _EVIDENCE_RETRIEVER = EvidenceRetriever()
    return _EVIDENCE_RETRIEVER


def _builtin_evidence(
    *,
    layer: str,
    identifier: str,
    matched_text: str,
    proposition_id: str,
) -> Evidence:
    field = _identifier_field(identifier)
    return Evidence(
        source_file="builtin_fallback_rules",
        section_title=f"{layer} fallback safety gates",
        rule_id=identifier if field == "rule_id" else "",
        sop_id=identifier if field == "sop_id" else "",
        case_id=identifier if field == "case_id" else "",
        doc_type="builtin",
        matched_text=_compact_text(matched_text),
        score=1.0,
        distance=0.0,
        layer=layer,
        proposition_id=proposition_id,
    )


def _ensure_evidence(
    evidence: List[Evidence],
    *,
    layer: str,
    identifier: str,
    matched_text: str,
    proposition_id: str,
) -> List[Evidence]:
    if evidence:
        return evidence
    return [
        _builtin_evidence(
            layer=layer,
            identifier=identifier,
            matched_text=matched_text,
            proposition_id=proposition_id,
        )
    ]


def _format_evidence_source(evidence: Sequence[Evidence]) -> str:
    if not evidence:
        return "无外部证据，已使用内置兜底规则"
    item = evidence[0]
    identifier = item.rule_id or item.sop_id or item.case_id or item.doc_type
    parts = [part for part in [item.source_file, item.section_title, identifier] if part]
    return " / ".join(parts) if parts else item.source_file or "unknown evidence"


def _serialize_evidence(evidence: Sequence[Evidence]) -> List[Dict[str, Any]]:
    return [item.model_dump() if hasattr(item, "model_dump") else dict(item) for item in evidence]


def _compliance_violation(text: str) -> Optional[Dict[str, str]]:
    for rule in COMPLIANCE_RULE_REFERENCES:
        if rule["keyword"] in text:
            return {
                "rule_id": rule["rule_id"],
                "keyword": rule["keyword"],
                "message": f"触发合规红线 {rule['rule_id']}：{rule['keyword']}",
            }

    if "销毁" in text and ("监控" in text or "记录" in text or "视频" in text):
        return {
            "rule_id": "COM-RED-018",
            "keyword": "销毁监控记录",
            "message": "触发合规红线 COM-RED-018：严禁销毁监控记录、删除日志或伪造数据",
        }
    if ("关闭" in text or "屏蔽" in text or "停用" in text) and (
        "报警" in text or "监控" in text or "传感器" in text or "联锁" in text
    ):
        return {
            "rule_id": "COM-RED-005",
            "keyword": "关闭报警/监控/传感器/联锁",
            "message": "触发合规红线 COM-RED-005：禁止屏蔽、关闭、破坏或绕过安全监控报警设施",
        }
    if ("无证" in text or "未持证" in text) and "上岗" in text:
        return {
            "rule_id": "COM-RED-003",
            "keyword": "无证上岗",
            "message": "触发合规红线 COM-RED-003：特种作业人员无有效证件不得上岗",
        }
    if "超能力" in text and ("生产" in text or "组织作业" in text):
        return {
            "rule_id": "COM-RED-001",
            "keyword": "超能力生产",
            "message": "触发合规红线 COM-RED-001：重大隐患或红级预警不得继续扩大生产",
        }
    return None


def _logic_violation(text: str) -> Optional[Dict[str, str]]:
    if "温度" in text and ("超过 100°C 正常" in text or "100度正常" in text):
        return {
            "rule_id": LOGIC_RULE_REFERENCES["temperature_impossible_normal"],
            "keyword": "温度超过 100°C 正常",
            "message": (
                f"与物理常识冲突 {LOGIC_RULE_REFERENCES['temperature_impossible_normal']}："
                "环境温度不可能超过 100°C 仍正常"
            ),
        }
    if "瓦斯浓度" in text and ("0%" in text or "无瓦斯" in text) and "正常生产" in text:
        return {
            "rule_id": LOGIC_RULE_REFERENCES["zero_sensor_not_safe"],
            "keyword": "瓦斯浓度 0% 正常生产",
            "message": (
                f"逻辑错误 {LOGIC_RULE_REFERENCES['zero_sensor_not_safe']}："
                "瓦斯浓度为 0% 时无法判定为正常生产（可能存在传感器故障）"
            ),
        }
    if "负压" in text and "正常" in text and "管道" in text:
        return {
            "rule_id": LOGIC_RULE_REFERENCES["negative_pressure_conflict"],
            "keyword": "负压正常冲突",
            "message": (
                f"逻辑错误 {LOGIC_RULE_REFERENCES['negative_pressure_conflict']}："
                "管道负压异常，需检查泄漏或风机故障"
            ),
        }
    return None


def _feasibility_violation(text: str) -> Optional[Dict[str, str]]:
    is_micro = "微型" in text or "小微" in text
    if "立即停产" in text and is_micro:
        return {
            "sop_id": FEASIBILITY_RULE_REFERENCES["micro_shutdown"],
            "keyword": "微型企业立即停产",
            "message": (
                f"处置可行性需核实 {FEASIBILITY_RULE_REFERENCES['micro_shutdown']}："
                "微型企业可能不具备立即停产的应急组织和现场管控条件"
            ),
        }
    if "撤离" in text and "全员" in text and is_micro:
        return {
            "sop_id": FEASIBILITY_RULE_REFERENCES["micro_evacuation"],
            "keyword": "微型企业全员撤离",
            "message": (
                f"处置可行性需核实 {FEASIBILITY_RULE_REFERENCES['micro_evacuation']}："
                "微型企业人员疏散能力有限，需核实岗位、通道和外部协同"
            ),
        }
    if (
        ("购置" in text or "采购" in text or "新建" in text)
        and ("大型设备" in text or "成套系统" in text or "大型成套" in text)
        and is_micro
    ):
        return {
            "sop_id": FEASIBILITY_RULE_REFERENCES["micro_large_purchase"],
            "keyword": "微型企业购置大型成套系统",
            "message": (
                f"处置可行性需核实 {FEASIBILITY_RULE_REFERENCES['micro_large_purchase']}："
                "微型企业可能不具备立即购置大型成套系统所需的资金、场地、人员和补证条件"
            ),
        }
    return None


# =============================================================================
# LangGraph 物理隔离 Checker 节点（3 个独立函数）
# =============================================================================

def compliance_checker(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph 合规红线 Checker 节点
    信息隔离：仅允许读取 state["atomic_propositions"]
    """
    propositions = _get_isolated_propositions(state)
    retriever = get_validation_evidence_retriever()
    violated: List[Dict[str, Any]] = []
    supporting_evidence: List[Evidence] = []

    for prop in propositions:
        text = prop.get("proposition", "")
        prop_id = prop.get("id", "unknown")
        violation = _compliance_violation(text)

        if violation:
            rule_id = violation["rule_id"]
            evidence = retriever.retrieve(
                query=f"{text} {rule_id} {violation['keyword']}",
                layer="compliance",
                doc_types=VALIDATION_DOC_TYPES["compliance"],
                preferred_ids=[rule_id],
                top_k=3,
                proposition_id=prop_id,
            )
            evidence = _ensure_evidence(
                evidence,
                layer="compliance",
                identifier=rule_id,
                matched_text=violation["message"],
                proposition_id=prop_id,
            )
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": violation["message"],
                "evidence": evidence,
            })
        else:
            supporting_evidence.extend(
                retriever.retrieve(
                    query=text,
                    layer="compliance",
                    doc_types=VALIDATION_DOC_TYPES["compliance"],
                    top_k=1,
                    proposition_id=prop_id,
                )
            )

    passed = len(violated) == 0
    reason = (
        "合规红线校验通过"
        if passed
        else "[合规红线] " + "; ".join(
            f"[{v['id']}] {v['violation']}（证据：{_format_evidence_source(v['evidence'])}）: {v['proposition']}"
            for v in violated
        )
    )
    evidence = [item for v in violated for item in v["evidence"]]

    return {
        "validation_result": ValidationResult(
            pass_=passed,
            violated_propositions=[v["id"] for v in violated],
            reason=reason,
            evidence=evidence,
            supporting_evidence=[] if not passed else supporting_evidence[:5],
        )
    }


def logic_checker(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph 工况逻辑 Checker 节点
    信息隔离：仅允许读取 state["atomic_propositions"]
    """
    propositions = _get_isolated_propositions(state)
    retriever = get_validation_evidence_retriever()
    violated: List[Dict[str, Any]] = []
    supporting_evidence: List[Evidence] = []

    for prop in propositions:
        text = prop.get("proposition", "")
        prop_id = prop.get("id", "unknown")
        violation = _logic_violation(text)

        if violation:
            rule_id = violation["rule_id"]
            evidence = retriever.retrieve(
                query=f"{text} {rule_id} {violation['keyword']}",
                layer="logic",
                doc_types=VALIDATION_DOC_TYPES["logic"],
                preferred_ids=[rule_id],
                top_k=3,
                proposition_id=prop_id,
            )
            evidence = _ensure_evidence(
                evidence,
                layer="logic",
                identifier=rule_id,
                matched_text=violation["message"],
                proposition_id=prop_id,
            )
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": violation["message"],
                "evidence": evidence,
            })
        else:
            supporting_evidence.extend(
                retriever.retrieve(
                    query=text,
                    layer="logic",
                    doc_types=VALIDATION_DOC_TYPES["logic"],
                    top_k=1,
                    proposition_id=prop_id,
                )
            )

    passed = len(violated) == 0
    reason = (
        "工况逻辑校验通过"
        if passed
        else "[工况逻辑] " + "; ".join(
            f"[{v['id']}] {v['violation']}（证据：{_format_evidence_source(v['evidence'])}）: {v['proposition']}"
            for v in violated
        )
    )
    evidence = [item for v in violated for item in v["evidence"]]

    return {
        "validation_result": ValidationResult(
            pass_=passed,
            violated_propositions=[v["id"] for v in violated],
            reason=reason,
            evidence=evidence,
            supporting_evidence=[] if not passed else supporting_evidence[:5],
        )
    }


def feasibility_checker(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph 处置可行性 Checker 节点
    信息隔离：仅允许读取 state["atomic_propositions"]
    """
    propositions = _get_isolated_propositions(state)
    retriever = get_validation_evidence_retriever()
    violated: List[Dict[str, Any]] = []
    supporting_evidence: List[Evidence] = []

    for prop in propositions:
        text = prop.get("proposition", "")
        prop_id = prop.get("id", "unknown")
        violation = _feasibility_violation(text)

        if violation:
            sop_id = violation["sop_id"]
            evidence = retriever.retrieve(
                query=f"{text} {sop_id} 企业执行条件 人员 资金 场地 补证 案例 {violation['keyword']}",
                layer="feasibility",
                doc_types=VALIDATION_DOC_TYPES["feasibility"],
                preferred_ids=[sop_id],
                top_k=4,
                proposition_id=prop_id,
            )
            evidence = _ensure_evidence(
                evidence,
                layer="feasibility",
                identifier=sop_id,
                matched_text=violation["message"],
                proposition_id=prop_id,
            )
            violated.append({
                "id": prop_id,
                "proposition": text,
                "violation": violation["message"],
                "evidence": evidence,
            })
        else:
            supporting_evidence.extend(
                retriever.retrieve(
                    query=text,
                    layer="feasibility",
                    doc_types=VALIDATION_DOC_TYPES["feasibility"],
                    top_k=1,
                    proposition_id=prop_id,
                )
            )

    passed = len(violated) == 0
    reason = (
        "处置可行性校验通过"
        if passed
        else "[处置可行性] " + "; ".join(
            f"[{v['id']}] {v['violation']}（证据：{_format_evidence_source(v['evidence'])}）: {v['proposition']}"
            for v in violated
        )
    )
    evidence = [item for v in violated for item in v["evidence"]]

    return {
        "validation_result": ValidationResult(
            pass_=passed,
            violated_propositions=[v["id"] for v in violated],
            reason=reason,
            evidence=evidence,
            supporting_evidence=[] if not passed else supporting_evidence[:5],
        )
    }


# =============================================================================
# 分级顺序执行：合规红线 → 工况逻辑 → 处置可行性
# =============================================================================

def run_march_validation(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    按分级顺序执行 MARCH 校验：
    合规红线 → 工况逻辑 → 处置可行性
    任意一级不通过即暂停并返回结构化修正反馈
    """
    supporting_evidence: List[Evidence] = []

    # Level 1: 合规红线
    result = compliance_checker(state)
    if not result["validation_result"].pass_:
        logger.warning(
            f"MARCH 合规红线拦截: {result['validation_result'].reason}"
        )
        return result
    supporting_evidence.extend(result["validation_result"].supporting_evidence)

    # Level 2: 工况逻辑
    result = logic_checker(state)
    if not result["validation_result"].pass_:
        logger.warning(
            f"MARCH 工况逻辑拦截: {result['validation_result'].reason}"
        )
        return result
    supporting_evidence.extend(result["validation_result"].supporting_evidence)

    # Level 3: 处置可行性
    result = feasibility_checker(state)
    if not result["validation_result"].pass_:
        logger.warning(
            f"MARCH 处置可行性拦截: {result['validation_result'].reason}"
        )
        return result
    supporting_evidence.extend(result["validation_result"].supporting_evidence)

    return {
        "validation_result": ValidationResult(
            pass_=True,
            reason="MARCH 三重校验全部通过",
            supporting_evidence=supporting_evidence[:9],
        )
    }


# =============================================================================
# ToolCallInterceptor：拦截所有工具调用请求，注入风险评估
# =============================================================================

class ToolCallInterceptor:
    """
    工具调用拦截器：对所有工具调用注入风险评估
    """

    def __init__(self, risk_assessor: Optional[RiskAssessor] = None):
        self.risk_assessor = risk_assessor or RiskAssessor()
        self.intercepted_calls: List[Dict[str, Any]] = []

    def intercept(
        self, tool_name: str, tool_func: Callable, *args: Any, **kwargs: Any
    ) -> Any:
        """
        拦截工具调用：先评估风险，通过后再执行原函数
        """
        risk = self.risk_assessor.assess_tool_call(tool_name, args, kwargs)
        self.intercepted_calls.append({
            "tool_name": tool_name,
            "args": args,
            "kwargs": kwargs,
            "risk": risk,
            "timestamp": time.time(),
        })

        if risk.get("blocked"):
            logger.error(
                f"工具调用被拦截: {tool_name}, 原因: {risk.get('reason')}"
            )
            raise HighRiskBlockedError(
                f"工具调用 {tool_name} 被风险拦截: {risk.get('reason')}"
            )

        logger.info(f"工具调用通过风险评估: {tool_name}")
        return tool_func(*args, **kwargs)

    def wrap(self, tool_name: str, tool_func: Callable) -> Callable:
        """返回一个被拦截器包装的工具函数"""
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.intercept(tool_name, tool_func, *args, **kwargs)
        return wrapper


# =============================================================================
# 向后兼容的包装类（保留旧接口）
# =============================================================================

class Checker:
    """
    兼容旧接口的 Checker 包装类
    test_harness.py 仍可直接 from harness.validation import Checker
    """

    def __init__(self, knowledge_base: Optional[KnowledgeBaseManager] = None):
        self.kb = knowledge_base or KnowledgeBaseManager()

    def check(self, propositions: List[Dict[str, str]]) -> Dict[str, Any]:
        state = {"atomic_propositions": propositions}
        result = run_march_validation(state)
        vr = result["validation_result"]
        return {
            "passed": vr.pass_,
            "level": "PASS" if vr.pass_ else "BLOCK",
            "details": [],
            "feedback": vr.reason,
            "evidence": _serialize_evidence(vr.evidence),
            "supporting_evidence": _serialize_evidence(vr.supporting_evidence),
            "timestamp": time.time(),
        }


class ValidationPipeline:
    """
    兼容旧接口的完整校验流水线
    test_harness.py 仍可直接 from harness.validation import ValidationPipeline
    """

    def __init__(self):
        self.kb = KnowledgeBaseManager()
        self.checker = Checker(self.kb)
        self.mc_validator = MonteCarloValidator()
        self.risk_assessor = RiskAssessor()

    def run(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        # Step 1: MARCH 声明级孤立验证
        propositions = Proposer.decompose(decision)
        march_result = self.checker.check(propositions)

        if not march_result["passed"]:
            logger.warning(f"MARCH 校验未通过: {march_result['feedback']}")
            return {
                "march_result": march_result,
                "monte_carlo_result": None,
                "final_decision": "REJECT",
                "routing": {
                    "action": "反馈修正",
                    "target": "智能体重生成",
                    "feedback": march_result["feedback"],
                },
            }

        # Step 2: 蒙特卡洛置信度检验
        mc_result = self.mc_validator.validate(decision, self.checker)

        if not mc_result["passed"]:
            logger.warning(
                f"蒙特卡洛置信度不足: {mc_result['confidence']} < {mc_result['threshold']}"
            )
            return {
                "march_result": march_result,
                "monte_carlo_result": mc_result,
                "final_decision": "BLOCK",
                "routing": {
                    "action": "高风险阻断",
                    "target": self._route_by_risk(decision),
                    "reason": f"置信度 {mc_result['confidence']} 低于阈值 {mc_result['threshold']}",
                },
            }

        # Step 3: 三维高风险阻断判断
        risk = self.risk_assessor.assess(decision)
        if risk.blocked:
            return {
                "march_result": march_result,
                "monte_carlo_result": mc_result,
                "final_decision": "MANUAL_REVIEW",
                "routing": {
                    "action": "转人工审核",
                    "target": self._route_by_risk(decision),
                    "reason": f"三维风险评估阻断: {risk.reason}",
                },
            }

        return {
            "march_result": march_result,
            "monte_carlo_result": mc_result,
            "final_decision": "APPROVE",
            "routing": {
                "action": "执行",
                "target": "预警推送系统",
            },
        }

    def _route_by_risk(self, decision: Dict[str, Any]) -> str:
        """根据风险等级路由到对应审核部门"""
        level = decision.get("predicted_level", "四级")
        routing_map = {
            "一级": "属地应急管理局 + 省级监管部门",
            "二级": "属地应急管理局 + 行业主管部门",
            "三级": "区县级安监部门",
            "四级": "企业安全管理部门",
            "红": "属地应急管理局 + 省级监管部门",
            "橙": "属地应急管理局 + 行业主管部门",
            "黄": "区县级安监部门",
            "蓝": "企业安全管理部门",
        }
        return routing_map.get(level, "企业安全管理部门")
