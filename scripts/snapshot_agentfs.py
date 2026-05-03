"""
AgentFS 快照脚本
PRAGMA wal_checkpoint(FULL) → 复制.db到snapshots/ → GitPython自动提交 → 生成Commit ID → 写入snapshots/index.json
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

# 将项目根目录加入路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_root = os.path.dirname(project_root)
if parent_root not in sys.path:
    sys.path.insert(0, parent_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import sqlite3

from git import Repo

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


def snapshot(agent_id: str, message: str) -> str:
    """
    生成 AgentFS 快照

    Returns:
        Git Commit ID
    """
    config = get_config()
    db_path = config.harness.agentfs.db_path
    git_repo_path = config.harness.agentfs.git_repo_path
    snapshots_dir = getattr(config.harness.agentfs, "snapshots_dir", "data/snapshots")

    os.makedirs(snapshots_dir, exist_ok=True)
    os.makedirs(git_repo_path, exist_ok=True)

    # 1. WAL Checkpoint
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(FULL)")
    conn.close()
    logger.info("SQLite WAL checkpoint(FULL) 完成")

    # 2. 复制 .db 到 snapshots/
    db_name = os.path.basename(db_path)
    snapshot_path = os.path.join(snapshots_dir, db_name)
    shutil.copy2(db_path, snapshot_path)
    logger.info(f"数据库已复制到快照目录: {snapshot_path}")

    # 3. GitPython 自动提交
    git_dir = os.path.join(git_repo_path, ".git")
    if not os.path.exists(git_dir):
        Repo.init(git_repo_path)
        logger.info(f"Git 仓库已初始化: {git_repo_path}")

    repo = Repo(git_repo_path)
    dest_in_repo = os.path.join(git_repo_path, db_name)
    shutil.copy2(db_path, dest_in_repo)
    repo.index.add([db_name])

    try:
        has_head = bool(repo.head.commit)
    except Exception:
        has_head = False

    has_changes = bool(repo.index.diff("HEAD")) if has_head else True

    if has_changes:
        commit = repo.index.commit(f"{message} [agent:{agent_id}]")
        commit_id = commit.hexsha
        logger.info(f"Git 提交完成，Commit ID: {commit_id}")
    else:
        commit_id = repo.head.commit.hexsha
        logger.info(f"无变更，当前 Commit ID: {commit_id}")

    # 4. 写入 snapshots/index.json
    index_path = os.path.join(snapshots_dir, "index.json")
    index_data = []
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except Exception:
            index_data = []

    index_data.append({
        "commit_id": commit_id,
        "timestamp": time.time(),
        "agent_id": agent_id,
        "message": message,
        "db_name": db_name,
    })

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    logger.info(f"快照索引已更新: {index_path}")

    return commit_id


def rollback(commit_id: str) -> None:
    """
    按 Commit ID 回滚 AgentFS 数据库到历史版本
    """
    config = get_config()
    db_path = config.harness.agentfs.db_path
    git_repo_path = config.harness.agentfs.git_repo_path

    repo = Repo(git_repo_path)
    try:
        commit = repo.commit(commit_id)
    except Exception as e:
        raise RuntimeError(f"无效的 Commit ID: {commit_id}") from e

    db_name = os.path.basename(db_path)
    blob = commit.tree / db_name
    content = blob.data_stream.read()

    with open(db_path, "wb") as f:
        f.write(content)

    logger.info(f"AgentFS 已回滚到 Commit: {commit_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentFS 快照工具")
    parser.add_argument("--agent-id", required=True, help="Agent ID")
    parser.add_argument("--message", required=True, help="提交说明")
    parser.add_argument("--rollback", default=None, help="回滚到指定 Commit ID")
    args = parser.parse_args()

    if args.rollback:
        rollback(args.rollback)
    else:
        cid = snapshot(args.agent_id, args.message)
        print(f"Snapshot Commit ID: {cid}")
