"""
pytest 配置
安装 workspace 包后运行测试；本地未安装时回退到 packages/*/src。
"""

import os
import sys
import tempfile

# 测试环境使用占位 Key，避免配置校验在收集阶段失败
os.environ.setdefault("GLM5_API_KEY", "test-key")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MINING_PROJECT_ROOT", project_root)

package_src_roots = [
    os.path.join(project_root, "packages", name, "src")
    for name in (
        "mining_risk_common",
        "mining_risk_serve",
        "mining_risk_train",
        "mining_risk_compat",
    )
]
for src_root in reversed(package_src_roots):
    if src_root not in sys.path:
        sys.path.insert(0, src_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


if os.name == "nt":
    def _sandbox_safe_mkdtemp(suffix=None, prefix=None, dir=None):
        """Create Windows temp dirs without the 0o700 DACL that blocks nested writes here."""
        prefix, suffix, dir, output_type = tempfile._sanitize_params(prefix, suffix, dir)
        names = tempfile._get_candidate_names()
        if output_type is bytes:
            names = map(os.fsencode, names)

        for _ in range(tempfile.TMP_MAX):
            name = next(names)
            path = os.path.abspath(os.path.join(dir, prefix + name + suffix))
            try:
                os.mkdir(path)
            except FileExistsError:
                continue
            return path

        raise FileExistsError(
            tempfile._errno.EEXIST,
            "No usable temporary directory name found",
        )

    tempfile.mkdtemp = _sandbox_safe_mkdtemp
