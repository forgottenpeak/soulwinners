#!/usr/bin/env python3
"""
Test real data collection with small sample
"""
import asyncio
import sys
import logging
sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

from collectors.pumpfun import PumpFunCollector
from pipeline.metrics import MetricsCalculator
from pipeline.clustering import ClusteringPipeline
from pipeline.ranking import RankingSystem, QualityFilter


async def test_real_collection():
    """Test with real blockchain data (small sample)."""
    print("=" * 60)
    print("REAL DATA COLLECTION TEST")
    print("=" * 60)

    # Collect 10 real wallets
    print("\n[1/4] Collecting real wallets from blockchain...")
    async with PumpFunCollector() as collector:
        wallets = await collector.collect_wallets(target_count=10)

    if not wallets:
        print("ERROR: No wallets collected. API may be rate limiting.")
        return

    print(f"  Collected {len(wallets)} real wallets")

    # Show sample wallet
    print("\n  Sample wallet data:")
    w = wallets[0]
    print(f"    Address: {w['wallet_address'][:30]}...")
    print(f"    SOL Balance: {w['current_balance_sol']:.2f}")
    print(f"    Buys: {w['buy_transactions']}, Sells: {w['sell_transactions']}")
    print(f"    Win Rate: {w['win_rate']:.1%}")

    # Calculate metrics
    print("\n[2/4] Calculating metrics...")
    calculator = MetricsCalculator()
    df_metrics = calculator.calculate_batch_metrics(wallets)
    print(f"  Metrics calculated for {len(df_metrics)} wallets")

    # Run clustering
    print("\n[3/4] Running K-Means clustering...")
    clustering = ClusteringPipeline()
    df_clustered = clustering.fit_transform(df_metrics)

    print(f"  Cluster assignments:")
    for cluster, count in df_clustered['cluster'].value_counts().sort_index().items():
        if count > 0:
            name = df_clustered[df_clustered['cluster'] == cluster]['cluster_name'].iloc[0]
            print(f"    {name}: {count}")

    # Rank and tier
    print("\n[4/4] Ranking and tiering...")
    ranker = RankingSystem()
    df_ranked = ranker.rank_and_tier(df_clustered)

    print(f"  Tier distribution:")
    for tier, count in df_ranked['tier'].value_counts().items():
        print(f"    {tier}: {count}")

    # Show top wallets
    print("\n" + "=" * 60)
    print("TOP WALLETS (Sorted by Priority Score)")
    print("=" * 60)

    for i, (_, row) in enumerate(df_ranked.head(5).iterrows(), 1):
        print(f"\n{i}. {row['wallet_address'][:40]}...")
        print(f"   Source: {row['source']} | Tier: {row['tier']}")
        print(f"   Strategy: {row['cluster_name']}")
        print(f"   ROI: {row['roi_pct']:.1f}% | Win Rate: {row['profit_token_ratio']:.1%}")
        print(f"   SOL: {row['current_balance_sol']:.2f} | Trades: {row['total_trades']}")
        print(f"   Priority Score: {row['priority_score']:.4f}")

    # Apply quality filter to see qualified
    print("\n" + "-" * 60)
    qf = QualityFilter()
    df_qualified = qf.apply_filters(df_ranked)
    print(f"Qualified wallets: {len(df_qualified)} / {len(df_ranked)}")

    if len(df_qualified) == 0:
        print("\n(No wallets met quality thresholds in this small sample)")
        print("A full collection of 500+ wallets will find qualified traders.")


if __name__ == "__main__":
    asyncio.run(test_real_collection())
