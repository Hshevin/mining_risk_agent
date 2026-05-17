"""
模型训练启动脚本
处理 PYTHONPATH 并执行训练
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from _bootstrap import setup_project_paths

setup_project_paths()

from mining_risk_train.train import train_and_save
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    logger.info("启动模型训练...")
    train_and_save()
