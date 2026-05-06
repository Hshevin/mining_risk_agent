export type ScenarioId = "chemical" | "metallurgy" | "dust";

export interface HealthResponse {
  status: string;
  version?: string;
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

<<<<<<< HEAD
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

=======
>>>>>>> e7cc200 (some changes)
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

export interface MarchResult {
  passed?: boolean;
  reason?: string;
  retry_count?: number;
}

export interface MonteCarloResult {
  passed?: boolean;
  confidence?: number;
  threshold?: number;
  valid_count?: number;
  total_samples?: number;
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
<<<<<<< HEAD
  error?: string;
  mock?: boolean;
  decision_response?: DecisionResponse;
=======
  mock?: boolean;
>>>>>>> e7cc200 (some changes)
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
  node_status?: NodeStatus[];
  mock?: boolean;
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
}

export interface IterationTriggerResponse {
  status: string;
  model_version?: string;
  model_path?: string;
  metrics?: Record<string, unknown>;
  message?: string;
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
