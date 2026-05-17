"""
模型训练启动脚本
处理 PYTHONPATH 并执行训练
"""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MINING_PROJECT_ROOT", project_root)
for name in ("mining_risk_common", "mining_risk_train", "mining_risk_serve"):
    src_root = os.path.join(project_root, "packages", name, "src")
    if src_root not in sys.path:
        sys.path.insert(0, src_root)

from mining_risk_train.train import train_and_save
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    logger.info("启动模型训练...")
    train_and_save()
