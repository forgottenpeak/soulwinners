"""
Real Alert Formatter
Uses ACTUAL blockchain data - no fake/hardcoded values
ONLY alerts on wallets from qualified_wallets table (passed all filters)
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp
import logging

from telegram import Bot
from telegram.constants import ParseMode
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, MIN_SOL_BALANCE

logger = logging.getLogger(__name__)


class RealAlertSender:
    """Send alerts with REAL blockchain data only."""

    TIER_EMOJI = {
        'Elite': '🔥',
        'High-Quality': '🟢',
        'Mid-Tier': '🟡',
        'Watchlist': '⚪',
    }

    def __init__(self):
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.channel_id = TELEGRAM_CHANNEL_ID

    def validate_wallet(self, wallet: Dict, actual_balance: float) -> bool:
        """
        Verify wallet still meets quality thresholds.
        Returns False if wallet should be skipped.
        """
        # CRITICAL: Balance must be >= 40 SOL
        if actual_balance < MIN_SOL_BALANCE:
            logger.warning(
                f"Skipping alert - balance {actual_balance:.2f} SOL < {MIN_SOL_BALANCE} minimum"
            )
            return False

        return True

    def format_real_alert(self, alert_data: Dict) -> str:
        """
        Format alert using ONLY real data from alert_data.

        alert_data contains:
        - wallet: qualified wallet data from DB (MUST have passed quality filter)
        - token: real token info from DexScreener
        - trade: actual transaction data with timestamp
        - sol_price: live SOL price from CoinGecko (~$78)
        - actual_balance: real wallet balance (MUST be >= 40 SOL)
        - recent_trades: actual last 5 trades from Helius
        - smart_money: count of other smart wallets in this token
        """
        wallet = alert_data['wallet']
        token = alert_data['token']
        trade = alert_data['trade']
        sol_price = alert_data['sol_price']
        actual_balance = alert_data['actual_balance']
        recent_trades = alert_data['recent_trades']
        smart_money = alert_data['smart_money']

        tier = wallet.get('tier', 'Unknown')
        tier_emoji = self.TIER_EMOJI.get(tier, '⚪')
        strategy = wallet.get('cluster_name', 'Unknown')

        # Calculate USD value with REAL SOL price
        sol_amount = trade.get('sol_amount', 0)
        usd_value = sol_amount * sol_price
        balance_usd = actual_balance * sol_price

        token_address = token.get('address', '')

        # Get buy timestamp
        time_ago = trade.get('time_ago', 'just now')

        # Build message - NO wallet address shown (privacy)
        message = f"""
{tier_emoji} **{tier.upper()} WALLET BUY** {tier_emoji}
⏰ Bought {time_ago}

🪙 **Token:** {token.get('symbol', '???')} ({token.get('name', 'Unknown')})
📍 **CA:** `{token_address}`
💰 **Amount:** {sol_amount:.4f} SOL (~${usd_value:.2f})

📊 **Strategy:** {strategy}
├ Win Rate: {wallet.get('profit_token_ratio', 0):.1%}
├ ROI: {wallet.get('roi_pct', 0):.1f}%
├ 10x+ Rate: {wallet.get('x10_ratio', 0):.1%}
└ Balance: {actual_balance:.2f} SOL (~${balance_usd:.0f})

💡 **SMART MONEY ACTIVITY:**
├─ 🔥 {smart_money.get('elite', 0)} Elite wallets bought this
├─ 🟢 {smart_money.get('high', 0)} High-Quality wallets holding
└─ Total smart money: {smart_money.get('total', 0)} wallets

🔗 **Links:**
[DexScreener](https://dexscreener.com/solana/{token_address}) | [Birdeye](https://birdeye.so/token/{token_address}?chain=solana) | [Solscan](https://solscan.io/token/{token_address}) | [Jupiter](https://jup.ag/swap/SOL-{token_address})"""

        # Add REAL recent trades with proper formatting
        if recent_trades and len(recent_trades) > 0:
            message += "\n\n📈 **Recent Trades:**"
            for t in recent_trades[:5]:
                tx_type = t.get('tx_type', 'trade')
                emoji = '🟢' if tx_type == 'buy' else '🔴'
                symbol = t.get('token_symbol', '???')[:10]
                time_str = t.get('time_ago', 'unknown')
                sol_amt = t.get('sol_amount', 0)
                usd_amt = sol_amt * sol_price
                message += f"\n{emoji} {tx_type.upper():4} {symbol:10} {sol_amt:.4f} SOL (${usd_amt:.2f}) {time_str}"

        return message

    def format_accumulation_alert(self, alert_data: Dict) -> str:
        """
        Format accumulation alert - when wallet buys same token multiple times.
        """
        wallet = alert_data['wallet']
        token = alert_data['token']
        accumulation = alert_data['accumulation']
        sol_price = alert_data['sol_price']
        smart_money = alert_data['smart_money']

        tier = wallet.get('tier', 'Unknown')
        tier_emoji = self.TIER_EMOJI.get(tier, '⚪')
        strategy = wallet.get('cluster_name', 'Unknown')

        # Accumulation data
        total_sol = accumulation.get('total_sol', 0)
        buy_count = accumulation.get('buy_count', 0)
        time_span = accumulation.get('time_span_min', 0)
        buy_amounts = accumulation.get('buy_amounts', [])

        usd_value = total_sol * sol_price
        token_address = token.get('address', '')

        # Format buy breakdown
        buy_breakdown = " + ".join(buy_amounts) if buy_amounts else f"{total_sol:.1f}"

        message = f"""
🔥 **ACCUMULATION DETECTED** 🔥
⏰ {buy_count} buys in {time_span} minutes

🪙 **Token:** ${token.get('symbol', '???')}
📍 **CA:** `{token_address}`
💰 **Total:** {total_sol:.1f} SOL ({buy_breakdown}) ~${usd_value:.0f}

📊 **{strategy}**
├ Win Rate: {wallet.get('profit_token_ratio', 0):.0%}
├ ROI: {wallet.get('roi_pct', 0):.0f}%
├ MC: ${token.get('market_cap', 0)/1e6:.1f}M
└ Liq: ${token.get('liquidity', 0)/1000:.0f}K

💡 **{tier} wallet accumulating gradually**
├─ 🔥 {smart_money.get('elite', 0)} Elite wallets in token
└─ Total smart money: {smart_money.get('total', 0)} wallets

🔗 [DEX](https://dexscreener.com/solana/{token_address}) | [Bird](https://birdeye.so/token/{token_address}?chain=solana) | [Jup](https://jup.ag/swap/SOL-{token_address})"""

        return message

    async def send_real_alert(self, alert_data: Dict) -> bool:
        """
        Send alert with real data to Telegram.
        Returns False if alert was skipped (failed validation).
        """
        # Validate wallet still meets thresholds
        if not self.validate_wallet(
            alert_data['wallet'],
            alert_data['actual_balance']
        ):
            return False

        # Check if this is an accumulation alert
        if alert_data.get('accumulation'):
            message = self.format_accumulation_alert(alert_data)
            logger.info(f"Formatting ACCUMULATION alert: {alert_data['accumulation']}")
        else:
            message = self.format_real_alert(alert_data)
        token = alert_data['token']
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
                    disable_web_page_preview=False
                )

            logger.info(f"Sent REAL alert for {token.get('symbol', '???')}")
            return True

        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            # Try text-only fallback
            try:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False
                )
                return True
            except Exception as e2:
                logger.error(f"Fallback also failed: {e2}")
                return False
