"""
模型训练启动脚本
处理 PYTHONPATH 并执行训练
"""

import os
import sys

# 将项目根目录加入路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_root = os.path.dirname(project_root)
if parent_root not in sys.path:
    sys.path.insert(0, parent_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from model.train import train_and_save
from utils.logger import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    logger.info("启动模型训练...")
    train_and_save()
