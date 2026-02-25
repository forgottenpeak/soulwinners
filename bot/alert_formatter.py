"""
Alert Formatter - CORRECT format with token metrics
"""
from datetime import datetime
from typing import Dict, List


def format_number(num: float) -> str:
    """Format large numbers with K, M, B suffixes."""
    if num >= 1_000_000_000:
        return f"${num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"${num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"${num / 1_000:.0f}K"
    else:
        return f"${num:.0f}"


class AlertFormatter:
    """Format alerts exactly as specified."""

    def format_buy_alert(
        self,
        wallet: Dict,
        token: Dict,
        trade: Dict,
        smart_money: Dict,
        recent_trades: List[Dict],
        sol_price: float = 78.0
    ) -> str:
        """
        Format a buy alert with token metrics.
        NO wallet address shown.
        """
        tier = wallet.get('tier', 'Unknown')
        tier_emoji = '🔥' if tier == 'Elite' else '🟢' if tier == 'High-Quality' else '🟡'
        strategy = wallet.get('cluster_name', 'Unknown Strategy')

        # Calculate time ago
        tx_timestamp = trade.get('timestamp', 0)
        time_ago = self._format_time_ago(tx_timestamp)

        # SOL amount and USD value
        sol_amount = trade.get('sol_amount', 0)
        usd_value = sol_amount * sol_price

        # Token info
        token_symbol = token.get('symbol', '???')
        token_name = token.get('name', 'Unknown')
        token_address = token.get('address', '')

        # Token metrics (from DexScreener)
        market_cap = token.get('market_cap', 0)
        liquidity = token.get('liquidity', 0)
        volume_1h = token.get('volume_1h', 0)
        price_change_1h = token.get('price_change_1h', 0)

        # Wallet stats
        win_rate = wallet.get('win_rate', 0) or wallet.get('profit_token_ratio', 0) or 0
        roi = wallet.get('roi_pct', 0) or 0
        x10_rate = wallet.get('x10_ratio', 0) or 0
        balance = wallet.get('current_balance_sol', 0) or 0

        # Smart money counts
        elite_count = smart_money.get('elite', 0)
        high_count = smart_money.get('high', 0)
        total_smart = smart_money.get('total', elite_count + high_count)

        # Build message
        message = f"""{tier_emoji} {tier.upper()} WALLET BUY {tier_emoji}
⏰ Bought {time_ago}

🪙 Token: {token_symbol} ({token_name})
📍 CA: `{token_address}`
💰 Amount: {sol_amount:.2f} SOL (~${usd_value:.0f})

📊 TOKEN METRICS:
├─ MC: {format_number(market_cap)}
├─ Liq: {format_number(liquidity)}
├─ Vol (1h): {format_number(volume_1h)}
└─ 1h: {price_change_1h:+.1f}%

📊 Strategy: {strategy}
├ Win Rate: {win_rate*100:.1f}%
├ ROI: {roi:.1f}%
├ 10x+ Rate: {x10_rate*100:.1f}%
└ Balance: {balance:.2f} SOL

💡 SMART MONEY ACTIVITY:
├─ 🔥 {elite_count} Elite wallets bought this
├─ 🟢 {high_count} High-Quality wallets holding
└─ Total smart money: {total_smart} wallets

🔗 [DexScreener](https://dexscreener.com/solana/{token_address}) | [Birdeye](https://birdeye.so/token/{token_address}?chain=solana) | [Solscan](https://solscan.io/token/{token_address})"""

        # Add last 5 trades if available
        if recent_trades and len(recent_trades) > 0:
            message += "\n\n📈 Last 5 Trades:"
            for t in recent_trades[:5]:
                pnl = t.get('pnl_percent', 0)
                emoji = '🟢' if pnl > 0 else '🔴' if pnl < 0 else '⚪'
                symbol = t.get('token_symbol', '???')[:10]
                time_str = t.get('time_ago', '')
                if pnl == 0:
                    message += f"\n{emoji} {symbol}: OPEN ({time_str})"
                else:
                    message += f"\n{emoji} {symbol}: {pnl:+.1f}% ({time_str})"

        return message

    def _format_time_ago(self, timestamp: int) -> str:
        """Format timestamp as 'Xm ago' or 'Xh ago'."""
        if not timestamp:
            return "just now"

        now = datetime.now().timestamp()
        diff = now - timestamp

        if diff < 60:
            return "just now"
        elif diff < 3600:
            return f"{int(diff / 60)}m ago"
        elif diff < 86400:
            return f"{int(diff / 3600)}h ago"
        elif diff < 604800:
            return f"{int(diff / 86400)}d ago"
        else:
            return f"{int(diff / 604800)}w ago"
