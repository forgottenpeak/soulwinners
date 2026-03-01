"""
Telegram Bot Commands - Private DM Only
Only responds to authorized admin user
With interactive settings, cron control, and logging
"""
import asyncio
import logging
import subprocess
import os
from io import BytesIO
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
import aiohttp

from config.settings import TELEGRAM_BOT_TOKEN
from database import get_connection
from collectors.helius import helius_rotator
from bot.utils import (
    extract_wallet_from_text,
    extract_wallet_from_bot_alert,
    truncate_wallet,
    format_wallet_for_user,
    format_stats,
    parse_remove_index,
    is_valid_solana_address,
)
from bot.realtime_bot import get_wallet_from_alert_cache

logger = logging.getLogger(__name__)

# Admin user ID - ONLY this user can use commands
ADMIN_USER_ID = None  # Will be set on first /start

# Premium user IDs (can use watchlist features with truncated addresses)
PREMIUM_USER_IDS = set()  # Load from database or config


class CommandBot:
    """Telegram bot with private commands for admin only."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.admin_id = ADMIN_USER_ID
        self.application = None
        self.helius_url = f"https://api.helius.xyz/v0"
        self.rotator = helius_rotator  # Use API key rotation
        self._balance_cache: Dict[str, Tuple[float, datetime]] = {}  # wallet -> (balance, timestamp)

    async def start(self):
        """Start the command bot."""
        self.application = Application.builder().token(self.token).build()

        # Register commands
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("pool", self.cmd_pool))
        self.application.add_handler(CommandHandler("wallets", self.cmd_wallets))
        self.application.add_handler(CommandHandler("leaderboard", self.cmd_leaderboard))
        self.application.add_handler(CommandHandler("stats", self.cmd_stats))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        self.application.add_handler(CommandHandler("register", self.cmd_register))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("cron", self.cmd_cron))
        self.application.add_handler(CommandHandler("logs", self.cmd_logs))
        self.application.add_handler(CommandHandler("restart", self.cmd_restart))
        self.application.add_handler(CommandHandler("trader", self.cmd_trader))
        self.application.add_handler(CommandHandler("insiders", self.cmd_insiders))
        self.application.add_handler(CommandHandler("clusters", self.cmd_clusters))
        self.application.add_handler(CommandHandler("early_birds", self.cmd_early_birds))

        # Watchlist commands
        self.application.add_handler(CommandHandler("add", self.cmd_add_wallet))
        self.application.add_handler(CommandHandler("watchlist", self.cmd_watchlist))
        self.application.add_handler(CommandHandler("remove_wallet", self.cmd_remove_wallet))
        self.application.add_handler(CommandHandler("remove", self.cmd_remove_wallet))  # Alias
        self.application.add_handler(CommandHandler("removewallet", self.cmd_remove_wallet))  # No underscore alias
        self.application.add_handler(CommandHandler("label", self.cmd_label))
        self.application.add_handler(CommandHandler("summary", self.cmd_summary))
        self.application.add_handler(CommandHandler("premium", self.cmd_premium))
        self.application.add_handler(CommandHandler("buttons", self.cmd_buttons))
        self.application.add_handler(CommandHandler("export", self.cmd_export))

        # Register callback handler for inline buttons
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

        # Initialize watchlist table
        self._init_watchlist_table()

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        # Set bot menu commands
        await self._set_bot_commands()

        logger.info("Command bot started")

    async def stop(self):
        """Stop the bot."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

    async def _set_bot_commands(self):
        """Set bot menu commands visible in Telegram."""
        from telegram import BotCommand

        commands = [
            # Main commands
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show all commands"),
            BotCommand("buttons", "Quick action buttons"),

            # Watchlist
            BotCommand("add", "Add wallet to watchlist"),
            BotCommand("watchlist", "View your watchlist"),
            BotCommand("remove", "Remove wallet from watchlist"),
            BotCommand("label", "Nickname a wallet"),
            BotCommand("summary", "Daily P&L summary"),
            BotCommand("export", "Export watchlist to CSV"),

            # Analysis
            BotCommand("pool", "View wallet leaderboard"),
            BotCommand("leaderboard", "Top performers by ROI"),
            BotCommand("stats", "Pool statistics"),
            BotCommand("insiders", "Insider pool stats"),
            BotCommand("clusters", "Wallet clusters"),

            # Premium
            BotCommand("premium", "Premium features info"),
            BotCommand("settings", "Bot settings"),
        ]

        try:
            await self.application.bot.set_my_commands(commands)
            logger.info(f"Set {len(commands)} bot menu commands")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")

    def _is_admin(self, user_id: int) -> bool:
        """Check if user is admin."""
        logger.debug(f"Admin check: user={user_id}, admin_id={self.admin_id}")
        if self.admin_id is None:
            logger.warning(f"Admin ID not set, rejecting user {user_id}")
            return False
        result = user_id == self.admin_id
        if not result:
            logger.warning(f"User {user_id} != admin {self.admin_id}")
        return result

    def _is_private(self, update: Update) -> bool:
        """Check if message is in private chat."""
        return update.effective_chat.type == "private"

    def _is_premium(self, user_id: int) -> bool:
        """Check if user is premium (or admin)."""
        if self._is_admin(user_id):
            return True
        return user_id in PREMIUM_USER_IDS

    def _init_watchlist_table(self):
        """Initialize user_watchlists table in database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_watchlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    wallet_address TEXT NOT NULL,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    win_rate REAL DEFAULT 0,
                    roi REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    UNIQUE(user_id, wallet_address)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_watchlist_user
                ON user_watchlists(user_id)
            """)
            conn.commit()
            conn.close()
            logger.info("Watchlist table initialized")
        except Exception as e:
            logger.error(f"Failed to init watchlist table: {e}")

    # =========================================================================
    # COMMANDS
    # =========================================================================

    async def cmd_register(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Register as admin (first user only)."""
        if not self._is_private(update):
            return

        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"

        if self.admin_id is None:
            self.admin_id = user_id
            # Save to file for persistence
            with open("data/admin_id.txt", "w") as f:
                f.write(str(user_id))

            await update.message.reply_text(
                f"✅ **Registered as Admin**\n\n"
                f"User: @{username}\n"
                f"ID: `{user_id}`\n\n"
                f"You now have access to all commands.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Admin registered: {username} ({user_id})")
        elif self.admin_id == user_id:
            await update.message.reply_text("You're already registered as admin.")
        else:
            await update.message.reply_text("Admin already registered.")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome message."""
        logger.info(f"Start command received from {update.effective_user.id} in {update.effective_chat.type}")
        if not self._is_private(update):
            logger.warning("Start command rejected: not private chat")
            return

        # Load admin ID from file if exists
        try:
            with open("data/admin_id.txt", "r") as f:
                self.admin_id = int(f.read().strip())
        except:
            pass

        user_id = update.effective_user.id

        if not self._is_admin(user_id):
            await update.message.reply_text(
                "🔒 **SoulWinners Admin Bot**\n\n"
                "This bot is for authorized admins only.\n\n"
                "If you're the owner, use /register to claim admin access.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        message = """
🚀 **SoulWinners Admin Panel**

Welcome! You have full access to wallet tracking commands.

**Commands:**
/pool - View all qualified wallets ranked by performance
/wallets - Full wallet addresses with stats
/leaderboard - Top performers with detailed metrics
/stats - Pool statistics and tier breakdown
/help - Command guide

**Status:** 🟢 Online
**Wallets Monitored:** Checking...
"""
        # Get wallet count
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
        count = cursor.fetchone()[0]
        conn.close()

        message = message.replace("Checking...", str(count))

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_pool(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all qualified wallets ranked by Buy Efficiency Score (BES)."""
        logger.info(f"Pool command received from {update.effective_user.id} in {update.effective_chat.type}")
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            logger.warning(f"Pool command rejected: private={self._is_private(update)}, admin={self._is_admin(update.effective_user.id)}")
            return

        await update.message.reply_text("📊 Loading wallet data with live balances...")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wallet_address, cluster_name, roi_pct, win_rate,
                   current_balance_sol, priority_score, tier, total_trades,
                   roi_per_trade, trade_frequency
            FROM qualified_wallets
        """)
        wallets = cursor.fetchall()
        conn.close()

        if not wallets:
            await update.message.reply_text("No qualified wallets in pool.")
            return

        # Calculate BES and fetch live data for each wallet
        wallet_data = []
        for w in wallets:
            (addr, strategy, roi, win_rate, db_balance, score, tier,
             total_trades, roi_per_trade, trade_freq) = w

            # Get live balance
            live_balance = await self._get_live_balance(addr)
            if live_balance is None:
                live_balance = db_balance or 0

            # Get last buy info
            last_buy = await self._get_last_buy_info(addr)

            # Calculate BES: (Avg ROI per Trade × Win Rate × Trade Frequency) / Avg Buy Size
            # Estimate avg buy size from balance and trades
            avg_buy_size = max(0.1, (live_balance or 1) / max(1, total_trades or 1))
            bes = 0
            if avg_buy_size > 0 and roi_per_trade and win_rate and trade_freq:
                bes = (abs(roi_per_trade) * win_rate * trade_freq) / avg_buy_size

            wallet_data.append({
                'addr': addr,
                'strategy': strategy or 'Unknown',
                'roi': roi or 0,
                'win_rate': win_rate or 0,
                'balance': live_balance,
                'tier': tier or 'Unknown',
                'trades': total_trades or 0,
                'roi_per_trade': roi_per_trade or 0,
                'avg_buy': avg_buy_size,
                'bes': bes,
                'last_buy': last_buy,
            })

        # Sort by BES descending
        wallet_data.sort(key=lambda x: x['bes'], reverse=True)

        # Build message
        tier_emoji = {'Elite': '🔥', 'High-Quality': '🟢', 'Mid-Tier': '🟡', 'Watchlist': '⚪'}
        medals = ['🥇', '🥈', '🥉']

        message = f"📊 **ELITE WALLET LEADERBOARD ({len(wallet_data)})**\n"
        message += "Ranked by Buy Efficiency Score\n\n"

        for i, w in enumerate(wallet_data):
            medal = medals[i] if i < 3 else f"#{i+1}"

            message += f"{medal} | BES: **{w['bes']:,.0f}** | {w['strategy']}\n"
            message += f"├─ ROI/Trade: {w['roi_per_trade']:,.0f}% | Win: {w['win_rate']*100:.0f}%\n"
            message += f"├─ Avg Buy: {w['avg_buy']:.1f} SOL | Trades: {w['trades']}\n"
            message += f"├─ Balance: **{w['balance']:.2f} SOL** (LIVE)\n"

            if w['last_buy']:
                message += f"├─ Last Buy: {w['last_buy']['time_ago']} | ${w['last_buy']['token']} {w['last_buy']['pnl']}\n"
            else:
                message += f"├─ Last Buy: No recent buys\n"

            # Full wallet address (no truncation for DM commands)
            message += f"└─ `{w['addr']}`\n\n"

        message += "💡 _BES = (Avg ROI × Win Rate × Frequency) / Avg Buy Size_\n"
        message += "_Higher = Better capital efficiency_"

        # Split if too long
        if len(message) > 4000:
            parts = []
            current = ""
            for line in message.split('\n'):
                if len(current) + len(line) + 1 > 4000:
                    parts.append(current)
                    current = line
                else:
                    current += '\n' + line if current else line
            if current:
                parts.append(current)

            for part in parts:
                await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_wallets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List wallets with FULL addresses and stats."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Wallets command received from user {update.effective_user.id}")
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wallet_address, cluster_name, roi_pct, win_rate,
                       current_balance_sol, tier
                FROM qualified_wallets
                ORDER BY priority_score DESC
            """)
            wallets = cursor.fetchall()
            conn.close()

            if not wallets:
                await update.message.reply_text("No qualified wallets.")
                return

            message = f"👛 **WALLET ADDRESSES ({len(wallets)})**\n\n"

            for i, w in enumerate(wallets, 1):
                addr, strategy, roi, win_rate, balance, tier = w

                message += f"**#{i} - {strategy}**\n"
                message += f"`{addr}`\n"
                message += f"ROI: {roi:,.0f}% | Win: {win_rate*100:.0f}% | {balance:.2f} SOL\n"
                message += f"[Solscan](https://solscan.io/account/{addr}) | "
                message += f"[Birdeye](https://birdeye.so/profile/{addr}?chain=solana)\n\n"

            # Split if too long
            if len(message) > 4000:
                parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
                for part in parts:
                    await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            logger.info("Wallets command completed successfully")
        except Exception as e:
            logger.error(f"Wallets command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Top performers with detailed metrics."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Leaderboard command received from user {update.effective_user.id}")
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wallet_address, cluster_name, roi_pct, win_rate,
                       current_balance_sol, x10_ratio, x20_ratio, x50_ratio,
                       total_trades, tier, priority_score
                FROM qualified_wallets
                ORDER BY roi_pct DESC
                LIMIT 10
            """)
            wallets = cursor.fetchall()
            conn.close()

            if not wallets:
                await update.message.reply_text("No qualified wallets.")
                return

            message = "🏆 **TOP PERFORMERS LEADERBOARD**\n\n"

            for i, w in enumerate(wallets, 1):
                (addr, strategy, roi, win_rate, balance,
                 x10, x20, x50, trades, tier, score) = w

                message += f"**#{i} {tier}** - {strategy}\n"
                message += f"├ ROI: **{roi:,.0f}%**\n"
                message += f"├ Win Rate: {win_rate*100:.0f}%\n"
                message += f"├ Balance: {balance:.2f} SOL\n"
                message += f"├ 10x Rate: {(x10 or 0)*100:.0f}%\n"
                message += f"├ Trades: {trades or 0}\n"
                message += f"├ Score: {score:.4f}\n"
                message += f"└ `{addr}`\n\n"

            # Split if too long
            if len(message) > 4000:
                parts = []
                current = ""
                for line in message.split('\n'):
                    if len(current) + len(line) + 1 > 4000:
                        parts.append(current)
                        current = line
                    else:
                        current += '\n' + line if current else line
                if current:
                    parts.append(current)
                for part in parts:
                    await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            logger.info("Leaderboard command completed successfully")
        except Exception as e:
            logger.error(f"Leaderboard command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    # =========================================================================
    # WATCHLIST COMMANDS
    # =========================================================================

    async def cmd_add_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Add wallet from forwarded buy alert.

        Usage: Forward a buy alert, then reply to it with /add
        """
        if not self._is_private(update):
            return

        user_id = update.effective_user.id

        # Check if user is admin or premium
        if not self._is_premium(user_id):
            await update.message.reply_text(
                "This feature is for premium users only.\n"
                "Contact admin for access."
            )
            return

        logger.info(f"Add wallet command from user {user_id}")

        # Check if this is a reply to another message
        reply_msg = update.message.reply_to_message
        if not reply_msg:
            await update.message.reply_text(
                "**How to add a wallet:**\n\n"
                "1. Forward a buy alert to this chat\n"
                "2. Reply to that message with /add\n\n"
                "The bot will extract the wallet address and add it to your watchlist.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Get text from replied message (could be forwarded)
        text = reply_msg.text or reply_msg.caption or ""

        if not text:
            await update.message.reply_text(
                "Could not read the message. Make sure the alert contains text."
            )
            return

        # Check if this is a reply to THIS BOT's own message
        bot_id = context.bot.id
        is_bot_message = reply_msg.from_user and reply_msg.from_user.id == bot_id

        wallet = None

        if is_bot_message:
            # FIRST: Try to look up full wallet from alert cache (most reliable)
            message_id = reply_msg.message_id
            wallet = get_wallet_from_alert_cache(message_id)

            if wallet:
                logger.info(f"Found wallet from cache: {wallet[:12]}...")
            else:
                # FALLBACK: Try to parse from bot's alert format
                wallet = extract_wallet_from_bot_alert(text)
                logger.info(f"Parsing bot's own alert, found: {wallet[:12] if wallet else 'None'}...")

                if not wallet:
                    # LAST RESORT: Generic extraction
                    wallet = extract_wallet_from_text(text)
                    logger.info(f"Fallback extraction: {wallet[:12] if wallet else 'None'}...")
        else:
            # External alert - use generic extraction
            wallet = extract_wallet_from_text(text)
            logger.info(f"Parsing external alert, found: {wallet[:12] if wallet else 'None'}...")

        if not wallet:
            await update.message.reply_text(
                "Could not find a valid Solana wallet address in that message.\n\n"
                "Make sure the alert contains a wallet address (not token address).\n"
                "Token addresses ending in 'pump' are filtered out."
            )
            return

        # Log what we found for debugging
        logger.info(f"Final extracted wallet: {wallet}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Ensure table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_watchlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    wallet_address TEXT NOT NULL,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    win_rate REAL DEFAULT 0,
                    roi REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    UNIQUE(user_id, wallet_address)
                )
            """)
            conn.commit()

            # Check if already in watchlist
            cursor.execute(
                "SELECT id FROM user_watchlists WHERE user_id = ? AND wallet_address = ?",
                (user_id, wallet)
            )
            existing = cursor.fetchone()

            if existing:
                conn.close()
                await update.message.reply_text(
                    f"This wallet is already in your watchlist.\n\n"
                    f"Wallet: {format_wallet_for_user(wallet, self._is_admin(user_id))}"
                )
                return

            # Analyze wallet
            await update.message.reply_text("Analyzing wallet...")

            stats = await self._analyze_wallet_stats(wallet)

            # Add to watchlist
            cursor.execute("""
                INSERT INTO user_watchlists (user_id, wallet_address, win_rate, roi, total_trades)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, wallet, stats['win_rate'], stats['roi'], stats['trades']))
            conn.commit()
            conn.close()

            logger.info(f"Successfully added wallet {wallet[:12]}... to watchlist for user {user_id}")

        except Exception as e:
            logger.error(f"Database error adding wallet: {e}")
            await update.message.reply_text(f"Database error: {e}")
            return

        # Format response based on user level
        wallet_display = format_wallet_for_user(wallet, self._is_admin(user_id))

        message = f"""**Added to Watchlist**

**Wallet:** {wallet_display}

**Stats:**
{format_stats(stats['win_rate'], stats['roi'], stats['trades'])}

Use /watchlist to see all your watched wallets."""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        logger.info(f"User {user_id} added wallet {wallet[:12]}... to watchlist")

    async def cmd_watchlist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user's personal watchlist."""
        if not self._is_private(update):
            return

        user_id = update.effective_user.id

        if not self._is_premium(user_id):
            await update.message.reply_text(
                "This feature is for premium users only.\n"
                "Contact admin for access."
            )
            return

        logger.info(f"Watchlist command from user {user_id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Ensure table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_watchlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    wallet_address TEXT NOT NULL,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    win_rate REAL DEFAULT 0,
                    roi REAL DEFAULT 0,
                    total_trades INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    UNIQUE(user_id, wallet_address)
                )
            """)
            conn.commit()

            cursor.execute("""
                SELECT wallet_address, win_rate, roi, total_trades, added_date
                FROM user_watchlists
                WHERE user_id = ?
                ORDER BY added_date DESC
            """, (user_id,))
            wallets = cursor.fetchall()
            conn.close()

            logger.info(f"Found {len(wallets)} wallets for user {user_id}")

        except Exception as e:
            logger.error(f"Database error in watchlist: {e}")
            await update.message.reply_text(f"Database error: {e}")
            return

        if not wallets:
            await update.message.reply_text(
                "**Your Watchlist**\n\n"
                "No wallets yet.\n\n"
                "To add a wallet:\n"
                "1. Forward a buy alert here\n"
                "2. Reply to it with /add",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        is_admin = self._is_admin(user_id)

        message = f"**Your Watchlist** ({len(wallets)} wallets)\n\n"

        for i, (wallet, win_rate, roi, trades, added) in enumerate(wallets, 1):
            wallet_display = format_wallet_for_user(wallet, is_admin)

            # Win rate emoji - ensure values are not None
            win_rate = win_rate or 0
            roi = roi or 0
            trades = trades or 0

            if win_rate >= 0.6:
                wr_emoji = "🟢"
            elif win_rate >= 0.4:
                wr_emoji = "🟡"
            else:
                wr_emoji = "🔴"

            message += f"**{i}.** {wallet_display}\n"
            message += f"   {wr_emoji} WR: {win_rate*100:.0f}% | ROI: {roi:+.0f}% | Trades: {trades}\n"

            # Add links for admin
            if is_admin:
                message += f"   [Solscan](https://solscan.io/account/{wallet}) | "
                message += f"[Birdeye](https://birdeye.so/profile/{wallet}?chain=solana)\n"

            message += "\n"

        message += "_Use /remove\\_wallet [number] to remove_"

        # Split if too long
        if len(message) > 4000:
            parts = []
            current = ""
            for line in message.split('\n'):
                if len(current) + len(line) + 1 > 4000:
                    parts.append(current)
                    current = line
                else:
                    current += '\n' + line if current else line
            if current:
                parts.append(current)

            for part in parts:
                await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_remove_wallet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove a wallet from watchlist by index."""
        if not self._is_private(update):
            return

        user_id = update.effective_user.id

        if not self._is_premium(user_id):
            await update.message.reply_text(
                "This feature is for premium users only."
            )
            return

        logger.info(f"Remove wallet command from user {user_id}")

        # Parse index from command
        text = update.message.text or ""
        index = parse_remove_index(text)

        if not index:
            await update.message.reply_text(
                "**Usage:** /remove_wallet [number]\n\n"
                "Example: /remove_wallet 1\n\n"
                "Use /watchlist to see numbered list.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        try:
            # Get user's wallets
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, wallet_address FROM user_watchlists
                WHERE user_id = ?
                ORDER BY added_date DESC
            """, (user_id,))
            wallets = cursor.fetchall()

            logger.info(f"User {user_id} has {len(wallets)} wallets, removing index {index}")

            if len(wallets) == 0:
                conn.close()
                await update.message.reply_text("Your watchlist is empty.")
                return

            if index < 1 or index > len(wallets):
                conn.close()
                await update.message.reply_text(
                    f"Invalid index {index}. You have {len(wallets)} wallet(s).\n"
                    f"Use /watchlist to see the numbered list."
                )
                return

            # Get the wallet at that index (1-based to 0-based)
            wallet_id, wallet_addr = wallets[index - 1]
            logger.info(f"Removing wallet id={wallet_id}: {wallet_addr[:12]}...")

            # Delete it
            cursor.execute("DELETE FROM user_watchlists WHERE id = ?", (wallet_id,))
            conn.commit()
            conn.close()

            wallet_display = format_wallet_for_user(wallet_addr, self._is_admin(user_id))

            await update.message.reply_text(
                f"✅ Removed wallet #{index} from watchlist:\n{wallet_display}",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"User {user_id} removed wallet {wallet_addr[:12]}... from watchlist")

        except Exception as e:
            logger.error(f"Remove wallet error: {e}")
            await update.message.reply_text(f"Error removing wallet: {e}")

    async def cmd_label(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Label a watchlist wallet with a nickname."""
        if not self._is_private(update):
            return

        user_id = update.effective_user.id

        if not self._is_premium(user_id):
            await update.message.reply_text("This feature is for premium users only.")
            return

        logger.info(f"Label command from user {user_id}")

        # Parse: /label [number] [nickname]
        text = update.message.text or ""
        parts = text.split(maxsplit=2)

        if len(parts) < 3:
            await update.message.reply_text(
                "**Usage:** /label [number] [nickname]\n\n"
                "Example: /label 1 Whale Trader\n"
                "Example: /label 2 Dev Wallet\n\n"
                "Use /watchlist to see numbered list.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        try:
            index = int(parts[1])
            nickname = parts[2].strip()
        except ValueError:
            await update.message.reply_text("Invalid number. Use /label [number] [nickname]")
            return

        if len(nickname) > 50:
            await update.message.reply_text("Nickname too long. Max 50 characters.")
            return

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get user's wallets
            cursor.execute("""
                SELECT id, wallet_address FROM user_watchlists
                WHERE user_id = ?
                ORDER BY added_date DESC
            """, (user_id,))
            wallets = cursor.fetchall()

            if index < 1 or index > len(wallets):
                conn.close()
                await update.message.reply_text(
                    f"Invalid index. You have {len(wallets)} wallets."
                )
                return

            wallet_id, wallet_addr = wallets[index - 1]

            # Update nickname (stored in notes column)
            cursor.execute(
                "UPDATE user_watchlists SET notes = ? WHERE id = ?",
                (nickname, wallet_id)
            )
            conn.commit()
            conn.close()

            wallet_display = truncate_wallet(wallet_addr)
            await update.message.reply_text(
                f"✅ Labeled wallet #{index}:\n"
                f"{wallet_display} → **{nickname}**",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"User {user_id} labeled wallet {wallet_addr[:12]}... as '{nickname}'")

        except Exception as e:
            logger.error(f"Label command error: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show daily P&L summary for watchlist wallets."""
        if not self._is_private(update):
            return

        user_id = update.effective_user.id

        if not self._is_premium(user_id):
            await update.message.reply_text("This feature is for premium users only.")
            return

        logger.info(f"Summary command from user {user_id}")

        await update.message.reply_text("📊 Calculating daily P&L...")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get user's watchlist wallets
            cursor.execute("""
                SELECT wallet_address, notes, win_rate, roi
                FROM user_watchlists
                WHERE user_id = ?
            """, (user_id,))
            wallets = cursor.fetchall()
            conn.close()

            if not wallets:
                await update.message.reply_text(
                    "No wallets in your watchlist.\n"
                    "Use /add to add wallets."
                )
                return

            # Analyze each wallet's 24h activity
            total_pnl_sol = 0
            total_trades = 0
            wallet_summaries = []

            for wallet_addr, nickname, win_rate, roi in wallets:
                pnl = await self._get_24h_pnl(wallet_addr)

                total_pnl_sol += pnl['pnl_sol']
                total_trades += pnl['trades']

                name = nickname if nickname else truncate_wallet(wallet_addr)
                pnl_emoji = "🟢" if pnl['pnl_sol'] >= 0 else "🔴"

                wallet_summaries.append({
                    'name': name,
                    'pnl_sol': pnl['pnl_sol'],
                    'trades': pnl['trades'],
                    'emoji': pnl_emoji,
                })

            # Sort by P&L descending
            wallet_summaries.sort(key=lambda x: x['pnl_sol'], reverse=True)

            # Build message
            total_emoji = "📈" if total_pnl_sol >= 0 else "📉"

            message = f"""📊 **DAILY P&L SUMMARY**

{total_emoji} **Total P&L:** {total_pnl_sol:+.2f} SOL
📈 **Trades Today:** {total_trades}

**By Wallet:**
"""
            for w in wallet_summaries[:10]:  # Top 10
                message += f"{w['emoji']} {w['name']}: {w['pnl_sol']:+.2f} SOL ({w['trades']} trades)\n"

            message += "\n_Based on last 24 hours of activity_"

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Summary command error: {e}")
            await update.message.reply_text(f"Error calculating summary: {e}")

    async def _get_24h_pnl(self, wallet_addr: str) -> Dict:
        """Get 24h P&L for a wallet."""
        result = {'pnl_sol': 0.0, 'trades': 0}

        try:
            api_key = await self.rotator.get_key()
            url = f"{self.helius_url}/addresses/{wallet_addr}/transactions?api-key={api_key}&limit=50"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status != 200:
                        return result
                    txs = await response.json()

            now = datetime.now().timestamp()
            day_ago = now - 86400

            skip_tokens = {
                'So11111111111111111111111111111111111111112',
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
            }

            # Track positions
            positions = {}

            for tx in txs:
                tx_time = tx.get('timestamp', 0)
                if tx_time < day_ago:
                    continue

                token_transfers = tx.get('tokenTransfers', [])
                native_transfers = tx.get('nativeTransfers', [])

                for transfer in token_transfers:
                    mint = transfer.get('mint', '')
                    if mint in skip_tokens:
                        continue

                    # Calculate SOL amount
                    sol_amount = 0
                    for nt in native_transfers:
                        if nt.get('fromUserAccount') == wallet_addr:
                            sol_amount += abs(nt.get('amount', 0)) / 1e9
                        elif nt.get('toUserAccount') == wallet_addr:
                            sol_amount -= abs(nt.get('amount', 0)) / 1e9

                    if mint not in positions:
                        positions[mint] = {'spent': 0, 'earned': 0}

                    if transfer.get('toUserAccount') == wallet_addr:
                        positions[mint]['spent'] += abs(sol_amount)
                        result['trades'] += 1
                    elif transfer.get('fromUserAccount') == wallet_addr:
                        positions[mint]['earned'] += abs(sol_amount)

            # Calculate P&L
            for pos in positions.values():
                result['pnl_sol'] += pos['earned'] - pos['spent']

        except Exception as e:
            logger.debug(f"24h P&L error for {wallet_addr[:12]}...: {e}")

        return result

    async def cmd_premium(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show premium features info."""
        if not self._is_private(update):
            return

        logger.info(f"Premium command from user {update.effective_user.id}")

        message = """💎 **SOULWINNERS PREMIUM**

**Free Features:**
• View public buy alerts
• Browse leaderboard

**Premium Features:**
• 👛 Personal watchlist (unlimited wallets)
• 🔔 Private DM alerts for your wallets
• 📊 Daily P&L summaries
• 🏷️ Label wallets with nicknames
• 📤 Export watchlist to CSV
• 🎯 Insider pool access
• 🔗 Cluster detection

**How to Get Premium:**
Contact @YourAdminUsername to upgrade.

_Current status: {status}_"""

        user_id = update.effective_user.id
        if self._is_admin(user_id):
            status = "👑 Admin (Full Access)"
        elif self._is_premium(user_id):
            status = "💎 Premium"
        else:
            status = "🆓 Free"

        await update.message.reply_text(
            message.format(status=status),
            parse_mode=ParseMode.MARKDOWN
        )

    async def cmd_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show quick action buttons."""
        if not self._is_private(update):
            return

        logger.info(f"Buttons command from user {update.effective_user.id}")

        keyboard = [
            [
                InlineKeyboardButton("📊 Watchlist", callback_data="btn_watchlist"),
                InlineKeyboardButton("📈 Summary", callback_data="btn_summary"),
            ],
            [
                InlineKeyboardButton("🏆 Leaderboard", callback_data="btn_leaderboard"),
                InlineKeyboardButton("📊 Pool Stats", callback_data="btn_stats"),
            ],
            [
                InlineKeyboardButton("🎯 Insiders", callback_data="btn_insiders"),
                InlineKeyboardButton("🔗 Clusters", callback_data="btn_clusters"),
            ],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="btn_settings"),
                InlineKeyboardButton("❓ Help", callback_data="btn_help"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🎮 **Quick Actions**\n\nTap a button:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    async def cmd_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Export watchlist to CSV format."""
        if not self._is_private(update):
            return

        user_id = update.effective_user.id

        if not self._is_premium(user_id):
            await update.message.reply_text("This feature is for premium users only.")
            return

        logger.info(f"Export command from user {user_id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT wallet_address, notes, win_rate, roi, total_trades, added_date
                FROM user_watchlists
                WHERE user_id = ?
                ORDER BY added_date DESC
            """, (user_id,))
            wallets = cursor.fetchall()
            conn.close()

            if not wallets:
                await update.message.reply_text("No wallets to export.")
                return

            # Build CSV
            csv_lines = ["wallet_address,nickname,win_rate,roi,trades,added_date"]
            for w in wallets:
                addr, nick, wr, roi, trades, added = w
                nick = nick or ""
                csv_lines.append(f"{addr},{nick},{wr or 0:.2f},{roi or 0:.0f},{trades or 0},{added or ''}")

            csv_content = "\n".join(csv_lines)

            # Send as document
            csv_file = BytesIO(csv_content.encode('utf-8'))
            csv_file.name = "watchlist_export.csv"

            await update.message.reply_document(
                document=csv_file,
                filename="watchlist_export.csv",
                caption=f"📤 Exported {len(wallets)} wallets"
            )
            logger.info(f"User {user_id} exported {len(wallets)} wallets")

        except Exception as e:
            logger.error(f"Export error: {e}")
            await update.message.reply_text(f"Export failed: {e}")

    async def _analyze_wallet_stats(self, wallet: str) -> Dict:
        """Analyze a wallet and return stats (win rate, ROI, trades)."""
        stats = {
            'win_rate': 0.0,
            'roi': 0.0,
            'trades': 0,
        }

        try:
            api_key = await self.rotator.get_key()
            url = f"{self.helius_url}/addresses/{wallet}/transactions?api-key={api_key}&limit=100"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch wallet txs: {response.status}")
                        return stats

                    txs = await response.json()

            # Track token positions: token -> {sol_spent, sol_earned}
            token_positions = {}

            skip_tokens = {
                'So11111111111111111111111111111111111111112',
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
            }

            for tx in txs:
                token_transfers = tx.get('tokenTransfers', [])
                native_transfers = tx.get('nativeTransfers', [])

                for transfer in token_transfers:
                    mint = transfer.get('mint', '')
                    if mint in skip_tokens:
                        continue

                    to_wallet = transfer.get('toUserAccount')
                    from_wallet = transfer.get('fromUserAccount')

                    if mint not in token_positions:
                        token_positions[mint] = {'sol_spent': 0, 'sol_earned': 0}

                    # Calculate SOL amount for this tx
                    sol_amount = 0
                    for nt in native_transfers:
                        if nt.get('fromUserAccount') == wallet:
                            sol_amount += abs(nt.get('amount', 0)) / 1e9
                        elif nt.get('toUserAccount') == wallet:
                            sol_amount -= abs(nt.get('amount', 0)) / 1e9

                    if to_wallet == wallet:  # Buy
                        token_positions[mint]['sol_spent'] += abs(sol_amount)
                    elif from_wallet == wallet:  # Sell
                        token_positions[mint]['sol_earned'] += abs(sol_amount)

            # Calculate stats
            total_spent = 0
            total_earned = 0
            wins = 0
            closed_trades = 0

            for token, pos in token_positions.items():
                spent = pos['sol_spent']
                earned = pos['sol_earned']

                if spent > 0:
                    total_spent += spent

                    if earned > 0:  # Closed position
                        total_earned += earned
                        closed_trades += 1

                        if earned > spent:
                            wins += 1

            stats['trades'] = len(token_positions)

            if closed_trades > 0:
                stats['win_rate'] = wins / closed_trades

            if total_spent > 0:
                stats['roi'] = ((total_earned - total_spent) / total_spent) * 100

            logger.info(f"Analyzed wallet {wallet[:12]}...: WR={stats['win_rate']:.0%}, ROI={stats['roi']:.0f}%, Trades={stats['trades']}")

        except Exception as e:
            logger.error(f"Failed to analyze wallet: {e}")

        return stats

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pool statistics."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Stats command received from user {update.effective_user.id}")
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Total wallets
            cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
            total = cursor.fetchone()[0]

            # Tier breakdown
            cursor.execute("""
                SELECT tier, COUNT(*), AVG(roi_pct), AVG(win_rate)
                FROM qualified_wallets
                GROUP BY tier
            """)
            tiers = cursor.fetchall()

            # Strategy breakdown
            cursor.execute("""
                SELECT cluster_name, COUNT(*)
                FROM qualified_wallets
                GROUP BY cluster_name
            """)
            strategies = cursor.fetchall()

            # Averages
            cursor.execute("""
                SELECT AVG(roi_pct), AVG(win_rate), AVG(current_balance_sol),
                       SUM(current_balance_sol)
                FROM qualified_wallets
            """)
            avgs = cursor.fetchone()
            conn.close()

            avg_roi, avg_wr, avg_bal, total_sol = avgs

            message = f"""📈 **POOL STATISTICS**

**Overview:**
├ Total Wallets: {total}
├ Total SOL Tracked: {total_sol or 0:,.0f} SOL
├ Avg ROI: {avg_roi or 0:,.0f}%
├ Avg Win Rate: {(avg_wr or 0)*100:.0f}%
└ Avg Balance: {avg_bal or 0:.2f} SOL

**Tier Breakdown:**
"""
            for tier, count, roi, wr in tiers:
                emoji = '🔥' if tier == 'Elite' else '🟢' if tier == 'High-Quality' else '🟡'
                message += f"{emoji} {tier}: {count} wallets (Avg ROI: {roi:,.0f}%)\n"

            message += "\n**Strategy Distribution:**\n"
            for strat, count in strategies:
                message += f"• {strat}: {count}\n"

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            logger.info("Stats command completed successfully")
        except Exception as e:
            logger.error(f"Stats command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comprehensive metrics guide."""
        if not self._is_private(update):
            return

        logger.info(f"Help command received from user {update.effective_user.id}")

        try:
            # Split into multiple messages for readability
            msg1 = """📊 **SOULWINNERS METRICS GUIDE**

**📈 BUY EFFICIENCY SCORE (BES)**
Measures capital efficiency - ROI per SOL risked.
`Formula: (ROI/Trade × Win Rate × Frequency) / Avg Buy`
Higher = Better returns with less capital

Example:
• Wallet A: 1000% ROI, 10 SOL avg buy = BES: 100
• Wallet B: 200% ROI, 0.5 SOL avg buy = BES: 400 ✅
_Wallet B is 4x more capital efficient!_

**📈 ROI/TRADE**
Average return on investment per trade
`Calculation: Total PnL / Number of trades`

**✅ WIN RATE**
Percentage of profitable trades
`Calculation: Winning trades / Total trades × 100%`

**💰 AVG BUY**
Average SOL amount invested per trade
Shows wallet's typical position size"""

            msg2 = """**🔢 TRADES**
Total number of trades in last 15 days
Higher = More active, more data points

**💎 BALANCE (LIVE)**
Current SOL balance fetched in real-time
Updated on each /pool request

**🕐 LAST BUY**
Most recent token purchase
Shows: Token symbol, time ago, 24h price change

**🎯 STRATEGY TYPES**
• **Moonshot Hunters** - High-risk, chasing 10x+
• **Core Alpha (Active)** - Frequent, consistent gains
• **Conviction Holders** - Long-term positions
• **Low-frequency Snipers** - Few trades, high conviction
• **Dormant/Legacy** - Previously active, now quiet"""

            msg3 = """**📊 QUALITY FILTERS**
Wallets must meet ALL to enter pool:
• SOL Balance ≥ 10
• Trades ≥ 15 (in 15 days)
• Win Rate ≥ 60%
• Total ROI ≥ 50%

**🔔 ALERT FILTERS**
Buy alerts posted to channel when:
• Wallet buys ≥ 2 SOL worth
• Transaction < 5 minutes old
• Last 5 closed trades show ≥ 60% win rate

**📱 COMMANDS**
/pool - BES leaderboard with live balances
/wallets - Full addresses with links
/leaderboard - Top 10 by ROI
/stats - Pool statistics
/buttons - Quick action buttons
/help - This guide

**🎯 ANALYSIS**
/insiders - Insider pool statistics
/clusters - Detected wallet clusters
/early_birds - Fresh launch snipers

**👁️ WATCHLIST**
/add - Reply to alert to add wallet
/watchlist - View your watched wallets
/remove [n] - Remove wallet by number
/label [n] [name] - Nickname a wallet
/summary - Daily P&L summary
/export - Export watchlist to CSV
/premium - Premium features info

**⚙️ ADMIN**
/settings - Control panel
/cron - Cron job status
/logs - View system logs
/restart - Restart components
/trader - Auto-trader status

_Watchlist alerts:_
_• BUY: When they buy ≥1.5 SOL_
_• SELL: When they sell (shows P/L)_"""

            await update.message.reply_text(msg1, parse_mode=ParseMode.MARKDOWN)
            await update.message.reply_text(msg2, parse_mode=ParseMode.MARKDOWN)
            await update.message.reply_text(msg3, parse_mode=ParseMode.MARKDOWN)
            logger.info("Help command completed successfully")
        except Exception as e:
            logger.error(f"Help command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    # =========================================================================
    # SETTINGS COMMANDS
    # =========================================================================

    def _get_setting(self, key: str, default: str = None) -> str:
        """Get a setting from the database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else default
        except:
            return default

    def _set_setting(self, key: str, value: str):
        """Set a setting in the database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (key, value))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")

    def _get_all_settings(self) -> Dict[str, str]:
        """Get all settings from database."""
        settings = {}
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            for row in cursor.fetchall():
                settings[row[0]] = row[1]
            conn.close()
        except:
            pass
        return settings

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Interactive settings control panel."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Settings command received from user {update.effective_user.id}")

        try:
            settings = self._get_all_settings()

            # Build settings display
            alerts_on = settings.get('alerts_enabled', 'true') == 'true'
            monitor_on = settings.get('monitor_enabled', 'true') == 'true'
            auto_disc = settings.get('auto_discovery', 'true') == 'true'

            message = """⚙️ **SOULWINNERS SETTINGS**

🔔 **ALERTS**
├─ Min Buy Amount: **{min_buy}** SOL
├─ Alert Age Limit: **{age_limit}** min
├─ Last 5 Win Rate: **{win_rate}%**
└─ Alerts: **{alerts_status}**

🔄 **CRON JOB**
├─ Discovery Frequency: **{freq}** min
└─ Auto-discovery: **{auto_disc}**

📊 **POOL FILTERS**
├─ Min SOL Balance: **{min_sol}**
├─ Min Trades: **{min_trades}**
├─ Min Win Rate: **{min_wr}%**
└─ Min ROI: **{min_roi}%**

👁️ **MONITORING**
├─ Poll Interval: **{poll_int}**s
└─ Monitor: **{monitor_status}**

_Tap buttons below to change settings_""".format(
                min_buy=settings.get('min_buy_amount', '2.0'),
                age_limit=settings.get('alert_age_limit_min', '5'),
                win_rate=int(float(settings.get('last_5_win_rate', '0.6')) * 100),
                alerts_status='🟢 ON' if alerts_on else '🔴 OFF',
                freq=settings.get('discovery_frequency_min', '30'),
                auto_disc='🟢 ON' if auto_disc else '🔴 OFF',
                min_sol=settings.get('min_sol_balance', '10'),
                min_trades=settings.get('min_trades', '15'),
                min_wr=int(float(settings.get('min_win_rate', '0.6')) * 100),
                min_roi=int(float(settings.get('min_roi', '0.5')) * 100),
                poll_int=settings.get('poll_interval_sec', '30'),
                monitor_status='🟢 ON' if monitor_on else '🔴 OFF'
            )

            # Build keyboard
            keyboard = [
                [
                    InlineKeyboardButton("🔔 Toggle Alerts", callback_data="toggle_alerts"),
                    InlineKeyboardButton("👁️ Toggle Monitor", callback_data="toggle_monitor"),
                ],
                [
                    InlineKeyboardButton("📊 Min Buy: +0.5", callback_data="min_buy_up"),
                    InlineKeyboardButton("📊 Min Buy: -0.5", callback_data="min_buy_down"),
                ],
                [
                    InlineKeyboardButton("⏱️ Poll: +10s", callback_data="poll_up"),
                    InlineKeyboardButton("⏱️ Poll: -10s", callback_data="poll_down"),
                ],
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="refresh_settings"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Settings command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_cron(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cron job status and control."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Cron command received from user {update.effective_user.id}")

        try:
            # Get last pipeline run from database
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT started_at, completed_at, status, wallets_collected,
                       wallets_qualified, wallets_added, error_message
                FROM pipeline_runs
                ORDER BY id DESC LIMIT 1
            """)
            last_run = cursor.fetchone()

            # Get pool stats
            cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
            total_wallets = cursor.fetchone()[0]

            cursor.execute("SELECT tier, COUNT(*) FROM qualified_wallets GROUP BY tier")
            tiers = cursor.fetchall()
            conn.close()

            # Get cron frequency from settings (default 10 min)
            cron_freq = int(self._get_setting('discovery_frequency_min', '10'))

            # Calculate next run time
            now = datetime.now()
            minutes_past = now.minute % cron_freq
            next_run_min = cron_freq - minutes_past if minutes_past > 0 else 0

            # Build tier breakdown
            tier_text = ""
            for tier, count in tiers:
                pct = int(count / total_wallets * 100) if total_wallets > 0 else 0
                tier_text += f"├─ {tier}: {count} ({pct}%)\n"
            if tier_text:
                tier_text = tier_text[:-1]  # Remove last newline

            # Last run info
            if last_run:
                started, completed, status, collected, qualified, added, error = last_run
                last_run_time = started[:16] if started else "Never"
                duration = "N/A"
                if started and completed:
                    try:
                        start_dt = datetime.fromisoformat(started)
                        end_dt = datetime.fromisoformat(completed)
                        dur_sec = (end_dt - start_dt).total_seconds()
                        duration = f"{int(dur_sec // 60)}m {int(dur_sec % 60)}s"
                    except:
                        pass
                issue_text = f"└─ {error}" if error else "└─ None"
            else:
                last_run_time = "Never"
                collected = qualified = added = 0
                duration = "N/A"
                status = "unknown"
                issue_text = "└─ No runs yet"

            message = f"""🔄 **WALLET DISCOVERY CRON STATUS**

⏰ **SCHEDULE**
├─ Frequency: Every {cron_freq} minutes
├─ Next Run: in {next_run_min}m
└─ Last Run: {last_run_time}

📊 **LAST RUN RESULTS**
├─ Wallets Scanned: {collected or 0}
├─ Passed Filters: {qualified or 0}
├─ Added to Pool: {added or 0}
└─ Duration: {duration}

⚠️ **ISSUES**
{issue_text}

💾 **CURRENT POOL**
├─ Total Wallets: {total_wallets}
{tier_text}

_Use buttons below to control cron job_"""

            keyboard = [
                [
                    InlineKeyboardButton("▶️ Run Now", callback_data="cron_run_now"),
                    InlineKeyboardButton("📋 View Logs", callback_data="cron_logs"),
                ],
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="refresh_cron"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Cron command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View recent system logs."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Logs command received from user {update.effective_user.id}")

        try:
            keyboard = [
                [
                    InlineKeyboardButton("📡 Bot Logs", callback_data="logs_bot"),
                    InlineKeyboardButton("🔄 Cron Logs", callback_data="logs_cron"),
                ],
                [
                    InlineKeyboardButton("⚠️ Error Logs", callback_data="logs_errors"),
                    InlineKeyboardButton("📊 Monitor Logs", callback_data="logs_monitor"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "📋 **SYSTEM LOGS**\n\nSelect which logs to view:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Logs command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Restart system components."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Restart command received from user {update.effective_user.id}")

        try:
            keyboard = [
                [
                    InlineKeyboardButton("🤖 Restart Bot", callback_data="restart_bot"),
                ],
                [
                    InlineKeyboardButton("🔄 Run Pipeline", callback_data="restart_pipeline"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "🔧 **SYSTEM CONTROL**\n\n⚠️ Use with caution!\n\nSelect component to restart:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Restart command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_trader(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """OpenClaw auto-trader status."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Trader command received from user {update.effective_user.id}")

        try:
            # Try to import OpenClaw
            try:
                from trader.position_manager import PositionManager
                pm = PositionManager()
                stats = pm.get_stats()
                positions = pm.get_open_positions()
            except ImportError:
                await update.message.reply_text(
                    "🤖 **OPENCLAW AUTO-TRADER**\n\n"
                    "⚠️ OpenClaw module not installed.\n\n"
                    "To enable auto-trading:\n"
                    "1. Set `OPENCLAW_PRIVATE_KEY` in .env\n"
                    "2. Fund wallet with SOL\n"
                    "3. Run `python3 run_openclaw.py`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # Format positions
            pos_text = ""
            if positions:
                for p in positions:
                    emoji = "🟢" if p.pnl_percent >= 0 else "🔴"
                    pos_text += f"\n{emoji} **{p.token_symbol}**\n"
                    pos_text += f"├ Entry: {p.entry_sol:.4f} SOL\n"
                    pos_text += f"├ P&L: {p.pnl_percent:+.1f}%\n"
                    pos_text += f"├ TP1: {'✅' if p.tp1_hit else '⏳'} | TP2: {'✅' if p.tp2_hit else '⏳'}\n"
                    pos_text += f"└ Remaining: {p.remaining_percent:.0f}%\n"
            else:
                pos_text = "\n└ No open positions"

            # Calculate goal progress bar
            progress = min(100, stats['progress_percent'])
            bar_filled = int(progress / 10)
            bar_empty = 10 - bar_filled
            progress_bar = "█" * bar_filled + "░" * bar_empty

            message = f"""🤖 **OPENCLAW AUTO-TRADER**

💰 **PORTFOLIO**
├ Starting: {stats['starting_balance']:.4f} SOL
├ Current: {stats['current_balance']:.4f} SOL
├ P&L: {stats['total_pnl_sol']:+.4f} SOL ({stats['total_pnl_percent']:+.1f}%)
└ Open: {stats['open_positions']}/3 positions

📊 **PERFORMANCE**
├ Total Trades: {stats['total_trades']}
├ Winning: {stats['winning_trades']}
└ Win Rate: {stats['win_rate']:.1f}%

🎯 **GOAL: $10,000**
├ Progress: {progress:.1f}%
└ [{progress_bar}]

📍 **OPEN POSITIONS**{pos_text}

_Strategy: Copy Elite Wallets (BES >1000)_"""

            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="refresh_trader"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Trader command failed: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def cmd_insiders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show insider pool statistics."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Insiders command received from user {update.effective_user.id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get insider pool stats
            cursor.execute("""
                SELECT COUNT(*),
                       AVG(early_entry_count),
                       AVG(win_rate),
                       AVG(avg_hold_minutes)
                FROM insider_pool
                WHERE is_active = 1
            """)
            row = cursor.fetchone()
            total = row[0] if row else 0
            avg_entries = row[1] if row and row[1] else 0
            avg_wr = row[2] if row and row[2] else 0
            avg_hold = row[3] if row and row[3] else 0

            # Get tier breakdown
            cursor.execute("""
                SELECT tier, COUNT(*)
                FROM insider_pool
                WHERE is_active = 1
                GROUP BY tier
                ORDER BY
                    CASE tier
                        WHEN 'Elite' THEN 1
                        WHEN 'Pro' THEN 2
                        WHEN 'Emerging' THEN 3
                        ELSE 4
                    END
            """)
            tiers = cursor.fetchall()

            # Get recent additions
            cursor.execute("""
                SELECT wallet_address, tier, early_entry_count, discovered_at
                FROM insider_pool
                WHERE is_active = 1
                ORDER BY discovered_at DESC
                LIMIT 5
            """)
            recent = cursor.fetchall()

            conn.close()

            # Build tier breakdown
            tier_text = ""
            for tier, count in tiers:
                pct = int(count / total * 100) if total > 0 else 0
                tier_text += f"├─ {tier}: {count} ({pct}%)\n"
            if tier_text:
                tier_text = tier_text[:-1]
            else:
                tier_text = "└─ No tiers yet"

            # Build recent list
            recent_text = ""
            if recent:
                for wallet, tier, entries, discovered in recent[:3]:
                    short_addr = f"{wallet[:6]}...{wallet[-4:]}"
                    recent_text += f"├─ {short_addr} ({tier})\n"
                    recent_text += f"│  Entries: {entries}, Added: {discovered[:10]}\n"
                recent_text = recent_text[:-1]
            else:
                recent_text = "└─ No recent additions"

            message = f"""🎯 <b>INSIDER POOL STATISTICS</b>

📊 <b>OVERVIEW</b>
├─ Total Insiders: {total}
├─ Avg Early Entries: {avg_entries:.1f}
├─ Avg Win Rate: {avg_wr:.1%}
└─ Avg Hold Time: {int(avg_hold or 0)}m

🏆 <b>TIER BREAKDOWN</b>
{tier_text}

🆕 <b>RECENT ADDITIONS</b> (Last 3)
{recent_text}

<i>Fresh launch snipers detected every 15 minutes</i>
<i>Use /early_birds to see latest catches</i>"""

            await update.message.reply_text(message, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Insiders command failed: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ Insider pool not initialized yet or error: {str(e)}")

    async def cmd_clusters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detected wallet clusters."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Clusters command received from user {update.effective_user.id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get cluster stats
            cursor.execute("""
                SELECT COUNT(DISTINCT cluster_id),
                       AVG(cluster_size),
                       COUNT(*)
                FROM wallet_clusters
                WHERE is_active = 1
            """)
            row = cursor.fetchone()
            total_clusters = row[0] if row else 0
            avg_size = row[1] if row and row[1] else 0
            total_memberships = row[2] if row else 0

            # Get largest clusters
            cursor.execute("""
                SELECT cluster_id, cluster_type, cluster_size,
                       shared_tokens, connection_strength, detected_at
                FROM wallet_clusters
                WHERE is_active = 1
                GROUP BY cluster_id
                ORDER BY cluster_size DESC, connection_strength DESC
                LIMIT 5
            """)
            top_clusters = cursor.fetchall()

            conn.close()

            # Build top clusters list
            cluster_text = ""
            if top_clusters:
                for i, (cid, ctype, size, tokens, strength, detected) in enumerate(top_clusters[:3], 1):
                    cluster_text += f"<b>{i}. Cluster #{cid}</b>\n"
                    cluster_text += f"├─ Type: {ctype}\n"
                    cluster_text += f"├─ Size: {size} wallets\n"
                    cluster_text += f"├─ Shared Tokens: {tokens}\n"
                    cluster_text += f"├─ Strength: {strength:.0%}\n"
                    cluster_text += f"└─ Detected: {detected[:10]}\n\n"
            else:
                cluster_text = "No clusters detected yet.\n"

            message = f"""🔗 <b>WALLET CLUSTER ANALYSIS</b>

📊 <b>OVERVIEW</b>
├─ Total Clusters: {total_clusters}
├─ Avg Cluster Size: {avg_size:.1f} wallets
└─ Total Memberships: {total_memberships}

🏆 <b>TOP CLUSTERS</b> (By Size)

{cluster_text}
<i>Clusters analyzed every 20 minutes</i>
<i>Look for: Dev teams, insider groups, coordinated buyers</i>"""

            await update.message.reply_text(message, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Clusters command failed: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ Cluster detection not initialized yet or error: {str(e)}")

    async def cmd_early_birds(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show fresh launch snipers (early bird wallets)."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Early birds command received from user {update.effective_user.id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get early bird stats from insider pool
            cursor.execute("""
                SELECT COUNT(*),
                       AVG(early_entry_count),
                       AVG(win_rate),
                       MAX(early_entry_count)
                FROM insider_pool
                WHERE is_active = 1
                AND early_entry_count >= 3
            """)
            row = cursor.fetchone()
            total = row[0] if row else 0
            avg_entries = row[1] if row and row[1] else 0
            avg_wr = row[2] if row and row[2] else 0
            max_entries = row[3] if row and row[3] else 0

            # Get top performers
            cursor.execute("""
                SELECT wallet_address, tier, early_entry_count,
                       win_rate, avg_roi_percent, discovered_at
                FROM insider_pool
                WHERE is_active = 1
                AND early_entry_count >= 3
                ORDER BY early_entry_count DESC, win_rate DESC
                LIMIT 10
            """)
            top_snipers = cursor.fetchall()

            conn.close()

            # Build top snipers list
            sniper_text = ""
            if top_snipers:
                for i, (wallet, tier, entries, wr, roi, discovered) in enumerate(top_snipers[:5], 1):
                    short_addr = f"{wallet[:6]}...{wallet[-4:]}"
                    sniper_text += f"<b>{i}. {short_addr}</b> ({tier})\n"
                    sniper_text += f"├─ Early Entries: {entries}\n"
                    sniper_text += f"├─ Win Rate: {wr:.1%}\n"
                    sniper_text += f"├─ Avg ROI: {roi:+.1f}%\n"
                    sniper_text += f"└─ Found: {discovered[:10]}\n\n"
            else:
                sniper_text = "No early birds detected yet.\n"

            message = f"""🐦 <b>FRESH LAUNCH SNIPERS</b>

📊 <b>STATISTICS</b>
├─ Total Early Birds: {total}
├─ Avg Early Entries: {avg_entries:.1f}
├─ Avg Win Rate: {avg_wr:.1%}
└─ Max Entries: {max_entries}

🏆 <b>TOP SNIPERS</b> (Most Early Entries)

{sniper_text}
<i>These wallets consistently buy within minutes of token creation</i>
<i>Updated every 15 minutes via insider detection</i>"""

            await update.message.reply_text(message, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error(f"Early birds command failed: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ Insider detection not initialized yet or error: {str(e)}")

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses."""
        query = update.callback_query
        await query.answer()

        if not self._is_admin(query.from_user.id):
            return

        data = query.data
        logger.info(f"Callback received: {data}")

        try:
            # Settings toggles
            if data == "toggle_alerts":
                current = self._get_setting('alerts_enabled', 'true')
                new_val = 'false' if current == 'true' else 'true'
                self._set_setting('alerts_enabled', new_val)
                status = "🟢 ON" if new_val == 'true' else "🔴 OFF"
                await query.edit_message_text(f"✅ Alerts are now {status}\n\nUse /settings to see all settings.")

            elif data == "toggle_monitor":
                current = self._get_setting('monitor_enabled', 'true')
                new_val = 'false' if current == 'true' else 'true'
                self._set_setting('monitor_enabled', new_val)
                status = "🟢 ON" if new_val == 'true' else "🔴 OFF"
                await query.edit_message_text(f"✅ Monitor is now {status}\n\nUse /settings to see all settings.")

            elif data == "min_buy_up":
                current = float(self._get_setting('min_buy_amount', '2.0'))
                new_val = min(10.0, current + 0.5)
                self._set_setting('min_buy_amount', str(new_val))
                await query.edit_message_text(f"✅ Min buy amount: {new_val} SOL\n\nUse /settings to see all settings.")

            elif data == "min_buy_down":
                current = float(self._get_setting('min_buy_amount', '2.0'))
                new_val = max(0.5, current - 0.5)
                self._set_setting('min_buy_amount', str(new_val))
                await query.edit_message_text(f"✅ Min buy amount: {new_val} SOL\n\nUse /settings to see all settings.")

            elif data == "poll_up":
                current = int(self._get_setting('poll_interval_sec', '30'))
                new_val = min(120, current + 10)
                self._set_setting('poll_interval_sec', str(new_val))
                await query.edit_message_text(f"✅ Poll interval: {new_val}s\n\nUse /settings to see all settings.")

            elif data == "poll_down":
                current = int(self._get_setting('poll_interval_sec', '30'))
                new_val = max(10, current - 10)
                self._set_setting('poll_interval_sec', str(new_val))
                await query.edit_message_text(f"✅ Poll interval: {new_val}s\n\nUse /settings to see all settings.")

            elif data == "refresh_settings":
                # Re-send settings command
                await query.message.delete()
                await self.cmd_settings(update, context)

            # Cron controls
            elif data == "cron_run_now":
                await query.edit_message_text("🔄 Starting pipeline... This may take a few minutes.\n\nUse /cron to check status.")
                # Run pipeline in background
                subprocess.Popen(
                    ["python3", "run_pipeline.py"],
                    cwd="/root/Soulwinners",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

            elif data == "cron_logs":
                await self._send_log_content(query, "cron")

            elif data == "refresh_cron":
                await query.message.delete()
                await self.cmd_cron(update, context)

            # Logs
            elif data == "logs_bot":
                await self._send_log_content(query, "bot")

            elif data == "logs_cron":
                await self._send_log_content(query, "cron")

            elif data == "logs_errors":
                await self._send_log_content(query, "errors")

            elif data == "logs_monitor":
                await self._send_log_content(query, "monitor")

            # Restart controls
            elif data == "restart_bot":
                await query.edit_message_text("🔄 Restarting bot service...\n\n⚠️ You may need to wait a moment and try /start again.")
                subprocess.Popen(["systemctl", "restart", "soulwinners"])

            elif data == "restart_pipeline":
                await query.edit_message_text("🔄 Starting pipeline manually...\n\nUse /cron to check progress.")
                subprocess.Popen(
                    ["python3", "run_pipeline.py"],
                    cwd="/root/Soulwinners",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

            elif data == "refresh_trader":
                await query.message.delete()
                await self.cmd_trader(update, context)

            # Quick action buttons from /buttons command
            elif data == "btn_watchlist":
                await query.message.delete()
                await self.cmd_watchlist(update, context)

            elif data == "btn_summary":
                await query.message.delete()
                await self.cmd_summary(update, context)

            elif data == "btn_leaderboard":
                await query.message.delete()
                await self.cmd_leaderboard(update, context)

            elif data == "btn_stats":
                await query.message.delete()
                await self.cmd_stats(update, context)

            elif data == "btn_insiders":
                await query.message.delete()
                await self.cmd_insiders(update, context)

            elif data == "btn_clusters":
                await query.message.delete()
                await self.cmd_clusters(update, context)

            elif data == "btn_settings":
                await query.message.delete()
                await self.cmd_settings(update, context)

            elif data == "btn_help":
                await query.message.delete()
                await self.cmd_help(update, context)

        except Exception as e:
            logger.error(f"Callback error: {e}")
            await query.edit_message_text(f"Error: {e}")

    async def _send_log_content(self, query, log_type: str):
        """Send log file content."""
        log_paths = {
            "bot": "/root/Soulwinners/logs/bot.log",
            "cron": "/root/Soulwinners/logs/cron.log",
            "monitor": "/root/Soulwinners/logs/monitor.log",
            "errors": "/root/Soulwinners/logs/bot.log",  # Filter for errors
        }

        log_path = log_paths.get(log_type, log_paths["bot"])

        try:
            # Read last 30 lines
            if log_type == "errors":
                result = subprocess.run(
                    ["grep", "-i", "error\\|exception\\|failed", log_path],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split('\n')[-20:]
            else:
                result = subprocess.run(
                    ["tail", "-30", log_path],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split('\n')

            if not lines or lines == ['']:
                content = "No logs found."
            else:
                content = '\n'.join(lines[-20:])  # Last 20 lines

            # Truncate if too long
            if len(content) > 3500:
                content = content[-3500:]

            await query.edit_message_text(
                f"📋 **{log_type.upper()} LOGS** (last 20 lines)\n\n```\n{content}\n```",
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            await query.edit_message_text(f"Error reading logs: {e}")

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _get_live_balance(self, wallet_addr: str) -> Optional[float]:
        """Get live SOL balance using public Solana RPC (Helius is rate limited)."""
        # Check cache (valid for 5 minutes)
        if wallet_addr in self._balance_cache:
            balance, cached_at = self._balance_cache[wallet_addr]
            if (datetime.now() - cached_at).seconds < 300:
                return balance

        # Use public Solana RPC (more reliable than rate-limited Helius)
        url = "https://api.mainnet-beta.solana.com"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [wallet_addr]
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'result' in data and 'value' in data['result']:
                            # Balance is in lamports (1 SOL = 1e9 lamports)
                            balance = data['result']['value'] / 1e9
                            self._balance_cache[wallet_addr] = (balance, datetime.now())
                            return balance
        except Exception as e:
            logger.debug(f"Balance fetch failed for {wallet_addr}: {e}")

        return None

    async def _get_last_buy_info(self, wallet_addr: str) -> Optional[Dict]:
        """Get info about the wallet's last buy transaction using rotated API keys."""
        api_key = await self.rotator.get_key()
        url = f"{self.helius_url}/addresses/{wallet_addr}/transactions?api-key={api_key}&limit=20"

        skip_tokens = {
            'So11111111111111111111111111111111111111112',  # WSOL
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status != 200:
                        return None

                    txs = await response.json()

                    for tx in txs:
                        token_transfers = tx.get('tokenTransfers', [])
                        if not token_transfers:
                            continue

                        # Find token transfer to this wallet (buy)
                        for transfer in token_transfers:
                            mint = transfer.get('mint', '')
                            if mint in skip_tokens:
                                continue

                            if transfer.get('toUserAccount') == wallet_addr:
                                # This is a buy
                                ts = tx.get('timestamp', 0)
                                token_symbol = transfer.get('symbol') or transfer.get('tokenSymbol') or mint[:6]

                                # Calculate time ago
                                time_ago = self._format_time_ago(ts)

                                # Try to get current price vs buy price for PnL
                                pnl_str = ""
                                token_info = await self._get_token_price(mint)
                                if token_info:
                                    pnl_str = f"+{token_info.get('price_change_24h', 0):.0f}%" if token_info.get('price_change_24h', 0) >= 0 else f"{token_info.get('price_change_24h', 0):.0f}%"

                                return {
                                    'time_ago': time_ago,
                                    'token': token_symbol,
                                    'pnl': pnl_str,
                                    'timestamp': ts,
                                }
        except Exception as e:
            logger.debug(f"Last buy fetch failed: {e}")

        return None

    async def _get_token_price(self, token_address: str) -> Optional[Dict]:
        """Get token price info from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            pair = data[0]
                            return {
                                'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                                'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0) or 0),
                            }
        except:
            pass
        return None

    def _format_time_ago(self, timestamp: int) -> str:
        """Format timestamp as relative time."""
        if not timestamp:
            return "Unknown"

        diff = datetime.now().timestamp() - timestamp
        if diff < 60:
            return "Just now"
        elif diff < 3600:
            return f"{int(diff/60)}m ago"
        elif diff < 86400:
            return f"{int(diff/3600)}h ago"
        elif diff < 604800:
            return f"{int(diff/86400)}d ago"
        else:
            return f"{int(diff/604800)}w ago"

    async def _get_last_trade_time(self, wallet_addr: str) -> str:
        """Get last activity time for a wallet using rotated API keys."""
        api_key = await self.rotator.get_key()
        url = f"{self.helius_url}/addresses/{wallet_addr}/transactions?api-key={api_key}&limit=1"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        txs = await response.json()
                        if txs:
                            ts = txs[0].get('timestamp', 0)
                            return self._format_time_ago(ts)
        except:
            pass

        return "Unknown"


async def run_command_bot():
    """Run the command bot standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    bot = CommandBot()
    try:
        await bot.start()
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(run_command_bot())
