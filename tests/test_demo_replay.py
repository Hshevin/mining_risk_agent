import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from mining_risk_serve.api.main import app
from mining_risk_serve.api.routers import iteration as iteration_router
from mining_risk_serve.iteration.data_source import DemoReplayDataSource
from mining_risk_serve.iteration.demo_replay import DemoReplayService


DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def _service(tmpdir):
    tmp_path = Path(tmpdir)
    return DemoReplayService(
        data_source=DemoReplayDataSource(demo_dir=DEMO_DIR),
        db_path=str(tmp_path / "audit.db"),
        reports_dir=tmp_path / "reports",
        sample_threshold=5000,
        f1_threshold=0.85,
    )


def test_demo_data_source_lists_required_batches():
    source = DemoReplayDataSource(demo_dir=DEMO_DIR)
    batches = {batch.batch_id: batch for batch in source.list_batches()}

    assert {
        "normal_batch",
        "risk_spike_retrain",
        "f1_drop_retrain",
        "regression_block",
        "drift_high_block",
    }.issubset(batches)
    assert batches["normal_batch"].sample_count == 1800
    assert batches["risk_spike_retrain"].risk_sample_count == 5600
    assert batches["f1_drop_retrain"].recent_f1 < 0.85


def test_demo_replay_evaluates_retrain_and_blocking_scenarios():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)

        normal = service.evaluate_batch(service.load_batch("normal_batch"))
        assert normal["status"] == "NO_RETRAIN"
        assert normal["retrain_required"] is False

        risk_spike = service.evaluate_batch(service.load_batch("risk_spike_retrain"))
        assert risk_spike["status"] == "RETRAIN_REQUIRED"
        assert "RISK_SAMPLE_THRESHOLD_EXCEEDED" in risk_spike["trigger_reasons"]

        f1_drop = service.evaluate_batch(service.load_batch("f1_drop_retrain"))
        assert f1_drop["status"] == "RETRAIN_REQUIRED"
        assert "PERFORMANCE_DEGRADED" in f1_drop["trigger_reasons"]

        regression = service.evaluate_batch(service.load_batch("regression_block"))
        assert regression["status"] == "BLOCKED"
        assert "REGRESSION" in regression["blocked_gates"]

        drift = service.evaluate_batch(service.load_batch("drift_high_block"))
        assert drift["status"] == "BLOCKED"
        assert "DRIFT" in drift["blocked_gates"]


def test_demo_replay_writes_report_and_trace_record():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)

        report = service.replay_batch("risk_spike_retrain")
        report_path = Path(report["report_path"])

        assert report_path.exists()
        assert report["evaluation"]["retrain_required"] is True
        assert report["metadata"]["batch_id"] == "risk_spike_retrain"

        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        assert loaded["metadata"]["risk_sample_count"] == 5600

        latest = service.latest_run()
        assert latest is not None
        assert latest["batch_id"] == "risk_spike_retrain"
        assert latest["retrain_required"] is True


def test_demo_replay_records_iteration_trigger_outcomes():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = _service(tmpdir)

        normal = service.replay_batch("normal_batch")
        assert normal["iteration"]["triggered"] is False
        assert normal["iteration"]["current_status"] == "NO_RETRAIN_REQUIRED"
        assert normal["iteration"]["risk_sample_count"] == 420

        risk_spike = service.replay_batch("risk_spike_retrain")
        assert risk_spike["iteration"]["triggered"] is True
        assert "RISK_SAMPLE_THRESHOLD_EXCEEDED" in risk_spike["iteration"]["trigger_reasons"]

        f1_drop = service.replay_batch("f1_drop_retrain")
        assert f1_drop["iteration"]["triggered"] is True
        assert "PERFORMANCE_DEGRADED" in f1_drop["iteration"]["trigger_reasons"]

        latest = service.latest_iteration_record()
        assert latest is not None
        assert latest["iteration_id"] == f1_drop["iteration_id"]
        assert latest["batch_id"] == "f1_drop_retrain"
        assert latest["trigger_threshold_samples"] == 5000
        assert latest["trigger_threshold_f1"] == 0.85


def test_iteration_demo_batch_api_lists_and_loads_batches():
    client = TestClient(app)

    list_resp = client.get("/api/v1/iteration/demo-batches")
    assert list_resp.status_code == 200
    batch_ids = {item["batch_id"] for item in list_resp.json()}
    assert "normal_batch" in batch_ids

    load_resp = client.get("/api/v1/iteration/demo-batches/normal_batch")
    assert load_resp.status_code == 200
    payload = load_resp.json()
    assert payload["metadata"]["batch_id"] == "normal_batch"
    assert payload["metadata"]["sample_count"] == 1800
    assert payload["record_count"] >= 1


def test_iteration_status_query_apis_return_latest_and_timeline(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(
            iteration_router,
            "DemoReplayService",
            lambda: _service(tmpdir),
        )
        client = TestClient(app)

        normal_resp = client.post("/api/v1/iteration/demo-batches/normal_batch/load")
        assert normal_resp.status_code == 200
        assert normal_resp.json()["triggered"] is False

        risk_resp = client.post("/api/v1/iteration/demo-batches/risk_spike_retrain/load")
        assert risk_resp.status_code == 200
        risk_payload = risk_resp.json()
        iteration_id = risk_payload["iteration_id"]
        assert risk_payload["triggered"] is True

        latest_resp = client.get("/api/v1/iteration/latest")
        assert latest_resp.status_code == 200
        latest_payload = latest_resp.json()
        assert latest_payload["iteration_id"] == iteration_id
        assert latest_payload["batch_id"] == "risk_spike_retrain"
        assert latest_payload["triggered"] is True
        assert latest_payload["current_status"] == "TRAINING_PENDING"
        assert latest_payload["next_actions"][0]["action"] == "START_TRAINING"

        by_id_resp = client.get(f"/api/v1/iteration/{iteration_id}")
        assert by_id_resp.status_code == 200
        assert by_id_resp.json()["batch"]["risk_sample_count"] == 5600

        timeline_resp = client.get(f"/api/v1/iteration/{iteration_id}/timeline")
        assert timeline_resp.status_code == 200
        events = {item["event"] for item in timeline_resp.json()["timeline"]}
        assert {"DATA_INGESTED", "TRIGGER_CHECKED"}.issubset(events)

        batch_latest_resp = client.get(
            "/api/v1/iteration/batches/risk_spike_retrain/latest-run"
        )
        assert batch_latest_resp.status_code == 200
        assert batch_latest_resp.json()["iteration_id"] == iteration_id


def test_iteration_upload_batch_csv_records_iteration(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr(
            iteration_router,
            "DemoReplayService",
            lambda: _service(tmpdir),
        )
        monkeypatch.setattr(
            iteration_router,
            "resolve_project_path",
            lambda path: tmp_path / path,
        )
        client = TestClient(app)

        csv_content = (
            "enterprise_id,risk_label,recent_f1\n"
            "UPLOAD-001,1,0.82\n"
            "UPLOAD-002,0,0.82\n"
        )
        resp = client.post(
            "/api/v1/iteration/upload-batch",
            files={"file": ("enterprise_update.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["sample_count"] == 2
        assert payload["risk_sample_count"] == 1
        assert payload["recent_f1"] == 0.82
        assert payload["triggered"] is True
        assert "PERFORMANCE_DEGRADED" in payload["trigger_reasons"]
        assert payload["current_status"] == "TRAINING_PENDING"
        assert payload["dataset_kind"] == "auto"
        assert payload["risk_column_used"] == "risk_label"
        assert Path(payload["upload_report_path"]).exists()
        assert Path(payload["iteration"]["data_source"]["path"]).exists()

        latest_resp = client.get("/api/v1/iteration/latest")
        assert latest_resp.status_code == 200
        assert latest_resp.json()["iteration_id"] == payload["iteration_id"]


def test_iteration_upload_public_accident_without_risk_label(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr(
            iteration_router,
            "DemoReplayService",
            lambda: _service(tmpdir),
        )
        monkeypatch.setattr(
            iteration_router,
            "resolve_project_path",
            lambda path: tmp_path / path,
        )
        client = TestClient(app)

        csv_content = "企业名称,事故概述\n企业A,发生机械伤害事故\n企业B,执法处罚记录\n"
        resp = client.post(
            "/api/v1/iteration/upload-batch",
            data={"dataset_kind": "public_accident", "recent_f1_override": "0.84"},
            files={"file": ("public_accident.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["dataset_kind"] == "public_accident"
        assert payload["sample_count"] == 2
        assert payload["risk_sample_count"] == 2
        assert payload["recent_f1"] == 0.84
        assert payload["triggered"] is True
        assert "PERFORMANCE_DEGRADED" in payload["trigger_reasons"]
        assert payload["risk_detection_strategy"].startswith("public_accident_all_rows")
        assert "公开新增事故数据模式下" in " ".join(payload["parsing_warnings"])
        assert "recent_f1_override=0.8400" in " ".join(payload["parsing_warnings"])
        assert Path(payload["upload_report_path"]).exists()


def test_iteration_upload_uses_second_row_when_first_header_is_column_placeholder(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr(
            iteration_router,
            "DemoReplayService",
            lambda: _service(tmpdir),
        )
        monkeypatch.setattr(
            iteration_router,
            "resolve_project_path",
            lambda path: tmp_path / path,
        )
        client = TestClient(app)

        csv_content = "Column1,Column2\n企业名称,是否事故\n企业A,是\n企业B,否\n"
        resp = client.post(
            "/api/v1/iteration/upload-batch",
            data={"dataset_kind": "auto"},
            files={"file": ("placeholder_header.csv", csv_content.encode("gb18030"), "text/csv")},
        )

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["detected_encoding"] == "gb18030"
        assert payload["header_row_index"] == 2
        assert payload["detected_columns"] == ["企业名称", "是否事故"]
        assert payload["risk_column_used"] == "是否事故"
        assert payload["risk_sample_count"] == 1
        assert "第二行作为真实表头" in " ".join(payload["parsing_warnings"])


def test_iteration_upload_manual_labeled_requires_label_field(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr(
            iteration_router,
            "DemoReplayService",
            lambda: _service(tmpdir),
        )
        monkeypatch.setattr(
            iteration_router,
            "resolve_project_path",
            lambda path: tmp_path / path,
        )
        client = TestClient(app)

        csv_content = "enterprise_id,enterprise_name\nE1,企业A\n"
        resp = client.post(
            "/api/v1/iteration/upload-batch",
            data={"dataset_kind": "manual_labeled"},
            files={"file": ("manual_missing_label.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "手动标注 CSV 必须包含明确标签字段" in detail["message"]
        assert detail["detected_columns"] == ["enterprise_id", "enterprise_name"]
        assert "risk_label" in detail["suggested_columns"]


def test_iteration_demo_reset_api_archives_latest(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(
            iteration_router,
            "DemoReplayService",
            lambda: _service(tmpdir),
        )
        client = TestClient(app)

        load_resp = client.post("/api/v1/iteration/demo-batches/risk_spike_retrain/load")
        assert load_resp.status_code == 200

        reset_resp = client.post("/api/v1/iteration/demo/reset")
        assert reset_resp.status_code == 200
        payload = reset_resp.json()
        assert payload["status"] == "RESET"
        assert payload["archived_iterations"] >= 1
        assert payload["latest_iteration"] is None

        latest_resp = client.get("/api/v1/iteration/latest")
        assert latest_resp.status_code == 404


def test_iteration_report_download_api(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(
            iteration_router,
            "DemoReplayService",
            lambda: _service(tmpdir),
        )
        client = TestClient(app)

        load_resp = client.post("/api/v1/iteration/demo-batches/risk_spike_retrain/load")
        assert load_resp.status_code == 200
        iteration_id = load_resp.json()["iteration_id"]

        reports_resp = client.get(f"/api/v1/iteration/{iteration_id}/reports")
        assert reports_resp.status_code == 200
        assert reports_resp.json()["reports"]["replay"]["available"] is True

        download_resp = client.get(f"/api/v1/iteration/{iteration_id}/reports/replay/download")
        assert download_resp.status_code == 200
        assert download_resp.headers["content-type"].startswith("application/json")
        assert f'{iteration_id}_replay.json' in download_resp.headers["content-disposition"]
        assert download_resp.json()["iteration_id"] == iteration_id
