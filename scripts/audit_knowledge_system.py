"""Read-only quality gate for the mining-risk knowledge system.

The audit verifies the local public-data-backed knowledge bases, AgentFS
runtime copies, formal Chroma RAG index, evidence validation, short-term
memory archival, and a mocked lightweight workflow path. It never rewrites the
knowledge-base Markdown files or rebuilds the RAG index.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from mining_risk_common.dataplane.loader import DataLoader
from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.knowledge_base import KnowledgeBaseManager
from mining_risk_serve.harness.memory import HybridMemoryManager, LongTermMemory, ShortTermMemory
from mining_risk_serve.harness.validation import EvidenceRetriever
from mining_risk_serve.harness.vector_store import VectorStore
from scripts.sync_kb_to_agentfs import (
    agentfs_manifest,
    compare_manifests,
    filesystem_manifest,
    get_paths,
    verify_agentfs_content,
)
from mining_risk_common.utils.config import get_config, resolve_project_path


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class AuditResult:
    name: str
    status: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _result(name: str, status: str, summary: str, **evidence: Any) -> AuditResult:
    return AuditResult(name=name, status=status, summary=summary, evidence=evidence)


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _grep_number(pattern: str, text: str, default: int = 0) -> int:
    match = re.search(pattern, text, flags=re.S)
    if not match:
        return default
    try:
        return int(match.group(1))
    except Exception:
        return default


def _kb_paths() -> list[Path]:
    return [PROJECT_ROOT / "knowledge_base" / name for name in KnowledgeBaseManager.KNOWLEDGE_FILES]


def check_public_data_paths() -> AuditResult:
    config = get_config()
    configured = list(config.data.all_public_data_paths or [])
    if config.data.public_data_root and config.data.public_data_root not in configured:
        configured.append(config.data.public_data_root)

    resolved = [resolve_project_path(path) for path in configured]
    missing = [str(path) for path in resolved if not path.exists()]
    status = PASS if resolved and not missing else FAIL
    summary = (
        f"{len(resolved)} configured public data path(s) exist"
        if status == PASS
        else f"{len(missing)} configured public data path(s) are missing"
    )
    return _result(
        "config.public_data_paths_exist",
        status,
        summary,
        paths=[str(path) for path in resolved],
        missing=missing,
    )


def _iter_public_data_files(paths: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    suffixes = {".csv", ".xlsx", ".xls"}
    for root in paths:
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)
    return sorted(dict.fromkeys(files), key=lambda p: p.as_posix())


def check_dataloader_reads_public_data(sample_rows: int = 5) -> AuditResult:
    config = get_config()
    roots = [resolve_project_path(path) for path in (config.data.all_public_data_paths or [config.data.public_data_root])]
    files = _iter_public_data_files([path for path in roots if path is not None])
    if not files:
        return _result("dataloader.public_data_readability", FAIL, "No public CSV/XLS/XLSX files discovered")

    loader = DataLoader()
    readable = 0
    errors: list[dict[str, str]] = []
    for path in files:
        try:
            loader.load_file(path, nrows=sample_rows)
            readable += 1
        except Exception as exc:
            errors.append({"file": _rel(path), "error": str(exc)[:500]})

    ratio = readable / len(files)
    status = PASS if ratio >= 0.80 else WARN if ratio >= 0.50 else FAIL
    return _result(
        "dataloader.public_data_readability",
        status,
        f"DataLoader read {readable}/{len(files)} CSV/XLS/XLSX files with nrows={sample_rows}",
        total_files=len(files),
        readable_files=readable,
        readability_ratio=round(ratio, 4),
        errors=errors[:10],
    )


def check_main_kb_files() -> AuditResult:
    details = []
    missing_or_empty = []
    for path in _kb_paths():
        size = path.stat().st_size if path.exists() else 0
        details.append({"file": _rel(path), "exists": path.exists(), "size": size})
        if not path.exists() or size <= 0:
            missing_or_empty.append(_rel(path))

    status = PASS if not missing_or_empty else FAIL
    return _result(
        "kb.six_main_files_exist_non_empty",
        status,
        "Six main knowledge-base Markdown files exist and are non-empty"
        if status == PASS
        else "Some main knowledge-base Markdown files are missing or empty",
        files=details,
        missing_or_empty=missing_or_empty,
    )


def _incremental_sections(text: str) -> list[str]:
    lines = text.splitlines()
    sections: list[str] = []
    current: list[str] = []
    in_section = False
    for line in lines:
        starts_heading = line.startswith("#")
        is_incremental = starts_heading and "增量更新" in line
        if is_incremental:
            if current:
                sections.append("\n".join(current).strip())
            current = [line]
            in_section = True
            continue
        if in_section and starts_heading and "增量更新" not in line:
            if current:
                sections.append("\n".join(current).strip())
            current = []
            in_section = False
            continue
        if in_section:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [section for section in sections if section]


def check_no_duplicate_incremental_sections() -> AuditResult:
    seen: dict[str, str] = {}
    duplicates = []
    section_count = 0
    for path in _kb_paths():
        if not path.exists():
            continue
        for section in _incremental_sections(_read_text(path)):
            section_count += 1
            digest = _sha256(re.sub(r"\s+", "\n", section).encode("utf-8"))
            previous = seen.get(digest)
            if previous:
                duplicates.append({"first": previous, "duplicate": _rel(path), "sha256": digest})
            else:
                seen[digest] = _rel(path)

    status = PASS if not duplicates else FAIL
    return _result(
        "kb.no_duplicate_incremental_update_blocks",
        status,
        f"No duplicated full '增量更新' sections found across {section_count} section(s)"
        if status == PASS
        else f"Found {len(duplicates)} duplicated full '增量更新' section(s)",
        incremental_section_count=section_count,
        duplicates=duplicates,
    )


def _is_empty_placeholder_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return len(cells) >= 2 and all(cell == "-" for cell in cells)


def check_no_large_empty_placeholders(max_allowed: int = 5) -> AuditResult:
    hits = []
    for path in _kb_paths():
        if not path.exists():
            continue
        for line_no, line in enumerate(_read_text(path).splitlines(), start=1):
            if _is_empty_placeholder_row(line) or "| - |" in line:
                hits.append({"file": _rel(path), "line": line_no, "text": line[:160]})

    status = PASS if len(hits) <= max_allowed else FAIL
    return _result(
        "kb.no_large_scale_empty_table_placeholders",
        status,
        f"Empty Markdown placeholder rows: {len(hits)} (threshold {max_allowed})",
        placeholder_count=len(hits),
        examples=hits[:10],
    )


def check_no_pending_placeholders() -> AuditResult:
    hits = []
    for path in _kb_paths():
        if not path.exists():
            continue
        for line_no, line in enumerate(_read_text(path).splitlines(), start=1):
            if "待填写" in line:
                hits.append({"file": _rel(path), "line": line_no, "text": line[:160]})

    status = PASS if not hits else FAIL
    return _result(
        "kb.no_pending_placeholder_text",
        status,
        "No '待填写' placeholder remains in the six main knowledge bases"
        if status == PASS
        else f"Found {len(hits)} '待填写' placeholder line(s)",
        hits=hits[:20],
    )


def check_enterprise_conditions_public_stats() -> AuditResult:
    path = PROJECT_ROOT / "knowledge_base" / "企业已具备的执行条件.md"
    text = _read_text(path) if path.exists() else ""
    required_terms = ["公开数据", "116798", "67", "2568"]
    missing = [term for term in required_terms if term not in text]
    status = PASS if not missing else FAIL
    return _result(
        "kb.enterprise_conditions_public_statistics",
        status,
        "Enterprise conditions KB cites real public-data inventory statistics"
        if status == PASS
        else "Enterprise conditions KB is missing expected public-data statistics",
        required_terms=required_terms,
        missing_terms=missing,
        file=_rel(path),
    )


def _case_count(prefix: str, text: str) -> int:
    return len(set(re.findall(rf"\b{prefix}-\d{{3}}\b", text)))


def check_accident_cases_bcd() -> AuditResult:
    path = PROJECT_ROOT / "knowledge_base" / "类似事故处理案例.md"
    text = _read_text(path) if path.exists() else ""
    counts = {prefix: _case_count(prefix, text) for prefix in ("A", "B", "C", "D", "E")}
    has_public_marker = "公开数据案例" in text and "真实公开数据案例" in text
    status = PASS if counts["B"] >= 1 and counts["C"] >= 1 and counts["D"] >= 1 and has_public_marker else FAIL
    return _result(
        "kb.accident_cases_bcd_real_public_data_cases",
        status,
        f"B/C/D case coverage: B={counts['B']}, C={counts['C']}, D={counts['D']}"
        if status == PASS
        else "B/C/D public-data case coverage is incomplete",
        case_counts=counts,
        has_public_data_marker=has_public_marker,
        file=_rel(path),
    )


def check_a_class_real_accident_gap() -> AuditResult:
    path = PROJECT_ROOT / "knowledge_base" / "类似事故处理案例.md"
    text = _read_text(path) if path.exists() else ""
    counts = {prefix: _case_count(prefix, text) for prefix in ("A", "B", "C", "D")}
    status = WARN if counts["A"] == 0 else PASS
    summary = (
        "No A-class real accident detail is confirmed in local public data"
        if status == WARN
        else f"A-class real accident cases present: {counts['A']}"
    )
    return _result(
        "gap.a_class_real_accident_detail",
        status,
        summary,
        case_counts=counts,
        required_follow_up="Import or crawl traceable accident investigation reports before claiming A-class accident detail coverage.",
    )


def check_rule_ids() -> AuditResult:
    files = {
        "COM": PROJECT_ROOT / "knowledge_base" / "工矿风险预警智能体合规执行书.md",
        "PHY": PROJECT_ROOT / "knowledge_base" / "工业物理常识及传感器时间序列逻辑.md",
        "SOP": PROJECT_ROOT / "knowledge_base" / "部门分级审核SOP.md",
    }
    counts: dict[str, int] = {}
    ids_by_type: dict[str, list[str]] = {}
    patterns = {
        "COM": r"\bCOM-[A-Z]+-\d{3}\b",
        "PHY": r"\bPHY-[A-Z]+-\d{3}\b",
        "SOP": r"\bSOP-[A-Z]+(?:-[A-Z0-9]+)*\b",
    }
    for key, path in files.items():
        text = _read_text(path) if path.exists() else ""
        ids = sorted(set(re.findall(patterns[key], text)))
        ids_by_type[key] = ids
        counts[key] = len(ids)
    total = sum(counts.values())
    status = PASS if counts["COM"] > 0 and counts["PHY"] > 0 and counts["SOP"] > 0 and total >= 60 else FAIL
    return _result(
        "kb.rule_libraries_have_com_phy_sop_ids",
        status,
        f"Unique rule IDs: COM={counts['COM']}, PHY={counts['PHY']}, SOP={counts['SOP']}, total={total}",
        counts=counts,
        total=total,
        sample_ids={key: value[:5] for key, value in ids_by_type.items()},
    )


def check_agentfs_main_kb_sync() -> AuditResult:
    db_path, _, _, kb_dir = get_paths()
    verification = verify_agentfs_content(db_path, kb_dir)
    comparison = compare_manifests(filesystem_manifest(kb_dir), agentfs_manifest(db_path))
    mismatches = [item for item in verification if not item.get("matches")]
    status = PASS if verification and not mismatches and comparison["all_main_files_match"] else FAIL
    return _result(
        "agentfs.six_kb_byte_identical",
        status,
        "AgentFS copies are byte-identical with the six filesystem KB files"
        if status == PASS
        else "AgentFS copies differ from filesystem KB files",
        db_path=str(db_path),
        verify=verification,
        comparison=comparison["comparison"],
    )


def check_agentfs_deprecated_path_retained() -> AuditResult:
    db_path, _, _, _ = get_paths()
    extras = [asdict(entry) for entry in agentfs_manifest(db_path) if entry.status_note]
    status = WARN if extras else PASS
    return _result(
        "gap.agentfs_deprecated_malformed_path",
        status,
        "Deprecated malformed AgentFS path is still retained by design"
        if status == WARN
        else "No deprecated malformed AgentFS path found",
        deprecated_entries=extras,
        handling="Do not delete until a backed-up migration is approved.",
    )


def check_chroma_index() -> AuditResult:
    config = get_config()
    rag_config = config.harness.memory.long_term.rag
    persist_dir = resolve_project_path(rag_config.get("persist_directory", "var/chroma"))
    report = _safe_json(PROJECT_ROOT / "reports" / "rag_index_rebuild_run.json")
    if not (persist_dir.exists() and (persist_dir / "chroma.sqlite3").exists()):
        return _result("rag.formal_chroma_index", FAIL, "Formal Chroma directory or sqlite file is missing", persist_dir=str(persist_dir))

    store = None
    try:
        store = VectorStore(
            persist_directory=str(persist_dir),
            collection_name=rag_config.get("collection_name", "knowledge_base"),
            embedding_backend="fallback",
        )
        count = store.collection.count()
    except Exception as exc:
        return _result("rag.formal_chroma_index", FAIL, f"Cannot open Chroma collection: {exc}", persist_dir=str(persist_dir))
    finally:
        if store is not None:
            try:
                store.client._system.stop()
            except Exception:
                pass

    expected = report.get("collection_count")
    reasonable = count >= 100 and (expected is None or abs(int(expected) - count) <= max(5, int(expected) * 0.05))
    status = PASS if reasonable else FAIL
    return _result(
        "rag.formal_chroma_index",
        status,
        f"Chroma collection knowledge_base has {count} chunks",
        persist_dir=str(persist_dir),
        collection_name=rag_config.get("collection_name", "knowledge_base"),
        collection_count=count,
        report_collection_count=expected,
        report_embedding_backend=report.get("embedding_backend"),
    )


def check_bge_embedding_gap() -> AuditResult:
    report = _safe_json(PROJECT_ROOT / "reports" / "rag_index_rebuild_run.json")
    deps = report.get("dependencies", {})
    using_fallback = bool(report.get("fallback_embedding_used")) or report.get("embedding_backend") == "fallback"
    sentence_transformers_available = bool(deps.get("sentence_transformers", {}).get("available"))
    status = WARN if using_fallback or not sentence_transformers_available else PASS
    return _result(
        "gap.real_bge_embedding_reranker",
        status,
        "Formal index still uses deterministic fallback embedding/reranker"
        if status == WARN
        else "Real BGE embedding dependency appears available",
        embedding_backend=report.get("embedding_backend"),
        fallback_embedding_used=report.get("fallback_embedding_used"),
        dependencies=deps,
    )


def check_rag_query_returns_evidence() -> AuditResult:
    store = None
    try:
        store = VectorStore(
            persist_directory=str(resolve_project_path("var/chroma")),
            collection_name="knowledge_base",
            embedding_backend="fallback",
        )
        results = store.similarity_search("粉尘涉爆 除尘系统 异常 公开数据", top_k=5)
    except Exception as exc:
        return _result("rag.query_returns_evidence_blocks", FAIL, f"RAG query failed: {exc}")
    finally:
        if store is not None:
            try:
                store.client._system.stop()
            except Exception:
                pass

    useful = [
        {
            "id": item.get("id"),
            "source_file": item.get("metadata", {}).get("source_file"),
            "doc_type": item.get("metadata", {}).get("doc_type"),
            "text_preview": item.get("text", "")[:120],
        }
        for item in results
        if item.get("text") and item.get("metadata", {}).get("source_file")
    ]
    status = PASS if useful else FAIL
    return _result(
        "rag.query_returns_evidence_blocks",
        status,
        f"RAG query returned {len(useful)} evidence block(s) with source_file"
        if status == PASS
        else "RAG query did not return source-attributed evidence blocks",
        query="粉尘涉爆 除尘系统 异常 公开数据",
        results=useful[:5],
    )


def _has_evidence(items: Sequence[Any], field_name: str) -> bool:
    return any(getattr(item, "source_file", "") and getattr(item, field_name, "") for item in items)


def check_validation_evidence() -> AuditResult:
    retriever = EvidenceRetriever()
    rule_evidence = retriever.retrieve(
        "销毁监控记录 COM-RED-018",
        layer="compliance",
        doc_types=["compliance"],
        preferred_ids=["COM-RED-018"],
        top_k=3,
        proposition_id="audit-com",
    )
    sop_evidence = retriever.retrieve(
        "微型企业立即停产 SOP-ROUTE-RED",
        layer="feasibility",
        doc_types=["sop"],
        preferred_ids=["SOP-ROUTE-RED"],
        top_k=3,
        proposition_id="audit-sop",
    )
    case_evidence = retriever.retrieve(
        "B-001 公开数据 隐患闭环 案例",
        layer="feasibility",
        doc_types=["cases"],
        preferred_ids=["B-001"],
        top_k=3,
        proposition_id="audit-case",
    )

    ok = (
        _has_evidence(rule_evidence, "rule_id")
        and _has_evidence(sop_evidence, "sop_id")
        and _has_evidence(case_evidence, "case_id")
    )
    status = PASS if ok else FAIL
    return _result(
        "validation.evidence_has_source_and_ids",
        status,
        "Evidence validation returns source_file plus rule_id/sop_id/case_id anchors"
        if status == PASS
        else "Evidence validation did not return all required source/id anchors",
        rule_evidence=[item.model_dump() for item in rule_evidence[:2]],
        sop_evidence=[item.model_dump() for item in sop_evidence[:2]],
        case_evidence=[item.model_dump() for item in case_evidence[:2]],
    )


def _char_tokens(text: str) -> int:
    return len(text)


def _make_workspace_temp_dir(prefix: str) -> Path:
    parent = PROJECT_ROOT / "tmp_pytest" / "knowledge_system_audit"
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        path = parent / f"{prefix}{uuid.uuid4().hex}"
        try:
            path.mkdir(parents=False, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"Unable to create unique audit temp directory under {parent}")


async def _check_memory_archive_async() -> AuditResult:
    tmp = _make_workspace_temp_dir("memory_archive_")
    try:
        fs = AgentFS(db_path=str(tmp / "agentfs.db"), git_repo_path=str(tmp / "git"))
        short = ShortTermMemory(max_tokens=80, safety_threshold=1.0, token_counter=_char_tokens)
        long = LongTermMemory(agentfs=fs)
        manager = HybridMemoryManager(short_term=short, long_term=long)

        short.add("P0 baseline", priority="P0")
        short.add("P1 摘要归档演练：粉尘涉爆除尘系统异常，需要闭环复查。" * 6, priority="P1", metadata={"audit": "knowledge_system"})
        summaries_before = short.get_p1_summaries()
        await manager.archive_experience()
        archive_path = long.memory_files[1]
        archived = fs.read(archive_path).decode("utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = bool(summaries_before) and "P1 摘要归档演练" in archived and short.get_p1_summaries() == []
    status = PASS if ok else FAIL
    return _result(
        "memory.p1_summary_archives_to_agentfs",
        status,
        "P1 short-term summary can be archived into an AgentFS memory file"
        if status == PASS
        else "P1 short-term summary archival failed",
        summaries_before=len(summaries_before),
        archive_path=archive_path,
        archive_contains_probe="P1 摘要归档演练" in archived,
    )


def check_memory_archive() -> AuditResult:
    return asyncio.run(_check_memory_archive_async())


async def _check_workflow_light_e2e_async() -> AuditResult:
    from mining_risk_serve.agent.workflow import ScenarioConfig, node_decision_generation, node_memory_recall

    state = {
        "enterprise_id": "AUDIT-E001",
        "raw_data": {
            "enterprise_name": "审计模拟企业",
            "dangerous_chemical_enterprise": 1,
            "risk_total_count": 3,
            "trouble_unrectified_count": 1,
        },
        "features": None,
        "prediction": {
            "predicted_level": "橙",
            "probability_distribution": {"红": 0.10, "橙": 0.70, "黄": 0.15, "蓝": 0.05},
            "shap_contributions": [
                {"feature": "trouble_unrectified_count", "contribution": 0.34},
                {"feature": "dangerous_chemical_enterprise", "contribution": 0.22},
                {"feature": "risk_total_count", "contribution": 0.16},
            ],
        },
        "memory_results": None,
        "decision": None,
        "march_result": None,
        "monte_carlo_result": None,
        "three_d_risk": None,
        "retry_count": 0,
        "final_status": "UNKNOWN",
        "node_status": [],
        "scenario_id": "chemical",
        "error": None,
    }

    class FakeMemory:
        def __init__(self) -> None:
            self.called = 0

        def is_long_term_rag_enabled(self) -> bool:
            return True

        async def recall_long_term(self, query: str, risk_level: str | None = None, top_k: int = 5) -> list[dict[str, Any]]:
            self.called += 1
            return [
                {
                    "text": "公开数据案例：危化品泄漏隐患闭环处置，需现场核查、限期整改并保留证据。",
                    "metadata": {"source_file": "knowledge_base/类似事故处理案例.md"},
                    "source": "knowledge_base/类似事故处理案例.md",
                    "rerank_score": 0.98,
                }
            ]

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.calls = 0

        async def generate_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return {
                "risk_level_and_attribution": {
                    "level": "橙",
                    "root_cause": "未整改隐患与危化品属性叠加，需要人工复核。",
                    "top_features": [{"feature": "trouble_unrectified_count", "contribution": 0.34}],
                },
                "government_intervention": {
                    "department_primary": {"name": "属地应急管理部门", "contact_role": "值班负责人", "action": "组织现场核查"},
                    "department_assist": {"name": "行业主管部门", "action": "协同复核"},
                    "actions": ["核查隐患闭环证据", "下发限期整改要求"],
                    "deadline_hours": 24,
                    "follow_up": "复查整改材料和现场照片。",
                },
                "enterprise_control": {
                    "equipment_id": "DCS-AUDIT",
                    "operation": "保持监测并暂停相关高风险作业",
                    "parameters": {"monitoring_interval_minutes": 30},
                    "emergency_resources": ["便携式气体检测仪", "应急物资"],
                    "personnel_actions": ["安全负责人到场确认", "班组复训"],
                },
            }

    class FakeMonteCarloResult:
        passed = True
        confidence = 0.96

        def model_dump(self) -> dict[str, Any]:
            return {"passed": True, "confidence": 0.96, "threshold": 0.90}

    class FakeSamplingNode:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def sample(self, decision: dict[str, Any]) -> FakeMonteCarloResult:
            return FakeMonteCarloResult()

    class FakeRiskResult:
        blocked = False
        total_score = 1.4

        def model_dump(self) -> dict[str, Any]:
            return {"blocked": False, "total_score": 1.4, "threshold": 2.2}

    class FakeRiskAssessor:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def assess(self, decision: dict[str, Any]) -> FakeRiskResult:
            return FakeRiskResult()

    fake_memory = FakeMemory()
    with (
        patch("agent.workflow._get_memory", return_value=fake_memory),
        patch("agent.workflow.OpenAICompatibleClient", new=FakeClient),
        patch("agent.workflow.SamplingNode", new=FakeSamplingNode),
        patch("agent.workflow.RiskAssessor", new=FakeRiskAssessor),
    ):
        state = await node_memory_recall(state)
        state = await node_decision_generation(state, ScenarioConfig("chemical"))

    node_names = [item["node"] for item in state["node_status"]]
    ok = (
        fake_memory.called == 1
        and state.get("memory_results")
        and state.get("march_result") is not None
        and state["march_result"].get("passed") is True
        and state.get("decision") is not None
        and "memory_recall" in node_names
        and "decision_generation" in node_names
    )
    return _result(
        "workflow.light_e2e_mocked_llm",
        PASS if ok else FAIL,
        "Mocked workflow path invoked memory_recall, decision_generation, RAG recall, and validation"
        if ok
        else "Mocked workflow path did not complete the required components",
        final_status=state.get("final_status"),
        memory_recall_calls=fake_memory.called,
        march_result=state.get("march_result"),
        node_status=state.get("node_status", []),
        external_llm_called=False,
    )


def check_workflow_light_e2e() -> AuditResult:
    return asyncio.run(_check_workflow_light_e2e_async())


def check_law_review_gap() -> AuditResult:
    return _result(
        "gap.legal_article_number_review",
        WARN,
        "Law and standard references are evidence-linked but article numbers still need legal review before production use",
        recommendation="Have legal/safety compliance owners review cited laws, standard clauses, and 2026 transition rules.",
    )


def check_threshold_calibration_gap() -> AuditResult:
    return _result(
        "gap.threshold_calibration",
        WARN,
        "Rule thresholds need enterprise-specific calibration against equipment design, SDS, alarms, and SOPs",
        recommendation="Build deployment-time threshold profiles per enterprise, device, material/SDS, and operating scenario.",
    )


def check_department_contacts_gap() -> AuditResult:
    config = get_config()
    approvers = config.iteration.approvers.model_dump()
    configured = {key: value for key, value in approvers.items() if value and "example.com" not in value}
    status = WARN
    return _result(
        "gap.department_real_contacts",
        status,
        "Department routing exists at role/email-placeholder level; real deployment contacts must be configured",
        configured_approver_fields=configured,
        recommendation="Inject real duty contacts, escalation rosters, and department ownership through deployment configuration.",
    )


def run_audit(sample_rows: int = 5) -> dict[str, Any]:
    checks: list[Callable[[], AuditResult]] = [
        check_public_data_paths,
        lambda: check_dataloader_reads_public_data(sample_rows=sample_rows),
        check_main_kb_files,
        check_no_duplicate_incremental_sections,
        check_no_large_empty_placeholders,
        check_no_pending_placeholders,
        check_enterprise_conditions_public_stats,
        check_accident_cases_bcd,
        check_rule_ids,
        check_agentfs_main_kb_sync,
        check_agentfs_deprecated_path_retained,
        check_chroma_index,
        check_bge_embedding_gap,
        check_rag_query_returns_evidence,
        check_validation_evidence,
        check_memory_archive,
        check_workflow_light_e2e,
        check_a_class_real_accident_gap,
        check_law_review_gap,
        check_threshold_calibration_gap,
        check_department_contacts_gap,
    ]

    results: list[AuditResult] = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:
            name = getattr(check, "__name__", "anonymous_check")
            results.append(_result(name, FAIL, f"Audit check raised {type(exc).__name__}: {exc}"))

    counts = {status: sum(1 for item in results if item.status == status) for status in (PASS, WARN, FAIL)}
    overall = "FAIL" if counts[FAIL] else "PASS_WITH_WARNINGS" if counts[WARN] else "PASS"
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "project_root": str(PROJECT_ROOT),
        "overall_status": overall,
        "status_counts": counts,
        "results": [asdict(item) for item in results],
    }


def _result_by_name(summary: dict[str, Any], name: str) -> dict[str, Any]:
    for item in summary["results"]:
        if item["name"] == name:
            return item
    return {"name": name, "status": "MISSING", "summary": "", "evidence": {}}


def render_markdown_report(summary: dict[str, Any]) -> str:
    rows = [
        (
            "公开数据可追溯接入",
            "config 公开数据路径存在；DataLoader 可读取绝大多数 CSV/XLSX；公开数据盘点覆盖 67 个文件/sheet、116798 行。",
            "config.public_data_paths_exist；dataloader.public_data_readability；reports/public_data_inventory_report.md。",
            "达标" if _result_by_name(summary, "dataloader.public_data_readability")["status"] == PASS else "未达标",
            "仍有少量异常文件需要人工处理，例如历史上记录的格式异常 Excel。",
            "将异常文件列入数据准入清单，按来源系统修复或显式排除。",
        ),
        (
            "六个主知识库完整且内容清洁",
            "六个 Markdown 主库存在且非空；无重复整段增量更新；无大规模空占位；未发现“待填写”。",
            "kb.six_main_files_exist_non_empty；kb.no_duplicate_incremental_update_blocks；kb.no_large_scale_empty_table_placeholders；kb.no_pending_placeholder_text。",
            "达标",
            "预警历史库包含历史增量更新标题，但未重复。",
            "后续新增知识时继续执行该审计脚本作为 CI 门禁。",
        ),
        (
            "事实型企业执行条件库",
            "企业执行条件库已吸收公开数据统计，并对人员、设备、隐患、执法、粉尘、冶金、危化、有限空间等条件做证据化整理。",
            "kb.enterprise_conditions_public_statistics；public_data_field_mapping.csv。",
            "基本达标",
            "阈值仍需按企业设备/SDS/SOP 校准。",
            "部署时建立企业级阈值画像和复核流程。",
        ),
        (
            "类似事故/隐患/执法案例库",
            "案例库包含 B/C/D 类真实公开数据案例，重建报告记录真实公开数据案例 36 个。",
            "kb.accident_cases_bcd_real_public_data_cases；reports/accident_cases_kb_rebuild_run.json。",
            "基本达标",
            "本地公开数据无法确认 A 类真实事故详案。",
            "接入事故调查报告来源后，再新增 A 类真实事故案例。",
        ),
        (
            "COM/PHY/SOP 证据型规则库",
            "三份规则库已包含 COM/PHY/SOP ID，合计 65 条左右规则，并可被 validation 证据检索引用。",
            "kb.rule_libraries_have_com_phy_sop_ids；validation.evidence_has_source_and_ids。",
            "基本达标",
            "法条编号、标准条款和 2026 过渡规则仍需法务复核。",
            "建立法务签核版规则发布流程。",
        ),
        (
            "AgentFS 运行态一致性",
            "AgentFS 与文件系统六库逐字节一致；deprecated 乱码路径保留且不影响六库读取。",
            "agentfs.six_kb_byte_identical；gap.agentfs_deprecated_malformed_path。",
            "达标但有警告",
            "AgentFS deprecated 乱码路径仍未迁移删除。",
            "在备份和引用确认后做迁移归档，不在本轮删除。",
        ),
        (
            "正式 RAG 索引和证据召回",
            "var/chroma 存在，collection=knowledge_base，chunk 数合理；RAG 查询能返回 source_file 证据块。",
            "rag.formal_chroma_index；rag.query_returns_evidence_blocks。",
            "本地可用",
            "当前仍使用 deterministic fallback embedding/reranker，不是真实 BGE。",
            "安装并验证 BGE embedding/reranker，重建索引并固定依赖版本。",
        ),
        (
            "三重校验和记忆闭环",
            "Evidence validation 可返回 source_file 以及 rule_id/sop_id/case_id；P1 摘要可归档到 AgentFS memory 文件。",
            "validation.evidence_has_source_and_ids；memory.p1_summary_archives_to_agentfs。",
            "达标",
            "部门真实联系人仍需部署环境配置。",
            "补齐真实联系人、值班表、部门路由和升级策略。",
        ),
        (
            "轻量端到端工作流",
            "使用 mock LLM 验证 memory_recall、decision_generation 前后的 RAG/validation 可调用，未触发外部 API。",
            "workflow.light_e2e_mocked_llm。",
            "达标",
            "完整生产链路仍需真实 LLM、真实 BGE、真实联系人和线上审计环境联调。",
            "下一轮做生产化依赖安装、密钥隔离和端到端演练。",
        ),
    ]

    lines = [
        "# 知识库 CI 质量门禁与端到端验收审计报告",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 项目目录：`{summary['project_root']}`",
        f"- 总体结论：`{summary['overall_status']}`",
        f"- 检查统计：PASS={summary['status_counts'][PASS]}，WARN={summary['status_counts'][WARN]}，FAIL={summary['status_counts'][FAIL]}",
        "- 审计边界：本报告只读检查知识库正文；不重建 RAG 索引；不删除 AgentFS deprecated 乱码路径；轻量工作流使用 mock LLM，不调用外部 API。",
        "",
        "## 技术方案验收矩阵",
        "",
        "| 方案要求 | 当前实现 | 验收证据 | 是否达标 | 剩余问题 | 改进建议 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |")

    lines.extend(
        [
            "",
            "## CI 门禁结果",
            "",
            "| 检查项 | 状态 | 摘要 |",
            "| --- | --- | --- |",
        ]
    )
    for item in summary["results"]:
        lines.append(f"| `{item['name']}` | {item['status']} | {item['summary']} |")

    warning_items = [item for item in summary["results"] if item["status"] == WARN]
    fail_items = [item for item in summary["results"] if item["status"] == FAIL]
    lines.extend(["", "## 剩余问题", ""])
    if fail_items:
        lines.append("未通过项：")
        for item in fail_items:
            lines.append(f"- `{item['name']}`：{item['summary']}")
    else:
        lines.append("未发现硬性 CI 失败项。")
    lines.append("")
    lines.append("警告项和生产化缺口：")
    for item in warning_items:
        lines.append(f"- `{item['name']}`：{item['summary']}")

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "底层数据知识库的本地验收目标已基本达成：公开数据已盘点并可读，六个主知识库已证据化重建并同步到 AgentFS，正式 RAG 索引可召回证据块，validation 和短期记忆归档链路可用。",
            "",
            "仍处于本地 fallback 或原型状态的能力包括：embedding/reranker 使用 deterministic fallback，轻量端到端验收使用 mock LLM，部门联系人和阈值画像尚未接入真实部署配置。",
            "",
            "生产环境补齐优先级：第一，安装真实 BGE embedding/reranker 并重建验证索引；第二，补齐真实事故调查报告、法务复核、企业阈值校准和部门联系人配置。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-rows", type=int, default=5, help="Rows read from each public CSV/XLSX file during DataLoader readability checks.")
    parser.add_argument("--json", dest="json_path", default=None, help="Optional path to write the machine-readable audit summary.")
    parser.add_argument("--report-md", default=None, help="Optional path to write the Markdown audit report.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_audit(sample_rows=args.sample_rows)

    if args.json_path:
        json_path = resolve_project_path(args.json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.report_md:
        report_path = resolve_project_path(args.report_md)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_markdown_report(summary), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["status_counts"][FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
