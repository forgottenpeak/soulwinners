"""
Hedgehog - SoulWinners AI Brain

Full autonomous AI agent with:
- Hybrid routing (GPT-4o-mini + Claude Sonnet 4)
- Telegram command interface
- Natural language understanding
- Self-healing capabilities
- Action logging and audit trail

Cost Target: $3-5/month
"""

__version__ = "2.0.0"
__codename__ = "Hedgehog"

from .brain import HedgehogBrain, get_brain
from .config import HedgehogConfig, get_config
from .router import AIRouter, get_router, ModelChoice

__all__ = [
    "HedgehogBrain",
    "HedgehogConfig",
    "AIRouter",
    "get_brain",
    "get_config",
    "get_router",
    "ModelChoice",
    "__version__",
    "__codename__",
]
