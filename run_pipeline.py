#!/usr/bin/env python3
"""
SoulWinners Pipeline Runner
Collects and analyzes wallets, adds qualified ones to pool.

Usage:
  python3 run_pipeline.py
  python3 run_pipeline.py --target 500
  python3 run_pipeline.py --threshold-sol 10 --threshold-win 60
"""
import asyncio
import argparse
import logging
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, '.')

from database import init_database, get_connection
from pipeline.orchestrator import PipelineOrchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def run_pipeline(args):
    """Run the wallet collection pipeline."""
    print("=" * 60)
    print("SOULWINNERS PIPELINE")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Initialize database
    init_database()

    # Get current pool size
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
    current_count = cursor.fetchone()[0]
    conn.close()

    print(f"\nCurrent pool: {current_count} wallets")
    print(f"Target collection: {args.target} wallets")
    print("")
    print("Thresholds:")
    print(f"  Min SOL balance: {args.threshold_sol}")
    print(f"  Min trades: {args.threshold_trades}")
    print(f"  Min win rate: {args.threshold_win}%")
    print(f"  Min ROI: {args.threshold_roi}%")
    print("")

    # Update settings
    import config.settings as settings
    settings.MIN_SOL_BALANCE = args.threshold_sol
    settings.MIN_TRADES_30D = args.threshold_trades
    settings.MIN_WIN_RATE = args.threshold_win / 100
    settings.MIN_ROI = args.threshold_roi / 100

    # Run pipeline
    orchestrator = PipelineOrchestrator()

    try:
        df_qualified = await orchestrator.run_full_pipeline()

        # Get final count
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
        final_count = cursor.fetchone()[0]

        cursor.execute("SELECT tier, COUNT(*) FROM qualified_wallets GROUP BY tier")
        tiers = cursor.fetchall()
        conn.close()

        print("")
        print("=" * 60)
        print("PIPELINE COMPLETE")
        print("=" * 60)
        print(f"Previous pool: {current_count} wallets")
        print(f"New pool: {final_count} wallets")
        print(f"Change: +{final_count - current_count} wallets")
        print("")
        print("Tier breakdown:")
        for tier, count in tiers:
            print(f"  {tier}: {count}")

        # Print top 10
        if not df_qualified.empty:
            print("\nTop 10 Wallets:")
            print("-" * 80)
            top10 = df_qualified.head(10)
            for i, (_, row) in enumerate(top10.iterrows(), 1):
                print(f"{i}. {row['wallet_address'][:30]}...")
                print(f"   Tier: {row['tier']} | Strategy: {row.get('cluster_name', 'N/A')}")
                print(f"   ROI: {row['roi_pct']:.1f}% | Win Rate: {row['profit_token_ratio']:.1%}")
                print()

        return final_count

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return current_count


def main():
    parser = argparse.ArgumentParser(description='SoulWinners Pipeline')
    parser.add_argument('--target', type=int, default=500,
                        help='Target number of wallets to collect (default: 500)')
    parser.add_argument('--threshold-sol', type=float, default=10,
                        help='Minimum SOL balance (default: 10)')
    parser.add_argument('--threshold-trades', type=int, default=15,
                        help='Minimum trades in 30 days (default: 15)')
    parser.add_argument('--threshold-win', type=float, default=60,
                        help='Minimum win rate percent (default: 60)')
    parser.add_argument('--threshold-roi', type=float, default=50,
                        help='Minimum ROI percent (default: 50)')

    args = parser.parse_args()

    try:
        result = asyncio.run(run_pipeline(args))
        print(f"\n✅ Pipeline complete: {result} qualified wallets in pool")
    except KeyboardInterrupt:
        print("\nPipeline interrupted")
        sys.exit(1)


if __name__ == "__main__":
    main()
