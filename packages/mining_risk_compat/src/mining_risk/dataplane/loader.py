import warnings
warnings.warn(
    "mining_risk.dataplane is deprecated; migrate to the new package layout",
    DeprecationWarning,
    stacklevel=2,
)
from mining_risk_common.dataplane.loader import *  # noqa: F403
