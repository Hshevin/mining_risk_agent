"""Demo-mode model iteration runner.

This module turns replay batches into a full, auditable model-iteration loop.
The model artifact and metrics are synthetic in demo mode, but every state
transition, report, approval, canary event, and audit archive is persisted.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from mining_risk_serve.iteration.demo_replay import DemoReplayService
from mining_risk_serve.iteration.state import IterationRecord, TimelineEvent, utc_now_iso
from mining_risk_common.utils.config import get_config, resolve_project_path


class DemoIterationError(ValueError):
    """Raised when a demo iteration step is not allowed."""

    def __init__(
        self,
        message: str,
        *,
        record: Optional[IterationRecord] = None,
        status_code: int = 400,
    ):
        super().__init__(message)
        self.record = record
        self.status_code = status_code


class DemoIterationRunner:
    """Run the demo-mode iteration lifecycle against IterationRecord state."""

    CANARY_RATIOS = [0.0, 0.1, 0.5, 1.0]
    REGRESSION_FAIL_BATCHES = {"regression_fail", "regression_block"}
    DRIFT_HIGH_BATCHES = {"drift_high", "drift_high_block"}

    def __init__(self, replay_service: Optional[DemoReplayService] = None):
        self.config = get_config()
        self.replay_service = replay_service or DemoReplayService()
        self.state_store = self.replay_service.state_store
        self.old_model_path = resolve_project_path(self.config.model.stacking.model_path)
        self.candidates_dir = resolve_project_path("artifacts/models/candidates")
        self.production_pointer_path = resolve_project_path(
            "artifacts/models/production/demo_current_pointer.json"
        )
        self.training_reports_dir = resolve_project_path("reports/training")
        self.regression_reports_dir = resolve_project_path("reports/regression")
        self.drift_reports_dir = resolve_project_path("reports/drift")
        self.pr_reports_dir = resolve_project_path("reports/pr")
        self.ci_reports_dir = resolve_project_path("reports/ci")
        self.approval_reports_dir = resolve_project_path("reports/approval")
        self.staging_reports_dir = resolve_project_path("reports/staging")
        self.canary_reports_dir = resolve_project_path("reports/canary")
        self.audit_dir = resolve_project_path("var/audit/iterations")

    def train_candidate(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        if not record.triggered:
            report = {
                "iteration_id": iteration_id,
                "batch_id": record.batch_id,
                "training_mode": "demo_fast_mode",
                "pass": False,
                "blocked_reason": "Batch did not trigger retraining.",
            }
            report_path = self._write_json(
                self.training_reports_dir / f"{iteration_id}_rejected.json",
                report,
            )
            record.metadata["training_report_path"] = str(report_path)
            self._fail(
                record,
                event="CANDIDATE_TRAINING",
                reason="normal_batch is not allowed to train because retrain_required=false",
            )
            raise DemoIterationError(report["blocked_reason"], record=record)
        self._require_status(record, ["TRAINING_PENDING"], "train_candidate")

        candidate_dir = self.candidates_dir / iteration_id
        model_version = f"demo-candidate-{iteration_id}-{int(time.time())}"
        candidate_model_path = candidate_dir / "candidate_model_demo.json"
        candidate_model = {
            "artifact_type": "demo_candidate_model",
            "training_mode": "demo_fast_mode",
            "iteration_id": iteration_id,
            "batch_id": record.batch_id,
            "model_version": model_version,
            "created_at": utc_now_iso(),
            "source": "synthetic demo replay batch",
        }
        self._write_json(candidate_model_path, candidate_model)

        training_report = {
            "iteration_id": iteration_id,
            "batch_id": record.batch_id,
            "training_mode": "demo_fast_mode",
            "old_model_path": str(self.old_model_path),
            "candidate_model_path": str(candidate_model_path),
            "model_version": model_version,
            "sample_count": record.sample_count,
            "risk_sample_count": record.risk_sample_count,
            "trigger_reasons": record.trigger_reasons,
            "started_at": utc_now_iso(),
            "completed_at": utc_now_iso(),
            "pass": True,
        }
        training_report_path = self._write_json(
            candidate_dir / "training_report.json",
            training_report,
        )

        record.current_status = "REGRESSION_PENDING"
        record.metadata.update(
            {
                "demo_mode": True,
                "training_mode": "demo_fast_mode",
                "model_version": model_version,
                "candidate_model_path": str(candidate_model_path),
                "training_report_path": str(training_report_path),
                "training_report": training_report,
                "blocked_reason": None,
            }
        )
        self._append_event(
            record,
            "CANDIDATE_TRAINING",
            "COMPLETED",
            "Demo candidate model artifact generated",
            {
                "training_mode": "demo_fast_mode",
                "candidate_model_path": str(candidate_model_path),
                "training_report_path": str(training_report_path),
            },
        )
        record = self._save(record)
        return self._step_response(
            record,
            report=training_report,
            message="candidate training completed in demo_fast_mode",
        )

    def run_regression_test(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["REGRESSION_PENDING"], "run_regression_test")

        report = self._build_regression_report(record)
        report_path = self._write_json(
            self.regression_reports_dir / f"{iteration_id}.json",
            report,
        )
        record.metadata["regression_report"] = report
        record.metadata["regression_report_path"] = str(report_path)
        if report["pass"]:
            record.current_status = "DRIFT_PENDING"
            status = "COMPLETED"
            message = "Regression gate passed"
            details = {"report_path": str(report_path), "delta": report["delta"]}
        else:
            record.current_status = "REGRESSION_BLOCKED"
            record.metadata["blocked_reason"] = "; ".join(report["failed_reasons"])
            status = "BLOCKED"
            message = "Regression gate blocked candidate model"
            details = {
                "report_path": str(report_path),
                "failed_reasons": report["failed_reasons"],
            }
        self._append_event(record, "REGRESSION_TEST", status, message, details)
        record = self._save(record)
        return self._step_response(record, report=report, message=message)

    def run_drift_analysis(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["DRIFT_PENDING"], "run_drift_analysis")

        report = self._build_drift_report(record)
        report_path = self._write_json(self.drift_reports_dir / f"{iteration_id}.json", report)
        record.metadata["drift_report"] = report
        record.metadata["drift_report_path"] = str(report_path)
        if report["pass"]:
            record.current_status = "PR_PENDING"
            status = "COMPLETED"
            message = "Drift gate passed"
        else:
            record.current_status = "DRIFT_BLOCKED"
            record.metadata["blocked_reason"] = report["blocked_reason"]
            status = "BLOCKED"
            message = "Drift gate blocked release"
        self._append_event(
            record,
            "DRIFT_ANALYSIS",
            status,
            message,
            {
                "report_path": str(report_path),
                "risk_level": report["risk_level"],
                "blocked_reason": report.get("blocked_reason"),
            },
        )
        record = self._save(record)
        return self._step_response(record, report=report, message=message)

    def create_pr_metadata(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["PR_PENDING"], "create_pr_metadata")
        self._require_quality_gates(record, require_ci=False)

        report = self._build_pr_metadata(record)
        report_path = self.pr_reports_dir / f"{iteration_id}.json"
        report["local_pr_metadata_path"] = str(report_path)
        self._write_json(report_path, report)
        record.metadata["pr_metadata"] = report
        record.metadata["pr_metadata_path"] = str(report_path)
        record.metadata["local_pr_metadata_path"] = str(report_path)
        record.current_status = "CI_PENDING"
        self._append_event(
            record,
            "PR_CREATED",
            "COMPLETED",
            "Local PR metadata generated",
            {
                "local_pr_metadata_path": str(report_path),
                "branch_name": report["branch_name"],
            },
        )
        record = self._save(record)
        return self._step_response(record, report=report, message="local PR metadata generated")

    def run_ci_precheck(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["CI_PENDING", "CI_FAILED"], "run_ci_precheck")

        record.current_status = "CI_RUNNING"
        self._append_event(
            record,
            "CI_RUNNING",
            "RUNNING",
            "Demo CI precheck started",
            {"pr_metadata_path": record.metadata.get("pr_metadata_path")},
        )
        record = self._save(record)

        report = self._build_ci_report(record)
        report_path = self._write_json(self.ci_reports_dir / f"{iteration_id}.json", report)
        report["report_path"] = str(report_path)
        record.metadata["ci_report"] = report
        record.metadata["ci_report_path"] = str(report_path)
        if report["status"] == "passed":
            record.current_status = "APPROVAL_PENDING"
            record.metadata["blocked_reason"] = None
            event = "CI_PASSED"
            status = "COMPLETED"
            message = "CI precheck passed"
        else:
            record.current_status = "CI_FAILED"
            record.metadata["blocked_reason"] = "; ".join(report["failed_reasons"])
            event = "CI_FAILED"
            status = "FAILED"
            message = "CI precheck blocked approval"
        self._append_event(
            record,
            event,
            status,
            message,
            {
                "report_path": str(report_path),
                "failed_reasons": report["failed_reasons"],
            },
        )
        record = self._save(record)
        return self._step_response(record, report=report, message=message)

    def approve_safety(
        self,
        iteration_id: str,
        *,
        approver: str = "demo_safety_reviewer",
        note: str = "demo safety approval",
    ) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["APPROVAL_PENDING"], "approve_safety")
        self._require_quality_gates(record)
        report = self._write_approval(record, "safety", approver, note)
        record.current_status = "SAFETY_APPROVED"
        record = self._save(record)
        return self._step_response(record, report=report, message="safety approval recorded")

    def approve_tech(
        self,
        iteration_id: str,
        *,
        approver: str = "demo_tech_reviewer",
        note: str = "demo technical approval",
    ) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["SAFETY_APPROVED"], "approve_tech")
        report = self._write_approval(record, "tech", approver, note)
        record.current_status = "STAGING_PENDING"
        record = self._save(record)
        return self._step_response(record, report=report, message="technical approval recorded")

    def start_staging(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["STAGING_PENDING"], "start_staging")

        report = {
            "iteration_id": iteration_id,
            "batch_id": record.batch_id,
            "status": "RUNNING",
            "demo_mode": True,
            "compressed_from": "24h",
            "compressed_to_seconds": 30,
            "started_at": utc_now_iso(),
            "candidate_model_path": record.metadata.get("candidate_model_path"),
        }
        report_path = self._write_json(
            self.staging_reports_dir / f"{iteration_id}_start.json",
            report,
        )
        record.current_status = "STAGING_RUNNING"
        record.metadata["staging_report"] = report
        record.metadata["staging_report_path"] = str(report_path)
        self._append_event(
            record,
            "STAGING",
            "RUNNING",
            "Demo staging started with 30 second compressed window",
            {"report_path": str(report_path), "compressed_to_seconds": 30},
        )
        record = self._save(record)
        return self._step_response(record, report=report, message="staging started")

    def complete_staging_demo(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["STAGING_RUNNING"], "complete_staging_demo")

        report = {
            "iteration_id": iteration_id,
            "batch_id": record.batch_id,
            "status": "PASSED",
            "demo_mode": True,
            "compressed_from": "24h",
            "compressed_to_seconds": 30,
            "completed_at": utc_now_iso(),
            "health_checks": {
                "latency_p95_ms": 84,
                "error_rate": 0.0,
                "risk_score_shift": 0.018,
            },
            "pass": True,
        }
        report_path = self._write_json(self.staging_reports_dir / f"{iteration_id}.json", report)
        record.current_status = "CANARY_READY"
        record.metadata["staging_report"] = report
        record.metadata["staging_report_path"] = str(report_path)
        self._append_event(
            record,
            "STAGING",
            "COMPLETED",
            "Demo staging completed",
            {"report_path": str(report_path), "status": "PASSED"},
        )
        record = self._save(record)
        return self._step_response(record, report=report, message="staging completed")

    def advance_canary(
        self,
        iteration_id: str,
        *,
        target_percentage: Optional[float] = None,
        operator: str = "demo_operator",
    ) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(record, ["CANARY_READY", "CANARY_RUNNING"], "advance_canary")

        current = float(record.metadata.get("canary_percentage", 0.0))
        next_ratio = self._next_canary_ratio(current)
        target = next_ratio if target_percentage is None else float(target_percentage)
        if round(target, 3) != round(next_ratio, 3):
            self._fail(
                record,
                event="CANARY",
                reason=(
                    f"canary cannot skip level: current={current}, "
                    f"next={next_ratio}, target={target}"
                ),
            )
            raise DemoIterationError(
                f"canary cannot skip level: current={current}, next={next_ratio}, target={target}",
                record=record,
            )

        event = {
            "iteration_id": iteration_id,
            "batch_id": record.batch_id,
            "from": current,
            "to": target,
            "operator": operator,
            "timestamp": utc_now_iso(),
            "demo_mode": True,
        }
        events = list(record.metadata.get("canary_events", []))
        events.append(event)
        report = {
            "iteration_id": iteration_id,
            "batch_id": record.batch_id,
            "current_percentage": target,
            "allowed_sequence": self.CANARY_RATIOS,
            "events": events,
            "demo_mode": True,
        }
        report_path = self._write_json(self.canary_reports_dir / f"{iteration_id}.json", report)
        record.metadata["canary_events"] = events
        record.metadata["canary_percentage"] = target
        record.metadata["canary_report_path"] = str(report_path)

        if target == 1.0:
            record.current_status = "PRODUCTION_RELEASED"
            pointer = {
                "mode": "demo_pointer_only",
                "model_version": record.metadata.get("model_version"),
                "candidate_model_path": record.metadata.get("candidate_model_path"),
                "released_at": utc_now_iso(),
                "note": "Demo mode updates pointer metadata only; production/current is not overwritten.",
            }
            pointer_path = self._write_json(self.production_pointer_path, pointer)
            record.metadata["production_pointer_path"] = str(pointer_path)
            message = "Canary reached 100%; demo production pointer updated"
        else:
            record.current_status = "CANARY_RUNNING"
            message = f"Canary advanced to {target}"

        self._append_event(
            record,
            "CANARY",
            "COMPLETED",
            message,
            {"from": current, "to": target, "report_path": str(report_path)},
        )
        record = self._save(record)
        return self._step_response(record, report=report, message=message)

    def archive_audit(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        self._require_status(
            record,
            ["PRODUCTION_RELEASED", "REGRESSION_BLOCKED", "DRIFT_BLOCKED", "CI_FAILED"],
            "archive_audit",
        )

        audit = {
            "iteration_id": iteration_id,
            "batch_id": record.batch_id,
            "trigger_reason": record.trigger_reasons,
            "training_report": record.metadata.get("training_report"),
            "regression_report": record.metadata.get("regression_report"),
            "drift_report": record.metadata.get("drift_report"),
            "pr_metadata": record.metadata.get("pr_metadata"),
            "ci_report": record.metadata.get("ci_report"),
            "approval_logs": record.metadata.get("approval_logs", []),
            "staging_report": record.metadata.get("staging_report"),
            "canary_events": record.metadata.get("canary_events", []),
            "final_status": record.current_status,
            "blocked_reason": record.metadata.get("blocked_reason"),
            "timeline": [event.to_dict() for event in record.timeline],
            "created_at": record.created_at,
            "archived_at": utc_now_iso(),
            "demo_mode": True,
        }
        audit_path = self._write_json(self.audit_dir / f"{iteration_id}.json", audit)
        record.metadata["audit_archive_path"] = str(audit_path)
        self._append_event(
            record,
            "AUDIT_ARCHIVE",
            "COMPLETED",
            "Iteration audit archive written",
            {"audit_archive_path": str(audit_path), "final_status": record.current_status},
        )
        record = self._save(record)
        return self._step_response(record, report=audit, message="audit archive written")

    def run_next_step(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        action = next((item for item in record.next_actions if item.get("enabled")), None)
        if not action:
            raise DemoIterationError("no enabled next action", record=record)
        action_name = str(action["action"])
        dispatch: Dict[str, Callable[[], Dict[str, Any]]] = {
            "START_TRAINING": lambda: self.train_candidate(iteration_id),
            "TRAIN_CANDIDATE": lambda: self.train_candidate(iteration_id),
            "RUN_REGRESSION": lambda: self.run_regression_test(iteration_id),
            "RUN_REGRESSION_TEST": lambda: self.run_regression_test(iteration_id),
            "RUN_DRIFT_ANALYSIS": lambda: self.run_drift_analysis(iteration_id),
            "CREATE_PR": lambda: self.create_pr_metadata(iteration_id),
            "RUN_CI_PRECHECK": lambda: self.run_ci_precheck(iteration_id),
            "APPROVE_SAFETY": lambda: self.approve_safety(iteration_id),
            "APPROVE_TECH": lambda: self.approve_tech(iteration_id),
            "START_STAGING": lambda: self.start_staging(iteration_id),
            "COMPLETE_STAGING_DEMO": lambda: self.complete_staging_demo(iteration_id),
            "ADVANCE_CANARY": lambda: self.advance_canary(iteration_id),
            "ARCHIVE_AUDIT": lambda: self.archive_audit(iteration_id),
        }
        if action_name not in dispatch:
            raise DemoIterationError(f"unsupported next action: {action_name}", record=record)
        return dispatch[action_name]()

    def run_to_end(self, iteration_id: str) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        while True:
            record = self._load_record(iteration_id)
            enabled = [item for item in record.next_actions if item.get("enabled")]
            if not enabled:
                break
            if (
                enabled[0]["action"] == "ARCHIVE_AUDIT"
                and record.metadata.get("audit_archive_path")
            ):
                break
            result = self.run_next_step(iteration_id)
            steps.append(
                {
                    "action": enabled[0]["action"],
                    "status": result["current_status"],
                    "message": result["message"],
                }
            )
            record = self._load_record(iteration_id)
            if record.current_status in {"REGRESSION_BLOCKED", "DRIFT_BLOCKED", "CI_FAILED"}:
                if not record.metadata.get("audit_archive_path"):
                    result = self.archive_audit(iteration_id)
                    steps.append(
                        {
                            "action": "ARCHIVE_AUDIT",
                            "status": result["current_status"],
                            "message": result["message"],
                        }
                    )
                break
            if (
                record.current_status == "PRODUCTION_RELEASED"
                and not record.metadata.get("audit_archive_path")
            ):
                result = self.archive_audit(iteration_id)
                steps.append(
                    {
                        "action": "ARCHIVE_AUDIT",
                        "status": result["current_status"],
                        "message": result["message"],
                    }
                )
                break
        final_record = self._load_record(iteration_id)
        return self._step_response(
            final_record,
            report={"steps": steps},
            message=f"demo run-to-end completed at {final_record.current_status}",
        )

    def get_audit(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        path_text = record.metadata.get("audit_archive_path")
        if not path_text:
            raise DemoIterationError("audit archive not generated", record=record, status_code=404)
        path = Path(path_text)
        if not path.exists():
            raise DemoIterationError("audit archive file is missing", record=record, status_code=404)
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return {"audit_archive_path": str(path), "audit": payload}

    def get_reports(self, iteration_id: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        reports = {
            report_type: self._report_item(record, report_type)
            for report_type in self._report_path_map(record)
        }
        return {
            "iteration_id": record.iteration_id,
            "batch_id": record.batch_id,
            "current_status": record.current_status,
            "reports": reports,
        }

    def get_report(self, iteration_id: str, report_type: str) -> Dict[str, Any]:
        record = self._load_record(iteration_id)
        normalized_type = report_type.lower()
        path_map = self._report_path_map(record)
        if normalized_type not in path_map:
            raise DemoIterationError(
                f"unsupported report_type: {report_type}",
                record=record,
                status_code=404,
            )
        item = self._report_item(record, normalized_type)
        if not item["available"]:
            raise DemoIterationError(
                f"{normalized_type} report not generated",
                record=record,
                status_code=404,
            )
        return {
            "iteration_id": record.iteration_id,
            "batch_id": record.batch_id,
            "report_type": normalized_type,
            "path": item["path"],
            "content": item["content"],
        }

    def _load_record(self, iteration_id: str) -> IterationRecord:
        record = self.state_store.get_record(iteration_id)
        if record is None:
            raise DemoIterationError(f"iteration record not found: {iteration_id}", status_code=404)
        record.metadata.setdefault("demo_mode", True)
        record.metadata.setdefault("training_mode", "demo_fast_mode")
        record.metadata.setdefault("canary_percentage", 0.0)
        record.metadata.setdefault("canary_events", [])
        record.metadata.setdefault("approval_logs", [])
        return record

    def _save(self, record: IterationRecord) -> IterationRecord:
        record.metadata["demo_mode"] = True
        record.metadata["training_mode"] = "demo_fast_mode"
        record.metadata.pop("next_actions", None)
        record.metadata["next_actions"] = record.next_actions
        record.updated_at = utc_now_iso()
        return self.state_store.save_record(record)

    def _append_event(
        self,
        record: IterationRecord,
        event: str,
        status: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        record.timeline.append(
            TimelineEvent(
                event=event,
                status=status,
                timestamp=utc_now_iso(),
                message=message,
                details=details or {},
            )
        )

    def _require_status(
        self,
        record: IterationRecord,
        allowed_statuses: Sequence[str],
        step: str,
    ) -> None:
        if record.current_status in allowed_statuses:
            return
        allowed_text = ", ".join(allowed_statuses)
        reason = (
            f"{step} requires status in [{allowed_text}], "
            f"current_status={record.current_status}"
        )
        self._fail(record, event=step.upper(), reason=reason)
        raise DemoIterationError(reason, record=record)

    def _fail(
        self,
        record: IterationRecord,
        *,
        event: str,
        reason: str,
        status: str = "FAILED",
    ) -> IterationRecord:
        record.metadata["blocked_reason"] = reason
        self._append_event(record, event, status, reason, {"blocked_reason": reason})
        return self._save(record)

    def _require_quality_gates(self, record: IterationRecord, *, require_ci: bool = True) -> None:
        regression = record.metadata.get("regression_report") or {}
        drift = record.metadata.get("drift_report") or {}
        if not regression.get("pass") or not drift.get("pass"):
            reason = "Regression and drift gates must both pass before approval."
            self._fail(record, event="APPROVAL", reason=reason)
            raise DemoIterationError(reason, record=record)
        if require_ci:
            ci = record.metadata.get("ci_report") or {}
            if ci.get("status") != "passed":
                reason = "CI precheck must pass before safety approval."
                self._fail(record, event="APPROVAL", reason=reason)
                raise DemoIterationError(reason, record=record)

    def _build_regression_report(self, record: IterationRecord) -> Dict[str, Any]:
        batch_id = record.batch_id
        failed = batch_id in self.REGRESSION_FAIL_BATCHES
        if failed:
            old_f1 = 0.874
            new_f1 = 0.812
        elif batch_id == "risk_spike_retrain":
            old_f1 = 0.901
            new_f1 = 0.914
        elif batch_id == "f1_drop_retrain":
            old_f1 = 0.823
            new_f1 = 0.872
        elif batch_id in self.DRIFT_HIGH_BATCHES:
            old_f1 = 0.881
            new_f1 = 0.889
        else:
            old_f1 = max(record.recent_f1 - 0.005, 0.0)
            new_f1 = record.recent_f1 + 0.006
        old_metrics = {
            "f1_macro": round(old_f1, 3),
            "precision_macro": round(old_f1 + 0.004, 3),
            "recall_macro": round(old_f1 - 0.003, 3),
        }
        new_metrics = {
            "f1_macro": round(new_f1, 3),
            "precision_macro": round(new_f1 + 0.003, 3),
            "recall_macro": round(new_f1 - 0.002, 3),
        }
        delta = {
            key: round(float(new_metrics[key]) - float(old_metrics[key]), 4)
            for key in old_metrics
        }
        failed_reasons = []
        if failed:
            failed_reasons.append("candidate model F1 below release threshold in demo batch")
        if new_metrics["f1_macro"] < 0.85:
            failed_reasons.append("candidate f1_macro < 0.85")
        return {
            "iteration_id": record.iteration_id,
            "batch_id": batch_id,
            "demo_mode": True,
            "old_model_path": str(self.old_model_path),
            "candidate_model_path": record.metadata.get("candidate_model_path"),
            "old_metrics": old_metrics,
            "new_metrics": new_metrics,
            "delta": delta,
            "pass": len(failed_reasons) == 0,
            "failed_reasons": failed_reasons,
            "created_at": utc_now_iso(),
        }

    def _build_drift_report(self, record: IterationRecord) -> Dict[str, Any]:
        high = record.batch_id in self.DRIFT_HIGH_BATCHES
        risk_level = "high" if high else ("medium" if record.batch_id == "f1_drop_retrain" else "low")
        psi = 0.42 if high else (0.19 if risk_level == "medium" else 0.11)
        passed = not high
        return {
            "iteration_id": record.iteration_id,
            "batch_id": record.batch_id,
            "demo_mode": True,
            "risk_level": risk_level,
            "psi": psi,
            "threshold": 0.25,
            "top_shifted_features": [
                "risk_total_count",
                "trouble_level_2_count",
                "industry_category",
            ]
            if high
            else ["risk_total_count"],
            "pass": passed,
            "blocked_reason": None
            if passed
            else "drift risk_level=high exceeds demo release gate",
            "created_at": utc_now_iso(),
        }

    def _build_pr_metadata(self, record: IterationRecord) -> Dict[str, Any]:
        regression = record.metadata.get("regression_report") or {}
        drift = record.metadata.get("drift_report") or {}
        model_version = str(record.metadata.get("model_version") or "demo-candidate")
        branch_name = f"feature/model-iteration-{record.iteration_id}"
        return {
            "iteration_id": record.iteration_id,
            "branch_name": branch_name,
            "update_purpose": "Demo-mode model iteration release candidate",
            "changed_content": {
                "candidate_model_path": record.metadata.get("candidate_model_path"),
                "training_report_path": record.metadata.get("training_report_path"),
                "regression_report_path": record.metadata.get("regression_report_path"),
                "drift_report_path": record.metadata.get("drift_report_path"),
                "demo_mode": True,
            },
            "old_model_version": self._old_model_version(),
            "candidate_model_version": model_version,
            "regression_summary": {
                "pass": regression.get("pass"),
                "old_metrics": regression.get("old_metrics"),
                "new_metrics": regression.get("new_metrics"),
                "delta": regression.get("delta"),
                "failed_reasons": regression.get("failed_reasons", []),
            },
            "drift_summary": {
                "pass": drift.get("pass"),
                "risk_level": drift.get("risk_level"),
                "psi": drift.get("psi"),
                "threshold": drift.get("threshold"),
                "blocked_reason": drift.get("blocked_reason"),
            },
            "high_risk_sample_comparison": {
                "risk_sample_count": record.risk_sample_count,
                "trigger_threshold_samples": record.trigger_threshold_samples,
                "excess": max(record.risk_sample_count - record.trigger_threshold_samples, 0),
                "trigger_reasons": record.trigger_reasons,
            },
            "approval_required": True,
            "generated_at": utc_now_iso(),
            "demo_mode": True,
        }

    def _build_ci_report(self, record: IterationRecord) -> Dict[str, Any]:
        regression = record.metadata.get("regression_report") or {}
        drift = record.metadata.get("drift_report") or {}
        candidate_model_path = record.metadata.get("candidate_model_path")
        model_artifact_exists = bool(candidate_model_path and Path(str(candidate_model_path)).exists())
        checks = {
            "code_style_check": {
                "status": "passed",
                "details": "Demo precheck uses repository lint/build in final verification.",
            },
            "system_load_check": {
                "status": "passed",
                "cpu_usage_pct": 18,
                "memory_usage_pct": 42,
                "details": "Synthetic demo load within pre-production threshold.",
            },
            "regression_gate": {
                "status": "passed" if regression.get("pass") else "failed",
                "report_path": record.metadata.get("regression_report_path"),
                "summary": {
                    "delta": regression.get("delta"),
                    "failed_reasons": regression.get("failed_reasons", []),
                },
            },
            "drift_gate": {
                "status": "passed" if drift.get("pass") else "failed",
                "report_path": record.metadata.get("drift_report_path"),
                "summary": {
                    "risk_level": drift.get("risk_level"),
                    "psi": drift.get("psi"),
                    "blocked_reason": drift.get("blocked_reason"),
                },
            },
            "model_artifact_check": {
                "status": "passed" if model_artifact_exists else "failed",
                "candidate_model_path": candidate_model_path,
            },
        }
        failed_reasons: List[str] = []
        if checks["regression_gate"]["status"] != "passed":
            failed_reasons.append("regression gate did not pass")
        if checks["drift_gate"]["status"] != "passed":
            failed_reasons.append("drift gate did not pass")
        if checks["model_artifact_check"]["status"] != "passed":
            failed_reasons.append("candidate model artifact is missing")
        status = "passed" if not failed_reasons else "failed"
        return {
            "iteration_id": record.iteration_id,
            "batch_id": record.batch_id,
            **checks,
            "status": status,
            "failed_reasons": failed_reasons,
            "generated_at": utc_now_iso(),
            "demo_mode": True,
        }

    def _old_model_version(self) -> str:
        if self.production_pointer_path.exists():
            try:
                with self.production_pointer_path.open("r", encoding="utf-8") as f:
                    pointer = json.load(f)
                value = pointer.get("model_version")
                if value:
                    return str(value)
            except (OSError, json.JSONDecodeError):
                pass
        return self.old_model_path.stem

    def _write_approval(
        self,
        record: IterationRecord,
        role: str,
        approver: str,
        note: str,
    ) -> Dict[str, Any]:
        report = {
            "iteration_id": record.iteration_id,
            "batch_id": record.batch_id,
            "role": role,
            "approver": approver,
            "note": note,
            "status": "APPROVED",
            "timestamp": utc_now_iso(),
            "demo_mode": True,
        }
        report_path = self._write_json(
            self.approval_reports_dir / f"{record.iteration_id}_{role}.json",
            report,
        )
        report["report_path"] = str(report_path)
        logs = list(record.metadata.get("approval_logs", []))
        logs.append(report)
        record.metadata["approval_logs"] = logs
        self._append_event(
            record,
            f"APPROVAL_{role.upper()}",
            "COMPLETED",
            f"{role} approval recorded",
            report,
        )
        return report

    def _next_canary_ratio(self, current: float) -> float:
        rounded = round(current, 3)
        for index, ratio in enumerate(self.CANARY_RATIOS):
            if round(ratio, 3) == rounded and index + 1 < len(self.CANARY_RATIOS):
                return self.CANARY_RATIOS[index + 1]
        raise DemoIterationError(f"no canary level after {current}")

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def _report_path_map(self, record: IterationRecord) -> Dict[str, Optional[str]]:
        return {
            "replay": record.report_path,
            "upload": record.metadata.get("upload_report_path"),
            "training": record.metadata.get("training_report_path"),
            "regression": record.metadata.get("regression_report_path"),
            "drift": record.metadata.get("drift_report_path"),
            "pr": record.metadata.get("pr_metadata_path"),
            "ci": record.metadata.get("ci_report_path"),
            "staging": record.metadata.get("staging_report_path"),
            "audit": record.metadata.get("audit_archive_path"),
        }

    def _report_item(self, record: IterationRecord, report_type: str) -> Dict[str, Any]:
        path_text = self._report_path_map(record).get(report_type)
        if not path_text:
            return {
                "report_type": report_type,
                "available": False,
                "path": None,
                "content": None,
            }
        path = Path(str(path_text))
        if not path.exists():
            return {
                "report_type": report_type,
                "available": False,
                "path": str(path),
                "content": None,
                "missing": True,
            }
        content: Any
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as f:
                content = json.load(f)
        else:
            with path.open("r", encoding="utf-8") as f:
                content = {"text": f.read()}
        return {
            "report_type": report_type,
            "available": True,
            "path": str(path),
            "content": content,
        }

    def _step_response(
        self,
        record: IterationRecord,
        *,
        report: Optional[Dict[str, Any]],
        message: str,
    ) -> Dict[str, Any]:
        payload = record.to_dict()
        return {
            "iteration_id": record.iteration_id,
            "batch_id": record.batch_id,
            "current_status": record.current_status,
            "timeline": payload["timeline"],
            "next_actions": payload["next_actions"],
            "iteration": payload,
            "report": report,
            "message": message,
        }
