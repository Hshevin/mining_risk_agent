"""
pytest 配置
添加项目根目录到 sys.path
"""

import os
import sys
import tempfile

# 测试环境使用占位 Key，避免配置校验在收集阶段失败
os.environ.setdefault("GLM5_API_KEY", "test-key")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_root = os.path.dirname(project_root)

if parent_root not in sys.path:
    sys.path.insert(0, parent_root)
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
