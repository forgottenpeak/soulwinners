"""
Telegram Bot for SoulWinners
Real-time alerts with token images and clickable links
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
import aiohttp

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    HELIUS_API_KEY,
)

logger = logging.getLogger(__name__)


class AlertFormatter:
    """Format wallet alerts with rich media and links."""

    TIER_EMOJI = {
        'Elite': '🔥',
        'High-Quality': '🟢',
        'Mid-Tier': '🟡',
        'Watchlist': '⚪',
    }

    @staticmethod
    def format_wallet_short(address: str) -> str:
        """Format wallet address as first7...last4"""
        if len(address) > 11:
            return f"{address[:7]}...{address[-4:]}"
        return address

    @staticmethod
    async def get_token_info(token_address: str) -> Dict:
        """Get full token info from DexScreener."""
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            pair = data[0]
                            return {
                                'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                                'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                                'address': token_address,
                                'image_url': pair.get('info', {}).get('imageUrl', ''),
                                'price_usd': pair.get('priceUsd', '0'),
                                'liquidity': pair.get('liquidity', {}).get('usd', 0),
                            }
        except Exception as e:
            logger.error(f"Error fetching token info: {e}")

        return {
            'name': 'Unknown',
            'symbol': '???',
            'address': token_address,
            'image_url': '',
            'price_usd': '0',
            'liquidity': 0,
        }

    def format_buy_alert(
        self,
        wallet: Dict,
        token: Dict,
        trade: Dict,
        recent_trades: List[Dict] = None
    ) -> str:
        """Format a buy alert message with clickable links."""
        tier = wallet.get('tier', 'Unknown')
        tier_emoji = self.TIER_EMOJI.get(tier, '⚪')
        strategy = wallet.get('cluster_name', 'Unknown Strategy')

        token_address = token.get('address', '')
        wallet_address = wallet.get('wallet_address', '')
        wallet_short = self.format_wallet_short(wallet_address)

        # Build message with proper Markdown clickable links
        message = f"""
{tier_emoji} **{tier.upper()} WALLET BUY ALERT** {tier_emoji}

🪙 **Token:** {token.get('symbol', '???')} ({token.get('name', 'Unknown')})
📍 **CA:** `{token_address}`
💰 **Amount:** {trade.get('sol_amount', 0):.4f} SOL

📊 **Wallet Stats:**
├ Strategy: {strategy}
├ Win Rate: {wallet.get('profit_token_ratio', 0):.1%}
├ ROI: {wallet.get('roi_pct', 0):.1f}%
├ 10x+ Rate: {wallet.get('x10_ratio', 0):.1%}
└ SOL Balance: {wallet.get('current_balance_sol', 0):.2f}

🔗 **Links:**
[DexScreener](https://dexscreener.com/solana/{token_address}) | [Birdeye](https://birdeye.so/token/{token_address}?chain=solana) | [Solscan](https://solscan.io/token/{token_address}) | [Jupiter](https://jup.ag/swap/SOL-{token_address})

👛 **Wallet:** `{wallet_short}`
[View on Solscan](https://solscan.io/account/{wallet_address}) | [View on Birdeye](https://birdeye.so/profile/{wallet_address}?chain=solana)"""

        # Add recent trades if available
        if recent_trades and len(recent_trades) > 0:
            message += "\n\n📈 **Last 5 Trades:**"
            for t in recent_trades[:5]:
                pnl = t.get('pnl_percent', 0)
                emoji = '🟢' if pnl > 0 else '🔴'
                symbol = t.get('token_symbol', '???')[:10]
                message += f"\n{emoji} {symbol}: {pnl:+.1f}%"

        return message

    def format_sell_alert(
        self,
        wallet: Dict,
        token: Dict,
        trade: Dict,
        pnl_percent: float = 0
    ) -> str:
        """Format a sell alert message with clickable links."""
        tier = wallet.get('tier', 'Unknown')
        tier_emoji = self.TIER_EMOJI.get(tier, '⚪')
        pnl_emoji = '🟢' if pnl_percent > 0 else '🔴'

        token_address = token.get('address', '')
        wallet_address = wallet.get('wallet_address', '')
        wallet_short = self.format_wallet_short(wallet_address)

        message = f"""
{tier_emoji} **{tier.upper()} WALLET SELL** {pnl_emoji}

🪙 **Token:** {token.get('symbol', '???')} ({token.get('name', 'Unknown')})
📍 **CA:** `{token_address}`
💰 **Sold:** {trade.get('sol_amount', 0):.4f} SOL
📊 **PnL:** {pnl_percent:+.1f}%

🔗 [DexScreener](https://dexscreener.com/solana/{token_address}) | [Birdeye](https://birdeye.so/token/{token_address}?chain=solana) | [Solscan](https://solscan.io/token/{token_address})

👛 `{wallet_short}` | [Solscan](https://solscan.io/account/{wallet_address})"""

        return message


class SoulWinnersBot:
    """Main Telegram bot for SoulWinners."""

    def __init__(self, db_connection=None):
        self.token = TELEGRAM_BOT_TOKEN
        self.channel_id = TELEGRAM_CHANNEL_ID
        self.bot = Bot(token=self.token)
        self.formatter = AlertFormatter()
        self.db = db_connection
        self.application = None

    async def start(self):
        """Initialize and start the bot."""
        self.application = Application.builder().token(self.token).build()

        # Register command handlers
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        self.application.add_handler(CommandHandler("pool", self.cmd_pool))
        self.application.add_handler(CommandHandler("elite", self.cmd_elite))
        self.application.add_handler(CommandHandler("tiers", self.cmd_tiers))
        self.application.add_handler(CommandHandler("recent", self.cmd_recent))
        self.application.add_handler(CommandHandler("settings", self.cmd_settings))
        self.application.add_handler(CommandHandler("help", self.cmd_help))

        # Start polling
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        logger.info("Telegram bot started")

    async def stop(self):
        """Stop the bot."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        message = """
🚀 **Welcome to SoulWinners!**

I track elite Solana wallets and alert you to their trades in real-time.

**Commands:**
/status - System status
/pool - View wallet pool stats
/elite - List Elite tier wallets
/tiers - Tier breakdown
/recent - Recent alerts
/settings - Configure alerts
/help - Help & info

Let's find alpha! 💎
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        # Get stats from database
        stats = await self._get_system_stats()

        message = f"""
📊 **SoulWinners Status**

👛 **Wallet Pool:**
├ Total Qualified: {stats.get('total_wallets', 0)}
├ Elite: {stats.get('elite_count', 0)}
├ High-Quality: {stats.get('high_count', 0)}
├ Mid-Tier: {stats.get('mid_count', 0)}
└ Watchlist: {stats.get('watchlist_count', 0)}

📡 **Monitoring:**
├ Active Websockets: {stats.get('active_ws', 0)}
├ Last Alert: {stats.get('last_alert', 'Never')}
└ Alerts Today: {stats.get('alerts_today', 0)}

🔄 **Last Pipeline Run:**
└ {stats.get('last_refresh', 'Never')}

✅ System Online
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_pool(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pool command - show wallet pool statistics."""
        stats = await self._get_pool_stats()

        message = f"""
👛 **Wallet Pool Overview**

📈 **Performance Metrics:**
├ Avg Win Rate: {stats.get('avg_win_rate', 0):.1%}
├ Avg ROI: {stats.get('avg_roi', 0):.1f}%
├ Avg 10x Rate: {stats.get('avg_x10', 0):.1%}
└ Total SOL Tracked: {stats.get('total_sol', 0):,.0f}

🎯 **Strategy Distribution:**
├ Snipers: {stats.get('snipers', 0)}
├ Moonshot Hunters: {stats.get('hunters', 0)}
├ Core Alpha: {stats.get('alpha', 0)}
├ Conviction Holders: {stats.get('holders', 0)}
└ Dormant: {stats.get('dormant', 0)}

🔄 **Source Distribution:**
├ Pump.fun: {stats.get('pumpfun', 0)}
├ DEX: {stats.get('dex', 0)}
└ Both: {stats.get('both', 0)}
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_elite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /elite command - list elite wallets."""
        wallets = await self._get_elite_wallets(limit=10)

        message = "🔥 **Top Elite Wallets:**\n\n"

        for i, w in enumerate(wallets, 1):
            addr = w.get('wallet_address', '')[:12]
            win_rate = w.get('profit_token_ratio', 0)
            roi = w.get('roi_pct', 0)
            strategy = w.get('cluster_name', 'Unknown')[:15]

            message += f"{i}. `{addr}...`\n"
            message += f"   {strategy} | WR: {win_rate:.0%} | ROI: {roi:.0f}%\n\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_tiers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /tiers command - show tier breakdown."""
        stats = await self._get_tier_stats()

        message = f"""
🏆 **Tier Breakdown**

🔥 **Elite** (Top 15%)
├ Count: {stats.get('elite_count', 0)}
├ Avg Win Rate: {stats.get('elite_wr', 0):.1%}
└ Avg ROI: {stats.get('elite_roi', 0):.1f}%

🟢 **High-Quality** (Next 25%)
├ Count: {stats.get('high_count', 0)}
├ Avg Win Rate: {stats.get('high_wr', 0):.1%}
└ Avg ROI: {stats.get('high_roi', 0):.1f}%

🟡 **Mid-Tier** (Next 40%)
├ Count: {stats.get('mid_count', 0)}
├ Avg Win Rate: {stats.get('mid_wr', 0):.1%}
└ Avg ROI: {stats.get('mid_roi', 0):.1f}%

⚪ **Watchlist** (Bottom 20%)
├ Count: {stats.get('watch_count', 0)}
├ Avg Win Rate: {stats.get('watch_wr', 0):.1%}
└ Avg ROI: {stats.get('watch_roi', 0):.1f}%
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_recent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /recent command - show recent alerts."""
        alerts = await self._get_recent_alerts(limit=5)

        message = "📋 **Recent Alerts:**\n\n"

        if not alerts:
            message += "No recent alerts."
        else:
            for alert in alerts:
                tier_emoji = AlertFormatter.TIER_EMOJI.get(alert.get('tier', ''), '⚪')
                symbol = alert.get('token_symbol', '???')
                action = alert.get('alert_type', 'trade').upper()
                time = alert.get('sent_at', '')

                message += f"{tier_emoji} {action}: {symbol}\n"
                message += f"   {time}\n\n"

        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command."""
        message = """
⚙️ **Settings**

Current alert configuration:

✅ Elite wallet alerts: ON
✅ High-Quality alerts: ON
🟡 Mid-Tier alerts: OFF
⚪ Watchlist alerts: OFF

Minimum trade size: 1 SOL

_Settings customization coming soon!_
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        message = """
❓ **SoulWinners Help**

**What is SoulWinners?**
An automated system that identifies and tracks elite Solana traders using ML clustering and priority scoring.

**How it works:**
1. Collects profitable wallets from Pump.fun & DEX
2. Calculates performance metrics (ROI, win rate, etc.)
3. Uses K-Means to identify trading strategies
4. Ranks wallets and assigns quality tiers
5. Monitors trades and sends real-time alerts

**Commands:**
/start - Welcome message
/status - System health & stats
/pool - Wallet pool overview
/elite - Top elite wallets
/tiers - Tier breakdown
/recent - Recent alerts
/settings - Configure alerts
/help - This help message

**Links in Alerts:**
• DexScreener - Chart & liquidity
• Birdeye - Analytics
• Solscan - Explorer
• Jupiter - Trade

Built with 💎 by SoulWinners
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    # =========================================================================
    # ALERT METHODS
    # =========================================================================

    async def send_buy_alert(
        self,
        wallet: Dict,
        token: Dict,
        trade: Dict,
        recent_trades: List[Dict] = None
    ):
        """Send a buy alert to the channel with real token data."""
        # Fetch real token info from DexScreener if we only have address
        if token.get('address') and not token.get('name'):
            token_info = await self.formatter.get_token_info(token.get('address'))
            token.update(token_info)

        message = self.formatter.format_buy_alert(wallet, token, trade, recent_trades)
        image_url = token.get('image_url', '')

        try:
            if image_url:
                await self.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=image_url,
                    caption=message,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False  # Enable link preview
                )

            logger.info(f"Sent buy alert for {token.get('symbol', 'Unknown')}")

        except Exception as e:
            logger.error(f"Error sending alert: {e}")
            # Fallback: try without image
            try:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False
                )
            except Exception as e2:
                logger.error(f"Fallback alert also failed: {e2}")

    async def send_sell_alert(
        self,
        wallet: Dict,
        token: Dict,
        trade: Dict,
        pnl_percent: float
    ):
        """Send a sell alert to the channel with real token data."""
        # Fetch real token info from DexScreener if we only have address
        if token.get('address') and not token.get('name'):
            token_info = await self.formatter.get_token_info(token.get('address'))
            token.update(token_info)

        message = self.formatter.format_sell_alert(wallet, token, trade, pnl_percent)

        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False
            )
            logger.info(f"Sent sell alert for {token.get('symbol', 'Unknown')}")

        except Exception as e:
            logger.error(f"Error sending sell alert: {e}")

    # =========================================================================
    # DATABASE HELPERS
    # =========================================================================

    async def _get_system_stats(self) -> Dict:
        """Get system statistics from database."""
        # Placeholder - implement with actual DB queries
        return {
            'total_wallets': 0,
            'elite_count': 0,
            'high_count': 0,
            'mid_count': 0,
            'watchlist_count': 0,
            'active_ws': 0,
            'last_alert': 'Never',
            'alerts_today': 0,
            'last_refresh': 'Never',
        }

    async def _get_pool_stats(self) -> Dict:
        """Get wallet pool statistics."""
        return {}

    async def _get_elite_wallets(self, limit: int = 10) -> List[Dict]:
        """Get top elite wallets."""
        return []

    async def _get_tier_stats(self) -> Dict:
        """Get tier statistics."""
        return {}

    async def _get_recent_alerts(self, limit: int = 5) -> List[Dict]:
        """Get recent alerts."""
        return []


async def main():
    """Test the bot."""
    bot = SoulWinnersBot()

    # Test alert formatting
    formatter = AlertFormatter()

    test_wallet = {
        'wallet_address': 'DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK',
        'tier': 'Elite',
        'cluster_name': 'Core Alpha (Active)',
        'profit_token_ratio': 0.78,
        'roi_pct': 245.5,
        'x10_ratio': 0.12,
        'current_balance_sol': 125.5,
    }

    test_token = {
        'address': 'So11111111111111111111111111111111111111112',
        'symbol': 'SOL',
        'name': 'Solana',
    }

    test_trade = {
        'sol_amount': 5.5,
    }

    message = formatter.format_buy_alert(test_wallet, test_token, test_trade)
    print(message)


if __name__ == "__main__":
    asyncio.run(main())
