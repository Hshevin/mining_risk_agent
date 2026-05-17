"""
轻量级记忆统计、筛选与导出数据准备。

该模块刻意不触发 RAG 索引重建，也不通过 AgentFS.read 读取内容，
避免统计请求污染 READ 审计日志。需要文件内容时直接只读查询 SQLite。
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mining_risk_serve.harness.agentfs import AgentFS
from mining_risk_serve.harness.memory import LongTermMemory, ShortTermMemory
from mining_risk_common.utils.config import get_config, resolve_project_path
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


LONG_TERM_ARCHIVES = [
    ("memory/核心指令归档.md", "P0", "核心指令"),
    ("memory/风险事件归档.md", "P1", "风险事件"),
    ("memory/处置经验归档.md", "P1", "处置经验"),
    ("memory/系统日志归档.md", "P2", "系统日志"),
]

WARNING_FILES = [
    ("knowledge_base/预警历史经验与短期记忆摘要.md", "预警历史经验"),
    ("knowledge_base/类似事故处理案例.md", "类似事故案例"),
]

PRIORITIES = ["P0", "P1", "P2", "P3"]

RISK_TYPE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "粉尘涉爆": ("粉尘", "涉爆", "除尘", "可燃性粉尘"),
    "危化品": ("危化", "危险化学", "储罐", "泄漏", "反应釜"),
    "冶金煤气": ("冶金", "煤气", "高炉", "转炉", "熔融"),
    "有限空间": ("有限空间", "受限空间", "中毒窒息", "缺氧"),
    "火灾爆炸": ("火灾", "爆炸", "燃爆", "瓦斯"),
    "设备失效": ("设备", "传感器", "报警", "联锁", "失效"),
}

RISK_LEVEL_KEYWORDS = ("红", "橙", "黄", "蓝", "A", "B", "C", "D", "高", "中", "低")


@dataclass
class MemoryStatsFilters:
    module: str = "all"
    priority: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    keyword: Optional[str] = None
    path: Optional[str] = None
    risk_level: Optional[str] = None
    risk_type: Optional[str] = None
    limit: int = 50
    offset: int = 0


def parse_time(value: Optional[str]) -> Optional[float]:
    """解析前端传入的 ISO/日期/时间戳。"""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def iso_from_timestamp(value: Optional[float]) -> str:
    if value is None:
        return ""
    try:
        return datetime.fromtimestamp(float(value)).isoformat(timespec="seconds")
    except Exception:
        return ""


def compact_text(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def normalize_agentfs_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/")
    return normalized if normalized.startswith("/") else f"/{normalized}"


def display_agentfs_path(path: str) -> str:
    return normalize_agentfs_path(path).lstrip("/")


def detect_risk_type(text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    metadata = metadata or {}
    for key in ("risk_type", "risk", "风险类型"):
        value = str(metadata.get(key) or "").strip()
        if value:
            for risk_type in RISK_TYPE_KEYWORDS:
                if risk_type in value:
                    return risk_type
            return value
    for risk_type, keywords in RISK_TYPE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return risk_type
    return "未标注"


def detect_risk_level(text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    metadata = metadata or {}
    for key in ("risk_level", "level", "risk", "风险等级"):
        value = str(metadata.get(key) or "").strip()
        if value:
            for level in RISK_LEVEL_KEYWORDS:
                if level in value:
                    return level
            return value
    for level in RISK_LEVEL_KEYWORDS:
        if re.search(rf"(风险等级|等级|level)[:：\s]*{re.escape(level)}", text):
            return level
    return ""


def detect_priority(text: str, default: str = "P2") -> str:
    match = re.search(r"\b(P[0-3])\b", text or "")
    return match.group(1) if match else default


def try_parse_metadata(text: str) -> Dict[str, Any]:
    patterns = [
        r"\*\*元数据\*\*[:：]\s*(\{.*?\})(?:\n|$)",
        r"metadata[:：]\s*(\{.*?\})(?:\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.S)
        if not match:
            continue
        try:
            value = json.loads(match.group(1))
            return value if isinstance(value, dict) else {}
        except Exception:
            continue
    return {}


def count_archive_entries(content: str) -> int:
    headings = re.findall(r"^##\s+", content or "", flags=re.M)
    table_rows = [
        line
        for line in (content or "").splitlines()
        if line.strip().startswith("|")
        and "---" not in line
        and not any(header in line for header in ("时间", "企业ID", "风险等级"))
    ]
    return max(len(headings), len(table_rows))


def split_markdown_entries(content: str) -> List[str]:
    text = content or ""
    matches = list(re.finditer(r"^##\s+.+$", text, flags=re.M))
    if not matches:
        return [text] if text.strip() else []
    entries: List[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if block:
            entries.append(block)
    return entries


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    uri_path = Path(db_path).resolve().as_posix()
    if not Path(db_path).exists():
        return sqlite3.connect(db_path)
    return sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)


def read_agentfs_file_raw(db_path: str, path: str) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
    normalized = normalize_agentfs_path(path)
    try:
        conn = _connect_readonly(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT content, checksum FROM files WHERE path = ?", (normalized,))
        file_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT size, mode, owner, agent_id, created_at, updated_at, checksum
            FROM metadata WHERE path = ?
            """,
            (normalized,),
        )
        meta_row = cursor.fetchone()
        conn.close()
    except Exception as exc:
        logger.warning("读取 AgentFS 文件失败 %s: %s", path, exc)
        return None, None

    if file_row is None and meta_row is None:
        return None, None
    metadata = {
        "path": normalized,
        "size": int(meta_row[0] or 0) if meta_row else len(file_row[0] or b""),
        "mode": meta_row[1] if meta_row else "644",
        "owner": meta_row[2] if meta_row else "agent",
        "agent_id": meta_row[3] if meta_row else None,
        "created_at": meta_row[4] if meta_row else None,
        "updated_at": meta_row[5] if meta_row else None,
        "checksum": (meta_row[6] if meta_row else file_row[1]),
    }
    return file_row[0] if file_row else None, metadata


def list_agentfs_metadata(db_path: str, root: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        conn = _connect_readonly(db_path)
        cursor = conn.cursor()
        if root:
            normalized = normalize_agentfs_path(root)
            cursor.execute(
                """
                SELECT path, size, mode, owner, agent_id, created_at, updated_at, checksum
                FROM metadata WHERE path LIKE ? ORDER BY updated_at DESC
                """,
                (f"{normalized}%",),
            )
        else:
            cursor.execute(
                """
                SELECT path, size, mode, owner, agent_id, created_at, updated_at, checksum
                FROM metadata ORDER BY updated_at DESC
                """
            )
        rows = cursor.fetchall()
        conn.close()
    except Exception as exc:
        logger.warning("读取 AgentFS metadata 失败: %s", exc)
        return []
    return [
        {
            "path": row[0],
            "size": int(row[1] or 0),
            "mode": row[2] or "644",
            "owner": row[3] or "agent",
            "agent_id": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "checksum": row[7],
        }
        for row in rows
    ]


def read_operation_log(db_path: str, limit: int = 100) -> List[Dict[str, Any]]:
    try:
        conn = _connect_readonly(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, operation, agent_id, path, details
            FROM operation_log ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as exc:
        logger.warning("读取 AgentFS operation_log 失败: %s", exc)
        return []
    return [
        {
            "id": row[0],
            "timestamp": row[1],
            "time": iso_from_timestamp(row[1]),
            "operation": row[2],
            "agent_id": row[3],
            "path": display_agentfs_path(row[4] or ""),
            "details": row[5] or "",
        }
        for row in rows
    ]


def operation_summary(db_path: str) -> Dict[str, Any]:
    logs = read_operation_log(db_path, limit=500)
    counts = {"READ": 0, "WRITE": 0, "DELETE": 0, "SNAPSHOT": 0, "ROLLBACK": 0}
    last_write: Optional[float] = None
    for item in logs:
        op = str(item.get("operation") or "").upper()
        counts[op] = counts.get(op, 0) + 1
        if op == "WRITE":
            ts = item.get("timestamp")
            if ts is not None and (last_write is None or ts > last_write):
                last_write = float(ts)
    return {
        "counts": counts,
        "recent": logs[:12],
        "last_write_time": iso_from_timestamp(last_write),
        "write_status": "active" if last_write else "no_write",
    }


def _empty_priority_count() -> Dict[str, int]:
    return {priority: 0 for priority in PRIORITIES}


def _date_bucket(timestamp: Optional[float]) -> str:
    if timestamp is None:
        return "未知"
    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d")
    except Exception:
        return "未知"


def _add_count(mapping: Dict[str, int], key: str, value: int = 1) -> None:
    mapping[key] = mapping.get(key, 0) + value


def _chart_items(counts: Dict[str, int]) -> List[Dict[str, Any]]:
    return [{"name": key, "value": value} for key, value in counts.items()]


def _score_association(record: Dict[str, Any]) -> float:
    score = 0.45
    if record.get("module") == "warning_experience":
        score += 0.2
    if record.get("risk_type") and record.get("risk_type") != "未标注":
        score += 0.15
    if record.get("priority") in ("P0", "P1"):
        score += 0.1
    if record.get("rag_score") is not None:
        try:
            score = max(score, min(1.0, float(record["rag_score"])))
        except Exception:
            pass
    return round(min(score, 1.0), 3)


def collect_short_term(short_term: Optional[ShortTermMemory]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    priority_counts = _empty_priority_count()
    trend_counts: Dict[str, int] = {}
    token_usage = 0
    summary_count = 0
    compressed_count = 0
    records: List[Dict[str, Any]] = []

    entries = short_term.get_all() if short_term is not None else []
    for index, entry in enumerate(entries):
        metadata = entry.get("metadata") or {}
        content = str(entry.get("content") or "")
        priority = str(entry.get("priority") or "P2")
        timestamp = float(entry.get("timestamp") or time.time())
        tokens = int(entry.get("tokens") or 0)
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
        token_usage += tokens
        if entry.get("summarized"):
            summary_count += 1
        if entry.get("compressed"):
            compressed_count += 1
        _add_count(trend_counts, _date_bucket(timestamp))
        risk_type = detect_risk_type(content, metadata)
        risk_level = detect_risk_level(content, metadata)
        records.append({
            "id": f"short-{index}-{int(timestamp)}",
            "module": "short_term",
            "source": "短期记忆",
            "path": "runtime/short_term",
            "content": content,
            "summary": compact_text(content),
            "priority": priority,
            "created_at": iso_from_timestamp(timestamp),
            "updated_at": iso_from_timestamp(timestamp),
            "timestamp": timestamp,
            "tokens": tokens,
            "size": len(content.encode("utf-8")),
            "metadata": metadata,
            "risk_type": risk_type,
            "risk_level": risk_level,
            "association_score": 0.5,
        })

    p1_summary_count = len(short_term.get_p1_summaries()) if short_term is not None else 0
    return {
        "total": len(entries),
        "priority_distribution": priority_counts,
        "token_usage": token_usage,
        "token_limit": short_term.token_limit if short_term is not None else 0,
        "max_tokens": short_term.max_tokens if short_term is not None else 0,
        "trend": [{"date": key, "value": trend_counts[key]} for key in sorted(trend_counts)],
        "recent": sorted(records, key=lambda item: item.get("timestamp") or 0, reverse=True)[:10],
        "summary_count": summary_count + p1_summary_count,
        "compressed_count": compressed_count,
        "p1_pending_archive": p1_summary_count,
    }, records


def collect_long_term(db_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    files: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    priority_counts = _empty_priority_count()
    risk_type_counts: Dict[str, int] = {}
    keyword_counts: Dict[str, int] = {}

    for path, default_priority, label in LONG_TERM_ARCHIVES:
        raw, metadata = read_agentfs_file_raw(db_path, path)
        content = raw.decode("utf-8", errors="replace") if raw else ""
        entry_count = count_archive_entries(content)
        updated_at = metadata.get("updated_at") if metadata else None
        file_info = {
            "path": path,
            "label": label,
            "exists": bool(raw is not None or metadata is not None),
            "size": metadata.get("size", 0) if metadata else 0,
            "updated_at": iso_from_timestamp(updated_at),
            "entry_count": entry_count,
            "priority": default_priority,
            "checksum": metadata.get("checksum") if metadata else "",
            "risk_type_distribution": {},
            "priority_distribution": _empty_priority_count(),
        }
        entries = split_markdown_entries(content)
        if not entries and content.strip():
            entries = [content]
        if not entries:
            entries = []
        for index, block in enumerate(entries):
            block_meta = try_parse_metadata(block)
            priority = detect_priority(block, default=default_priority)
            risk_type = detect_risk_type(block, block_meta)
            risk_level = detect_risk_level(block, block_meta)
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
            file_info["priority_distribution"][priority] = file_info["priority_distribution"].get(priority, 0) + 1
            _add_count(risk_type_counts, risk_type)
            _add_count(file_info["risk_type_distribution"], risk_type)
            for risk_key, keywords in RISK_TYPE_KEYWORDS.items():
                if any(keyword in block for keyword in keywords):
                    _add_count(keyword_counts, risk_key)
            records.append({
                "id": f"long-{path}-{index}",
                "module": "long_term",
                "source": label,
                "path": path,
                "content": block,
                "summary": compact_text(block),
                "priority": priority,
                "created_at": iso_from_timestamp(updated_at),
                "updated_at": iso_from_timestamp(updated_at),
                "timestamp": updated_at,
                "tokens": max(1, len(block) // 2),
                "size": len(block.encode("utf-8")),
                "metadata": block_meta,
                "risk_type": risk_type,
                "risk_level": risk_level,
                "association_score": 0.62,
            })
        files.append(file_info)

    return {
        "files": files,
        "total_entries": sum(item["entry_count"] for item in files),
        "priority_distribution": priority_counts,
        "risk_type_distribution": risk_type_counts,
        "keyword_distribution": keyword_counts,
    }, records


def _read_rag_report() -> Dict[str, Any]:
    path = resolve_project_path("reports/rag_index_rebuild_run.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_warning_experience(db_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    records: List[Dict[str, Any]] = []
    file_stats: List[Dict[str, Any]] = []
    type_counts: Dict[str, int] = {}
    risk_level_counts: Dict[str, int] = {}
    risk_type_counts: Dict[str, int] = {}

    for path, label in WARNING_FILES:
        raw, metadata = read_agentfs_file_raw(db_path, path)
        content = raw.decode("utf-8", errors="replace") if raw else ""
        updated_at = metadata.get("updated_at") if metadata else None
        entries = split_markdown_entries(content)
        if not entries and content.strip():
            entries = [content]
        _add_count(type_counts, label, max(1, len(entries)) if content.strip() else 0)
        file_stats.append({
            "path": path,
            "label": label,
            "exists": bool(raw is not None or metadata is not None),
            "size": metadata.get("size", 0) if metadata else 0,
            "updated_at": iso_from_timestamp(updated_at),
            "entry_count": count_archive_entries(content),
        })
        for index, block in enumerate(entries):
            block_meta = try_parse_metadata(block)
            risk_type = detect_risk_type(block, block_meta)
            risk_level = detect_risk_level(block, block_meta)
            _add_count(risk_type_counts, risk_type)
            if risk_level:
                _add_count(risk_level_counts, risk_level)
            records.append({
                "id": f"warning-{path}-{index}",
                "module": "warning_experience",
                "source": label,
                "path": path,
                "content": block,
                "summary": compact_text(block),
                "priority": detect_priority(block, default="P1"),
                "created_at": iso_from_timestamp(updated_at),
                "updated_at": iso_from_timestamp(updated_at),
                "timestamp": updated_at,
                "tokens": max(1, len(block) // 2),
                "size": len(block.encode("utf-8")),
                "metadata": block_meta,
                "risk_type": risk_type,
                "risk_level": risk_level,
                "association_score": 0.72,
            })

    rag = _read_rag_report()
    per_file = rag.get("per_source_file_chunk_count") or {}
    warning_rag_hits = 0
    for key, value in per_file.items():
        normalized = str(key).replace("\\", "/")
        if any(path in normalized for path, _ in WARNING_FILES):
            try:
                warning_rag_hits += int(value)
            except Exception:
                pass

    return {
        "files": file_stats,
        "total": len(records),
        "type_distribution": type_counts,
        "risk_level_distribution": risk_level_counts,
        "risk_type_distribution": risk_type_counts,
        "rag_hit_count": warning_rag_hits,
        "rag_collection_count": int(rag.get("collection_count") or 0),
    }, records


def record_matches(record: Dict[str, Any], filters: MemoryStatsFilters) -> bool:
    if filters.module and filters.module != "all" and record.get("module") != filters.module:
        return False
    if filters.priority and record.get("priority") != filters.priority:
        return False
    timestamp = record.get("timestamp")
    if filters.start_time is not None and timestamp is not None and float(timestamp) < filters.start_time:
        return False
    if filters.end_time is not None and timestamp is not None and float(timestamp) > filters.end_time:
        return False
    if filters.keyword:
        needle = filters.keyword.lower()
        haystack = json.dumps(record, ensure_ascii=False).lower()
        if needle not in haystack:
            return False
    if filters.path and filters.path not in str(record.get("path") or ""):
        return False
    if filters.risk_level and filters.risk_level not in str(record.get("risk_level") or ""):
        return False
    if filters.risk_type and filters.risk_type not in str(record.get("risk_type") or ""):
        return False
    return True


def apply_filters(records: Iterable[Dict[str, Any]], filters: MemoryStatsFilters) -> List[Dict[str, Any]]:
    return [record for record in records if record_matches(record, filters)]


def build_heatmap(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    x_axis = sorted({str(item.get("risk_type") or "未标注") for item in records}) or ["未标注"]
    y_axis = PRIORITIES
    matrix: Dict[Tuple[str, str], int] = {}
    for item in records:
        x_key = str(item.get("risk_type") or "未标注")
        y_key = str(item.get("priority") or "P2")
        matrix[(x_key, y_key)] = matrix.get((x_key, y_key), 0) + 1
    data = [
        {"x": x_key, "y": y_key, "value": matrix.get((x_key, y_key), 0)}
        for y_key in y_axis
        for x_key in x_axis
    ]
    return {"xAxis": x_axis, "yAxis": y_axis, "data": data}


def build_trend(records: List[Dict[str, Any]], operation_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, int]] = {}
    for record in records:
        bucket = _date_bucket(record.get("timestamp"))
        row = buckets.setdefault(bucket, {
            "date": bucket,
            "short_term": 0,
            "long_term": 0,
            "warning_experience": 0,
            "agentfs_write": 0,
        })
        module = str(record.get("module") or "")
        if module in row:
            row[module] += 1
    for log in operation_logs:
        if str(log.get("operation") or "").upper() != "WRITE":
            continue
        bucket = _date_bucket(log.get("timestamp"))
        row = buckets.setdefault(bucket, {
            "date": bucket,
            "short_term": 0,
            "long_term": 0,
            "warning_experience": 0,
            "agentfs_write": 0,
        })
        row["agentfs_write"] += 1
    return [buckets[key] for key in sorted(buckets)]


def build_statistics_payload(
    *,
    filters: Optional[MemoryStatsFilters] = None,
    agentfs: Optional[AgentFS] = None,
    short_term: Optional[ShortTermMemory] = None,
) -> Dict[str, Any]:
    filters = filters or MemoryStatsFilters()
    config = get_config()
    fs = agentfs or AgentFS()
    db_path = fs.db_path or config.harness.agentfs.db_path

    short_stats, short_records = collect_short_term(short_term)
    long_stats, long_records = collect_long_term(db_path)
    warning_stats, warning_records = collect_warning_experience(db_path)
    operations = operation_summary(db_path)

    all_records = short_records + long_records + warning_records
    for record in all_records:
        record["association_score"] = _score_association(record)

    filtered_records = apply_filters(all_records, filters)
    filtered_records.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    paged_records = filtered_records[filters.offset: filters.offset + filters.limit]

    priority_counts = _empty_priority_count()
    module_counts: Dict[str, int] = {}
    risk_type_counts: Dict[str, int] = {}
    path_counts: Dict[str, int] = {}
    for record in filtered_records:
        priority_counts[str(record.get("priority") or "P2")] = priority_counts.get(str(record.get("priority") or "P2"), 0) + 1
        _add_count(module_counts, str(record.get("module") or "unknown"))
        _add_count(risk_type_counts, str(record.get("risk_type") or "未标注"))
        _add_count(path_counts, str(record.get("path") or "unknown"))

    today = datetime.now().strftime("%Y-%m-%d")
    today_added = sum(1 for record in all_records if _date_bucket(record.get("timestamp")) == today)
    recent_write = operations.get("last_write_time") or ""

    kpis = [
        {"key": "total_memory", "label": "总记忆数", "value": len(all_records), "unit": "条", "status": "normal"},
        {"key": "today_added", "label": "今日新增", "value": today_added, "unit": "条", "status": "normal"},
        {"key": "p1_pending_archive", "label": "P1 待归档", "value": short_stats["p1_pending_archive"], "unit": "条", "status": "warning" if short_stats["p1_pending_archive"] else "normal"},
        {"key": "long_term_files", "label": "长期归档文件", "value": len([f for f in long_stats["files"] if f["exists"]]), "unit": "个", "status": "normal"},
        {"key": "last_write_time", "label": "最近写入时间", "value": recent_write or "无", "unit": "", "status": "normal" if recent_write else "warning"},
        {"key": "agentfs_write_status", "label": "AgentFS 写入状态", "value": operations["write_status"], "unit": "", "status": "normal" if recent_write else "warning"},
    ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "filters": {
            "module": filters.module,
            "priority": filters.priority,
            "start_time": iso_from_timestamp(filters.start_time),
            "end_time": iso_from_timestamp(filters.end_time),
            "keyword": filters.keyword,
            "path": filters.path,
            "risk_level": filters.risk_level,
            "risk_type": filters.risk_type,
            "limit": filters.limit,
            "offset": filters.offset,
        },
        "kpis": kpis,
        "short_term": short_stats,
        "long_term": long_stats,
        "warning_experience": warning_stats,
        "agentfs_operations": operations,
        "charts": {
            "trend": build_trend(filtered_records, operations["recent"]),
            "priority_bar": _chart_items(priority_counts),
            "type_bar": _chart_items(path_counts),
            "source_pie": _chart_items(module_counts),
            "risk_type_pie": _chart_items(risk_type_counts),
            "heatmap": build_heatmap(filtered_records),
        },
        "recent_records": paged_records,
        "total_records": len(filtered_records),
        "limit": filters.limit,
        "offset": filters.offset,
    }


def build_export_rows(
    *,
    filters: Optional[MemoryStatsFilters] = None,
    agentfs: Optional[AgentFS] = None,
    short_term: Optional[ShortTermMemory] = None,
) -> List[Dict[str, Any]]:
    export_filters = filters or MemoryStatsFilters()
    full_filters = MemoryStatsFilters(
        module=export_filters.module,
        priority=export_filters.priority,
        start_time=export_filters.start_time,
        end_time=export_filters.end_time,
        keyword=export_filters.keyword,
        path=export_filters.path,
        risk_level=export_filters.risk_level,
        risk_type=export_filters.risk_type,
        limit=100000,
        offset=0,
    )
    payload = build_statistics_payload(
        filters=full_filters,
        agentfs=agentfs,
        short_term=short_term,
    )
    rows = []
    for record in payload["recent_records"]:
        rows.append({
            "module": record.get("module"),
            "content": record.get("content"),
            "summary": record.get("summary"),
            "priority": record.get("priority"),
            "source": record.get("source"),
            "path": record.get("path"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "timestamp": record.get("timestamp"),
            "tokens": record.get("tokens"),
            "size": record.get("size"),
            "risk_level": record.get("risk_level"),
            "risk_type": record.get("risk_type"),
            "association_score": record.get("association_score"),
            "rag_score": record.get("rag_score"),
            "metadata": json.dumps(record.get("metadata") or {}, ensure_ascii=False),
        })
    return rows
