"""
全局业务异常定义模块
"""


class MiningRiskAgentException(Exception):
    """基础业务异常"""
    pass


class DataLoadingError(MiningRiskAgentException):
    """数据加载异常"""
    pass


class DataValidationError(MiningRiskAgentException):
    """数据校验异常"""
    pass


class FeatureEngineeringError(MiningRiskAgentException):
    """特征工程异常"""
    pass


class ModelTrainingError(MiningRiskAgentException):
    """模型训练异常"""
    pass


class ModelInferenceError(MiningRiskAgentException):
    """模型推理异常"""
    pass


class KnowledgeBaseError(MiningRiskAgentException):
    """知识库操作异常"""
    pass


class AgentFSError(MiningRiskAgentException):
    """AgentFS 虚拟文件系统异常"""
    pass


class MemoryManagerError(MiningRiskAgentException):
    """记忆管理异常"""
    pass


class ValidationError(MiningRiskAgentException):
    """校验异常"""
    pass


class MonteCarloValidationError(MiningRiskAgentException):
    """蒙特卡洛校验异常"""
    pass


class HighRiskBlockedError(MiningRiskAgentException):
    """高风险阻断异常"""
    pass


class ModelIterationError(MiningRiskAgentException):
    """模型迭代管控异常"""
    pass


class AuditLogError(MiningRiskAgentException):
    """审计日志异常"""
    pass
