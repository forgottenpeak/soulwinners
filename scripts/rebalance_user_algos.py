#!/usr/bin/env python3
"""
Weekly User Algorithm Rebalancing Script

Rebalances all users' personalized wallet feeds based on updated performance data.
Should be run weekly via cron.

Usage:
    python scripts/rebalance_user_algos.py [--user USER_ID] [--dry-run]

Cron schedule (every Sunday at 2 AM UTC):
    0 2 * * 0 cd /root/Soulwinners && python scripts/rebalance_user_algos.py >> logs/rebalance.log 2>&1
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from bot.personalized_algo import PersonalizedAlgo

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_all_users_with_config() -> list:
    """Get all users who have algorithm configurations."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, risk_tolerance, preferred_win_rate, preferred_roi,
               last_rebalanced
        FROM user_algo_config
        ORDER BY user_id
    """)

    users = []
    for row in cursor.fetchall():
        users.append({
            "user_id": row[0],
            "risk_tolerance": row[1],
            "preferred_win_rate": row[2],
            "preferred_roi": row[3],
            "last_rebalanced": row[4],
        })

    conn.close()
    return users


def rebalance_all_users(dry_run: bool = False) -> dict:
    """
    Rebalance wallet feeds for all users.

    Args:
        dry_run: If True, don't save changes

    Returns:
        Summary statistics
    """
    algo = PersonalizedAlgo()

    # First, update the global pool with latest wallet data
    logger.info("=" * 60)
    logger.info("STEP 1: Updating global wallet pool...")
    logger.info("=" * 60)

    pool_size = algo.populate_global_pool()
    logger.info(f"Global pool now has {pool_size} wallets")

    # Get all users
    users = get_all_users_with_config()
    logger.info(f"\nFound {len(users)} users with algorithm configurations")

    if not users:
        logger.warning("No users to rebalance. Run personalized_algo.py to create configs.")
        return {"users_processed": 0, "total_wallets_assigned": 0}

    # Rebalance each user
    logger.info("=" * 60)
    logger.info("STEP 2: Rebalancing user feeds...")
    logger.info("=" * 60)

    stats = {
        "users_processed": 0,
        "users_failed": 0,
        "total_wallets_assigned": 0,
        "by_risk_profile": {
            "conservative": 0,
            "balanced": 0,
            "aggressive": 0,
        },
    }

    for user in users:
        user_id = user["user_id"]
        risk = user["risk_tolerance"]
        last_rebal = user["last_rebalanced"] or "never"

        logger.info(f"\n{'─' * 40}")
        logger.info(f"User {user_id} | Risk: {risk} | Last rebalanced: {last_rebal}")

        try:
            if dry_run:
                # Just calculate, don't save
                wallets = algo.select_wallets_for_user(user_id)
                wallet_count = len(wallets)
                logger.info(f"[DRY RUN] Would assign {wallet_count} wallets")
            else:
                # Actually rebalance and save
                wallet_count = algo.rebalance_user_feed(user_id)
                logger.info(f"Assigned {wallet_count} wallets")

            stats["users_processed"] += 1
            stats["total_wallets_assigned"] += wallet_count
            stats["by_risk_profile"][risk] = stats["by_risk_profile"].get(risk, 0) + 1

            # Log feed stats
            feed_stats = algo.get_feed_stats(user_id)
            logger.info(f"  Elite: {feed_stats['elite_count']} | "
                       f"Insider: {feed_stats['insider_count']} | "
                       f"High: {feed_stats['high_quality_count']}")
            logger.info(f"  Avg WR: {feed_stats['avg_win_rate']:.0%} | "
                       f"Avg ROI: {feed_stats['avg_roi']:.0f}%")

        except Exception as e:
            logger.error(f"Failed to rebalance user {user_id}: {e}")
            stats["users_failed"] += 1

    return stats


def rebalance_single_user(user_id: int, dry_run: bool = False) -> dict:
    """Rebalance a single user's feed."""
    algo = PersonalizedAlgo()

    # Update global pool first
    logger.info("Updating global pool...")
    pool_size = algo.populate_global_pool()
    logger.info(f"Global pool: {pool_size} wallets")

    # Get user config
    config = algo.get_user_config(user_id)
    logger.info(f"\nUser {user_id} config:")
    logger.info(f"  Risk tolerance: {config['risk_tolerance']}")
    logger.info(f"  Preferred win rate: {config['preferred_win_rate']:.0%}")
    logger.info(f"  Preferred ROI: {config['preferred_roi']:.0f}%")
    logger.info(f"  Feed size: {config['feed_size']}")

    # Select wallets
    wallets = algo.select_wallets_for_user(user_id)

    if dry_run:
        logger.info(f"\n[DRY RUN] Would assign {len(wallets)} wallets")
    else:
        algo.save_user_feed(user_id, wallets)
        logger.info(f"\nAssigned {len(wallets)} wallets")

    # Show stats
    stats = algo.get_feed_stats(user_id)
    logger.info(f"\nFeed composition:")
    logger.info(f"  Elite: {stats['elite_count']}")
    logger.info(f"  Insider: {stats['insider_count']}")
    logger.info(f"  High-Quality: {stats['high_quality_count']}")
    logger.info(f"  Avg Win Rate: {stats['avg_win_rate']:.0%}")
    logger.info(f"  Avg ROI: {stats['avg_roi']:.0f}%")

    # Show top selections
    logger.info(f"\nTop 10 wallet selections:")
    for w in wallets[:10]:
        logger.info(f"  {w.wallet_address[:12]}... | {w.tier:12} | "
                   f"Score: {w.match_score:.1f} | {w.match_reason}")

    return {
        "user_id": user_id,
        "wallets_assigned": len(wallets),
        "feed_stats": stats,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Rebalance user wallet feeds based on updated performance data"
    )
    parser.add_argument(
        "--user",
        type=int,
        help="Rebalance a specific user ID only"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate but don't save changes"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("SoulWinners: User Algorithm Rebalancer")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    if args.dry_run:
        logger.info("MODE: DRY RUN (no changes will be saved)")
    logger.info("=" * 60)

    try:
        if args.user:
            # Single user rebalance
            result = rebalance_single_user(args.user, dry_run=args.dry_run)
            logger.info(f"\nResult: {result}")
        else:
            # All users rebalance
            stats = rebalance_all_users(dry_run=args.dry_run)

            logger.info("\n" + "=" * 60)
            logger.info("REBALANCE COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Users processed: {stats['users_processed']}")
            logger.info(f"Users failed: {stats['users_failed']}")
            logger.info(f"Total wallets assigned: {stats['total_wallets_assigned']}")
            logger.info(f"By risk profile: {stats['by_risk_profile']}")

    except Exception as e:
        logger.error(f"Rebalance failed: {e}")
        sys.exit(1)

    logger.info(f"\nCompleted at: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
