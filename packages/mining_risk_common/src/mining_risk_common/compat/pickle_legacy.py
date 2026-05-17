"""
在反序列化 artifacts 前注册旧模块路径别名。

历史训练产物中 sklearn Pipeline 与模型 pkl 仍引用 ``data.preprocessor``、
``model._logistic``、``utils.config`` 等迁移前路径。
"""

from __future__ import annotations

import sys
import types

_REGISTERED = False


def register_legacy_pickle_modules() -> None:
    global _REGISTERED
    if _REGISTERED:
        return

    from mining_risk_common import dataplane
    from mining_risk_common.dataplane import preprocessor as preprocessor_mod
    from mining_risk_common.model import stacking as stacking_mod
    from mining_risk_common.utils import config as config_mod

    data_mod = types.ModuleType("data")
    data_mod.preprocessor = preprocessor_mod
    sys.modules.setdefault("data", data_mod)
    sys.modules.setdefault("data.preprocessor", preprocessor_mod)

    model_mod = types.ModuleType("model")
    model_mod.stacking = stacking_mod
    sys.modules.setdefault("model", model_mod)
    sys.modules.setdefault("model.stacking", stacking_mod)

    # 部分 pkl 将工厂函数记在 model._logistic 下
    logistic_mod = types.ModuleType("model._logistic")
    logistic_mod._create_logistic_regression = stacking_mod._create_logistic_regression
    sys.modules.setdefault("model._logistic", logistic_mod)

    utils_mod = types.ModuleType("utils")
    utils_mod.config = config_mod
    sys.modules.setdefault("utils", utils_mod)
    sys.modules.setdefault("utils.config", config_mod)

    # 确保 dataplane 子模块在 pickle 查找自定义 Transformer 类时可用
    sys.modules.setdefault("mining_risk_common.dataplane.preprocessor", preprocessor_mod)

    _REGISTERED = True
