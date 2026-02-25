"""
Telegram Bot Commands - UPDATED with clean format
All fixes: accumulation, bullet format, 10 min cron, working settings
"""
import asyncio
import logging
import subprocess
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
import aiohttp

from config.settings import TELEGRAM_BOT_TOKEN
from database import get_connection
from collectors.helius import helius_rotator

logger = logging.getLogger(__name__)
ADMIN_USER_ID = None


class CommandBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.admin_id = ADMIN_USER_ID
        self.application = None
        self.helius_url = "https://api.helius.xyz/v0"
        self.rotator = helius_rotator
        self._balance_cache: Dict[str, Tuple[float, datetime]] = {}

    async def start(self):
        self.application = Application.builder().token(self.token).build()
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
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)
        logger.info("Command bot started")

    async def stop(self):
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

    def _is_admin(self, user_id: int) -> bool:
        if self.admin_id is None:
            return False
        return user_id == self.admin_id

    def _is_private(self, update: Update) -> bool:
        return update.effective_chat.type == "private"

    def _get_setting(self, key: str, default: str = None) -> str:
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
        try:
            conn = get_connection()
            conn.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, value))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")

    async def cmd_register(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update):
            return
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        if self.admin_id is None:
            self.admin_id = user_id
            os.makedirs("data", exist_ok=True)
            with open("data/admin_id.txt", "w") as f:
                f.write(str(user_id))
            await update.message.reply_text(f"✅ Registered as Admin\n\nUser: @{username}\nID: `{user_id}`", parse_mode=ParseMode.MARKDOWN)
        elif self.admin_id == user_id:
            await update.message.reply_text("You're already registered as admin.")
        else:
            await update.message.reply_text("Admin already registered.")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update):
            return
        try:
            with open("data/admin_id.txt", "r") as f:
                self.admin_id = int(f.read().strip())
        except:
            pass
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("🔒 SoulWinners Admin Bot\n\nUse /register to claim admin access.", parse_mode=ParseMode.MARKDOWN)
            return
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
        count = cursor.fetchone()[0]
        conn.close()
        msg = f"""🚀 **SoulWinners Admin Panel**

• Status: 🟢 Online
• Wallets Monitored: {count}

**Commands:**
• /pool - Wallet leaderboard
• /stats - Pool statistics
• /cron - Cron job status
• /settings - Bot settings
• /trader - OpenClaw status
• /help - Full guide"""
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_pool(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        await update.message.reply_text("📊 Loading wallet data...")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT wallet_address, cluster_name, roi_pct, win_rate, current_balance_sol, tier, total_trades, roi_per_trade, trade_frequency FROM qualified_wallets ORDER BY priority_score DESC LIMIT 20")
        wallets = cursor.fetchall()
        conn.close()
        if not wallets:
            await update.message.reply_text("No qualified wallets in pool.")
            return
        msg = f"📊 **TOP WALLETS** ({len(wallets)})\n\n"
        for i, w in enumerate(wallets[:10], 1):
            addr, strategy, roi, wr, bal, tier, trades, rpt, freq = w
            wr = wr or 0
            roi = roi or 0
            bal = bal or 0
            trades = trades or 0
            rpt = rpt or 0
            avg_buy = bal / trades if trades > 0 else 1
            bes = (abs(rpt) * wr * (freq or 1)) / avg_buy if avg_buy > 0 else 0
            emoji = "🔥" if tier == "Elite" else "🟢"
            msg += f"{emoji} **#{i}** BES: {bes:,.0f}\n"
            msg += f"• Strategy: {strategy or 'Unknown'}\n"
            msg += f"• ROI: {roi:.0f}% | Win: {wr*100:.0f}%\n"
            msg += f"• Balance: {bal:.1f} SOL | Trades: {trades}\n"
            msg += f"• `{addr[:20]}...`\n\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_wallets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT wallet_address, cluster_name, roi_pct, win_rate, current_balance_sol, tier FROM qualified_wallets ORDER BY priority_score DESC")
        wallets = cursor.fetchall()
        conn.close()
        if not wallets:
            await update.message.reply_text("No qualified wallets.")
            return
        msg = f"👛 **WALLET ADDRESSES** ({len(wallets)})\n\n"
        for i, w in enumerate(wallets, 1):
            addr, strategy, roi, wr, bal, tier = w
            msg += f"**#{i}** {strategy or 'Unknown'}\n"
            msg += f"`{addr}`\n"
            msg += f"• ROI: {roi or 0:.0f}% | Win: {(wr or 0)*100:.0f}% | {bal or 0:.1f} SOL\n\n"
        if len(msg) > 4000:
            for i in range(0, len(msg), 4000):
                await update.message.reply_text(msg[i:i+4000], parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT wallet_address, cluster_name, roi_pct, win_rate, current_balance_sol, x10_ratio, total_trades, tier FROM qualified_wallets ORDER BY roi_pct DESC LIMIT 10")
        wallets = cursor.fetchall()
        conn.close()
        if not wallets:
            await update.message.reply_text("No qualified wallets.")
            return
        msg = "🏆 **TOP 10 BY ROI**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, w in enumerate(wallets, 1):
            addr, strategy, roi, wr, bal, x10, trades, tier = w
            medal = medals[i-1] if i <= 3 else f"#{i}"
            msg += f"{medal} **{tier}** - {strategy or 'Unknown'}\n"
            msg += f"• ROI: **{roi or 0:,.0f}%**\n"
            msg += f"• Win Rate: {(wr or 0)*100:.0f}%\n"
            msg += f"• Balance: {bal or 0:.1f} SOL\n"
            msg += f"• 10x Rate: {(x10 or 0)*100:.0f}%\n"
            msg += f"• `{addr[:20]}...`\n\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT tier, COUNT(*), AVG(roi_pct), AVG(win_rate) FROM qualified_wallets GROUP BY tier")
        tiers = cursor.fetchall()
        cursor.execute("SELECT cluster_name, COUNT(*) FROM qualified_wallets GROUP BY cluster_name")
        strategies = cursor.fetchall()
        cursor.execute("SELECT AVG(roi_pct), AVG(win_rate), AVG(current_balance_sol), SUM(current_balance_sol) FROM qualified_wallets")
        avgs = cursor.fetchone()
        conn.close()
        avg_roi, avg_wr, avg_bal, total_sol = avgs
        msg = f"""📈 **POOL STATISTICS**

**Overview**
• Total Wallets: {total}
• Total SOL Tracked: {total_sol or 0:,.0f} SOL
• Avg ROI: {avg_roi or 0:,.0f}%
• Avg Win Rate: {(avg_wr or 0)*100:.0f}%
• Avg Balance: {avg_bal or 0:.1f} SOL

**Tier Breakdown**
"""
        for tier, count, roi, wr in tiers:
            emoji = "🔥" if tier == "Elite" else "🟢" if tier == "High-Quality" else "🟡"
            msg += f"{emoji} {tier}: {count} (Avg ROI: {roi or 0:,.0f}%)\n"
        msg += "\n**Strategy Distribution**\n"
        for strat, count in strategies:
            msg += f"• {strat or 'Unknown'}: {count}\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def cmd_cron(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        cron_freq = int(self._get_setting('discovery_frequency_min', '10'))
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT started_at, completed_at, status, wallets_collected, wallets_qualified, wallets_added, error_message FROM pipeline_runs ORDER BY id DESC LIMIT 1")
        last_run = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
        total_wallets = cursor.fetchone()[0]
        cursor.execute("SELECT tier, COUNT(*) FROM qualified_wallets GROUP BY tier")
        tiers = cursor.fetchall()
        conn.close()
        now = datetime.now()
        next_run_min = cron_freq - (now.minute % cron_freq)
        if last_run:
            started, completed, status, collected, qualified, added, error = last_run
            last_run_time = started[:16] if started else "Never"
            duration = "N/A"
            if started and completed:
                try:
                    s = datetime.fromisoformat(started)
                    e = datetime.fromisoformat(completed)
                    dur = (e - s).total_seconds()
                    duration = f"{int(dur // 60)}m {int(dur % 60)}s"
                except:
                    pass
        else:
            last_run_time = "Never"
            collected = qualified = added = 0
            duration = "N/A"
            status = "unknown"
            error = None
        tier_text = ""
        for tier, count in tiers:
            pct = int(count / total_wallets * 100) if total_wallets > 0 else 0
            tier_text += f"• {tier}: {count} ({pct}%)\n"
        msg = f"""🔄 **CRON STATUS**

**Schedule**
• Frequency: Every {cron_freq} minutes
• Next Run: in {next_run_min}m
• Last Run: {last_run_time}

**Last Run Results**
• Wallets Scanned: {collected or 0}
• Passed Filters: {qualified or 0}
• Added to Pool: {added or 0}
• Duration: {duration}
• Status: {status or 'unknown'}

**Current Pool** ({total_wallets} wallets)
{tier_text}"""
        if error:
            msg += f"\n⚠️ Error: {error[:100]}"
        keyboard = [[InlineKeyboardButton("▶️ Run Now", callback_data="cron_run_now"), InlineKeyboardButton("🔄 Refresh", callback_data="refresh_cron")]]
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        alerts_on = self._get_setting('alerts_enabled', 'true') == 'true'
        monitor_on = self._get_setting('monitor_enabled', 'true') == 'true'
        min_buy = self._get_setting('min_buy_amount', '2.0')
        cron_freq = self._get_setting('discovery_frequency_min', '10')
        msg = f"""⚙️ **SETTINGS**

**Alerts**
• Status: {'🟢 ON' if alerts_on else '🔴 OFF'}
• Min Buy Amount: {min_buy} SOL
• Accumulation Window: 30 min

**Cron Job**
• Frequency: {cron_freq} min
• Auto-discovery: 🟢 ON

**Monitor**
• Status: {'🟢 ON' if monitor_on else '🔴 OFF'}

**Pool Filters**
• Min SOL: 10
• Min Trades: 15
• Min Win Rate: 60%
• Min ROI: 50%"""
        keyboard = [
            [InlineKeyboardButton(f"{'🔴 Disable' if alerts_on else '🟢 Enable'} Alerts", callback_data="toggle_alerts")],
            [InlineKeyboardButton("Min Buy +0.5", callback_data="min_buy_up"), InlineKeyboardButton("Min Buy -0.5", callback_data="min_buy_down")],
            [InlineKeyboardButton("Cron 10min", callback_data="cron_10"), InlineKeyboardButton("Cron 30min", callback_data="cron_30")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_settings")]
        ]
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        keyboard = [
            [InlineKeyboardButton("📡 Bot Logs", callback_data="logs_bot"), InlineKeyboardButton("🔄 Cron Logs", callback_data="logs_cron")],
            [InlineKeyboardButton("⚠️ Errors", callback_data="logs_errors")]
        ]
        await update.message.reply_text("📋 **SYSTEM LOGS**\n\nSelect log type:", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

    async def cmd_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        keyboard = [
            [InlineKeyboardButton("🤖 Restart Bot", callback_data="restart_bot")],
            [InlineKeyboardButton("🔄 Run Pipeline", callback_data="restart_pipeline")]
        ]
        await update.message.reply_text("🔧 **SYSTEM CONTROL**\n\n⚠️ Use with caution!", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

    async def cmd_trader(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return
        try:
            from trader.position_manager import PositionManager
            pm = PositionManager()
            stats = pm.get_stats()
            positions = pm.get_open_positions()
            progress = min(100, stats['progress_percent'])
            bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
            pos_text = ""
            if positions:
                for p in positions:
                    emoji = "🟢" if p.pnl_percent >= 0 else "🔴"
                    pos_text += f"\n{emoji} {p.token_symbol}: {p.pnl_percent:+.1f}%"
            else:
                pos_text = "\n• No open positions"
            msg = f"""🤖 **OPENCLAW TRADER**

**Portfolio**
• Starting: {stats['starting_balance']:.4f} SOL
• Current: {stats['current_balance']:.4f} SOL
• P&L: {stats['total_pnl_sol']:+.4f} SOL ({stats['total_pnl_percent']:+.1f}%)

**Performance**
• Trades: {stats['total_trades']}
• Win Rate: {stats['win_rate']:.1f}%

**Goal: $10,000**
• Progress: {progress:.1f}%
• [{bar}]

**Positions** ({stats['open_positions']}/3){pos_text}"""
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        except ImportError:
            await update.message.reply_text("🤖 **OPENCLAW**\n\n⚠️ Not installed yet.\n\nSet OPENCLAW_PRIVATE_KEY in .env", parse_mode=ParseMode.MARKDOWN)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_private(update):
            return
        msg = """📊 **SOULWINNERS GUIDE**

**Commands**
• /pool - Wallet leaderboard by BES
• /wallets - Full addresses with links
• /leaderboard - Top 10 by ROI
• /stats - Pool statistics
• /cron - Cron job status
• /settings - Bot settings
• /trader - OpenClaw status
• /logs - System logs
• /restart - Restart components

**Metrics**
• BES = (ROI × Win Rate × Frequency) / Avg Buy
• Higher BES = Better capital efficiency

**Alerts**
• Single buy ≥ 2 SOL
• Accumulation: Multiple buys totaling ≥ 2 SOL

**Pool Filters**
• SOL Balance ≥ 10
• Trades ≥ 15
• Win Rate ≥ 60%
• ROI ≥ 50%"""
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not self._is_admin(query.from_user.id):
            return
        data = query.data
        try:
            if data == "toggle_alerts":
                current = self._get_setting('alerts_enabled', 'true')
                new_val = 'false' if current == 'true' else 'true'
                self._set_setting('alerts_enabled', new_val)
                await query.edit_message_text(f"✅ Alerts {'enabled' if new_val == 'true' else 'disabled'}\n\nUse /settings to see all settings.")
            elif data == "min_buy_up":
                current = float(self._get_setting('min_buy_amount', '2.0'))
                self._set_setting('min_buy_amount', str(min(10.0, current + 0.5)))
                await query.edit_message_text(f"✅ Min buy: {min(10.0, current + 0.5)} SOL\n\nUse /settings")
            elif data == "min_buy_down":
                current = float(self._get_setting('min_buy_amount', '2.0'))
                self._set_setting('min_buy_amount', str(max(0.5, current - 0.5)))
                await query.edit_message_text(f"✅ Min buy: {max(0.5, current - 0.5)} SOL\n\nUse /settings")
            elif data == "cron_10":
                self._set_setting('discovery_frequency_min', '10')
                await query.edit_message_text("✅ Cron set to 10 minutes\n\nUse /settings")
            elif data == "cron_30":
                self._set_setting('discovery_frequency_min', '30')
                await query.edit_message_text("✅ Cron set to 30 minutes\n\nUse /settings")
            elif data == "refresh_settings":
                await query.message.delete()
                await self.cmd_settings(update, context)
            elif data == "cron_run_now":
                await query.edit_message_text("🔄 Starting pipeline...\n\nUse /cron to check status.")
                subprocess.Popen(["python3", "run_pipeline.py"], cwd="/root/Soulwinners", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif data == "refresh_cron":
                await query.message.delete()
                await self.cmd_cron(update, context)
            elif data == "logs_bot":
                await self._send_logs(query, "bot")
            elif data == "logs_cron":
                await self._send_logs(query, "cron")
            elif data == "logs_errors":
                await self._send_logs(query, "errors")
            elif data == "restart_bot":
                await query.edit_message_text("🔄 Restarting bot...")
                subprocess.Popen(["systemctl", "restart", "soulwinners"])
            elif data == "restart_pipeline":
                await query.edit_message_text("🔄 Running pipeline...")
                subprocess.Popen(["python3", "run_pipeline.py"], cwd="/root/Soulwinners", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Callback error: {e}")

    async def _send_logs(self, query, log_type: str):
        paths = {"bot": "logs/bot.log", "cron": "logs/cron.log", "errors": "logs/bot.log"}
        try:
            if log_type == "errors":
                result = subprocess.run(["grep", "-i", "error", paths[log_type]], capture_output=True, text=True, timeout=5, cwd="/root/Soulwinners")
                lines = result.stdout.strip().split('\n')[-15:]
            else:
                result = subprocess.run(["tail", "-20", paths[log_type]], capture_output=True, text=True, timeout=5, cwd="/root/Soulwinners")
                lines = result.stdout.strip().split('\n')
            content = '\n'.join(lines[-15:]) if lines and lines != [''] else "No logs found."
            if len(content) > 3500:
                content = content[-3500:]
            await query.edit_message_text(f"📋 **{log_type.upper()} LOGS**\n\n```\n{content}\n```", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.edit_message_text(f"Error: {e}")


async def run_command_bot():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    bot = CommandBot()
    try:
        await bot.start()
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(run_command_bot())
