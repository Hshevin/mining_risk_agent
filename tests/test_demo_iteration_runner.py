import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mining_risk_serve.api.main import app
from mining_risk_serve.api.routers import iteration as iteration_router
from mining_risk_serve.iteration.data_source import DemoReplayDataSource
from mining_risk_serve.iteration.demo_replay import DemoReplayService
from mining_risk_serve.iteration.demo_runner import DemoIterationError, DemoIterationRunner


DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def _service(tmpdir):
    tmp_path = Path(tmpdir)
    return DemoReplayService(
        data_source=DemoReplayDataSource(demo_dir=DEMO_DIR),
        db_path=str(tmp_path / "audit.db"),
        reports_dir=tmp_path / "reports" / "demo_replay",
        sample_threshold=5000,
        f1_threshold=0.85,
    )


def _runner(tmpdir, service):
    tmp_path = Path(tmpdir)
    runner = DemoIterationRunner(replay_service=service)
    runner.candidates_dir = tmp_path / "models" / "candidates"
    runner.production_pointer_path = tmp_path / "models" / "production" / "demo_current_pointer.json"
    runner.training_reports_dir = tmp_path / "reports" / "training"
    runner.regression_reports_dir = tmp_path / "reports" / "regression"
    runner.drift_reports_dir = tmp_path / "reports" / "drift"
    runner.pr_reports_dir = tmp_path / "reports" / "pr"
    runner.ci_reports_dir = tmp_path / "reports" / "ci"
    runner.approval_reports_dir = tmp_path / "reports" / "approval"
    runner.staging_reports_dir = tmp_path / "reports" / "staging"
    runner.canary_reports_dir = tmp_path / "reports" / "canary"
    runner.audit_dir = tmp_path / "audit" / "iterations"
    return runner


def test_normal_batch_cannot_train():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)
        runner = _runner(tmpdir, service)
        iteration_id = service.replay_batch("normal_batch")["iteration_id"]

        with pytest.raises(DemoIterationError):
            runner.train_candidate(iteration_id)

        record = service.state_store.get_record(iteration_id)
        assert record is not None
        assert record.current_status == "NO_RETRAIN_REQUIRED"
        assert record.metadata["blocked_reason"]


def test_risk_spike_retrain_can_run_to_end_and_archive():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)
        runner = _runner(tmpdir, service)
        iteration_id = service.replay_batch("risk_spike_retrain")["iteration_id"]

        result = runner.run_to_end(iteration_id)
        iteration = result["iteration"]

        assert iteration["current_status"] == "PRODUCTION_RELEASED"
        assert iteration["canary_percentage"] == 1.0
        assert iteration["training_report"]["training_mode"] == "demo_fast_mode"
        timeline_events = [item["event"] for item in iteration["timeline"]]
        assert "PR_CREATED" in timeline_events
        assert "CI_PASSED" in timeline_events
        assert iteration["pr_metadata_path"]
        assert iteration["ci_report"]["status"] == "passed"
        assert Path(iteration["candidate_model_path"]).exists()
        assert Path(iteration["pr_metadata_path"]).exists()
        assert Path(iteration["ci_report_path"]).exists()
        assert Path(iteration["audit_archive_path"]).exists()

        audit = runner.get_audit(iteration_id)["audit"]
        assert audit["batch_id"] == "risk_spike_retrain"
        assert audit["final_status"] == "PRODUCTION_RELEASED"
        assert audit["pr_metadata"]["iteration_id"] == iteration_id
        assert audit["ci_report"]["status"] == "passed"


def test_regression_fail_blocks_at_regression_gate():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)
        runner = _runner(tmpdir, service)
        iteration_id = service.replay_batch("regression_fail")["iteration_id"]

        runner.train_candidate(iteration_id)
        result = runner.run_regression_test(iteration_id)
        iteration = result["iteration"]

        assert iteration["current_status"] == "REGRESSION_BLOCKED"
        assert iteration["regression_report"]["pass"] is False
        assert iteration["blocked_reason"]
        assert "APPROVAL_PENDING" not in [item["event"] for item in iteration["timeline"]]


def test_drift_high_blocks_at_drift_gate():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)
        runner = _runner(tmpdir, service)
        iteration_id = service.replay_batch("drift_high")["iteration_id"]

        runner.train_candidate(iteration_id)
        runner.run_regression_test(iteration_id)
        result = runner.run_drift_analysis(iteration_id)
        iteration = result["iteration"]

        assert iteration["current_status"] == "DRIFT_BLOCKED"
        assert iteration["drift_report"]["risk_level"] == "high"
        assert iteration["drift_report"]["pass"] is False
        assert "APPROVAL_PENDING" not in [item["event"] for item in iteration["timeline"]]


def test_ci_failure_blocks_safety_approval():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)
        runner = _runner(tmpdir, service)
        iteration_id = service.replay_batch("risk_spike_retrain")["iteration_id"]

        runner.train_candidate(iteration_id)
        runner.run_regression_test(iteration_id)
        runner.run_drift_analysis(iteration_id)
        runner.create_pr_metadata(iteration_id)
        record = service.state_store.get_record(iteration_id)
        assert record is not None
        record.metadata["candidate_model_path"] = str(Path(tmpdir) / "missing-model.json")
        service.state_store.save_record(record)

        result = runner.run_ci_precheck(iteration_id)
        iteration = result["iteration"]

        assert iteration["current_status"] == "CI_FAILED"
        assert iteration["ci_report"]["status"] == "failed"
        assert "candidate model artifact is missing" in iteration["ci_report"]["failed_reasons"]
        with pytest.raises(DemoIterationError):
            runner.approve_safety(iteration_id)

        record = service.state_store.get_record(iteration_id)
        assert record is not None
        assert record.current_status == "CI_FAILED"
        assert record.metadata["approval_logs"] == []


def test_ci_passes_before_approval_pending():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)
        runner = _runner(tmpdir, service)
        iteration_id = service.replay_batch("risk_spike_retrain")["iteration_id"]

        runner.train_candidate(iteration_id)
        runner.run_regression_test(iteration_id)
        drift_result = runner.run_drift_analysis(iteration_id)
        assert drift_result["iteration"]["current_status"] == "PR_PENDING"

        pr_result = runner.create_pr_metadata(iteration_id)
        assert pr_result["iteration"]["current_status"] == "CI_PENDING"

        ci_result = runner.run_ci_precheck(iteration_id)
        assert ci_result["iteration"]["current_status"] == "APPROVAL_PENDING"
        assert ci_result["iteration"]["ci_report"]["status"] == "passed"

        approval = runner.approve_safety(iteration_id)
        assert approval["iteration"]["current_status"] == "SAFETY_APPROVED"


def test_canary_cannot_skip_level():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)
        runner = _runner(tmpdir, service)
        iteration_id = service.replay_batch("risk_spike_retrain")["iteration_id"]

        runner.train_candidate(iteration_id)
        runner.run_regression_test(iteration_id)
        runner.run_drift_analysis(iteration_id)
        runner.create_pr_metadata(iteration_id)
        runner.run_ci_precheck(iteration_id)
        runner.approve_safety(iteration_id)
        runner.approve_tech(iteration_id)
        runner.start_staging(iteration_id)
        runner.complete_staging_demo(iteration_id)

        with pytest.raises(DemoIterationError):
            runner.advance_canary(iteration_id, target_percentage=0.5)

        record = service.state_store.get_record(iteration_id)
        assert record is not None
        assert record.current_status == "CANARY_READY"
        assert "cannot skip" in record.metadata["blocked_reason"]


def test_demo_iteration_api_run_to_end_and_audit(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)

        monkeypatch.setattr(iteration_router, "DemoReplayService", lambda: service)
        monkeypatch.setattr(
            iteration_router,
            "DemoIterationRunner",
            lambda replay_service=None: _runner(tmpdir, replay_service or service),
        )
        client = TestClient(app)

        load_resp = client.post("/api/v1/iteration/demo-batches/risk_spike_retrain/load")
        assert load_resp.status_code == 200
        iteration_id = load_resp.json()["iteration_id"]

        run_resp = client.post(f"/api/v1/iteration/{iteration_id}/demo/run-to-end")
        assert run_resp.status_code == 200
        payload = run_resp.json()
        assert payload["iteration"]["current_status"] == "PRODUCTION_RELEASED"
        assert payload["iteration"]["audit_archive_path"]
        timeline_events = [item["event"] for item in payload["iteration"]["timeline"]]
        assert "PR_CREATED" in timeline_events
        assert "CI_PASSED" in timeline_events

        audit_resp = client.get(f"/api/v1/iteration/{iteration_id}/audit")
        assert audit_resp.status_code == 200
        assert audit_resp.json()["audit"]["batch_id"] == "risk_spike_retrain"

        reports_resp = client.get(f"/api/v1/iteration/{iteration_id}/reports")
        assert reports_resp.status_code == 200
        reports = reports_resp.json()["reports"]
        for report_type in ("training", "regression", "drift", "pr", "ci", "audit"):
            assert reports[report_type]["available"] is True
            detail_resp = client.get(
                f"/api/v1/iteration/{iteration_id}/reports/{report_type}"
            )
            assert detail_resp.status_code == 200
            assert detail_resp.json()["content"]["iteration_id"] == iteration_id
