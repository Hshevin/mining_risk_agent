import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  DemoIterationAction,
  downloadIterationReport,
  fetchDemoBatches,
  fetchIterationAudit,
  fetchIterationReport,
  fetchIterationReports,
  fetchIterationTimeline,
  fetchLatestIteration,
  loadDemoBatch,
  resetIterationDemoState,
  runDemoIterationAction,
  uploadIterationBatch,
} from "../api/client";
import type {
  DatasetKind,
  DemoBatch,
  DemoReplayLoadResponse,
  IterationAuditResponse,
  IterationReportResponse,
  IterationReportsResponse,
  IterationRecord,
  IterationTimelineEvent,
  IterationUploadBatchResponse,
  UploadParsingReport,
} from "../api/types";
import JsonView from "../components/JsonView";
import ScadaCard from "../components/ScadaCard";

const DEFAULT_RISK_SAMPLE_THRESHOLD = 5000;
const DEFAULT_F1_THRESHOLD = 0.85;

const EVENT_LABELS: Record<string, string> = {
  DATA_INGESTED: "数据入库",
  TRIGGER_CHECKED: "触发判断",
  CANDIDATE_TRAINING: "候选模型训练",
  REGRESSION_TEST: "回归测试",
  DRIFT_ANALYSIS: "Drift 分析",
  PR_CREATED: "PR 门禁",
  CI_PASSED: "CI 预检",
  APPROVAL_SAFETY: "安全审批",
  APPROVAL_TECH: "技术审批",
  STAGING: "预生产",
  CANARY: "灰度发布",
  AUDIT_ARCHIVE: "审计归档",
};

const STATUS_LABELS: Record<string, string> = {
  COMPLETED: "已完成",
  PENDING: "等待前置步骤",
  NOT_STARTED: "等待前置步骤",
  RUNNING: "运行中",
  FAILED: "失败",
  BLOCKED: "已阻断",
  PASSED: "通过",
  NO_RETRAIN_REQUIRED: "无需重训",
  TRAINING_PENDING: "待训练",
  REGRESSION_PENDING: "待回归测试",
  DRIFT_PENDING: "待 Drift 分析",
  PR_PENDING: "待 PR 门禁",
  CI_PENDING: "待 CI 预检",
  CI_RUNNING: "CI 运行中",
  CI_FAILED: "CI 阻断",
  APPROVAL_PENDING: "待安全审批",
  SAFETY_APPROVED: "安全已批",
  STAGING_PENDING: "待预生产",
  STAGING_RUNNING: "预生产运行中",
  CANARY_READY: "待灰度",
  CANARY_RUNNING: "灰度中",
  PRODUCTION_RELEASED: "已发布生产",
  REGRESSION_BLOCKED: "回归阻断",
  DRIFT_BLOCKED: "Drift 阻断",
};

const REASON_LABELS: Record<string, string> = {
  RISK_SAMPLE_THRESHOLD_EXCEEDED: "风险样本超过阈值",
  PERFORMANCE_DEGRADED: "近期 F1 低于阈值",
};

const SCENARIO_LABELS: Record<string, string> = {
  NORMAL_BATCH: "常规批次",
  RISK_SAMPLE_SPIKE: "风险样本激增",
  RECENT_F1_DROP: "近期 F1 下降",
  REGRESSION_BLOCK: "历史回归阻断",
  DRIFT_HIGH_BLOCK: "历史 Drift 阻断",
  REGRESSION_FAIL: "回归门禁失败",
  DRIFT_HIGH: "高 Drift 风险",
  UPLOAD_BATCH: "上传 CSV",
};

const ACTION_LABELS: Record<string, string> = {
  MONITOR_NEXT_BATCH: "继续监控下一批",
  SELECT_BATCH: "请选择批次",
  START_TRAINING: "启动候选模型训练",
  TRAIN_CANDIDATE: "启动候选模型训练",
  RUN_REGRESSION: "运行回归测试",
  RUN_REGRESSION_TEST: "运行回归测试",
  RUN_DRIFT_ANALYSIS: "运行 Drift 分析",
  CREATE_PR: "生成 PR 门禁",
  RUN_CI_PRECHECK: "运行 CI 预检",
  APPROVE_SAFETY: "安全审批",
  APPROVE_TECH: "技术审批",
  START_STAGING: "启动预生产",
  COMPLETE_STAGING_DEMO: "完成预生产演示",
  ADVANCE_CANARY: "推进灰度",
  ARCHIVE_AUDIT: "生成审计归档",
  VIEW_AUDIT: "查看审计归档",
};

const API_ACTION_LABELS: Record<DemoIterationAction, string> = {
  train: "候选模型训练",
  "regression-test": "回归测试",
  "drift-analysis": "Drift 分析",
  "pr/create": "PR 门禁",
  "ci/run": "CI 预检",
  "approve/safety": "安全审批",
  "approve/tech": "技术审批",
  "staging/start": "预生产启动",
  "staging/complete-demo": "预生产完成",
  "canary/advance": "灰度推进",
  "demo/run-next-step": "下一步",
  "demo/run-to-end": "完整链路",
};

const MESSAGE_LABELS: Record<string, string> = {
  "Demo batch data ingested": "演示批次已入库",
  "Retraining trigger rules evaluated": "重训触发规则已完成判断",
  "Pending after trigger check": "等待触发后的下一阶段",
  "Demo candidate model artifact generated": "候选模型演示产物已生成",
  "Regression gate passed": "回归门禁通过",
  "Regression gate blocked candidate model": "回归门禁阻断候选模型",
  "Drift gate passed": "Drift 门禁通过",
  "Drift gate blocked release": "Drift 门禁阻断发布",
  "Local PR metadata generated": "PR 门禁元数据已生成",
  "Demo CI precheck started": "CI 预检已启动",
  "CI precheck passed": "CI 预检通过",
  "CI precheck blocked approval": "CI 预检阻断审批",
  "safety approval recorded": "安全审批已记录",
  "tech approval recorded": "技术审批已记录",
  "Demo staging started with 30 second compressed window": "预生产已启动，演示窗口压缩为 30 秒",
  "Demo staging completed": "预生产演示已完成",
  "Canary advanced to 0.1": "灰度已推进到 10%",
  "Canary advanced to 0.5": "灰度已推进到 50%",
  "Canary reached 100%; demo production pointer updated": "灰度已到 100%，演示生产指针已更新",
  "Iteration audit archive written": "迭代审计归档已写入",
};

const TEXT_REPLACEMENTS: Array<[RegExp, string]> = [
  [/candidate model F1 below release threshold in demo batch/g, "候选模型 F1 低于发布阈值"],
  [/candidate f1_macro < 0\.85/g, "候选模型 f1_macro < 0.85"],
  [/drift risk_level=high exceeds demo release gate/g, "Drift 风险等级 high 超出发布门禁"],
  [/candidate model artifact is missing/g, "候选模型产物缺失"],
  [/CI precheck must pass before safety approval\./g, "CI 预检通过后才允许安全审批。"],
  [/Batch did not trigger retraining\./g, "该批次未触发重训。"],
  [/normal_batch is not allowed to train because retrain_required=false/g, "normal_batch 未触发重训，不允许启动训练"],
];

const WORKFLOW_STEPS = [
  { event: "DATA_INGESTED", aliases: ["DATA_INGESTED"] },
  { event: "TRIGGER_CHECKED", aliases: ["TRIGGER_CHECKED"] },
  { event: "CANDIDATE_TRAINING", aliases: ["TRAINING_PENDING", "CANDIDATE_TRAINING"] },
  { event: "REGRESSION_TEST", aliases: ["REGRESSION_PENDING", "REGRESSION_TEST", "REGRESSION_BLOCKED"] },
  { event: "DRIFT_ANALYSIS", aliases: ["DRIFT_PENDING", "DRIFT_ANALYSIS", "DRIFT_BLOCKED"] },
  { event: "PR_CREATED", aliases: ["PR_PENDING", "PR_CREATED"] },
  { event: "CI_PASSED", aliases: ["CI_PENDING", "CI_RUNNING", "CI_PASSED", "CI_FAILED"] },
  { event: "APPROVAL_SAFETY", aliases: ["APPROVAL_PENDING", "APPROVAL_SAFETY"] },
  { event: "APPROVAL_TECH", aliases: ["SAFETY_APPROVED", "APPROVAL_TECH"] },
  { event: "STAGING", aliases: ["STAGING_PENDING", "STAGING_RUNNING", "STAGING"] },
  { event: "CANARY", aliases: ["CANARY_READY", "CANARY_RUNNING", "CANARY"] },
  { event: "AUDIT_ARCHIVE", aliases: ["AUDIT_ARCHIVE", "ARCHIVE_PENDING"] },
];

const REPORT_TYPES = [
  { type: "replay", label: "入库回放报告" },
  { type: "upload", label: "上传解析报告" },
  { type: "training", label: "训练报告" },
  { type: "regression", label: "回归测试报告" },
  { type: "drift", label: "Drift 报告" },
  { type: "pr", label: "PR 元数据" },
  { type: "ci", label: "CI 报告" },
  { type: "staging", label: "预生产报告" },
  { type: "audit", label: "审计归档" },
];

const DATASET_KIND_LABELS: Record<DatasetKind, string> = {
  auto: "自动识别",
  public_accident: "公开新增事故数据",
  manual_labeled: "手动标注 CSV",
};

function formatInteger(value?: number | null): string {
  return typeof value === "number" ? value.toLocaleString() : "-";
}

function formatF1(value?: number | null): string {
  return typeof value === "number" ? value.toFixed(3) : "-";
}

function formatPct(value?: number | null): string {
  if (typeof value !== "number") return "0%";
  return `${Math.round(value * 100)}%`;
}

function yesNo(value?: boolean | null): string {
  return value ? "是" : "否";
}

function passFail(value: unknown): string {
  if (typeof value !== "boolean") return "-";
  return value ? "通过" : "未通过";
}

function formatTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function labelFor(map: Record<string, string>, key?: string | null): string {
  if (!key) return "-";
  return map[key] ?? key;
}

function numberFrom(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusTone(status: string): { color: string; border: string; bg: string } {
  const normalized = status.toUpperCase();
  if (["COMPLETED", "PASSED", "CI_PASSED", "PRODUCTION_RELEASED", "NO_RETRAIN_REQUIRED"].includes(normalized)) {
    return { color: "#6ee7b7", border: "#10b98144", bg: "rgba(16, 185, 129, 0.08)" };
  }
  if (["PENDING", "RUNNING", "TRAINING_PENDING", "PR_PENDING", "CI_PENDING", "CI_RUNNING", "CANARY_RUNNING"].includes(normalized)) {
    return { color: "#fde68a", border: "#eab30844", bg: "rgba(234, 179, 8, 0.08)" };
  }
  if (["FAILED", "BLOCKED", "REGRESSION_BLOCKED", "DRIFT_BLOCKED", "CI_FAILED"].includes(normalized)) {
    return { color: "#fca5a5", border: "#ef444444", bg: "rgba(239, 68, 68, 0.08)" };
  }
  return { color: "#93c5fd", border: "#3b82f644", bg: "rgba(59, 130, 246, 0.08)" };
}

function StatusBadge({ status }: { status: string }) {
  const tone = statusTone(status);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        minHeight: 24,
        padding: "3px 8px",
        borderRadius: 4,
        border: `1px solid ${tone.border}`,
        background: tone.bg,
        color: tone.color,
        fontSize: 11,
        fontWeight: 700,
        justifyContent: "center",
        lineHeight: 1.2,
        maxWidth: "100%",
        overflowWrap: "anywhere",
        textAlign: "center",
        whiteSpace: "normal",
      }}
    >
      {labelFor(STATUS_LABELS, status)}
    </span>
  );
}

function timelineClass(status: string): string {
  const normalized = status.toUpperCase();
  if (["COMPLETED", "PASSED", "NO_RETRAIN_REQUIRED"].includes(normalized)) return "completed";
  if (["RUNNING", "IN_PROGRESS"].includes(normalized)) return "running";
  if (["FAILED", "BLOCKED", "ERROR"].includes(normalized)) return "failed";
  return "";
}

function scenarioName(batch: DemoBatch): string {
  return labelFor(SCENARIO_LABELS, batch.scenario) || batch.batch_id;
}

function expectedEffect(batch: DemoBatch): { label: string; tone: string } {
  const id = batch.batch_id.toLowerCase();
  const scenario = (batch.scenario ?? "").toUpperCase();
  if (id === "regression_fail" || scenario.includes("REGRESSION_FAIL")) {
    return { label: "回归测试阻断", tone: "danger" };
  }
  if (id === "drift_high" || scenario.includes("DRIFT_HIGH")) {
    return { label: "Drift 高风险阻断", tone: "danger" };
  }
  if (batch.risk_sample_count > DEFAULT_RISK_SAMPLE_THRESHOLD) {
    return { label: "风险样本触发重训", tone: "warn" };
  }
  if (batch.recent_f1 < DEFAULT_F1_THRESHOLD) {
    return { label: "F1 下降触发重训", tone: "warn" };
  }
  return { label: "无需重训", tone: "ok" };
}

function buildWorkflowTimeline(events: IterationTimelineEvent[]): IterationTimelineEvent[] {
  const byStep = new Map<string, IterationTimelineEvent>();
  for (const event of events) {
    const step = WORKFLOW_STEPS.find((item) => item.aliases.includes(event.event));
    if (!step) continue;
    byStep.set(step.event, {
      ...event,
      event: step.event,
      details: { ...(event.details ?? {}), backend_event: event.event },
    });
  }
  return WORKFLOW_STEPS.map((step) => {
    const event = byStep.get(step.event);
    if (event) return event;
    return {
      event: step.event,
      status: "NOT_STARTED",
      timestamp: "",
      message: "等待前置步骤",
      details: {},
    };
  });
}

function reasonSummary(reasons: string[]): string {
  if (!reasons.length) return "无触发原因";
  return reasons.map((item) => labelFor(REASON_LABELS, item)).join(" / ");
}

function actionLabel(action?: string | null): string {
  if (!action) return "-";
  return ACTION_LABELS[action] ?? action;
}

function apiActionLabel(action: DemoIterationAction): string {
  return API_ACTION_LABELS[action] ?? action;
}

function localizeText(value?: unknown): string {
  if (typeof value !== "string" || !value) return "";
  let text = MESSAGE_LABELS[value] ?? value;
  for (const [pattern, replacement] of TEXT_REPLACEMENTS) {
    text = text.replace(pattern, replacement);
  }
  return text;
}

function reportField(record: IterationRecord | null, key: keyof IterationRecord): unknown {
  if (!record) return null;
  const direct = record[key];
  if (direct !== undefined && direct !== null) return direct;
  return record.metadata?.[String(key)] ?? null;
}

function uploadReportFrom(record: IterationRecord | null, uploadResult: IterationUploadBatchResponse | null): UploadParsingReport | null {
  if (uploadResult?.upload_report) return uploadResult.upload_report;
  const metadataReport = record?.metadata?.upload_report;
  return asRecord(metadataReport) as UploadParsingReport | null;
}

function firstEnabledAction(record: IterationRecord | null): string {
  const action = record?.next_actions?.find((item) => item.enabled) ?? record?.next_actions?.[0];
  if (action) return actionLabel(String(action.action));
  if (!record) return "加载演示批次或上传 CSV";
  return record.triggered ? "等待迭代阶段推进" : "继续监控下一批";
}

function reportLabel(reportType: string): string {
  return REPORT_TYPES.find((item) => item.type === reportType)?.label ?? reportType;
}

export default function IterationPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [batches, setBatches] = useState<DemoBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [latest, setLatest] = useState<IterationRecord | null>(null);
  const [timeline, setTimeline] = useState<IterationTimelineEvent[]>([]);
  const [lastReplay, setLastReplay] = useState<DemoReplayLoadResponse | null>(null);
  const [audit, setAudit] = useState<IterationAuditResponse | null>(null);
  const [reports, setReports] = useState<IterationReportsResponse | null>(null);
  const [activeReport, setActiveReport] = useState<IterationReportResponse | null>(null);
  const [uploadResult, setUploadResult] = useState<IterationUploadBatchResponse | null>(null);
  const [datasetKind, setDatasetKind] = useState<DatasetKind>("auto");
  const [recentF1Override, setRecentF1Override] = useState("");
  const [loadingBatches, setLoadingBatches] = useState(false);
  const [loadingLatest, setLoadingLatest] = useState(false);
  const [loadingBatchId, setLoadingBatchId] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);

  const selectedBatch = useMemo(
    () => batches.find((item) => item.batch_id === selectedBatchId) ?? null,
    [batches, selectedBatchId],
  );

  const riskThreshold = numberFrom(
    latest?.thresholds?.risk_sample_count,
    latest?.trigger_threshold_samples ?? DEFAULT_RISK_SAMPLE_THRESHOLD,
  );
  const f1Threshold = numberFrom(
    latest?.thresholds?.recent_f1,
    latest?.trigger_threshold_f1 ?? DEFAULT_F1_THRESHOLD,
  );
  const backendTimeline = timeline.length > 0 ? timeline : latest?.timeline ?? [];
  const displayTimeline = buildWorkflowTimeline(backendTimeline);
  const sourceType = latest?.data_source?.type ?? "demo_replay";
  const sourceLabel = sourceType === "demo_replay" ? "演示回放" : "上传 CSV";
  const loadedBatchId = latest?.batch_id ?? lastReplay?.metadata.batch_id ?? "未加载";
  const reportPath = latest?.report_path ?? lastReplay?.report_path ?? "";
  const triggerReasons = latest?.trigger_reasons ?? lastReplay?.trigger_reasons ?? [];
  const triggered = latest?.triggered ?? lastReplay?.triggered ?? false;
  const currentStatus = latest?.current_status ?? lastReplay?.current_status ?? "NOT_STARTED";
  const gateBlocked = ["REGRESSION_BLOCKED", "DRIFT_BLOCKED", "CI_FAILED", "BLOCKED"].includes(
    currentStatus.toUpperCase(),
  );
  const currentBatch = latest ? batches.find((batch) => batch.batch_id === latest.batch_id) : null;
  const currentScenario = currentBatch ? scenarioName(currentBatch) : loadedBatchId;
  const enabledActionCode =
    latest?.next_actions?.find((item) => item.enabled)?.action ?? "SELECT_BATCH";
  const uploadIsExcel = /\.(xlsx|xls)$/i.test(uploadFile?.name ?? "");
  const trainingReport = asRecord(reportField(latest, "training_report"));
  const regressionReport = asRecord(reportField(latest, "regression_report"));
  const driftReport = asRecord(reportField(latest, "drift_report"));
  const prMetadata = asRecord(reportField(latest, "pr_metadata"));
  const ciReport = asRecord(reportField(latest, "ci_report"));
  const stagingReport = asRecord(reportField(latest, "staging_report"));
  const approvalLogs = latest?.approval_logs ?? [];
  const canaryPercentage = latest?.canary_percentage ?? 0;
  const auditPath = latest?.audit_archive_path ?? "";
  const prMetadataPath = String(reportField(latest, "pr_metadata_path") ?? prMetadata?.local_pr_metadata_path ?? "-");
  const ciReportPath = String(reportField(latest, "ci_report_path") ?? "-");
  const reportItems = reports?.reports ?? {};
  const blockedReason = localizeText(latest?.blocked_reason);
  const hasRunnableBackendAction =
    latest?.next_actions?.some((item) => item.enabled && item.action !== "VIEW_AUDIT") ?? false;
  const uploadReport = uploadReportFrom(latest, uploadResult);
  const uploadReportPath = uploadResult?.upload_report_path ?? String(latest?.metadata?.upload_report_path ?? "");

  useEffect(() => {
    void loadBatchList();
    void refreshLatestStatus();
  }, []);

  function actionEnabled(actions: string[]): boolean {
    if (!latest || runningAction) return false;
    return latest.next_actions?.some((item) => item.enabled && actions.includes(item.action));
  }

  async function refreshReports(iterationId?: string | null) {
    if (!iterationId) {
      setReports(null);
      setActiveReport(null);
      return;
    }
    const result = await fetchIterationReports(iterationId);
    setReports(result);
    if (!result) setActiveReport(null);
  }

  async function loadBatchList() {
    setLoadingBatches(true);
    setBatchError(null);
    try {
      const data = await fetchDemoBatches();
      setBatches(data);
      const defaultBatch = data.find((item) => item.batch_id === "risk_spike_retrain") ?? data[0];
      setSelectedBatchId((prev) => prev || defaultBatch?.batch_id || "");
    } catch (error) {
      setBatches([]);
      setBatchError(errorText(error));
    } finally {
      setLoadingBatches(false);
    }
  }

  async function refreshLatestStatus(): Promise<IterationRecord | null> {
    setLoadingLatest(true);
    setOperationError(null);
    try {
      const record = await fetchLatestIteration();
      if (!record) {
        setLatest(null);
        setTimeline([]);
        setReports(null);
        setActiveReport(null);
        return null;
      }
      setLatest(record);
      setSelectedBatchId((prev) => prev || record.batch_id);
      const timelineResponse = await fetchIterationTimeline(record.iteration_id);
      setTimeline(timelineResponse?.timeline ?? record.timeline ?? []);
      await refreshReports(record.iteration_id);
      return record;
    } catch (error) {
      setOperationError(errorText(error));
      return null;
    } finally {
      setLoadingLatest(false);
    }
  }

  async function handleLoadBatch() {
    if (!selectedBatchId) return;
    setLoadingBatchId(selectedBatchId);
    setMessage(null);
    setAudit(null);
    setReports(null);
    setActiveReport(null);
    setUploadResult(null);
    setOperationError(null);
    try {
      const result = await loadDemoBatch(selectedBatchId);
      if (!result) throw new Error("后端未返回批次入库结果");
      setLastReplay(result);
      setLatest(result.iteration ?? null);
      setTimeline(result.timeline ?? result.iteration?.timeline ?? []);
      setMessage(`演示批次已入库：${result.metadata.batch_id}`);
      await refreshLatestStatus();
    } catch (error) {
      setOperationError(errorText(error));
    } finally {
      setLoadingBatchId(null);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setUploadFile(file);
    setMessage(null);
    setOperationError(null);
  }

  async function handleUploadBatch() {
    if (!uploadFile || uploadIsExcel) return;
    setUploading(true);
    setMessage(null);
    setAudit(null);
    setReports(null);
    setActiveReport(null);
    setOperationError(null);
    try {
      const result = await uploadIterationBatch(uploadFile, datasetKind, recentF1Override);
      setUploadResult(result);
      setLatest(result.iteration);
      setTimeline(result.timeline ?? result.iteration.timeline ?? []);
      setSelectedBatchId("");
      setLastReplay(null);
      setMessage(
        `上传批次已入库：${result.batch_id}，风险样本 ${formatInteger(
          result.risk_sample_count,
        )}，F1 ${formatF1(result.recent_f1)}`,
      );
      setUploadFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refreshLatestStatus();
    } catch (error) {
      setOperationError(errorText(error));
    } finally {
      setUploading(false);
    }
  }

  async function handleResetDemoState() {
    setRunningAction("reset");
    setMessage(null);
    setOperationError(null);
    try {
      const result = await resetIterationDemoState();
      setLatest(null);
      setTimeline([]);
      setLastReplay(null);
      setAudit(null);
      setReports(null);
      setActiveReport(null);
      setUploadResult(null);
      setMessage(`${result.message} 已归档记录 ${result.archived_iterations} 条。`);
      await loadBatchList();
    } catch (error) {
      setOperationError(errorText(error));
    } finally {
      setRunningAction(null);
    }
  }

  async function runAction(label: string, action: DemoIterationAction, body?: Record<string, unknown>) {
    if (!latest) return;
    setRunningAction(label);
    setMessage(null);
    setOperationError(null);
    try {
      const result = await runDemoIterationAction(latest.iteration_id, action, body);
      setLatest(result.iteration);
      setTimeline(result.timeline ?? result.iteration.timeline ?? []);
      await refreshReports(result.iteration.iteration_id);
      setMessage(`${apiActionLabel(action)}已完成，当前状态：${labelFor(STATUS_LABELS, result.current_status)}`);
      if (result.iteration.audit_archive_path) {
        const nextAudit = await fetchIterationAudit(result.iteration.iteration_id);
        setAudit(nextAudit);
      }
    } catch (error) {
      setOperationError(errorText(error));
      await refreshLatestStatus();
    } finally {
      setRunningAction(null);
    }
  }

  async function handleFetchAudit() {
    if (!latest) return;
    setRunningAction("audit");
    setOperationError(null);
    try {
      const result = await fetchIterationAudit(latest.iteration_id);
      if (!result) throw new Error("审计归档尚未生成");
      setAudit(result);
      setMessage(`已读取审计归档：${result.audit_archive_path}`);
    } catch (error) {
      setOperationError(errorText(error));
    } finally {
      setRunningAction(null);
    }
  }

  async function handleViewReport(reportType: string) {
    if (!latest) return;
    setRunningAction(`report-${reportType}`);
    setOperationError(null);
    try {
      const result = await fetchIterationReport(latest.iteration_id, reportType);
      if (!result) throw new Error(`${reportLabel(reportType)}尚未生成`);
      setActiveReport(result);
      setMessage(`已读取${reportLabel(reportType)}：${result.path}`);
    } catch (error) {
      setOperationError(errorText(error));
    } finally {
      setRunningAction(null);
    }
  }

  async function handleDownloadReport(reportType: string) {
    if (!latest) return;
    setRunningAction(`download-${reportType}`);
    setOperationError(null);
    try {
      await downloadIterationReport(latest.iteration_id, reportType);
      setMessage(`已下载 ${latest.iteration_id}_${reportType}.json`);
    } catch (error) {
      setOperationError(errorText(error));
    } finally {
      setRunningAction(null);
    }
  }

  function handleReportClick() {
    if (!reportPath) return;
    setMessage(`回放报告路径：${reportPath}`);
  }

  const ciFailedReasons = Array.isArray(ciReport?.failed_reasons)
    ? ciReport.failed_reasons.map((item) => localizeText(item)).join("；") || "-"
    : "-";

  return (
    <div>
      <div className="section-title">模型迭代路演 | Demo Replay / demo_fast_mode</div>

      <div className="row cols-4">
        <ScadaCard title="数据来源" value={sourceLabel} sub={sourceType} glowClass="glow-blue" />
        <ScadaCard
          title="当前批次"
          value={loadedBatchId}
          sub={latest ? currentScenario : "加载演示批次或上传 CSV"}
          glowClass={latest ? "glow-white" : "glow-yellow"}
        />
        <ScadaCard
          title="风险样本 / 门禁"
          value={`${formatInteger(latest?.risk_sample_count)}/${formatInteger(riskThreshold)}`}
          sub={latest ? `样本总数 ${formatInteger(latest.sample_count)}` : "等待批次入库"}
          glowClass={latest && latest.risk_sample_count > riskThreshold ? "glow-red" : "glow-green"}
        />
        <ScadaCard
          title="近期 F1 / 门禁"
          value={`${formatF1(latest?.recent_f1)}/${formatF1(f1Threshold)}`}
          sub={latest ? latest.iteration_id : "等待触发判断"}
          glowClass={latest && latest.recent_f1 < f1Threshold ? "glow-red" : "glow-green"}
        />
      </div>

      <div className="row cols-4" style={{ marginTop: 12 }}>
        <ScadaCard
          title="是否触发"
          value={yesNo(triggered)}
          sub={triggered ? "重训门禁已打开" : "仅监控下一批"}
          glowClass={triggered ? "glow-yellow" : "glow-green"}
          pulse={triggered}
        />
        <ScadaCard
          title="当前状态"
          value={<span className="compact-card-value">{labelFor(STATUS_LABELS, currentStatus)}</span>}
          sub={currentStatus}
          glowClass={gateBlocked ? "glow-red" : triggered ? "glow-yellow" : "glow-white"}
        />
        <ScadaCard
          title="灰度比例"
          value={formatPct(canaryPercentage)}
          sub="0 -> 10 -> 50 -> 100"
          glowClass={canaryPercentage >= 1 ? "glow-green" : "glow-blue"}
        />
        <ScadaCard
          title="下一步动作"
          value={<span className="compact-card-value">{actionLabel(enabledActionCode)}</span>}
          sub={firstEnabledAction(latest)}
          glowClass={latest ? "glow-blue" : "glow-yellow"}
        />
      </div>

      <div className="divider" />

      <div className="iteration-panel">
        <div className="subtitle" style={{ marginTop: 0 }}>完整模型迭代闭环</div>
        <div className="workflow-grid">
          {displayTimeline.map((item, index) => (
            <div className={`workflow-node ${timelineClass(item.status)}`} key={`${item.event}-${index}`}>
              <div className="timeline-index font-mono">{index + 1}</div>
              <div style={{ minWidth: 0 }}>
                <div className="node-name">{labelFor(EVENT_LABELS, item.event)}</div>
                <div className="node-detail">
                  {labelFor(STATUS_LABELS, item.status)} | {localizeText(item.message) || "等待前置步骤"}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="divider" />

      <div className="iteration-action-bar">
        <button className="scada-btn secondary" type="button" onClick={() => void refreshLatestStatus()} disabled={loadingLatest}>
          {loadingLatest ? "刷新中..." : "刷新后端状态"}
        </button>
        <button className="scada-btn" type="button" onClick={() => void handleLoadBatch()} disabled={!selectedBatchId || Boolean(loadingBatchId)}>
          {loadingBatchId ? "加载中..." : "加载选中演示批次"}
        </button>
        <button className="scada-btn secondary" type="button" onClick={() => fileInputRef.current?.click()}>
          选择 CSV 文件
        </button>
        <button className="scada-btn secondary" type="button" onClick={handleReportClick} disabled={!reportPath}>
          查看回放报告路径
        </button>
        <button className="scada-btn danger" type="button" onClick={() => void handleResetDemoState()} disabled={Boolean(runningAction)}>
          重置路演状态
        </button>
      </div>

      {message && <div className="alert success" style={{ marginTop: 12 }}>{message}</div>}
      {operationError && <div className="alert error" style={{ marginTop: 12 }}>{operationError}</div>}
      {latest?.blocked_reason && (
        <div className="alert warning" style={{ marginTop: 12 }}>
          阻断原因：<span className="font-mono">{blockedReason}</span>
        </div>
      )}

      <div className="divider" />

      <div className="row cols-2">
        <div className="iteration-panel">
          <div className="subtitle" style={{ marginTop: 0 }}>演示批次</div>
          <div className="scenario-grid" style={{ marginTop: 10, gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
            {loadingBatches &&
              [0, 1, 2].map((item) => (
                <div className="scenario-card muted" key={item}>
                  <div className="scenario-title">正在读取演示批次...</div>
                  <div className="scenario-desc">GET /api/v1/iteration/demo-batches</div>
                </div>
              ))}
            {!loadingBatches && batchError && <div className="alert error scenario-span">{batchError}</div>}
            {!loadingBatches &&
              !batchError &&
              batches.map((batch) => {
                const selected = batch.batch_id === selectedBatchId;
                const effect = expectedEffect(batch);
                return (
                  <button
                    type="button"
                    className={`scenario-card ${selected ? "selected" : ""}`}
                    key={batch.batch_id}
                    onClick={() => setSelectedBatchId(batch.batch_id)}
                  >
                    <div className="scenario-card-head">
                      <div>
                        <div className="scenario-title">{scenarioName(batch)}</div>
                        <div className="scenario-id font-mono">{batch.batch_id}</div>
                      </div>
                      <span className={`scenario-effect ${effect.tone}`}>{effect.label}</span>
                    </div>
                    <div className="scenario-desc">{batch.description}</div>
                    <div className="scenario-metrics">
                      <div>
                        <span>样本数</span>
                        <strong className="font-mono">{formatInteger(batch.sample_count)}</strong>
                      </div>
                      <div>
                        <span>风险样本</span>
                        <strong className="font-mono">{formatInteger(batch.risk_sample_count)}</strong>
                      </div>
                      <div>
                        <span>F1</span>
                        <strong className="font-mono">{formatF1(batch.recent_f1)}</strong>
                      </div>
                    </div>
                  </button>
                );
              })}
          </div>
        </div>

        <div className="iteration-panel">
          <div className="subtitle" style={{ marginTop: 0 }}>CSV 上传入口</div>
          <div className="upload-control-grid">
            <label className="scada-label">
              数据类型
              <select
                className="scada-select"
                value={datasetKind}
                onChange={(event) => setDatasetKind(event.target.value as DatasetKind)}
              >
                <option value="auto">自动识别</option>
                <option value="public_accident">公开新增事故数据</option>
                <option value="manual_labeled">手动标注 CSV</option>
              </select>
            </label>
            <label className="scada-label">
              recent_f1_override
              <input
                className="scada-input"
                type="number"
                step="0.001"
                min="0"
                max="1"
                placeholder="例如 0.84"
                value={recentF1Override}
                onChange={(event) => setRecentF1Override(event.target.value)}
              />
            </label>
          </div>
          <input ref={fileInputRef} className="scada-input" type="file" accept=".csv,.xlsx,.xls" onChange={handleFileChange} />
          <div className="upload-hint">
            自动识别支持 <span className="font-mono">risk_label</span>、<span className="font-mono">label</span>、<span className="font-mono">risk_level</span>、
            风险等级、是否事故、处罚次数、事故概述等字段。公开新增事故数据无标签字段也可入库。
          </div>
          {uploadFile && (
            <div className={uploadIsExcel ? "alert warning" : "alert info"} style={{ marginTop: 10 }}>
              已选择：<span className="font-mono">{uploadFile.name}</span>
              {uploadIsExcel ? "。Excel 上传暂未启用。" : ""}
            </div>
          )}
          <button className="scada-btn" type="button" onClick={() => void handleUploadBatch()} disabled={!uploadFile || uploadIsExcel || uploading}>
            {uploading ? "上传中..." : "上传并入库判断"}
          </button>

          <div className="subtitle">当前批次详情</div>
          <div className="detail-grid">
            <span>批次 ID</span>
            <strong className="font-mono">{loadedBatchId}</strong>
            <span>是否触发</span>
            <strong>{yesNo(triggered)}</strong>
            <span>触发原因</span>
            <strong>{reasonSummary(triggerReasons)}</strong>
            <span>当前状态</span>
            <strong>{labelFor(STATUS_LABELS, currentStatus)}</strong>
            <span>报告路径</span>
            <strong className="font-mono">{reportPath || "-"}</strong>
          </div>
        </div>
      </div>

      {uploadReport && (
        <>
          <div className="divider" />
          <div className="iteration-panel">
            <div className="subtitle" style={{ marginTop: 0 }}>上传解析结果</div>
            <div className="detail-grid upload-result-grid">
              <span>文件名</span>
              <strong>{uploadReport.original_filename}</strong>
              <span>数据类型</span>
              <strong>{labelFor(DATASET_KIND_LABELS, uploadReport.dataset_kind)}</strong>
              <span>样本数</span>
              <strong className="font-mono">{formatInteger(uploadReport.sample_count)}</strong>
              <span>风险样本数</span>
              <strong className="font-mono">{formatInteger(uploadReport.risk_sample_count)}</strong>
              <span>使用的风险字段</span>
              <strong className="font-mono">{uploadReport.risk_column_used || "未使用，按公开事故数据整批计入"}</strong>
              <span>识别策略</span>
              <strong className="font-mono">{uploadReport.risk_detection_strategy}</strong>
              <span>表头行</span>
              <strong className="font-mono">第 {uploadReport.header_row_index} 行</strong>
              <span>解析警告</span>
              <strong>{uploadReport.parsing_warnings.length ? uploadReport.parsing_warnings.join("；") : "无"}</strong>
              <span>是否触发</span>
              <strong>{yesNo(uploadReport.triggered)}</strong>
              <span>触发原因</span>
              <strong>{reasonSummary(uploadReport.trigger_reasons)}</strong>
              <span>iteration_id</span>
              <strong className="font-mono">{uploadReport.iteration_id}</strong>
              <span>upload_report_path</span>
              <strong className="font-mono">{uploadReportPath || "-"}</strong>
            </div>
          </div>
        </>
      )}

      <div className="divider" />

      <div className="iteration-panel">
        <div className="subtitle" style={{ marginTop: 0 }}>完整路演操作区</div>
        <div className="iteration-action-bar">
          <button className="scada-btn" type="button" disabled={!actionEnabled(["START_TRAINING", "TRAIN_CANDIDATE"])} onClick={() => void runAction("train", "train")}>
            启动候选模型训练
          </button>
          <button className="scada-btn" type="button" disabled={!actionEnabled(["RUN_REGRESSION", "RUN_REGRESSION_TEST"])} onClick={() => void runAction("regression", "regression-test")}>
            运行回归测试
          </button>
          <button className="scada-btn" type="button" disabled={!actionEnabled(["RUN_DRIFT_ANALYSIS"])} onClick={() => void runAction("drift", "drift-analysis")}>
            运行 Drift 分析
          </button>
          <button className="scada-btn secondary" type="button" disabled={!actionEnabled(["CREATE_PR"])} onClick={() => void runAction("pr", "pr/create")}>
            生成 PR 门禁
          </button>
          <button className="scada-btn secondary" type="button" disabled={!actionEnabled(["RUN_CI_PRECHECK"])} onClick={() => void runAction("ci", "ci/run")}>
            运行 CI 预检
          </button>
          <button className="scada-btn secondary" type="button" disabled={!actionEnabled(["APPROVE_SAFETY"])} onClick={() => void runAction("safety", "approve/safety", { approver: "demo_safety_reviewer", note: "demo safety approval" })}>
            安全审批
          </button>
          <button className="scada-btn secondary" type="button" disabled={!actionEnabled(["APPROVE_TECH"])} onClick={() => void runAction("tech", "approve/tech", { approver: "demo_tech_reviewer", note: "demo technical approval" })}>
            技术审批
          </button>
          <button className="scada-btn secondary" type="button" disabled={!actionEnabled(["START_STAGING"])} onClick={() => void runAction("staging-start", "staging/start")}>
            启动预生产
          </button>
          <button className="scada-btn secondary" type="button" disabled={!actionEnabled(["COMPLETE_STAGING_DEMO"])} onClick={() => void runAction("staging-complete", "staging/complete-demo")}>
            完成预生产演示
          </button>
          <button className="scada-btn secondary" type="button" disabled={!actionEnabled(["ADVANCE_CANARY"])} onClick={() => void runAction("canary", "canary/advance")}>
            推进灰度
          </button>
          <button className="scada-btn secondary" type="button" disabled={!latest || Boolean(runningAction) || !hasRunnableBackendAction} onClick={() => void runAction("run-next", "demo/run-next-step")}>
            执行下一步
          </button>
          <button className="scada-btn" type="button" disabled={!latest || Boolean(runningAction) || !triggered || !hasRunnableBackendAction} onClick={() => void runAction("run-to-end", "demo/run-to-end")}>
            一键演示完整链路
          </button>
          <button className="scada-btn secondary" type="button" disabled={!auditPath || Boolean(runningAction)} onClick={() => void handleFetchAudit()}>
            查看审计归档
          </button>
        </div>
        {runningAction && <div className="node-detail" style={{ marginTop: 10 }}>正在执行后端动作：{runningAction}</div>}
      </div>

      <div className="divider" />

      <div className="row cols-2">
        <div className="iteration-panel">
          <div className="subtitle" style={{ marginTop: 0 }}>产物与报告摘要</div>
          <div className="detail-grid">
            <span>候选模型路径</span>
            <strong className="font-mono">{String(reportField(latest, "candidate_model_path") ?? "-")}</strong>
            <span>模型版本</span>
            <strong className="font-mono">{String(reportField(latest, "model_version") ?? "-")}</strong>
            <span>训练报告</span>
            <strong className="font-mono">{String(reportField(latest, "training_report_path") ?? "-")}</strong>
            <span>回归是否通过</span>
            <strong>{passFail(regressionReport?.pass)}</strong>
            <span>Drift 风险等级</span>
            <strong className="font-mono">{String(driftReport?.risk_level ?? "-")}</strong>
            <span>PR metadata path</span>
            <strong className="font-mono">{prMetadataPath}</strong>
            <span>CI report path</span>
            <strong className="font-mono">{ciReportPath}</strong>
            <span>审批记录数</span>
            <strong className="font-mono">{approvalLogs.length}</strong>
            <span>预生产状态</span>
            <strong className="font-mono">{String(stagingReport?.status ?? "-")}</strong>
            <span>审计归档路径</span>
            <strong className="font-mono">{auditPath || "-"}</strong>
          </div>
        </div>

        <div className="iteration-panel">
          <div className="subtitle" style={{ marginTop: 0 }}>PR / CI / 门禁摘要</div>
          <div className="detail-grid">
            <span>PR 分支</span>
            <strong className="font-mono">{String(prMetadata?.branch_name ?? "-")}</strong>
            <span>回归 F1 变化</span>
            <strong className="font-mono">{String(asRecord(regressionReport?.delta)?.f1_macro ?? "-")}</strong>
            <span>回归失败原因</span>
            <strong>
              {Array.isArray(regressionReport?.failed_reasons)
                ? regressionReport.failed_reasons.map((item) => localizeText(item)).join("；") || "-"
                : "-"}
            </strong>
            <span>Drift PSI</span>
            <strong className="font-mono">{String(driftReport?.psi ?? "-")}</strong>
            <span>Drift 阻断原因</span>
            <strong>{localizeText(driftReport?.blocked_reason) || "-"}</strong>
            <span>CI 状态</span>
            <strong className="font-mono">{String(ciReport?.status ?? "-")}</strong>
            <span>CI 失败原因</span>
            <strong>{ciFailedReasons}</strong>
          </div>
        </div>
      </div>

      <div className="divider" />

      <div className="subtitle">后端状态时间线</div>
      <div className="timeline-container">
        {displayTimeline.map((item, index) => (
          <div className={`timeline-node ${timelineClass(item.status)}`} key={`${item.event}-${index}`}>
            <div className="timeline-index font-mono">{index + 1}</div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <div className="node-name">{labelFor(EVENT_LABELS, item.event)}</div>
                <StatusBadge status={item.status} />
              </div>
              <div className="node-detail">
                {formatTime(item.timestamp)} | <span className="font-mono">{String(item.details?.backend_event ?? item.event)}</span> | {localizeText(item.message) || "等待前置步骤"}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="divider" />

      <div className="iteration-panel">
        <div className="subtitle" style={{ marginTop: 0 }}>报告中心 / 证据链</div>
        <div className="scenario-grid" style={{ marginTop: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          {REPORT_TYPES.map((item) => {
            const report = reportItems[item.type];
            const available = report?.available ?? false;
            return (
              <div className={`scenario-card ${available ? "selected" : "muted"}`} key={item.type}>
                <div className="scenario-card-head">
                  <div>
                    <div className="scenario-title">{item.label}</div>
                    <div className="scenario-id font-mono">{report?.path || "尚未生成"}</div>
                  </div>
                  <StatusBadge status={available ? "PASSED" : "NOT_STARTED"} />
                </div>
                <div className="report-actions">
                  <button className="scada-btn secondary" type="button" disabled={!available || Boolean(runningAction)} onClick={() => void handleViewReport(item.type)}>
                    查看
                  </button>
                  <button className="scada-btn secondary" type="button" disabled={!available || Boolean(runningAction)} onClick={() => void handleDownloadReport(item.type)}>
                    下载 JSON
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 12 }}>
          <JsonView
            data={
              activeReport
                ? { report_type: activeReport.report_type, path: activeReport.path, content: activeReport.content }
                : { status: "请选择一份报告查看", available_reports: Object.keys(reportItems) }
            }
            maxHeight={320}
          />
        </div>
      </div>

      <div className="divider" />

      <div className="row cols-2">
        <div className="iteration-panel">
          <div className="subtitle" style={{ marginTop: 0 }}>训练报告</div>
          <JsonView data={trainingReport ?? { status: "尚未生成" }} maxHeight={260} />
        </div>
        <div className="iteration-panel">
          <div className="subtitle" style={{ marginTop: 0 }}>审计归档</div>
          <JsonView data={audit?.audit ?? { audit_archive_path: auditPath || "尚未生成" }} maxHeight={260} />
        </div>
      </div>
    </div>
  );
}
