#!/usr/bin/env python3
"""Restore wallets from wallet_metrics table to qualified_wallets."""
from database import get_connection
from datetime import datetime

def restore_from_metrics():
    conn = get_connection()
    cursor = conn.cursor()

    # Get current qualified wallets
    cursor.execute("SELECT wallet_address FROM qualified_wallets")
    current = set(row[0] for row in cursor.fetchall())
    print(f"Current qualified: {len(current)}")

    # Get wallets from wallet_metrics that pass relaxed thresholds
    cursor.execute('''
        SELECT wallet_address, source, roi_pct, median_roi_pct,
               profit_token_ratio, trade_frequency, roi_per_trade,
               x10_ratio, x20_ratio, x50_ratio, x100_ratio,
               median_hold_time, profit_per_hold_second,
               cluster, cluster_label, cluster_name,
               roi_final, priority_score, tier, strategy_bucket,
               current_balance_sol, total_trades
        FROM wallet_metrics
        WHERE current_balance_sol >= 5
        AND total_trades >= 10
        AND profit_token_ratio >= 0.5
        AND roi_pct >= 30
        ORDER BY priority_score DESC
    ''')
    potential_wallets = cursor.fetchall()
    print(f"Potential wallets from metrics: {len(potential_wallets)}")

    # Insert wallets not already in qualified_wallets
    restored = 0
    for row in potential_wallets:
        wallet = row[0]
        if wallet not in current:
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
                    row[0],  # wallet_address
                    row[1],  # source
                    row[2],  # roi_pct
                    row[3],  # median_roi_pct
                    row[4],  # profit_token_ratio
                    row[5],  # trade_frequency
                    row[6],  # roi_per_trade
                    row[7],  # x10_ratio
                    row[8],  # x20_ratio
                    row[9],  # x50_ratio
                    row[10], # x100_ratio
                    row[11], # median_hold_time
                    row[12], # profit_per_hold_second
                    row[13], # cluster
                    row[14], # cluster_label
                    row[15], # cluster_name
                    row[16], # roi_final
                    row[17], # priority_score
                    row[18], # tier
                    row[19], # strategy_bucket
                    row[20], # current_balance_sol
                    row[21], # total_trades
                    row[4],  # win_rate (same as profit_token_ratio)
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
    print(f"Restored {restored} wallets from wallet_metrics")
    print(f"Final qualified_wallets count: {final_count}")

    # Show tier breakdown
    cursor.execute("SELECT tier, COUNT(*) FROM qualified_wallets GROUP BY tier")
    print("Tier breakdown:")
    for tier, count in cursor.fetchall():
        print(f"  {tier}: {count}")

    conn.close()

if __name__ == "__main__":
    restore_from_metrics()
