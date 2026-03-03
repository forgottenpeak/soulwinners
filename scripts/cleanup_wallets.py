#!/usr/bin/env python3
"""
Weekly Wallet Cleanup Script - FIXED VERSION
Removes stale and underperforming wallets from qualified_wallets pool.

FIXES:
- Proper last activity detection (no more 999 days bug)
- Checks ALL transaction types, not just SWAP
- Cross-references with transactions table
- Conservative removal (only truly inactive wallets)

Run weekly via cron: 0 0 * * 0 /root/Soulwinners/venv/bin/python3 /root/Soulwinners/scripts/cleanup_wallets.py
Run immediately with: python scripts/cleanup_wallets.py --immediate
Dry run: python scripts/cleanup_wallets.py --dry-run
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
from collectors.helius import HeliusClient

# Configure logging
log_dir = Path(__file__).parent.parent / 'logs'
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / 'cleanup.log')
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# CLEANUP CRITERIA (Conservative - only remove truly bad wallets)
# =============================================================================
CLEANUP_CRITERIA = {
    'inactive_days': 90,          # Remove if no trades in 90+ days
    'min_win_rate': 0.40,         # Remove if win rate below 40% (very lenient)
    'min_roi': -50.0,             # Remove if ROI below -50% (major loser)
    'consecutive_losses': 5,       # Remove if 5+ losses in a row
    'lookback_days': 30,          # Check last 30 days of performance
    'min_trades_for_judgment': 5,  # Need at least 5 trades to judge performance
}


class WalletCleanup:
    """Handles wallet cleanup and performance re-analysis."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.helius = HeliusClient()  # Uses proper key rotation
        self.removed_wallets: List[Dict] = []
        self.stats_before: Dict = {}
        self.stats_after: Dict = {}

    def get_current_pool(self) -> pd.DataFrame:
        """Get all wallets from qualified_wallets table."""
        conn = get_connection()
        df = pd.read_sql_query("""
            SELECT * FROM qualified_wallets
            ORDER BY priority_score DESC
        """, conn)
        conn.close()
        return df

    def get_last_activity_from_db(self, wallet_address: str) -> Optional[datetime]:
        """
        Check our local transactions table for last activity.
        This is a fallback when Helius API doesn't return data.
        """
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT MAX(timestamp) FROM transactions
                WHERE wallet_address = ?
            """, (wallet_address,))
            result = cursor.fetchone()
            if result and result[0]:
                return datetime.fromisoformat(result[0])
        except Exception as e:
            logger.debug(f"DB lookup failed for {wallet_address[:8]}...: {e}")
        finally:
            conn.close()
        return None

    async def get_last_activity_from_helius(
        self,
        wallet_address: str,
    ) -> Tuple[Optional[datetime], int]:
        """
        Fetch REAL last activity from Helius API using key rotation.
        Returns (last_activity_date, transaction_count_30d)
        """
        try:
            # Use HeliusClient with proper key rotation
            data = await self.helius.get_transaction_history(wallet_address, limit=100)

            if not data:
                return None, 0

            # Get last transaction timestamp
            last_timestamp = data[0].get('timestamp', 0)
            if last_timestamp:
                last_activity = datetime.fromtimestamp(last_timestamp)
            else:
                last_activity = None

            # Count transactions in last 30 days
            cutoff = datetime.now() - timedelta(days=30)
            recent_count = 0
            for tx in data:
                tx_time = tx.get('timestamp', 0)
                if tx_time:
                    tx_date = datetime.fromtimestamp(tx_time)
                    if tx_date >= cutoff:
                        recent_count += 1
                    else:
                        break  # Transactions are sorted newest first

            return last_activity, recent_count

        except Exception as e:
            logger.debug(f"Error fetching transactions for {wallet_address[:8]}...: {e}")
            return None, -1

    async def analyze_wallet_activity(
        self,
        wallet_address: str
    ) -> Dict[str, Any]:
        """
        Comprehensive activity analysis combining API and DB data.
        """
        result = {
            'last_activity': None,
            'last_activity_days_ago': None,
            'recent_trade_count': 0,
            'source': 'unknown',
            'is_active': True,  # Assume active until proven otherwise
        }

        # Try Helius API first
        api_activity, api_count = await self.get_last_activity_from_helius(wallet_address)

        if api_count == -1:
            # Rate limited or error - check DB as fallback
            db_activity = self.get_last_activity_from_db(wallet_address)
            if db_activity:
                result['last_activity'] = db_activity
                result['last_activity_days_ago'] = (datetime.now() - db_activity).days
                result['source'] = 'database'
                result['is_active'] = result['last_activity_days_ago'] < CLEANUP_CRITERIA['inactive_days']
            else:
                # Can't determine - assume active (conservative)
                result['source'] = 'unknown_assume_active'
                result['is_active'] = True
            return result

        if api_activity:
            result['last_activity'] = api_activity
            result['last_activity_days_ago'] = (datetime.now() - api_activity).days
            result['recent_trade_count'] = api_count
            result['source'] = 'helius_api'
            result['is_active'] = result['last_activity_days_ago'] < CLEANUP_CRITERIA['inactive_days']
        else:
            # API returned empty - check DB as fallback
            db_activity = self.get_last_activity_from_db(wallet_address)
            if db_activity:
                result['last_activity'] = db_activity
                result['last_activity_days_ago'] = (datetime.now() - db_activity).days
                result['source'] = 'database_fallback'
                result['is_active'] = result['last_activity_days_ago'] < CLEANUP_CRITERIA['inactive_days']
            else:
                # Truly no activity found anywhere
                result['last_activity_days_ago'] = 999
                result['source'] = 'no_data'
                result['is_active'] = False

        return result

    async def analyze_recent_performance(
        self,
        wallet_address: str,
    ) -> Dict[str, Any]:
        """
        Analyze recent trading performance from Helius using key rotation.
        """
        result = {
            'trade_count': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': None,  # None = not enough data
            'consecutive_losses': 0,
            'pnl_sol': 0,
        }

        try:
            # Use HeliusClient with proper key rotation
            data = await self.helius.get_transaction_history(wallet_address, limit=50)

            if not data:
                return result

            # Analyze only SWAP transactions for performance
            cutoff = datetime.now() - timedelta(days=CLEANUP_CRITERIA['lookback_days'])
            current_streak = 0
            max_consecutive_losses = 0

            for tx in data:
                tx_time = tx.get('timestamp', 0)
                if tx_time and datetime.fromtimestamp(tx_time) < cutoff:
                    break

                # Only analyze swap transactions for win/loss
                tx_type = tx.get('type', '')
                if 'SWAP' not in tx_type.upper():
                    continue

                result['trade_count'] += 1

                # Analyze PnL from native transfers
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
                result['pnl_sol'] += net

                if net > 0:
                    result['wins'] += 1
                    current_streak = 0
                elif net < 0:
                    result['losses'] += 1
                    current_streak += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_streak)

            result['consecutive_losses'] = max_consecutive_losses

            # Calculate win rate only if we have enough trades
            total = result['wins'] + result['losses']
            if total >= CLEANUP_CRITERIA['min_trades_for_judgment']:
                result['win_rate'] = result['wins'] / total

            return result

        except Exception as e:
            logger.debug(f"Error analyzing performance for {wallet_address[:8]}...: {e}")
            return result

    def should_remove_wallet(
        self,
        wallet_data: Dict,
        activity: Dict,
        performance: Dict
    ) -> Tuple[bool, str]:
        """
        Determine if a wallet should be removed based on criteria.
        CONSERVATIVE: Only remove wallets that clearly meet removal criteria.

        Returns:
            Tuple of (should_remove, reason)
        """
        reasons = []

        # Check 1: Truly inactive (confirmed no activity)
        if activity['source'] == 'no_data':
            # Only remove if we're confident there's no data
            reasons.append(f"no activity data found")
        elif activity['last_activity_days_ago'] and activity['last_activity_days_ago'] >= CLEANUP_CRITERIA['inactive_days']:
            reasons.append(f"inactive {activity['last_activity_days_ago']} days")

        # Check 2: Very poor win rate (only if we have enough data)
        if performance['win_rate'] is not None:
            if performance['win_rate'] < CLEANUP_CRITERIA['min_win_rate']:
                reasons.append(f"low win rate ({performance['win_rate']*100:.0f}%)")

        # Check 3: Major ROI loss
        stored_roi = wallet_data.get('roi_pct', 0)
        if stored_roi < CLEANUP_CRITERIA['min_roi']:
            reasons.append(f"severe loss ({stored_roi:.0f}% ROI)")

        # Check 4: Extended losing streak (only with enough trades)
        if performance['trade_count'] >= CLEANUP_CRITERIA['min_trades_for_judgment']:
            if performance['consecutive_losses'] >= CLEANUP_CRITERIA['consecutive_losses']:
                reasons.append(f"losing streak ({performance['consecutive_losses']} losses)")

        if reasons:
            return True, "; ".join(reasons)
        return False, ""

    async def analyze_and_cleanup(self, batch_size: int = 10) -> Dict[str, Any]:
        """
        Main cleanup process:
        1. Load all wallets
        2. Re-analyze activity and performance
        3. Remove only truly problematic wallets
        4. Calculate before/after stats
        """
        logger.info("=" * 60)
        logger.info("STARTING WALLET CLEANUP (FIXED VERSION)")
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
        skipped_count = 0

        logger.info(f"\nAnalyzing {total_wallets} wallets in batches of {batch_size}...")
        logger.info(f"Criteria: inactive>{CLEANUP_CRITERIA['inactive_days']}d, "
                   f"win_rate<{CLEANUP_CRITERIA['min_win_rate']*100}%, "
                   f"ROI<{CLEANUP_CRITERIA['min_roi']}%, "
                   f"losses>={CLEANUP_CRITERIA['consecutive_losses']}")

        wallet_list = df.to_dict('records')

        for i in range(0, len(wallet_list), batch_size):
            batch = wallet_list[i:i+batch_size]

            for wallet in batch:
                wallet_addr = wallet['wallet_address']

                # Get activity data
                activity = await self.analyze_wallet_activity(wallet_addr)

                # Get performance data (only if potentially inactive)
                performance = {'trade_count': 0, 'wins': 0, 'losses': 0,
                             'win_rate': None, 'consecutive_losses': 0, 'pnl_sol': 0}

                if not activity['is_active'] or activity['source'] == 'unknown_assume_active':
                    # Check performance for inactive or unknown wallets
                    performance = await self.analyze_recent_performance(wallet_addr)

                # Make decision
                should_remove, reason = self.should_remove_wallet(wallet, activity, performance)

                if should_remove:
                    wallets_to_remove.append({
                        'wallet_address': wallet_addr,
                        'tier': wallet.get('tier', 'Unknown'),
                        'roi_pct': wallet.get('roi_pct', 0),
                        'win_rate': wallet.get('win_rate', wallet.get('profit_token_ratio', 0)),
                        'reason': reason,
                        'last_activity': activity.get('last_activity'),
                        'activity_source': activity.get('source'),
                    })
                    logger.info(
                        f"  REMOVE: {wallet_addr[:12]}... "
                        f"({wallet.get('tier', 'Unknown')}) - {reason}"
                    )
                else:
                    wallets_to_keep.append(wallet)
                    if activity['source'] == 'unknown_assume_active':
                        skipped_count += 1

                # Small delay between wallets
                await asyncio.sleep(0.2)

            logger.info(f"  Processed {min(i+batch_size, total_wallets)}/{total_wallets} wallets...")
            await asyncio.sleep(1)  # Longer pause between batches

        self.removed_wallets = wallets_to_remove

        logger.info(f"\nSkipped {skipped_count} wallets due to uncertain status (assumed active)")

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
        """Remove wallets from qualified_wallets table and archive them."""
        if not wallet_addresses:
            return 0

        conn = get_connection()
        cursor = conn.cursor()

        # Archive removed wallets with full data
        for addr in wallet_addresses:
            wallet_info = next((w for w in self.removed_wallets
                               if w['wallet_address'] == addr), {})
            cursor.execute("""
                INSERT OR REPLACE INTO wallet_cleanup_log (
                    wallet_address,
                    removed_at,
                    reason,
                    roi_at_removal,
                    win_rate_at_removal,
                    tier_at_removal
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                addr,
                datetime.now().isoformat(),
                wallet_info.get('reason', 'unknown'),
                wallet_info.get('roi_pct', 0),
                wallet_info.get('win_rate', 0),
                wallet_info.get('tier', 'Unknown'),
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

        logger.info(f"Removed {removed} wallets from database (archived in cleanup_log)")
        return removed

    def _log_summary(self, total: int, removed: int, kept: int):
        """Log cleanup summary with before/after comparison."""
        logger.info("\n" + "=" * 60)
        logger.info("CLEANUP SUMMARY")
        logger.info("=" * 60)

        actual_removed = len(self.removed_wallets) if self.dry_run else removed

        logger.info(f"\nPool Changes:")
        logger.info(f"  Before: {total} wallets")
        logger.info(f"  Removed: {actual_removed} wallets ({actual_removed/total*100:.1f}%)" if total > 0 else "  Removed: 0")
        logger.info(f"  After: {total - actual_removed} wallets")

        if self.stats_before:
            logger.info(f"\nStatistics (IQR Filtered):")
            if 'roi_pct' in self.stats_before:
                logger.info(f"  BEFORE - Robust ROI: {self.stats_before['roi_pct']['robust_mean']:.0f}%")
            if self.stats_after and 'roi_pct' in self.stats_after:
                logger.info(f"  AFTER  - Robust ROI: {self.stats_after['roi_pct']['robust_mean']:.0f}%")

        if self.removed_wallets:
            logger.info(f"\nRemoved Wallets ({len(self.removed_wallets)}):")
            for w in self.removed_wallets[:15]:
                logger.info(f"  {w['wallet_address'][:12]}... [{w['tier']}] - {w['reason']}")
            if len(self.removed_wallets) > 15:
                logger.info(f"  ... and {len(self.removed_wallets) - 15} more")

        logger.info("\n" + "=" * 60)

        # Save removal log to file
        self._save_removal_log()

    def _save_removal_log(self):
        """Save removal log to CSV for review."""
        if not self.removed_wallets:
            return

        DATA_DIR.mkdir(exist_ok=True)
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
            win_rate_at_removal REAL,
            tier_at_removal TEXT,
            days_inactive INTEGER,
            consecutive_losses INTEGER
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
    parser = argparse.ArgumentParser(description='Weekly Wallet Cleanup Script (FIXED)')
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
    sys.exit(0)


if __name__ == "__main__":
    main()
