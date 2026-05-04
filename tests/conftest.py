"""
pytest 配置
添加项目根目录到 sys.path
"""

import os
import sys

# 测试环境使用占位 Key，避免配置校验在收集阶段失败
os.environ.setdefault("GLM5_API_KEY", "test-key")

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_root = os.path.dirname(project_root)

if parent_root not in sys.path:
    sys.path.insert(0, parent_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
