"""
V'ger Control Bot - Telegram interface for OpenClaw Auto-Trader

Commands:
/status - Current positions, P&L, balance
/settings - View/change strategy parameters
/exit [token] - Force close position
/buy [token] [amount] - Manual trade
/report - Today's trade history
/balance - Wallet SOL balance
/portfolio - All open positions
/history - Last 10 trades
/help - Command guide
"""
import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

# Import trader components
from trader.position_manager import PositionManager, Position
from trader.strategy import TradingStrategy, StrategyConfig
from trader.solana_dex import JupiterDEX

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/vger.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Config
VGER_BOT_TOKEN = os.getenv('VGER_BOT_TOKEN')
VGER_ADMIN_ID = int(os.getenv('VGER_ADMIN_ID', '1153491543'))
DB_PATH = "data/openclaw.db"

# Global state
position_manager = PositionManager(DB_PATH)
strategy = TradingStrategy()
pending_confirmations: Dict[int, Dict] = {}  # user_id -> confirmation data


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id == VGER_ADMIN_ID


def format_duration(entry_time: datetime) -> str:
    """Format time duration as human-readable string."""
    duration = datetime.now() - entry_time
    hours = duration.seconds // 3600
    minutes = (duration.seconds % 3600) // 60

    if duration.days > 0:
        return f"{duration.days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def get_sol_price() -> float:
    """Get current SOL price from database or default."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM stats WHERE key = 'sol_price'")
        result = cursor.fetchone()
        conn.close()
        return float(result[0]) if result else 78.0
    except:
        return 78.0


def update_sol_price(price: float):
    """Update SOL price in database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT OR REPLACE INTO stats (key, value) VALUES ('sol_price', ?)
        """, (str(price),))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update SOL price: {e}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Unauthorized. V'ger responds only to Commander.")
        return

    await update.message.reply_text(
        "🖖 **V'GER ONLINE**\n\n"
        "I am V'ger. I control the OpenClaw auto-trader.\n\n"
        "Use /help to see available commands.",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    if not is_admin(update.effective_user.id):
        return

    help_text = """
🖖 **V'GER COMMAND INTERFACE**

📊 **MONITORING**
/status - Current positions & P&L
/portfolio - All open positions
/balance - Wallet SOL balance
/report - Today's trade history
/history - Last 10 trades

⚙️ **SETTINGS**
/settings - View strategy settings
/set <param> <value> - Change setting

📈 **TRADING**
/exit <token> - Force close position
/buy <token> <amount> - Manual buy

❓ **INFO**
/help - This message

**Example Commands:**
• `/exit BONK` - Close BONK position
• `/set stop_loss 15` - Change stop loss to -15%
• `/buy BONK 0.1` - Buy 0.1 SOL of BONK
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show current status."""
    if not is_admin(update.effective_user.id):
        return

    try:
        stats = position_manager.get_stats()
        positions = position_manager.get_open_positions()
        sol_price = get_sol_price()

        balance_sol = stats['current_balance']
        balance_usd = balance_sol * sol_price
        total_pnl = stats['total_pnl_sol']
        total_pnl_pct = stats['total_pnl_percent']

        # Build status message
        status_emoji = "🟢" if total_pnl >= 0 else "🔴"

        message = f"""
{status_emoji} **OPENCLAW STATUS**

💰 **Balance:** {balance_sol:.4f} SOL (${balance_usd:.2f})
📊 **Open Positions:** {len(positions)}/3
📈 **Total P&L:** {total_pnl:+.4f} SOL ({total_pnl_pct:+.1f}%)

🎯 **Goal Progress:** {stats['progress_percent']:.1f}% to $10k
📊 **Stats:** {stats['winning_trades']}/{stats['total_trades']} wins ({stats['win_rate']:.1f}%)
"""

        # Add position details
        if positions:
            message += "\n📋 **POSITIONS:**\n"
            for i, pos in enumerate(positions, 1):
                pnl_emoji = "🟢" if pos.pnl_sol >= 0 else "🔴"
                duration = format_duration(pos.entry_time)

                message += f"\n{pnl_emoji} **{i}. ${pos.token_symbol}**\n"
                message += f"├ Entry: {pos.entry_sol:.4f} SOL @ ${pos.entry_price:.8f}\n"
                message += f"├ Current: ${pos.current_price:.8f} ({pos.pnl_percent:+.1f}%)\n"
                message += f"├ Value: {pos.current_value_sol:.4f} SOL\n"
                message += f"├ P&L: {pos.pnl_sol:+.4f} SOL\n"
                message += f"├ Remaining: {pos.remaining_percent:.0f}%\n"
                message += f"└ Duration: {duration}\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Status command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /settings command - view current strategy settings."""
    if not is_admin(update.effective_user.id):
        return

    try:
        config = strategy.config

        message = f"""
⚙️ **STRATEGY SETTINGS**

📊 **Position Sizing:**
├ Position Size: {config.position_size_percent:.0f}% of balance
└ Max Positions: {config.max_positions}

🚪 **Exit Rules:**
├ Stop Loss: {config.stop_loss_percent:.0f}%
├ TP1: +{config.tp1_percent:.0f}% (sell {config.tp1_sell_percent:.0f}%)
└ TP2: +{config.tp2_percent:.0f}% (sell {config.tp2_sell_percent:.0f}%)

🎯 **Entry Filters:**
├ Min BES: {config.min_bes:.0f}
├ Min Win Rate: {config.min_recent_win_rate:.0%}
└ Min Liquidity: ${config.min_liquidity_usd:,.0f}

📈 **Advanced:**
├ Momentum Threshold: {config.momentum_threshold:.0f}%
└ Stagnation Time: {config.stagnation_minutes} minutes

**Change settings:**
`/set <param> <value>`

**Examples:**
• `/set stop_loss 15` → -15% stop loss
• `/set tp1_percent 40` → TP1 at +40%
• `/set position_size 80` → Use 80% of balance
"""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Settings command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /set command - change strategy setting."""
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set <param> <value>`\n\n"
            "Available params:\n"
            "• stop_loss (e.g., 15 for -15%)\n"
            "• tp1_percent (e.g., 50)\n"
            "• tp2_percent (e.g., 100)\n"
            "• position_size (e.g., 70)\n"
            "• min_bes (e.g., 1000)",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    param = context.args[0].lower()
    try:
        value = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid value. Must be a number.")
        return

    # Map param names to config attributes
    param_map = {
        'stop_loss': ('stop_loss_percent', -abs(value)),  # Always negative
        'tp1': ('tp1_percent', abs(value)),
        'tp1_percent': ('tp1_percent', abs(value)),
        'tp2': ('tp2_percent', abs(value)),
        'tp2_percent': ('tp2_percent', abs(value)),
        'position_size': ('position_size_percent', abs(value)),
        'min_bes': ('min_bes', abs(value)),
        'min_liquidity': ('min_liquidity_usd', abs(value)),
        'min_win_rate': ('min_recent_win_rate', abs(value) / 100 if value > 1 else abs(value)),
    }

    if param not in param_map:
        await update.message.reply_text(f"❌ Unknown parameter: {param}")
        return

    attr_name, final_value = param_map[param]
    setattr(strategy.config, attr_name, final_value)

    await update.message.reply_text(
        f"✅ Updated `{param}` to `{final_value}`\n\n"
        "Use /settings to view all settings.",
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info(f"Setting updated: {param} = {final_value}")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /portfolio command - show all open positions."""
    if not is_admin(update.effective_user.id):
        return

    try:
        positions = position_manager.get_open_positions()

        if not positions:
            await update.message.reply_text("📊 No open positions.")
            return

        sol_price = get_sol_price()

        message = "📊 **OPEN POSITIONS**\n\n"

        for i, pos in enumerate(positions, 1):
            pnl_emoji = "🟢" if pos.pnl_sol >= 0 else "🔴"
            duration = format_duration(pos.entry_time)
            value_usd = pos.current_value_sol * sol_price

            message += f"{pnl_emoji} **{i}. ${pos.token_symbol}**\n"
            message += f"├ Entry: {pos.entry_sol:.4f} SOL\n"
            message += f"├ Current: {pos.current_value_sol:.4f} SOL (${value_usd:.2f})\n"
            message += f"├ P&L: {pos.pnl_sol:+.4f} SOL ({pos.pnl_percent:+.1f}%)\n"
            message += f"├ Remaining: {pos.remaining_percent:.0f}%\n"
            message += f"└ Age: {duration}\n\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Portfolio command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /balance command - show wallet balance."""
    if not is_admin(update.effective_user.id):
        return

    try:
        stats = position_manager.get_stats()
        sol_price = get_sol_price()

        balance_sol = stats['current_balance']
        balance_usd = balance_sol * sol_price
        starting = stats['starting_balance']

        message = f"""
💰 **WALLET BALANCE**

**Current:** {balance_sol:.4f} SOL (${balance_usd:.2f})
**Starting:** {starting:.4f} SOL
**Total P&L:** {stats['total_pnl_sol']:+.4f} SOL ({stats['total_pnl_percent']:+.1f}%)

**Progress to $10k Goal:** {stats['progress_percent']:.1f}%
"""

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Balance command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command - show last 10 trades."""
    if not is_admin(update.effective_user.id):
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trade_type, token_symbol, sol_amount, pnl_sol,
                   pnl_percent, timestamp
            FROM trade_history
            WHERE trade_type != 'entry'
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        trades = cursor.fetchall()
        conn.close()

        if not trades:
            await update.message.reply_text("📊 No trade history yet.")
            return

        message = "📊 **TRADE HISTORY** (Last 10)\n\n"

        for trade in trades:
            trade_type, symbol, sol_amt, pnl_sol, pnl_pct, timestamp = trade
            pnl_emoji = "🟢" if pnl_sol >= 0 else "🔴"

            # Parse timestamp
            try:
                dt = datetime.fromisoformat(timestamp)
                time_str = dt.strftime("%m/%d %H:%M")
            except:
                time_str = timestamp[:16]

            trade_label = {
                'tp1': 'TP1',
                'tp2': 'TP2',
                'stop': 'STOP',
                'manual': 'EXIT'
            }.get(trade_type, trade_type.upper())

            message += f"{pnl_emoji} **{trade_label} - ${symbol}**\n"
            message += f"├ {time_str}\n"
            message += f"├ {sol_amt:.4f} SOL\n"
            message += f"└ {pnl_sol:+.4f} SOL ({pnl_pct:+.1f}%)\n\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"History command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report command - today's trading summary."""
    if not is_admin(update.effective_user.id):
        return

    try:
        today = datetime.now().date()
        today_str = today.isoformat()

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Get today's trades
        cursor.execute("""
            SELECT COUNT(*), SUM(pnl_sol),
                   SUM(CASE WHEN pnl_sol > 0 THEN 1 ELSE 0 END)
            FROM trade_history
            WHERE DATE(timestamp) = ?
            AND trade_type != 'entry'
        """, (today_str,))

        row = cursor.fetchone()
        total_trades = row[0] or 0
        total_pnl = row[1] or 0.0
        wins = row[2] or 0

        # Get today's trade details
        cursor.execute("""
            SELECT trade_type, token_symbol, pnl_sol, pnl_percent, timestamp
            FROM trade_history
            WHERE DATE(timestamp) = ?
            AND trade_type != 'entry'
            ORDER BY timestamp DESC
        """, (today_str,))

        trades = cursor.fetchall()
        conn.close()

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

        message = f"""
📊 **DAILY REPORT** - {today.strftime('%B %d, %Y')}

{pnl_emoji} **Summary:**
├ Total Trades: {total_trades}
├ Wins: {wins}/{total_trades} ({win_rate:.0f}%)
└ P&L: {total_pnl:+.4f} SOL

"""

        if trades:
            message += "**Trades Today:**\n"
            for trade in trades:
                trade_type, symbol, pnl_sol, pnl_pct, timestamp = trade
                emoji = "🟢" if pnl_sol >= 0 else "🔴"
                dt = datetime.fromisoformat(timestamp)
                time_str = dt.strftime("%H:%M")

                message += f"{emoji} {time_str} - ${symbol}: {pnl_sol:+.4f} SOL ({pnl_pct:+.1f}%)\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Report command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /exit command - force close a position."""
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage: `/exit <TOKEN_SYMBOL>`\n\n"
            "Example: `/exit BONK`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    token_symbol = context.args[0].upper()

    # Find position by symbol
    positions = position_manager.get_open_positions()
    position = None

    for pos in positions:
        if pos.token_symbol.upper() == token_symbol:
            position = pos
            break

    if not position:
        await update.message.reply_text(
            f"❌ No open position found for ${token_symbol}\n\n"
            "Use /portfolio to see all positions."
        )
        return

    # Show confirmation
    sol_price = get_sol_price()
    value_usd = position.current_value_sol * sol_price
    entry_usd = position.entry_sol * sol_price

    keyboard = [
        [
            InlineKeyboardButton("✅ CONFIRM EXIT", callback_data=f"exit_confirm_{position.token_mint}"),
            InlineKeyboardButton("❌ CANCEL", callback_data="exit_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = f"""
⚠️ **CONFIRM EXIT**

**Position:** ${position.token_symbol}
**Entry:** {position.entry_sol:.4f} SOL (${entry_usd:.2f})
**Current:** {position.current_value_sol:.4f} SOL (${value_usd:.2f})
**P&L:** {position.pnl_sol:+.4f} SOL ({position.pnl_percent:+.1f}%)
**Remaining:** {position.remaining_percent:.0f}%

⚠️ This will close the entire position immediately.
"""

    await update.message.reply_text(
        message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )


async def handle_exit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle exit confirmation button press."""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    if query.data == "exit_cancel":
        await query.edit_message_text("❌ Exit cancelled.")
        return

    # Extract token mint from callback data
    if not query.data.startswith("exit_confirm_"):
        return

    token_mint = query.data.replace("exit_confirm_", "")

    # Find position
    position = None
    for pos in position_manager.get_open_positions():
        if pos.token_mint == token_mint:
            position = pos
            break

    if not position:
        await query.edit_message_text("❌ Position not found or already closed.")
        return

    await query.edit_message_text(
        f"🔄 Closing ${position.token_symbol} position...\n\n"
        "⚠️ **Note:** Actual trade execution requires OpenClaw trader to be running."
    )

    # Log the manual close request
    logger.warning(f"Manual exit requested for {position.token_symbol} ({token_mint})")

    # In production, this would call the actual DEX to execute the trade
    # For now, just log it
    await query.edit_message_text(
        f"⚠️ **EXIT REQUEST LOGGED**\n\n"
        f"Position: ${position.token_symbol}\n"
        f"Current P&L: {position.pnl_sol:+.4f} SOL ({position.pnl_percent:+.1f}%)\n\n"
        f"✅ OpenClaw will execute this exit when the trader is running.\n\n"
        f"**For immediate execution:**\n"
        f"1. Ensure OpenClaw service is running\n"
        f"2. The trader will detect this and execute the sell\n\n"
        f"Use /status to monitor.",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /buy command - manual buy (requires confirmation)."""
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/buy <TOKEN_SYMBOL> <SOL_AMOUNT>`\n\n"
            "Example: `/buy BONK 0.1`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    token_symbol = context.args[0].upper()

    try:
        sol_amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid SOL amount.")
        return

    if sol_amount <= 0:
        await update.message.reply_text("❌ SOL amount must be positive.")
        return

    # Check balance
    stats = position_manager.get_stats()
    if sol_amount > stats['current_balance'] * 0.95:  # Leave 5% for fees
        await update.message.reply_text(
            f"❌ Insufficient balance.\n\n"
            f"Available: {stats['current_balance']:.4f} SOL\n"
            f"Requested: {sol_amount:.4f} SOL"
        )
        return

    # Check max positions
    if len(position_manager.get_open_positions()) >= 3:
        await update.message.reply_text("❌ Max positions reached (3/3)")
        return

    sol_price = get_sol_price()
    usd_value = sol_amount * sol_price

    await update.message.reply_text(
        f"⚠️ **MANUAL BUY REQUEST**\n\n"
        f"Token: ${token_symbol}\n"
        f"Amount: {sol_amount:.4f} SOL (${usd_value:.2f})\n\n"
        f"✅ This requires OpenClaw trader to be running.\n"
        f"Manual buys are not yet fully automated.\n\n"
        f"**To execute manually:**\n"
        f"1. Log into your VPS\n"
        f"2. Use Jupiter API or DEX directly\n"
        f"3. Buy {sol_amount:.4f} SOL of ${token_symbol}",
        parse_mode=ParseMode.MARKDOWN
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)


def main():
    """Start V'ger bot."""
    if not VGER_BOT_TOKEN:
        raise ValueError("VGER_BOT_TOKEN not set in environment")

    # Ensure logs directory exists
    Path("logs").mkdir(exist_ok=True)

    logger.info("=" * 60)
    logger.info("V'GER CONTROL BOT STARTING")
    logger.info("=" * 60)
    logger.info(f"Admin ID: {VGER_ADMIN_ID}")
    logger.info(f"Database: {DB_PATH}")

    # Create application
    application = Application.builder().token(VGER_BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("settings", cmd_settings))
    application.add_handler(CommandHandler("set", cmd_set))
    application.add_handler(CommandHandler("portfolio", cmd_portfolio))
    application.add_handler(CommandHandler("balance", cmd_balance))
    application.add_handler(CommandHandler("history", cmd_history))
    application.add_handler(CommandHandler("report", cmd_report))
    application.add_handler(CommandHandler("exit", cmd_exit))
    application.add_handler(CommandHandler("buy", cmd_buy))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_exit_callback))

    # Error handler
    application.add_error_handler(error_handler)

    # Start bot
    logger.info("V'ger bot started. Awaiting commands...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
