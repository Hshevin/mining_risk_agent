"""
预生产 24 小时试运行监控
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from mining_risk_common.utils.config import get_config
from mining_risk_common.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StagingSample:
    timestamp: float
    latency_ms: float
    is_anomaly: bool
    confidence: float
    input_hash: str


class StagingMonitor:
    """
    预生产监控器
    - 每 5 分钟采样
    - 监控延迟、异常率、置信度分布、输入数据分布漂移
    """

    def __init__(
        self,
        model_version: str,
        duration_hours: int = 24,
        sample_interval_minutes: int = 5,
        logs_dir: str = "logs",
    ):
        config = get_config()
        self.model_version = model_version
        self.duration_hours = duration_hours
        self.sample_interval_seconds = sample_interval_minutes * 60
        self.logs_dir = logs_dir
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.samples: List[Dict] = []
        os.makedirs(logs_dir, exist_ok=True)

    def start(self) -> None:
        """启动预生产监控"""
        self.start_time = time.time()
        self.end_time = self.start_time + self.duration_hours * 3600
        logger.info(f"预生产监控启动: {self.model_version}, 持续 {self.duration_hours} 小时")

    def record_sample(
        self,
        latency_ms: float,
        is_anomaly: bool,
        confidence: float,
        input_features: Optional[Dict] = None,
    ) -> Dict:
        """
        记录一次采样（模拟每5分钟调用）
        """
        sample = {
            "timestamp": time.time(),
            "model_version": self.model_version,
            "latency_ms": latency_ms,
            "is_anomaly": bool(is_anomaly),
            "confidence": float(confidence),
            "input_hash": self._hash_input(input_features),
        }
        self.samples.append(sample)

        # 写入实时日志文件
        log_file = os.path.join(
            self.logs_dir,
            f"staging_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False, indent=2)

        return sample

    def _hash_input(self, features: Optional[Dict]) -> str:
        """简单哈希输入特征用于分布追踪"""
        if features is None:
            return ""
        import hashlib
        s = json.dumps(features, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(s.encode("utf-8")).hexdigest()[:8]

    def check_drift(self, window_size: int = 12) -> Dict:
        """
        检查输入数据分布漂移（简化：基于最近 window_size 个样本的置信度分布）
        """
        if len(self.samples) < window_size * 2:
            return {"drift_detected": False, "reason": "样本不足", "kl_divergence": 0.0}

        recent = self.samples[-window_size:]
        previous = self.samples[-window_size * 2:-window_size]

        recent_conf = [s["confidence"] for s in recent]
        prev_conf = [s["confidence"] for s in previous]

        # 简化：用均值差异作为漂移指标
        mean_diff = abs(np.mean(recent_conf) - np.mean(prev_conf))
        std_recent = np.std(recent_conf)
        threshold = max(std_recent * 2, 0.1)

        drift_detected = mean_diff > threshold
        return {
            "drift_detected": bool(drift_detected),
            "mean_diff": float(mean_diff),
            "threshold": float(threshold),
            "recent_mean": float(np.mean(recent_conf)),
            "previous_mean": float(np.mean(prev_conf)),
        }

    def generate_report(self) -> Dict:
        """
        生成 staging_report
        """
        if not self.samples:
            return {"status": "NO_DATA", "model_version": self.model_version}

        latencies = [s["latency_ms"] for s in self.samples]
        anomalies = [s["is_anomaly"] for s in self.samples]
        confidences = [s["confidence"] for s in self.samples]

        anomaly_rate = sum(anomalies) / len(anomalies) if anomalies else 0.0
        drift = self.check_drift()

        # 判定是否有异常
        has_anomaly = (
            anomaly_rate > 0.05  # 异常率 > 5%
            or np.mean(latencies) > 1000  # 平均延迟 > 1s
            or drift["drift_detected"]
        )

        report = {
            "model_version": self.model_version,
            "start_time": self.start_time,
            "end_time": time.time(),
            "total_samples": len(self.samples),
            "latency": {
                "mean_ms": float(np.mean(latencies)),
                "p99_ms": float(np.percentile(latencies, 99)),
                "max_ms": float(np.max(latencies)),
            },
            "anomaly_rate": float(anomaly_rate),
            "confidence_distribution": {
                "mean": float(np.mean(confidences)),
                "std": float(np.std(confidences)),
                "min": float(np.min(confidences)),
                "max": float(np.max(confidences)),
            },
            "drift_analysis": drift,
            "has_anomaly": bool(has_anomaly),
            "status": "CANARY_READY" if not has_anomaly else "ROLLBACK",
            "timestamp": time.time(),
        }

        report_path = os.path.join(self.logs_dir, f"staging_report_{self.model_version}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"预生产报告已生成: {report_path}, 状态: {report['status']}")
        return report

    def run_simulation(self, num_samples: int = 12) -> Dict:
        """
        模拟运行（用于测试）
        生成 num_samples 个随机采样，然后生成报告
        """
        self.start()
        for i in range(num_samples):
            latency = np.random.normal(200, 50)
            is_anomaly = np.random.random() < 0.02
            confidence = np.random.uniform(0.7, 0.99)
            self.record_sample(latency, is_anomaly, confidence)
        return self.generate_report()
