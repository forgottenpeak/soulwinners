"""
Real-Time Monitoring Bot
- Monitors BUY transactions for qualified wallets (public channel)
- Monitors BUY transactions for user watchlist wallets (personal DM alerts)
- ONLY alerts on transactions < 5 minutes old
- ONLY alerts if buy amount >= threshold (1 SOL qualified, 1.5 SOL watchlist)
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Set, Optional
import aiohttp
from telegram import Bot
from telegram.constants import ParseMode

from config.settings import (
    HELIUS_API_KEY,
    HELIUS_PREMIUM_KEY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    DATABASE_PATH,
)
from database import get_connection
from bot.alert_formatter import AlertFormatter
from collectors.helius import helius_premium_rotator  # Use PREMIUM key for real-time
from bot.utils import truncate_wallet

logger = logging.getLogger(__name__)

# Configuration
MIN_BUY_AMOUNT_SOL = 1.0       # Minimum 1 SOL for qualified wallet alerts
MIN_WATCHLIST_BUY_SOL = 1.5    # Minimum 1.5 SOL for watchlist alerts
MAX_TX_AGE_MINUTES = 5         # Only alert on transactions < 5 minutes old
POLL_INTERVAL = 30             # Seconds between polling cycles
MIN_LAST_5_WIN_RATE = 0.60     # 60% minimum win rate on last 5 closed trades

# Admin user ID - sees full addresses
ADMIN_USER_ID = 1153491543

# Alert cache for /add command lookup
# Stores message_id -> full wallet address
ALERT_WALLET_CACHE: Dict[int, str] = {}
ALERT_CACHE_MAX_SIZE = 500  # Keep last 500 alerts


def cache_alert_wallet(message_id: int, wallet_address: str):
    """Store mapping of message_id to full wallet address for /add command."""
    global ALERT_WALLET_CACHE

    ALERT_WALLET_CACHE[message_id] = wallet_address

    # Clean up old entries if cache too large
    if len(ALERT_WALLET_CACHE) > ALERT_CACHE_MAX_SIZE:
        # Remove oldest entries (first 100)
        keys_to_remove = list(ALERT_WALLET_CACHE.keys())[:100]
        for key in keys_to_remove:
            del ALERT_WALLET_CACHE[key]

    logger.debug(f"Cached alert {message_id} -> {wallet_address[:12]}...")


def get_wallet_from_alert_cache(message_id: int) -> Optional[str]:
    """Look up full wallet address from alert cache by message_id."""
    return ALERT_WALLET_CACHE.get(message_id)


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


class RealTimeBot:
    """
    Real-time monitoring bot.
    - Polls Helius for new transactions
    - Only alerts on BUY transactions
    - Filters by transaction age and amount
    """

    def __init__(self):
        self.rotator = helius_premium_rotator  # Use PREMIUM key for real-time monitoring
        self.base_url = f"https://api.helius.xyz/v0"
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_CHANNEL_ID

        self.formatter = AlertFormatter()
        self.smart_money = SmartMoneyTracker()
        self.watchlist = WatchlistTracker()
        self.watchlist_positions = WatchlistPositionTracker()  # Track positions for sell P/L
        self.price_service = PriceService()

        self.qualified_wallets: Dict[str, Dict] = {}
        self.watchlist_wallets: Set[str] = set()  # NEW: Watchlist wallet addresses
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

        logger.info(f"Loaded {len(self.qualified_wallets)} qualified wallets")
        logger.info(f"Loaded {len(self.watchlist_wallets)} watchlist wallets")
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

        logger.info(f"Starting real-time monitor")
        logger.info(f"  Qualified wallets: {count}")
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
                     f"👁️ Watchlist wallets: {watchlist_count}\n\n"
                     f"Monitoring buys ≥{MIN_BUY_AMOUNT_SOL} SOL (qualified)\n"
                     f"Monitoring buys ≥{MIN_WATCHLIST_BUY_SOL} SOL (watchlist)",
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

    async def _poll_cycle(self):
        """One polling cycle - check qualified + watchlist wallets."""
        total_qualified = len(self.qualified_wallets)
        total_watchlist = len(self.watchlist_wallets)

        logger.info(f"📡 Poll cycle starting ({total_qualified} qualified + {total_watchlist} watchlist)...")

        checked = 0

        # Check qualified wallets (public channel alerts)
        for wallet_addr, wallet_data in self.qualified_wallets.items():
            try:
                await self._check_wallet(wallet_addr, wallet_data, is_watchlist=False)
                checked += 1
                await asyncio.sleep(1.5)  # Rate limit between wallets
            except Exception as e:
                logger.warning(f"Error checking qualified {wallet_addr[:15]}...: {e}")

        # Check watchlist wallets (personal DM alerts)
        for wallet_addr in self.watchlist_wallets:
            # Skip if already checked as qualified wallet
            if wallet_addr in self.qualified_wallets:
                continue

            try:
                await self._check_wallet(wallet_addr, None, is_watchlist=True)
                checked += 1
                await asyncio.sleep(1.5)  # Rate limit between wallets
            except Exception as e:
                logger.warning(f"Error checking watchlist {wallet_addr[:15]}...: {e}")

        logger.info(f"📡 Poll cycle complete ({checked} wallets checked)")

    async def _check_wallet(self, wallet_addr: str, wallet_data: Optional[Dict],
                            is_watchlist: bool = False):
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

            await self._process_transaction(tx, wallet_addr, wallet_data, is_watchlist)

    async def _process_transaction(self, tx: Dict, wallet_addr: str,
                                    wallet_data: Optional[Dict], is_watchlist: bool = False):
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

        # 4. Handle QUALIFIED wallets - buys only
        if tx_type != 'buy':
            return  # Skip sells for qualified wallets

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

    async def _send_qualified_alert(self, wallet_addr: str, wallet_data: Dict, parsed: Dict):
        """Send alert to public channel for qualified wallet buys."""
        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']
        tx_timestamp = parsed['timestamp']

        # Record for smart money tracking
        self.smart_money.record_buy(token_address, wallet_addr)

        # Get token info from DexScreener
        token_info = await self._get_token_info(token_address)

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

        message = self.formatter.format_buy_alert(
            wallet=wallet_data,
            token=token_info,
            trade=trade_data,
            smart_money=smart_money,
            recent_trades=recent_trades,
            sol_price=sol_price
        )

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
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    sent_message = await self.bot.send_message(
                        chat_id=self.channel_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                sent_message = await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )

            # Cache message_id -> wallet for /add command lookup
            if sent_message:
                cache_alert_wallet(sent_message.message_id, wallet_addr)

            logger.info(f"✅ QUALIFIED ALERT: {wallet_data.get('tier')} bought {token_info.get('symbol')} for {sol_amount:.2f} SOL")

        except Exception as e:
            logger.error(f"❌ FAILED to send qualified alert: {e}")

    async def _send_watchlist_buy_alert(self, wallet_addr: str, parsed: Dict):
        """Send personal DM buy alerts to users who have this wallet in their watchlist."""
        token_address = parsed['token_address']
        sol_amount = parsed['sol_amount']

        # Get all users subscribed to this wallet
        subscribers = self.watchlist.get_wallet_subscribers(wallet_addr)

        if not subscribers:
            return

        # Get token info
        token_info = await self._get_token_info(token_address)
        token_symbol = token_info.get('symbol', '???')

        logger.info(f"🔔 WATCHLIST BUY: {wallet_addr[:12]}... bought {sol_amount:.2f} SOL of ${token_symbol}")

        # Send personalized alert to each subscriber
        for sub in subscribers:
            user_id = sub['user_id']
            win_rate = sub.get('win_rate', 0)
            added_date = sub.get('added_date', '')
            nickname = sub.get('nickname', '')

            # Calculate days since added
            days_ago = "Unknown"
            if added_date:
                try:
                    added_dt = datetime.fromisoformat(added_date.replace('Z', '+00:00'))
                    days = (datetime.now() - added_dt).days
                    days_ago = f"{days} day{'s' if days != 1 else ''} ago"
                except:
                    days_ago = added_date[:10]

            # Format wallet based on user privilege
            is_admin = (user_id == ADMIN_USER_ID)
            if is_admin:
                wallet_display = f"`{wallet_addr}`"
            else:
                wallet_display = truncate_wallet(wallet_addr)

            # Build alert message
            message = f"""🔔 **WATCHLIST BUY**

💰 {wallet_display} bought **{sol_amount:.2f} SOL** of **${token_symbol}**

📊 **Wallet Stats:**
├ Win Rate: {win_rate*100:.0f}%
└ Added: {days_ago}

🪙 **Token:** ${token_symbol}
├ Market Cap: ${token_info.get('market_cap', 0):,.0f}
└ Liquidity: ${token_info.get('liquidity', 0):,.0f}

[DexScreener](https://dexscreener.com/solana/{token_address})"""

            if nickname:
                message = message.replace("WATCHLIST BUY", f"WATCHLIST BUY ({nickname})")

            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
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

        # Send personalized alert to each subscriber
        for sub in subscribers:
            user_id = sub['user_id']
            win_rate = sub.get('win_rate', 0)
            nickname = sub.get('nickname', '')

            # Format wallet based on user privilege
            is_admin = (user_id == ADMIN_USER_ID)
            if is_admin:
                wallet_display = f"`{wallet_addr}`"
            else:
                wallet_display = truncate_wallet(wallet_addr)

            # Build alert message
            if position:
                message = f"""📤 **WATCHLIST SELL**

💰 {wallet_display} sold **${token_symbol}**

📊 **Trade Result:**
├ Entry: {entry_sol:.2f} SOL
├ Exit: {sol_amount:.2f} SOL
├ {pnl_emoji} P/L: {pnl_str}
└ Hold Time: {hold_time}

📈 **Wallet Stats:**
└ Win Rate: {win_rate*100:.0f}%

[DexScreener](https://dexscreener.com/solana/{token_address})"""
            else:
                message = f"""📤 **WATCHLIST SELL**

💰 {wallet_display} sold **{sol_amount:.2f} SOL** of **${token_symbol}**

📊 **Trade Result:**
└ P/L: Entry not tracked (bought before monitoring)

📈 **Wallet Stats:**
└ Win Rate: {win_rate*100:.0f}%

[DexScreener](https://dexscreener.com/solana/{token_address})"""

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
        """Get token info with metrics from DexScreener."""
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

                            return {
                                'address': token_address,
                                'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                                'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                                'image_url': pair.get('info', {}).get('imageUrl', ''),
                                # Token metrics
                                'market_cap': float(pair.get('marketCap', 0) or 0),
                                'liquidity': float(pair.get('liquidity', {}).get('usd', 0) or 0),
                                'volume_1h': float(pair.get('volume', {}).get('h1', 0) or 0),
                                'volume_24h': float(pair.get('volume', {}).get('h24', 0) or 0),
                                'price_change_1h': float(price_change.get('h1', 0) or 0),
                                'price_change_24h': float(price_change.get('h24', 0) or 0),
                            }
        except Exception as e:
            logger.debug(f"Token info error: {e}")

        return {
            'address': token_address,
            'name': 'Unknown',
            'symbol': '???',
            'image_url': '',
            'market_cap': 0,
            'liquidity': 0,
            'volume_1h': 0,
            'volume_24h': 0,
            'price_change_1h': 0,
            'price_change_24h': 0,
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
