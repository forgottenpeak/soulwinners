"""
Real-Time Monitoring Bot
- Monitors BUY transactions for qualified wallets (public channel)
- Monitors BUY transactions for user watchlist wallets (personal DM alerts)
- Win milestone alerts (2x, 3x, 5x, 10x, 20x, 50x, 100x)
- SoulScanner buttons on all buy alerts
- ONLY alerts on transactions < 5 minutes old
- ONLY alerts if buy amount >= threshold (1 SOL qualified, 1.5 SOL watchlist)
"""
import asyncio
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Set, Optional
import aiohttp
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from config.settings import (
    BUY_ALERT_KEYS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_USER_ID,
    DATABASE_PATH,
)
from database import get_connection
from bot.alert_formatter import AlertFormatter, SOULSCANNER_BOT
from collectors.helius import helius_buy_alert_rotator  # 5 keys for real-time buy alerts

# Position lifecycle tracking (V3 - track outcomes from entry to exit)
try:
    from bot.lifecycle_tracker import get_lifecycle_tracker, should_track_position
    HAS_LIFECYCLE_TRACKER = True
except ImportError:
    HAS_LIFECYCLE_TRACKER = False
    get_lifecycle_tracker = None
    should_track_position = None

# V3 Edge Auto-Trader imports (optional - graceful fallback if not available)
try:
    from ml.predictor import get_predictor, predict_trade
    from bot.auto_trader import get_auto_trader, process_trade_signal
    HAS_ML_PREDICTOR = True
except ImportError:
    HAS_ML_PREDICTOR = False
    get_predictor = None
    predict_trade = None
    get_auto_trader = None
    process_trade_signal = None

logger = logging.getLogger(__name__)

# Win milestone thresholds
WIN_MILESTONES = [2, 3, 5, 10, 20, 50, 100]

# Configuration
MIN_BUY_AMOUNT_SOL = 1.5       # Minimum 1.5 SOL for qualified wallet alerts
MIN_WATCHLIST_BUY_SOL = 1.5    # Minimum 1.5 SOL for watchlist alerts
MAX_TX_AGE_MINUTES = 5         # Only alert on transactions < 5 minutes old
POLL_INTERVAL = 30             # Seconds between polling cycles
MIN_LAST_5_WIN_RATE = 0.60     # 60% minimum win rate on last 5 closed trades

# Admin user ID - sees full addresses (from settings)
ADMIN_USER_ID = TELEGRAM_USER_ID

# Alert cache for /add command lookup
# Stores message_id -> full wallet address
ALERT_WALLET_CACHE: Dict[int, str] = {}
ALERT_CACHE_MAX_SIZE = 500  # Keep last 500 alerts

# Truncated wallet reverse lookup cache
# Stores truncated (e.g., "75ZGm...S4s9j") -> full wallet address
TRUNCATED_WALLET_CACHE: Dict[str, str] = {}
TRUNCATED_CACHE_MAX_SIZE = 1000  # Keep last 1000 wallets


def cache_alert_wallet(message_id: int, wallet_address: str):
    """Store mapping of message_id to full wallet address for /add command."""
    global ALERT_WALLET_CACHE, TRUNCATED_WALLET_CACHE

    ALERT_WALLET_CACHE[message_id] = wallet_address

    # Also cache truncated -> full mapping
    if wallet_address and len(wallet_address) > 12:
        truncated = f"{wallet_address[:5]}...{wallet_address[-5:]}"
        TRUNCATED_WALLET_CACHE[truncated] = wallet_address

    # Clean up old entries if cache too large
    if len(ALERT_WALLET_CACHE) > ALERT_CACHE_MAX_SIZE:
        # Remove oldest entries (first 100)
        keys_to_remove = list(ALERT_WALLET_CACHE.keys())[:100]
        for key in keys_to_remove:
            del ALERT_WALLET_CACHE[key]

    if len(TRUNCATED_WALLET_CACHE) > TRUNCATED_CACHE_MAX_SIZE:
        # Remove oldest entries (first 200)
        keys_to_remove = list(TRUNCATED_WALLET_CACHE.keys())[:200]
        for key in keys_to_remove:
            del TRUNCATED_WALLET_CACHE[key]

    logger.debug(f"Cached alert {message_id} -> {wallet_address[:12]}...")


def get_wallet_from_alert_cache(message_id: int) -> Optional[str]:
    """Look up full wallet address from alert cache by message_id."""
    return ALERT_WALLET_CACHE.get(message_id)


def get_wallet_from_truncated(truncated: str) -> Optional[str]:
    """Look up full wallet address from truncated format (e.g., '75ZGm...S4s9j')."""
    return TRUNCATED_WALLET_CACHE.get(truncated)


class WatchlistPositionTracker:
    """Track token positions for watchlist wallets to calculate sell P/L."""

    def __init__(self):
        # (wallet, token) -> {sol_spent, token_amount, first_buy_time}
        self.positions: Dict[tuple, Dict] = {}

    def record_buy(self, wallet: str, token: str, sol_amount: float, timestamp: int):
        """Record a buy for position tracking."""
        key = (wallet, token)
        if key not in self.positions:
            self.positions[key] = {
                'sol_spent': 0,
                'first_buy_time': timestamp,
            }
        self.positions[key]['sol_spent'] += sol_amount
        logger.debug(f"Position tracked: {wallet[:8]}... bought {sol_amount:.2f} SOL of {token[:8]}...")

    def get_position(self, wallet: str, token: str) -> Optional[Dict]:
        """Get position info for a wallet/token pair."""
        return self.positions.get((wallet, token))

    def close_position(self, wallet: str, token: str, sol_earned: float) -> Optional[Dict]:
        """Close a position and return P/L info."""
        key = (wallet, token)
        pos = self.positions.get(key)
        if not pos:
            return None

        sol_spent = pos['sol_spent']
        first_buy_time = pos['first_buy_time']

        # Calculate P/L
        pnl_sol = sol_earned - sol_spent
        pnl_pct = ((sol_earned - sol_spent) / sol_spent * 100) if sol_spent > 0 else 0

        # Remove or reduce position
        # For simplicity, we'll clear on any sell (could track partial sells later)
        del self.positions[key]

        return {
            'entry_sol': sol_spent,
            'exit_sol': sol_earned,
            'pnl_sol': pnl_sol,
            'pnl_pct': pnl_pct,
            'first_buy_time': first_buy_time,
        }


class WatchlistTracker:
    """Track user watchlist wallets and their owners."""

    def __init__(self):
        # wallet_address -> list of {user_id, added_date, win_rate, roi, nickname}
        self.watchlist_wallets: Dict[str, List[Dict]] = {}

    def load_watchlist_wallets(self):
        """Load all user watchlist wallets from database."""
        self.watchlist_wallets.clear()

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, wallet_address, added_date, win_rate, roi,
                       total_trades, notes
                FROM user_watchlists
            """)
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                user_id, wallet, added, win_rate, roi, trades, notes = row

                if wallet not in self.watchlist_wallets:
                    self.watchlist_wallets[wallet] = []

                self.watchlist_wallets[wallet].append({
                    'user_id': user_id,
                    'added_date': added,
                    'win_rate': win_rate or 0,
                    'roi': roi or 0,
                    'trades': trades or 0,
                    'nickname': notes or '',
                })

            logger.info(f"Loaded {len(self.watchlist_wallets)} watchlist wallets for {sum(len(v) for v in self.watchlist_wallets.values())} user subscriptions")

        except Exception as e:
            logger.warning(f"Failed to load watchlist wallets: {e}")

    def get_wallet_subscribers(self, wallet_address: str) -> List[Dict]:
        """Get all users subscribed to a wallet."""
        return self.watchlist_wallets.get(wallet_address, [])

    def is_watchlist_wallet(self, wallet_address: str) -> bool:
        """Check if wallet is in any user's watchlist."""
        return wallet_address in self.watchlist_wallets


class SmartMoneyTracker:
    """Track which smart money wallets are in which tokens."""

    def __init__(self):
        self.token_buyers: Dict[str, Set[str]] = {}  # token -> set of wallet addresses
        self.wallet_tiers: Dict[str, str] = {}  # wallet -> tier

    def load_wallet_tiers(self):
        """Load wallet tiers from database."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT wallet_address, tier FROM qualified_wallets")
        for row in cursor.fetchall():
            self.wallet_tiers[row[0]] = row[1]
        conn.close()
        logger.info(f"Loaded {len(self.wallet_tiers)} wallet tiers")

    def record_buy(self, token_address: str, wallet_address: str):
        """Record a wallet buying a token."""
        if token_address not in self.token_buyers:
            self.token_buyers[token_address] = set()
        self.token_buyers[token_address].add(wallet_address)

    def get_smart_money_count(self, token_address: str) -> Dict:
        """Get count of smart money wallets in a token."""
        if token_address not in self.token_buyers:
            return {'elite': 0, 'high': 0, 'total': 0}

        wallets = self.token_buyers[token_address]
        elite = 0
        high = 0

        for wallet in wallets:
            tier = self.wallet_tiers.get(wallet, '')
            if tier == 'Elite':
                elite += 1
            elif tier == 'High-Quality':
                high += 1

        return {
            'elite': elite,
            'high': high,
            'total': len(wallets)
        }


class PriceService:
    """Get live SOL price."""

    def __init__(self):
        self.sol_price: float = 78.0
        self.last_update: datetime = None

    async def get_sol_price(self) -> float:
        """Get current SOL price from CoinGecko."""
        # Cache for 60 seconds
        if self.last_update and (datetime.now() - self.last_update).seconds < 60:
            return self.sol_price

        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = data.get('solana', {}).get('usd', 0)
                        if price > 0:
                            self.sol_price = float(price)
                            self.last_update = datetime.now()
        except Exception as e:
            logger.debug(f"Price fetch failed: {e}")

        return self.sol_price


class WinMilestoneTracker:
    """Track buy entries and check for win milestones."""

    def __init__(self):
        # (wallet, token) -> {entry_mcap, message_id, alerted_milestones: set()}
        self.entries: Dict[tuple, Dict] = {}

    def record_entry(self, wallet_addr: str, token_addr: str, entry_mcap: float, message_id: int):
        """Record a new buy entry for milestone tracking."""
        key = (wallet_addr, token_addr)
        self.entries[key] = {
            'entry_mcap': entry_mcap,
            'message_id': message_id,
            'alerted_milestones': set(),
        }
        logger.debug(f"Recorded entry for milestone tracking: {wallet_addr[:8]}.../{token_addr[:8]}... at MC ${entry_mcap:,.0f}")

    def check_milestone(self, wallet_addr: str, token_addr: str, current_mcap: float) -> Optional[Dict]:
        """
        Check if current mcap hits a new milestone.
        Returns milestone info if new milestone reached, None otherwise.
        """
        key = (wallet_addr, token_addr)
        entry = self.entries.get(key)

        if not entry:
            return None

        entry_mcap = entry['entry_mcap']
        if entry_mcap <= 0:
            return None

        multiplier = current_mcap / entry_mcap
        alerted = entry['alerted_milestones']

        # Find highest unalerted milestone that's been reached
        for milestone in reversed(WIN_MILESTONES):
            if multiplier >= milestone and milestone not in alerted:
                alerted.add(milestone)
                self._save_milestone_to_db(wallet_addr, token_addr, entry_mcap, milestone, current_mcap)
                return {
                    'milestone': milestone,
                    'multiplier': multiplier,
                    'entry_mcap': entry_mcap,
                    'current_mcap': current_mcap,
                    'message_id': entry['message_id'],
                }

        return None

    def _save_milestone_to_db(self, wallet_addr: str, token_addr: str,
                               entry_mcap: float, milestone: int, current_mcap: float):
        """Save milestone to database to prevent duplicate alerts."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO win_milestones
                (token_address, wallet_address, entry_mcap, milestone_x, current_mcap)
                VALUES (?, ?, ?, ?, ?)
            """, (token_addr, wallet_addr, entry_mcap, milestone, current_mcap))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to save milestone to DB: {e}")

    def load_from_db(self):
        """Load previously alerted milestones from database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wallet_address, token_address, entry_mcap, milestone_x, alert_message_id
                FROM win_milestones
                WHERE alerted_at > datetime('now', '-7 days')
            """)
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                wallet, token, entry_mcap, milestone, msg_id = row
                key = (wallet, token)
                if key not in self.entries:
                    self.entries[key] = {
                        'entry_mcap': entry_mcap,
                        'message_id': msg_id or 0,
                        'alerted_milestones': set(),
                    }
                self.entries[key]['alerted_milestones'].add(milestone)

            logger.info(f"Loaded {len(rows)} milestone records from database")

        except Exception as e:
            logger.warning(f"Failed to load milestones from DB: {e}")


class InsiderTracker:
    """Track insider wallets from insider_pool for special alerts."""

    def __init__(self):
        # wallet_address -> {pattern, confidence, win_rate, avg_roi}
        self.insider_wallets: Dict[str, Dict] = {}

    def load_insider_wallets(self):
        """Load all insider wallets from database."""
        self.insider_wallets.clear()

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wallet_address, pattern, confidence, win_rate, avg_roi
                FROM insider_pool
            """)
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                wallet, pattern, conf, wr, roi = row
                self.insider_wallets[wallet] = {
                    'pattern': pattern or 'Unknown',
                    'confidence': conf or 0,
                    'win_rate': wr or 0,
                    'avg_roi': roi or 0,
                }

            logger.info(f"Loaded {len(self.insider_wallets)} insider wallets for monitoring")

        except Exception as e:
            logger.warning(f"Failed to load insider wallets: {e}")

    def is_insider(self, wallet_address: str) -> bool:
        """Check if wallet is in insider pool."""
        return wallet_address in self.insider_wallets

    def get_insider_info(self, wallet_address: str) -> Optional[Dict]:
        """Get insider info for a wallet."""
        return self.insider_wallets.get(wallet_address)

    @staticmethod
    def calculate_insider_confidence(pattern: str, trades_data: Dict = None) -> int:
        """
        Calculate dynamic confidence score based on pattern type and trade history.

        Base scores by pattern:
        - Airdrop Insider: 85 (highest - direct insider access)
        - Migration Sniper: 75 (migration sniping requires inside info)
        - Launch Sniper: 65 (first buyer patterns)
        - Early Bird Hunter: 60 (consistent early entries)
        - Unknown: 50 (baseline)

        Adjustments:
        - +10 for high trade frequency (>10 trades)
        - +10 for high win rate (>60%)
        - -10 for inactivity (>7 days since last trade)

        Returns:
            Confidence score 0-100
        """
        base_scores = {
            'Airdrop Insider': 85,
            'Migration Sniper': 75,
            'Launch Sniper': 65,
            'Early Bird Hunter': 60,
            'Unknown': 50,
        }

        confidence = base_scores.get(pattern, 50)

        if trades_data:
            # Boost for trade frequency
            total_trades = trades_data.get('total_trades', 0)
            if total_trades >= 20:
                confidence += 15
            elif total_trades >= 10:
                confidence += 10
            elif total_trades >= 5:
                confidence += 5

            # Boost for win rate
            win_rate = trades_data.get('win_rate', 0)
            if win_rate >= 0.7:
                confidence += 15
            elif win_rate >= 0.6:
                confidence += 10
            elif win_rate >= 0.5:
                confidence += 5

            # Penalty for inactivity
            days_since_trade = trades_data.get('days_since_last_trade', 0)
            if days_since_trade > 14:
                confidence -= 15
            elif days_since_trade > 7:
                confidence -= 10

        return min(max(confidence, 0), 100)

    def get_insider_real_stats(self, wallet_address: str) -> Dict:
        """
        Get real stats for insider from trade history.

        Returns:
            Dict with win_rate, avg_roi, total_trades, days_since_last_trade
        """
        from datetime import datetime, timedelta

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get recent trades from trade_history table (only buys >= 1.5 SOL)
            cursor.execute("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN roi > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(roi) as avg_roi,
                    MAX(timestamp) as last_trade
                FROM trade_history
                WHERE wallet_address = ?
                AND timestamp > datetime('now', '-30 days')
                AND sol_amount >= ?
            """, (wallet_address, MIN_BUY_AMOUNT_SOL))

            row = cursor.fetchone()
            conn.close()

            if row and row[0] > 0:
                total = row[0]
                wins = row[1] or 0
                avg_roi = row[2] or 0
                last_trade = row[3]

                # Calculate days since last trade
                days_since = 0
                if last_trade:
                    try:
                        last_dt = datetime.fromisoformat(last_trade.replace('Z', '+00:00'))
                        days_since = (datetime.now() - last_dt.replace(tzinfo=None)).days
                    except:
                        days_since = 0

                return {
                    'total_trades': total,
                    'win_rate': wins / total if total > 0 else 0,
                    'avg_roi': avg_roi,
                    'days_since_last_trade': days_since
                }

        except Exception as e:
            logger.debug(f"Could not get real stats for {wallet_address[:12]}...: {e}")

        # Return defaults if no data
        return {
            'total_trades': 0,
            'win_rate': 0,
            'avg_roi': 0,
            'days_since_last_trade': 0
        }


class RealTimeBot:
    """
    Real-time monitoring bot.
    - Polls Helius for new transactions using BUY_ALERT_KEYS pool (5 keys)
    - Only alerts on BUY transactions
    - Filters by transaction age and amount
    - Auto-monitors INSIDER wallets with special alerts

    API Keys: Uses helius_buy_alert_rotator which rotates through BUY_ALERT_KEYS
    (5 dedicated keys for real-time monitoring, separate from other task pools)
    """

    def __init__(self):
        self.rotator = helius_buy_alert_rotator  # 5 keys for buy alerts
        self.base_url = f"https://api.helius.xyz/v0"
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_CHANNEL_ID

        self.formatter = AlertFormatter()
        self.smart_money = SmartMoneyTracker()
        self.watchlist = WatchlistTracker()
        self.watchlist_positions = WatchlistPositionTracker()  # Track positions for sell P/L
        self.price_service = PriceService()
        self.insider_tracker = InsiderTracker()  # Insider tracking
        self.milestone_tracker = WinMilestoneTracker()  # Win milestone tracking

        # Position lifecycle tracker for ML training data
        self.lifecycle_tracker = None
        if HAS_LIFECYCLE_TRACKER:
            self.lifecycle_tracker = get_lifecycle_tracker()
            logger.info("✅ Lifecycle tracker initialized")

        self.qualified_wallets: Dict[str, Dict] = {}
        self.insider_wallets: Set[str] = set()  # Insider wallet addresses
        self.watchlist_wallets: Set[str] = set()  # Watchlist wallet addresses
        self.last_signatures: Dict[str, str] = {}  # wallet -> last seen signature
        self.running = False

        # Skip tokens (stablecoins, wrapped SOL)
        self.skip_tokens = {
            'So11111111111111111111111111111111111111112',  # WSOL
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
        }

    async def load_qualified_wallets(self):
        """Load qualified wallets from database."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM qualified_wallets")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        self.qualified_wallets.clear()
        for row in rows:
            wallet_dict = dict(zip(columns, row))
            self.qualified_wallets[wallet_dict['wallet_address']] = wallet_dict

        # Also load for smart money tracker
        self.smart_money.load_wallet_tiers()

        # Load watchlist wallets
        self.watchlist.load_watchlist_wallets()
        self.watchlist_wallets = set(self.watchlist.watchlist_wallets.keys())

        # Load insider wallets for special alerts
        self.insider_tracker.load_insider_wallets()
        self.insider_wallets = set(self.insider_tracker.insider_wallets.keys())

        # Load win milestone history
        self.milestone_tracker.load_from_db()

        logger.info(f"Loaded {len(self.qualified_wallets)} qualified wallets")
        logger.info(f"Loaded {len(self.watchlist_wallets)} watchlist wallets")
        logger.info(f"Loaded {len(self.insider_wallets)} insider wallets")
        return len(self.qualified_wallets)

    async def start(self):
        """Start real-time monitoring."""
        self.running = True

        # Load wallets
        count = await self.load_qualified_wallets()
        if count == 0:
            logger.warning("No qualified wallets to monitor!")
            return

        watchlist_count = len(self.watchlist_wallets)

        insider_count = len(self.insider_wallets)

        logger.info(f"Starting real-time monitor")
        logger.info(f"  Qualified wallets: {count}")
        logger.info(f"  Insider wallets: {insider_count}")
        logger.info(f"  Watchlist wallets: {watchlist_count}")
        logger.info(f"  Min buy (qualified): {MIN_BUY_AMOUNT_SOL} SOL")
        logger.info(f"  Min buy (watchlist): {MIN_WATCHLIST_BUY_SOL} SOL")
        logger.info(f"  Max tx age: {MAX_TX_AGE_MINUTES} minutes")
        logger.info(f"  Poll interval: {POLL_INTERVAL} seconds")

        # Send startup message to OWNER (not public channel)
        try:
            await self.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🚀 **SoulWinners Online**\n\n"
                     f"📊 Qualified wallets: {count}\n"
                     f"🎯 Insider wallets: {insider_count}\n"
                     f"👁️ Watchlist wallets: {watchlist_count}\n\n"
                     f"Monitoring buys ≥{MIN_BUY_AMOUNT_SOL} SOL (qualified)\n"
                     f"Monitoring buys ≥{MIN_WATCHLIST_BUY_SOL} SOL (watchlist)\n"
                     f"🎯 Insider buys → special alerts",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Could not send startup message to owner: {e}")

        # Start polling loop
        while self.running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error(f"Poll cycle error: {e}")

            await asyncio.sleep(POLL_INTERVAL)

    def _is_cron_enabled(self, cron_name: str) -> bool:
        """Check if a cron job is enabled in database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT enabled FROM cron_states WHERE cron_name = ?", (cron_name,))
            row = cursor.fetchone()
            conn.close()
            return bool(row[0]) if row else True  # Default to enabled
        except:
            return True  # Default to enabled if error

    def _is_lifecycle_tracking_enabled(self) -> bool:
        """
        Check if lifecycle tracking is enabled (INDEPENDENT from buy_alerts).
        This allows tracking positions silently even when channel alerts are off.
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'lifecycle_tracking_enabled'")
            row = cursor.fetchone()
            conn.close()
            return row[0].lower() == 'true' if row else False  # Default to disabled
        except:
            return False  # Default to disabled if error

    def _create_lifecycle_position(
        self,
        wallet_addr: str,
        token_address: str,
        token_symbol: str,
        tx_timestamp: int,
        entry_mcap: float,
        liquidity: float,
        sol_amount: float,
        wallet_type: str,
        wallet_tier: str,
        alert_message_id: Optional[int] = None,
    ) -> bool:
        """
        Create lifecycle position for ML training (runs independently of alerts).

        Returns True if position was created successfully.
        """
        if not self.lifecycle_tracker:
            return False

        if not self._is_lifecycle_tracking_enabled():
            return False

        if entry_mcap <= 0:
            return False

        if not should_track_position(sol_amount, wallet_tier, wallet_type):
            return False

        try:
            self.lifecycle_tracker.create_position(
                wallet_address=wallet_addr,
                token_address=token_address,
                token_symbol=token_symbol,
                entry_timestamp=tx_timestamp,
                entry_mc=entry_mcap,
                entry_liquidity=liquidity,
                buy_sol_amount=sol_amount,
                buy_event_id=None,
                wallet_type=wallet_type,
                wallet_tier=wallet_tier,
                alert_message_id=alert_message_id,
            )
            logger.info(f"📊 Lifecycle position created: {wallet_addr[:8]}... {sol_amount:.2f} SOL ({wallet_type})")
            return True
        except Exception as e:
            logger.debug(f"Lifecycle tracking error: {e}")
            return False

    def _is_ai_gate_enabled(self) -> bool:
        """Check if AI decision gate is enabled."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'ai_gate_enabled'")
            row = cursor.fetchone()
            conn.close()
            return row[0] == 'true' if row else False  # Default to disabled
        except:
            return False

    def _is_autotrader_enabled(self) -> bool:
        """Check if auto-trader is enabled."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'autotrader_enabled'")
            row = cursor.fetchone()
            conn.close()
            return row[0] == 'true' if row else False  # Default to disabled
        except:
            return False

    async def _poll_cycle(self):
        """One polling cycle - check qualified + insider + watchlist wallets."""
        # Check if buy_alerts is enabled
        if not self._is_cron_enabled('buy_alerts'):
            logger.info("📡 Poll cycle skipped - buy_alerts DISABLED")
            return

        total_qualified = len(self.qualified_wallets)
        total_insider = len(self.insider_wallets)
        total_watchlist = len(self.watchlist_wallets)

        logger.info(f"📡 Poll cycle starting ({total_qualified} qualified + {total_insider} insiders + {total_watchlist} watchlist)...")

        checked = 0

        # Check qualified wallets (public channel alerts)
        for wallet_addr, wallet_data in self.qualified_wallets.items():
            try:
                await self._check_wallet(wallet_addr, wallet_data, is_watchlist=False, is_insider=False)
                checked += 1
                await asyncio.sleep(1.5)  # Rate limit between wallets
            except Exception as e:
                logger.warning(f"Error checking qualified {wallet_addr[:15]}...: {e}")

        # Check insider wallets (special public channel alerts)
        for wallet_addr in self.insider_wallets:
            # Skip if already checked as qualified wallet
            if wallet_addr in self.qualified_wallets:
                continue

            try:
                await self._check_wallet(wallet_addr, None, is_watchlist=False, is_insider=True)
                checked += 1
                await asyncio.sleep(1.5)  # Rate limit between wallets
            except Exception as e:
                logger.warning(f"Error checking insider {wallet_addr[:15]}...: {e}")

        # Check watchlist wallets (personal DM alerts)
        # Note: Wallets in both qualified/insider AND watchlist get DMs sent from _send_qualified_alert/_send_insider_alert
        watchlist_only_count = 0
        for wallet_addr in self.watchlist_wallets:
            # Skip if already checked as qualified or insider wallet (DM will be sent there)
            if wallet_addr in self.qualified_wallets or wallet_addr in self.insider_wallets:
                continue

            watchlist_only_count += 1
            try:
                await self._check_wallet(wallet_addr, None, is_watchlist=True, is_insider=False)
                checked += 1
                await asyncio.sleep(1.5)  # Rate limit between wallets
            except Exception as e:
                logger.warning(f"Error checking watchlist {wallet_addr[:15]}...: {e}")

        if watchlist_only_count > 0:
            logger.info(f"📋 Checked {watchlist_only_count} watchlist-only wallets")

        logger.info(f"📡 Poll cycle complete ({checked} wallets checked)")

        # Check for win milestones on tracked entries
        await self._check_win_milestones()

    async def _check_win_milestones(self):
        """Check all tracked entries for win milestones (2x, 3x, 5x, etc.)."""
        entries = list(self.milestone_tracker.entries.items())

        if not entries:
            return

        logger.debug(f"Checking {len(entries)} entries for win milestones...")

        for (wallet_addr, token_addr), entry_data in entries:
            try:
                # Get current token info
                token_info = await self._get_token_info(token_addr)
                current_mcap = token_info.get('market_cap', 0)

                if current_mcap <= 0:
                    continue

                # Check for milestone
                milestone = self.milestone_tracker.check_milestone(
                    wallet_addr, token_addr, current_mcap
                )

                if milestone:
                    token_symbol = token_info.get('symbol', '???')
                    await self._send_win_milestone_alert(
                        token_symbol=token_symbol,
                        token_address=token_addr,
                        milestone_data=milestone
                    )

                # Rate limit
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.debug(f"Error checking milestone for {token_addr[:12]}...: {e}")

    async def _send_win_milestone_alert(self, token_symbol: str, token_address: str, milestone_data: Dict):
        """Send a WIN MILESTONE alert to the public channel."""
        multiplier = milestone_data['multiplier']
        entry_mcap = milestone_data['entry_mcap']
        current_mcap = milestone_data['current_mcap']
        original_msg_id = milestone_data.get('message_id', 0)

        # Build link to original alert (if we have the message ID)
        next_alert_link = None
        if original_msg_id and self.channel_id:
            # Channel links use the format: https://t.me/c/CHANNEL_ID/MESSAGE_ID
            # For public channels: https://t.me/CHANNEL_NAME/MESSAGE_ID
            channel_str = str(self.channel_id)
            if channel_str.startswith('-100'):
                channel_id_short = channel_str[4:]  # Remove -100 prefix
                next_alert_link = f"https://t.me/c/{channel_id_short}/{original_msg_id}"

        # Format the alert
        message, keyboard = self.formatter.format_win_milestone_alert(
            token_symbol=token_symbol,
            token_address=token_address,
            multiplier=multiplier,
            entry_mcap=entry_mcap,
            current_mcap=current_mcap,
            next_alert_link=next_alert_link
        )

        logger.info(f"📈 WIN MILESTONE: ${token_symbol} hit {multiplier:.1f}x!")

        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            logger.info(f"✅ WIN ALERT sent: ${token_symbol} {milestone_data['milestone']}x milestone")

        except Exception as e:
            logger.error(f"❌ Failed to send win milestone alert: {e}")

    async def _check_wallet(self, wallet_addr: str, wallet_data: Optional[Dict],
                            is_watchlist: bool = False, is_insider: bool = False):
        """Check a single wallet for new transactions using rotated API keys."""
        api_key = await self.rotator.get_key()
        url = f"{self.base_url}/addresses/{wallet_addr}/transactions?api-key={api_key}&limit=5"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 429:
                        logger.debug(f"Key {api_key[:8]}... rate limited, rotating...")
                        return
                    if response.status != 200:
                        return
                    txs = await response.json()
        except Exception as e:
            logger.debug(f"Request failed: {e}")
            return

        if not txs:
            return

        # Get last seen signature for this wallet
        last_sig = self.last_signatures.get(wallet_addr)
        latest_sig = txs[0].get('signature')

        # Update last signature
        self.last_signatures[wallet_addr] = latest_sig

        # If this is first check, just record and return
        if not last_sig:
            return

        # If no new transactions
        if latest_sig == last_sig:
            return

        # Process new transactions (those before our last seen)
        for tx in txs:
            if tx.get('signature') == last_sig:
                break  # Reached previously seen tx

            await self._process_transaction(tx, wallet_addr, wallet_data, is_watchlist, is_insider)

    async def _process_transaction(self, tx: Dict, wallet_addr: str,
                                    wallet_data: Optional[Dict], is_watchlist: bool = False,
                                    is_insider: bool = False):
        """Process a transaction and potentially send alert."""
        # 1. Parse the transaction
        parsed = self._parse_swap(tx, wallet_addr)
        if not parsed:
            return

        tx_type = parsed['type']
        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']

        # 2. Check transaction age (< 5 minutes)
        tx_timestamp = parsed['timestamp']
        now = datetime.now().timestamp()
        age_minutes = (now - tx_timestamp) / 60

        if age_minutes > MAX_TX_AGE_MINUTES:
            logger.debug(f"⏭️ Skipping old tx ({age_minutes:.1f}m old)")
            return

        # 3. Handle WATCHLIST wallets - track buys AND sells
        if is_watchlist:
            if tx_type == 'buy':
                # Track position for later sell P/L calculation
                self.watchlist_positions.record_buy(wallet_addr, token_address, sol_amount, tx_timestamp)

                # Check minimum buy amount
                if sol_amount < MIN_WATCHLIST_BUY_SOL:
                    logger.debug(f"⏭️ Skipping small watchlist buy ({sol_amount:.4f} SOL < {MIN_WATCHLIST_BUY_SOL} SOL)")
                    return

                await self._send_watchlist_buy_alert(wallet_addr, parsed)

            elif tx_type == 'sell':
                # Get position info for P/L calculation
                position = self.watchlist_positions.close_position(wallet_addr, token_address, sol_amount)
                await self._send_watchlist_sell_alert(wallet_addr, parsed, position)

            return

        # 4. Handle INSIDER wallets - buys (alert) + sells (lifecycle only)
        if is_insider:
            if tx_type == 'sell':
                # Record sell but keep tracking token lifecycle
                await self._record_lifecycle_sell(wallet_addr, parsed)
                return

            # Lower minimum for insiders (0.5 SOL)
            if sol_amount < 0.5:
                logger.debug(f"⏭️ Skipping small insider buy ({sol_amount:.4f} SOL < 0.5 SOL)")
                return

            await self._send_insider_alert(wallet_addr, parsed)

            # ALSO send watchlist DM if this wallet is in someone's watchlist
            if self.watchlist.is_watchlist_wallet(wallet_addr):
                logger.info(f"📨 Insider also in watchlist - sending DM alerts")
                await self._send_watchlist_buy_alert(wallet_addr, parsed)
            return

        # 5. Handle QUALIFIED wallets - buys (alert) + sells (lifecycle only)
        if tx_type == 'sell':
            # Record sell but keep tracking token lifecycle
            await self._record_lifecycle_sell(wallet_addr, parsed)
            return

        # Check buy amount
        if sol_amount < MIN_BUY_AMOUNT_SOL:
            logger.debug(f"⏭️ Skipping small buy ({sol_amount:.4f} SOL < {MIN_BUY_AMOUNT_SOL} SOL)")
            return

        # Check last 5 trades quality
        recent_quality = await self._check_last_5_trades_quality(wallet_addr)
        if not recent_quality['passed']:
            logger.info(f"⏭️ Skipping - wallet on losing streak ({recent_quality['win_rate']*100:.0f}%)")
            return

        await self._send_qualified_alert(wallet_addr, wallet_data, parsed)

        # ALSO send watchlist DM if this wallet is in someone's watchlist
        if self.watchlist.is_watchlist_wallet(wallet_addr):
            logger.info(f"📨 Wallet also in watchlist - sending DM alerts")
            await self._send_watchlist_buy_alert(wallet_addr, parsed)

    async def _send_qualified_alert(self, wallet_addr: str, wallet_data: Dict, parsed: Dict):
        """
        Handle qualified wallet buy - lifecycle tracking + optional channel alert.

        INDEPENDENT CONTROLS:
        - lifecycle_tracking_enabled: Creates position records for ML (silent)
        - buy_alerts (cron): Sends alerts to public channel
        """
        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']
        tx_timestamp = parsed['timestamp']

        # Record for smart money tracking (always)
        self.smart_money.record_buy(token_address, wallet_addr)

        # Get token info from DexScreener (needed for both tracking and alerts)
        token_info = await self._get_token_info(token_address)
        entry_mcap = token_info.get('market_cap', 0)
        wallet_tier = wallet_data.get('tier') if wallet_data else None

        # =====================================================================
        # LIFECYCLE TRACKING (INDEPENDENT - runs even if alerts disabled)
        # =====================================================================
        self._create_lifecycle_position(
            wallet_addr=wallet_addr,
            token_address=token_address,
            token_symbol=token_info.get('symbol', '???'),
            tx_timestamp=tx_timestamp,
            entry_mcap=entry_mcap,
            liquidity=token_info.get('liquidity', 0),
            sol_amount=sol_amount,
            wallet_type='qualified',
            wallet_tier=wallet_tier,
            alert_message_id=None,  # No alert yet
        )

        # =====================================================================
        # CHECK IF CHANNEL ALERTS ENABLED (separate from lifecycle tracking)
        # =====================================================================
        if not self._is_cron_enabled('buy_alerts'):
            logger.debug(f"📊 Lifecycle tracked (alerts OFF): {wallet_addr[:8]}... {sol_amount:.2f} SOL")
            return  # Skip channel alert, but tracking is done

        # =====================================================================
        # V3 EDGE: AI DECISION LAYER
        # =====================================================================
        if HAS_ML_PREDICTOR and self._is_ai_gate_enabled():
            try:
                # Build feature snapshot and get AI prediction
                wallet_data_copy = dict(wallet_data) if wallet_data else {}
                wallet_data_copy['wallet_address'] = wallet_addr

                prediction = predict_trade(wallet_data_copy, token_info, parsed)

                prob_runner = prediction.get('prob_runner', 0.5)
                prob_rug = prediction.get('prob_rug', 0.5)
                decision = prediction.get('decision', 'flag')

                # AI decision gate - skip if not approved
                if decision != 'approve':
                    logger.info(f"🤖 AI SKIPPED: {token_info.get('symbol', '???')} "
                               f"({prob_runner:.0%} runner, {prob_rug:.0%} rug) - {prediction.get('decision_reason', '')}")
                    return  # Don't alert

                logger.info(f"🤖 AI APPROVED: {token_info.get('symbol', '???')} "
                           f"({prob_runner:.0%} runner, {prob_rug:.0%} rug)")

                # Optionally trigger auto-trader
                if self._is_autotrader_enabled():
                    asyncio.create_task(
                        process_trade_signal(wallet_data_copy, token_info, parsed)
                    )

            except Exception as e:
                logger.warning(f"AI prediction failed (continuing without): {e}")

        # Get smart money count for this token
        smart_money = self.smart_money.get_smart_money_count(token_address)

        # Get recent trades for this wallet
        recent_trades = await self._get_recent_trades(wallet_addr)

        # Get SOL price
        sol_price = await self.price_service.get_sol_price()

        # Format alert
        trade_data = {
            'sol_amount': sol_amount,
            'timestamp': tx_timestamp,
        }

        # Ensure wallet_address is in wallet_data for truncation
        wallet_data_with_addr = dict(wallet_data) if wallet_data else {}
        wallet_data_with_addr['wallet_address'] = wallet_addr

        message = self.formatter.format_buy_alert(
            wallet=wallet_data_with_addr,
            token=token_info,
            trade=trade_data,
            smart_money=smart_money,
            recent_trades=recent_trades,
            sol_price=sol_price
        )

        # Get SoulScanner buttons for buy alerts
        reply_markup = self.formatter.get_buy_alert_buttons(token_address)

        # Send to public channel
        logger.info(f"Sending qualified alert for {token_info.get('symbol')} ({sol_amount:.2f} SOL)...")

        try:
            image_url = token_info.get('image_url', '')
            sent_message = None

            if image_url:
                try:
                    sent_message = await self.bot.send_photo(
                        chat_id=self.channel_id,
                        photo=image_url,
                        caption=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
                except Exception:
                    sent_message = await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
            else:
                sent_message = await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )

            # Cache message_id -> wallet for /add command lookup
            if sent_message:
                cache_alert_wallet(sent_message.message_id, wallet_addr)

                # Record entry for win milestone tracking
                if entry_mcap > 0:
                    self.milestone_tracker.record_entry(
                        wallet_addr, token_address, entry_mcap, sent_message.message_id
                    )

            logger.info(f"✅ QUALIFIED ALERT: {wallet_data.get('tier')} bought {token_info.get('symbol')} for {sol_amount:.2f} SOL")

        except Exception as e:
            logger.error(f"❌ FAILED to send qualified alert: {e}")

    async def _send_insider_alert(self, wallet_addr: str, parsed: Dict):
        """
        Handle insider wallet buy - lifecycle tracking + optional channel alert.

        INDEPENDENT CONTROLS:
        - lifecycle_tracking_enabled: Creates position records for ML (silent)
        - buy_alerts (cron): Sends alerts to public channel
        """
        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']
        tx_timestamp = parsed['timestamp']

        # Get insider info
        insider_info = self.insider_tracker.get_insider_info(wallet_addr)
        pattern = insider_info.get('pattern', 'Unknown') if insider_info else 'Unknown'

        # Get real stats from trade history
        real_stats = self.insider_tracker.get_insider_real_stats(wallet_addr)

        # Calculate dynamic confidence based on pattern and real stats
        confidence = InsiderTracker.calculate_insider_confidence(pattern, real_stats)

        # Use real stats if available, otherwise fall back to DB values
        if real_stats['total_trades'] > 0:
            win_rate = real_stats['win_rate']
            avg_roi = real_stats['avg_roi']
        else:
            win_rate = insider_info.get('win_rate', 0) if insider_info else 0
            avg_roi = insider_info.get('avg_roi', 0) if insider_info else 0

        # Get token info from DexScreener (now with extended metrics)
        token_info = await self._get_token_info(token_address)
        market_cap = token_info.get('market_cap', 0)
        liquidity = token_info.get('liquidity', 0)
        token_symbol = token_info.get('symbol', '???')

        # =====================================================================
        # LIFECYCLE TRACKING (INDEPENDENT - runs even if alerts disabled)
        # =====================================================================
        self._create_lifecycle_position(
            wallet_addr=wallet_addr,
            token_address=token_address,
            token_symbol=token_symbol,
            tx_timestamp=tx_timestamp,
            entry_mcap=market_cap,
            liquidity=liquidity,
            sol_amount=sol_amount,
            wallet_type='insider',
            wallet_tier=pattern,
            alert_message_id=None,
        )

        # =====================================================================
        # CHECK IF CHANNEL ALERTS ENABLED (separate from lifecycle tracking)
        # =====================================================================
        if not self._is_cron_enabled('buy_alerts'):
            logger.debug(f"📊 Insider lifecycle tracked (alerts OFF): {wallet_addr[:8]}... {sol_amount:.2f} SOL")
            return  # Skip channel alert, but tracking is done

        # Continue with token info extraction for alert formatting
        token_name = token_info.get('name', 'Unknown')
        volume_5m = token_info.get('volume_5m', 0)
        volume_1h = token_info.get('volume_1h', 0)
        volume_24h = token_info.get('volume_24h', 0)
        holders = token_info.get('holders', 0)
        token_age_hours = token_info.get('token_age_hours', 0)
        buys_5m = token_info.get('buys_5m', 0)
        sells_5m = token_info.get('sells_5m', 0)
        price_change_5m = token_info.get('price_change_5m', 0)
        price_change_1h = token_info.get('price_change_1h', 0)

        # Get SOL price
        sol_price = await self.price_service.get_sol_price()
        usd_value = sol_amount * sol_price

        # Calculate time ago
        now = datetime.now().timestamp()
        age_seconds = now - tx_timestamp
        if age_seconds < 60:
            time_ago = "just now"
        elif age_seconds < 3600:
            time_ago = f"{int(age_seconds / 60)}m ago"
        else:
            time_ago = f"{int(age_seconds / 3600)}h ago"

        # Format token age
        if token_age_hours < 1:
            age_str = f"{int(token_age_hours * 60)}m"
        elif token_age_hours < 24:
            age_str = f"{token_age_hours:.1f}h"
        elif token_age_hours < 168:  # Less than a week
            age_str = f"{token_age_hours / 24:.1f}d"
        else:
            age_str = f"{token_age_hours / 168:.1f}w"

        # Format confidence and win rate
        conf_pct = confidence * 100 if confidence <= 1 else confidence
        wr_pct = win_rate * 100 if win_rate <= 1 else win_rate

        # Format numbers
        def fmt_num(n):
            if n >= 1_000_000_000:
                return f"${n/1_000_000_000:.1f}B"
            elif n >= 1_000_000:
                return f"${n/1_000_000:.1f}M"
            elif n >= 1_000:
                return f"${n/1_000:.0f}K"
            return f"${n:.0f}"

        # Build enhanced INSIDER ALERT message with FULL wallet address
        message = f"""🎯🔥 **INSIDER ALERT** 🔥🎯
⏰ Bought {time_ago}

🪙 **${token_symbol}** ({token_name})
📍 CA: `{token_address}`
💰 **{sol_amount:.2f} SOL** (~${usd_value:.0f})

📊 **TOKEN METRICS:**
├─ 💹 MC: {fmt_num(market_cap)}
├─ 💧 Liq: {fmt_num(liquidity)}
├─ 👥 Holders: {holders if holders else 'N/A'}
└─ ⏱️ Age: {age_str}

📈 **VOLUME:**
├─ 5m: {fmt_num(volume_5m)} ({price_change_5m:+.1f}%)
├─ 1h: {fmt_num(volume_1h)} ({price_change_1h:+.1f}%)
└─ 24h: {fmt_num(volume_24h)}

🔄 **5m Activity:** {buys_5m} buys / {sells_5m} sells

🕵️ **INSIDER PROFILE:**
├─ 🎯 Pattern: {pattern}
├─ 📊 Confidence: {conf_pct:.0f}%
├─ ✅ Win Rate: {wr_pct:.0f}%
└─ 💰 Avg ROI: {avg_roi:+.0f}%

👛 **Wallet:** `{wallet_addr[:5]}...{wallet_addr[-5:]}`

⚠️ _Insider detected via launch/migration sniping_
💡 _Reply /wallet to reveal full address (admin only)_

🔗 [DexScreener](https://dexscreener.com/solana/{token_address}) | [Birdeye](https://birdeye.so/token/{token_address}?chain=solana)"""

        # Get SoulScanner buttons for buy alerts
        reply_markup = self.formatter.get_buy_alert_buttons(token_address)

        # Send to public channel
        logger.info(f"🎯 Sending INSIDER alert for {token_symbol} ({sol_amount:.2f} SOL)...")

        try:
            image_url = token_info.get('image_url', '')
            sent_message = None

            if image_url:
                try:
                    sent_message = await self.bot.send_photo(
                        chat_id=self.channel_id,
                        photo=image_url,
                        caption=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
                except Exception:
                    sent_message = await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
            else:
                sent_message = await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )

            # Cache message_id -> wallet for /add command lookup
            if sent_message:
                cache_alert_wallet(sent_message.message_id, wallet_addr)

                # Record entry for win milestone tracking
                if market_cap > 0:
                    self.milestone_tracker.record_entry(
                        wallet_addr, token_address, market_cap, sent_message.message_id
                    )

            logger.info(f"✅ INSIDER ALERT: {pattern} insider bought {token_symbol} for {sol_amount:.2f} SOL")

        except Exception as e:
            logger.error(f"❌ FAILED to send insider alert: {e}")

    async def _send_watchlist_buy_alert(self, wallet_addr: str, parsed: Dict):
        """Send personal DM buy alerts to users who have this wallet in their watchlist."""
        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']

        # Get all users subscribed to this wallet
        subscribers = self.watchlist.get_wallet_subscribers(wallet_addr)

        if not subscribers:
            return

        # Get token info (extended metrics)
        token_info = await self._get_token_info(token_address)
        token_symbol = token_info.get('symbol', '???')
        token_name = token_info.get('name', 'Unknown')
        market_cap = token_info.get('market_cap', 0)
        liquidity = token_info.get('liquidity', 0)
        holders = token_info.get('holders', 0)
        token_age_hours = token_info.get('token_age_hours', 0)
        volume_5m = token_info.get('volume_5m', 0)
        volume_1h = token_info.get('volume_1h', 0)
        volume_24h = token_info.get('volume_24h', 0)
        buys_5m = token_info.get('buys_5m', 0)
        sells_5m = token_info.get('sells_5m', 0)
        price_change_5m = token_info.get('price_change_5m', 0)

        # Get SOL price for USD values
        sol_price = await self.price_service.get_sol_price()
        usd_value = sol_amount * sol_price

        # Create position lifecycle tracker for ML training (watchlist - smart filter)
        if (self.lifecycle_tracker and market_cap > 0 and
            should_track_position(sol_amount, None, 'watchlist')):
            try:
                self.lifecycle_tracker.create_position(
                    wallet_address=wallet_addr,
                    token_address=token_address,
                    token_symbol=token_symbol,
                    entry_timestamp=parsed.get('timestamp', int(datetime.now().timestamp())),
                    entry_mc=market_cap,
                    entry_liquidity=liquidity,
                    buy_sol_amount=sol_amount,
                    buy_event_id=None,
                    wallet_type='watchlist',
                    wallet_tier=None,
                    alert_message_id=None,  # DM alerts don't go to channel
                )
                logger.info(f"📊 Watchlist position tracked: {wallet_addr[:8]}... {sol_amount:.2f} SOL")
            except Exception as e:
                logger.debug(f"Lifecycle tracking error (watchlist): {e}")

        # Get wallet performance from recent trades
        recent_trades = await self._get_recent_trades(wallet_addr)

        # Calculate wallet performance stats
        total_trades = len(recent_trades)
        wins = sum(1 for t in recent_trades if t.get('pnl_percent', 0) > 0)
        losses = sum(1 for t in recent_trades if t.get('pnl_percent', 0) < 0)
        win_rate = wins / total_trades if total_trades > 0 else 0

        # Average ROI
        avg_roi = 0
        if recent_trades:
            rois = [t.get('pnl_percent', 0) for t in recent_trades if t.get('pnl_percent', 0) != 0]
            avg_roi = sum(rois) / len(rois) if rois else 0

        # Best trade
        best_trade = None
        best_roi = 0
        for t in recent_trades:
            pnl = t.get('pnl_percent', 0)
            if pnl > best_roi:
                best_roi = pnl
                best_trade = t.get('token_symbol', '???')

        # Recent streak (last 5 trades)
        recent_5 = recent_trades[:5] if len(recent_trades) >= 5 else recent_trades
        streak_icons = []
        for t in recent_5:
            pnl = t.get('pnl_percent', 0)
            if pnl > 0:
                streak_icons.append("✅")
            elif pnl < 0:
                streak_icons.append("❌")
            else:
                streak_icons.append("⏳")  # Open position
        streak_str = "".join(streak_icons) if streak_icons else "N/A"
        streak_wins = streak_icons.count("✅")
        streak_total = len([s for s in streak_icons if s != "⏳"])

        # Last trade time
        last_trade_str = "N/A"
        if recent_trades and recent_trades[0].get('last_tx_time'):
            last_time = recent_trades[0]['last_tx_time']
            age_seconds = datetime.now().timestamp() - last_time
            if age_seconds < 3600:
                last_trade_str = f"{int(age_seconds / 60)}m ago"
            elif age_seconds < 86400:
                last_trade_str = f"{int(age_seconds / 3600)}h ago"
            else:
                last_trade_str = f"{int(age_seconds / 86400)}d ago"

        # Format token age
        if token_age_hours < 1:
            age_str = f"{int(token_age_hours * 60)}m"
        elif token_age_hours < 24:
            age_str = f"{token_age_hours:.1f}h"
        else:
            age_str = f"{token_age_hours / 24:.1f}d"

        # Calculate liquidity ratio
        liq_ratio = (liquidity / market_cap * 100) if market_cap > 0 else 0

        # Calculate momentum (5m vs 1h volume)
        momentum = 0
        if volume_1h > 0:
            momentum = ((volume_5m * 12) - volume_1h) / volume_1h * 100  # Annualize 5m to compare

        # Format numbers helper
        def fmt_num(n):
            if n >= 1_000_000:
                return f"${n/1_000_000:.1f}M"
            elif n >= 1_000:
                return f"${n/1_000:.0f}K"
            return f"${n:.0f}"

        logger.info(f"🔔 WATCHLIST BUY: {wallet_addr[:12]}... bought {sol_amount:.2f} SOL of ${token_symbol}")

        # Send personalized alert to each subscriber
        for sub in subscribers:
            user_id = sub['user_id']
            added_date = sub.get('added_date', '')
            nickname = sub.get('nickname', '')

            # Calculate days since added
            days_ago = "Unknown"
            if added_date:
                try:
                    added_dt = datetime.fromisoformat(added_date.replace('Z', '+00:00'))
                    days = (datetime.now() - added_dt).days
                    days_ago = f"{days}d"
                except:
                    days_ago = "?"

            # Truncated wallet display for cleaner look
            wallet_display = f"`{wallet_addr[:5]}...{wallet_addr[-5:]}`"

            # Best trade display
            best_str = f"+{best_roi:.0f}% ({best_trade})" if best_trade else "N/A"

            # Build enhanced alert message
            message = f"""🔔 **WATCHLIST BUY**{f' ({nickname})' if nickname else ''}

👛 Wallet: {wallet_display}
💰 Bought **{sol_amount:.2f} SOL** (~${usd_value:.0f}) of **${token_symbol}**

📊 **WALLET PERFORMANCE:**
├─ Win Rate: {win_rate*100:.0f}% ({wins}/{total_trades} trades)
├─ Avg ROI: {avg_roi:+.0f}% per trade
├─ Best Trade: {best_str}
├─ Recent: {streak_str} ({streak_wins}/{streak_total} last)
└─ Last Trade: {last_trade_str}

🪙 **TOKEN METRICS:**
├─ MC: {fmt_num(market_cap)} | Liq: {fmt_num(liquidity)} ({liq_ratio:.0f}%)
├─ Holders: {holders if holders else 'N/A'} | Age: {age_str}
├─ Vol 5m: {fmt_num(volume_5m)} | 1h: {fmt_num(volume_1h)} | 24h: {fmt_num(volume_24h)}
├─ Activity: {buys_5m} buys / {sells_5m} sells (5m)
└─ Momentum: {momentum:+.0f}% | Price: {price_change_5m:+.1f}% (5m)

💵 **ENTRY:**
├─ Position: ${usd_value:.0f} USD ({sol_amount:.2f} SOL)
├─ SOL Price: ${sol_price:.2f}
└─ Added: {days_ago} ago

🔗 [DexScreener](https://dexscreener.com/solana/{token_address}) | [Wallet](https://solscan.io/account/{wallet_addr})"""

            # Get SoulScanner buttons for buy alerts
            reply_markup = self.formatter.get_buy_alert_buttons(token_address)

            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
                logger.info(f"✅ Watchlist buy alert sent to user {user_id} for ${token_symbol}")

            except Exception as e:
                logger.warning(f"Failed to send watchlist alert to {user_id}: {e}")

    async def _send_watchlist_sell_alert(self, wallet_addr: str, parsed: Dict, position: Optional[Dict]):
        """Send personal DM sell alerts to users who have this wallet in their watchlist."""
        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']  # SOL earned from sell

        # Get all users subscribed to this wallet
        subscribers = self.watchlist.get_wallet_subscribers(wallet_addr)

        if not subscribers:
            return

        # Get token info
        token_info = await self._get_token_info(token_address)
        token_symbol = token_info.get('symbol', '???')

        # Calculate P/L
        if position:
            entry_sol = position['entry_sol']
            pnl_sol = position['pnl_sol']
            pnl_pct = position['pnl_pct']
            first_buy_time = position['first_buy_time']

            # Calculate hold time
            hold_seconds = int(datetime.now().timestamp() - first_buy_time)
            if hold_seconds < 3600:
                hold_time = f"{hold_seconds // 60} minutes"
            elif hold_seconds < 86400:
                hold_time = f"{hold_seconds // 3600} hours"
            else:
                hold_time = f"{hold_seconds // 86400} days"

            pnl_emoji = "📈" if pnl_sol >= 0 else "📉"
            pnl_str = f"{pnl_sol:+.2f} SOL ({pnl_pct:+.0f}%)"
        else:
            # No position tracked (maybe bought before bot started)
            entry_sol = 0
            pnl_sol = 0
            pnl_pct = 0
            pnl_emoji = "📊"
            pnl_str = "Unknown (no entry tracked)"
            hold_time = "Unknown"

        logger.info(f"📤 WATCHLIST SELL: {wallet_addr[:12]}... sold {sol_amount:.2f} SOL of ${token_symbol} ({pnl_str})")

        # Record sell but keep tracking token lifecycle
        if self.lifecycle_tracker:
            try:
                lifecycle_position = self.lifecycle_tracker.get_oldest_open_position(
                    wallet_address=wallet_addr,
                    token_address=token_address,
                )
                if lifecycle_position:
                    exit_timestamp = parsed.get('timestamp', int(datetime.now().timestamp()))

                    # Record sell but keep position OPEN for lifecycle tracking
                    result = self.lifecycle_tracker.record_sell_event(
                        position_id=lifecycle_position['id'],
                        exit_timestamp=exit_timestamp,
                        sell_sol_received=sol_amount,
                        sell_event_id=None,
                    )
                    logger.info(
                        f"💰 Sell recorded: {token_symbol} @ {result.get('wallet_roi_percent', 0):+.1f}% | "
                        f"Tracking token lifecycle continues..."
                    )
            except Exception as e:
                logger.debug(f"Lifecycle record error: {e}")

        # Send personalized alert to each subscriber
        for sub in subscribers:
            user_id = sub['user_id']
            win_rate = sub.get('win_rate', 0)
            nickname = sub.get('nickname', '')

            # Always show FULL wallet address in watchlist DM alerts
            wallet_display = f"`{wallet_addr}`"

            # Build alert message with full wallet
            if position:
                message = f"""📤 **WATCHLIST SELL**

👛 Wallet: {wallet_display}
💰 Sold **${token_symbol}**

📊 **Trade Result:**
├ Entry: {entry_sol:.2f} SOL
├ Exit: {sol_amount:.2f} SOL
├ {pnl_emoji} P/L: {pnl_str}
└ Hold Time: {hold_time}

📈 **Wallet Stats:**
└ Win Rate: {win_rate*100:.0f}%

🔗 [DexScreener](https://dexscreener.com/solana/{token_address}) | [Wallet](https://solscan.io/account/{wallet_addr})"""
            else:
                message = f"""📤 **WATCHLIST SELL**

👛 Wallet: {wallet_display}
💰 Sold **{sol_amount:.2f} SOL** of **${token_symbol}**

📊 **Trade Result:**
└ P/L: Entry not tracked (bought before monitoring)

📈 **Wallet Stats:**
└ Win Rate: {win_rate*100:.0f}%

🔗 [DexScreener](https://dexscreener.com/solana/{token_address}) | [Wallet](https://solscan.io/account/{wallet_addr})"""

            if nickname:
                message = message.replace("WATCHLIST SELL", f"WATCHLIST SELL ({nickname})")

            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                logger.info(f"✅ Watchlist sell alert sent to user {user_id} for ${token_symbol}")

            except Exception as e:
                logger.warning(f"Failed to send watchlist sell alert to {user_id}: {e}")

    async def _record_lifecycle_sell(self, wallet_addr: str, parsed: Dict):
        """
        Record sell event but KEEP position open for lifecycle tracking.

        Position tracking continues until 48h to capture full token lifecycle.
        Outcome is based on TOKEN performance, not wallet's exit timing.

        This teaches ML: "What happens to tokens after elite wallets buy?"
        """
        if not self.lifecycle_tracker:
            return

        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']

        try:
            # Find matching open position (FIFO)
            lifecycle_position = self.lifecycle_tracker.get_oldest_open_position(
                wallet_address=wallet_addr,
                token_address=token_address,
            )

            if not lifecycle_position:
                logger.debug(f"No open position found for {wallet_addr[:8]}... sell")
                return

            exit_timestamp = parsed.get('timestamp', int(datetime.now().timestamp()))
            token_symbol = lifecycle_position.get('token_symbol', '???')

            # Record sell but keep position OPEN
            result = self.lifecycle_tracker.record_sell_event(
                position_id=lifecycle_position['id'],
                exit_timestamp=exit_timestamp,
                sell_sol_received=sol_amount,
                sell_event_id=None,
            )

            logger.info(
                f"💰 Sell recorded: {token_symbol} @ {result.get('wallet_roi_percent', 0):+.1f}% | "
                f"Position continues tracking token lifecycle..."
            )

        except Exception as e:
            logger.debug(f"Error recording lifecycle sell: {e}")

    def _parse_swap(self, tx: Dict, wallet_addr: str) -> Optional[Dict]:
        """Parse a swap transaction."""
        try:
            token_transfers = tx.get('tokenTransfers', [])
            native_transfers = tx.get('nativeTransfers', [])

            if not token_transfers:
                return None

            # Find the main token (not SOL/stables)
            main_transfer = None
            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                if mint not in self.skip_tokens:
                    main_transfer = transfer
                    break

            if not main_transfer:
                return None

            # Calculate SOL amount
            sol_amount = 0
            for nt in native_transfers:
                amount = abs(nt.get('amount', 0)) / 1e9
                if nt.get('fromUserAccount') == wallet_addr:
                    sol_amount += amount  # SOL out = buying
                elif nt.get('toUserAccount') == wallet_addr:
                    sol_amount -= amount  # SOL in = selling

            # Determine buy or sell
            is_buy = main_transfer.get('toUserAccount') == wallet_addr
            tx_type = 'buy' if is_buy else 'sell'

            return {
                'signature': tx.get('signature'),
                'type': tx_type,
                'token_address': main_transfer.get('mint'),
                'sol_amount': abs(sol_amount),
                'timestamp': tx.get('timestamp', 0),
            }

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    async def _get_token_info(self, token_address: str) -> Dict:
        """Get token info with extended metrics from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            pair = data[0]

                            # Extract price changes
                            price_change = pair.get('priceChange', {})
                            volume = pair.get('volume', {})
                            txns = pair.get('txns', {})

                            # Calculate token age from pairCreatedAt
                            pair_created_at = pair.get('pairCreatedAt', 0)
                            token_age_hours = 0
                            if pair_created_at:
                                age_seconds = datetime.now().timestamp() * 1000 - pair_created_at
                                token_age_hours = max(0, age_seconds / (1000 * 3600))

                            # Get holder count from info if available
                            info = pair.get('info', {})
                            holders = info.get('holders', 0)

                            # Build chart preview URL
                            pair_address = pair.get('pairAddress', '')
                            chart_url = f"https://dexscreener.com/solana/{pair_address}" if pair_address else ''

                            # Calculate buys/sells in 5m, 1h, 24h
                            txns_m5 = txns.get('m5', {})
                            txns_h1 = txns.get('h1', {})
                            txns_h24 = txns.get('h24', {})

                            return {
                                'address': token_address,
                                'pair_address': pair_address,
                                'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                                'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                                'image_url': info.get('imageUrl', ''),
                                # Token metrics
                                'market_cap': float(pair.get('marketCap', 0) or 0),
                                'fdv': float(pair.get('fdv', 0) or 0),
                                'liquidity': float(pair.get('liquidity', {}).get('usd', 0) or 0),
                                # Volume at multiple timeframes
                                'volume_5m': float(volume.get('m5', 0) or 0),
                                'volume_1h': float(volume.get('h1', 0) or 0),
                                'volume_24h': float(volume.get('h24', 0) or 0),
                                # Price changes
                                'price_change_5m': float(price_change.get('m5', 0) or 0),
                                'price_change_1h': float(price_change.get('h1', 0) or 0),
                                'price_change_24h': float(price_change.get('h24', 0) or 0),
                                # Transaction counts
                                'buys_5m': int(txns_m5.get('buys', 0) or 0),
                                'sells_5m': int(txns_m5.get('sells', 0) or 0),
                                'buys_1h': int(txns_h1.get('buys', 0) or 0),
                                'sells_1h': int(txns_h1.get('sells', 0) or 0),
                                'buys_24h': int(txns_h24.get('buys', 0) or 0),
                                'sells_24h': int(txns_h24.get('sells', 0) or 0),
                                # Extended info
                                'holders': int(holders) if holders else 0,
                                'token_age_hours': token_age_hours,
                                'chart_url': chart_url,
                            }
        except Exception as e:
            logger.debug(f"Token info error: {e}")

        return {
            'address': token_address,
            'pair_address': '',
            'name': 'Unknown',
            'symbol': '???',
            'image_url': '',
            'market_cap': 0,
            'fdv': 0,
            'liquidity': 0,
            'volume_5m': 0,
            'volume_1h': 0,
            'volume_24h': 0,
            'price_change_5m': 0,
            'price_change_1h': 0,
            'price_change_24h': 0,
            'buys_5m': 0,
            'sells_5m': 0,
            'buys_1h': 0,
            'sells_1h': 0,
            'buys_24h': 0,
            'sells_24h': 0,
            'holders': 0,
            'token_age_hours': 0,
            'chart_url': '',
        }

    async def _get_recent_trades(self, wallet_addr: str) -> List[Dict]:
        """Get recent trades with REAL PnL calculation using rotated API keys."""
        api_key = await self.rotator.get_key()
        url = f"{self.base_url}/addresses/{wallet_addr}/transactions?api-key={api_key}&limit=50"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status != 200:
                        logger.debug(f"Failed to get trades: {response.status}")
                        return []
                    txs = await response.json()
        except Exception as e:
            logger.debug(f"Error fetching trades: {e}")
            return []

        # Track token positions: token -> {sol_spent, sol_earned, last_tx_time}
        token_positions = {}

        for tx in txs:
            parsed = self._parse_swap(tx, wallet_addr)
            if not parsed:
                continue

            token = parsed['token_address']
            sol_amount = parsed['sol_amount']
            tx_type = parsed['type']
            tx_time = parsed['timestamp']

            # Filter: Only count buys >= 1.5 SOL for analysis
            if tx_type == 'buy' and sol_amount < MIN_BUY_AMOUNT_SOL:
                continue  # Skip small buys from analysis

            if token not in token_positions:
                token_positions[token] = {
                    'sol_spent': 0,
                    'sol_earned': 0,
                    'last_tx_time': tx_time,
                    'last_tx_type': tx_type,
                }

            if tx_type == 'buy':
                token_positions[token]['sol_spent'] += sol_amount
            else:  # sell
                token_positions[token]['sol_earned'] += sol_amount

            # Update last tx time if more recent
            if tx_time > token_positions[token]['last_tx_time']:
                token_positions[token]['last_tx_time'] = tx_time
                token_positions[token]['last_tx_type'] = tx_type

        # Build trades list with real PnL
        trades = []
        for token, pos in token_positions.items():
            sol_spent = pos['sol_spent']
            sol_earned = pos['sol_earned']

            # Calculate PnL only for closed positions (both buy and sell)
            if sol_spent > 0 and sol_earned > 0:
                pnl = ((sol_earned - sol_spent) / sol_spent) * 100
            elif sol_spent > 0:
                pnl = 0  # Open position (no sells yet)
            else:
                continue  # Skip if no buys

            # Get token symbol
            token_info = await self._get_token_info(token)

            # Calculate time ago
            tx_time = pos['last_tx_time']
            now = datetime.now().timestamp()
            diff = now - tx_time

            if diff < 3600:
                time_ago = f"{int(diff / 60)}m ago"
            elif diff < 86400:
                time_ago = f"{int(diff / 3600)}h ago"
            elif diff < 604800:
                time_ago = f"{int(diff / 86400)}d ago"
            else:
                time_ago = f"{int(diff / 604800)}w ago"

            trades.append({
                'token_symbol': token_info.get('symbol', '???'),
                'pnl_percent': pnl,
                'time_ago': time_ago,
                'last_tx_time': tx_time,
            })

        # Sort by most recent and return top 5
        trades.sort(key=lambda x: x['last_tx_time'], reverse=True)
        return trades[:5]

    async def _check_last_5_trades_quality(self, wallet_addr: str) -> Dict:
        """
        Check if wallet's last 5 closed trades meet quality threshold.
        Returns dict with: passed, win_rate, closed_count, wins

        Filters out wallets on losing streaks.
        Requires >= 60% win rate on last 5 closed trades.
        """
        logger.info(f"🔍 Checking trade quality for {wallet_addr[:12]}...")

        # Get recent trades (already calculates PnL)
        trades = await self._get_recent_trades(wallet_addr)

        if not trades:
            logger.warning(f"❌ REJECTED {wallet_addr[:12]}: No trade history found")
            return {'passed': False, 'win_rate': 0, 'closed_count': 0, 'wins': 0}

        # Filter to only closed positions (pnl_percent != 0)
        closed_trades = [t for t in trades if t['pnl_percent'] != 0]

        logger.info(f"   Found {len(trades)} recent trades, {len(closed_trades)} closed positions")
        for t in closed_trades[:5]:
            emoji = "✅" if t['pnl_percent'] > 0 else "❌"
            logger.info(f"   {emoji} {t['token_symbol']}: {t['pnl_percent']:+.1f}%")

        if len(closed_trades) < 3:
            # Not enough closed trades - allow but log
            logger.info(f"✅ PASSED {wallet_addr[:12]}: Only {len(closed_trades)} closed trades (need 3+ to filter)")
            return {'passed': True, 'win_rate': 0, 'closed_count': len(closed_trades), 'wins': 0}

        # Count wins (positive PnL)
        wins = sum(1 for t in closed_trades if t['pnl_percent'] > 0)
        win_rate = wins / len(closed_trades)

        # Check against minimum threshold
        passed = win_rate >= MIN_LAST_5_WIN_RATE

        if passed:
            logger.info(f"✅ PASSED {wallet_addr[:12]}: {wins}/{len(closed_trades)} wins ({win_rate*100:.0f}% >= {MIN_LAST_5_WIN_RATE*100:.0f}%)")
        else:
            logger.warning(f"❌ REJECTED {wallet_addr[:12]}: {wins}/{len(closed_trades)} wins ({win_rate*100:.0f}% < {MIN_LAST_5_WIN_RATE*100:.0f}%)")

        return {
            'passed': passed,
            'win_rate': win_rate,
            'closed_count': len(closed_trades),
            'wins': wins
        }

    def stop(self):
        """Stop monitoring."""
        self.running = False
        logger.info("Real-time bot stopped")


async def main():
    """Run the real-time bot."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    bot = RealTimeBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
