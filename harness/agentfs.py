"""
AgentFS 虚拟文件系统
基于 SQLite 设计，实现 POSIX-like 文件系统接口
"""

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import git
from git import Repo

from utils.config import get_config
from utils.exceptions import AgentFSError
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FileStat:
    """文件元数据结构体"""
    path: str
    size: int
    mode: str
    owner: str
    agent_id: Optional[str]
    created_at: float
    updated_at: float
    checksum: str


class AgentFS:
    """
    AgentFS 虚拟文件系统

    SQLite 表结构：
    1. files: 文件内容（Blob）与路径哈希
    2. metadata: 文件元数据（权限/时间/AgentID）
    3. operation_log: 操作日志（READ/WRITE/DELETE）
    """

    ALLOWED_ROOTS = ("knowledge_base", "memory")

    def __init__(self, db_path: Optional[str] = None, git_repo_path: Optional[str] = None):
        config = get_config()
        self.db_path = db_path or config.harness.agentfs.db_path
        self.git_repo_path = git_repo_path or config.harness.agentfs.git_repo_path
        self._ensure_dirs()
        self._init_db()
        self._init_git()

    def _ensure_dirs(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        os.makedirs(self.git_repo_path, exist_ok=True)

    def _init_db(self) -> None:
        """初始化 SQLite 数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # files 表：存储 BLOB/路径/哈希
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                content BLOB NOT NULL,
                checksum TEXT NOT NULL
            )
        """)

        # metadata 表：存储权限/时间/AgentID
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                size INTEGER NOT NULL,
                mode TEXT NOT NULL DEFAULT '644',
                owner TEXT NOT NULL DEFAULT 'agent',
                agent_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                checksum TEXT NOT NULL
            )
        """)

        # operation_log 表：READ/WRITE/DELETE 审计日志
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                operation TEXT NOT NULL,
                agent_id TEXT,
                path TEXT,
                details TEXT
            )
        """)

        # 兼容旧表：尝试添加缺失的列（idempotent）
        for col, dtype in [("checksum", "TEXT"), ("content", "BLOB")]:
            try:
                cursor.execute(f"ALTER TABLE files ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                pass

        for col, dtype, default in [
            ("mode", "TEXT", "'644'"),
            ("owner", "TEXT", "'agent'"),
            ("agent_id", "TEXT", None),
        ]:
            try:
                default_clause = f"DEFAULT {default}" if default else ""
                cursor.execute(f"ALTER TABLE metadata ADD COLUMN {col} {dtype} {default_clause}")
            except sqlite3.OperationalError:
                pass

        # 兼容旧 logs 表：若不存在 operation_log 但存在 logs，则重命名（仅首次）
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='operation_log'")
        if not cursor.fetchone():
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs'")
            if cursor.fetchone():
                cursor.execute("ALTER TABLE logs RENAME TO operation_log")

        conn.commit()
        conn.close()
        logger.info("AgentFS 数据库已初始化")

    def _init_git(self) -> None:
        """初始化 Git 仓库"""
        git_dir = os.path.join(self.git_repo_path, ".git")
        if not os.path.exists(git_dir):
            Repo.init(self.git_repo_path)
            logger.info(f"Git 仓库已初始化: {self.git_repo_path}")

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return path

    def _validate_path(self, path: str) -> None:
        """路径沙箱：仅允许 knowledge_base/ 与 memory/ 为根"""
        normalized = self._normalize_path(path)
        parts = normalized.strip("/").split("/")
        if not parts or parts[0] not in self.ALLOWED_ROOTS:
            raise PermissionError(
                f"路径越界: {path}，仅允许 {'/'.join(self.ALLOWED_ROOTS)}/ 为根"
            )

    def _log_operation(self, operation: str, path: Optional[str] = None,
                       agent_id: Optional[str] = None, details: Optional[str] = None) -> None:
        """记录操作日志到 operation_log"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO operation_log (timestamp, operation, agent_id, path, details) VALUES (?, ?, ?, ?, ?)",
            (time.time(), operation, agent_id, path, details),
        )
        conn.commit()
        conn.close()

    def _checksum(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def write(self, path: str, content: bytes, agent_id: Optional[str] = None,
              mode: str = "644", owner: str = "agent") -> None:
        """写入文件"""
        path = self._normalize_path(path)
        self._validate_path(path)

        now = time.time()
        checksum = self._checksum(content)

        conn = self._get_conn()
        cursor = conn.cursor()

        # 保留原始创建时间（若文件已存在）
        cursor.execute("SELECT created_at FROM metadata WHERE path = ?", (path,))
        old = cursor.fetchone()
        created_at = old[0] if old else now

        cursor.execute(
            "INSERT OR REPLACE INTO files (path, content, checksum) VALUES (?, ?, ?)",
            (path, content, checksum),
        )
        cursor.execute(
            """
            INSERT OR REPLACE INTO metadata
            (path, size, mode, owner, agent_id, created_at, updated_at, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (path, len(content), mode, owner, agent_id, created_at, now, checksum),
        )

        conn.commit()
        conn.close()
        self._log_operation("WRITE", path=path, agent_id=agent_id, details=f"size={len(content)}")
        logger.debug(f"AgentFS 写入: {path}")

    def read(self, path: str) -> bytes:
        """读取文件"""
        path = self._normalize_path(path)
        self._validate_path(path)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM files WHERE path = ?", (path,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            raise AgentFSError(f"文件不存在: {path}")

        self._log_operation("READ", path=path)
        return row[0]

    def delete(self, path: str, agent_id: Optional[str] = None) -> None:
        """删除文件"""
        path = self._normalize_path(path)
        self._validate_path(path)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM files WHERE path = ?", (path,))
        cursor.execute("DELETE FROM metadata WHERE path = ?", (path,))
        conn.commit()
        conn.close()
        self._log_operation("DELETE", path=path, agent_id=agent_id)
        logger.debug(f"AgentFS 删除: {path}")

    def ls(self, directory: str = "/") -> List[FileStat]:
        """列出目录下的文件（POSIX-like ls）"""
        directory = self._normalize_path(directory)
        if directory != "/":
            self._validate_path(directory)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT path, size, mode, owner, agent_id, created_at, updated_at, checksum
            FROM metadata WHERE path LIKE ?
            """,
            (directory + "%",),
        )
        rows = cursor.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append(FileStat(
                path=row[0],
                size=row[1],
                mode=row[2] or "644",
                owner=row[3] or "agent",
                agent_id=row[4],
                created_at=row[5],
                updated_at=row[6],
                checksum=row[7],
            ))
        return results

    def stat(self, path: str) -> FileStat:
        """获取文件元数据（POSIX-like stat）"""
        path = self._normalize_path(path)
        self._validate_path(path)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT path, size, mode, owner, agent_id, created_at, updated_at, checksum
            FROM metadata WHERE path = ?
            """,
            (path,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            raise AgentFSError(f"文件不存在: {path}")

        return FileStat(
            path=row[0],
            size=row[1],
            mode=row[2] or "644",
            owner=row[3] or "agent",
            agent_id=row[4],
            created_at=row[5],
            updated_at=row[6],
            checksum=row[7],
        )

    def exists(self, path: str) -> bool:
        """检查文件是否存在"""
        path = self._normalize_path(path)
        if path != "/":
            try:
                self._validate_path(path)
            except PermissionError:
                return False

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM files WHERE path = ?", (path,))
        row = cursor.fetchone()
        conn.close()
        return row is not None

    def list_files(self, directory: str = "/") -> List[Dict[str, Any]]:
        """列出目录下的文件（兼容旧接口，返回字典列表）"""
        stats = self.ls(directory)
        return [
            {
                "path": s.path,
                "size": s.size,
                "updated_at": datetime.fromtimestamp(s.updated_at).isoformat(),
                "checksum": s.checksum,
            }
            for s in stats
        ]

    def checkpoint(self) -> None:
        """触发 SQLite Checkpoint，合并 WAL 日志"""
        conn = self._get_conn()
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.close()
        logger.info("AgentFS Checkpoint 完成")

    def snapshot(self, commit_message: str, agent_id: Optional[str] = None) -> str:
        """
        生成快照并 Git 提交

        Returns:
            Commit ID
        """
        self.checkpoint()

        # 将 db 文件复制到 git 仓库
        db_name = os.path.basename(self.db_path)
        dest = os.path.join(self.git_repo_path, db_name)
        import shutil
        shutil.copy2(self.db_path, dest)

        repo = Repo(self.git_repo_path)
        repo.index.add([db_name])

        # 如果无变更则直接返回当前 HEAD
        try:
            has_head = bool(repo.head.commit)
        except Exception:
            has_head = False

        has_changes = bool(repo.index.diff("HEAD")) if has_head else True

        if has_changes:
            commit = repo.index.commit(f"{commit_message} [agent:{agent_id or 'system'}]")
            commit_id = commit.hexsha
            logger.info(f"Git 提交完成，Commit ID: {commit_id}")
            self._log_operation("SNAPSHOT", agent_id=agent_id, details=f"commit={commit_id}")
            return commit_id
        else:
            commit_id = repo.head.commit.hexsha
            logger.info(f"无变更，当前 Commit ID: {commit_id}")
            return commit_id

    def rollback(self, commit_id: str) -> None:
        """
        按 Commit ID 回滚到历史状态
        """
        repo = Repo(self.git_repo_path)
        try:
            commit = repo.commit(commit_id)
        except Exception as e:
            raise AgentFSError(f"无效的 Commit ID: {commit_id}") from e

        # 检出指定版本的 db 文件
        db_name = os.path.basename(self.db_path)
        blob = commit.tree / db_name
        content = blob.data_stream.read()

        with open(self.db_path, "wb") as f:
            f.write(content)

        self._log_operation("ROLLBACK", details=f"to_commit={commit_id}")
        logger.info(f"已回滚到 Commit: {commit_id}")

    def diff(self, commit_a: str, commit_b: str) -> List[Dict[str, str]]:
        """
        对比两个 Commit 的差异

        Returns:
            变更列表
        """
        repo = Repo(self.git_repo_path)
        diff = repo.commit(commit_a).diff(commit_b)
        changes = []
        for d in diff:
            changes.append({
                "change_type": d.change_type,
                "file": d.a_path or d.b_path,
            })
        return changes
