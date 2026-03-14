"""
Position Lifecycle Tracker

Tracks positions from entry to exit with real-time updates.
- Records buy entries from realtime_bot.py
- Matches sells to open buys (FIFO)
- Updates peak MC hourly
- Labels outcomes after 48h or on sell
"""
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp

from database import get_connection

logger = logging.getLogger(__name__)

# Outcome thresholds (can be configured via settings)
RUNNER_THRESHOLD = 100  # +100% ROI = runner
RUG_THRESHOLD = -80     # -80% ROI = rug
MAX_TRACKING_HOURS = 48  # Auto-label after 48 hours

# Minimum buy amount to track (filter noise)
MIN_TRACK_SOL = 0.8  # Only track positions >= 0.8 SOL (quality filter)

# Maximum open positions to prevent overload
MAX_TRACKED_POSITIONS = 1000


def should_track_position(buy_amount: float, wallet_tier: str = None, wallet_type: str = None) -> bool:
    """
    Decide if a buy is worth lifecycle tracking.

    Track ALL qualified wallets AND insiders >= 0.5 SOL.
    Insiders are CRITICAL - they catch early moons at token birth.

    Expected distribution:
    - Insiders: ~60% of tracked positions (they trade more frequently)
    - Elite qualified: ~30%
    - High-Quality: ~10%

    Args:
        buy_amount: SOL amount of the buy
        wallet_tier: 'Elite', 'High-Quality', 'Mid-Tier', etc.
        wallet_type: 'qualified', 'insider', 'watchlist'

    Returns:
        True if position should be tracked
    """
    # Never track below minimum (0.5 SOL)
    if buy_amount < MIN_TRACK_SOL:
        return False

    # Track ALL insiders >= 0.5 SOL (they catch early moons!)
    # Migration snipers, launch snipers, etc. - CRITICAL signals
    if wallet_type == 'insider':
        return True

    # Track qualified wallets by tier
    if wallet_type == 'qualified':
        if wallet_tier == 'Elite':
            return True  # Track all Elite >= 0.5 SOL
        elif wallet_tier == 'High-Quality':
            return buy_amount >= 0.75  # Slightly higher bar
        elif wallet_tier == 'Mid-Tier':
            return buy_amount >= 1.5  # Much higher bar
        else:
            return buy_amount >= 2.0  # Unknown tier, only big buys

    # Watchlist wallets - track if >= 1.0 SOL
    if wallet_type == 'watchlist':
        return buy_amount >= 1.0

    return False


class PositionLifecycleTracker:
    """
    Track position lifecycles from buy to sell.

    Provides methods for:
    - Creating lifecycle records on buy
    - Matching sells to open positions (FIFO)
    - Updating peak MC during monitoring
    - Labeling outcomes
    """

    def __init__(self):
        self.runner_threshold = RUNNER_THRESHOLD
        self.rug_threshold = RUG_THRESHOLD
        self.max_tracking_hours = MAX_TRACKING_HOURS
        self._load_settings()

    def _load_settings(self):
        """Load thresholds from settings table."""
        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'lifecycle_%'")
            settings = dict(cursor.fetchall())
            conn.close()

            if 'lifecycle_runner_threshold' in settings:
                self.runner_threshold = float(settings['lifecycle_runner_threshold'])
            if 'lifecycle_rug_threshold' in settings:
                self.rug_threshold = float(settings['lifecycle_rug_threshold'])
            if 'lifecycle_check_hours' in settings:
                self.max_tracking_hours = float(settings['lifecycle_check_hours'])

        except Exception as e:
            logger.debug(f"Could not load lifecycle settings: {e}")

    def create_position(
        self,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        entry_timestamp: int,
        entry_mc: float,
        entry_liquidity: float,
        buy_sol_amount: float,
        buy_event_id: Optional[int] = None,
        wallet_type: str = 'qualified',
        wallet_tier: str = None,
        alert_message_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Create a new position lifecycle record on buy.

        Args:
            wallet_address: Wallet that made the buy
            token_address: Token contract address
            token_symbol: Token symbol
            entry_timestamp: Unix timestamp of buy
            entry_mc: Market cap at entry
            entry_liquidity: Liquidity at entry
            buy_sol_amount: SOL spent on buy
            buy_event_id: Optional link to trade_events table
            wallet_type: 'qualified', 'insider', or 'watchlist'
            wallet_tier: Wallet tier if available
            alert_message_id: Telegram message ID if alert was sent

        Returns:
            Position ID if created, None if error
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO position_lifecycle (
                    buy_event_id, wallet_address, token_address, token_symbol,
                    entry_timestamp, entry_mc, entry_liquidity, buy_sol_amount,
                    peak_mc, peak_timestamp, current_mc, last_checked_timestamp,
                    outcome, wallet_type, wallet_tier, alert_sent, alert_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                buy_event_id,
                wallet_address,
                token_address,
                token_symbol,
                entry_timestamp,
                entry_mc,
                entry_liquidity,
                buy_sol_amount,
                entry_mc,  # Initial peak = entry
                entry_timestamp,  # Initial peak timestamp = entry
                entry_mc,  # Current MC = entry
                int(time.time()),  # Last checked = now
                'open',  # Status = open
                wallet_type,
                wallet_tier,
                1 if alert_message_id else 0,
                alert_message_id,
            ))

            position_id = cursor.lastrowid
            conn.commit()

            logger.info(
                f"📊 Lifecycle created: {wallet_address[:8]}.../{token_symbol} "
                f"@ MC ${entry_mc:,.0f} ({buy_sol_amount:.2f} SOL)"
            )

            return position_id

        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                logger.debug(f"Position already exists for {wallet_address[:8]}.../{token_address[:8]}...")
            else:
                logger.warning(f"Error creating position: {e}")
            return None

        finally:
            conn.close()

    def get_oldest_open_position(
        self,
        wallet_address: str,
        token_address: str,
    ) -> Optional[Dict]:
        """
        Get the oldest open position for a wallet/token pair (FIFO matching).

        Args:
            wallet_address: Wallet address
            token_address: Token address

        Returns:
            Position dict or None if no open position
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id, buy_event_id, wallet_address, token_address, token_symbol,
                       entry_timestamp, entry_mc, entry_liquidity, buy_sol_amount,
                       peak_mc, peak_timestamp, current_mc, wallet_type, wallet_tier
                FROM position_lifecycle
                WHERE wallet_address = ?
                AND token_address = ?
                AND (outcome IS NULL OR outcome = 'open')
                ORDER BY entry_timestamp ASC
                LIMIT 1
            """, (wallet_address, token_address))

            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'buy_event_id': row[1],
                    'wallet_address': row[2],
                    'token_address': row[3],
                    'token_symbol': row[4],
                    'entry_timestamp': row[5],
                    'entry_mc': row[6],
                    'entry_liquidity': row[7],
                    'buy_sol_amount': row[8],
                    'peak_mc': row[9],
                    'peak_timestamp': row[10],
                    'current_mc': row[11],
                    'wallet_type': row[12],
                    'wallet_tier': row[13],
                }
            return None

        finally:
            conn.close()

    def record_sell_event(
        self,
        position_id: int,
        exit_timestamp: int,
        sell_sol_received: float,
        sell_event_id: Optional[int] = None,
    ) -> Dict:
        """
        Record sell event but KEEP position open for lifecycle tracking.

        Position tracking continues until 48h to capture full token lifecycle.
        Outcome is based on TOKEN performance, not wallet's exit timing.

        Args:
            position_id: Position ID
            exit_timestamp: Unix timestamp of sell
            sell_sol_received: SOL received from sell
            sell_event_id: Optional link to trade_events table

        Returns:
            Dict with sell data (position stays open)
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Get position data
            cursor.execute("""
                SELECT entry_timestamp, entry_mc, buy_sol_amount
                FROM position_lifecycle
                WHERE id = ?
            """, (position_id,))

            row = cursor.fetchone()
            if not row:
                return {'error': 'Position not found'}

            entry_timestamp, entry_mc, buy_sol_amount = row

            # Calculate wallet's ROI at sell (for logging, not for outcome)
            wallet_roi = 0
            if buy_sol_amount > 0:
                wallet_roi = ((sell_sol_received - buy_sol_amount) / buy_sol_amount) * 100

            # Record sell but keep position OPEN
            # Outcome will be set later by auto_label based on token lifecycle
            cursor.execute("""
                UPDATE position_lifecycle SET
                    sell_event_id = ?,
                    exit_timestamp = ?,
                    sell_sol_received = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                sell_event_id,
                exit_timestamp,
                sell_sol_received,
                datetime.now().isoformat(),
                position_id,
            ))

            conn.commit()

            logger.info(
                f"💰 Sell recorded: ID {position_id} | Wallet ROI: {wallet_roi:+.1f}% | "
                f"Position stays OPEN for lifecycle tracking"
            )

            return {
                'position_id': position_id,
                'wallet_roi_percent': wallet_roi,
                'entry_sol': buy_sol_amount,
                'exit_sol': sell_sol_received,
                'position_status': 'open',  # Still tracking
            }

        finally:
            conn.close()

    def close_position(
        self,
        position_id: int,
        exit_timestamp: int,
        exit_mc: float,
        sell_sol_received: float,
        sell_event_id: Optional[int] = None,
    ) -> Dict:
        """
        DEPRECATED: Use record_sell_event() instead.
        Kept for backward compatibility but just calls record_sell_event.
        """
        return self.record_sell_event(
            position_id=position_id,
            exit_timestamp=exit_timestamp,
            sell_sol_received=sell_sol_received,
            sell_event_id=sell_event_id,
        )

    def update_position_mc(
        self,
        position_id: int,
        current_mc: float,
    ) -> Dict:
        """
        Update position with current market cap (called hourly).

        Updates peak_mc if current_mc is higher.

        Args:
            position_id: Position ID
            current_mc: Current market cap

        Returns:
            Dict with update status
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Get current peak
            cursor.execute("""
                SELECT peak_mc, entry_mc, entry_timestamp, check_count
                FROM position_lifecycle
                WHERE id = ?
            """, (position_id,))

            row = cursor.fetchone()
            if not row:
                return {'error': 'Position not found'}

            peak_mc, entry_mc, entry_timestamp, check_count = row
            now = int(time.time())

            # Check if new peak
            new_peak = current_mc > (peak_mc or 0)

            if new_peak:
                time_to_peak = (now - entry_timestamp) / 3600.0
                cursor.execute("""
                    UPDATE position_lifecycle SET
                        peak_mc = ?,
                        peak_timestamp = ?,
                        time_to_peak_hours = ?,
                        current_mc = ?,
                        last_checked_timestamp = ?,
                        check_count = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    current_mc,
                    now,
                    time_to_peak,
                    current_mc,
                    now,
                    (check_count or 0) + 1,
                    datetime.now().isoformat(),
                    position_id,
                ))
            else:
                cursor.execute("""
                    UPDATE position_lifecycle SET
                        current_mc = ?,
                        last_checked_timestamp = ?,
                        check_count = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    current_mc,
                    now,
                    (check_count or 0) + 1,
                    datetime.now().isoformat(),
                    position_id,
                ))

            conn.commit()

            return {
                'position_id': position_id,
                'current_mc': current_mc,
                'new_peak': new_peak,
                'peak_mc': current_mc if new_peak else peak_mc,
            }

        finally:
            conn.close()

    def auto_label_old_position(
        self,
        position_id: int,
    ) -> Dict:
        """
        Auto-label a position after 48h based on TOKEN lifecycle.

        Outcome is based on what happened to the TOKEN, not when wallet sold:
        - RUNNER: Token peaked 2x+ from entry (opportunity existed)
        - RUG: Token dumped 80%+ from entry (token died)
        - SIDEWAYS: Neither extreme

        This teaches ML: "What happens to tokens after elite wallets buy?"

        Args:
            position_id: Position ID to label

        Returns:
            Dict with labeling result
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT entry_mc, peak_mc, current_mc, entry_timestamp,
                       buy_sol_amount, sell_sol_received
                FROM position_lifecycle
                WHERE id = ? AND (outcome IS NULL OR outcome = 'open')
            """, (position_id,))

            row = cursor.fetchone()
            if not row:
                return {'error': 'Position not found or already labeled'}

            entry_mc, peak_mc, current_mc, entry_timestamp, buy_sol, sell_sol = row

            # Calculate TOKEN lifecycle ROI (not wallet P/L)
            if entry_mc and entry_mc > 0:
                # Peak ROI: How high did the token go?
                peak_roi = ((peak_mc or entry_mc) - entry_mc) / entry_mc * 100
                # Current ROI: Where is token now?
                current_roi = ((current_mc or 0) - entry_mc) / entry_mc * 100
            else:
                peak_roi = 0
                current_roi = 0

            # Determine outcome based on TOKEN LIFECYCLE
            # This is about the token's performance, not the wallet's timing
            if peak_roi >= self.runner_threshold:
                # Token peaked at 2x+ = RUNNER
                # Even if wallet sold at 1.5x, the token was a runner
                outcome = 'runner'
                final_roi = peak_roi
            elif current_roi <= self.rug_threshold or current_mc == 0:
                # Token dumped 80%+ or is dead = RUG
                # Even if wallet sold at breakeven, the token rugged
                outcome = 'rug'
                final_roi = current_roi
            else:
                # Token didn't moon or rug = SIDEWAYS
                outcome = 'sideways'
                final_roi = max(peak_roi, current_roi)  # Best case for sideways

            now = int(time.time())
            hold_duration = (now - entry_timestamp) / 3600.0

            # Also calculate wallet's actual P/L (for reference, not for labeling)
            wallet_roi = None
            if buy_sol and buy_sol > 0 and sell_sol:
                wallet_roi = ((sell_sol - buy_sol) / buy_sol) * 100

            cursor.execute("""
                UPDATE position_lifecycle SET
                    final_roi_percent = ?,
                    hold_duration_hours = ?,
                    outcome = ?,
                    outcome_labeled_at = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                final_roi,
                hold_duration,
                outcome,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                position_id,
            ))

            conn.commit()

            wallet_note = f", wallet sold at {wallet_roi:+.1f}%" if wallet_roi else ""
            logger.info(
                f"🏷️  Labeled position {position_id}: {outcome} "
                f"(token peak: {peak_roi:+.1f}%, current: {current_roi:+.1f}%{wallet_note})"
            )

            return {
                'position_id': position_id,
                'outcome': outcome,
                'token_peak_roi': peak_roi,
                'token_current_roi': current_roi,
                'final_roi_percent': final_roi,
                'wallet_roi_percent': wallet_roi,
                'hold_duration_hours': hold_duration,
            }

        finally:
            conn.close()

    def get_open_positions(self, limit: int = 1000) -> List[Dict]:
        """
        Get all open positions for hourly monitoring.

        Args:
            limit: Max positions to return

        Returns:
            List of position dicts
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id, wallet_address, token_address, token_symbol,
                       entry_timestamp, entry_mc, buy_sol_amount,
                       peak_mc, current_mc, last_checked_timestamp, check_count
                FROM position_lifecycle
                WHERE outcome IS NULL OR outcome = 'open'
                ORDER BY entry_timestamp ASC
                LIMIT ?
            """, (limit,))

            positions = []
            for row in cursor.fetchall():
                positions.append({
                    'id': row[0],
                    'wallet_address': row[1],
                    'token_address': row[2],
                    'token_symbol': row[3],
                    'entry_timestamp': row[4],
                    'entry_mc': row[5],
                    'buy_sol_amount': row[6],
                    'peak_mc': row[7],
                    'current_mc': row[8],
                    'last_checked_timestamp': row[9],
                    'check_count': row[10],
                })

            return positions

        finally:
            conn.close()

    def get_positions_needing_label(self) -> List[Dict]:
        """
        Get open positions that are old enough to auto-label.

        Returns:
            List of positions older than max_tracking_hours
        """
        cutoff_timestamp = int(time.time()) - (self.max_tracking_hours * 3600)

        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id, wallet_address, token_address, token_symbol,
                       entry_timestamp, entry_mc, peak_mc, current_mc
                FROM position_lifecycle
                WHERE (outcome IS NULL OR outcome = 'open')
                AND entry_timestamp < ?
                ORDER BY entry_timestamp ASC
            """, (cutoff_timestamp,))

            positions = []
            for row in cursor.fetchall():
                positions.append({
                    'id': row[0],
                    'wallet_address': row[1],
                    'token_address': row[2],
                    'token_symbol': row[3],
                    'entry_timestamp': row[4],
                    'entry_mc': row[5],
                    'peak_mc': row[6],
                    'current_mc': row[7],
                })

            return positions

        finally:
            conn.close()

    def get_stats(self) -> Dict:
        """Get lifecycle tracking statistics."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            stats = {}

            # Total positions
            cursor.execute("SELECT COUNT(*) FROM position_lifecycle")
            stats['total_positions'] = cursor.fetchone()[0]

            # Open positions
            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE outcome IS NULL OR outcome = 'open'
            """)
            stats['open_positions'] = cursor.fetchone()[0]

            # By outcome
            cursor.execute("""
                SELECT outcome, COUNT(*) FROM position_lifecycle
                WHERE outcome IS NOT NULL AND outcome != 'open'
                GROUP BY outcome
            """)
            stats['by_outcome'] = dict(cursor.fetchall())

            # Average ROI by outcome
            cursor.execute("""
                SELECT outcome, AVG(final_roi_percent) FROM position_lifecycle
                WHERE outcome IS NOT NULL AND outcome != 'open'
                AND final_roi_percent IS NOT NULL
                GROUP BY outcome
            """)
            stats['avg_roi_by_outcome'] = dict(cursor.fetchall())

            # Positions in last 24h
            cutoff = int(time.time()) - 86400
            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE entry_timestamp > ?
            """, (cutoff,))
            stats['positions_24h'] = cursor.fetchone()[0]

            return stats

        finally:
            conn.close()


# Global tracker instance
_tracker = None


def get_lifecycle_tracker() -> PositionLifecycleTracker:
    """Get or create the global lifecycle tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = PositionLifecycleTracker()
    return _tracker
