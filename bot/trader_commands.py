"""
Auto-Trader Telegram Commands
User and Admin commands for OpenClaw trading bot
"""

import asyncio
import json
import logging
import sqlite3
import qrcode
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from telegram import Update, Bot, BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config.settings import TELEGRAM_BOT_TOKEN
from database import get_connection

logger = logging.getLogger(__name__)

# Admin user ID
ADMIN_USER_ID = 1153491543

# Database paths
SOULWINNERS_DB = Path(__file__).parent.parent / "data" / "soulwinners.db"
OPENCLAW_DB = Path(__file__).parent.parent / "data" / "openclaw.db"


async def update_user_menu(bot: Bot, user_id: int):
    """Set personalized command menu based on user role."""
    # Check if user is authorized
    is_admin = (user_id == ADMIN_USER_ID)
    is_authorized = False

    if not is_admin:
        try:
            conn = sqlite3.connect(SOULWINNERS_DB)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM authorized_users WHERE user_id = ? AND status = 'active'",
                (user_id,)
            )
            is_authorized = cursor.fetchone() is not None
            conn.close()
        except Exception as e:
            logger.error(f"Error checking authorization: {e}")

    # Define command lists by role
    if is_admin:
        commands = [
            BotCommand("start", "Welcome message"),
            BotCommand("help", "How to use"),
            BotCommand("deposit", "Get deposit wallet"),
            BotCommand("balance", "Check balance"),
            BotCommand("strategy", "Set trading strategy"),
            BotCommand("copylist", "View copy trading pool"),
            BotCommand("enable", "Enable wallet for copy trading"),
            BotCommand("disable", "Disable wallet"),
            BotCommand("positions", "View open positions"),
            BotCommand("history", "Trade history"),
            BotCommand("report", "AI strategy report"),
            BotCommand("withdraw", "Withdraw funds"),
            BotCommand("authorize", "Authorize user"),
            BotCommand("revoke", "Revoke user access"),
            BotCommand("authorized", "List authorized users"),
            BotCommand("users", "View all users"),
            BotCommand("fees", "View user fees"),
            BotCommand("totalfees", "Total fees collected"),
            BotCommand("transferfees", "Transfer fees to owner"),
            BotCommand("wallet", "Reveal full wallet address"),
        ]
    elif is_authorized:
        commands = [
            BotCommand("start", "Welcome message"),
            BotCommand("help", "How to use"),
            BotCommand("deposit", "Get deposit wallet"),
            BotCommand("balance", "Check balance"),
            BotCommand("strategy", "Set trading strategy"),
            BotCommand("copylist", "View copy trading pool"),
            BotCommand("enable", "Enable wallet for copy trading"),
            BotCommand("disable", "Disable wallet"),
            BotCommand("positions", "View open positions"),
            BotCommand("history", "Trade history"),
            BotCommand("report", "AI strategy report"),
            BotCommand("withdraw", "Withdraw funds"),
        ]
    else:
        commands = [
            BotCommand("start", "Welcome to SoulWinners"),
            BotCommand("help", "How it works"),
        ]

    # Set menu for this specific user
    try:
        scope = BotCommandScopeChat(chat_id=user_id)
        await bot.set_my_commands(commands, scope=scope)
        role = "admin" if is_admin else "authorized" if is_authorized else "default"
        logger.info(f"Set {role} menu for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to set menu for user {user_id}: {e}")


class TraderCommands:
    """Auto-trader Telegram commands."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN

    def _is_admin(self, user_id: int) -> bool:
        """Check if user is admin."""
        return user_id == ADMIN_USER_ID

    def _is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized for auto-trader access."""
        # Admin always has access
        if self._is_admin(user_id):
            return True

        # Check authorized_users table
        try:
            conn = sqlite3.connect(SOULWINNERS_DB)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status FROM authorized_users
                WHERE user_id = ? AND status = 'active'
            """, (user_id,))
            row = cursor.fetchone()
            conn.close()
            return row is not None
        except Exception as e:
            logger.error(f"Authorization check error: {e}")
            return False

    async def _check_auth(self, update: Update) -> bool:
        """Check authorization and send error if not authorized."""
        user_id = update.effective_user.id
        if not self._is_authorized(user_id):
            await update.message.reply_text(
                "🔒 **Access Denied**\n\n"
                "You are not authorized to use auto-trader features.\n"
                "Contact admin to request access.",
                parse_mode=ParseMode.MARKDOWN
            )
            return False
        return True

    def _init_trader_tables(self):
        """Initialize auto-trader specific tables."""
        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        # User strategies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_strategies (
                user_id INTEGER PRIMARY KEY,
                buy_amount_sol REAL DEFAULT 0.5,
                take_profit_pct REAL DEFAULT 50.0,
                stop_loss_pct REAL DEFAULT 10.0,
                max_trades_day INTEGER DEFAULT 20,
                auto_trade_enabled INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Copy pool table (wallets enabled for copy trading per user)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS copy_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                wallet_address TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, wallet_address)
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_copy_pool_user ON copy_pool(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_strategies_user ON user_strategies(user_id)")

        # Authorized users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id INTEGER PRIMARY KEY,
                authorized_by INTEGER NOT NULL,
                authorized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        """)

        conn.commit()
        conn.close()
        logger.info("Trader tables initialized")

    # =========================================================================
    # USER COMMANDS
    # =========================================================================

    async def cmd_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /deposit - Show user's deposit wallet address and QR code
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        try:
            from trader.wallet_manager import get_user_wallet, create_user_wallet

            # Get or create wallet
            wallet = get_user_wallet(user_id)
            if not wallet:
                wallet = create_user_wallet(user_id)

            address = wallet['deposit_address']

            # Generate QR code
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(address)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            # Convert to bytes
            bio = BytesIO()
            img.save(bio, format='PNG')
            bio.seek(0)

            caption = f"""💳 **Your Deposit Wallet**

📍 **Address:**
`{address}`

💰 **Current Balance:** {wallet.get('balance', 0):.4f} SOL

━━━━━━━━━━━━━━━━━━━━━
Send SOL to this address to fund your auto-trader.

Minimum deposit: 0.1 SOL
Funds available within ~30 seconds after confirmation.
"""

            await update.message.reply_photo(
                photo=bio,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Deposit command error: {e}")
            await update.message.reply_text(
                f"Error getting deposit address: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /balance - Check SOL balance in trading wallet
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        try:
            from trader.wallet_manager import get_user_wallet

            wallet = get_user_wallet(user_id)

            if not wallet:
                await update.message.reply_text(
                    "No wallet found. Use /deposit to create one.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            balance = wallet.get('balance', 0)
            address = wallet.get('deposit_address', 'Unknown')

            message = f"""💰 **Wallet Balance**

📍 Address: `{address[:12]}...{address[-8:]}`
💎 Balance: **{balance:.4f} SOL**

━━━━━━━━━━━━━━━━━━━━━
/deposit - Show deposit address
/withdraw - Withdraw funds
/fees - View fees paid
"""

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Balance command error: {e}")
            await update.message.reply_text(f"Error: {str(e)}")

    async def cmd_strategy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /strategy - View or edit trading strategy
        Usage: /strategy [buy_amount] [take_profit] [stop_loss] [max_trades]
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        # Check for arguments to update
        if context.args and len(context.args) >= 1:
            try:
                buy_amount = float(context.args[0]) if len(context.args) > 0 else 0.5
                take_profit = float(context.args[1]) if len(context.args) > 1 else 50.0
                stop_loss = float(context.args[2]) if len(context.args) > 2 else 10.0
                max_trades = int(context.args[3]) if len(context.args) > 3 else 20

                # Validate
                if buy_amount < 0.01 or buy_amount > 10:
                    await update.message.reply_text("Buy amount must be between 0.01 and 10 SOL")
                    return
                if take_profit < 10 or take_profit > 500:
                    await update.message.reply_text("Take profit must be between 10% and 500%")
                    return
                if stop_loss < 5 or stop_loss > 50:
                    await update.message.reply_text("Stop loss must be between 5% and 50%")
                    return
                if max_trades < 1 or max_trades > 100:
                    await update.message.reply_text("Max trades must be between 1 and 100")
                    return

                # Update strategy
                cursor.execute("""
                    INSERT OR REPLACE INTO user_strategies
                    (user_id, buy_amount_sol, take_profit_pct, stop_loss_pct, max_trades_day, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, buy_amount, take_profit, stop_loss, max_trades))
                conn.commit()

                await update.message.reply_text(
                    f"✅ **Strategy Updated**\n\n"
                    f"💰 Buy amount: {buy_amount} SOL\n"
                    f"📈 Take profit: +{take_profit}%\n"
                    f"📉 Stop loss: -{stop_loss}%\n"
                    f"🔢 Max trades/day: {max_trades}",
                    parse_mode=ParseMode.MARKDOWN
                )
                conn.close()
                return

            except ValueError:
                await update.message.reply_text(
                    "Invalid values. Use: /strategy [buy_amount] [take_profit] [stop_loss] [max_trades]\n"
                    "Example: /strategy 0.3 100 15 10"
                )
                conn.close()
                return

        # Get current strategy
        cursor.execute("""
            SELECT buy_amount_sol, take_profit_pct, stop_loss_pct, max_trades_day, auto_trade_enabled
            FROM user_strategies WHERE user_id = ?
        """, (user_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            buy_amount, take_profit, stop_loss, max_trades, auto_enabled = row
        else:
            buy_amount, take_profit, stop_loss, max_trades, auto_enabled = 0.5, 50.0, 10.0, 20, 0

        status = "🟢 ACTIVE" if auto_enabled else "🔴 PAUSED"

        message = f"""⚙️ **Current Strategy**

{status}

💰 Buy amount: **{buy_amount} SOL**
📈 Take profit: **+{take_profit}%**
📉 Stop loss: **-{stop_loss}%**
🔢 Max trades/day: **{max_trades}**

━━━━━━━━━━━━━━━━━━━━━
**Update strategy:**
`/strategy [buy] [tp] [sl] [max]`

Example: `/strategy 0.3 100 15 10`
"""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_copylist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /copylist - View wallets in copy pool
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT wallet_address, enabled, added_at
            FROM copy_pool
            WHERE user_id = ?
            ORDER BY added_at DESC
        """, (user_id,))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            # Try to migrate from watchlist
            message = """📋 **Copy Trading Pool**

No wallets in your copy pool yet.

**Add wallets:**
- Use /enable <wallet_address> to add a wallet
- Or reply to an alert with /enable

Your watchlist wallets can be migrated:
/migrate_watchlist
"""
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            return

        enabled_count = sum(1 for r in rows if r[1])
        message = f"📋 **Copy Trading Pool** ({enabled_count} active)\n\n"

        for addr, enabled, added_at in rows:
            status = "✅" if enabled else "❌"
            short_addr = f"{addr[:7]}...{addr[-5:]}"
            state = "[ACTIVE]" if enabled else "[PAUSED]"
            message += f"{status} `{short_addr}` {state}\n"

        message += f"""
━━━━━━━━━━━━━━━━━━━━━
/enable <wallet> - Activate wallet
/disable <wallet> - Pause wallet
"""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_enable(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /enable <wallet> - Enable wallet for copy trading
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        if not context.args:
            await update.message.reply_text(
                "Usage: /enable <wallet_address>\n"
                "Example: /enable 7BNaxx...S4s9j"
            )
            return

        wallet_input = context.args[0]

        # Try to find full address from partial
        wallet_address = await self._resolve_wallet_address(wallet_input)

        if not wallet_address:
            await update.message.reply_text(f"Wallet not found: {wallet_input}")
            return

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        # Insert or update
        cursor.execute("""
            INSERT INTO copy_pool (user_id, wallet_address, enabled)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, wallet_address) DO UPDATE SET enabled = 1
        """, (user_id, wallet_address))

        conn.commit()
        conn.close()

        short_addr = f"{wallet_address[:7]}...{wallet_address[-5:]}"
        await update.message.reply_text(
            f"✅ Wallet enabled for copy trading\n\n`{short_addr}`",
            parse_mode=ParseMode.MARKDOWN
        )

    async def cmd_disable(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /disable <wallet> - Disable wallet from copy trading
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        if not context.args:
            await update.message.reply_text(
                "Usage: /disable <wallet_address>\n"
                "Example: /disable 7BNaxx...S4s9j"
            )
            return

        wallet_input = context.args[0]
        wallet_address = await self._resolve_wallet_address(wallet_input)

        if not wallet_address:
            await update.message.reply_text(f"Wallet not found: {wallet_input}")
            return

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE copy_pool SET enabled = 0
            WHERE user_id = ? AND wallet_address = ?
        """, (user_id, wallet_address))

        if cursor.rowcount == 0:
            await update.message.reply_text(f"Wallet not in your copy pool: {wallet_input}")
        else:
            short_addr = f"{wallet_address[:7]}...{wallet_address[-5:]}"
            await update.message.reply_text(
                f"❌ Wallet disabled from copy trading\n\n`{short_addr}`",
                parse_mode=ParseMode.MARKDOWN
            )

        conn.commit()
        conn.close()

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /positions - View open trading positions
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        if not OPENCLAW_DB.exists():
            await update.message.reply_text("No trading data found.")
            return

        conn = sqlite3.connect(OPENCLAW_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT token_symbol, token_mint, entry_sol, current_value_sol,
                   pnl_percent, pnl_sol, status, entry_time
            FROM positions
            WHERE status IN ('open', 'partial')
            ORDER BY entry_time DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text(
                "📊 **Open Positions**\n\nNo open positions.\n\n/history - View trade history",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        message = f"📊 **Open Positions** ({len(rows)})\n\n"

        for symbol, mint, entry, current, pnl_pct, pnl_sol, status, entry_time in rows:
            emoji = "🟢" if pnl_pct >= 0 else "🔴"
            status_str = "PARTIAL" if status == "partial" else "OPEN"

            message += f"""{emoji} **{symbol}** [{status_str}]
├ Entry: {entry:.4f} SOL
├ Current: {current:.4f} SOL
├ P&L: {pnl_pct:+.1f}% ({pnl_sol:+.4f} SOL)
└ [Chart](https://dexscreener.com/solana/{mint})

"""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /history - View trade history (last 10 trades)
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        if not OPENCLAW_DB.exists():
            await update.message.reply_text("No trading data found.")
            return

        conn = sqlite3.connect(OPENCLAW_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT token_symbol, trade_type, sol_amount, pnl_sol, pnl_percent, timestamp
            FROM trade_history
            WHERE trade_type != 'entry'
            ORDER BY timestamp DESC
            LIMIT 10
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text(
                "📜 **Trade History**\n\nNo trades yet.\n\nStart trading with /strategy",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        message = "📜 **Trade History** (Last 10)\n\n"

        total_pnl = 0
        wins = 0
        losses = 0

        for symbol, trade_type, sol, pnl_sol, pnl_pct, ts in rows:
            emoji = "🟢" if pnl_sol >= 0 else "🔴"
            type_str = trade_type.upper()

            if pnl_sol >= 0:
                wins += 1
            else:
                losses += 1
            total_pnl += pnl_sol

            # Parse timestamp
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%m/%d %H:%M")
            except:
                time_str = ts[:10] if ts else "Unknown"

            message += f"{emoji} **{symbol}** | {type_str}\n"
            message += f"   {sol:.4f} SOL | {pnl_pct:+.1f}% | {time_str}\n"

        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

        message += f"""
━━━━━━━━━━━━━━━━━━━━━
{pnl_emoji} Total P&L: **{total_pnl:+.4f} SOL**
📊 Win Rate: **{win_rate:.0f}%** ({wins}W / {losses}L)
"""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_fees(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /fees <user_id> - View fees for a specific user (ADMIN ONLY)
        """
        admin_id = update.effective_user.id

        if not self._is_admin(admin_id):
            await update.message.reply_text("Admin only command.")
            return

        # Get target user (self or specified)
        if context.args:
            try:
                target_user_id = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Invalid user ID.")
                return
        else:
            target_user_id = admin_id

        try:
            from trader.fee_collector import get_user_fees

            fees = get_user_fees(target_user_id)

            message = f"""💸 **Trading Fees** (User {target_user_id})

📊 Total trades: **{fees['total_trades']}**
💰 Total fees paid: **{fees['total_fees_sol']:.4f} SOL**

━━━━━━━━━━━━━━━━━━━━━
Fee per trade: 0.01 SOL
First trade: {fees['first_fee_at'] or 'N/A'}
Last trade: {fees['last_fee_at'] or 'N/A'}
"""

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Fees command error: {e}")
            await update.message.reply_text(f"Error: {str(e)}")

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /report - Get latest AI strategy report or request new one
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        try:
            from trader.ai_advisor import get_report_history, generate_report, send_report_to_user

            # Check for existing reports
            reports = get_report_history(user_id, limit=1)

            if context.args and context.args[0].lower() == 'new':
                # Generate new report
                await update.message.reply_text(
                    "🤖 Generating AI report... This may take a moment.",
                    parse_mode=ParseMode.MARKDOWN
                )

                report = generate_report(user_id, days=3)

                if report.get('success'):
                    result = await send_report_to_user(user_id, report, self.token)
                    if not result.get('success'):
                        await update.message.reply_text(f"Report generated but failed to send: {result.get('error')}")
                else:
                    await update.message.reply_text(f"Failed to generate report: {report.get('error')}")
                return

            if reports:
                # Send last report info
                last_report = reports[0]
                stats = last_report.get('stats', {})

                message = f"""📊 **Latest AI Report**

Generated: {last_report['created_at']}

📈 **Stats from report:**
├ Trades: {stats.get('total_trades', 0)}
├ Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}
├ Win Rate: {stats.get('win_rate', 0):.1f}%
└ P&L: {stats.get('total_pnl_sol', 0):+.4f} SOL

━━━━━━━━━━━━━━━━━━━━━
/report new - Generate fresh report
"""
                await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(
                    "No reports yet.\n\nUse `/report new` to generate your first AI strategy report.",
                    parse_mode=ParseMode.MARKDOWN
                )

        except Exception as e:
            logger.error(f"Report command error: {e}")
            await update.message.reply_text(f"Error: {str(e)}")

    async def cmd_withdraw(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /withdraw <amount> <address> - Withdraw SOL from trading wallet
        """
        if not await self._check_auth(update):
            return

        user_id = update.effective_user.id

        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /withdraw <amount> <destination_address>\n\n"
                "Example: /withdraw 0.5 8yYWQT2mNdadVgPefGtbo14ofZp1cqjS5AEDD6jdqfhX"
            )
            return

        try:
            amount = float(context.args[0])
            destination = context.args[1]

            # Validate amount
            if amount < 0.01:
                await update.message.reply_text("Minimum withdrawal: 0.01 SOL")
                return

            # Validate address (basic check)
            if len(destination) < 32 or len(destination) > 44:
                await update.message.reply_text("Invalid Solana address")
                return

            from trader.wallet_manager import get_user_wallet

            wallet = get_user_wallet(user_id)
            if not wallet:
                await update.message.reply_text("No wallet found. Use /deposit first.")
                return

            balance = wallet.get('balance', 0)
            if amount > balance - 0.001:  # Keep some for fees
                await update.message.reply_text(
                    f"Insufficient balance.\n"
                    f"Available: {balance:.4f} SOL\n"
                    f"Requested: {amount:.4f} SOL"
                )
                return

            # Show confirmation
            short_dest = f"{destination[:8]}...{destination[-6:]}"
            message = f"""⚠️ **Confirm Withdrawal**

Amount: **{amount:.4f} SOL**
To: `{short_dest}`
Fee: ~0.000005 SOL

Reply with /confirm_withdraw to proceed.
"""

            # Store pending withdrawal in context
            context.user_data['pending_withdraw'] = {
                'amount': amount,
                'destination': destination,
                'timestamp': datetime.now().isoformat()
            }

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except ValueError:
            await update.message.reply_text("Invalid amount. Use a number like: 0.5")

    # =========================================================================
    # ADMIN COMMANDS
    # =========================================================================

    async def cmd_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /users - List all users with balances (ADMIN ONLY)
        """
        user_id = update.effective_user.id

        if not self._is_admin(user_id):
            await update.message.reply_text("Admin only command.")
            return

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, deposit_address, balance_sol, created_at
            FROM user_wallets
            ORDER BY balance_sol DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("No users yet.")
            return

        total_balance = sum(r[2] for r in rows)
        message = f"👥 **All Users** ({len(rows)})\n\n"

        for uid, addr, balance, created in rows:
            short_addr = f"{addr[:8]}...{addr[-6:]}"
            message += f"• User `{uid}`\n"
            message += f"  {short_addr} | {balance:.4f} SOL\n"

        message += f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"💰 Total Balance: **{total_balance:.4f} SOL**"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_totalfees(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /totalfees - View all fees collected (ADMIN ONLY)
        """
        user_id = update.effective_user.id

        if not self._is_admin(user_id):
            await update.message.reply_text("Admin only command.")
            return

        try:
            from trader.fee_collector import get_total_fees, get_pending_fees

            stats = get_total_fees()
            pending = get_pending_fees()

            message = f"""💰 **Fee Collection Stats**

📊 **Totals:**
├ Total trades: {stats['total_trades']}
├ Unique users: {stats['unique_users']}
├ Total collected: **{stats['total_collected_sol']:.4f} SOL**
├ Total transferred: {stats['total_transferred_sol']:.4f} SOL
└ Pending transfer: **{pending:.4f} SOL**

━━━━━━━━━━━━━━━━━━━━━
/transferfees - Transfer pending to owner
"""

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Totalfees command error: {e}")
            await update.message.reply_text(f"Error: {str(e)}")

    async def cmd_transferfees(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /transferfees - Manually trigger fee transfer to owner wallet (ADMIN ONLY)
        """
        user_id = update.effective_user.id

        if not self._is_admin(user_id):
            await update.message.reply_text("Admin only command.")
            return

        try:
            from trader.fee_collector import send_to_owner, get_pending_fees

            pending = get_pending_fees()

            if pending < 0.01:
                await update.message.reply_text(
                    f"Pending fees too small: {pending:.4f} SOL\n"
                    f"Minimum transfer: 0.01 SOL"
                )
                return

            await update.message.reply_text(
                f"💸 Transferring {pending:.4f} SOL to owner wallet...",
                parse_mode=ParseMode.MARKDOWN
            )

            result = await send_to_owner()

            if result.get('success'):
                await update.message.reply_text(
                    f"✅ **Transfer Successful**\n\n"
                    f"Amount: {result['amount_sol']:.4f} SOL\n"
                    f"TX: `{result['signature'][:20]}...`\n"
                    f"To: `{result['owner_wallet'][:12]}...`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(f"❌ Transfer failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Transferfees command error: {e}")
            await update.message.reply_text(f"Error: {str(e)}")

    async def cmd_authorize(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /authorize <user_id> - Grant auto-trader access to user (ADMIN ONLY)
        """
        admin_id = update.effective_user.id

        if not self._is_admin(admin_id):
            await update.message.reply_text("Admin only command.")
            return

        if not context.args:
            await update.message.reply_text(
                "Usage: /authorize <user_id>\n"
                "Example: /authorize 987654321"
            )
            return

        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID. Must be a number.")
            return

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        # Check if already authorized
        cursor.execute("""
            SELECT status FROM authorized_users WHERE user_id = ?
        """, (target_user_id,))
        row = cursor.fetchone()

        if row and row[0] == 'active':
            await update.message.reply_text(f"User {target_user_id} is already authorized.")
            conn.close()
            return

        # Authorize user
        cursor.execute("""
            INSERT INTO authorized_users (user_id, authorized_by, status)
            VALUES (?, ?, 'active')
            ON CONFLICT(user_id) DO UPDATE SET
                status = 'active',
                authorized_by = ?,
                authorized_at = CURRENT_TIMESTAMP
        """, (target_user_id, admin_id, admin_id))

        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ **User Authorized**\n\n"
            f"User ID: `{target_user_id}`\n"
            f"Status: Active\n\n"
            f"They can now use auto-trader commands.\n"
            f"Their menu has been updated.",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"User {target_user_id} authorized by admin {admin_id}")

        # Update the user's command menu
        try:
            bot = Bot(token=self.token)
            await update_user_menu(bot, target_user_id)
        except Exception as e:
            logger.error(f"Failed to update menu for authorized user: {e}")

    async def cmd_revoke(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /revoke <user_id> - Remove auto-trader access from user (ADMIN ONLY)
        """
        admin_id = update.effective_user.id

        if not self._is_admin(admin_id):
            await update.message.reply_text("Admin only command.")
            return

        if not context.args:
            await update.message.reply_text(
                "Usage: /revoke <user_id>\n"
                "Example: /revoke 987654321"
            )
            return

        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID. Must be a number.")
            return

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE authorized_users
            SET status = 'revoked'
            WHERE user_id = ?
        """, (target_user_id,))

        if cursor.rowcount == 0:
            await update.message.reply_text(f"User {target_user_id} was not authorized.")
        else:
            await update.message.reply_text(
                f"❌ **Access Revoked**\n\n"
                f"User ID: `{target_user_id}`\n"
                f"Status: Revoked\n\n"
                f"They can no longer use auto-trader commands.\n"
                f"Their menu has been reset.",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"User {target_user_id} access revoked by admin {admin_id}")

            # Update the user's command menu to default
            try:
                bot = Bot(token=self.token)
                await update_user_menu(bot, target_user_id)
            except Exception as e:
                logger.error(f"Failed to update menu for revoked user: {e}")

        conn.commit()
        conn.close()

    async def cmd_authorized(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /authorized - View list of authorized users (ADMIN ONLY)
        """
        admin_id = update.effective_user.id

        if not self._is_admin(admin_id):
            await update.message.reply_text("Admin only command.")
            return

        conn = sqlite3.connect(SOULWINNERS_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, authorized_by, authorized_at, status
            FROM authorized_users
            ORDER BY authorized_at DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text(
                "👥 **Authorized Users**\n\n"
                "No users authorized yet.\n\n"
                "/authorize <user_id> - Grant access",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        active_count = sum(1 for r in rows if r[3] == 'active')
        message = f"👥 **Authorized Users** ({active_count} active)\n\n"

        for uid, auth_by, auth_at, status in rows:
            emoji = "✅" if status == 'active' else "❌"
            status_str = status.upper()

            # Parse timestamp
            try:
                dt = datetime.fromisoformat(auth_at)
                date_str = dt.strftime("%Y-%m-%d")
            except:
                date_str = str(auth_at)[:10] if auth_at else "Unknown"

            message += f"{emoji} `{uid}` [{status_str}]\n"
            message += f"   Added: {date_str}\n"

        message += f"""
━━━━━━━━━━━━━━━━━━━━━
/authorize <user_id> - Grant access
/revoke <user_id> - Remove access
"""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    async def _resolve_wallet_address(self, wallet_input: str) -> Optional[str]:
        """
        Resolve partial wallet address to full address.
        Searches qualified_wallets and watchlists.
        """
        # If already looks like a full address
        if len(wallet_input) >= 32:
            return wallet_input

        # Search in qualified_wallets
        conn = get_connection()
        cursor = conn.cursor()

        # Try prefix match
        cursor.execute("""
            SELECT wallet_address FROM qualified_wallets
            WHERE wallet_address LIKE ? LIMIT 1
        """, (f"{wallet_input}%",))

        row = cursor.fetchone()
        if row:
            conn.close()
            return row[0]

        # Try suffix match
        cursor.execute("""
            SELECT wallet_address FROM qualified_wallets
            WHERE wallet_address LIKE ? LIMIT 1
        """, (f"%{wallet_input}",))

        row = cursor.fetchone()
        conn.close()

        if row:
            return row[0]

        return None


# Initialize
trader_commands = TraderCommands()


def register_trader_commands(application):
    """Register all trader commands with the bot application."""
    from telegram.ext import CommandHandler

    tc = trader_commands
    tc._init_trader_tables()

    # User commands (authorized users)
    application.add_handler(CommandHandler("deposit", tc.cmd_deposit))
    application.add_handler(CommandHandler("balance", tc.cmd_balance))
    application.add_handler(CommandHandler("strategy", tc.cmd_strategy))
    application.add_handler(CommandHandler("copylist", tc.cmd_copylist))
    application.add_handler(CommandHandler("enable", tc.cmd_enable))
    application.add_handler(CommandHandler("disable", tc.cmd_disable))
    application.add_handler(CommandHandler("positions", tc.cmd_positions))
    application.add_handler(CommandHandler("history", tc.cmd_history))
    application.add_handler(CommandHandler("report", tc.cmd_report))
    application.add_handler(CommandHandler("withdraw", tc.cmd_withdraw))

    # Admin-only commands
    application.add_handler(CommandHandler("users", tc.cmd_users))
    application.add_handler(CommandHandler("fees", tc.cmd_fees))
    application.add_handler(CommandHandler("totalfees", tc.cmd_totalfees))
    application.add_handler(CommandHandler("transferfees", tc.cmd_transferfees))
    application.add_handler(CommandHandler("authorize", tc.cmd_authorize))
    application.add_handler(CommandHandler("revoke", tc.cmd_revoke))
    application.add_handler(CommandHandler("authorized", tc.cmd_authorized))

    logger.info("Registered 17 trader commands")
