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

        # Add aggregate wallet performance stats
        if recent_trades and len(recent_trades) > 0:
            # Calculate aggregate stats from recent trades
            total_trades = len(recent_trades)
            profitable = sum(1 for t in recent_trades if t.get('pnl_percent', 0) > 0)
            losses = sum(1 for t in recent_trades if t.get('pnl_percent', 0) < 0)
            open_trades = sum(1 for t in recent_trades if t.get('pnl_percent', 0) == 0)

            pnls = [t.get('pnl_percent', 0) for t in recent_trades if t.get('pnl_percent', 0) != 0]
            avg_roi = sum(pnls) / len(pnls) if pnls else 0
            win_rate_recent = profitable / (profitable + losses) if (profitable + losses) > 0 else 0

            # Calculate average hold time
            hold_times = []
            for t in recent_trades:
                if t.get('hold_time_min'):
                    hold_times.append(t.get('hold_time_min'))

            avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0

            message += f"""

📈 RECENT PERFORMANCE:
• Avg ROI: {avg_roi:+.0f}%
• Win Rate: {win_rate_recent*100:.0f}%
• Record: {profitable}W / {losses}L / {open_trades}O
• Avg Hold: {self._format_hold_time(avg_hold)}"""

        return message

    def _format_hold_time(self, minutes: float) -> str:
        """Format hold time in readable format."""
        if minutes <= 0:
            return "N/A"
        elif minutes < 60:
            return f"{int(minutes)}m"
        elif minutes < 1440:  # Less than a day
            return f"{minutes/60:.1f}h"
        else:
            return f"{minutes/1440:.1f}d"

    def format_accumulation_alert(
        self,
        wallet: Dict,
        token: Dict,
        trade: Dict,
        accumulation: Dict,
        smart_money: Dict,
        recent_trades: List[Dict],
        sol_price: float = 78.0
    ) -> str:
        """
        Format an accumulation alert when wallet buys same token multiple times.
        """
        tier = wallet.get('tier', 'Unknown')
        tier_emoji = '🔥' if tier == 'Elite' else '🟢' if tier == 'High-Quality' else '🟡'
        strategy = wallet.get('cluster_name', 'Unknown Strategy')

        # Accumulation data
        total_sol = accumulation.get('total_sol', 0)
        buy_count = accumulation.get('buy_count', 0)
        time_span = accumulation.get('time_span_min', 0)
        buy_amounts = accumulation.get('buy_amounts', [])

        usd_value = total_sol * sol_price

        # Token info
        token_symbol = token.get('symbol', '???')
        token_name = token.get('name', 'Unknown')
        token_address = token.get('address', '')

        # Token metrics
        market_cap = token.get('market_cap', 0)
        liquidity = token.get('liquidity', 0)

        # Wallet stats
        win_rate = wallet.get('win_rate', 0) or wallet.get('profit_token_ratio', 0) or 0
        roi = wallet.get('roi_pct', 0) or 0

        # Smart money counts
        elite_count = smart_money.get('elite', 0)
        total_smart = smart_money.get('total', 0)

        # Format buy breakdown
        buy_breakdown = " + ".join(buy_amounts) if buy_amounts else str(total_sol)

        message = f"""🔥 ACCUMULATION DETECTED 🔥
⏰ {buy_count} buys in {time_span} minutes

🪙 Token: ${token_symbol}
📍 CA: `{token_address}`
💰 Total: {total_sol:.1f} SOL ({buy_breakdown}) ~${usd_value:.0f}

📊 {strategy}
├ Win Rate: {win_rate*100:.0f}%
├ ROI: {roi:.0f}%
├ MC: {format_number(market_cap)}
└ Liq: {format_number(liquidity)}

💡 Smart money accumulating gradually
├─ 🔥 {elite_count} Elite wallets in token
└─ Total smart money: {total_smart} wallets

🔗 [DEX](https://dexscreener.com/solana/{token_address}) | [Bird](https://birdeye.so/token/{token_address}?chain=solana)"""

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
