"""
灰度发布流量控制
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)

CANARY_RATIOS = [0.0, 0.1, 0.5, 1.0]


@dataclass
class TrafficRecord:
    timestamp: float
    model_version: str
    ratio: float
    operator: str
    note: str = ""


class CanaryDeployment:
    """
    灰度发布控制器
    """

    def __init__(self, config_path: str = "canary_config.json"):
        self.config_path = config_path
        self._traffic_log: List[TrafficRecord] = []
        self._load_config()

    def _load_config(self) -> None:
        """加载配置"""
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._traffic_log = [
                    TrafficRecord(**r) for r in data.get("traffic_log", [])
                ]
        else:
            self._traffic_log = []

    def _save_config(self) -> None:
        """保存配置"""
        data = {
            "traffic_log": [
                {
                    "timestamp": r.timestamp,
                    "model_version": r.model_version,
                    "ratio": r.ratio,
                    "operator": r.operator,
                    "note": r.note,
                }
                for r in self._traffic_log
            ],
            "updated_at": time.time(),
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_current_ratio(self, model_version: str) -> float:
        """获取当前流量比例"""
        for r in reversed(self._traffic_log):
            if r.model_version == model_version:
                return r.ratio
        return 0.0

    def set_traffic_ratio(
        self,
        model_version: str,
        ratio: float,
        operator: str = "system",
        note: str = "",
    ) -> Dict:
        """
        设置流量比例
        ratio 支持 0.0 -> 0.1 -> 0.5 -> 1.0 阶梯切换
        """
        if ratio not in CANARY_RATIOS:
            raise ValueError(f"比例必须是 {CANARY_RATIOS} 之一")

        current = self.get_current_ratio(model_version)
        if ratio < current and ratio != 0.0:
            logger.warning(f"流量比例降级: {current} -> {ratio}")

        record = TrafficRecord(
            timestamp=time.time(),
            model_version=model_version,
            ratio=ratio,
            operator=operator,
            note=note,
        )
        self._traffic_log.append(record)
        self._save_config()

        logger.info(f"灰度流量切换: {model_version} {current} -> {ratio} (by {operator})")
        return {
            "model_version": model_version,
            "previous_ratio": current,
            "current_ratio": ratio,
            "operator": operator,
            "timestamp": record.timestamp,
        }

    def get_traffic_history(self, model_version: Optional[str] = None) -> List[Dict]:
        """获取流量切换日志"""
        records = self._traffic_log
        if model_version:
            records = [r for r in records if r.model_version == model_version]
        return [
            {
                "timestamp": r.timestamp,
                "model_version": r.model_version,
                "ratio": r.ratio,
                "operator": r.operator,
                "note": r.note,
            }
            for r in records
        ]

    def promote(self, model_version: str, operator: str = "system") -> Dict:
        """
        自动晋升到下一级流量比例
        """
        current = self.get_current_ratio(model_version)
        idx = CANARY_RATIOS.index(current)
        if idx + 1 < len(CANARY_RATIOS):
            next_ratio = CANARY_RATIOS[idx + 1]
            return self.set_traffic_ratio(model_version, next_ratio, operator, note="auto_promote")
        return {
            "model_version": model_version,
            "previous_ratio": current,
            "current_ratio": current,
            "message": "已是最大流量比例",
        }

    def rollback(self, model_version: str, operator: str = "system") -> Dict:
        """
        回滚流量到 0
        """
        return self.set_traffic_ratio(model_version, 0.0, operator, note="rollback")
