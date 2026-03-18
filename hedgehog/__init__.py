"""
Hedgehog v4.0 - The TRUE Brain of SoulWinners

A brain that KNOWS everything about its house.
No guessing. Instant answers. Complete system knowledge.

Architecture:
- Knowledge Base: Scans and caches the entire system
- Smart Tools: Query knowledge first, live system second
- Hybrid AI: GPT-4o-mini (95%) + Claude Sonnet (5%)
- Self-healing: Proactive monitoring and auto-fix

Usage:
    python -m hedgehog init     # Initialize knowledge base (FIRST TIME)
    python -m hedgehog bot      # Run with Telegram interface
    python -m hedgehog status   # Check system status

Cost Target: $3-5/month
"""

__version__ = "4.0.0"
__codename__ = "Hedgehog Brain"

from .brain import HedgehogBrain, get_brain
from .config import HedgehogConfig, get_config
from .router import AIRouter, get_router, ModelChoice

# Knowledge system
from .knowledge import (
    HedgehogKnowledge,
    get_kb,
    initialize_knowledge,
    get_scanner,
    KnowledgeUpdater,
    ask,
    wallet_count,
    is_running,
    table_rows,
)

__all__ = [
    # Core brain
    "HedgehogBrain",
    "HedgehogConfig",
    "AIRouter",
    "get_brain",
    "get_config",
    "get_router",
    "ModelChoice",
    # Knowledge system
    "HedgehogKnowledge",
    "get_kb",
    "initialize_knowledge",
    "get_scanner",
    "KnowledgeUpdater",
    # Quick knowledge functions
    "ask",
    "wallet_count",
    "is_running",
    "table_rows",
    # Meta
    "__version__",
    "__codename__",
]
