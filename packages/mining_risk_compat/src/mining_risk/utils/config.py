import warnings
warnings.warn(
    "mining_risk.utils is deprecated; migrate to the new package layout",
    DeprecationWarning,
    stacklevel=2,
)
from mining_risk_common.utils.config import *  # noqa: F403
