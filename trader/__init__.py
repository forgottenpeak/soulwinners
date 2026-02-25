"""
OpenClaw Auto-Trader Module
Copy-trading bot that follows SoulWinners elite wallet signals
"""
from .openclaw import OpenClawTrader
from .position_manager import PositionManager
from .strategy import TradingStrategy
from .solana_dex import JupiterDEX

__all__ = ['OpenClawTrader', 'PositionManager', 'TradingStrategy', 'JupiterDEX']
