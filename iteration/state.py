"""Persistent iteration state records for replay and dashboard APIs."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


TRIGGER_REASON_RISK_SAMPLES = "RISK_SAMPLE_THRESHOLD_EXCEEDED"
TRIGGER_REASON_PERFORMANCE = "PERFORMANCE_DEGRADED"


def utc_now_iso() -> str:
    """Return an ISO timestamp that sorts lexicographically in SQLite."""

    return datetime.now(timezone.utc).isoformat()


def build_iteration_id(batch_id: str, timestamp: Optional[float] = None) -> str:
    """Build a stable, readable id for one data-ingestion iteration run."""

    millis = int((timestamp or time.time()) * 1000)
    return f"iter_{batch_id}_{millis}"


@dataclass
class TimelineEvent:
    """One frontend-friendly iteration timeline event."""

    event: str
    status: str
    timestamp: str
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineEvent":
        return cls(
            event=str(data["event"]),
            status=str(data.get("status", "")),
            timestamp=str(data.get("timestamp", "")),
            message=str(data.get("message", "")),
            details=dict(data.get("details", {})),
        )


@dataclass
class IterationRecord:
    """Unified model-iteration status after a data batch is ingested."""

    iteration_id: str
    batch_id: str
    data_source: Dict[str, Any]
    sample_count: int
    risk_sample_count: int
    recent_f1: float
    trigger_threshold_samples: int
    trigger_threshold_f1: float
    triggered: bool
    trigger_reasons: List[str]
    current_status: str
    timeline: List[TimelineEvent]
    report_path: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def batch(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "data_source": self.data_source,
            "sample_count": self.sample_count,
            "risk_sample_count": self.risk_sample_count,
            "recent_f1": self.recent_f1,
        }

    @property
    def thresholds(self) -> Dict[str, Any]:
        return {
            "risk_sample_count": self.trigger_threshold_samples,
            "recent_f1": self.trigger_threshold_f1,
        }

    @property
    def next_actions(self) -> List[Dict[str, Any]]:
        configured_actions = self.metadata.get("next_actions")
        if isinstance(configured_actions, list):
            return configured_actions

        if not self.triggered:
            return [
                {
                    "action": "MONITOR_NEXT_BATCH",
                    "label": "Monitor next batch",
                    "enabled": True,
                }
            ]

        status = self.current_status.upper()
        if self.metadata.get("audit_archive_path") and status in {
            "REGRESSION_BLOCKED",
            "DRIFT_BLOCKED",
            "CI_FAILED",
            "PRODUCTION_RELEASED",
        }:
            return [
                {
                    "action": "VIEW_AUDIT",
                    "label": "View audit archive",
                    "enabled": True,
                }
            ]
        enabled_by_status = {
            "TRAINING_PENDING": ("START_TRAINING", "Train candidate model"),
            "REGRESSION_PENDING": ("RUN_REGRESSION", "Run regression test"),
            "DRIFT_PENDING": ("RUN_DRIFT_ANALYSIS", "Run drift analysis"),
            "PR_PENDING": ("CREATE_PR", "Create local PR metadata"),
            "CI_PENDING": ("RUN_CI_PRECHECK", "Run CI precheck"),
            "CI_FAILED": ("ARCHIVE_AUDIT", "Archive blocked audit"),
            "APPROVAL_PENDING": ("APPROVE_SAFETY", "Safety approval"),
            "SAFETY_APPROVED": ("APPROVE_TECH", "Technical approval"),
            "STAGING_PENDING": ("START_STAGING", "Start staging"),
            "STAGING_RUNNING": ("COMPLETE_STAGING_DEMO", "Complete demo staging"),
            "CANARY_READY": ("ADVANCE_CANARY", "Advance canary"),
            "CANARY_RUNNING": ("ADVANCE_CANARY", "Advance canary"),
            "REGRESSION_BLOCKED": ("ARCHIVE_AUDIT", "Archive blocked audit"),
            "DRIFT_BLOCKED": ("ARCHIVE_AUDIT", "Archive blocked audit"),
            "PRODUCTION_RELEASED": ("ARCHIVE_AUDIT", "Archive audit"),
        }
        enabled = enabled_by_status.get(status)
        action_order = [
            ("START_TRAINING", "Train candidate model"),
            ("RUN_REGRESSION", "Run regression test"),
            ("RUN_DRIFT_ANALYSIS", "Run drift analysis"),
            ("CREATE_PR", "Create local PR metadata"),
            ("RUN_CI_PRECHECK", "Run CI precheck"),
            ("APPROVE_SAFETY", "Safety approval"),
            ("APPROVE_TECH", "Technical approval"),
            ("START_STAGING", "Start staging"),
            ("COMPLETE_STAGING_DEMO", "Complete demo staging"),
            ("ADVANCE_CANARY", "Advance canary"),
            ("ARCHIVE_AUDIT", "Archive audit"),
        ]
        return [
            {
                "action": action,
                "label": label,
                "enabled": bool(enabled and enabled[0] == action),
            }
            for action, label in action_order
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration_id": self.iteration_id,
            "batch_id": self.batch_id,
            "data_source": self.data_source,
            "batch": self.batch,
            "sample_count": self.sample_count,
            "risk_sample_count": self.risk_sample_count,
            "recent_f1": self.recent_f1,
            "trigger_threshold_samples": self.trigger_threshold_samples,
            "trigger_threshold_f1": self.trigger_threshold_f1,
            "thresholds": self.thresholds,
            "triggered": self.triggered,
            "retrain_required": self.triggered,
            "trigger_reasons": self.trigger_reasons,
            "current_status": self.current_status,
            "timeline": [event.to_dict() for event in self.timeline],
            "report_path": self.report_path,
            "next_actions": self.next_actions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "demo_mode": self.metadata.get("demo_mode", False),
            "training_report": self.metadata.get("training_report"),
            "training_report_path": self.metadata.get("training_report_path"),
            "candidate_model_path": self.metadata.get("candidate_model_path"),
            "model_version": self.metadata.get("model_version"),
            "regression_report": self.metadata.get("regression_report"),
            "regression_report_path": self.metadata.get("regression_report_path"),
            "drift_report": self.metadata.get("drift_report"),
            "drift_report_path": self.metadata.get("drift_report_path"),
            "pr_metadata": self.metadata.get("pr_metadata"),
            "pr_metadata_path": self.metadata.get("pr_metadata_path"),
            "local_pr_metadata_path": self.metadata.get("local_pr_metadata_path"),
            "ci_report": self.metadata.get("ci_report"),
            "ci_report_path": self.metadata.get("ci_report_path"),
            "approval_logs": self.metadata.get("approval_logs", []),
            "staging_report": self.metadata.get("staging_report"),
            "staging_report_path": self.metadata.get("staging_report_path"),
            "canary_percentage": self.metadata.get("canary_percentage", 0.0),
            "canary_events": self.metadata.get("canary_events", []),
            "audit_archive_path": self.metadata.get("audit_archive_path"),
            "blocked_reason": self.metadata.get("blocked_reason"),
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "IterationRecord":
        row_keys = row.keys()
        return cls(
            iteration_id=row["iteration_id"],
            batch_id=row["batch_id"],
            data_source=json.loads(row["data_source_json"]),
            sample_count=int(row["sample_count"]),
            risk_sample_count=int(row["risk_sample_count"]),
            recent_f1=float(row["recent_f1"]),
            trigger_threshold_samples=int(row["trigger_threshold_samples"]),
            trigger_threshold_f1=float(row["trigger_threshold_f1"]),
            triggered=bool(row["triggered"]),
            trigger_reasons=json.loads(row["trigger_reasons_json"] or "[]"),
            current_status=row["current_status"],
            timeline=[
                TimelineEvent.from_dict(item)
                for item in json.loads(row["timeline_json"] or "[]")
            ],
            report_path=row["report_path"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata_json"] or "{}")
            if "metadata_json" in row_keys
            else {},
        )


@dataclass
class IterationState:
    """Current state snapshot for APIs that need the latest record."""

    current_status: str
    latest_iteration_id: Optional[str] = None
    latest_record: Optional[IterationRecord] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_status": self.current_status,
            "latest_iteration_id": self.latest_iteration_id,
            "latest_record": self.latest_record.to_dict() if self.latest_record else None,
        }


class IterationStateStore:
    """SQLite repository for iteration records."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS iteration_records (
                iteration_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                data_source_json TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                risk_sample_count INTEGER NOT NULL,
                recent_f1 REAL NOT NULL,
                trigger_threshold_samples INTEGER NOT NULL,
                trigger_threshold_f1 REAL NOT NULL,
                triggered INTEGER NOT NULL,
                trigger_reasons_json TEXT NOT NULL,
                current_status TEXT NOT NULL,
                timeline_json TEXT NOT NULL,
                report_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute("PRAGMA table_info(iteration_records)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "metadata_json" not in columns:
            cursor.execute(
                "ALTER TABLE iteration_records ADD COLUMN metadata_json TEXT DEFAULT '{}'"
            )
        if "archived" not in columns:
            cursor.execute(
                "ALTER TABLE iteration_records ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
            )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_iteration_records_updated_at
            ON iteration_records(updated_at)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_iteration_records_batch_updated
            ON iteration_records(batch_id, updated_at)
            """
        )
        conn.commit()
        conn.close()

    def save_record(self, record: IterationRecord) -> IterationRecord:
        self.ensure_tables()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO iteration_records
            (iteration_id, batch_id, data_source_json, sample_count, risk_sample_count,
             recent_f1, trigger_threshold_samples, trigger_threshold_f1, triggered,
             trigger_reasons_json, current_status, timeline_json, report_path,
             created_at, updated_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(iteration_id) DO UPDATE SET
                batch_id=excluded.batch_id,
                data_source_json=excluded.data_source_json,
                sample_count=excluded.sample_count,
                risk_sample_count=excluded.risk_sample_count,
                recent_f1=excluded.recent_f1,
                trigger_threshold_samples=excluded.trigger_threshold_samples,
                trigger_threshold_f1=excluded.trigger_threshold_f1,
                triggered=excluded.triggered,
                trigger_reasons_json=excluded.trigger_reasons_json,
                current_status=excluded.current_status,
                timeline_json=excluded.timeline_json,
                report_path=excluded.report_path,
                updated_at=excluded.updated_at,
                metadata_json=excluded.metadata_json
            """,
            (
                record.iteration_id,
                record.batch_id,
                json.dumps(record.data_source, ensure_ascii=False),
                record.sample_count,
                record.risk_sample_count,
                record.recent_f1,
                record.trigger_threshold_samples,
                record.trigger_threshold_f1,
                int(record.triggered),
                json.dumps(record.trigger_reasons, ensure_ascii=False),
                record.current_status,
                json.dumps([event.to_dict() for event in record.timeline], ensure_ascii=False),
                record.report_path,
                record.created_at,
                record.updated_at,
                json.dumps(record.metadata, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
        return record

    def get_record(self, iteration_id: str) -> Optional[IterationRecord]:
        self.ensure_tables()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM iteration_records WHERE iteration_id = ?",
            (iteration_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return IterationRecord.from_row(row) if row else None

    def get_latest_record(self) -> Optional[IterationRecord]:
        self.ensure_tables()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM iteration_records
            WHERE COALESCE(archived, 0) = 0
            ORDER BY updated_at DESC, iteration_id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        conn.close()
        return IterationRecord.from_row(row) if row else None

    def get_latest_for_batch(self, batch_id: str) -> Optional[IterationRecord]:
        self.ensure_tables()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM iteration_records
            WHERE batch_id = ?
              AND COALESCE(archived, 0) = 0
            ORDER BY updated_at DESC, iteration_id DESC
            LIMIT 1
            """,
            (batch_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return IterationRecord.from_row(row) if row else None

    def get_state(self) -> IterationState:
        latest = self.get_latest_record()
        return IterationState(
            current_status=latest.current_status if latest else "IDLE",
            latest_iteration_id=latest.iteration_id if latest else None,
            latest_record=latest,
        )

    def archive_active_records(self, *, reason: str = "demo reset") -> int:
        """Hide current demo records from latest-status APIs without deleting audit history."""

        self.ensure_tables()
        conn = self._get_conn()
        cursor = conn.cursor()
        now = utc_now_iso()
        cursor.execute(
            """
            SELECT * FROM iteration_records
            WHERE COALESCE(archived, 0) = 0
            """
        )
        rows = cursor.fetchall()
        archived_count = 0
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata.update(
                {
                    "archived": True,
                    "archived_at": now,
                    "archive_reason": reason,
                    "status_before_archive": row["current_status"],
                }
            )
            cursor.execute(
                """
                UPDATE iteration_records
                SET archived = 1,
                    current_status = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE iteration_id = ?
                """,
                (
                    "DEMO_RESET_ARCHIVED",
                    now,
                    json.dumps(metadata, ensure_ascii=False),
                    row["iteration_id"],
                ),
            )
            archived_count += 1
        conn.commit()
        conn.close()
        return archived_count


def build_timeline(
    *,
    batch_id: str,
    triggered: bool,
    trigger_reasons: List[str],
    thresholds: Dict[str, Any],
    observed: Dict[str, Any],
    timestamp: str,
    blocked_gates: Optional[List[str]] = None,
) -> List[TimelineEvent]:
    blocked_gates = blocked_gates or []
    timeline = [
        TimelineEvent(
            event="DATA_INGESTED",
            status="COMPLETED",
            timestamp=timestamp,
            message="Demo batch data ingested",
            details={"batch_id": batch_id, **observed},
        ),
        TimelineEvent(
            event="TRIGGER_CHECKED",
            status="COMPLETED",
            timestamp=timestamp,
            message="Retraining trigger rules evaluated",
            details={
                "triggered": triggered,
                "trigger_reasons": trigger_reasons,
                "thresholds": thresholds,
            },
        ),
    ]

    if triggered:
        timeline.append(
            TimelineEvent(
                event="TRAINING_PENDING",
                status="PENDING",
                timestamp=timestamp,
                message="Pending after trigger check",
                details={"batch_id": batch_id, "blocked_gates": blocked_gates},
            )
        )
    elif blocked_gates:
        for event, gate in (
            ("TRAINING_PENDING", None),
            ("REGRESSION_PENDING", "REGRESSION"),
            ("DRIFT_PENDING", "DRIFT"),
            ("PR_PENDING", None),
            ("CI_PENDING", None),
        ):
            if gate and gate in blocked_gates:
                status = "BLOCKED"
                message = f"{gate.title()} gate blocked release"
            else:
                status = "NOT_STARTED"
                message = "Not started because release gate is blocked"
            timeline.append(
                TimelineEvent(
                    event=event,
                    status=status,
                    timestamp=timestamp if status == "BLOCKED" else "",
                    message=message,
                    details={"batch_id": batch_id, "blocked_gates": blocked_gates},
                )
            )

    return timeline
