#!/usr/bin/env python3
"""
Insider Wallet Analyzer
Independently calculates performance stats for insider wallets.

Insiders are tracked for PATTERN (launch sniping, migration sniping),
not for meeting qualification thresholds. This script analyzes their
actual trading performance.

Run weekly or when new insiders are detected.
"""
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiohttp
from database import get_connection
from collectors.helius import HeliusRotator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
TRANSACTION_LOOKBACK_DAYS = 30
MAX_TRANSACTIONS = 100  # Per wallet
RATE_LIMIT_DELAY = 1.5  # Seconds between API calls

# Skip tokens (stablecoins, wrapped SOL)
SKIP_TOKENS = {
    'So11111111111111111111111111111111111111112',   # WSOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
}


class InsiderAnalyzer:
    """Analyze insider wallet trading performance."""

    def __init__(self):
        self.rotator = HeliusRotator(use_premium=False)  # Use free keys
        self.base_url = "https://api.helius.xyz/v0"

    async def get_insider_wallets(self) -> List[Dict]:
        """Load all insider wallets from database."""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT wallet_address, pattern, confidence,
                   win_rate, avg_roi, discovered_at
            FROM insider_pool
        """)

        columns = ['wallet_address', 'pattern', 'confidence',
                   'win_rate', 'avg_roi', 'discovered_at']
        rows = cursor.fetchall()
        conn.close()

        insiders = []
        for row in rows:
            insiders.append(dict(zip(columns, row)))

        return insiders

    async def fetch_transactions(self, wallet_addr: str) -> List[Dict]:
        """Fetch recent transactions for a wallet."""
        api_key = await self.rotator.get_key()
        url = f"{self.base_url}/addresses/{wallet_addr}/transactions"
        params = {
            'api-key': api_key,
            'limit': MAX_TRANSACTIONS,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    if response.status == 429:
                        logger.warning(f"Rate limited, waiting...")
                        await asyncio.sleep(5)
                        return await self.fetch_transactions(wallet_addr)

                    if response.status != 200:
                        logger.warning(f"API error {response.status} for {wallet_addr[:12]}...")
                        return []

                    return await response.json()

        except Exception as e:
            logger.error(f"Failed to fetch transactions for {wallet_addr[:12]}...: {e}")
            return []

    def parse_swap(self, tx: Dict, wallet_addr: str) -> Optional[Dict]:
        """Parse a swap transaction."""
        try:
            token_transfers = tx.get('tokenTransfers', [])
            native_transfers = tx.get('nativeTransfers', [])

            if not token_transfers:
                return None

            # Find the main token (not SOL/stables)
            main_transfer = None
            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                if mint not in SKIP_TOKENS:
                    main_transfer = transfer
                    break

            if not main_transfer:
                return None

            # Calculate SOL amount
            sol_amount = 0
            for nt in native_transfers:
                amount = abs(nt.get('amount', 0)) / 1e9
                if nt.get('fromUserAccount') == wallet_addr:
                    sol_amount += amount  # SOL out = buying
                elif nt.get('toUserAccount') == wallet_addr:
                    sol_amount -= amount  # SOL in = selling

            # Determine buy or sell
            is_buy = main_transfer.get('toUserAccount') == wallet_addr
            tx_type = 'buy' if is_buy else 'sell'

            return {
                'signature': tx.get('signature'),
                'type': tx_type,
                'token_address': main_transfer.get('mint'),
                'sol_amount': abs(sol_amount),
                'timestamp': tx.get('timestamp', 0),
            }

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    def calculate_stats(self, swaps: List[Dict]) -> Dict:
        """
        Calculate trading statistics from parsed swaps.

        Tracks positions and calculates:
        - Win rate (profitable trades / total closed trades)
        - ROI (total profit / total invested)
        - Avg buy size
        - Total trades
        """
        if not swaps:
            return {
                'win_rate': 0,
                'avg_roi': 0,
                'avg_buy_sol': 0,
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
            }

        # Track positions: token -> {sol_spent, buys}
        positions: Dict[str, Dict] = {}

        # Track closed trades for win/loss calculation
        closed_trades = []
        buy_amounts = []

        # Sort by timestamp (oldest first)
        swaps_sorted = sorted(swaps, key=lambda x: x.get('timestamp', 0))

        for swap in swaps_sorted:
            token = swap['token_address']
            sol_amount = swap['sol_amount']
            tx_type = swap['type']

            if tx_type == 'buy':
                # Record buy
                if token not in positions:
                    positions[token] = {'sol_spent': 0, 'buys': 0}
                positions[token]['sol_spent'] += sol_amount
                positions[token]['buys'] += 1
                buy_amounts.append(sol_amount)

            elif tx_type == 'sell':
                # Close position (fully or partially)
                if token in positions and positions[token]['sol_spent'] > 0:
                    entry_sol = positions[token]['sol_spent']
                    exit_sol = sol_amount

                    # Calculate P/L
                    pnl_pct = ((exit_sol - entry_sol) / entry_sol * 100) if entry_sol > 0 else 0

                    closed_trades.append({
                        'token': token,
                        'entry_sol': entry_sol,
                        'exit_sol': exit_sol,
                        'pnl_pct': pnl_pct,
                        'profitable': pnl_pct > 0,
                    })

                    # Clear position (simplified - full close)
                    del positions[token]

        # Calculate stats
        total_closed = len(closed_trades)
        wins = sum(1 for t in closed_trades if t['profitable'])
        losses = total_closed - wins

        win_rate = wins / total_closed if total_closed > 0 else 0

        # Calculate average ROI
        if closed_trades:
            total_pnl = sum(t['pnl_pct'] for t in closed_trades)
            avg_roi = total_pnl / len(closed_trades)
        else:
            avg_roi = 0

        # Average buy size
        avg_buy_sol = sum(buy_amounts) / len(buy_amounts) if buy_amounts else 0

        return {
            'win_rate': win_rate,
            'avg_roi': avg_roi,
            'avg_buy_sol': avg_buy_sol,
            'total_trades': len(buy_amounts),
            'closed_trades': total_closed,
            'wins': wins,
            'losses': losses,
            'open_positions': len(positions),
        }

    async def analyze_wallet(self, wallet_addr: str) -> Dict:
        """Analyze a single wallet's trading performance."""
        logger.info(f"Analyzing {wallet_addr[:12]}...")

        # Fetch transactions
        transactions = await self.fetch_transactions(wallet_addr)

        if not transactions:
            logger.warning(f"  No transactions found")
            return {'error': 'no_transactions'}

        # Filter to recent transactions (within lookback period)
        cutoff = (datetime.now() - timedelta(days=TRANSACTION_LOOKBACK_DAYS)).timestamp()
        recent_txs = [tx for tx in transactions if tx.get('timestamp', 0) >= cutoff]

        logger.info(f"  Found {len(recent_txs)} transactions in last {TRANSACTION_LOOKBACK_DAYS} days")

        # Parse swaps
        swaps = []
        for tx in recent_txs:
            parsed = self.parse_swap(tx, wallet_addr)
            if parsed:
                swaps.append(parsed)

        logger.info(f"  Parsed {len(swaps)} swaps (buys/sells)")

        # Calculate stats
        stats = self.calculate_stats(swaps)

        logger.info(f"  Stats: WR={stats['win_rate']*100:.0f}% | ROI={stats['avg_roi']:+.0f}% | "
                   f"Trades={stats['total_trades']} | W/L={stats['wins']}/{stats['losses']}")

        return stats

    async def update_insider_stats(self, wallet_addr: str, stats: Dict):
        """Update insider_pool with calculated stats."""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE insider_pool
            SET win_rate = ?,
                avg_roi = ?,
                last_updated = ?
            WHERE wallet_address = ?
        """, (
            stats.get('win_rate', 0),
            stats.get('avg_roi', 0),
            datetime.now().isoformat(),
            wallet_addr,
        ))

        conn.commit()
        conn.close()

        logger.info(f"  Updated stats in database")

    async def run(self):
        """Run the full insider analysis."""
        logger.info("=" * 60)
        logger.info("INSIDER WALLET ANALYZER")
        logger.info("=" * 60)

        # Get all insider wallets
        insiders = await self.get_insider_wallets()
        logger.info(f"Found {len(insiders)} insider wallets to analyze")

        if not insiders:
            logger.warning("No insider wallets found in database")
            return

        # Track aggregate stats
        total_analyzed = 0
        total_with_trades = 0
        aggregate_win_rate = 0
        aggregate_roi = 0

        # Analyze each wallet
        for i, insider in enumerate(insiders, 1):
            wallet_addr = insider['wallet_address']
            pattern = insider.get('pattern', 'Unknown')

            logger.info(f"\n[{i}/{len(insiders)}] {pattern}")

            try:
                stats = await self.analyze_wallet(wallet_addr)

                if 'error' not in stats:
                    # Update database
                    await self.update_insider_stats(wallet_addr, stats)

                    total_analyzed += 1
                    if stats.get('total_trades', 0) > 0:
                        total_with_trades += 1
                        aggregate_win_rate += stats.get('win_rate', 0)
                        aggregate_roi += stats.get('avg_roi', 0)

                # Rate limiting
                await asyncio.sleep(RATE_LIMIT_DELAY)

            except Exception as e:
                logger.error(f"  Error analyzing wallet: {e}")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("ANALYSIS COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total wallets analyzed: {total_analyzed}")
        logger.info(f"Wallets with trades: {total_with_trades}")

        if total_with_trades > 0:
            avg_wr = aggregate_win_rate / total_with_trades
            avg_roi = aggregate_roi / total_with_trades
            logger.info(f"Average win rate: {avg_wr*100:.1f}%")
            logger.info(f"Average ROI: {avg_roi:+.1f}%")

        logger.info("=" * 60)


async def analyze_single_wallet(wallet_address: str) -> Dict:
    """
    Analyze a single wallet - useful when new insider is detected.

    Returns the calculated stats.
    """
    analyzer = InsiderAnalyzer()
    stats = await analyzer.analyze_wallet(wallet_address)

    if 'error' not in stats:
        await analyzer.update_insider_stats(wallet_address, stats)

    return stats


async def main():
    """Main entry point."""
    import sys

    # Check for single wallet argument
    if len(sys.argv) > 1:
        wallet = sys.argv[1]
        logger.info(f"Analyzing single wallet: {wallet}")
        stats = await analyze_single_wallet(wallet)
        print(f"Stats: {stats}")
        return

    # Full analysis
    analyzer = InsiderAnalyzer()
    await analyzer.run()


if __name__ == "__main__":
    asyncio.run(main())
