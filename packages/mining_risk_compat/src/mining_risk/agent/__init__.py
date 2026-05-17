import warnings
warnings.warn(
    "mining_risk.agent is deprecated; migrate to the new package layout",
    DeprecationWarning,
    stacklevel=2,
)
from mining_risk_serve.agent import *  # noqa: F403
