"""
Position Manager - Track open positions and P&L
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    OPEN = "open"
    PARTIAL = "partial"  # Some sold (TP1 hit)
    CLOSED = "closed"
    STOPPED = "stopped"  # Stop loss hit


@dataclass
class Position:
    """Represents an open trading position."""
    id: str  # Unique position ID
    token_mint: str
    token_symbol: str
    entry_price: float  # Price per token at entry
    entry_sol: float  # SOL spent to enter
    token_amount: float  # Tokens received
    current_price: float = 0.0
    current_value_sol: float = 0.0
    pnl_percent: float = 0.0
    pnl_sol: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    tp1_hit: bool = False  # +50% take profit
    tp2_hit: bool = False  # +100% take profit
    stop_hit: bool = False  # -20% stop loss
    remaining_percent: float = 100.0  # % of position remaining
    entry_time: datetime = field(default_factory=datetime.now)
    last_update: datetime = field(default_factory=datetime.now)
    source_wallet: str = ""  # Elite wallet that triggered this trade
    entry_signature: str = ""
    exit_signatures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'token_mint': self.token_mint,
            'token_symbol': self.token_symbol,
            'entry_price': self.entry_price,
            'entry_sol': self.entry_sol,
            'token_amount': self.token_amount,
            'current_price': self.current_price,
            'current_value_sol': self.current_value_sol,
            'pnl_percent': self.pnl_percent,
            'pnl_sol': self.pnl_sol,
            'status': self.status.value,
            'tp1_hit': self.tp1_hit,
            'tp2_hit': self.tp2_hit,
            'stop_hit': self.stop_hit,
            'remaining_percent': self.remaining_percent,
            'entry_time': self.entry_time.isoformat(),
            'last_update': self.last_update.isoformat(),
            'source_wallet': self.source_wallet,
            'entry_signature': self.entry_signature,
        }


class PositionManager:
    """
    Manages trading positions with database persistence.

    Features:
    - Track open positions (max 3 simultaneous)
    - Calculate real-time P&L
    - Handle partial exits (TP1, TP2)
    - Track total performance
    """

    MAX_POSITIONS = 3

    def __init__(self, db_path: str = "data/openclaw.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.positions: Dict[str, Position] = {}  # token_mint -> Position
        self._init_database()
        self._load_positions()

    def _init_database(self):
        """Initialize OpenClaw database schema."""
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            -- Positions table
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                token_mint TEXT NOT NULL,
                token_symbol TEXT,
                entry_price REAL,
                entry_sol REAL,
                token_amount REAL,
                current_price REAL DEFAULT 0,
                current_value_sol REAL DEFAULT 0,
                pnl_percent REAL DEFAULT 0,
                pnl_sol REAL DEFAULT 0,
                status TEXT DEFAULT 'open',
                tp1_hit INTEGER DEFAULT 0,
                tp2_hit INTEGER DEFAULT 0,
                stop_hit INTEGER DEFAULT 0,
                remaining_percent REAL DEFAULT 100,
                entry_time TEXT,
                last_update TEXT,
                source_wallet TEXT,
                entry_signature TEXT,
                exit_signatures TEXT DEFAULT '[]'
            );

            -- Trade history
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id TEXT,
                trade_type TEXT,  -- 'entry', 'tp1', 'tp2', 'stop', 'manual'
                token_mint TEXT,
                token_symbol TEXT,
                sol_amount REAL,
                token_amount REAL,
                price REAL,
                pnl_sol REAL,
                pnl_percent REAL,
                signature TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Daily P&L tracking
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date TEXT PRIMARY KEY,
                starting_balance REAL,
                ending_balance REAL,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                pnl_sol REAL DEFAULT 0,
                pnl_percent REAL DEFAULT 0
            );

            -- Overall stats
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            -- Initialize stats
            INSERT OR IGNORE INTO stats (key, value) VALUES
                ('starting_balance', '0.2'),
                ('current_balance', '0.2'),
                ('total_pnl_sol', '0'),
                ('total_pnl_percent', '0'),
                ('total_trades', '0'),
                ('winning_trades', '0'),
                ('goal_balance', '128');

            CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
            CREATE INDEX IF NOT EXISTS idx_positions_token ON positions(token_mint);
            CREATE INDEX IF NOT EXISTS idx_history_timestamp ON trade_history(timestamp DESC);
        """)
        conn.commit()
        conn.close()
        logger.info(f"OpenClaw database initialized at {self.db_path}")

    def _load_positions(self):
        """Load open positions from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, token_mint, token_symbol, entry_price, entry_sol,
                   token_amount, current_price, current_value_sol, pnl_percent,
                   pnl_sol, status, tp1_hit, tp2_hit, stop_hit, remaining_percent,
                   entry_time, last_update, source_wallet, entry_signature
            FROM positions
            WHERE status IN ('open', 'partial')
        """)
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            pos = Position(
                id=row[0],
                token_mint=row[1],
                token_symbol=row[2],
                entry_price=row[3],
                entry_sol=row[4],
                token_amount=row[5],
                current_price=row[6],
                current_value_sol=row[7],
                pnl_percent=row[8],
                pnl_sol=row[9],
                status=PositionStatus(row[10]),
                tp1_hit=bool(row[11]),
                tp2_hit=bool(row[12]),
                stop_hit=bool(row[13]),
                remaining_percent=row[14],
                entry_time=datetime.fromisoformat(row[15]) if row[15] else datetime.now(),
                last_update=datetime.fromisoformat(row[16]) if row[16] else datetime.now(),
                source_wallet=row[17] or "",
                entry_signature=row[18] or "",
            )
            self.positions[pos.token_mint] = pos

        logger.info(f"Loaded {len(self.positions)} open positions")

    def _save_position(self, position: Position):
        """Save position to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO positions (
                id, token_mint, token_symbol, entry_price, entry_sol,
                token_amount, current_price, current_value_sol, pnl_percent,
                pnl_sol, status, tp1_hit, tp2_hit, stop_hit, remaining_percent,
                entry_time, last_update, source_wallet, entry_signature, exit_signatures
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.id,
            position.token_mint,
            position.token_symbol,
            position.entry_price,
            position.entry_sol,
            position.token_amount,
            position.current_price,
            position.current_value_sol,
            position.pnl_percent,
            position.pnl_sol,
            position.status.value,
            int(position.tp1_hit),
            int(position.tp2_hit),
            int(position.stop_hit),
            position.remaining_percent,
            position.entry_time.isoformat(),
            position.last_update.isoformat(),
            position.source_wallet,
            position.entry_signature,
            str(position.exit_signatures),
        ))
        conn.commit()
        conn.close()

    def can_open_position(self) -> bool:
        """Check if we can open a new position (max 3)."""
        open_count = len([p for p in self.positions.values()
                         if p.status in (PositionStatus.OPEN, PositionStatus.PARTIAL)])
        return open_count < self.MAX_POSITIONS

    def has_position(self, token_mint: str) -> bool:
        """Check if we already have a position in this token."""
        pos = self.positions.get(token_mint)
        return pos is not None and pos.status in (PositionStatus.OPEN, PositionStatus.PARTIAL)

    def open_position(
        self,
        token_mint: str,
        token_symbol: str,
        entry_price: float,
        entry_sol: float,
        token_amount: float,
        source_wallet: str,
        entry_signature: str
    ) -> Optional[Position]:
        """
        Open a new trading position.

        Returns Position if successful, None if failed.
        """
        if not self.can_open_position():
            logger.warning("Max positions reached (3)")
            return None

        if self.has_position(token_mint):
            logger.warning(f"Already have position in {token_symbol}")
            return None

        position_id = f"{token_mint[:8]}_{int(datetime.now().timestamp())}"

        position = Position(
            id=position_id,
            token_mint=token_mint,
            token_symbol=token_symbol,
            entry_price=entry_price,
            entry_sol=entry_sol,
            token_amount=token_amount,
            current_price=entry_price,
            current_value_sol=entry_sol,
            source_wallet=source_wallet,
            entry_signature=entry_signature,
        )

        self.positions[token_mint] = position
        self._save_position(position)
        self._log_trade('entry', position, entry_sol, token_amount, entry_signature)

        logger.info(f"Opened position: {token_symbol} | {entry_sol:.4f} SOL | {token_amount:.2f} tokens")
        return position

    def update_position_price(self, token_mint: str, current_price: float, sol_price: float = 1.0) -> Optional[Position]:
        """
        Update position with current price and calculate P&L.

        Args:
            token_mint: Token address
            current_price: Current token price in USD
            sol_price: Current SOL price in USD (for SOL value calc)

        Returns:
            Updated position or None
        """
        position = self.positions.get(token_mint)
        if not position or position.status == PositionStatus.CLOSED:
            return None

        position.current_price = current_price
        position.last_update = datetime.now()

        # Calculate P&L
        if position.entry_price > 0:
            position.pnl_percent = ((current_price / position.entry_price) - 1) * 100

        # Calculate current SOL value based on remaining tokens
        remaining_tokens = position.token_amount * (position.remaining_percent / 100)
        current_value_usd = remaining_tokens * current_price
        position.current_value_sol = current_value_usd / sol_price if sol_price > 0 else 0

        # Calculate P&L in SOL
        entry_sol_remaining = position.entry_sol * (position.remaining_percent / 100)
        position.pnl_sol = position.current_value_sol - entry_sol_remaining

        self._save_position(position)
        return position

    def partial_close(
        self,
        token_mint: str,
        close_percent: float,
        exit_sol: float,
        exit_signature: str,
        reason: str = "manual"
    ) -> Optional[Position]:
        """
        Partially close a position.

        Args:
            token_mint: Token address
            close_percent: Percentage of REMAINING position to close
            exit_sol: SOL received from sale
            exit_signature: Transaction signature
            reason: 'tp1', 'tp2', 'stop', 'manual'
        """
        position = self.positions.get(token_mint)
        if not position:
            return None

        # Calculate what percentage of original we're selling
        selling_percent = position.remaining_percent * (close_percent / 100)
        position.remaining_percent -= selling_percent

        # Track exit
        position.exit_signatures.append(exit_signature)

        # Update flags
        if reason == 'tp1':
            position.tp1_hit = True
            position.status = PositionStatus.PARTIAL
        elif reason == 'tp2':
            position.tp2_hit = True
        elif reason == 'stop':
            position.stop_hit = True
            position.status = PositionStatus.STOPPED

        # Check if fully closed
        if position.remaining_percent <= 0.5:  # Consider closed if <0.5%
            position.remaining_percent = 0
            if position.status != PositionStatus.STOPPED:
                position.status = PositionStatus.CLOSED

        self._save_position(position)

        # Calculate P&L for this sale
        entry_sol_portion = position.entry_sol * (selling_percent / 100)
        pnl_sol = exit_sol - entry_sol_portion
        pnl_pct = ((exit_sol / entry_sol_portion) - 1) * 100 if entry_sol_portion > 0 else 0

        self._log_trade(reason, position, exit_sol, 0, exit_signature, pnl_sol, pnl_pct)
        self._update_stats(pnl_sol, pnl_sol > 0)

        logger.info(f"Partial close ({reason}): {position.token_symbol} | "
                   f"-{close_percent:.0f}% | {exit_sol:.4f} SOL | P&L: {pnl_sol:+.4f} SOL")

        return position

    def close_position(
        self,
        token_mint: str,
        exit_sol: float,
        exit_signature: str,
        reason: str = "manual"
    ) -> Optional[Position]:
        """Fully close a position."""
        return self.partial_close(token_mint, 100.0, exit_sol, exit_signature, reason)

    def _log_trade(
        self,
        trade_type: str,
        position: Position,
        sol_amount: float,
        token_amount: float,
        signature: str,
        pnl_sol: float = 0,
        pnl_percent: float = 0
    ):
        """Log trade to history."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO trade_history (
                position_id, trade_type, token_mint, token_symbol,
                sol_amount, token_amount, price, pnl_sol, pnl_percent, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.id,
            trade_type,
            position.token_mint,
            position.token_symbol,
            sol_amount,
            token_amount,
            position.current_price,
            pnl_sol,
            pnl_percent,
            signature
        ))
        conn.commit()
        conn.close()

    def _update_stats(self, pnl_sol: float, is_win: bool):
        """Update overall statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Update totals
        cursor.execute("SELECT value FROM stats WHERE key = 'total_pnl_sol'")
        current_pnl = float(cursor.fetchone()[0])
        cursor.execute("UPDATE stats SET value = ? WHERE key = 'total_pnl_sol'",
                      (str(current_pnl + pnl_sol),))

        cursor.execute("SELECT value FROM stats WHERE key = 'total_trades'")
        total_trades = int(cursor.fetchone()[0])
        cursor.execute("UPDATE stats SET value = ? WHERE key = 'total_trades'",
                      (str(total_trades + 1),))

        if is_win:
            cursor.execute("SELECT value FROM stats WHERE key = 'winning_trades'")
            wins = int(cursor.fetchone()[0])
            cursor.execute("UPDATE stats SET value = ? WHERE key = 'winning_trades'",
                          (str(wins + 1),))

        # Update current balance
        cursor.execute("SELECT value FROM stats WHERE key = 'current_balance'")
        balance = float(cursor.fetchone()[0])
        cursor.execute("UPDATE stats SET value = ? WHERE key = 'current_balance'",
                      (str(balance + pnl_sol),))

        conn.commit()
        conn.close()

    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        return [p for p in self.positions.values()
                if p.status in (PositionStatus.OPEN, PositionStatus.PARTIAL)]

    def get_stats(self) -> Dict:
        """Get overall trading statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM stats")
        stats = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        starting = float(stats.get('starting_balance', 0.2))
        current = float(stats.get('current_balance', 0.2))
        goal = float(stats.get('goal_balance', 128))
        total_trades = int(stats.get('total_trades', 0))
        winning_trades = int(stats.get('winning_trades', 0))

        return {
            'starting_balance': starting,
            'current_balance': current,
            'total_pnl_sol': current - starting,
            'total_pnl_percent': ((current / starting) - 1) * 100 if starting > 0 else 0,
            'goal_balance': goal,
            'progress_percent': (current / goal) * 100 if goal > 0 else 0,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0,
            'open_positions': len(self.get_open_positions()),
        }

    def set_starting_balance(self, balance: float):
        """Set the starting balance."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE stats SET value = ? WHERE key = 'starting_balance'", (str(balance),))
        conn.execute("UPDATE stats SET value = ? WHERE key = 'current_balance'", (str(balance),))
        conn.commit()
        conn.close()
        logger.info(f"Starting balance set to {balance:.4f} SOL")

    def update_current_balance(self, balance: float):
        """Update current balance (from wallet)."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE stats SET value = ? WHERE key = 'current_balance'", (str(balance),))
        conn.commit()
        conn.close()
