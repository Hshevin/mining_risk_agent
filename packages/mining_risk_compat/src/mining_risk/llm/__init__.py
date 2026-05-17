import warnings
warnings.warn(
    "mining_risk.llm is deprecated; migrate to the new package layout",
    DeprecationWarning,
    stacklevel=2,
)
from mining_risk_serve.llm import *  # noqa: F403
