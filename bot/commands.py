"""
Telegram Bot Commands - Private DM Only
Only responds to authorized admin user
With interactive settings, cron control, and logging
"""
import asyncio
import logging
import subprocess
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
import aiohttp

from config.settings import TELEGRAM_BOT_TOKEN
from database import get_connection
from collectors.helius import helius_rotator

logger = logging.getLogger(__name__)

# Admin user ID - ONLY this user can use commands
ADMIN_USER_ID = None  # Will be set on first /start


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

        # Register callback handler for inline buttons
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        logger.info("Command bot started")

    async def stop(self):
        """Stop the bot."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

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
/wallets - Full addresses with Solscan/Birdeye links
/leaderboard - Top 10 by ROI
/stats - Pool statistics
/settings - Control panel (alerts, filters, cron)
/cron - Cron job status & control
/logs - View system logs
/restart - Restart components
/help - This guide"""

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
