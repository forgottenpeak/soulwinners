"""
Trading Strategy - Entry/Exit Rules for OpenClaw
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

from .position_manager import Position, PositionStatus

logger = logging.getLogger(__name__)


class ExitAction(Enum):
    HOLD = "hold"
    STOP_LOSS = "stop_loss"  # -20% → sell 100%
    TAKE_PROFIT_1 = "take_profit_1"  # +50% → sell 50%
    TAKE_PROFIT_2 = "take_profit_2"  # +100% → sell 50%
    STAGNATION_EXIT = "stagnation"  # Flat for 10 min after TP2
    MOMENTUM_HOLD = "momentum_hold"  # Surging past 100%


@dataclass
class StrategyConfig:
    """Trading strategy parameters."""
    # Position sizing
    position_size_percent: float = 70.0  # Use 70% of balance per trade
    max_positions: int = 3  # Max simultaneous positions

    # Entry filters
    min_liquidity_usd: float = 50000  # Min $50k liquidity
    min_bes: float = 1000  # Min BES score for entry
    min_recent_win_rate: float = 0.80  # 80% win rate on last 5 trades

    # Stop loss
    stop_loss_percent: float = -20.0  # Exit at -20%

    # Take profit levels
    tp1_percent: float = 50.0  # +50% → sell 50%
    tp1_sell_percent: float = 50.0  # Sell 50% at TP1

    tp2_percent: float = 100.0  # +100% → sell 50% of remaining
    tp2_sell_percent: float = 50.0  # Sell 50% at TP2

    # Momentum detection
    momentum_threshold: float = 120.0  # Consider >120% as surging
    stagnation_minutes: int = 10  # Flat for 10 min = stagnate

    # Price change thresholds for stagnation
    stagnation_threshold: float = 2.0  # <2% change = stagnant


class TradingStrategy:
    """
    OpenClaw Trading Strategy

    Entry Rules:
    - Copy elite wallet buys (BES > 1000)
    - Token liquidity >= $50k
    - Wallet's last 5 trades >= 80% win rate
    - Use 70% of balance
    - Max 3 positions

    Exit Rules:
    1. Stop Loss: -20% → Sell 100% immediately
    2. Take Profit 1: +50% → Sell 50%
    3. Take Profit 2: +100% → Sell 50% of remaining
    4. Momentum: If surging past 100%, hold runner
    5. Stagnation: If flat for 10 min after TP2, sell remaining
    """

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self._price_history: Dict[str, List[Tuple[datetime, float]]] = {}

    def should_enter(
        self,
        wallet_bes: float,
        wallet_win_rate: float,
        token_liquidity: float,
        current_positions: int,
        already_holding_token: bool
    ) -> Tuple[bool, str]:
        """
        Check if we should enter a trade.

        Returns:
            (should_enter, reason)
        """
        # Check max positions
        if current_positions >= self.config.max_positions:
            return False, f"Max positions reached ({self.config.max_positions})"

        # Check if already holding
        if already_holding_token:
            return False, "Already holding this token"

        # Check BES threshold
        if wallet_bes < self.config.min_bes:
            return False, f"BES {wallet_bes:.0f} below threshold {self.config.min_bes}"

        # Check win rate
        if wallet_win_rate < self.config.min_recent_win_rate:
            return False, f"Win rate {wallet_win_rate:.1%} below {self.config.min_recent_win_rate:.0%}"

        # Check liquidity
        if token_liquidity < self.config.min_liquidity_usd:
            return False, f"Liquidity ${token_liquidity:,.0f} below ${self.config.min_liquidity_usd:,.0f}"

        return True, "All criteria met"

    def calculate_position_size(self, current_balance: float) -> float:
        """Calculate SOL amount to use for trade."""
        return current_balance * (self.config.position_size_percent / 100)

    def check_exit(self, position: Position) -> Tuple[ExitAction, float]:
        """
        Check if position should be exited.

        Returns:
            (action, sell_percent)
        """
        pnl = position.pnl_percent

        # 1. STOP LOSS - Exit immediately at -20%
        if pnl <= self.config.stop_loss_percent:
            return ExitAction.STOP_LOSS, 100.0

        # 2. TAKE PROFIT 1 - Sell 50% at +50%
        if pnl >= self.config.tp1_percent and not position.tp1_hit:
            return ExitAction.TAKE_PROFIT_1, self.config.tp1_sell_percent

        # 3. TAKE PROFIT 2 - Sell 50% at +100%
        if pnl >= self.config.tp2_percent and position.tp1_hit and not position.tp2_hit:
            return ExitAction.TAKE_PROFIT_2, self.config.tp2_sell_percent

        # 4. After TP2 hit, check for momentum or stagnation
        if position.tp2_hit:
            # Check for momentum surge
            if pnl >= self.config.momentum_threshold:
                return ExitAction.MOMENTUM_HOLD, 0.0

            # Check for stagnation
            if self._is_stagnant(position):
                return ExitAction.STAGNATION_EXIT, 100.0

        return ExitAction.HOLD, 0.0

    def _is_stagnant(self, position: Position) -> bool:
        """
        Check if price has been flat for stagnation period.
        """
        token = position.token_mint
        history = self._price_history.get(token, [])

        if len(history) < 2:
            return False

        # Look at last N minutes of price data
        cutoff = datetime.now() - timedelta(minutes=self.config.stagnation_minutes)
        recent_prices = [(t, p) for t, p in history if t >= cutoff]

        if len(recent_prices) < 3:
            return False

        # Calculate price range
        prices = [p for _, p in recent_prices]
        min_price = min(prices)
        max_price = max(prices)

        if min_price <= 0:
            return False

        price_range_pct = ((max_price - min_price) / min_price) * 100

        # If price range is less than threshold, it's stagnant
        return price_range_pct < self.config.stagnation_threshold

    def record_price(self, token_mint: str, price: float):
        """Record price for stagnation detection."""
        if token_mint not in self._price_history:
            self._price_history[token_mint] = []

        self._price_history[token_mint].append((datetime.now(), price))

        # Keep only last 30 minutes of data
        cutoff = datetime.now() - timedelta(minutes=30)
        self._price_history[token_mint] = [
            (t, p) for t, p in self._price_history[token_mint]
            if t >= cutoff
        ]

    def format_exit_reason(self, action: ExitAction, position: Position) -> str:
        """Format exit reason for logging/alerts."""
        pnl = position.pnl_percent

        if action == ExitAction.STOP_LOSS:
            return f"STOP LOSS triggered at {pnl:.1f}%"
        elif action == ExitAction.TAKE_PROFIT_1:
            return f"TP1 (+50%) hit at {pnl:.1f}% → Selling 50%"
        elif action == ExitAction.TAKE_PROFIT_2:
            return f"TP2 (+100%) hit at {pnl:.1f}% → Selling 50%"
        elif action == ExitAction.STAGNATION_EXIT:
            return f"Price stagnant for {self.config.stagnation_minutes}m after TP2 → Closing"
        elif action == ExitAction.MOMENTUM_HOLD:
            return f"MOMENTUM SURGE at {pnl:.1f}% → Holding runner"
        else:
            return f"Holding at {pnl:.1f}%"


class SignalQueue:
    """
    Queue for passing signals from SoulWinners to OpenClaw.
    Thread-safe, in-memory queue with persistence option.
    """

    def __init__(self, db_path: str = "data/openclaw.db"):
        import sqlite3
        self.db_path = db_path
        self._init_queue_table()

    def _init_queue_table(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signal_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_mint TEXT NOT NULL,
                token_symbol TEXT,
                wallet_address TEXT,
                wallet_bes REAL,
                wallet_win_rate REAL,
                wallet_tier TEXT,
                buy_sol REAL,
                token_liquidity REAL,
                token_market_cap REAL,
                status TEXT DEFAULT 'pending',  -- pending, processing, executed, skipped
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                processed_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    def push_signal(
        self,
        token_mint: str,
        token_symbol: str,
        wallet_address: str,
        wallet_bes: float,
        wallet_win_rate: float,
        wallet_tier: str,
        buy_sol: float,
        token_liquidity: float,
        token_market_cap: float
    ):
        """Add a new signal to the queue."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO signal_queue (
                token_mint, token_symbol, wallet_address, wallet_bes,
                wallet_win_rate, wallet_tier, buy_sol, token_liquidity,
                token_market_cap, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (
            token_mint, token_symbol, wallet_address, wallet_bes,
            wallet_win_rate, wallet_tier, buy_sol, token_liquidity,
            token_market_cap
        ))
        conn.commit()
        conn.close()
        logger.info(f"Signal queued: {token_symbol} from {wallet_address[:15]}...")

    def pop_signal(self) -> Optional[Dict]:
        """Get next pending signal and mark as processing."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, token_mint, token_symbol, wallet_address, wallet_bes,
                   wallet_win_rate, wallet_tier, buy_sol, token_liquidity,
                   token_market_cap, created_at
            FROM signal_queue
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1
        """)
        row = cursor.fetchone()

        if not row:
            conn.close()
            return None

        signal_id = row[0]
        cursor.execute(
            "UPDATE signal_queue SET status = 'processing' WHERE id = ?",
            (signal_id,)
        )
        conn.commit()
        conn.close()

        return {
            'id': signal_id,
            'token_mint': row[1],
            'token_symbol': row[2],
            'wallet_address': row[3],
            'wallet_bes': row[4],
            'wallet_win_rate': row[5],
            'wallet_tier': row[6],
            'buy_sol': row[7],
            'token_liquidity': row[8],
            'token_market_cap': row[9],
            'created_at': row[10],
        }

    def complete_signal(self, signal_id: int, status: str = 'executed'):
        """Mark signal as completed."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE signal_queue SET status = ?, processed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, signal_id)
        )
        conn.commit()
        conn.close()

    def get_pending_count(self) -> int:
        """Get count of pending signals."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM signal_queue WHERE status = 'pending'")
        count = cursor.fetchone()[0]
        conn.close()
        return count
