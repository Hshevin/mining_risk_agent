"""
两级终审状态机
PENDING_REVIEW -> SECURITY_APPROVED -> TECH_APPROVED -> STAGING -> PRODUCTION -> ARCHIVED
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from harness.agentfs import AgentFS
from utils.config import get_config
from utils.logger import get_logger

logger = get_logger(__name__)


class ApprovalStatus(Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    SECURITY_APPROVED = "SECURITY_APPROVED"
    TECH_APPROVED = "TECH_APPROVED"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


@dataclass
class ApprovalRecord:
    record_id: str
    model_version: str
    status: ApprovalStatus
    security_approver: Optional[str] = None
    security_approved_at: Optional[float] = None
    tech_approver: Optional[str] = None
    tech_approved_at: Optional[float] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[float] = None
    reject_reason: Optional[str] = None
    history: List[Dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class ApprovalFSM:
    """
    两级终审状态机
    """

    def __init__(self, db_path: Optional[str] = None):
        config = get_config()
        iteration_cfg = getattr(config, "iteration", None)
        if iteration_cfg is None:
            self.approvers = {
                "security": "security@example.com",
                "tech": "tech@example.com",
            }
        else:
            self.approvers = {
                "security": getattr(iteration_cfg.approvers, "security", "security@example.com"),
                "tech": getattr(iteration_cfg.approvers, "tech", "tech@example.com"),
            }
        self.db_path = db_path or "data/approval_fsm.db"
        self._ensure_table()
        self.agentfs = AgentFS()

    def _ensure_table(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS approval_records (
                record_id TEXT PRIMARY KEY,
                model_version TEXT NOT NULL,
                status TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_record(self, record_id: str, model_version: str) -> ApprovalRecord:
        """创建审批记录"""
        record = ApprovalRecord(
            record_id=record_id,
            model_version=model_version,
            status=ApprovalStatus.PENDING_REVIEW,
        )
        self._save_record(record)
        self._notify("审批已创建", f"模型 {model_version} 进入审批流程，当前状态: PENDING_REVIEW")
        self._log_to_agentfs("APPROVAL_CREATED", record)
        return record

    def _save_record(self, record: ApprovalRecord) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        data = json.dumps({
            "security_approver": record.security_approver,
            "security_approved_at": record.security_approved_at,
            "tech_approver": record.tech_approver,
            "tech_approved_at": record.tech_approved_at,
            "rejected_by": record.rejected_by,
            "rejected_at": record.rejected_at,
            "reject_reason": record.reject_reason,
            "history": record.history,
            "created_at": record.created_at,
        }, ensure_ascii=False)
        cursor.execute(
            """
            INSERT OR REPLACE INTO approval_records
            (record_id, model_version, status, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record.record_id, record.model_version, record.status.value, data, record.created_at, time.time()),
        )
        conn.commit()
        conn.close()

    def load_record(self, record_id: str) -> Optional[ApprovalRecord]:
        """加载审批记录"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM approval_records WHERE record_id = ?", (record_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        data = json.loads(row["data"])
        return ApprovalRecord(
            record_id=row["record_id"],
            model_version=row["model_version"],
            status=ApprovalStatus(row["status"]),
            security_approver=data.get("security_approver"),
            security_approved_at=data.get("security_approved_at"),
            tech_approver=data.get("tech_approver"),
            tech_approved_at=data.get("tech_approved_at"),
            rejected_by=data.get("rejected_by"),
            rejected_at=data.get("rejected_at"),
            reject_reason=data.get("reject_reason"),
            history=data.get("history", []),
            created_at=data.get("created_at", row["created_at"]),
        )

    def approve(
        self,
        record_id: str,
        approver_role: str,
        approver_name: str,
    ) -> ApprovalRecord:
        """
        提交审批结果
        approver_role: 'security' 或 'tech'
        """
        record = self.load_record(record_id)
        if record is None:
            raise ValueError(f"审批记录不存在: {record_id}")

        if record.status == ApprovalStatus.REJECTED:
            raise ValueError("审批已拒绝，无法继续")

        if approver_role not in ("security", "tech"):
            raise ValueError("审批角色必须是 security 或 tech")

        # 状态流转检查
        if approver_role == "security":
            if record.status != ApprovalStatus.PENDING_REVIEW:
                raise ValueError(f"安全审批必须在 PENDING_REVIEW 状态提交，当前: {record.status.value}")
            record.status = ApprovalStatus.SECURITY_APPROVED
            record.security_approver = approver_name
            record.security_approved_at = time.time()
            record.history.append({
                "from": "PENDING_REVIEW",
                "to": "SECURITY_APPROVED",
                "by": approver_name,
                "at": record.security_approved_at,
            })
            self._notify("安全审批通过", f"审批人 {approver_name} 通过了安全审批，模型: {record.model_version}")

        elif approver_role == "tech":
            if record.status != ApprovalStatus.SECURITY_APPROVED:
                raise ValueError(f"技术审批必须在 SECURITY_APPROVED 状态提交，当前: {record.status.value}")
            record.status = ApprovalStatus.TECH_APPROVED
            record.tech_approver = approver_name
            record.tech_approved_at = time.time()
            record.history.append({
                "from": "SECURITY_APPROVED",
                "to": "TECH_APPROVED",
                "by": approver_name,
                "at": record.tech_approved_at,
            })
            self._notify("技术审批通过", f"审批人 {approver_name} 通过了技术审批，模型: {record.model_version}")

        self._save_record(record)
        self._log_to_agentfs(f"APPROVAL_{approver_role.upper()}", record)
        logger.info(f"审批记录 {record_id} 状态更新为 {record.status.value}")
        return record

    def reject(self, record_id: str, approver_name: str, reason: str) -> ApprovalRecord:
        """拒绝审批"""
        record = self.load_record(record_id)
        if record is None:
            raise ValueError(f"审批记录不存在: {record_id}")

        record.status = ApprovalStatus.REJECTED
        record.rejected_by = approver_name
        record.rejected_at = time.time()
        record.reject_reason = reason
        record.history.append({
            "from": record.status.value,
            "to": "REJECTED",
            "by": approver_name,
            "at": record.rejected_at,
            "reason": reason,
        })
        self._save_record(record)
        self._notify("审批被拒绝", f"审批人 {approver_name} 拒绝了模型 {record.model_version}: {reason}")
        self._log_to_agentfs("APPROVAL_REJECTED", record)
        return record

    def promote_to_staging(self, record_id: str) -> ApprovalRecord:
        """推进到 STAGING 状态"""
        record = self.load_record(record_id)
        if record is None:
            raise ValueError(f"审批记录不存在: {record_id}")
        if record.status != ApprovalStatus.TECH_APPROVED:
            raise ValueError("必须先通过技术审批")

        record.status = ApprovalStatus.STAGING
        record.history.append({
            "from": "TECH_APPROVED",
            "to": "STAGING",
            "at": time.time(),
        })
        self._save_record(record)
        self._notify("进入预生产", f"模型 {record.model_version} 已进入 STAGING 试运行阶段")
        self._log_to_agentfs("PROMOTE_STAGING", record)
        return record

    def promote_to_production(self, record_id: str) -> ApprovalRecord:
        """推进到 PRODUCTION 状态"""
        record = self.load_record(record_id)
        if record is None:
            raise ValueError(f"审批记录不存在: {record_id}")
        if record.status != ApprovalStatus.STAGING:
            raise ValueError("必须完成 STAGING 试运行")

        record.status = ApprovalStatus.PRODUCTION
        record.history.append({
            "from": "STAGING",
            "to": "PRODUCTION",
            "at": time.time(),
        })
        self._save_record(record)
        self._notify("正式上线", f"模型 {record.model_version} 已正式上线")
        self._log_to_agentfs("PROMOTE_PRODUCTION", record)
        return record

    def archive(self, record_id: str) -> ApprovalRecord:
        """归档"""
        record = self.load_record(record_id)
        if record is None:
            raise ValueError(f"审批记录不存在: {record_id}")

        record.status = ApprovalStatus.ARCHIVED
        record.history.append({
            "from": "PRODUCTION",
            "to": "ARCHIVED",
            "at": time.time(),
        })
        self._save_record(record)
        self._log_to_agentfs("ARCHIVED", record)
        return record

    def _notify(self, title: str, message: str) -> None:
        """审批节点变更时发送通知（邮件/Webhook）"""
        # 邮件通知
        try:
            self._send_email(title, message)
        except Exception as e:
            logger.warning(f"邮件通知失败: {e}")

        # Webhook 通知
        try:
            self._send_webhook(title, message)
        except Exception as e:
            logger.warning(f"Webhook 通知失败: {e}")

    def _send_email(self, title: str, message: str) -> None:
        """发送邮件通知"""
        import smtplib
        from email.mime.text import MIMEText

        config = get_config()
        iteration_cfg = getattr(config, "iteration", None)
        if iteration_cfg is None:
            logger.debug("SMTP 未配置，跳过邮件发送")
            return
        smtp_cfg = iteration_cfg.smtp
        if not smtp_cfg.host:
            logger.debug("SMTP 未配置，跳过邮件发送")
            return

        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = smtp_cfg.from_addr or "agent@example.com"
        recipients = [self.approvers.get("security"), self.approvers.get("tech")]
        recipients = [r for r in recipients if r]
        msg["To"] = ", ".join(recipients)

        try:
            with smtplib.SMTP(smtp_cfg.host, smtp_cfg.port or 25) as server:
                if smtp_cfg.use_tls:
                    server.starttls()
                if smtp_cfg.username:
                    server.login(smtp_cfg.username, smtp_cfg.password)
                server.sendmail(msg["From"], recipients, msg.as_string())
            logger.info(f"邮件已发送: {title}")
        except Exception as e:
            logger.warning(f"邮件发送失败: {e}")

    def _send_webhook(self, title: str, message: str) -> None:
        """发送 Webhook 通知"""
        config = get_config()
        iteration_cfg = getattr(config, "iteration", None)
        webhook_url = iteration_cfg.webhook_url if iteration_cfg else None
        if not webhook_url:
            return

        import requests
        payload = {
            "title": title,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            logger.warning(f"Webhook 发送失败: {e}")

    def _log_to_agentfs(self, operation: str, record: ApprovalRecord) -> None:
        """全流程写入 AgentFS operation_log"""
        try:
            details = json.dumps({
                "record_id": record.record_id,
                "model_version": record.model_version,
                "status": record.status.value,
                "history": record.history,
            }, ensure_ascii=False)
            # AgentFS 的 operation_log 通过 _log_operation 写入，但它不对外暴露直接写入接口
            # 这里我们通过写 memory 文件来记录审批日志
            log_content = f"[{datetime.now().isoformat()}] {operation}: {details}\n"
            self.agentfs.write(
                f"memory/approval_{record.record_id}.log",
                log_content.encode("utf-8"),
                agent_id="approval_fsm",
            )
        except Exception as e:
            logger.warning(f"AgentFS 日志写入失败: {e}")


import os
