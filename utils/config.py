"""
配置加载模块
加载并解析 config.yaml 中的全局配置参数
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class ProjectConfig(BaseModel):
    name: str
    version: str
    debug: bool = False


class DataConfig(BaseModel):
    raw_data_path: str
    reference_data_path: str
    merged_data_path: Optional[str] = None  # 预合并训练集路径（new_已清洗.csv）
    supported_formats: List[str]
    encoding: str = "utf-8-sig"
    batch_size: int = 1000
    table_join_keys: Optional[Dict[str, Any]] = None  # 各原始表的主键/外键映射


class FeatureConfig(BaseModel):
    target_column: str = "new_level"  # 目标列（A/B/C/D）
    id_columns: List[str]
    binary_columns: List[str]
    numeric_columns: List[str]
    enum_columns: List[str]
    text_columns: List[str]
    industry_columns: List[str]
    special_features: Optional[Dict[str, Any]] = None  # 特殊逻辑特征列显式映射
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


def _env_prefix(provider: str) -> str:
    """将 provider 名转换成可用于环境变量的前缀。"""
    return re.sub(r"[^A-Z0-9]+", "_", provider.upper()).strip("_")


class LLMProviderConfig(BaseModel):
    model: str = ""
    api_key: str = ""
    api_key_env: str = ""
    base_url: str = ""
    default_temperature: float = 0.3
    default_max_tokens: int = 8192
    max_retries: int = 3

    @model_validator(mode="after")
    def _apply_env_override(self) -> "GLM5Config":
        env_key = os.getenv("GLM5_API_KEY")
        if env_key:
            self.api_key = env_key
        if not self.api_key:
            raise ValueError(
                "GLM-5 API Key 未配置，请设置环境变量 GLM5_API_KEY"
            )
        return self


class LLMConfig(BaseModel):
    glm5: GLM5Config = Field(default_factory=GLM5Config)


class LLMConfig(BaseModel):
    provider: str = "glm5"
    providers: Dict[str, LLMProviderConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _apply_env_override(self) -> "LLMConfig":
        env_provider = os.getenv("LLM_PROVIDER")
        if env_provider:
            self.provider = env_provider
        self.provider = self.provider.lower()

        self.providers = {
            name.lower(): cfg for name, cfg in self.providers.items()
        }
        if not self.providers:
            self.providers[self.provider] = LLMProviderConfig(
                model=os.getenv("LLM_MODEL", self.provider),
                base_url=os.getenv("LLM_BASE_URL", ""),
            )
        if self.provider not in self.providers:
            self.providers[self.provider] = LLMProviderConfig(
                model=os.getenv("LLM_MODEL", self.provider),
                base_url=os.getenv("LLM_BASE_URL", ""),
            )

        for name, cfg in self.providers.items():
            prefix = _env_prefix(name)
            env_key = (
                os.getenv(cfg.api_key_env)
                if cfg.api_key_env
                else None
            ) or os.getenv(f"LLM_{prefix}_API_KEY")
            env_model = os.getenv(f"LLM_{prefix}_MODEL")
            env_base_url = os.getenv(f"LLM_{prefix}_BASE_URL")

            if name == self.provider:
                env_key = os.getenv("LLM_API_KEY") or env_key or os.getenv("OPENAI_API_KEY")
                env_model = os.getenv("LLM_MODEL") or env_model
                env_base_url = os.getenv("LLM_BASE_URL") or env_base_url

            if env_key:
                cfg.api_key = env_key
            if env_model:
                cfg.model = env_model
            if env_base_url:
                cfg.base_url = env_base_url
        return self

    @property
    def active(self) -> LLMProviderConfig:
        return self.providers[self.provider]

    @property
    def available_provider_names(self) -> List[str]:
        return sorted(self.providers.keys())


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
    llm: LLMConfig = Field(default_factory=LLMConfig)
    scenarios: ScenariosConfig
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
