"""
Alert Formatter - CORRECT format with token metrics
With LIVE balance fetching from Helius API
With SoulScanner buttons and Win Milestone alerts
"""
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config.settings import HELIUS_FREE_KEYS

logger = logging.getLogger(__name__)

# SoulScanner bot link
SOULSCANNER_BOT = "https://t.me/SoulScannerBot?start="


async def fetch_live_balance(wallet_address: str) -> Optional[float]:
    """
    Fetch LIVE SOL balance from Helius API.
    Returns balance in SOL or None if fetch fails.
    """
    api_key = HELIUS_FREE_KEYS[0] if HELIUS_FREE_KEYS else None
    if not api_key:
        return None

    url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/balances"
    params = {'api-key': api_key}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Native SOL balance is in lamports
                    native_balance = data.get('nativeBalance', 0)
                    return native_balance / 1e9  # Convert to SOL
    except Exception as e:
        logger.debug(f"Failed to fetch live balance for {wallet_address[:12]}...: {e}")

    return None


async def fetch_live_wallet_stats(wallet_address: str) -> Dict:
    """
    Fetch fresh wallet statistics from recent transactions.
    Returns dict with win_rate, roi estimate, recent_trades.
    """
    api_key = HELIUS_FREE_KEYS[0] if HELIUS_FREE_KEYS else None
    if not api_key:
        return {}

    url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/transactions"
    params = {'api-key': api_key, 'limit': 50}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    txs = await resp.json()

                    if not txs:
                        return {}

                    wins = 0
                    losses = 0
                    total_pnl = 0

                    for tx in txs:
                        if 'SWAP' not in tx.get('type', '').upper():
                            continue

                        native_transfers = tx.get('nativeTransfers', [])
                        fee_payer = tx.get('feePayer', wallet_address)

                        sol_in = sum(
                            t.get('amount', 0) / 1e9
                            for t in native_transfers
                            if t.get('toUserAccount') == fee_payer
                        )
                        sol_out = sum(
                            t.get('amount', 0) / 1e9
                            for t in native_transfers
                            if t.get('fromUserAccount') == fee_payer
                        )

                        net = sol_in - sol_out
                        total_pnl += net

                        if net > 0:
                            wins += 1
                        elif net < 0:
                            losses += 1

                    total_trades = wins + losses
                    win_rate = wins / total_trades if total_trades > 0 else 0

                    return {
                        'live_win_rate': win_rate,
                        'recent_trades': total_trades,
                        'recent_pnl_sol': total_pnl,
                    }

    except Exception as e:
        logger.debug(f"Failed to fetch live stats for {wallet_address[:12]}...: {e}")

    return {}


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

    async def format_buy_alert_async(
        self,
        wallet: Dict,
        token: Dict,
        trade: Dict,
        smart_money: Dict,
        recent_trades: List[Dict],
        sol_price: float = 78.0,
        fetch_live: bool = True
    ) -> str:
        """
        Format a buy alert with LIVE balance and stats.
        Async version that fetches fresh data from Helius.
        """
        wallet_address = wallet.get('wallet_address', '')

        # Fetch LIVE balance and stats if enabled
        live_balance = None
        live_stats = {}

        if fetch_live and wallet_address:
            try:
                live_balance, live_stats = await asyncio.gather(
                    fetch_live_balance(wallet_address),
                    fetch_live_wallet_stats(wallet_address)
                )
            except Exception as e:
                logger.debug(f"Failed to fetch live data: {e}")

        # Use live balance if available, otherwise fall back to cached
        if live_balance is not None:
            wallet = wallet.copy()
            wallet['current_balance_sol'] = live_balance
            wallet['_balance_source'] = 'live'

        # Update win rate if we have live stats
        if live_stats.get('live_win_rate') is not None:
            wallet = wallet.copy() if '_balance_source' not in wallet else wallet
            wallet['win_rate'] = live_stats['live_win_rate']
            wallet['_stats_source'] = 'live'

        # Call the sync formatter
        return self.format_buy_alert(wallet, token, trade, smart_money, recent_trades, sol_price)

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
        Includes wallet address for /add command.
        """
        tier = wallet.get('tier', 'Unknown')
        tier_emoji = '🔥' if tier == 'Elite' else '🟢' if tier == 'High-Quality' else '🟡'
        strategy = wallet.get('cluster_name', 'Unknown Strategy')
        wallet_address = wallet.get('wallet_address', '')

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

        # Wallet stats (may be live or cached)
        win_rate = wallet.get('win_rate', 0) or wallet.get('profit_token_ratio', 0) or 0
        roi = wallet.get('roi_pct', 0) or 0
        x10_rate = wallet.get('x10_ratio', 0) or 0
        balance = wallet.get('current_balance_sol', 0) or 0

        # Show indicator if using live data
        balance_indicator = " (LIVE)" if wallet.get('_balance_source') == 'live' else ""

        # Smart money counts
        elite_count = smart_money.get('elite', 0)
        high_count = smart_money.get('high', 0)
        total_smart = smart_money.get('total', elite_count + high_count)

        # TRUNCATE wallet for public channel (privacy)
        if wallet_address and len(wallet_address) > 12:
            wallet_truncated = f"{wallet_address[:5]}...{wallet_address[-5:]}"
        else:
            wallet_truncated = wallet_address or "Unknown"

        # Build message - truncated wallet for public (use /wallet to reveal)
        message = f"""{tier_emoji} {tier.upper()} WALLET BUY {tier_emoji}
⏰ Bought {time_ago}
👛 Wallet: `{wallet_truncated}`

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
└ Balance: {balance:.2f} SOL{balance_indicator}

💡 SMART MONEY ACTIVITY:
├─ 🔥 {elite_count} Elite wallets bought this
├─ 🟢 {high_count} High-Quality wallets holding
└─ Total smart money: {total_smart} wallets

🔗 [DexScreener](https://dexscreener.com/solana/{token_address}) | [Birdeye](https://birdeye.so/token/{token_address}?chain=solana) | [Token](https://solscan.io/token/{token_address}) | [Wallet](https://solscan.io/account/{wallet_address})"""

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

    def get_buy_alert_buttons(self, token_address: str) -> InlineKeyboardMarkup:
        """Generate inline buttons for BUY alerts (qualified, insider, watchlist)."""
        buttons = [
            [
                InlineKeyboardButton(
                    "🔒 CA ↗",
                    url=f"https://solscan.io/token/{token_address}"
                ),
                InlineKeyboardButton(
                    "👁 Scan ↗",
                    url=f"{SOULSCANNER_BOT}{token_address}"
                ),
            ]
        ]
        return InlineKeyboardMarkup(buttons)

    def format_win_milestone_alert(
        self,
        token_symbol: str,
        token_address: str,
        multiplier: float,
        entry_mcap: float,
        current_mcap: float,
        next_alert_link: str = None
    ) -> Tuple[str, InlineKeyboardMarkup]:
        """
        Format a WIN MILESTONE alert when token reaches 2x+ profit.

        Args:
            token_symbol: Token symbol (e.g., "PEPE")
            token_address: Token contract address
            multiplier: Current multiplier (e.g., 5.2 for 5.2x)
            entry_mcap: Market cap at entry
            current_mcap: Current market cap
            next_alert_link: Link to original buy alert message

        Returns:
            Tuple of (message_text, inline_keyboard)
        """
        # Format multiplier display
        if multiplier >= 100:
            mult_display = f"{int(multiplier)}x"
        elif multiplier >= 10:
            mult_display = f"{multiplier:.1f}x"
        else:
            mult_display = f"{multiplier:.1f}x"

        # Generate money bag emoji rows based on multiplier
        emoji_rows = self._get_money_emoji_rows(multiplier)

        # Format market caps
        entry_mcap_str = format_number(entry_mcap)
        current_mcap_str = format_number(current_mcap)

        # Build message
        message = f"""📈 ${token_symbol} is up {mult_display} 📈
from ⚡ Entry Signal

{entry_mcap_str} → {current_mcap_str}

{emoji_rows}"""

        # Build buttons
        buttons = [
            [
                InlineKeyboardButton(
                    "🔒 CA ↗",
                    url=f"https://solscan.io/token/{token_address}"
                ),
                InlineKeyboardButton(
                    "👁 Scan ↗",
                    url=f"{SOULSCANNER_BOT}{token_address}"
                ),
            ]
        ]

        # Add "Next" button if we have a link to the original alert
        if next_alert_link:
            buttons[0].append(
                InlineKeyboardButton(
                    "🔑 Next ↗",
                    url=next_alert_link
                )
            )

        keyboard = InlineKeyboardMarkup(buttons)

        return message, keyboard

    def _get_money_emoji_rows(self, multiplier: float) -> str:
        """
        Generate money bag emoji rows based on multiplier.

        Scaling:
        - 2x-5x: 1 row (10 💸)
        - 5x-10x: 2 rows (20 💸)
        - 10x-20x: 3 rows (30 💸)
        - 20x-50x: 4 rows (40 💸)
        - 50x+: 5 rows (50 💸)
        """
        row = "💸" * 10

        if multiplier < 5:
            num_rows = 1
        elif multiplier < 10:
            num_rows = 2
        elif multiplier < 20:
            num_rows = 3
        elif multiplier < 50:
            num_rows = 4
        else:
            num_rows = 5

        return "\n".join([row] * num_rows)
