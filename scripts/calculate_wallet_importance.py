#!/usr/bin/env python3
"""
Dynamic Wallet Importance Scoring

Calculates importance scores based on position lifecycle outcomes:
- +5 points for 10x+ tokens (caught early moons)
- +3 points for 5x+ tokens
- +2 points for 3x+ tokens
- +1 point for 2x+ tokens
- -1 point for rugs (rugged tokens they bought)

Score = Sum of all points / sqrt(total_positions)
(Normalized to prevent high-volume traders from dominating)

Cron schedule (daily at 3 AM):
    0 3 * * * cd /root/Soulwinners && ./venv/bin/python3 scripts/calculate_wallet_importance.py >> logs/wallet_importance.log 2>&1

Usage:
    python scripts/calculate_wallet_importance.py [--force] [--stats]
"""
import argparse
import logging
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Scoring weights
POINTS = {
    '10x': 5,
    '5x': 3,
    '3x': 2,
    '2x': 1,
    'rug': -1,
}


def is_cron_enabled() -> bool:
    """Check if wallet_importance cron is enabled."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT enabled FROM cron_states WHERE cron_name = 'wallet_importance'")
        row = cursor.fetchone()
        conn.close()
        return bool(row[0]) if row else True
    except:
        return True


def get_scoring_weights() -> Dict[str, int]:
    """Load scoring weights from settings."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        weights = {}
        for key, default in [
            ('importance_10x_points', 5),
            ('importance_5x_points', 3),
            ('importance_3x_points', 2),
            ('importance_2x_points', 1),
            ('importance_rug_penalty', -1),
        ]:
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            weights[key] = int(row[0]) if row else default

        conn.close()
        return {
            '10x': weights['importance_10x_points'],
            '5x': weights['importance_5x_points'],
            '3x': weights['importance_3x_points'],
            '2x': weights['importance_2x_points'],
            'rug': weights['importance_rug_penalty'],
        }
    except:
        return POINTS


def calculate_wallet_importance():
    """
    Calculate importance scores for all wallets based on lifecycle outcomes.

    Uses position_lifecycle data to score wallets by their token outcomes.
    """
    logger.info("=" * 60)
    logger.info("WALLET IMPORTANCE CALCULATION")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    points = get_scoring_weights()
    logger.info(f"Scoring weights: {points}")

    conn = get_connection()
    cursor = conn.cursor()

    stats = {
        'wallets_scored': 0,
        'wallets_updated': 0,
        'wallets_new': 0,
        'total_runners': 0,
        'total_rugs': 0,
        'errors': 0,
    }

    try:
        # Get all wallets with labeled positions
        cursor.execute("""
            SELECT
                wallet_address,
                COUNT(*) as total_positions,
                -- Outcome counts
                SUM(CASE WHEN outcome = 'runner' THEN 1 ELSE 0 END) as runner_count,
                SUM(CASE WHEN outcome = 'rug' THEN 1 ELSE 0 END) as rug_count,
                SUM(CASE WHEN outcome = 'sideways' THEN 1 ELSE 0 END) as sideways_count,
                -- Multi-bagger counts (from token peak ROI)
                SUM(CASE WHEN final_roi_percent >= 900 THEN 1 ELSE 0 END) as tokens_10x,
                SUM(CASE WHEN final_roi_percent >= 400 AND final_roi_percent < 900 THEN 1 ELSE 0 END) as tokens_5x,
                SUM(CASE WHEN final_roi_percent >= 200 AND final_roi_percent < 400 THEN 1 ELSE 0 END) as tokens_3x,
                SUM(CASE WHEN final_roi_percent >= 100 AND final_roi_percent < 200 THEN 1 ELSE 0 END) as tokens_2x
            FROM position_lifecycle
            WHERE outcome IS NOT NULL
            AND outcome != 'open'
            GROUP BY wallet_address
            HAVING total_positions >= 3
        """)

        wallet_data = cursor.fetchall()
        logger.info(f"Found {len(wallet_data)} wallets with labeled positions")

        for row in wallet_data:
            wallet_addr = row[0]
            total_positions = row[1]
            runner_count = row[2] or 0
            rug_count = row[3] or 0
            sideways_count = row[4] or 0
            tokens_10x = row[5] or 0
            tokens_5x = row[6] or 0
            tokens_3x = row[7] or 0
            tokens_2x = row[8] or 0

            try:
                # Calculate raw score
                raw_score = (
                    tokens_10x * points['10x'] +
                    tokens_5x * points['5x'] +
                    tokens_3x * points['3x'] +
                    tokens_2x * points['2x'] +
                    rug_count * points['rug']
                )

                # Normalize by sqrt of total positions
                # This rewards quality over quantity
                importance_score = raw_score / math.sqrt(max(total_positions, 1))

                # Update or insert into wallet_global_pool
                cursor.execute("""
                    INSERT INTO wallet_global_pool (
                        wallet_address, importance_score, importance_updated_at,
                        runner_count, rug_count, sideways_count,
                        tokens_2x_plus, tokens_3x_plus, tokens_5x_plus, tokens_10x_plus
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(wallet_address) DO UPDATE SET
                        importance_score = excluded.importance_score,
                        importance_updated_at = excluded.importance_updated_at,
                        runner_count = excluded.runner_count,
                        rug_count = excluded.rug_count,
                        sideways_count = excluded.sideways_count,
                        tokens_2x_plus = excluded.tokens_2x_plus,
                        tokens_3x_plus = excluded.tokens_3x_plus,
                        tokens_5x_plus = excluded.tokens_5x_plus,
                        tokens_10x_plus = excluded.tokens_10x_plus,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    wallet_addr, importance_score, datetime.now().isoformat(),
                    runner_count, rug_count, sideways_count,
                    tokens_2x + tokens_3x + tokens_5x + tokens_10x,  # 2x+ cumulative
                    tokens_3x + tokens_5x + tokens_10x,  # 3x+ cumulative
                    tokens_5x + tokens_10x,  # 5x+ cumulative
                    tokens_10x,  # 10x+
                ))

                stats['wallets_scored'] += 1
                stats['total_runners'] += runner_count
                stats['total_rugs'] += rug_count

                if importance_score > 5:
                    logger.info(
                        f"⭐ High importance: {wallet_addr[:12]}... "
                        f"score={importance_score:.2f} "
                        f"(10x:{tokens_10x}, 5x:{tokens_5x}, rugs:{rug_count})"
                    )

            except Exception as e:
                logger.warning(f"Error scoring wallet {wallet_addr[:12]}...: {e}")
                stats['errors'] += 1

        conn.commit()

        # Get top performers
        cursor.execute("""
            SELECT wallet_address, importance_score, tokens_10x_plus, rug_count
            FROM wallet_global_pool
            WHERE importance_score IS NOT NULL
            ORDER BY importance_score DESC
            LIMIT 10
        """)

        top_wallets = cursor.fetchall()

        logger.info("\n" + "=" * 60)
        logger.info("TOP 10 WALLETS BY IMPORTANCE SCORE")
        logger.info("=" * 60)

        for i, (addr, score, x10, rugs) in enumerate(top_wallets, 1):
            logger.info(f"#{i}: {addr[:12]}... | Score: {score:.2f} | 10x: {x10} | Rugs: {rugs}")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("CALCULATION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Wallets scored: {stats['wallets_scored']}")
        logger.info(f"Total runners tracked: {stats['total_runners']}")
        logger.info(f"Total rugs tracked: {stats['total_rugs']}")
        logger.info(f"Errors: {stats['errors']}")

        return stats

    except Exception as e:
        logger.error(f"Error calculating wallet importance: {e}")
        raise

    finally:
        conn.close()


def show_stats():
    """Display wallet importance statistics."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Overall stats
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                AVG(importance_score) as avg_score,
                MAX(importance_score) as max_score,
                MIN(importance_score) as min_score,
                SUM(tokens_10x_plus) as total_10x,
                SUM(rug_count) as total_rugs
            FROM wallet_global_pool
            WHERE importance_score IS NOT NULL
        """)

        row = cursor.fetchone()

        print("\n" + "=" * 60)
        print("WALLET IMPORTANCE STATISTICS")
        print("=" * 60)
        print(f"Wallets scored: {row[0]:,}")
        print(f"Average score: {row[1]:.2f}" if row[1] else "N/A")
        print(f"Max score: {row[2]:.2f}" if row[2] else "N/A")
        print(f"Min score: {row[3]:.2f}" if row[3] else "N/A")
        print(f"Total 10x tokens caught: {row[4] or 0:,}")
        print(f"Total rugs: {row[5] or 0:,}")

        # Score distribution
        print("\nScore Distribution:")
        cursor.execute("""
            SELECT
                CASE
                    WHEN importance_score >= 10 THEN 'Elite (10+)'
                    WHEN importance_score >= 5 THEN 'High (5-10)'
                    WHEN importance_score >= 2 THEN 'Mid (2-5)'
                    WHEN importance_score >= 0 THEN 'Low (0-2)'
                    ELSE 'Negative (<0)'
                END as tier,
                COUNT(*) as count
            FROM wallet_global_pool
            WHERE importance_score IS NOT NULL
            GROUP BY tier
            ORDER BY MIN(importance_score) DESC
        """)

        for tier, count in cursor.fetchall():
            print(f"  {tier}: {count:,}")

        # Top 5 wallets
        print("\nTop 5 by Importance:")
        cursor.execute("""
            SELECT wallet_address, importance_score, tokens_10x_plus, tokens_5x_plus, rug_count
            FROM wallet_global_pool
            WHERE importance_score IS NOT NULL
            ORDER BY importance_score DESC
            LIMIT 5
        """)

        for i, (addr, score, x10, x5, rugs) in enumerate(cursor.fetchall(), 1):
            print(f"  #{i}: {addr[:8]}...{addr[-4:]} | Score: {score:.2f} | 10x: {x10} | 5x: {x5} | Rugs: {rugs}")

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Calculate dynamic wallet importance scores"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if cron is disabled"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show statistics only"
    )

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    # Check if cron is enabled
    if not args.force and not is_cron_enabled():
        logger.info("Wallet importance calculation is DISABLED (cron_states)")
        return

    calculate_wallet_importance()


if __name__ == "__main__":
    main()
