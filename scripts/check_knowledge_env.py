"""
Read-only diagnostics for AgentFS, knowledge-base files, Chroma storage,
and the public enterprise data file inventory.

The script intentionally avoids importing project modules that may initialize
or mutate AgentFS/Chroma state. It reads SQLite databases in read-only mode and
prints a JSON report.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dt(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _sqlite_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _sqlite_overview(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"exists": False, "path": str(db_path)}

    info: dict[str, Any] = {
        "exists": True,
        "path": str(db_path),
        "size_bytes": db_path.stat().st_size,
        "modified_at": _dt(db_path.stat().st_mtime),
        "tables": {},
    }
    with _connect_readonly(db_path) as conn:
        for table in _sqlite_table_names(conn):
            quoted = _quote_ident(table)
            columns = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
            count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            info["tables"][table] = {
                "row_count": count,
                "columns": [
                    {
                        "name": col[1],
                        "type": col[2],
                        "notnull": bool(col[3]),
                        "pk": bool(col[5]),
                    }
                    for col in columns
                ],
            }
    return info


def _agentfs_report(project_root: Path) -> dict[str, Any]:
    db_path = project_root / "data" / "agentfs.db"
    report = _sqlite_overview(db_path)
    if not report.get("exists"):
        return report

    with _connect_readonly(db_path) as conn:
        tables = set(_sqlite_table_names(conn))
        if "metadata" in tables:
            rows = conn.execute(
                """
                SELECT path, size, owner, agent_id, updated_at, checksum
                FROM metadata
                WHERE path LIKE '/knowledge_base/%' OR path LIKE '/memory/%'
                ORDER BY path
                """
            ).fetchall()
            report["virtual_files"] = [
                {
                    "path": row[0],
                    "size": row[1],
                    "owner": row[2],
                    "agent_id": row[3],
                    "updated_at": _dt(row[4]) if row[4] else None,
                    "checksum": row[5],
                }
                for row in rows
            ]
    return report


def _knowledge_files(project_root: Path) -> list[dict[str, Any]]:
    kb_dir = project_root / "knowledge_base"
    files = []
    if not kb_dir.exists():
        return files

    for path in sorted(kb_dir.rglob("*.md")):
        stat = path.stat()
        files.append(
            {
                "path": _rel(path, project_root),
                "size_bytes": stat.st_size,
                "modified_at": _dt(stat.st_mtime),
            }
        )
    return files


def _chroma_report(project_root: Path) -> list[dict[str, Any]]:
    data_dir = project_root / "data"
    reports = []
    if not data_dir.exists():
        return reports

    for sqlite_path in sorted(data_dir.rglob("chroma.sqlite3")):
        chroma_dir = sqlite_path.parent
        item = _sqlite_overview(sqlite_path)
        item["directory"] = _rel(chroma_dir, project_root)
        item["hnsw_index_dirs"] = [
            _rel(path, project_root)
            for path in sorted(chroma_dir.iterdir())
            if path.is_dir()
        ]

        if item.get("exists"):
            with _connect_readonly(sqlite_path) as conn:
                tables = set(_sqlite_table_names(conn))
                status: dict[str, Any] = {}
                for table in [
                    "collections",
                    "collection_metadata",
                    "segments",
                    "embeddings",
                    "embeddings_queue",
                ]:
                    if table in tables:
                        quoted = _quote_ident(table)
                        status[f"{table}_rows"] = conn.execute(
                            f"SELECT COUNT(*) FROM {quoted}"
                        ).fetchone()[0]
                item["chroma_status"] = status
        reports.append(item)
    return reports


def _public_data_report(public_root: Path) -> dict[str, Any]:
    files = []
    if public_root.exists():
        for path in sorted(public_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".csv", ".xlsx"}:
                stat = path.stat()
                files.append(
                    {
                        "path": _rel(path, public_root),
                        "suffix": path.suffix.lower(),
                        "size_bytes": stat.st_size,
                        "modified_at": _dt(stat.st_mtime),
                    }
                )

    suffix_counts = Counter(item["suffix"] for item in files)
    top_level_counts = Counter(Path(item["path"]).parts[0] for item in files)
    new_cleaned = [
        item for item in files if "new_已清洗" in Path(item["path"]).name
    ]

    return {
        "root": str(public_root),
        "exists": public_root.exists(),
        "file_count": len(files),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "top_level_counts": dict(sorted(top_level_counts.items())),
        "new_cleaned_files": new_cleaned,
        "source_file_count_excluding_new_cleaned": len(files) - len(new_cleaned),
        "files": files,
    }


def build_report(project_root: Path, public_data_root: Path | None = None) -> dict[str, Any]:
    project_root = project_root.resolve()
    if public_data_root is None:
        public_data_root = (project_root.parent / "公开数据").resolve()
    else:
        public_data_root = public_data_root.resolve()

    return {
        "project_root": str(project_root),
        "agentfs": _agentfs_report(project_root),
        "knowledge_base_files": _knowledge_files(project_root),
        "chroma": _chroma_report(project_root),
        "public_data": _public_data_report(public_data_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only knowledge environment check")
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to mining_risk_agent project root",
    )
    parser.add_argument(
        "--public-data-root",
        default=None,
        help="Path to the public data root; defaults to ../公开数据",
    )
    args = parser.parse_args()

    report = build_report(
        Path(args.project_root),
        Path(args.public_data_root) if args.public_data_root else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
