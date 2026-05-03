"""
AgentFS 虚拟文件系统单元测试
覆盖：写读删、越界拦截、POSIX接口(ls/stat)、快照生成、版本回滚
"""

import os
import shutil
import tempfile

import pytest

from harness.agentfs import AgentFS, FileStat


class TestAgentFS:
    """测试 AgentFS 虚拟文件系统"""

    def test_write_read_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            fs.write("knowledge_base/test/file.txt", b"hello world")
            content = fs.read("knowledge_base/test/file.txt")
            assert content == b"hello world"

            fs.delete("knowledge_base/test/file.txt")
            assert not fs.exists("knowledge_base/test/file.txt")

    def test_ls_and_stat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            fs.write("knowledge_base/a.txt", b"a", agent_id="test_agent", mode="600")
            fs.write("knowledge_base/b.txt", b"bb", agent_id="test_agent")
            fs.write("memory/log.txt", b"log", owner="system")

            # ls 根目录
            all_files = fs.ls("/")
            assert len(all_files) == 3

            # ls 子目录
            kb_files = fs.ls("knowledge_base")
            assert len(kb_files) == 2

            # stat 单文件
            stat = fs.stat("knowledge_base/a.txt")
            assert isinstance(stat, FileStat)
            assert stat.path == "/knowledge_base/a.txt"
            assert stat.size == 1
            assert stat.mode == "600"
            assert stat.owner == "agent"
            assert stat.agent_id == "test_agent"
            assert stat.checksum is not None

            stat_mem = fs.stat("memory/log.txt")
            assert stat_mem.owner == "system"

    def test_sandbox_violation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            # 非法根目录
            with pytest.raises(PermissionError):
                fs.write("/test.txt", b"illegal")
            with pytest.raises(PermissionError):
                fs.write("other/file.txt", b"illegal")
            with pytest.raises(PermissionError):
                fs.read("/foo.txt")
            with pytest.raises(PermissionError):
                fs.delete("/bar.txt")
            with pytest.raises(PermissionError):
                fs.stat("/baz.txt")

            # 合法根目录不应抛错
            fs.write("knowledge_base/ok.txt", b"ok")
            fs.write("memory/ok.txt", b"ok")

    def test_snapshot_and_rollback(self):
        tmpdir = tempfile.mkdtemp()
        try:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            fs.write("knowledge_base/data.txt", b"version1")
            commit1 = fs.snapshot("first", agent_id="test")
            fs.write("knowledge_base/data.txt", b"version2")
            commit2 = fs.snapshot("second", agent_id="test")

            # 回滚到版本1
            fs.rollback(commit1)
            content = fs.read("knowledge_base/data.txt")
            assert content == b"version1"

            # 回滚到版本2
            fs.rollback(commit2)
            content = fs.read("knowledge_base/data.txt")
            assert content == b"version2"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_list_files_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            fs.write("memory/x.txt", b"x")
            files = fs.list_files("memory")
            assert len(files) == 1
            assert "path" in files[0]
            assert "size" in files[0]
            assert "updated_at" in files[0]
            assert "checksum" in files[0]

    def test_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fs = AgentFS(
                db_path=os.path.join(tmpdir, "test.db"),
                git_repo_path=os.path.join(tmpdir, "git"),
            )
            assert not fs.exists("knowledge_base/missing.txt")
            fs.write("knowledge_base/exists.txt", b"yes")
            assert fs.exists("knowledge_base/exists.txt")
