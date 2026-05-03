"""
配置加载模块
加载并解析 config.yaml 中的全局配置参数
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    name: str
    version: str
    debug: bool = False


class DataConfig(BaseModel):
    raw_data_path: str
    reference_data_path: str
    supported_formats: List[str]
    encoding: str = "utf-8-sig"
    batch_size: int = 1000


class FeatureConfig(BaseModel):
    id_columns: List[str]
    binary_columns: List[str]
    numeric_columns: List[str]
    enum_columns: List[str]
    text_columns: List[str]
    industry_columns: List[str]
    missing_value_strategy: Dict[str, Any]
    outlier_clip_quantile: float = 0.99


class BaseLearnerConfig(BaseModel):
    name: str
    type: str
    params: Dict[str, Any] = Field(default_factory=dict)


class MetaLearnerConfig(BaseModel):
    type: str
    params: Dict[str, Any] = Field(default_factory=dict)


class CVConfig(BaseModel):
    n_splits: int = 5
    shuffle: bool = False


class SplitRatioConfig(BaseModel):
    train: float = 0.7
    val: float = 0.2
    test: float = 0.1


class StackingConfig(BaseModel):
    base_learners: List[BaseLearnerConfig]
    meta_learner: MetaLearnerConfig
    cv: CVConfig
    split_ratio: SplitRatioConfig
    model_path: str
    pipeline_path: str


class ModelConfig(BaseModel):
    stacking: StackingConfig
    risk_levels: List[str]
    industry_risk_coefficients: Dict[str, Any]


class AgentFSConfig(BaseModel):
    db_path: str
    snapshot_interval: int
    git_repo_path: str
    snapshots_dir: str = "data/snapshots"


class ShortTermMemoryConfig(BaseModel):
    max_tokens: int
    safety_threshold: float
    cleanup_strategy: str
    priority_levels: Dict[str, Any]


class LongTermMemoryConfig(BaseModel):
    knowledge_files: List[str]
    archive_files: Optional[List[str]] = None
    rag: Dict[str, Any]


class MemoryConfig(BaseModel):
    short_term: ShortTermMemoryConfig
    long_term: LongTermMemoryConfig


class MarchConfig(BaseModel):
    enabled: bool
    check_levels: List[str]


class MonteCarloConfig(BaseModel):
    enabled: bool
    n_samples: int
    confidence_threshold: float
    risk_dimensions: List[Dict[str, Any]]


class ValidationConfig(BaseModel):
    march: MarchConfig
    monte_carlo: MonteCarloConfig


class GitFlowConfig(BaseModel):
    main_branch: str
    dev_branch: str
    feature_branch_prefix: str
    release_branch_prefix: str


class CIConfig(BaseModel):
    enabled: bool
    pipeline: List[str]
    regression: Dict[str, Any]


class ApprovalConfig(BaseModel):
    levels: List[Dict[str, Any]]
    trial_period_hours: int


class ModelIterationConfig(BaseModel):
    git_flow: GitFlowConfig
    ci: CIConfig
    approval: ApprovalConfig


class HarnessConfig(BaseModel):
    agentfs: AgentFSConfig
    memory: MemoryConfig
    validation: ValidationConfig
    model_iteration: ModelIterationConfig


class APIConfig(BaseModel):
    host: str
    port: int
    reload: bool
    workers: int
    docs_url: str
    openapi_url: str


class FrontendConfig(BaseModel):
    port: int
    title: str
    page_icon: str


class LoggingConfig(BaseModel):
    level: str
    format: str
    file: str
    max_bytes: int
    backup_count: int


class AuditConfig(BaseModel):
    db_path: str
    retention_days: int
    auto_archive: bool


class MonitorConfig(BaseModel):
    sample_threshold: int = 5000
    f1_threshold: float = 0.85
    db_path: str = "data/audit.db"


class ApproversConfig(BaseModel):
    security: str = "security@example.com"
    tech: str = "tech@example.com"


class CanaryConfig(BaseModel):
    ratios: List[float] = Field(default_factory=lambda: [0.0, 0.1, 0.5, 1.0])


class StagingConfig(BaseModel):
    duration_hours: int = 24
    sample_interval_minutes: int = 5


class SMTPConfig(BaseModel):
    host: str = ""
    port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_addr: str = Field(default="agent@example.com", alias="from")


class IterationConfig(BaseModel):
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    approvers: ApproversConfig = Field(default_factory=ApproversConfig)
    canary: CanaryConfig = Field(default_factory=CanaryConfig)
    staging: StagingConfig = Field(default_factory=StagingConfig)
    smtp: SMTPConfig = Field(default_factory=SMTPConfig)
    webhook_url: str = ""


class GLM5Config(BaseModel):
    model: str = "glm-5"
    api_key: str = ""
    base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    default_temperature: float = 0.3
    default_max_tokens: int = 8192
    max_retries: int = 3


class SingleScenarioConfig(BaseModel):
    name: str
    kb_subdir: str
    prompt_template: str
    checker_strictness: str
    confidence_threshold: float
    risk_threshold: float
    memory_top_k: int


class ScenariosConfig(BaseModel):
    chemical: SingleScenarioConfig
    metallurgy: SingleScenarioConfig
    dust: SingleScenarioConfig


class AppConfig(BaseModel):
    project: ProjectConfig
    data: DataConfig
    features: FeatureConfig
    model: ModelConfig
    harness: HarnessConfig
    llm: Dict[str, Any] = Field(default_factory=dict)
    scenarios: Dict[str, Any] = Field(default_factory=dict)
    api: APIConfig
    frontend: FrontendConfig
    logging: LoggingConfig
    audit: AuditConfig
    iteration: IterationConfig = Field(default_factory=IterationConfig)


class ConfigManager:
    """配置管理器单例类"""

    _instance: Optional["ConfigManager"] = None
    _config: Optional[AppConfig] = None

    def __new__(cls, config_path: Optional[str] = None) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if self._config is not None:
            return
        if config_path is None:
            # 默认从项目根目录加载
            base_dir = Path(__file__).resolve().parent.parent
            config_path = base_dir / "config.yaml"
        self.load_config(str(config_path))

    def load_config(self, config_path: str) -> None:
        """从 YAML 文件加载配置"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._config = AppConfig(**raw)

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            raise RuntimeError("配置尚未加载")
        return self._config


def get_config() -> AppConfig:
    """获取全局配置对象的便捷函数"""
    return ConfigManager().config
