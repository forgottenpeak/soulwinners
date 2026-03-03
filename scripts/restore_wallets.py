#!/usr/bin/env python3
"""
Restore Wallets Script
Restores wallets that were incorrectly removed during cleanup.

Usage:
  # Restore specific wallet
  python scripts/restore_wallets.py --wallet 7BNaxx...

  # Restore all wallets removed in last cleanup
  python scripts/restore_wallets.py --restore-all

  # List removed wallets
  python scripts/restore_wallets.py --list

  # Restore and add to watchlist
  python scripts/restore_wallets.py --wallet 7BNaxx... --add-watchlist
"""
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import pandas as pd
from typing import List, Dict, Optional

from database import get_connection
from config.settings import DATABASE_PATH, DATA_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def list_removed_wallets(limit: int = 50) -> pd.DataFrame:
    """List recently removed wallets from cleanup log."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check what columns exist
    cursor.execute("PRAGMA table_info(wallet_cleanup_log)")
    columns = [row[1] for row in cursor.fetchall()]

    if not columns:
        conn.close()
        return pd.DataFrame()

    # Build query based on available columns
    select_cols = ['wallet_address']
    if 'removed_at' in columns:
        select_cols.append('removed_at')
    if 'reason' in columns:
        select_cols.append('reason')
    if 'roi_at_removal' in columns:
        select_cols.append('roi_at_removal')
    if 'win_rate_at_removal' in columns:
        select_cols.append('win_rate_at_removal')
    if 'tier_at_removal' in columns:
        select_cols.append('tier_at_removal')

    query = f"""
        SELECT {', '.join(select_cols)}
        FROM wallet_cleanup_log
        ORDER BY {'removed_at DESC' if 'removed_at' in columns else 'wallet_address'}
        LIMIT {limit}
    """

    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_wallet_from_backup(wallet_address: str) -> Optional[Dict]:
    """
    Try to get wallet data from wallet_metrics table or cleanup log.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Try wallet_metrics first (may have more complete data)
    cursor.execute("""
        SELECT * FROM wallet_metrics WHERE wallet_address = ?
    """, (wallet_address,))
    row = cursor.fetchone()

    if row:
        columns = [desc[0] for desc in cursor.description]
        conn.close()
        return dict(zip(columns, row))

    # Fall back to cleanup log
    cursor.execute("""
        SELECT * FROM wallet_cleanup_log WHERE wallet_address = ?
    """, (wallet_address,))
    row = cursor.fetchone()

    if row:
        columns = [desc[0] for desc in cursor.description]
        data = dict(zip(columns, row))
        # Convert cleanup log format to qualified_wallets format
        return {
            'wallet_address': data['wallet_address'],
            'roi_pct': data.get('roi_at_removal', 0),
            'win_rate': data.get('win_rate_at_removal', 0),
            'profit_token_ratio': data.get('win_rate_at_removal', 0),
            'tier': data.get('tier_at_removal', 'Mid-Tier'),
            'source': 'restored',
        }

    conn.close()
    return None


def restore_wallet(wallet_address: str, add_to_watchlist: bool = False) -> bool:
    """
    Restore a single wallet to qualified_wallets.
    """
    # Check if already exists
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT wallet_address FROM qualified_wallets WHERE wallet_address = ?",
        (wallet_address,)
    )
    exists = cursor.fetchone()

    if exists:
        logger.info(f"Wallet {wallet_address[:12]}... already in qualified_wallets")
        conn.close()
        return True

    # Get backup data
    wallet_data = get_wallet_from_backup(wallet_address)

    if not wallet_data:
        logger.warning(f"No backup data found for {wallet_address[:12]}...")
        # Create minimal entry
        wallet_data = {
            'wallet_address': wallet_address,
            'source': 'restored',
            'tier': 'High-Quality',  # Default tier
            'roi_pct': 0,
            'win_rate': 0.5,
            'profit_token_ratio': 0.5,
        }
        logger.info("Creating minimal entry with default values")

    # Insert into qualified_wallets
    cursor.execute("""
        INSERT OR REPLACE INTO qualified_wallets (
            wallet_address, source, roi_pct, median_roi_pct,
            profit_token_ratio, trade_frequency, roi_per_trade,
            x10_ratio, x20_ratio, x50_ratio, x100_ratio,
            median_hold_time, profit_per_hold_second,
            cluster, cluster_label, cluster_name,
            roi_final, priority_score, tier, strategy_bucket,
            current_balance_sol, total_trades, win_rate,
            qualified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        wallet_data.get('wallet_address'),
        wallet_data.get('source', 'restored'),
        wallet_data.get('roi_pct', 0),
        wallet_data.get('median_roi_pct', 0),
        wallet_data.get('profit_token_ratio', wallet_data.get('win_rate', 0.5)),
        wallet_data.get('trade_frequency', 1),
        wallet_data.get('roi_per_trade', 0),
        wallet_data.get('x10_ratio', 0),
        wallet_data.get('x20_ratio', 0),
        wallet_data.get('x50_ratio', 0),
        wallet_data.get('x100_ratio', 0),
        wallet_data.get('median_hold_time', 0),
        wallet_data.get('profit_per_hold_second', 0),
        wallet_data.get('cluster', 0),
        wallet_data.get('cluster_label', 'Restored'),
        wallet_data.get('cluster_name', 'Core Alpha (Active)'),
        wallet_data.get('roi_final', wallet_data.get('roi_pct', 0)),
        wallet_data.get('priority_score', 0.5),
        wallet_data.get('tier', 'High-Quality'),
        wallet_data.get('strategy_bucket', 'Restored'),
        wallet_data.get('current_balance_sol', 0),
        wallet_data.get('total_trades', 0),
        wallet_data.get('win_rate', wallet_data.get('profit_token_ratio', 0.5)),
        datetime.now().isoformat()
    ))

    # Remove from cleanup log
    cursor.execute(
        "DELETE FROM wallet_cleanup_log WHERE wallet_address = ?",
        (wallet_address,)
    )

    conn.commit()
    logger.info(f"Restored wallet {wallet_address[:12]}... to qualified_wallets")

    # Add to watchlist if requested
    if add_to_watchlist:
        add_wallet_to_watchlist(cursor, wallet_address)

    conn.close()
    return True


def add_wallet_to_watchlist(cursor, wallet_address: str):
    """Add wallet to user watchlist."""
    # Check if user_watchlists table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='user_watchlists'
    """)
    if not cursor.fetchone():
        logger.warning("user_watchlists table doesn't exist")
        return

    # Add to default watchlist (user_id = 0 for system)
    cursor.execute("""
        INSERT OR IGNORE INTO user_watchlists (user_id, wallet_address, added_at)
        VALUES (0, ?, ?)
    """, (wallet_address, datetime.now().isoformat()))
    logger.info(f"Added {wallet_address[:12]}... to system watchlist")


def restore_all_recent(hours: int = 24) -> int:
    """Restore all wallets removed in the last N hours."""
    conn = get_connection()
    cursor = conn.cursor()

    # Get wallets removed recently
    cursor.execute("""
        SELECT wallet_address FROM wallet_cleanup_log
        WHERE removed_at >= datetime('now', '-{} hours')
    """.format(hours))
    wallets = [row[0] for row in cursor.fetchall()]
    conn.close()

    if not wallets:
        logger.info(f"No wallets removed in the last {hours} hours")
        return 0

    logger.info(f"Found {len(wallets)} wallets to restore")
    restored = 0
    for addr in wallets:
        if restore_wallet(addr):
            restored += 1

    return restored


def main():
    parser = argparse.ArgumentParser(description='Restore Wallets Script')
    parser.add_argument(
        '--wallet', '-w',
        help='Specific wallet address to restore'
    )
    parser.add_argument(
        '--restore-all', '-a',
        action='store_true',
        help='Restore all wallets removed in last 24 hours'
    )
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List removed wallets'
    )
    parser.add_argument(
        '--add-watchlist',
        action='store_true',
        help='Also add restored wallet to watchlist'
    )
    parser.add_argument(
        '--hours',
        type=int,
        default=24,
        help='Hours to look back for --restore-all (default: 24)'
    )

    args = parser.parse_args()

    if args.list:
        df = list_removed_wallets()
        if len(df) == 0:
            print("No removed wallets found")
        else:
            print("\nRecently Removed Wallets:")
            print("=" * 80)
            for _, row in df.iterrows():
                print(f"  {row['wallet_address'][:16]}... | "
                      f"Tier: {row['tier_at_removal']} | "
                      f"ROI: {row['roi_at_removal']:.0f}% | "
                      f"Reason: {row['reason']}")
            print(f"\nTotal: {len(df)} wallets")
        return

    if args.wallet:
        success = restore_wallet(args.wallet, add_to_watchlist=args.add_watchlist)
        if success:
            print(f"Successfully restored {args.wallet[:16]}...")
        else:
            print(f"Failed to restore {args.wallet[:16]}...")
        return

    if args.restore_all:
        count = restore_all_recent(hours=args.hours)
        print(f"Restored {count} wallets")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
