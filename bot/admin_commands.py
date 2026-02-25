"""
Private Admin Commands
Only accessible by the channel owner
"""
import asyncio
from datetime import datetime
from typing import List, Dict
from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import get_connection
from config.settings import TELEGRAM_BOT_TOKEN

# YOUR TELEGRAM USER ID - Only you can use admin commands
ADMIN_USER_ID = None  # Will be set on first /register command


class AdminCommands:
    """Private admin commands for wallet management."""

    def __init__(self):
        self.admin_id = ADMIN_USER_ID
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin."""
        return self.admin_id and user_id == self.admin_id

    async def register_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /register - Register yourself as admin (first user only)
        """
        global ADMIN_USER_ID

        user_id = update.effective_user.id
        username = update.effective_user.username

        if ADMIN_USER_ID is None:
            ADMIN_USER_ID = user_id
            self.admin_id = user_id

            # Save to database
            conn = get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute(
                "INSERT OR REPLACE INTO admin_config (key, value) VALUES (?, ?)",
                ("admin_user_id", str(user_id))
            )
            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"✅ Registered as admin!\n\n"
                f"User ID: `{user_id}`\n"
                f"Username: @{username}\n\n"
                f"You now have access to private commands:\n"
                f"/wallets - View all qualified wallets\n"
                f"/leaderboard - Top performers\n"
                f"/wallet <address> - Wallet details\n"
                f"/addwallet <address> - Add wallet manually\n"
                f"/removewallet <address> - Remove wallet\n"
                f"/refresh - Run pipeline manually",
                parse_mode=ParseMode.MARKDOWN
            )
        elif user_id == ADMIN_USER_ID:
            await update.message.reply_text("✅ You are already the admin!")
        else:
            await update.message.reply_text("❌ Admin already registered.")

    async def cmd_wallets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /wallets - List all qualified wallets with full addresses (PRIVATE)
        """
        if not self.is_admin(update.effective_user.id):
            return

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wallet_address, tier, cluster_name, priority_score,
                   current_balance_sol, profit_token_ratio, roi_pct
            FROM qualified_wallets
            ORDER BY priority_score DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text(
                "📭 No qualified wallets yet.\n\n"
                "Run /refresh to collect wallets.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        message = "👛 **QUALIFIED WALLETS (PRIVATE)**\n\n"

        for i, row in enumerate(rows, 1):
            addr, tier, strategy, score, balance, win_rate, roi = row
            tier_emoji = {'Elite': '🔥', 'High-Quality': '🟢', 'Mid-Tier': '🟡'}.get(tier, '⚪')

            message += f"{i}. {tier_emoji} **{tier}**\n"
            message += f"   `{addr}`\n"
            message += f"   {strategy or 'Unknown'}\n"
            message += f"   💰 {balance:.1f} SOL | WR: {win_rate:.0%} | ROI: {roi:.0f}%\n\n"

            # Split message if too long
            if len(message) > 3500:
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
                message = ""

        if message:
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /leaderboard - Top performing wallets (PRIVATE)
        """
        if not self.is_admin(update.effective_user.id):
            return

        conn = get_connection()
        cursor = conn.cursor()

        # By ROI
        cursor.execute("""
            SELECT wallet_address, tier, roi_pct, profit_token_ratio
            FROM qualified_wallets
            ORDER BY roi_pct DESC
            LIMIT 10
        """)
        by_roi = cursor.fetchall()

        # By Win Rate
        cursor.execute("""
            SELECT wallet_address, tier, roi_pct, profit_token_ratio
            FROM qualified_wallets
            ORDER BY profit_token_ratio DESC
            LIMIT 10
        """)
        by_winrate = cursor.fetchall()

        # By Balance
        cursor.execute("""
            SELECT wallet_address, tier, current_balance_sol
            FROM qualified_wallets
            ORDER BY current_balance_sol DESC
            LIMIT 10
        """)
        by_balance = cursor.fetchall()

        conn.close()

        message = "🏆 **LEADERBOARD (PRIVATE)**\n\n"

        message += "📈 **TOP ROI:**\n"
        for i, (addr, tier, roi, wr) in enumerate(by_roi[:5], 1):
            message += f"{i}. `{addr[:15]}...` {roi:.0f}%\n"

        message += "\n🎯 **TOP WIN RATE:**\n"
        for i, (addr, tier, roi, wr) in enumerate(by_winrate[:5], 1):
            message += f"{i}. `{addr[:15]}...` {wr:.0%}\n"

        message += "\n💰 **HIGHEST BALANCE:**\n"
        for i, (addr, tier, bal) in enumerate(by_balance[:5], 1):
            message += f"{i}. `{addr[:15]}...` {bal:.1f} SOL\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_wallet_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /wallet <address> - Get full details of a specific wallet (PRIVATE)
        """
        if not self.is_admin(update.effective_user.id):
            return

        if not context.args:
            await update.message.reply_text("Usage: /wallet <address>")
            return

        address = context.args[0]

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM qualified_wallets WHERE wallet_address = ?",
            (address,)
        )
        row = cursor.fetchone()

        if not row:
            # Try partial match
            cursor.execute(
                "SELECT * FROM qualified_wallets WHERE wallet_address LIKE ?",
                (f"{address}%",)
            )
            row = cursor.fetchone()

        conn.close()

        if not row:
            await update.message.reply_text(f"❌ Wallet not found: {address[:20]}...")
            return

        columns = [
            'wallet_address', 'source', 'roi_pct', 'median_roi_pct',
            'profit_token_ratio', 'trade_frequency', 'roi_per_trade',
            'x10_ratio', 'x20_ratio', 'x50_ratio', 'x100_ratio',
            'median_hold_time', 'profit_per_hold_second',
            'cluster', 'cluster_label', 'cluster_name',
            'roi_final', 'priority_score', 'tier', 'strategy_bucket',
            'current_balance_sol', 'total_trades', 'win_rate',
            'qualified_at', 'last_alert_at'
        ]

        wallet = dict(zip(columns, row))

        message = f"""
👛 **WALLET DETAILS (PRIVATE)**

📍 **Address:**
`{wallet['wallet_address']}`

🏷 **Classification:**
├ Tier: {wallet['tier']}
├ Strategy: {wallet['cluster_name']}
├ Cluster: {wallet['cluster']}
└ Source: {wallet['source']}

📊 **Performance:**
├ ROI: {wallet['roi_pct']:.1f}%
├ Win Rate: {wallet['profit_token_ratio']:.1%}
├ ROI/Trade: {wallet['roi_per_trade']:.2f}%
└ Trade Freq: {wallet['trade_frequency']:.2f}/day

🎰 **Multi-baggers:**
├ 10x+: {wallet['x10_ratio']:.1%}
├ 20x+: {wallet['x20_ratio']:.1%}
├ 50x+: {wallet['x50_ratio']:.1%}
└ 100x+: {wallet['x100_ratio']:.1%}

💰 **Current:**
├ Balance: {wallet['current_balance_sol']:.2f} SOL
├ Total Trades: {wallet['total_trades']}
└ Priority Score: {wallet['priority_score']:.4f}

🔗 **Links:**
[Solscan](https://solscan.io/account/{wallet['wallet_address']}) | [Birdeye](https://birdeye.so/profile/{wallet['wallet_address']}?chain=solana)

📅 Qualified: {wallet['qualified_at'] or 'Unknown'}
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_pool_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /pool - Pool statistics (PRIVATE)
        """
        if not self.is_admin(update.effective_user.id):
            return

        conn = get_connection()
        cursor = conn.cursor()

        # Total qualified
        cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
        total = cursor.fetchone()[0]

        # By tier
        cursor.execute("""
            SELECT tier, COUNT(*), AVG(current_balance_sol), AVG(roi_pct), AVG(profit_token_ratio)
            FROM qualified_wallets
            GROUP BY tier
        """)
        tiers = cursor.fetchall()

        # By source
        cursor.execute("""
            SELECT source, COUNT(*)
            FROM qualified_wallets
            GROUP BY source
        """)
        sources = cursor.fetchall()

        # By strategy
        cursor.execute("""
            SELECT cluster_name, COUNT(*)
            FROM qualified_wallets
            GROUP BY cluster_name
        """)
        strategies = cursor.fetchall()

        conn.close()

        message = f"""
📊 **POOL STATISTICS (PRIVATE)**

👛 **Total Qualified:** {total}

🏆 **By Tier:**
"""
        for tier, count, avg_bal, avg_roi, avg_wr in tiers:
            emoji = {'Elite': '🔥', 'High-Quality': '🟢', 'Mid-Tier': '🟡'}.get(tier, '⚪')
            message += f"{emoji} {tier}: {count} (avg {avg_bal:.0f} SOL, {avg_roi:.0f}% ROI)\n"

        message += "\n📦 **By Source:**\n"
        for source, count in sources:
            message += f"• {source}: {count}\n"

        message += "\n🎯 **By Strategy:**\n"
        for strategy, count in strategies:
            message += f"• {strategy or 'Unknown'}: {count}\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


# Initialize admin commands
admin = AdminCommands()


def load_admin_id():
    """Load admin ID from database on startup."""
    global ADMIN_USER_ID
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM admin_config WHERE key = 'admin_user_id'")
        row = cursor.fetchone()
        conn.close()
        if row:
            ADMIN_USER_ID = int(row[0])
            admin.admin_id = ADMIN_USER_ID
    except:
        pass
