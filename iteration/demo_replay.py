"""Replay demo enterprise batches through the iteration trigger gates."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from iteration.data_source import (
    EnterpriseDataBatch,
    EnterpriseDataSource,
    build_enterprise_data_source,
)
from iteration.monitor import ModelMonitor
from iteration.state import (
    IterationRecord,
    IterationStateStore,
    TRIGGER_REASON_PERFORMANCE,
    TRIGGER_REASON_RISK_SAMPLES,
    build_iteration_id,
    build_timeline,
    utc_now_iso,
)
from utils.config import get_config, resolve_project_path
from utils.logger import get_logger


logger = get_logger(__name__)


class DemoReplayService:
    """Evaluate demo batches and leave a traceable backend replay record."""

    def __init__(
        self,
        data_source: Optional[EnterpriseDataSource] = None,
        db_path: Optional[str] = None,
        reports_dir: Optional[str | Path] = None,
        sample_threshold: Optional[int] = None,
        f1_threshold: Optional[float] = None,
    ):
        config = get_config()
        self.data_source = data_source or build_enterprise_data_source()
        configured_db_path = db_path or config.iteration.monitor.db_path or config.audit.db_path
        self.db_path = str(resolve_project_path(configured_db_path))
        configured_reports_dir = config.iteration.data_source.reports_dir
        self.reports_dir = resolve_project_path(reports_dir or configured_reports_dir)
        self.sample_threshold = sample_threshold or config.iteration.monitor.sample_threshold
        self.f1_threshold = f1_threshold or config.iteration.monitor.f1_threshold
        self.state_store = IterationStateStore(self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_replay_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                batch_id TEXT NOT NULL,
                status TEXT NOT NULL,
                retrain_required INTEGER NOT NULL,
                blocked INTEGER NOT NULL,
                trigger_reasons TEXT,
                blocked_gates TEXT,
                report_path TEXT,
                metadata_json TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute("PRAGMA table_info(demo_replay_runs)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "archived" not in columns:
            cursor.execute(
                "ALTER TABLE demo_replay_runs ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()
        conn.close()
        self.state_store.ensure_tables()

    def list_batches(self) -> List[Dict[str, Any]]:
        return [batch.to_dict() for batch in self.data_source.list_batches()]

    def load_batch(self, batch_id: str) -> EnterpriseDataBatch:
        return self.data_source.load_batch(batch_id)

    def evaluate_batch(self, batch: EnterpriseDataBatch) -> Dict[str, Any]:
        metadata = batch.metadata
        trigger_reasons: List[str] = []
        blocked_gates: List[str] = []

        if metadata.risk_sample_count > self.sample_threshold:
            trigger_reasons.append(TRIGGER_REASON_RISK_SAMPLES)
        if metadata.recent_f1 < self.f1_threshold:
            trigger_reasons.append(TRIGGER_REASON_PERFORMANCE)

        regression = batch.gates.get("regression", {})
        regression_status = str(regression.get("status", "PASS")).upper()
        if regression_status not in {"PASS", "PASSED", "OK"}:
            blocked_gates.append("REGRESSION")

        drift = batch.gates.get("drift", {})
        drift_risk = str(drift.get("risk_level", drift.get("status", "LOW"))).upper()
        if drift_risk in {"HIGH", "CRITICAL", "BLOCKED", "FAIL"}:
            blocked_gates.append("DRIFT")

        retrain_required = bool(trigger_reasons)
        blocked = bool(blocked_gates)
        if blocked:
            status = "BLOCKED"
        elif retrain_required:
            status = "RETRAIN_REQUIRED"
        else:
            status = "NO_RETRAIN"

        return {
            "status": status,
            "retrain_required": retrain_required,
            "blocked": blocked,
            "trigger_reasons": trigger_reasons,
            "blocked_gates": blocked_gates,
            "thresholds": {
                "risk_sample_threshold": self.sample_threshold,
                "trigger_threshold_samples": self.sample_threshold,
                "f1_threshold": self.f1_threshold,
                "trigger_threshold_f1": self.f1_threshold,
            },
            "gates": batch.gates,
        }

    def replay_batch(self, batch_id: str) -> Dict[str, Any]:
        self._ensure_tables()
        batch = self.load_batch(batch_id)
        monitor_details = self._record_monitor_inputs(batch)
        evaluation = self.evaluate_batch(batch)
        report = self._build_report(batch, evaluation)
        report["monitor"] = monitor_details
        report_path = self._write_report(report)
        report["report_path"] = str(report_path)
        iteration_record = self._record_iteration(batch, evaluation, report_path)
        report["iteration"] = iteration_record.to_dict()
        report["iteration_id"] = iteration_record.iteration_id
        self._write_report(report)
        self._record_run(batch, evaluation, report_path)
        logger.info(
            "demo replay batch=%s status=%s report=%s",
            batch.metadata.batch_id,
            evaluation["status"],
            report_path,
        )
        return report

    def record_uploaded_batch(
        self,
        *,
        metadata: "BatchMetadata",
        upload_path: Path,
        records_preview: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Persist one uploaded enterprise batch through the same iteration gates."""

        self._ensure_tables()
        batch = EnterpriseDataBatch(
            metadata=metadata,
            records=records_preview or [],
            gates={},
            source=f"upload_batch:{upload_path.name}",
        )
        monitor_details = self._record_monitor_inputs(batch)
        evaluation = self.evaluate_batch(batch)
        data_source = {
            "type": "upload_batch",
            "path": str(upload_path),
            "replaceable_with": "database or streaming enterprise data source",
        }
        report = self._build_report(batch, evaluation, data_source=data_source)
        report["upload_path"] = str(upload_path)
        report["monitor"] = monitor_details
        report_path = self._write_report(report)
        report["report_path"] = str(report_path)
        iteration_record = self._record_iteration(
            batch,
            evaluation,
            report_path,
            data_source=data_source,
        )
        report["iteration"] = iteration_record.to_dict()
        report["iteration_id"] = iteration_record.iteration_id
        self._write_report(report)
        self._record_run(batch, evaluation, report_path)
        logger.info(
            "uploaded iteration batch=%s status=%s report=%s",
            metadata.batch_id,
            evaluation["status"],
            report_path,
        )
        return report

    def _record_monitor_inputs(self, batch: EnterpriseDataBatch) -> Dict[str, Any]:
        metadata = batch.metadata
        monitor = ModelMonitor(
            db_path=self.db_path,
            sample_threshold=self.sample_threshold,
            f1_threshold=self.f1_threshold,
        )
        cumulative_risk_samples = monitor.record_new_samples(
            metadata.risk_sample_count,
            source=f"demo_replay:{metadata.batch_id}:risk_samples",
        )
        monitor.record_performance(
            model_version=f"demo_replay:{metadata.batch_id}",
            accuracy=metadata.recent_f1,
            precision=metadata.recent_f1,
            recall=metadata.recent_f1,
            f1_score=metadata.recent_f1,
            dataset=f"demo_replay:{metadata.batch_id}",
        )
        return {
            "recorded_risk_sample_count": metadata.risk_sample_count,
            "cumulative_risk_sample_count": cumulative_risk_samples,
            "recorded_recent_f1": metadata.recent_f1,
        }

    def _build_report(
        self,
        batch: EnterpriseDataBatch,
        evaluation: Dict[str, Any],
        data_source: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "data_source": data_source or self.data_source.describe(),
            "metadata": batch.metadata.to_dict(),
            "record_count": len(batch.records),
            "records_preview": batch.records[:5],
            "evaluation": evaluation,
            "timestamp": time.time(),
        }

    def _record_iteration(
        self,
        batch: EnterpriseDataBatch,
        evaluation: Dict[str, Any],
        report_path: Path,
        data_source: Optional[Dict[str, Any]] = None,
    ) -> IterationRecord:
        metadata = batch.metadata
        timestamp = time.time()
        now = utc_now_iso()
        thresholds = {
            "risk_sample_count": self.sample_threshold,
            "recent_f1": self.f1_threshold,
        }
        observed = {
            "sample_count": metadata.sample_count,
            "risk_sample_count": metadata.risk_sample_count,
            "recent_f1": metadata.recent_f1,
        }
        triggered = bool(evaluation["retrain_required"])
        blocked_gates = list(evaluation.get("blocked_gates", []))
        if "REGRESSION" in blocked_gates:
            current_status = "REGRESSION_BLOCKED"
        elif "DRIFT" in blocked_gates:
            current_status = "DRIFT_BLOCKED"
        elif triggered:
            current_status = "TRAINING_PENDING"
        else:
            current_status = "NO_RETRAIN_REQUIRED"
        record = IterationRecord(
            iteration_id=build_iteration_id(metadata.batch_id, timestamp),
            batch_id=metadata.batch_id,
            data_source=data_source or self.data_source.describe(),
            sample_count=metadata.sample_count,
            risk_sample_count=metadata.risk_sample_count,
            recent_f1=metadata.recent_f1,
            trigger_threshold_samples=self.sample_threshold,
            trigger_threshold_f1=self.f1_threshold,
            triggered=triggered,
            trigger_reasons=list(evaluation["trigger_reasons"]),
            current_status=current_status,
            timeline=build_timeline(
                batch_id=metadata.batch_id,
                triggered=triggered,
                trigger_reasons=list(evaluation["trigger_reasons"]),
                blocked_gates=blocked_gates,
                thresholds=thresholds,
                observed=observed,
                timestamp=now,
            ),
            report_path=str(report_path),
            created_at=now,
            updated_at=now,
            metadata={
                "demo_mode": data_source is None
                or (data_source or {}).get("type") == "demo_batch",
                "training_mode": "demo_fast_mode",
                "canary_percentage": 0.0,
                "canary_events": [],
                "approval_logs": [],
                "blocked_reason": (
                    "Initial demo replay gate blocked release"
                    if blocked_gates
                    else None
                ),
                "initial_blocked_gates": blocked_gates,
            },
        )
        return self.state_store.save_record(record)

    def _write_report(self, report: Dict[str, Any]) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        batch_id = report["metadata"]["batch_id"]
        output_path = self.reports_dir / f"{batch_id}_report.json"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return output_path

    def _record_run(
        self,
        batch: EnterpriseDataBatch,
        evaluation: Dict[str, Any],
        report_path: Path,
    ) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO demo_replay_runs
            (timestamp, batch_id, status, retrain_required, blocked,
             trigger_reasons, blocked_gates, report_path, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                batch.metadata.batch_id,
                evaluation["status"],
                int(evaluation["retrain_required"]),
                int(evaluation["blocked"]),
                json.dumps(evaluation["trigger_reasons"], ensure_ascii=False),
                json.dumps(evaluation["blocked_gates"], ensure_ascii=False),
                str(report_path),
                json.dumps(batch.metadata.to_dict(), ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

    def latest_run(self, batch_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        self._ensure_tables()
        conn = self._get_conn()
        cursor = conn.cursor()
        if batch_id:
            cursor.execute(
                """
                SELECT * FROM demo_replay_runs
                WHERE batch_id = ?
                  AND COALESCE(archived, 0) = 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (batch_id,),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM demo_replay_runs
                WHERE COALESCE(archived, 0) = 0
                ORDER BY id DESC
                LIMIT 1
                """
            )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        data = dict(row)
        for key in ("trigger_reasons", "blocked_gates"):
            data[key] = json.loads(data[key] or "[]")
        data["metadata"] = json.loads(data.pop("metadata_json"))
        data["retrain_required"] = bool(data["retrain_required"])
        data["blocked"] = bool(data["blocked"])
        return data

    def reset_demo_state(self) -> Dict[str, Any]:
        """Archive current demo run state while keeping source demo batches and reports on disk."""

        self._ensure_tables()
        archived_iterations = self.state_store.archive_active_records(reason="demo reset")
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE demo_replay_runs
            SET archived = 1
            WHERE COALESCE(archived, 0) = 0
            """
        )
        archived_runs = cursor.rowcount
        conn.commit()
        conn.close()
        return {
            "status": "RESET",
            "archived_iterations": archived_iterations,
            "archived_runs": archived_runs,
            "latest_iteration": self.latest_iteration_record(),
            "latest_run": self.latest_run(),
            "message": "演示状态已重置；原始 demo batch 文件和历史报告未删除。",
        }

    def latest_iteration_record(self) -> Optional[Dict[str, Any]]:
        record = self.state_store.get_latest_record()
        return record.to_dict() if record else None

    def get_iteration_record(self, iteration_id: str) -> Optional[Dict[str, Any]]:
        record = self.state_store.get_record(iteration_id)
        return record.to_dict() if record else None

    def get_iteration_timeline(self, iteration_id: str) -> Optional[Dict[str, Any]]:
        record = self.state_store.get_record(iteration_id)
        if record is None:
            return None
        return {
            "iteration_id": record.iteration_id,
            "batch_id": record.batch_id,
            "current_status": record.current_status,
            "triggered": record.triggered,
            "timeline": [event.to_dict() for event in record.timeline],
        }

    def latest_iteration_for_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        record = self.state_store.get_latest_for_batch(batch_id)
        return record.to_dict() if record else None
