#!/usr/bin/env python3
"""Restore wallets from backup CSV to qualified_wallets table."""
import pandas as pd
from database import get_connection
from datetime import datetime

def restore_wallets():
    conn = get_connection()
    cursor = conn.cursor()

    # Get current qualified wallets
    cursor.execute("SELECT wallet_address FROM qualified_wallets")
    current = set(row[0] for row in cursor.fetchall())
    print(f"Current qualified: {len(current)}")

    # Read the oldest backup which has the original wallets
    df_backup = pd.read_csv("data/df_ranked_20260224_095824.csv")
    print(f"Backup has: {len(df_backup)} wallets")

    # Restore wallets from backup that are not currently in qualified_wallets
    restored = 0
    for _, row in df_backup.iterrows():
        wallet = row.get("wallet_address")
        if wallet and wallet not in current:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO qualified_wallets (
                        wallet_address, source, roi_pct, median_roi_pct,
                        profit_token_ratio, trade_frequency, roi_per_trade,
                        x10_ratio, x20_ratio, x50_ratio, x100_ratio,
                        median_hold_time, profit_per_hold_second,
                        cluster, cluster_label, cluster_name,
                        roi_final, priority_score, tier, strategy_bucket,
                        current_balance_sol, total_trades, win_rate,
                        qualified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    wallet,
                    row.get("source", "restored"),
                    row.get("roi_pct", 0),
                    row.get("median_roi_pct", 0),
                    row.get("profit_token_ratio", 0),
                    row.get("trade_frequency", 0),
                    row.get("roi_per_trade", 0),
                    row.get("x10_ratio", 0),
                    row.get("x20_ratio", 0),
                    row.get("x50_ratio", 0),
                    row.get("x100_ratio", 0),
                    row.get("median_hold_time", 0),
                    row.get("profit_per_hold_second", 0),
                    row.get("cluster", 0),
                    row.get("cluster_label", ""),
                    row.get("cluster_name", "Restored"),
                    row.get("roi_final", 0),
                    row.get("priority_score", 0),
                    row.get("tier", "Watchlist"),
                    row.get("strategy_bucket", "Restored"),
                    row.get("current_balance_sol", 0),
                    row.get("total_trades", 0),
                    row.get("profit_token_ratio", 0),
                    datetime.now().isoformat()
                ))
                restored += 1
                current.add(wallet)
            except Exception as e:
                print(f"Error restoring {wallet}: {e}")

    conn.commit()

    # Check final count
    cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
    final_count = cursor.fetchone()[0]
    print(f"Restored {restored} wallets from backup")
    print(f"Final qualified_wallets count: {final_count}")

    conn.close()

if __name__ == "__main__":
    restore_wallets()
