#!/usr/bin/env python3
"""
Weekly Wallet Cleanup Script
Removes stale and underperforming wallets from qualified_wallets pool.

Run weekly via cron: 0 0 * * 0 /root/Soulwinners/venv/bin/python3 /root/Soulwinners/scripts/cleanup_wallets.py
Run immediately with: python scripts/cleanup_wallets.py --immediate
"""
import sys
import os
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any, Optional
import asyncio
import aiohttp

from database import get_connection
from config.settings import (
    DATABASE_PATH, HELIUS_FREE_KEYS, DATA_DIR,
    MIN_WIN_RATE, MIN_ROI
)
from utils.statistics import (
    calculate_pool_robust_stats,
    robust_stats,
    cap_impossible_values,
    get_performance_health_score
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent.parent / 'logs' / 'cleanup.log')
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# CLEANUP CRITERIA
# =============================================================================
CLEANUP_CRITERIA = {
    'inactive_days': 90,          # Remove if no trades in X days
    'min_win_rate': 0.50,         # Remove if win rate dropped below 50%
    'min_roi': 0.0,               # Remove if ROI dropped below 0%
    'consecutive_losses': 3,       # Remove if 3+ losses in a row (recent)
    'lookback_days': 30,          # Check last 30 days of performance
}


class WalletCleanup:
    """Handles wallet cleanup and performance re-analysis."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.api_keys = HELIUS_FREE_KEYS.copy()
        self.key_index = 0
        self.removed_wallets: List[Dict] = []
        self.stats_before: Dict = {}
        self.stats_after: Dict = {}

    def get_api_key(self) -> str:
        """Rotate through API keys."""
        key = self.api_keys[self.key_index % len(self.api_keys)]
        self.key_index += 1
        return key

    def get_current_pool(self) -> pd.DataFrame:
        """Get all wallets from qualified_wallets table."""
        conn = get_connection()
        df = pd.read_sql_query("""
            SELECT * FROM qualified_wallets
            ORDER BY priority_score DESC
        """, conn)
        conn.close()
        return df

    async def get_recent_transactions(
        self,
        wallet_address: str,
        days: int = 30
    ) -> List[Dict]:
        """Fetch recent transactions for a wallet from Helius."""
        api_key = self.get_api_key()
        url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/transactions"

        params = {
            'api-key': api_key,
            'type': 'SWAP',
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        # Filter to recent transactions
                        cutoff = datetime.now() - timedelta(days=days)
                        recent = []
                        for tx in data[:50]:  # Check last 50 transactions
                            timestamp = tx.get('timestamp', 0)
                            tx_date = datetime.fromtimestamp(timestamp)
                            if tx_date >= cutoff:
                                recent.append(tx)
                        return recent
                    return []
        except Exception as e:
            logger.debug(f"Error fetching transactions for {wallet_address[:8]}...: {e}")
            return []

    def analyze_recent_performance(
        self,
        transactions: List[Dict]
    ) -> Dict[str, Any]:
        """Analyze recent transaction performance."""
        if not transactions:
            return {
                'trade_count': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'consecutive_losses': 0,
                'last_trade_days_ago': 999,
                'pnl_sol': 0,
            }

        wins = 0
        losses = 0
        consecutive_losses = 0
        max_consecutive_losses = 0
        current_streak = 0
        pnl_sol = 0

        # Sort by timestamp (newest first)
        sorted_txs = sorted(transactions, key=lambda x: x.get('timestamp', 0), reverse=True)

        for tx in sorted_txs:
            # Simplified PnL analysis from transaction data
            native_transfers = tx.get('nativeTransfers', [])

            sol_in = sum(
                t.get('amount', 0) / 1e9
                for t in native_transfers
                if t.get('toUserAccount') == tx.get('feePayer')
            )
            sol_out = sum(
                t.get('amount', 0) / 1e9
                for t in native_transfers
                if t.get('fromUserAccount') == tx.get('feePayer')
            )

            net = sol_in - sol_out
            pnl_sol += net

            if net > 0:
                wins += 1
                current_streak = 0
            else:
                losses += 1
                current_streak += 1
                max_consecutive_losses = max(max_consecutive_losses, current_streak)

        # Calculate last trade days ago
        if sorted_txs:
            last_timestamp = sorted_txs[0].get('timestamp', 0)
            last_date = datetime.fromtimestamp(last_timestamp)
            last_trade_days = (datetime.now() - last_date).days
        else:
            last_trade_days = 999

        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0

        return {
            'trade_count': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'consecutive_losses': max_consecutive_losses,
            'last_trade_days_ago': last_trade_days,
            'pnl_sol': pnl_sol,
        }

    def should_remove_wallet(
        self,
        wallet_data: Dict,
        recent_perf: Dict
    ) -> Tuple[bool, str]:
        """
        Determine if a wallet should be removed based on criteria.

        Returns:
            Tuple of (should_remove, reason)
        """
        reasons = []

        # Check 1: Inactive for too long
        last_trade_days = recent_perf.get('last_trade_days_ago', 999)
        if last_trade_days >= CLEANUP_CRITERIA['inactive_days']:
            reasons.append(f"inactive ({last_trade_days} days)")

        # Check 2: Win rate dropped below threshold
        # Use recent win rate if available, otherwise current stored value
        recent_win_rate = recent_perf.get('win_rate')
        stored_win_rate = wallet_data.get('win_rate', wallet_data.get('profit_token_ratio', 0))

        if recent_perf['trade_count'] >= 5:  # Need enough data
            if recent_win_rate < CLEANUP_CRITERIA['min_win_rate']:
                reasons.append(f"low win rate ({recent_win_rate*100:.0f}%)")
        elif stored_win_rate < CLEANUP_CRITERIA['min_win_rate']:
            reasons.append(f"low win rate ({stored_win_rate*100:.0f}%)")

        # Check 3: ROI dropped below threshold
        stored_roi = wallet_data.get('roi_pct', 0)
        if stored_roi < CLEANUP_CRITERIA['min_roi'] * 100:
            reasons.append(f"negative ROI ({stored_roi:.0f}%)")

        # Check 4: Too many consecutive losses
        if recent_perf['consecutive_losses'] >= CLEANUP_CRITERIA['consecutive_losses']:
            reasons.append(f"losing streak ({recent_perf['consecutive_losses']} losses)")

        if reasons:
            return True, "; ".join(reasons)
        return False, ""

    async def analyze_and_cleanup(self, batch_size: int = 20) -> Dict[str, Any]:
        """
        Main cleanup process:
        1. Load all wallets
        2. Re-analyze recent performance
        3. Remove underperforming wallets
        4. Calculate before/after stats
        """
        logger.info("=" * 60)
        logger.info("STARTING WALLET CLEANUP")
        logger.info("=" * 60)

        # Get current pool
        df = self.get_current_pool()
        total_wallets = len(df)
        logger.info(f"Current pool size: {total_wallets} wallets")

        if total_wallets == 0:
            logger.warning("No wallets in pool!")
            return {'total': 0, 'removed': 0, 'kept': 0}

        # Calculate stats BEFORE cleanup
        df = cap_impossible_values(df)
        self.stats_before = calculate_pool_robust_stats(df)

        # Analyze each wallet
        wallets_to_remove = []
        wallets_to_keep = []

        logger.info(f"\nAnalyzing {total_wallets} wallets in batches of {batch_size}...")

        wallet_list = df.to_dict('records')

        for i in range(0, len(wallet_list), batch_size):
            batch = wallet_list[i:i+batch_size]

            tasks = []
            for wallet in batch:
                tasks.append(self.get_recent_transactions(
                    wallet['wallet_address'],
                    days=CLEANUP_CRITERIA['lookback_days']
                ))

            # Fetch transactions in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for wallet, txs in zip(batch, results):
                if isinstance(txs, Exception):
                    txs = []

                recent_perf = self.analyze_recent_performance(txs)
                should_remove, reason = self.should_remove_wallet(wallet, recent_perf)

                if should_remove:
                    wallets_to_remove.append({
                        'wallet_address': wallet['wallet_address'],
                        'tier': wallet.get('tier', 'Unknown'),
                        'roi_pct': wallet.get('roi_pct', 0),
                        'win_rate': wallet.get('win_rate', wallet.get('profit_token_ratio', 0)),
                        'reason': reason,
                    })
                    logger.info(
                        f"  REMOVE: {wallet['wallet_address'][:12]}... "
                        f"({wallet.get('tier', 'Unknown')}) - {reason}"
                    )
                else:
                    wallets_to_keep.append(wallet)

            logger.info(f"  Processed {min(i+batch_size, total_wallets)}/{total_wallets} wallets...")
            await asyncio.sleep(0.5)  # Rate limiting

        self.removed_wallets = wallets_to_remove

        # Perform removal
        removed_count = 0
        if wallets_to_remove and not self.dry_run:
            removed_count = self._remove_wallets_from_db(
                [w['wallet_address'] for w in wallets_to_remove]
            )

        # Calculate stats AFTER cleanup
        df_after = self.get_current_pool()
        if len(df_after) > 0:
            df_after = cap_impossible_values(df_after)
            self.stats_after = calculate_pool_robust_stats(df_after)

        # Log summary
        self._log_summary(total_wallets, removed_count, len(wallets_to_keep))

        return {
            'total': total_wallets,
            'removed': removed_count if not self.dry_run else len(wallets_to_remove),
            'kept': len(wallets_to_keep),
            'removed_wallets': wallets_to_remove,
            'stats_before': self.stats_before,
            'stats_after': self.stats_after,
        }

    def _remove_wallets_from_db(self, wallet_addresses: List[str]) -> int:
        """Remove wallets from qualified_wallets table."""
        if not wallet_addresses:
            return 0

        conn = get_connection()
        cursor = conn.cursor()

        # Archive removed wallets first
        for addr in wallet_addresses:
            cursor.execute("""
                INSERT OR REPLACE INTO wallet_cleanup_log (
                    wallet_address,
                    removed_at,
                    reason
                ) VALUES (?, ?, ?)
            """, (
                addr,
                datetime.now().isoformat(),
                next((w['reason'] for w in self.removed_wallets
                      if w['wallet_address'] == addr), 'unknown')
            ))

        # Remove from qualified_wallets
        placeholders = ','.join(['?' for _ in wallet_addresses])
        cursor.execute(
            f"DELETE FROM qualified_wallets WHERE wallet_address IN ({placeholders})",
            wallet_addresses
        )

        removed = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"Removed {removed} wallets from database")
        return removed

    def _log_summary(self, total: int, removed: int, kept: int):
        """Log cleanup summary with before/after comparison."""
        logger.info("\n" + "=" * 60)
        logger.info("CLEANUP SUMMARY")
        logger.info("=" * 60)

        logger.info(f"\nPool Changes:")
        logger.info(f"  Before: {total} wallets")
        logger.info(f"  Removed: {removed} wallets ({removed/total*100:.1f}%)" if total > 0 else "  Removed: 0")
        logger.info(f"  After: {kept} wallets")

        if self.stats_before and self.stats_after:
            logger.info(f"\nROI Statistics:")
            if 'roi_pct' in self.stats_before:
                logger.info(f"  BEFORE - Raw: {self.stats_before['roi_pct']['raw_mean']:.0f}%, "
                           f"Robust: {self.stats_before['roi_pct']['robust_mean']:.0f}%")
            if 'roi_pct' in self.stats_after:
                logger.info(f"  AFTER  - Raw: {self.stats_after['roi_pct']['raw_mean']:.0f}%, "
                           f"Robust: {self.stats_after['roi_pct']['robust_mean']:.0f}%")

            logger.info(f"\nWin Rate Statistics:")
            wr_key = 'win_rate' if 'win_rate' in self.stats_before else 'profit_token_ratio'
            if wr_key in self.stats_before:
                logger.info(f"  BEFORE - Raw: {self.stats_before[wr_key]['raw_mean']*100:.0f}%, "
                           f"Robust: {self.stats_before[wr_key]['robust_mean']*100:.0f}%")
            if wr_key in self.stats_after:
                logger.info(f"  AFTER  - Raw: {self.stats_after[wr_key]['raw_mean']*100:.0f}%, "
                           f"Robust: {self.stats_after[wr_key]['robust_mean']*100:.0f}%")

        if self.removed_wallets:
            logger.info(f"\nRemoved Wallets:")
            for w in self.removed_wallets[:10]:  # Show first 10
                logger.info(f"  {w['wallet_address'][:12]}... [{w['tier']}] - {w['reason']}")
            if len(self.removed_wallets) > 10:
                logger.info(f"  ... and {len(self.removed_wallets) - 10} more")

        logger.info("\n" + "=" * 60)

        # Save removal log to file
        self._save_removal_log()

    def _save_removal_log(self):
        """Save removal log to CSV for review."""
        if not self.removed_wallets:
            return

        log_path = DATA_DIR / f"cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df = pd.DataFrame(self.removed_wallets)
        df.to_csv(log_path, index=False)
        logger.info(f"Removal log saved to: {log_path}")


def ensure_cleanup_log_table():
    """Create wallet_cleanup_log table if it doesn't exist."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_cleanup_log (
            wallet_address TEXT PRIMARY KEY,
            removed_at TIMESTAMP,
            reason TEXT,
            roi_at_removal REAL,
            win_rate_at_removal REAL
        )
    """)
    conn.commit()
    conn.close()


async def run_cleanup(dry_run: bool = False, immediate: bool = False):
    """Run the cleanup process."""
    # Ensure log directory exists
    log_dir = Path(__file__).parent.parent / 'logs'
    log_dir.mkdir(exist_ok=True)

    # Ensure cleanup log table exists
    ensure_cleanup_log_table()

    if dry_run:
        logger.info("DRY RUN MODE - No wallets will be removed")

    cleanup = WalletCleanup(dry_run=dry_run)
    result = await cleanup.analyze_and_cleanup()

    return result


def main():
    parser = argparse.ArgumentParser(description='Weekly Wallet Cleanup Script')
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Run analysis without removing wallets'
    )
    parser.add_argument(
        '--immediate', '-i',
        action='store_true',
        help='Run cleanup immediately (not just scheduled)'
    )
    args = parser.parse_args()

    logger.info(f"Starting cleanup script at {datetime.now()}")

    result = asyncio.run(run_cleanup(
        dry_run=args.dry_run,
        immediate=args.immediate
    ))

    # Exit with appropriate code
    if result['removed'] > 0 or args.dry_run:
        sys.exit(0)
    else:
        logger.info("No wallets needed removal")
        sys.exit(0)


if __name__ == "__main__":
    main()
