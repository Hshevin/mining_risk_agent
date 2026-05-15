"""
全局业务异常定义模块

所有业务层异常应继承 ``MiningRiskAgentException``，由 API 异常处理器统一映射。
"""


class MiningRiskAgentException(Exception):
    """基础业务异常，所有领域异常的超类。"""

    pass


class DataLoadingError(MiningRiskAgentException):
    """数据加载异常：文件不存在、格式错误或解析失败。"""

    pass


class DataValidationError(MiningRiskAgentException):
    """数据校验异常：字段缺失、类型不符或业务规则不满足。"""

    pass


class FeatureEngineeringError(MiningRiskAgentException):
    """特征工程异常：转换流水线执行失败。"""

    pass


class ModelTrainingError(MiningRiskAgentException):
    """模型训练异常：训练过程失败或指标不达标。"""

    pass


class ModelInferenceError(MiningRiskAgentException):
    """模型推理异常：预测阶段失败。"""

    pass


class KnowledgeBaseError(MiningRiskAgentException):
    """知识库操作异常：读写、快照或回滚失败。"""

    pass


class AgentFSError(MiningRiskAgentException):
    """AgentFS 虚拟文件系统异常。"""

    pass


class MemoryManagerError(MiningRiskAgentException):
    """记忆管理异常：短期/长期记忆 CRUD 失败。"""

    pass


class ValidationError(MiningRiskAgentException):
    """校验异常：MARCH/蒙特卡洛等校验链路失败。"""

    pass


class MonteCarloValidationError(MiningRiskAgentException):
    """蒙特卡洛校验异常：置信度未达阈值。"""

    pass


class HighRiskBlockedError(MiningRiskAgentException):
    """高风险阻断异常：三维风险评分触发硬阻断。"""

    pass


class ModelIterationError(MiningRiskAgentException):
    """模型迭代管控异常：训练/审批/灰度流程失败。"""

    pass


class AuditLogError(MiningRiskAgentException):
    """审计日志异常：写入或查询失败。"""

    pass
