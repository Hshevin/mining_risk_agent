import warnings
warnings.warn(
    "mining_risk.harness is deprecated; migrate to the new package layout",
    DeprecationWarning,
    stacklevel=2,
)
from mining_risk_serve.harness import *  # noqa: F403
