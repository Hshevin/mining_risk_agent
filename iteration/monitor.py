"""
模型监控模块
定时扫描数据库，监控新增样本数与模型性能，触发重训练信号
"""

import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)

SAMPLE_THRESHOLD = 5000
F1_THRESHOLD = 0.85


@dataclass
class TriggerSignal:
    """触发信号"""
    triggered: bool
    reason: Optional[str] = None
    details: Optional[Dict] = None


class ModelMonitor:
    """
    模型监控器
    - 监控新增样本数量
    - 监控近期模型性能（F1分数）
    - 输出是否应该重训练
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        sample_threshold: int = SAMPLE_THRESHOLD,
        f1_threshold: float = F1_THRESHOLD,
    ):
        config = get_config()
        # 使用 audit.db 作为默认监控数据库（兼容现有系统）
        self.db_path = db_path or config.audit.db_path
        self.sample_threshold = sample_threshold
        self.f1_threshold = f1_threshold
        self._ensure_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        """确保监控所需表存在"""
        conn = self._get_conn()
        cursor = conn.cursor()

        # 样本追踪表：记录每次新增的样本批次
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sample_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_time REAL NOT NULL,
                batch_size INTEGER NOT NULL,
                source TEXT,
                cumulative_count INTEGER NOT NULL
            )
        """)

        # 性能追踪表：记录每次模型评估指标
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_time REAL NOT NULL,
                model_version TEXT,
                accuracy REAL,
                precision REAL,
                recall REAL,
                f1_score REAL,
                auc REAL,
                dataset TEXT
            )
        """)

        conn.commit()
        conn.close()
        logger.info("监控表已初始化")

    def record_new_samples(self, batch_size: int, source: str = "api_upload") -> int:
        """
        记录新增样本批次，返回当前累计样本数
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # 查询当前累计数
        cursor.execute("SELECT cumulative_count FROM sample_tracking ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        prev_count = row["cumulative_count"] if row else 0
        new_count = prev_count + batch_size

        cursor.execute(
            "INSERT INTO sample_tracking (batch_time, batch_size, source, cumulative_count) VALUES (?, ?, ?, ?)",
            (time.time(), batch_size, source, new_count),
        )
        conn.commit()
        conn.close()

        logger.info(f"记录新增样本: +{batch_size}, 累计: {new_count}")
        return new_count

    def record_performance(
        self,
        model_version: str,
        accuracy: float,
        precision: float,
        recall: float,
        f1_score: float,
        auc: Optional[float] = None,
        dataset: str = "validation",
    ) -> None:
        """记录模型性能指标"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO performance_tracking
            (eval_time, model_version, accuracy, precision, recall, f1_score, auc, dataset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (time.time(), model_version, accuracy, precision, recall, f1_score, auc, dataset),
        )
        conn.commit()
        conn.close()
        logger.info(f"记录性能: model={model_version}, F1={f1_score:.4f}")

    def get_cumulative_sample_count(self) -> int:
        """获取累计新增样本数"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT cumulative_count FROM sample_tracking ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row["cumulative_count"] if row else 0

    def get_recent_f1_scores(self, window_days: int = 7) -> List[float]:
        """获取近期 F1 分数列表"""
        since = time.time() - window_days * 86400
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT f1_score FROM performance_tracking WHERE eval_time > ? ORDER BY eval_time DESC",
            (since,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [r["f1_score"] for r in rows if r["f1_score"] is not None]

    def check_sample_threshold(self) -> TriggerSignal:
        """检查样本数阈值"""
        count = self.get_cumulative_sample_count()
        if count > self.sample_threshold:
            return TriggerSignal(
                triggered=True,
                reason="SAMPLE_THRESHOLD_EXCEEDED",
                details={"cumulative_samples": count, "threshold": self.sample_threshold},
            )
        return TriggerSignal(triggered=False)

    def check_performance_threshold(self) -> TriggerSignal:
        """检查性能阈值"""
        f1_scores = self.get_recent_f1_scores(window_days=7)
        if not f1_scores:
            return TriggerSignal(triggered=False)

        recent_f1 = sum(f1_scores) / len(f1_scores)
        if recent_f1 < self.f1_threshold:
            return TriggerSignal(
                triggered=True,
                reason="PERFORMANCE_DEGRADED",
                details={"recent_f1": round(recent_f1, 4), "threshold": self.f1_threshold, "count": len(f1_scores)},
            )
        return TriggerSignal(triggered=False)

    def should_retrain(self) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        判断是否应该触发重训练

        Returns:
            (should_retrain, trigger_reason, details)
        """
        sample_check = self.check_sample_threshold()
        if sample_check.triggered:
            logger.warning(f"触发重训练信号: {sample_check.reason}")
            return True, sample_check.reason, sample_check.details

        perf_check = self.check_performance_threshold()
        if perf_check.triggered:
            logger.warning(f"触发重训练信号: {perf_check.reason}")
            return True, perf_check.reason, perf_check.details

        return False, None, None

    def get_monitoring_summary(self) -> Dict:
        """获取监控摘要"""
        count = self.get_cumulative_sample_count()
        f1_scores = self.get_recent_f1_scores(window_days=7)
        recent_f1 = round(sum(f1_scores) / len(f1_scores), 4) if f1_scores else None

        return {
            "cumulative_samples": count,
            "sample_threshold": self.sample_threshold,
            "sample_triggered": count > self.sample_threshold,
            "recent_f1": recent_f1,
            "f1_threshold": self.f1_threshold,
            "performance_triggered": (recent_f1 is not None and recent_f1 < self.f1_threshold),
            "timestamp": datetime.now().isoformat(),
        }
