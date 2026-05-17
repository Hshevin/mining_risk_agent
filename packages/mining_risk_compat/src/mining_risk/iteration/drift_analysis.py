import warnings
warnings.warn(
    "mining_risk.iteration is deprecated; migrate to the new package layout",
    DeprecationWarning,
    stacklevel=2,
)
from mining_risk_train.iteration.drift_analysis import *  # noqa: F403
