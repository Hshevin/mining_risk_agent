"""Pluggable enterprise data sources for model iteration."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.config import get_config, resolve_project_path


REQUIRED_METADATA_FIELDS = {
    "batch_id",
    "sample_count",
    "risk_sample_count",
    "recent_f1",
    "description",
}


@dataclass(frozen=True)
class BatchMetadata:
    """Metadata shared by demo and future real enterprise batches."""

    batch_id: str
    sample_count: int
    risk_sample_count: int
    recent_f1: float
    description: str
    scenario: str = "unspecified"
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchMetadata":
        missing = REQUIRED_METADATA_FIELDS - set(data)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"batch metadata missing required fields: {missing_text}")
        return cls(
            batch_id=str(data["batch_id"]),
            sample_count=int(data["sample_count"]),
            risk_sample_count=int(data["risk_sample_count"]),
            recent_f1=float(data["recent_f1"]),
            description=str(data["description"]),
            scenario=str(data.get("scenario", "unspecified")),
            tags=list(data.get("tags", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnterpriseDataBatch:
    """A loaded enterprise data batch."""

    metadata: BatchMetadata
    records: List[Dict[str, Any]] = field(default_factory=list)
    gates: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"

    def to_dict(self, include_records: bool = True) -> Dict[str, Any]:
        payload = {
            "metadata": self.metadata.to_dict(),
            "gates": self.gates,
            "source": self.source,
            "record_count": len(self.records),
        }
        if include_records:
            payload["records"] = self.records
        return payload


class EnterpriseDataSource(ABC):
    """Replaceable source boundary for iteration batches."""

    name: str

    @abstractmethod
    def list_batches(self) -> List[BatchMetadata]:
        """Return available batch metadata without loading the full records."""

    @abstractmethod
    def load_batch(self, batch_id: str) -> EnterpriseDataBatch:
        """Load one batch by id."""

    def describe(self) -> Dict[str, Any]:
        return {"type": self.name}


class DemoReplayDataSource(EnterpriseDataSource):
    """Read replayable demo batches from local JSON files under data/demo."""

    name = "demo_replay"

    def __init__(self, demo_dir: Optional[str | Path] = None):
        config = get_config()
        configured_dir = getattr(config.iteration.data_source, "demo_dir", "data/demo")
        self.demo_dir = resolve_project_path(demo_dir or configured_dir)

    def describe(self) -> Dict[str, Any]:
        return {
            "type": self.name,
            "demo_dir": str(self.demo_dir),
            "replaceable_with": "database or streaming enterprise data source",
        }

    def _iter_batch_files(self) -> List[Path]:
        if not self.demo_dir.exists():
            return []
        return sorted(self.demo_dir.glob("*.json"))

    def _read_file(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"demo batch must be a JSON object: {path}")
        return data

    def _batch_from_file(self, path: Path) -> EnterpriseDataBatch:
        data = self._read_file(path)
        metadata = BatchMetadata.from_dict(data.get("metadata", {}))
        records = data.get("records", [])
        if not isinstance(records, list):
            raise ValueError(f"records must be a list: {path}")
        gates = data.get("gates", {})
        if not isinstance(gates, dict):
            raise ValueError(f"gates must be an object: {path}")
        return EnterpriseDataBatch(
            metadata=metadata,
            records=records,
            gates=gates,
            source=f"{self.name}:{path.name}",
        )

    def list_batches(self) -> List[BatchMetadata]:
        batches = [self._batch_from_file(path).metadata for path in self._iter_batch_files()]
        return sorted(batches, key=lambda item: item.batch_id)

    def load_batch(self, batch_id: str) -> EnterpriseDataBatch:
        for path in self._iter_batch_files():
            batch = self._batch_from_file(path)
            if batch.metadata.batch_id == batch_id:
                return batch
        raise FileNotFoundError(f"demo batch not found: {batch_id}")


def build_enterprise_data_source(source_type: Optional[str] = None) -> EnterpriseDataSource:
    """Factory kept small so real DB-backed sources can be plugged in later."""

    config = get_config()
    configured_type = getattr(config.iteration.data_source, "type", "demo_replay")
    selected = (source_type or configured_type or "demo_replay").lower()
    if selected == "demo_replay":
        return DemoReplayDataSource()
    raise ValueError(f"unsupported enterprise data source: {selected}")
