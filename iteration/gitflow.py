"""
Git Flow 分支管理脚本
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import git
from git import Repo

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


class GitFlowManager:
    """
    Git Flow 分支管理器
    """

    def __init__(self, repo_path: Optional[str] = None):
        config = get_config()
        self.repo_path = repo_path or "."
        self.main_branch = config.harness.model_iteration.git_flow.main_branch
        self.dev_branch = config.harness.model_iteration.git_flow.dev_branch
        self.feature_prefix = config.harness.model_iteration.git_flow.feature_branch_prefix
        self._ensure_repo()

    def _ensure_repo(self) -> None:
        """确保是 Git 仓库"""
        git_dir = os.path.join(self.repo_path, ".git")
        if not os.path.exists(git_dir):
            Repo.init(self.repo_path)
            logger.info(f"Git 仓库已初始化: {self.repo_path}")

    def _repo(self) -> Repo:
        return Repo(self.repo_path)

    def _run_git(self, args: List[str]) -> str:
        """执行 Git 命令"""
        result = subprocess.run(
            ["git", "-C", self.repo_path] + args,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"Git 命令失败: {result.stderr}")
            raise RuntimeError(f"Git 命令失败: {result.stderr}")
        return result.stdout.strip()

    def create_feature_branch(self, model_version: str) -> str:
        """
        从 main 创建 feature 分支
        分支名格式: feature/model_v{x}
        """
        branch_name = f"{self.feature_prefix}model_{model_version}"

        # 确保 main 分支存在
        repo = self._repo()
        if self.main_branch not in [h.name for h in repo.heads]:
            # 若 main 不存在，从当前分支创建
            if repo.heads:
                repo.create_head(self.main_branch)
            else:
                # 完全新仓库，创建初始提交
                repo.index.commit("Initial commit")
                repo.create_head(self.main_branch)

        self._run_git(["checkout", self.main_branch])
        self._run_git(["checkout", "-b", branch_name])
        logger.info(f"创建特性分支: {branch_name} (基于 {self.main_branch})")
        return branch_name

    def generate_pr_template(
        self,
        old_metrics: Dict[str, float],
        new_metrics: Dict[str, float],
        shap_stability: Optional[float] = None,
    ) -> str:
        """
        自动生成 PR 描述，含新旧模型性能对比
        """
        def _fmt(key: str) -> str:
            old_v = old_metrics.get(key, 0.0)
            new_v = new_metrics.get(key, 0.0)
            delta = new_v - old_v
            sign = "+" if delta >= 0 else ""
            return f"{old_v:.4f} → {new_v:.4f} ({sign}{delta:.4f})"

        lines = [
            "## 模型迭代 PR",
            "",
            "### 性能对比",
            "",
            f"| 指标 | 旧模型 | 新模型 | 变化 |",
            f"|------|--------|--------|------|",
            f"| 准确率 (Accuracy) | {_fmt('test_accuracy')} |",
            f"| 精确率 (Precision) | {_fmt('test_precision')} |",
            f"| 召回率 (Recall) | {_fmt('test_recall')} |",
            f"| F1 分数 (Macro) | {_fmt('test_f1')} |",
            f"| AUC | {_fmt('test_auc')} |",
            "",
        ]

        if shap_stability is not None:
            status = "稳定" if shap_stability >= 0.8 else "需关注"
            lines.extend([
                "### SHAP 稳定性",
                f"- Kendall Tau 相关性: {shap_stability:.4f} ({status})",
                "",
            ])

        lines.extend([
            "### 检查清单",
            "- [ ] 回归测试通过",
            "- [ ] Drift 分析通过",
            "- [ ] 两级审批完成",
            "",
        ])

        return "\n".join(lines)

    def protect_main_branch(self) -> None:
        """
        配置分支保护规则脚本
        禁止直接推送，强制 PR 审核
        """
        hook_path = os.path.join(self.repo_path, ".git", "hooks", "pre-push")
        hook_content = """#!/bin/sh
# 分支保护钩子：禁止直接推送 main
protected_branch="main"
remote="$1"
url="$2"

while read local_ref local_sha remote_ref remote_sha
do
    if [ "$remote_ref" = "refs/heads/$protected_branch" ]; then
        echo "ERROR: 禁止直接推送 $protected_branch 分支，请通过 Pull Request 合并"
        exit 1
    fi
done

exit 0
"""
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write(hook_content)

        # Windows 下无 exec 权限概念，但仍尝试设置
        try:
            os.chmod(hook_path, 0o755)
        except Exception:
            pass

        logger.info(f"主分支保护规则已配置: {hook_path}")

    def commit_changes(self, message: str, files: Optional[List[str]] = None) -> str:
        """提交变更"""
        repo = self._repo()
        if files:
            repo.index.add(files)
        else:
            repo.index.add(["."])
        commit = repo.index.commit(message)
        return commit.hexsha
