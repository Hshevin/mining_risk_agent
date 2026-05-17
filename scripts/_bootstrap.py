"""为 scripts/ 下的入口脚本注入 monorepo 包路径（无需先 pip install -e）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PACKAGE_NAMES = (
    "mining_risk_common",
    "mining_risk_train",
    "mining_risk_serve",
    "mining_risk_compat",
)


def setup_project_paths() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    os.environ.setdefault("MINING_PROJECT_ROOT", str(project_root))
    for name in _PACKAGE_NAMES:
        src_root = project_root / "packages" / name / "src"
        if src_root.is_dir():
            path = str(src_root)
            if path not in sys.path:
                sys.path.insert(0, path)
    root = str(project_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    return project_root
