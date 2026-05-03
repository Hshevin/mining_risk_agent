"""
模型迭代模块单元测试
覆盖：监控阈值触发、Git Flow 分支创建、回归测试报告生成、审批状态机流转、灰度流量切换
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time

import numpy as np
import pandas as pd
import pytest

from iteration.approval_fsm import ApprovalFSM, ApprovalStatus
from iteration.canary import CanaryDeployment
from iteration.gitflow import GitFlowManager
from iteration.monitor import ModelMonitor
from iteration.regression_test import RegressionTester
from iteration.staging_monitor import StagingMonitor


class TestModelMonitor:
    """测试监控模块"""

    def test_should_retrain_sample_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            monitor = ModelMonitor(db_path=db_path, sample_threshold=5000, f1_threshold=0.85)

            # 模拟插入 5001 条样本
            monitor.record_new_samples(5001, source="test")

            should, reason, details = monitor.should_retrain()
            assert should is True
            assert reason == "SAMPLE_THRESHOLD_EXCEEDED"
            assert details["cumulative_samples"] == 5001

    def test_should_retrain_performance_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            monitor = ModelMonitor(db_path=db_path, sample_threshold=5000, f1_threshold=0.85)

            # 记录低 F1 性能
            monitor.record_performance("v1", 0.8, 0.8, 0.8, 0.84)
            should, reason, details = monitor.should_retrain()
            assert should is True
            assert reason == "PERFORMANCE_DEGRADED"
            assert details["recent_f1"] < 0.85

    def test_no_trigger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            monitor = ModelMonitor(db_path=db_path, sample_threshold=5000, f1_threshold=0.85)
            should, reason, details = monitor.should_retrain()
            assert should is False
            assert reason is None

    def test_monitoring_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            monitor = ModelMonitor(db_path=db_path, sample_threshold=5000, f1_threshold=0.85)
            monitor.record_new_samples(100, source="test")
            monitor.record_performance("v1", 0.9, 0.9, 0.9, 0.9)
            summary = monitor.get_monitoring_summary()
            assert summary["cumulative_samples"] == 100
            assert summary["recent_f1"] == 0.9
            assert summary["sample_triggered"] is False
            assert summary["performance_triggered"] is False


class TestGitFlowManager:
    """测试 Git Flow 分支管理"""

    def test_create_feature_branch(self):
        tmpdir = tempfile.mkdtemp()
        try:
            # 初始化 git 仓库
            os.system(f'git init "{tmpdir}"')
            os.system(f'git -C "{tmpdir}" config user.email "test@test.com"')
            os.system(f'git -C "{tmpdir}" config user.name "Test"')
            with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as f:
                f.write("# test")
            os.system(f'git -C "{tmpdir}" add .')
            os.system(f'git -C "{tmpdir}" commit -m "init"')

            gm = GitFlowManager(repo_path=tmpdir)
            branch = gm.create_feature_branch("v2")
            assert branch == "feature/model_v2"

            # 验证分支存在
            result = os.popen(f'git -C "{tmpdir}" branch').read()
            assert "feature/model_v2" in result
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_generate_pr_template(self):
        gm = GitFlowManager(repo_path=".")
        old_m = {"test_accuracy": 0.85, "test_f1": 0.84}
        new_m = {"test_accuracy": 0.88, "test_f1": 0.87}
        pr = gm.generate_pr_template(old_m, new_m, shap_stability=0.82)
        assert "模型迭代 PR" in pr
        assert "0.8400 → 0.8700" in pr
        assert "SHAP 稳定性" in pr

    def test_protect_main_branch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.system(f'git init "{tmpdir}"')
            gm = GitFlowManager(repo_path=tmpdir)
            gm.protect_main_branch()
            hook = os.path.join(tmpdir, ".git", "hooks", "pre-push")
            assert os.path.exists(hook)
            with open(hook, "r", encoding="utf-8") as f:
                content = f.read()
            assert "protected_branch" in content


class TestRegressionTester:
    """测试回归测试"""

    def test_regression_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建两个相同的模型用于测试
            from model.stacking import StackingRiskModel
            np.random.seed(42)
            X = pd.DataFrame(np.random.randn(100, 5))
            y = pd.Series([0, 1, 2, 3] * 25)
            model = StackingRiskModel()
            model.fit(X, y)

            old_path = os.path.join(tmpdir, "old.pkl")
            new_path = os.path.join(tmpdir, "new.pkl")
            model.save(old_path)
            model.save(new_path)

            # 创建测试数据 CSV
            test_csv = os.path.join(tmpdir, "test.csv")
            df = X.copy()
            df["label"] = y
            df.to_csv(test_csv, index=False)

            output = os.path.join(tmpdir, "regression_report.json")
            tester = RegressionTester(
                old_model_path=old_path,
                new_model_path=new_path,
                test_data_path=test_csv,
            )
            report = tester.run(output_path=output)

            assert report["status"] in ("PASS", "DEGRADED")
            assert "old_metrics" in report
            assert "new_metrics" in report
            assert os.path.exists(output)

            with open(output, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["status"] == report["status"]


class TestApprovalFSM:
    """测试审批状态机"""

    def test_full_approval_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "approval.db")
            fsm = ApprovalFSM(db_path=db_path)

            rec = fsm.create_record("rec-001", "v2")
            assert rec.status == ApprovalStatus.PENDING_REVIEW

            # 安全审批
            rec = fsm.approve("rec-001", "security", "张三")
            assert rec.status == ApprovalStatus.SECURITY_APPROVED
            assert rec.security_approver == "张三"

            # 技术审批
            rec = fsm.approve("rec-001", "tech", "李四")
            assert rec.status == ApprovalStatus.TECH_APPROVED
            assert rec.tech_approver == "李四"

            # 推进到 STAGING
            rec = fsm.promote_to_staging("rec-001")
            assert rec.status == ApprovalStatus.STAGING

            # 推进到 PRODUCTION
            rec = fsm.promote_to_production("rec-001")
            assert rec.status == ApprovalStatus.PRODUCTION

            # 归档
            rec = fsm.archive("rec-001")
            assert rec.status == ApprovalStatus.ARCHIVED

    def test_reject(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "approval.db")
            fsm = ApprovalFSM(db_path=db_path)
            fsm.create_record("rec-002", "v3")
            rec = fsm.reject("rec-002", "王五", "模型存在严重偏差")
            assert rec.status == ApprovalStatus.REJECTED
            assert rec.reject_reason == "模型存在严重偏差"

    def test_invalid_transition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "approval.db")
            fsm = ApprovalFSM(db_path=db_path)
            fsm.create_record("rec-003", "v4")
            with pytest.raises(ValueError):
                # 未通过安全审批不能直接技术审批
                fsm.approve("rec-003", "tech", "李四")


class TestStagingMonitor:
    """测试预生产监控"""

    def test_simulation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = StagingMonitor(
                model_version="v2",
                duration_hours=1,
                sample_interval_minutes=5,
                logs_dir=tmpdir,
            )
            report = monitor.run_simulation(num_samples=12)
            assert report["model_version"] == "v2"
            assert report["total_samples"] == 12
            assert "latency" in report
            assert report["status"] in ("CANARY_READY", "ROLLBACK")

            # 确认日志文件非空
            log_files = [f for f in os.listdir(tmpdir) if f.startswith("staging_monitor_")]
            assert len(log_files) > 0
            for lf in log_files:
                with open(os.path.join(tmpdir, lf), "r", encoding="utf-8") as f:
                    data = json.load(f)
                assert "latency_ms" in data
                assert "confidence" in data


class TestCanaryDeployment:
    """测试灰度发布"""

    def test_traffic_ratio_steps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "canary.json")
            cd = CanaryDeployment(config_path=config_path)

            result = cd.set_traffic_ratio("v2", 0.1, operator="test")
            assert result["current_ratio"] == 0.1

            result = cd.promote("v2", operator="test")
            assert result["current_ratio"] == 0.5

            result = cd.promote("v2", operator="test")
            assert result["current_ratio"] == 1.0

            result = cd.rollback("v2", operator="test")
            assert result["current_ratio"] == 0.0

    def test_invalid_ratio(self):
        cd = CanaryDeployment(config_path="tmp_canary.json")
        with pytest.raises(ValueError):
            cd.set_traffic_ratio("v2", 0.3)
