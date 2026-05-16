import type { HealthPayload } from "./types/common";

export type { ApiErrorBody, ApiResponse, PaginatedData, PaginatedResponse } from "./types/common";

export type ScenarioId = "chemical" | "metallurgy" | "dust";

export interface HealthResponse extends HealthPayload {
  detail?: string;
}

export interface ScenarioSwitchResponse {
  scenario_id: string;
  scenario_name: string;
  message: string;
  confidence_threshold: number;
  risk_threshold: number;
  checker_strictness: string;
  memory_top_k: number;
}

export type LLMProvider = string;

export interface LLMConfigResponse {
  provider: LLMProvider;
  model: string;
  base_url: string;
  default_temperature: number;
  default_max_tokens: number;
  max_retries: number;
  has_api_key: boolean;
  available_providers: LLMProvider[];
  message?: string;
}

export interface LLMUpdateRequest {
  provider: string;
  model?: string;
  base_url?: string;
  api_key?: string;
  api_key_env?: string;
  default_temperature?: number;
  default_max_tokens?: number;
  max_retries?: number;
}

export interface ShapContribution {
  feature: string;
  contribution: number;
}

export interface DepartmentInfo {
  name?: string;
  contact_role?: string;
  action?: string;
}

export interface GovernmentIntervention {
  department_primary?: DepartmentInfo;
  department_assist?: DepartmentInfo;
  actions?: string[];
  deadline_hours?: number;
  follow_up?: string;
}

export interface EnterpriseControl {
  equipment_id?: string;
  operation?: string;
  parameters?: Record<string, unknown>;
  emergency_resources?: string[];
  personnel_actions?: string[];
}

export interface EvidenceAnchor {
  source_file?: string;
  section_title?: string;
  rule_id?: string;
  sop_id?: string;
  case_id?: string;
  doc_type?: string;
  matched_text?: string;
  score?: number | null;
  distance?: number | null;
  layer?: string;
  proposition_id?: string;
}

export interface MarchResult {
  passed?: boolean;
  reason?: string;
  retry_count?: number;
  evidence?: EvidenceAnchor[];
  supporting_evidence?: EvidenceAnchor[];
}

export interface MonteCarloResult {
  passed?: boolean;
  confidence?: number;
  threshold?: number;
  valid_count?: number;
  total_samples?: number;
  n_samples?: number;
  status?: string;
  samples?: unknown[];
}

export interface ThreeDRisk {
  severity?: string;
  relevance?: string;
  irreversibility?: string;
  total_score?: number;
  risk_level?: string;
  blocked?: boolean;
  reason?: string;
}

export interface NodeStatus {
  node: string;
  status: string;
  timestamp?: number;
  detail?: string;
  final_status?: string;
  predicted_level?: string;
  error?: string;
  mock?: boolean;
  decision_response?: DecisionResponse;
}

export interface DecisionResponse {
  enterprise_id: string;
  scenario_id: string;
  final_status: string;
  predicted_level: string;
  probability_distribution: Record<string, number>;
  shap_contributions: ShapContribution[];
  risk_level_and_attribution?: {
    level?: string;
    root_cause?: string;
  };
  government_intervention?: GovernmentIntervention;
  enterprise_control?: EnterpriseControl;
  march_result?: MarchResult;
  monte_carlo_result?: MonteCarloResult;
  three_d_risk?: ThreeDRisk;
  rag_evidence?: EvidenceAnchor[];
  node_status?: NodeStatus[];
  mock?: boolean;
}

export interface KnowledgeOverviewMetrics {
  audit_status: string;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  kb_file_count: number;
  rag_chunks: number;
  real_public_data_cases: number;
  rule_count: number;
  agentfs_sync_status: string;
  embedding_backend: string;
}

export interface KnowledgeBaseStatus {
  filename: string;
  type: string;
  highlight: string;
  agentfs_match: boolean;
  rag_chunks: number;
  source_commit?: string;
  source_commit_short?: string;
  quality_status: string;
  summary: string;
  key_sections: string[];
  data_sources: string[];
  fs_size?: number;
  sha256?: string;
  updated_at?: string;
}

export interface AgentFSSyncStatus {
  snapshot_commit_id?: string;
  snapshot_commit_short?: string;
  fs_agentfs_match: boolean;
  backup_path?: string;
  deprecated_entries: Array<Record<string, unknown>>;
  deprecated_warning: string;
  sync_script_name: string;
  db_path?: string;
  agent_id?: string;
}

export interface RagIndexStatus {
  persist_directory: string;
  collection_name: string;
  collection_count: number;
  embedding_backend: string;
  fallback_embedding_used: boolean;
  source_commit?: string;
  source_commit_short?: string;
}

export interface MemoryArchiveStatus {
  path: string;
  priority: "P0" | "P1" | "P2" | "P3";
  strategy: string;
  description: string;
}

export interface KnowledgeSystemOverview {
  overview: KnowledgeOverviewMetrics;
  knowledge_bases: KnowledgeBaseStatus[];
  agentfs: AgentFSSyncStatus;
  rag_index: RagIndexStatus;
  memory_archives: MemoryArchiveStatus[];
  audit_warnings: string[];
}

export interface KnowledgeRagResult extends EvidenceAnchor {
  id?: string;
  source_file: string;
  section_title: string;
  doc_type: string;
  matched_text: string;
}

export interface KnowledgeRagSearchResponse {
  query: string;
  mode: string;
  collection_name: string;
  embedding_backend: string;
  results: KnowledgeRagResult[];
}

export type MemoryModule = "short_term" | "long_term" | "warning_experience" | "all";
export type MemoryPriority = "P0" | "P1" | "P2" | "P3";

export interface MemoryKpi {
  key: string;
  label: string;
  value: string | number;
  unit?: string;
  status?: "normal" | "warning" | "danger" | string;
}

export interface MemoryChartItem {
  name: string;
  value: number;
}

export interface MemoryTrendPoint {
  date: string;
  short_term: number;
  long_term: number;
  warning_experience: number;
  agentfs_write: number;
}

export interface MemoryHeatmap {
  xAxis: string[];
  yAxis: string[];
  data: Array<{ x: string; y: string; value: number }>;
}

export interface MemoryRecord {
  id: string;
  module: MemoryModule | string;
  source: string;
  path: string;
  content: string;
  summary: string;
  priority: MemoryPriority | string;
  created_at?: string;
  updated_at?: string;
  timestamp?: number;
  tokens?: number;
  size?: number;
  metadata?: Record<string, unknown>;
  risk_type?: string;
  risk_level?: string;
  association_score?: number;
  rag_score?: number;
}

export interface MemoryArchiveFileStat {
  path: string;
  label?: string;
  exists: boolean;
  size: number;
  updated_at?: string;
  entry_count: number;
  priority?: MemoryPriority | string;
  checksum?: string;
  risk_type_distribution?: Record<string, number>;
  priority_distribution?: Record<string, number>;
}

export interface MemoryStatisticsResponse {
  generated_at: string;
  filters: Record<string, unknown>;
  kpis: MemoryKpi[];
  short_term: {
    total: number;
    priority_distribution: Record<string, number>;
    token_usage: number;
    token_limit: number;
    max_tokens: number;
    trend: Array<{ date: string; value: number }>;
    recent: MemoryRecord[];
    summary_count: number;
    compressed_count: number;
    p1_pending_archive: number;
  };
  long_term: {
    files: MemoryArchiveFileStat[];
    total_entries: number;
    priority_distribution: Record<string, number>;
    risk_type_distribution: Record<string, number>;
    keyword_distribution: Record<string, number>;
  };
  warning_experience: {
    files: MemoryArchiveFileStat[];
    total: number;
    type_distribution: Record<string, number>;
    risk_level_distribution: Record<string, number>;
    risk_type_distribution: Record<string, number>;
    rag_hit_count: number;
    rag_collection_count: number;
  };
  agentfs_operations: {
    counts: Record<string, number>;
    recent: Array<Record<string, unknown>>;
    last_write_time?: string;
    write_status: string;
  };
  charts: {
    trend: MemoryTrendPoint[];
    priority_bar: MemoryChartItem[];
    type_bar: MemoryChartItem[];
    source_pie: MemoryChartItem[];
    risk_type_pie: MemoryChartItem[];
    heatmap: MemoryHeatmap;
  };
  recent_records: MemoryRecord[];
  total_records: number;
  limit: number;
  offset: number;
  cache?: { hit: boolean; ttl_seconds: number };
}

export interface MemoryStatisticsParams {
  module?: MemoryModule;
  priority?: MemoryPriority | "";
  start_time?: string;
  end_time?: string;
  keyword?: string;
  path?: string;
  risk_level?: string;
  risk_type?: string;
  limit?: number;
  offset?: number;
  refresh?: boolean;
}

export interface IterationStatus {
  current_state: string;
  current_state_cn: string;
  monitor_summary: {
    total_samples?: number;
    recent_f1?: number;
    [key: string]: unknown;
  };
  pending_approvals: Array<{
    record_id: string;
    model_version: string;
    status: string;
  }>;
  data_source?: IterationDataSource;
  last_demo_replay?: DemoReplayRun | null;
  latest_iteration?: IterationRecord | null;
}

export interface IterationTriggerResponse {
  status: string;
  model_version?: string;
  model_path?: string;
  metrics?: Record<string, unknown>;
  message?: string;
}

export interface IterationDataSource {
  type: string;
  demo_dir?: string;
  replaceable_with?: string;
  [key: string]: unknown;
}

export interface DemoBatch {
  batch_id: string;
  description: string;
  sample_count: number;
  risk_sample_count: number;
  recent_f1: number;
  scenario?: string;
  tags?: string[];
}

export interface IterationTimelineEvent {
  event: string;
  status: string;
  timestamp: string;
  message?: string;
  details?: Record<string, unknown>;
}

export interface IterationNextAction {
  action: string;
  label: string;
  enabled?: boolean;
  [key: string]: unknown;
}

export interface IterationRecord {
  id: string;
  version: string;
  date: string;
  status: "draft" | "testing" | "pending_approval" | "approved" | "rejected" | "canary" | "production" | string;
  f1: number;
  samples: number;
  description: string;
  improvements: string[];
  technical_details: string;
  expected_effect: string;
  approver?: string;
  approval_comment?: string;
  approved_at?: string | number;
  iteration_id?: string;
  batch_id?: string;
  data_source?: IterationDataSource;
  batch?: Record<string, unknown>;
  sample_count?: number;
  risk_sample_count?: number;
  recent_f1?: number;
  trigger_threshold_samples?: number;
  trigger_threshold_f1?: number;
  thresholds?: {
    risk_sample_count?: number;
    recent_f1?: number;
    [key: string]: unknown;
  };
  triggered?: boolean;
  retrain_required?: boolean;
  trigger_reasons?: string[];
  current_status?: string;
  timeline?: IterationTimelineEvent[];
  report_path?: string;
  next_actions?: IterationNextAction[];
  created_at?: string | number;
  updated_at?: string;
  metadata?: Record<string, unknown>;
  demo_mode?: boolean;
  training_report?: Record<string, unknown> | null;
  training_report_path?: string | null;
  candidate_model_path?: string | null;
  model_version?: string | null;
  regression_report?: Record<string, unknown> | null;
  regression_report_path?: string | null;
  drift_report?: Record<string, unknown> | null;
  drift_report_path?: string | null;
  pr_metadata?: Record<string, unknown> | null;
  pr_metadata_path?: string | null;
  local_pr_metadata_path?: string | null;
  ci_report?: Record<string, unknown> | null;
  ci_report_path?: string | null;
  approval_logs?: Array<Record<string, unknown>>;
  staging_report?: Record<string, unknown> | null;
  staging_report_path?: string | null;
  canary_percentage?: number;
  canary_events?: Array<Record<string, unknown>>;
  audit_archive_path?: string | null;
  blocked_reason?: string | null;
}

export interface DemoReplayRun {
  batch_id: string;
  iteration_id?: string | null;
  status: string;
  retrain_required: boolean;
  blocked: boolean;
  trigger_reasons: string[];
  blocked_gates: string[];
  report_path: string;
  metadata?: DemoBatch;
  iteration?: IterationRecord;
  [key: string]: unknown;
}

export interface DemoReplayLoadResponse {
  status: string;
  retrain_required: boolean;
  blocked: boolean;
  triggered?: boolean;
  trigger_reasons: string[];
  blocked_gates: string[];
  metadata: DemoBatch;
  report_path: string;
  iteration_id?: string | null;
  current_status?: string | null;
  timeline: IterationTimelineEvent[];
  next_actions: IterationNextAction[];
  iteration?: IterationRecord | null;
  report: Record<string, unknown>;
  message: string;
}

export interface IterationTimelineResponse {
  iteration_id: string;
  batch_id: string;
  current_status: string;
  triggered: boolean;
  timeline: IterationTimelineEvent[];
}

export interface IterationUploadBatchResponse {
  status: string;
  batch_id: string;
  original_filename: string;
  dataset_kind: DatasetKind;
  detected_encoding: string;
  header_row_index: number;
  detected_columns: string[];
  risk_column_used?: string | null;
  risk_detection_strategy: string;
  parsing_warnings: string[];
  sample_count: number;
  risk_sample_count: number;
  recent_f1: number;
  triggered: boolean;
  retrain_required: boolean;
  trigger_reasons: string[];
  current_status: string;
  report_path: string;
  upload_report_path: string;
  iteration_id: string;
  timeline: IterationTimelineEvent[];
  next_actions: IterationNextAction[];
  iteration: IterationRecord;
  upload_report: UploadParsingReport;
  message: string;
}

export type DatasetKind = "auto" | "public_accident" | "manual_labeled";

export interface UploadParsingReport {
  original_filename: string;
  dataset_kind: DatasetKind | string;
  detected_encoding: string;
  header_row_index: number;
  detected_columns: string[];
  risk_column_used?: string | null;
  risk_detection_strategy: string;
  sample_count: number;
  risk_sample_count: number;
  recent_f1: number;
  triggered: boolean;
  trigger_reasons: string[];
  parsing_warnings: string[];
  upload_path: string;
  iteration_id: string;
}

export interface DemoResetResponse {
  status: string;
  archived_iterations: number;
  archived_runs: number;
  latest_iteration?: IterationRecord | null;
  latest_run?: DemoReplayRun | null;
  message: string;
}

export interface DemoIterationStepResponse {
  iteration_id: string;
  batch_id: string;
  current_status: string;
  timeline: IterationTimelineEvent[];
  next_actions: IterationNextAction[];
  iteration: IterationRecord;
  report?: Record<string, unknown> | null;
  message: string;
}

export interface IterationAuditResponse {
  audit_archive_path: string;
  audit: Record<string, unknown>;
}

export interface IterationReportItem {
  report_type: string;
  available: boolean;
  path?: string | null;
  content?: Record<string, unknown> | null;
  missing?: boolean;
}

export interface IterationReportsResponse {
  iteration_id: string;
  batch_id: string;
  current_status: string;
  reports: Record<string, IterationReportItem>;
}

export interface IterationReportResponse {
  iteration_id: string;
  batch_id: string;
  report_type: string;
  path: string;
  content: Record<string, unknown>;
}

export interface DataUploadResponse {
  success: boolean;
  message: string;
  rows: number;
  columns: number;
  preview?: Array<Record<string, unknown>>;
}

export interface AuditLogEntry {
  id: number;
  timestamp: number;
  event_type: string;
  agent_id?: string;
  enterprise_id?: string;
  details?: string;
  risk_level?: string;
  validation_status?: string;
}

export interface ShortTermMemory {
  id: string;
  text: string;
  priority: "P0" | "P1" | "P2" | "P3";
  type: "short";
  time: string;
  timestamp: number;
  source?: string;
  tags?: string[];
  enterprise_id?: string;
  category?: "inference" | "warning" | "experience" | "context";
  compressed?: boolean;
  context_window_active?: boolean;
}

export interface LongTermMemory {
  id: string;
  text: string;
  priority: "P0" | "P1" | "P2" | "P3";
  type: "long";
  time: string;
  timestamp: number;
  source?: string;
  tags?: string[];
  enterprise_id?: string;
  category?: "regulation" | "accident_case" | "experience" | "knowledge" | "enterprise_data";
  migrated_from_short?: boolean;
  migrated_at?: number;
  data_source?: string;
  verified?: boolean;
}

export type MemoryItem = ShortTermMemory | LongTermMemory;

export interface WarningLog {
  id: string;
  timestamp: number;
  time_str: string;
  enterprise_id: string;
  enterprise_name: string;
  risk_level: string;
  risk_score: number;
  trigger_condition: string;
  root_cause: string;
  actions_taken: string[];
  status: "active" | "resolved" | "expired";
  resolution?: string;
  experience_recorded?: boolean;
}

export interface IterationRecord {
  id: string;
  version: string;
  date: string;
  status: "draft" | "testing" | "pending_approval" | "approved" | "rejected" | "canary" | "production";
  f1: number;
  samples: number;
  description: string;
  improvements: string[];
  technical_details: string;
  expected_effect: string;
  approver?: string;
  approval_comment?: string;
  approved_at?: number;
  created_at: number;
}

export interface EnterpriseRiskScore {
  enterprise_id: string;
  enterprise_name: string;
  risk_score: number;
  risk_level: string;
  scenario: string;
  assessment_time: string;
  key_factors: { name: string; value: number; color: string }[];
  inference_stored: boolean;
}

export interface ModelEvaluationReport {
  id: string;
  generated_at: string;
  total_assessments: number;
  accuracy: number;
  precision: number;
  recall: number;
  f1_score: number;
  false_positive_rate: number;
  false_negative_rate: number;
  level_distribution: Record<string, number>;
  improvement_suggestions: string[];
}
