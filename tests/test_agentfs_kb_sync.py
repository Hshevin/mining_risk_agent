from pathlib import Path

from harness.agentfs import AgentFS
from harness.knowledge_base import KnowledgeBaseManager
from harness.vector_store import split_by_headers
from scripts.sync_kb_to_agentfs import (
    MAIN_KB_FILES,
    agentfs_manifest,
    compare_manifests,
    filesystem_manifest,
    get_paths,
    verify_agentfs_content,
)


def _enterprise_conditions_filename() -> str:
    return next(name for name in MAIN_KB_FILES if name.startswith("企业已具备"))


def test_main_kb_files_match_between_filesystem_and_agentfs():
    db_path, _, _, kb_dir = get_paths()

    verification = verify_agentfs_content(db_path, kb_dir)
    assert verification
    assert all(item["matches"] for item in verification)

    comparison = compare_manifests(
        filesystem_manifest(kb_dir),
        agentfs_manifest(db_path),
    )
    assert comparison["all_main_files_match"]


def test_enterprise_conditions_agentfs_is_new_large_version():
    db_path, git_repo_path, _, kb_dir = get_paths()
    filename = _enterprise_conditions_filename()

    fs_size = (kb_dir / filename).stat().st_size
    agentfs = AgentFS(db_path=str(db_path), git_repo_path=str(git_repo_path))
    stat = agentfs.stat(f"knowledge_base/{filename}")

    assert stat.size == fs_size
    assert stat.size > 50000
    assert stat.agent_id == "kb_sync"


def test_knowledge_base_manager_reads_synced_enterprise_sections():
    db_path, git_repo_path, _, _ = get_paths()
    filename = _enterprise_conditions_filename()
    manager = KnowledgeBaseManager(
        agentfs=AgentFS(db_path=str(db_path), git_repo_path=str(git_repo_path))
    )

    text = manager.read(filename)

    assert "## 4. 粉尘涉爆执行条件" in text
    assert "## 5. 冶金设备执行条件" in text
    assert "## 6. 危化品与重大危险源执行条件" in text
    assert "## 11. AgentFS 同步建议" in text


def test_vector_store_split_by_headers_uses_filesystem_version():
    _, _, _, kb_dir = get_paths()
    text = (kb_dir / _enterprise_conditions_filename()).read_text(encoding="utf-8")

    chunks = split_by_headers(text, max_chunk_size=500, overlap=80)
    titles = [chunk["metadata"]["section_title"] for chunk in chunks]

    assert len(chunks) >= 120
    assert any("粉尘涉爆执行条件" in title for title in titles)
    assert any("AgentFS 同步建议" in title for title in titles)


def test_malformed_agentfs_path_does_not_affect_six_kb_reads():
    db_path, git_repo_path, _, _ = get_paths()
    entries = agentfs_manifest(db_path)
    manager = KnowledgeBaseManager(
        agentfs=AgentFS(db_path=str(db_path), git_repo_path=str(git_repo_path))
    )

    assert any(entry.status_note == "deprecated_malformed_path" for entry in entries)

    for filename in MAIN_KB_FILES:
        text = manager.read(filename)
        assert text.strip()
        assert text.startswith("#")
