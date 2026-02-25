"""
Optimized Wallet Collector
- Pre-filters by balance (>= 40 SOL)
- Parallel processing (20 wallets simultaneously)
- Progress bar
- Caching
"""
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict, Set, Optional
import logging

from config.settings import HELIUS_API_KEY, MIN_SOL_BALANCE, MIN_TRADES_30D
from database import get_connection

logger = logging.getLogger(__name__)


class OptimizedCollector:
    """Fast wallet collector with pre-filtering and parallel processing."""

    def __init__(self):
        self.api_key = HELIUS_API_KEY
        self.base_url = f"https://api.helius.xyz/v0"
        self.semaphore = asyncio.Semaphore(20)  # 20 concurrent requests
        self.session: Optional[aiohttp.ClientSession] = None
        self.cached_wallets: Set[str] = set()
        self._load_cache()

    def _load_cache(self):
        """Load previously analyzed wallets from database."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT wallet_address FROM wallet_metrics")
            self.cached_wallets = {row[0] for row in cursor.fetchall()}
            conn.close()
            logger.info(f"Loaded {len(self.cached_wallets)} cached wallets")
        except:
            self.cached_wallets = set()

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def get_wallet_balance(self, wallet: str) -> float:
        """Quick balance check for pre-filtering."""
        url = f"{self.base_url}/addresses/{wallet}/balances?api-key={self.api_key}"

        try:
            async with self.semaphore:
                async with self.session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('nativeBalance', 0) / 1e9
        except:
            pass
        return 0

    async def pre_filter_wallets(
        self,
        wallets: List[str],
        min_sol: float = MIN_SOL_BALANCE
    ) -> List[str]:
        """
        Pre-filter wallets by balance BEFORE full analysis.
        This can cut 800 wallets down to ~50.
        """
        logger.info(f"Pre-filtering {len(wallets)} wallets (>= {min_sol} SOL)...")

        # Skip already cached wallets
        new_wallets = [w for w in wallets if w not in self.cached_wallets]
        logger.info(f"  New wallets (not in cache): {len(new_wallets)}")

        if not new_wallets:
            return []

        # Check balances in parallel
        qualified = []
        batch_size = 50

        for i in range(0, len(new_wallets), batch_size):
            batch = new_wallets[i:i + batch_size]
            tasks = [self.get_wallet_balance(w) for w in batch]
            balances = await asyncio.gather(*tasks)

            for wallet, balance in zip(batch, balances):
                if balance >= min_sol:
                    qualified.append(wallet)

            progress = min(i + batch_size, len(new_wallets))
            pct = progress / len(new_wallets) * 100
            logger.info(f"  Pre-filter progress: {progress}/{len(new_wallets)} ({pct:.0f}%) - {len(qualified)} qualified")

        logger.info(f"Pre-filter complete: {len(qualified)} wallets with >= {min_sol} SOL")
        return qualified

    async def analyze_wallet_parallel(self, wallet: str) -> Optional[Dict]:
        """Analyze a single wallet with rate limiting."""
        async with self.semaphore:
            return await self._analyze_wallet(wallet)

    async def _analyze_wallet(self, wallet: str) -> Optional[Dict]:
        """Full wallet analysis."""
        # Get transactions
        url = f"{self.base_url}/addresses/{wallet}/transactions?api-key={self.api_key}&limit=100"

        try:
            async with self.session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                txs = await resp.json()
        except:
            return None

        if not txs:
            return None

        # Get balance
        balance = await self.get_wallet_balance(wallet)

        # Parse transactions
        metrics = {
            'wallet_address': wallet,
            'source': 'optimized',
            'current_balance_sol': balance,
            'buy_transactions': 0,
            'sell_transactions': 0,
            'unique_tokens_traded': set(),
            'total_sol_spent': 0,
            'total_sol_earned': 0,
            'profitable_trades': 0,
            'total_closed_trades': 0,
            'tokens_10x_plus': 0,
            'tokens_20x_plus': 0,
            'tokens_50x_plus': 0,
            'tokens_100x_plus': 0,
        }

        # Track token positions
        token_positions = {}  # token -> {'buy_sol': x, 'sell_sol': y}

        for tx in txs:
            self._parse_transaction(tx, wallet, metrics, token_positions)

        # Calculate derived metrics
        metrics['unique_tokens_traded'] = len(metrics['unique_tokens_traded'])
        total_trades = metrics['buy_transactions'] + metrics['sell_transactions']
        metrics['total_trades'] = total_trades

        # Calculate win rate from token positions
        for token, pos in token_positions.items():
            buy_sol = pos.get('buy_sol', 0)
            sell_sol = pos.get('sell_sol', 0)

            if buy_sol > 0 and sell_sol > 0:
                metrics['total_closed_trades'] += 1
                roi = (sell_sol - buy_sol) / buy_sol

                if roi > 0:
                    metrics['profitable_trades'] += 1

                    if roi >= 99:  # 100x
                        metrics['tokens_100x_plus'] += 1
                    elif roi >= 49:  # 50x
                        metrics['tokens_50x_plus'] += 1
                    elif roi >= 19:  # 20x
                        metrics['tokens_20x_plus'] += 1
                    elif roi >= 9:  # 10x
                        metrics['tokens_10x_plus'] += 1

        # Win rate
        if metrics['total_closed_trades'] > 0:
            metrics['win_rate'] = metrics['profitable_trades'] / metrics['total_closed_trades']
        else:
            metrics['win_rate'] = 0

        # ROI
        if metrics['total_sol_spent'] > 0:
            net_pnl = metrics['total_sol_earned'] - metrics['total_sol_spent']
            metrics['roi_pct'] = (net_pnl / metrics['total_sol_spent']) * 100
        else:
            metrics['roi_pct'] = 0

        # Days active (estimate from first tx)
        if txs:
            first_ts = txs[-1].get('timestamp', 0)
            if first_ts:
                metrics['days_since_first_trade'] = max(1, int((datetime.now().timestamp() - first_ts) / 86400))
            else:
                metrics['days_since_first_trade'] = 30
        else:
            metrics['days_since_first_trade'] = 30

        return metrics

    def _parse_transaction(self, tx: Dict, wallet: str, metrics: Dict, positions: Dict):
        """Parse a single transaction."""
        token_transfers = tx.get('tokenTransfers', [])
        native_transfers = tx.get('nativeTransfers', [])

        # Skip stablecoins and wrapped SOL
        SKIP_TOKENS = {
            'So11111111111111111111111111111111111111112',  # WSOL
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
        }

        for transfer in token_transfers:
            mint = transfer.get('mint', '')
            if not mint or mint in SKIP_TOKENS:
                continue

            metrics['unique_tokens_traded'].add(mint)

            # Initialize position tracking
            if mint not in positions:
                positions[mint] = {'buy_sol': 0, 'sell_sol': 0}

            # Determine buy or sell
            to_user = transfer.get('toUserAccount', '')
            from_user = transfer.get('fromUserAccount', '')

            if to_user == wallet:
                # This is a BUY
                metrics['buy_transactions'] += 1

                # Get SOL amount from native transfers
                for nt in native_transfers:
                    if nt.get('fromUserAccount') == wallet:
                        sol_amount = abs(nt.get('amount', 0)) / 1e9
                        metrics['total_sol_spent'] += sol_amount
                        positions[mint]['buy_sol'] += sol_amount
                        break

            elif from_user == wallet:
                # This is a SELL
                metrics['sell_transactions'] += 1

                # Get SOL amount received
                for nt in native_transfers:
                    if nt.get('toUserAccount') == wallet:
                        sol_amount = abs(nt.get('amount', 0)) / 1e9
                        metrics['total_sol_earned'] += sol_amount
                        positions[mint]['sell_sol'] += sol_amount
                        break

    async def collect_and_analyze(
        self,
        wallet_addresses: List[str],
        target_count: int = 500
    ) -> List[Dict]:
        """
        Collect and analyze wallets with optimizations:
        1. Pre-filter by balance
        2. Parallel processing
        3. Progress tracking
        """
        logger.info(f"Starting optimized collection of {len(wallet_addresses)} wallets")

        # Step 1: Pre-filter by balance
        qualified = await self.pre_filter_wallets(wallet_addresses[:target_count * 3])

        if not qualified:
            logger.warning("No wallets passed pre-filter!")
            return []

        # Step 2: Full analysis in parallel
        logger.info(f"Analyzing {len(qualified)} pre-filtered wallets in parallel...")

        results = []
        batch_size = 20  # Process 20 at a time

        for i in range(0, len(qualified), batch_size):
            batch = qualified[i:i + batch_size]
            tasks = [self.analyze_wallet_parallel(w) for w in batch]
            batch_results = await asyncio.gather(*tasks)

            for result in batch_results:
                if result and result.get('total_trades', 0) > 0:
                    results.append(result)

            # Progress
            progress = min(i + batch_size, len(qualified))
            pct = progress / len(qualified) * 100
            logger.info(f"Analyzed {progress}/{len(qualified)} ({pct:.0f}%) - {len(results)} valid")

        logger.info(f"Collection complete: {len(results)} wallets analyzed")
        return results


async def test_optimized():
    """Test the optimized collector."""
    import sys
    sys.path.insert(0, '.')

    # Get some wallets from trending tokens
    url = "https://api.dexscreener.com/token-boosts/top/v1"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            tokens = [t.get('tokenAddress') for t in data if t.get('chainId') == 'solana'][:10]

    # Get traders from tokens
    wallets = set()
    async with aiohttp.ClientSession() as session:
        for token in tokens:
            url = f"https://api.helius.xyz/v0/addresses/{token}/transactions?api-key={HELIUS_API_KEY}&limit=50"
            async with session.get(url) as resp:
                if resp.status == 200:
                    txs = await resp.json()
                    for tx in txs:
                        fp = tx.get('feePayer')
                        if fp:
                            wallets.add(fp)

    print(f"Found {len(wallets)} wallets to analyze")

    # Run optimized collection
    async with OptimizedCollector() as collector:
        results = await collector.collect_and_analyze(list(wallets), target_count=50)

    print(f"\nResults: {len(results)} wallets analyzed")
    if results:
        print("\nTop 5 by balance:")
        sorted_results = sorted(results, key=lambda x: x.get('current_balance_sol', 0), reverse=True)
        for r in sorted_results[:5]:
            print(f"  {r['wallet_address'][:20]}... {r['current_balance_sol']:.2f} SOL, WR: {r['win_rate']:.1%}, ROI: {r['roi_pct']:.1f}%")


if __name__ == "__main__":
    asyncio.run(test_optimized())
