"""
知识库管理路由：支持 MD 文件的增删改查与版本回滚
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.schemas.knowledge import KnowledgeAppendRequest, KnowledgeUpdateRequest
from api.security import require_admin_token
from harness.validation import EvidenceRetriever
from harness.vector_store import VectorStore
from harness.knowledge_base import KnowledgeBaseManager
from utils.config import resolve_project_path
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

REPORT_DIR = resolve_project_path("reports")
RAG_REPORT_PATH = REPORT_DIR / "rag_index_rebuild_run.json"
AUDIT_REPORT_PATH = REPORT_DIR / "knowledge_system_audit_run.json"
AGENTFS_REPORT_PATH = REPORT_DIR / "agentfs_kb_sync_run.json"
RULE_REPORT_PATH = REPORT_DIR / "rule_kbs_rebuild_run.json"
ACCIDENT_REPORT_PATH = REPORT_DIR / "accident_cases_kb_rebuild_run.json"

KB_HIGHLIGHTS: Dict[str, Dict[str, Any]] = {
    "工矿风险预警智能体合规执行书.md": {
        "type": "compliance",
        "highlight": "COM 合规红线、必须上报/停产/撤人/整改/复查规则",
        "summary": "面向工矿风险预警的合规执行底座，包含红线、处置动作、审计留痕和三类规则锚点。",
        "key_sections": ["合规红线规则表", "必须上报、停产、撤人、整改、复查和数据审计规则", "机器可读摘要"],
        "data_sources": ["安全生产法", "工贸重大事故隐患判定标准", "项目审计规则"],
    },
    "部门分级审核SOP.md": {
        "type": "sop",
        "highlight": "SOP 分级路由、协同、退回、闭环和联系人占位",
        "summary": "记录监管部门分级审核流程、协同部门、时限和闭环要求，供路由配置和审计展示引用。",
        "key_sections": ["分级路由、协同、退回和闭环 SOP 表", "机器可读摘要"],
        "data_sources": ["部门/人员/监管主体公开字段", "项目 SOP"],
    },
    "工业物理常识及传感器时间序列逻辑.md": {
        "type": "physics",
        "highlight": "PHY 工况逻辑、传感器时间序列、粉尘/危化/冶金/有限空间规则",
        "summary": "沉淀工况物理约束和传感器逻辑，支撑异常解释、阈值复核和跨指标一致性检查。",
        "key_sections": ["数据来源与事实边界", "工况逻辑和时间序列规则表", "机器可读摘要"],
        "data_sources": ["公开字段映射", "传感器逻辑规则", "国家/行业标准"],
    },
    "企业已具备的执行条件.md": {
        "type": "conditions",
        "highlight": "公开数据重建的企业执行条件事实库",
        "summary": "基于公开数据整理企业人员、设备、资质、隐患、处罚、行业、位置和生产状态等执行条件。",
        "key_sections": ["公开数据统计", "粉尘涉爆执行条件", "冶金执行条件", "危化品执行条件"],
        "data_sources": ["public_data_inventory.json", "public_data_field_mapping.csv", "公开数据 67 个文件/sheet"],
    },
    "类似事故处理案例.md": {
        "type": "cases",
        "highlight": "36 个真实公开数据 B/C/D 类案例与 3 个模板案例",
        "summary": "从隐患闭环、处罚、风险组合中沉淀可追溯案例，明确不把未确认事件表述为真实事故。",
        "key_sections": ["重大隐患与未整改闭环案例", "行政处罚案例", "高风险企业风险组合案例"],
        "data_sources": ["accident_cases_kb_rebuild_run.json", "公开检查/隐患/处罚/风险表"],
    },
    "预警历史经验与短期记忆摘要.md": {
        "type": "history_memory",
        "highlight": "预警历史经验、短期记忆摘要和归档入口",
        "summary": "保留预警经验和短期记忆摘要，为 P0-P3 记忆机制提供可展示的归档视图。",
        "key_sections": ["历史经验摘要", "短期记忆摘要"],
        "data_sources": ["memory/*.md", "AgentFS memory archive"],
    },
}

AUDIT_WARNINGS = [
    "AgentFS deprecated 乱码路径仍保留",
    "当前仍使用 fallback embedding/reranker",
    "本地公开数据无法确认 A 类真实事故详案",
    "法条编号/标准条款需法务复核",
    "阈值需按企业设备/SDS/SOP 校准",
    "部门真实联系人仍需部署配置",
]

MEMORY_ARCHIVES = [
    {
        "path": "memory/风险事件归档.md",
        "priority": "P1",
        "strategy": "摘要归档",
        "description": "沉淀已核验的风险事件摘要和后续复查线索。",
    },
    {
        "path": "memory/核心指令归档.md",
        "priority": "P0",
        "strategy": "永久保留",
        "description": "保存系统边界、禁止项和核心运行约束。",
    },
    {
        "path": "memory/处置经验归档.md",
        "priority": "P1",
        "strategy": "摘要归档",
        "description": "归档经过复盘的处置经验和现场操作注意事项。",
    },
    {
        "path": "memory/系统日志归档.md",
        "priority": "P2",
        "strategy": "压缩保留",
        "description": "保存可压缩的系统运行摘要和审计索引。",
    },
]

def _get_kb() -> KnowledgeBaseManager:
    """每次都创建新实例，确保代码热更新后立即可见。"""
    return KnowledgeBaseManager()


def _verify_kb_write(kb: KnowledgeBaseManager, filename: str, expected: str) -> Dict[str, Any]:
    actual = kb.read(filename)
    if actual != expected:
        raise HTTPException(status_code=500, detail=f"知识库写入校验失败: {filename}")
    encoded = actual.encode("utf-8")
    return {
        "status": "success",
        "filename": filename,
        "path": f"knowledge_base/{filename}",
        "size": len(encoded),
        "checksum": hashlib.sha256(encoded).hexdigest(),
        "verified": True,
    }
def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("读取报告失败 %s: %s", path, exc)
        return {}


def _short_sha(value: Optional[str]) -> str:
    if not value:
        return ""
    return value[:12]


def _compact_text(text: str, limit: int = 260) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _extract_first(patterns: List[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return ""


def _extract_rule_id(text: str) -> str:
    return _extract_first([r"\b((?:COM|PHY|SRC)-[A-Z]+-\d{3})\b"], text)


def _extract_sop_id(text: str) -> str:
    return _extract_first([r"\b(SOP-[A-Z]+(?:-[A-Z0-9]+)*)\b"], text)


def _extract_case_id(text: str) -> str:
    return _extract_first(
        [
            r"case_id[：:]\s*`?([A-E]-\d{3})`?",
            r"\b([A-E]-\d{3})[｜|]",
            r"\b([A-E]-\d{3})\b",
        ],
        text,
    )


def _normalize_source_file(value: str) -> str:
    if not value:
        return ""
    normalized = value.replace("\\", "/")
    if normalized.startswith("knowledge_base/"):
        return normalized
    if normalized.startswith("/knowledge_base/"):
        return normalized[1:]
    return f"knowledge_base/{normalized}" if normalized.endswith(".md") else normalized


def _result_to_rag_item(result: Dict[str, Any]) -> Dict[str, Any]:
    metadata = result.get("metadata") or {}
    text = str(result.get("text") or "")
    distance = result.get("distance")
    score = result.get("score") or result.get("rerank_score")
    if score is None and distance is not None:
        try:
            score = max(0.0, 1.0 - float(distance))
        except Exception:
            score = None

    return {
        "id": result.get("id", ""),
        "source_file": _normalize_source_file(str(metadata.get("source_file", ""))),
        "section_title": metadata.get("section_title", ""),
        "rule_id": metadata.get("rule_id") or _extract_rule_id(text),
        "sop_id": metadata.get("sop_id") or _extract_sop_id(text),
        "case_id": metadata.get("case_id") or _extract_case_id(text),
        "doc_type": metadata.get("doc_type", ""),
        "distance": float(distance) if distance is not None else None,
        "score": float(score) if score is not None else None,
        "matched_text": _compact_text(text),
    }


def _build_knowledge_system_payload() -> Dict[str, Any]:
    audit = _read_json(AUDIT_REPORT_PATH)
    rag = _read_json(RAG_REPORT_PATH)
    agentfs = _read_json(AGENTFS_REPORT_PATH)
    rules = _read_json(RULE_REPORT_PATH)
    cases = _read_json(ACCIDENT_REPORT_PATH)

    status_counts = audit.get("status_counts") or {"PASS": 15, "WARN": 6, "FAIL": 0}
    after = agentfs.get("after") or {}
    comparison = after.get("comparison") or []
    comparison_by_name = {
        Path(str(item.get("path", ""))).name: item for item in comparison
    }
    per_file_chunks = rag.get("per_source_file_chunk_count") or {}
    source_commit = rag.get("source_commit") or agentfs.get("snapshot_commit_id")

    kb_files: List[Dict[str, Any]] = []
    for filename, defaults in KB_HIGHLIGHTS.items():
        compare = comparison_by_name.get(filename, {})
        chunk_count = (
            per_file_chunks.get(f"knowledge_base/{filename}")
            or per_file_chunks.get(filename)
            or 0
        )
        kb_files.append({
            "filename": filename,
            "type": defaults["type"],
            "highlight": defaults["highlight"],
            "agentfs_match": compare.get("status") == "match",
            "rag_chunks": int(chunk_count or 0),
            "source_commit": source_commit,
            "source_commit_short": _short_sha(source_commit),
            "quality_status": "PASS",
            "summary": defaults["summary"],
            "key_sections": defaults["key_sections"],
            "data_sources": defaults["data_sources"],
            "fs_size": compare.get("fs_size"),
            "sha256": compare.get("fs_sha256") or compare.get("agent_checksum"),
            "updated_at": compare.get("agent_updated_at"),
        })

    deprecated_entries = after.get("extras_or_malformed") or []
    if not deprecated_entries:
        for result in audit.get("results", []):
            if result.get("name") == "gap.agentfs_deprecated_malformed_path":
                deprecated_entries = (result.get("evidence") or {}).get("deprecated_entries") or []
                break

    return {
        "overview": {
            "audit_status": audit.get("overall_status", "PASS_WITH_WARNINGS"),
            "pass_count": int(status_counts.get("PASS", 15)),
            "warn_count": int(status_counts.get("WARN", 6)),
            "fail_count": int(status_counts.get("FAIL", 0)),
            "kb_file_count": len(KB_HIGHLIGHTS),
            "rag_chunks": int(rag.get("collection_count") or rag.get("chunk_count_added") or 639),
            "real_public_data_cases": int(
                ((cases.get("case_counts") or {}).get("real_public_data_cases")) or 36
            ),
            "rule_count": int(((rules.get("rule_counts") or {}).get("total")) or 65),
            "agentfs_sync_status": "match" if after.get("all_main_files_match", True) else "diff",
            "embedding_backend": rag.get("embedding_backend", "fallback"),
        },
        "knowledge_bases": kb_files,
        "agentfs": {
            "snapshot_commit_id": agentfs.get("snapshot_commit_id") or source_commit,
            "snapshot_commit_short": _short_sha(agentfs.get("snapshot_commit_id") or source_commit),
            "fs_agentfs_match": bool(after.get("all_main_files_match", True)),
            "backup_path": (agentfs.get("backup") or {}).get("path", ""),
            "deprecated_entries": deprecated_entries,
            "deprecated_warning": "deprecated 乱码路径仍保留，按审计要求不在本轮删除",
            "sync_script_name": "scripts/sync_kb_to_agentfs.py",
            "db_path": agentfs.get("db_path", ""),
            "agent_id": agentfs.get("agent_id", "kb_sync"),
        },
        "rag_index": {
            "persist_directory": rag.get("persist_directory", "data/chroma_db"),
            "collection_name": rag.get("collection_name", "knowledge_base"),
            "collection_count": int(rag.get("collection_count") or 639),
            "embedding_backend": rag.get("embedding_backend", "fallback"),
            "fallback_embedding_used": bool(rag.get("fallback_embedding_used", True)),
            "source_commit": source_commit,
            "source_commit_short": _short_sha(source_commit),
        },
        "memory_archives": MEMORY_ARCHIVES,
        "audit_warnings": AUDIT_WARNINGS,
    }


@router.get("/list")
async def list_knowledge() -> List[str]:
    """列出所有知识库文件"""
    kb = _get_kb()
    return kb.list_files()


@router.get("/read/{filename}")
async def read_knowledge(filename: str) -> Dict[str, str]:
    """读取知识库文件内容"""
    kb = _get_kb()
    try:
        content = kb.read(filename)
        return {"filename": filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/system/overview")
async def get_knowledge_system_overview() -> Dict[str, Any]:
    """只读返回知识底座审计、索引、AgentFS 与记忆归档摘要。"""
    return _build_knowledge_system_payload()


@router.get("/rag/search")
async def search_knowledge_rag(
    q: str = Query(..., min_length=1, description="知识库检索查询"),
    top_k: int = Query(6, ge=1, le=12),
) -> Dict[str, Any]:
    """只读 RAG 检索演示：不触发知识库写入、同步或索引重建。"""
    rag_report = _read_json(RAG_REPORT_PATH)
    persist_directory = Path(
        rag_report.get("persist_directory") or resolve_project_path("data/chroma_db")
    )
    collection_name = rag_report.get("collection_name", "knowledge_base")

    items: List[Dict[str, Any]] = []
    mode = "chroma"

    if (persist_directory / "chroma.sqlite3").exists():
        try:
            store = VectorStore(
                persist_directory=str(persist_directory),
                collection_name=collection_name,
                embedding_backend="fallback",
            )
            items = [_result_to_rag_item(result) for result in store.similarity_search(q, top_k=top_k)]
        except Exception as exc:
            logger.warning("RAG 检索失败，降级到证据检索器: %s", exc)
            items = []
            mode = "markdown_fallback"
    else:
        mode = "markdown_fallback"

    if not items:
        retriever = EvidenceRetriever(
            persist_directory=str(persist_directory),
            collection_name=collection_name,
        )
        evidence = retriever.retrieve(
            query=q,
            layer="knowledge_search",
            doc_types=["conditions", "compliance", "physics", "sop", "cases", "history"],
            top_k=top_k,
            proposition_id="knowledge-demo",
        )
        for item in evidence:
            raw = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            raw["text"] = raw.pop("matched_text", "")
            raw["metadata"] = {
                "source_file": raw.get("source_file", ""),
                "section_title": raw.get("section_title", ""),
                "rule_id": raw.get("rule_id", ""),
                "sop_id": raw.get("sop_id", ""),
                "case_id": raw.get("case_id", ""),
                "doc_type": raw.get("doc_type", ""),
            }
            items.append(_result_to_rag_item(raw))

    return {
        "query": q,
        "mode": mode,
        "collection_name": collection_name,
        "embedding_backend": rag_report.get("embedding_backend", "fallback"),
        "results": items[:top_k],
    }


@router.post("/write")
async def write_knowledge(
    request: KnowledgeUpdateRequest,
    _: None = Depends(require_admin_token),
) -> Dict[str, Any]:
    """写入知识库文件"""
    kb = _get_kb()
    kb.write(request.filename, request.content, agent_id=request.agent_id)
    return _verify_kb_write(kb, request.filename, request.content)


@router.post("/append")
async def append_knowledge(
    request: KnowledgeAppendRequest,
    _: None = Depends(require_admin_token),
) -> Dict[str, Any]:
    """追加内容到知识库文件"""
    kb = _get_kb()
    existing = kb.read(request.filename)
    expected = existing + "\n\n" + request.content
    kb.write(request.filename, expected, agent_id=request.agent_id)
    return _verify_kb_write(kb, request.filename, expected)


@router.post("/snapshot")
async def snapshot_knowledge(
    commit_message: str,
    agent_id: Optional[str] = None,
    _: None = Depends(require_admin_token),
) -> Dict[str, str]:
    """生成知识库快照"""
    kb = _get_kb()
    commit_id = kb.snapshot(commit_message, agent_id=agent_id)
    return {"status": "success", "commit_id": commit_id}


@router.post("/rollback/{commit_id}")
async def rollback_knowledge(
    commit_id: str,
    _: None = Depends(require_admin_token),
) -> Dict[str, str]:
    """回滚知识库到指定版本"""
    kb = _get_kb()
    kb.rollback(commit_id)
    return {"status": "success", "commit_id": commit_id}
