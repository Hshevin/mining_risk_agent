"""
迭代子模块测试：iteration/state、monitor、canary。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from mining_risk_serve.iteration.canary import CANARY_RATIOS, CanaryDeployment
from mining_risk_serve.iteration.monitor import ModelMonitor, TriggerSignal
from mining_risk_serve.iteration.state import (
    TRIGGER_REASON_RISK_SAMPLES,
    IterationRecord,
    IterationStateStore,
    TimelineEvent,
    build_iteration_id,
    build_timeline,
    utc_now_iso,
)


class TestIterationStateHelpers:
    def test_utc_now_iso_non_empty(self):
        s = utc_now_iso()
        assert len(s) > 10

    def test_build_iteration_id_stable_millis(self):
        i1 = build_iteration_id("batchA", timestamp=1.234)
        i2 = build_iteration_id("batchA", timestamp=1.234)
        assert i1 == i2
        assert i1.startswith("iter_batchA_")

    def test_timeline_event_roundtrip(self):
        ev = TimelineEvent(
            event="E",
            status="S",
            timestamp="t",
            message="m",
            details={"k": 1},
        )
        d = ev.to_dict()
        ev2 = TimelineEvent.from_dict(d)
        assert ev2.event == "E"
        assert ev2.details == {"k": 1}


class TestIterationRecord:
    def test_next_actions_not_triggered(self):
        rec = _minimal_record(triggered=False, status="IDLE")
        acts = rec.next_actions
        assert len(acts) == 1
        assert acts[0]["action"] == "MONITOR_NEXT_BATCH"

    def test_next_actions_training_pending(self):
        rec = _minimal_record(triggered=True, status="TRAINING_PENDING")
        acts = rec.next_actions
        enabled = [a for a in acts if a["enabled"]]
        assert any(a["action"] == "START_TRAINING" for a in enabled)

    def test_to_dict_contains_batch_and_thresholds(self):
        rec = _minimal_record(triggered=False, status="IDLE")
        d = rec.to_dict()
        assert d["batch"]["batch_id"] == "b1"
        assert d["thresholds"]["risk_sample_count"] == 5000


def _minimal_record(*, triggered: bool, status: str) -> IterationRecord:
    now = utc_now_iso()
    return IterationRecord(
        iteration_id="iter_x",
        batch_id="b1",
        data_source={"kind": "demo"},
        sample_count=10,
        risk_sample_count=2,
        recent_f1=0.9,
        trigger_threshold_samples=5000,
        trigger_threshold_f1=0.85,
        triggered=triggered,
        trigger_reasons=[] if not triggered else [TRIGGER_REASON_RISK_SAMPLES],
        current_status=status,
        timeline=[],
        report_path="",
        created_at=now,
        updated_at=now,
        metadata={},
    )


class TestIterationStateStore:
    def test_save_get_latest_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "iter.db")
            store = IterationStateStore(db)
            store.ensure_tables()
            now = utc_now_iso()
            rec = IterationRecord(
                iteration_id="iter_1",
                batch_id="b1",
                data_source={"x": 1},
                sample_count=100,
                risk_sample_count=10,
                recent_f1=0.8,
                trigger_threshold_samples=5000,
                trigger_threshold_f1=0.85,
                triggered=False,
                trigger_reasons=[],
                current_status="MONITORING",
                timeline=[
                    TimelineEvent(
                        event="DATA_INGESTED",
                        status="COMPLETED",
                        timestamp=now,
                        message="ok",
                        details={},
                    )
                ],
                report_path="/tmp/r.md",
                created_at=now,
                updated_at=now,
                metadata={"demo_mode": True},
            )
            store.save_record(rec)
            got = store.get_record("iter_1")
            assert got is not None
            assert got.batch_id == "b1"
            latest = store.get_latest_record()
            assert latest is not None
            assert latest.iteration_id == "iter_1"

            n = store.archive_active_records(reason="test cleanup")
            assert n == 1
            state = store.get_state()
            assert state.current_status == "IDLE"


class TestBuildTimeline:
    def test_build_timeline_not_triggered(self):
        ts = utc_now_iso()
        tl = build_timeline(
            batch_id="B",
            triggered=False,
            trigger_reasons=[],
            thresholds={"a": 1},
            observed={"n": 2},
            timestamp=ts,
        )
        assert tl[0].event == "DATA_INGESTED"
        assert tl[1].event == "TRIGGER_CHECKED"
        assert len(tl) == 2


class TestModelMonitor:
    def test_sample_and_performance_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "audit.db")
            m = ModelMonitor(db_path=db, sample_threshold=10, f1_threshold=0.99)
            assert m.get_cumulative_sample_count() == 0
            m.record_new_samples(5)
            assert m.get_cumulative_sample_count() == 5
            m.record_new_samples(20)
            sig = m.check_sample_threshold()
            assert isinstance(sig, TriggerSignal)
            assert sig.triggered is True
            m.record_performance("v1", 0.9, 0.8, 0.7, f1_score=0.5)
            psig = m.check_performance_threshold()
            assert psig.triggered is True


class TestCanaryDeployment:
    def test_ratio_ladder_and_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "canary.json")
            c = CanaryDeployment(config_path=path)
            assert c.get_current_ratio("m-v1") == 0.0
            c.set_traffic_ratio("m-v1", 0.1, operator="t")
            assert c.get_current_ratio("m-v1") == 0.1
            out = c.promote("m-v1", operator="t")
            assert out["current_ratio"] == 0.5
            hist = c.get_traffic_history("m-v1")
            assert len(hist) >= 2

    def test_invalid_ratio_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = CanaryDeployment(config_path=os.path.join(tmp, "c.json"))
            with pytest.raises(ValueError):
                c.set_traffic_ratio("m", 0.25)

    def test_rollback_sets_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = CanaryDeployment(config_path=os.path.join(tmp, "c.json"))
            c.set_traffic_ratio("m", 0.5)
            c.rollback("m")
            assert c.get_current_ratio("m") == 0.0


def test_canary_ratios_constant():
    assert CANARY_RATIOS == [0.0, 0.1, 0.5, 1.0]
