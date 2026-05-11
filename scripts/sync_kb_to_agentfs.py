"""Synchronize filesystem Markdown knowledge bases into AgentFS.

The filesystem ``knowledge_base/*.md`` files are treated as the current
authoritative source. AgentFS remains the runtime store with audit logs and
Git snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.agentfs import AgentFS
from harness.knowledge_base import KnowledgeBaseManager
from utils.config import get_config, resolve_project_path


DEFAULT_AGENT_ID = "kb_sync"
DEFAULT_MESSAGE = "Sync knowledge_base Markdown from filesystem"
MAIN_KB_FILES = tuple(KnowledgeBaseManager.KNOWLEDGE_FILES)


@dataclass(frozen=True)
class FsEntry:
    path: str
    size: int
    sha256: str
    mtime: str


@dataclass(frozen=True)
class AgentEntry:
    path: str
    size: int | None
    checksum: str | None
    updated_at: str | None
    content_size: int | None
    file_checksum: str | None
    agent_id: str | None
    status_note: str = ""


@dataclass(frozen=True)
class BackupInfo:
    path: str
    size: int
    copied_at: str
    source_mtime: str


def _iso_from_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_paths() -> tuple[Path, Path, Path, Path]:
    config = get_config()
    db_path = resolve_project_path(config.harness.agentfs.db_path)
    git_repo_path = resolve_project_path(config.harness.agentfs.git_repo_path)
    snapshots_dir = resolve_project_path(config.harness.agentfs.snapshots_dir)
    kb_dir = PROJECT_ROOT / "knowledge_base"
    return db_path, git_repo_path, snapshots_dir, kb_dir


def filesystem_manifest(kb_dir: Path, filenames: tuple[str, ...] = MAIN_KB_FILES) -> list[FsEntry]:
    entries: list[FsEntry] = []
    for filename in filenames:
        file_path = kb_dir / filename
        data = file_path.read_bytes()
        stat = file_path.stat()
        entries.append(
            FsEntry(
                path=f"/knowledge_base/{filename}",
                size=len(data),
                sha256=_sha256(data),
                mtime=_iso_from_timestamp(stat.st_mtime) or "",
            )
        )
    return entries


def agentfs_manifest(db_path: Path) -> list[AgentEntry]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            WITH paths AS (
                SELECT path FROM files
                WHERE path LIKE '/knowledge_base/%' OR path LIKE 'knowledge_base/%'
                UNION
                SELECT path FROM metadata
                WHERE path LIKE '/knowledge_base/%' OR path LIKE 'knowledge_base/%'
            )
            SELECT
                p.path,
                m.size,
                m.checksum,
                m.updated_at,
                length(f.content) AS content_size,
                f.checksum AS file_checksum,
                m.agent_id
            FROM paths p
            LEFT JOIN files f ON f.path = p.path
            LEFT JOIN metadata m ON m.path = p.path
            ORDER BY p.path
            """
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    entries = []
    for row in rows:
        path = row[0]
        note = ""
        if "?" in path or not path.endswith(".md"):
            note = "deprecated_malformed_path"
        entries.append(
            AgentEntry(
                path=path,
                size=row[1],
                checksum=row[2],
                updated_at=_iso_from_timestamp(row[3]),
                content_size=row[4],
                file_checksum=row[5],
                agent_id=row[6],
                status_note=note,
            )
        )
    return entries


def compare_manifests(fs_entries: list[FsEntry], agent_entries: list[AgentEntry]) -> dict[str, Any]:
    by_agent = {entry.path: entry for entry in agent_entries}
    main_paths = {entry.path for entry in fs_entries}
    comparison = []
    for fs_entry in fs_entries:
        agent_entry = by_agent.get(fs_entry.path)
        if agent_entry is None:
            status = "missing_in_agentfs"
        elif agent_entry.size == fs_entry.size and agent_entry.checksum == fs_entry.sha256:
            status = "match"
        else:
            status = "diff"

        comparison.append(
            {
                "path": fs_entry.path,
                "fs_size": fs_entry.size,
                "fs_sha256": fs_entry.sha256,
                "fs_mtime": fs_entry.mtime,
                "agent_size": agent_entry.size if agent_entry else None,
                "agent_checksum": agent_entry.checksum if agent_entry else None,
                "agent_updated_at": agent_entry.updated_at if agent_entry else None,
                "agent_id": agent_entry.agent_id if agent_entry else None,
                "status": status,
            }
        )

    extras = [entry for entry in agent_entries if entry.path not in main_paths]
    return {
        "filesystem": [asdict(entry) for entry in fs_entries],
        "agentfs": [asdict(entry) for entry in agent_entries],
        "comparison": comparison,
        "extras_or_malformed": [asdict(entry) for entry in extras],
        "all_main_files_match": all(item["status"] == "match" for item in comparison),
    }


def backup_agentfs_db(db_path: Path, snapshots_dir: Path, label: str = "pre_kb_sync") -> BackupInfo:
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = snapshots_dir / f"agentfs_{label}_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    stat = backup_path.stat()
    return BackupInfo(
        path=str(backup_path),
        size=stat.st_size,
        copied_at=datetime.now().isoformat(timespec="seconds"),
        source_mtime=_iso_from_timestamp(db_path.stat().st_mtime) or "",
    )


def sync_files_to_agentfs(
    agentfs: AgentFS,
    kb_dir: Path,
    filenames: tuple[str, ...] = MAIN_KB_FILES,
    agent_id: str = DEFAULT_AGENT_ID,
) -> list[dict[str, Any]]:
    synced = []
    for filename in filenames:
        file_path = kb_dir / filename
        content = file_path.read_bytes()
        agent_path = f"knowledge_base/{filename}"
        agentfs.write(agent_path, content, agent_id=agent_id)
        synced.append(
            {
                "path": f"/{agent_path}",
                "size": len(content),
                "sha256": _sha256(content),
            }
        )
    return synced


def verify_agentfs_content(
    db_path: Path,
    kb_dir: Path,
    filenames: tuple[str, ...] = MAIN_KB_FILES,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        results = []
        for filename in filenames:
            agent_path = f"/knowledge_base/{filename}"
            fs_content = (kb_dir / filename).read_bytes()
            cursor.execute("SELECT content FROM files WHERE path = ?", (agent_path,))
            row = cursor.fetchone()
            agent_content = row[0] if row else None
            results.append(
                {
                    "path": agent_path,
                    "matches": agent_content == fs_content,
                    "fs_size": len(fs_content),
                    "agent_size": len(agent_content) if agent_content is not None else None,
                    "fs_sha256": _sha256(fs_content),
                    "agent_sha256": _sha256(agent_content) if agent_content is not None else None,
                }
            )
    finally:
        conn.close()
    return results


def build_summary(args: argparse.Namespace) -> dict[str, Any]:
    db_path, git_repo_path, snapshots_dir, kb_dir = get_paths()
    agentfs = AgentFS(db_path=str(db_path), git_repo_path=str(git_repo_path))

    summary: dict[str, Any] = {
        "db_path": str(db_path),
        "kb_dir": str(kb_dir),
        "snapshots_dir": str(snapshots_dir),
        "agent_id": args.agent_id,
        "dry_run": args.dry_run,
        "before": compare_manifests(
            filesystem_manifest(kb_dir),
            agentfs_manifest(db_path),
        ),
        "backup": None,
        "synced": [],
        "verify": [],
        "after": None,
        "snapshot_commit_id": None,
    }

    if args.backup and not args.dry_run:
        summary["backup"] = asdict(backup_agentfs_db(db_path, snapshots_dir))

    if args.sync and not args.dry_run:
        summary["synced"] = sync_files_to_agentfs(
            agentfs=agentfs,
            kb_dir=kb_dir,
            agent_id=args.agent_id,
        )

    if args.verify:
        summary["verify"] = verify_agentfs_content(db_path, kb_dir)

    if args.snapshot and not args.dry_run:
        summary["snapshot_commit_id"] = agentfs.snapshot(args.message, agent_id=args.agent_id)

    summary["after"] = compare_manifests(
        filesystem_manifest(kb_dir),
        agentfs_manifest(db_path),
    )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compare only; do not write AgentFS.")
    parser.add_argument("--backup", action="store_true", help="Copy data/agentfs.db into snapshots first.")
    parser.add_argument("--sync", action="store_true", help="Write the six Markdown KB files into AgentFS.")
    parser.add_argument("--verify", action="store_true", help="Verify AgentFS byte content against filesystem.")
    parser.add_argument("--snapshot", action="store_true", help="Create an AgentFS Git snapshot after sync.")
    parser.add_argument("--agent-id", default=DEFAULT_AGENT_ID, help="Agent ID for AgentFS audit records.")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="Snapshot commit message.")
    parser.add_argument("--report-json", default=None, help="Optional path for a JSON run summary.")
    args = parser.parse_args(argv)

    if not any([args.dry_run, args.backup, args.sync, args.verify, args.snapshot]):
        args.dry_run = True
        args.verify = True

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_summary(args)

    if args.report_json:
        report_path = resolve_project_path(args.report_json)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if (
        args.verify
        and not args.dry_run
        and summary["verify"]
        and not all(item["matches"] for item in summary["verify"])
    ):
        return 1
    if (
        summary["after"]
        and not args.dry_run
        and not summary["after"]["all_main_files_match"]
        and (args.sync or args.verify)
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
