"""
OpenClaw Auto-Trader Module
Copy-trading bot that follows SoulWinners elite wallet signals
"""
from .openclaw import OpenClawTrader
from .position_manager import PositionManager
from .strategy import TradingStrategy
from .solana_dex import JupiterDEX
from .fee_collector import (
    collect_fee,
    send_to_owner,
    get_user_fees,
    get_total_fees,
    get_pending_fees,
    FEE_PER_TRADE_SOL,
    OWNER_WALLET
)
from .ai_advisor import (
    analyze_performance,
    generate_report,
    suggest_improvements,
    send_report_to_user,
    get_report_history
)

__all__ = [
    # Trading
    'OpenClawTrader',
    'PositionManager',
    'TradingStrategy',
    'JupiterDEX',
    # Fee collection
    'collect_fee',
    'send_to_owner',
    'get_user_fees',
    'get_total_fees',
    'get_pending_fees',
    'FEE_PER_TRADE_SOL',
    'OWNER_WALLET',
    # AI Advisor
    'analyze_performance',
    'generate_report',
    'suggest_improvements',
    'send_report_to_user',
    'get_report_history',
]
