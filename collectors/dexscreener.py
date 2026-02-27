"""
DexScreener Wallet Collector
Collects profitable wallets from DEX trading (Raydium, Jupiter, Orca)
FIXED: Now tracks SOL value per token for accurate win rate
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging

from .base import BaseCollector
from config.settings import DEXSCREENER_RATE_LIMIT
from .helius import helius_rotator

logger = logging.getLogger(__name__)

# Headers to bypass Cloudflare protection
CLOUDFLARE_BYPASS_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Origin': 'https://dexscreener.com',
    'Referer': 'https://dexscreener.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

# Skip these tokens (stablecoins, wrapped SOL)
SKIP_TOKENS = {
    'So11111111111111111111111111111111111111112',  # WSOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
}


class DexScreenerCollector(BaseCollector):
    """Collector for DEX trading wallets via DexScreener."""

    def __init__(self):
        super().__init__(rate_limit=DEXSCREENER_RATE_LIMIT)
        self.dexscreener_base = "https://api.dexscreener.com"
        self.rotator = helius_rotator  # Use API key rotation for 4x capacity

    def get_source_name(self) -> str:
        return "dex"

    async def get_trending_tokens(self) -> List[Dict]:
        """Get trending Solana tokens from DexScreener."""
        url = f"{self.dexscreener_base}/token-boosts/top/v1"
        result = await self.fetch_with_retry(url, headers=CLOUDFLARE_BYPASS_HEADERS)
        if not result:
            return []
        return [t for t in result if t.get('chainId') == 'solana'][:50]

    async def get_token_traders(self, token_address: str) -> List[str]:
        """Get wallets that traded a token using Helius with key rotation and retry."""
        for attempt in range(3):
            api_key = await self.rotator.get_key()
            url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions?api-key={api_key}&limit=100"
            txs = await self.fetch_with_retry(url)
            if txs:
                wallets = set()
                for tx in txs:
                    if 'feePayer' in tx:
                        wallets.add(tx['feePayer'])
                return list(wallets)
            await asyncio.sleep(1)
        return []

    async def get_wallet_transactions(self, wallet: str) -> List[Dict]:
        """Get transaction history for a wallet with key rotation and retry."""
        for attempt in range(3):
            api_key = await self.rotator.get_key()
            url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions?api-key={api_key}&limit=100"
            result = await self.fetch_with_retry(url)
            if result:
                return result
            await asyncio.sleep(1)
        return []

    async def get_wallet_balances(self, wallet: str) -> Dict:
        """Get current balances for a wallet with key rotation and retry."""
        for attempt in range(3):
            api_key = await self.rotator.get_key()
            url = f"https://api.helius.xyz/v0/addresses/{wallet}/balances?api-key={api_key}"
            result = await self.fetch_with_retry(url)
            if result:
                return result
            await asyncio.sleep(1)
        return {}

    async def analyze_wallet_dex_performance(self, wallet: str) -> Dict[str, Any]:
        """
        Analyze a wallet's DEX trading performance.
        FIXED: Now tracks SOL value per token for accurate win rate.
        """
        transactions = await self.get_wallet_transactions(wallet)
        balances = await self.get_wallet_balances(wallet)

        if not transactions:
            return None

        # Get timestamps
        timestamps = [tx.get('timestamp', 0) for tx in transactions if tx.get('timestamp')]
        first_trade = min(timestamps) if timestamps else 0
        days_since_first = max(1, int((datetime.now().timestamp() - first_trade) / 86400)) if first_trade else 30

        # Initialize metrics
        metrics = {
            "wallet_address": wallet,
            "source": "dex",
            "days_since_first_trade": days_since_first,
            "pnl_sol": 0,
            "roi_percent": 0,
            "median_roi_percent": 0,
            "median_hold_time_seconds": 0,
            "unique_tokens_traded": 0,
            "tokens_net_profit": 0,
            "buy_transactions": 0,
            "sell_transactions": 0,
            "current_balance_sol": 0,
            "total_sol_spent": 0,
            "total_sol_earned": 0,
            "win_rate": 0,
            "tokens_less_10x": 0,
            "tokens_10x_plus": 0,
            "tokens_20x_plus": 0,
            "tokens_50x_plus": 0,
            "tokens_100x_plus": 0,
        }

        # Extract SOL balance
        if balances and 'nativeBalance' in balances:
            metrics['current_balance_sol'] = balances['nativeBalance'] / 1e9

        # Track SOL spent/earned PER TOKEN for accurate profit calculation
        token_positions = {}  # token -> {'sol_spent': x, 'sol_earned': y, 'first_buy': ts, 'last_sell': ts}

        for tx in transactions:
            timestamp = tx.get('timestamp', 0)
            token_transfers = tx.get('tokenTransfers', [])
            native_transfers = tx.get('nativeTransfers', [])

            # Build SOL transfer totals for this tx
            sol_out = 0
            sol_in = 0

            for nt in native_transfers:
                amount = abs(nt.get('amount', 0)) / 1e9
                if nt.get('fromUserAccount') == wallet:
                    sol_out += amount
                elif nt.get('toUserAccount') == wallet:
                    sol_in += amount

            # Process token transfers
            for transfer in token_transfers:
                token_mint = transfer.get('mint', '')
                if not token_mint or token_mint in SKIP_TOKENS:
                    continue

                if token_mint not in token_positions:
                    token_positions[token_mint] = {
                        'sol_spent': 0,
                        'sol_earned': 0,
                        'first_buy': None,
                        'last_sell': None
                    }

                to_user = transfer.get('toUserAccount', '')
                from_user = transfer.get('fromUserAccount', '')

                if to_user == wallet:
                    # BUY
                    metrics['buy_transactions'] += 1
                    token_positions[token_mint]['sol_spent'] += sol_out
                    if not token_positions[token_mint]['first_buy']:
                        token_positions[token_mint]['first_buy'] = timestamp
                    metrics['total_sol_spent'] += sol_out
                    sol_out = 0

                elif from_user == wallet:
                    # SELL
                    metrics['sell_transactions'] += 1
                    token_positions[token_mint]['sol_earned'] += sol_in
                    token_positions[token_mint]['last_sell'] = timestamp
                    metrics['total_sol_earned'] += sol_in
                    sol_in = 0

        # Calculate metrics from token positions
        metrics['unique_tokens_traded'] = len(token_positions)
        profitable_tokens = 0
        total_closed = 0
        hold_times = []
        rois = []

        for token, pos in token_positions.items():
            sol_spent = pos['sol_spent']
            sol_earned = pos['sol_earned']

            if sol_spent > 0 and sol_earned > 0:
                total_closed += 1
                profit = sol_earned - sol_spent

                if profit > 0:
                    profitable_tokens += 1
                    metrics['tokens_net_profit'] += 1

                    roi_multiple = sol_earned / sol_spent
                    rois.append(roi_multiple)

                    if roi_multiple >= 100:
                        metrics['tokens_100x_plus'] += 1
                    elif roi_multiple >= 50:
                        metrics['tokens_50x_plus'] += 1
                    elif roi_multiple >= 20:
                        metrics['tokens_20x_plus'] += 1
                    elif roi_multiple >= 10:
                        metrics['tokens_10x_plus'] += 1
                    else:
                        metrics['tokens_less_10x'] += 1

                # Calculate hold time
                if pos['first_buy'] and pos['last_sell']:
                    hold_time = pos['last_sell'] - pos['first_buy']
                    if hold_time > 0:
                        hold_times.append(hold_time)

        # Win rate
        if total_closed > 0:
            metrics['win_rate'] = profitable_tokens / total_closed
        else:
            metrics['win_rate'] = 0

        # Median hold time
        if hold_times:
            hold_times.sort()
            metrics['median_hold_time_seconds'] = hold_times[len(hold_times) // 2]

        # ROI calculations
        if rois:
            rois.sort()
            metrics['median_roi_percent'] = (rois[len(rois) // 2] - 1) * 100
            avg_roi = sum(rois) / len(rois)
            metrics['roi_percent'] = (avg_roi - 1) * 100

        # Overall PnL
        metrics['pnl_sol'] = metrics['total_sol_earned'] - metrics['total_sol_spent']

        return metrics

    async def collect_wallets(self, target_count: int = 500) -> List[Dict[str, Any]]:
        """Collect profitable DEX trading wallets."""
        logger.info(f"Starting DexScreener wallet collection, target: {target_count}")

        # Get trending tokens
        trending = await self.get_trending_tokens()
        logger.info(f"Found {len(trending)} trending Solana tokens")

        # Collect wallets from trending token traders
        all_wallets = set()
        for token in trending[:20]:
            token_addr = token.get('tokenAddress')
            if token_addr:
                traders = await self.get_token_traders(token_addr)
                all_wallets.update(traders)
                await asyncio.sleep(0.2)

        logger.info(f"Found {len(all_wallets)} unique wallets from trending tokens")

        # Analyze each wallet
        results = []
        for wallet in list(all_wallets)[:target_count]:
            try:
                metrics = await self.analyze_wallet_dex_performance(wallet)
                if metrics and metrics['buy_transactions'] > 0:
                    results.append(metrics)
                    if len(results) % 50 == 0:
                        logger.info(f"Analyzed {len(results)} wallets")
            except Exception as e:
                logger.error(f"Error analyzing wallet {wallet}: {e}")

            await asyncio.sleep(0.1)

        logger.info(f"Collected {len(results)} DEX wallets")
        return results


async def main():
    """Test the collector."""
    async with DexScreenerCollector() as collector:
        wallets = await collector.collect_wallets(target_count=10)
        for w in wallets[:3]:
            print(f"\nWallet: {w['wallet_address'][:20]}...")
            print(f"  SOL Balance: {w['current_balance_sol']:.2f}")
            print(f"  Days Active: {w['days_since_first_trade']}")
            print(f"  Win Rate: {w['win_rate']:.1%}")
            print(f"  ROI: {w['roi_percent']:.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
