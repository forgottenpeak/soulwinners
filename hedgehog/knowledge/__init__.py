"""
Hedgehog Knowledge System

Hedgehog's brain - complete knowledge of the SoulWinners system.
Query here first, live system second.
"""

from .soulwinners_map import (
    SoulWinnersScanner,
    KnowledgeUpdater,
    get_scanner,
    get_knowledge,
    initialize_knowledge,
    STATE_FILE,
    MAIN_DB,
    HEDGEHOG_DB
)

from .knowledge_base import (
    HedgehogKnowledge,
    QueryResult,
    get_kb,
    ask,
    wallet_count,
    is_running,
    table_rows
)

__all__ = [
    # Scanner
    'SoulWinnersScanner',
    'KnowledgeUpdater',
    'get_scanner',
    'get_knowledge',
    'initialize_knowledge',

    # Knowledge Base
    'HedgehogKnowledge',
    'QueryResult',
    'get_kb',

    # Quick functions
    'ask',
    'wallet_count',
    'is_running',
    'table_rows',

    # Paths
    'STATE_FILE',
    'MAIN_DB',
    'HEDGEHOG_DB'
]
