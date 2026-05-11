"""
日志工具模块
统一日志格式与输出策?"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

from utils.config import get_config


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    获取配置好的日志记录?    
    Args:
        name: 日志记录器名?        level: 日志级别，默认从配置读取
    
    Returns:
        配置好的 Logger 实例
    """
    config = get_config()
    log_level = level or config.logging.level
    log_format = config.logging.format
    log_file = config.logging.file

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 避免重复添加 Handler
    if logger.handlers:
        return logger

    # 控制台输
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_formatter = logging.Formatter(log_format)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 文件输出（按大小轮转
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=config.logging.max_bytes,
            backupCount=config.logging.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        file_formatter = logging.Formatter(log_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger
