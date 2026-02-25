#!/usr/bin/env python3
"""
Quick pipeline test with minimal data collection
"""
import asyncio
import sys
import logging
sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

from database import init_database
from pipeline.metrics import MetricsCalculator
from pipeline.clustering import ClusteringPipeline
from pipeline.ranking import RankingSystem, QualityFilter


async def test_with_sample_data():
    """Test the pipeline with sample wallet data."""
    print("=" * 60)
    print("SOULWINNERS PIPELINE TEST")
    print("=" * 60)

    # Initialize database
    init_database()

    # Create sample wallet data (simulating collected data)
    sample_wallets = [
        {
            "wallet_address": f"WALLET{i:03d}",
            "source": "pumpfun" if i % 3 == 0 else "dex",
            "current_balance_sol": 20 + (i * 5),
            "buy_transactions": 30 + i * 2,
            "sell_transactions": 25 + i,
            "unique_tokens_traded": 15 + i,
            "total_sol_spent": 100 + i * 10,
            "total_sol_earned": 150 + i * 20,
            "win_rate": 0.5 + (i % 5) * 0.1,
            "days_since_first_trade": 30,
            "tokens_10x_plus": i % 5,
            "tokens_20x_plus": i % 3,
            "tokens_50x_plus": i % 7,
            "tokens_100x_plus": 0,
            "median_hold_time_seconds": 3600 + i * 100,
        }
        for i in range(50)
    ]

    print(f"\n[1/4] Sample wallets: {len(sample_wallets)}")

    # Calculate metrics
    print("\n[2/4] Calculating metrics...")
    calculator = MetricsCalculator()
    df_metrics = calculator.calculate_batch_metrics(sample_wallets)
    print(f"  Calculated metrics for {len(df_metrics)} wallets")
    print(f"  Columns: {list(df_metrics.columns)}")

    # Run clustering
    print("\n[3/4] Running K-Means clustering...")
    clustering = ClusteringPipeline()
    df_clustered = clustering.fit_transform(df_metrics)
    print(f"  Cluster distribution:")
    for cluster, count in df_clustered['cluster'].value_counts().sort_index().items():
        name = df_clustered[df_clustered['cluster'] == cluster]['cluster_name'].iloc[0]
        print(f"    Cluster {cluster} ({name}): {count}")

    # Rank and tier
    print("\n[4/4] Ranking and assigning tiers...")
    ranker = RankingSystem()
    df_ranked = ranker.rank_and_tier(df_clustered)
    print(f"  Tier distribution:")
    for tier, count in df_ranked['tier'].value_counts().items():
        print(f"    {tier}: {count}")

    # Apply quality filter
    print("\n[5/4] Applying quality filters...")
    quality_filter = QualityFilter()
    df_qualified = quality_filter.apply_filters(df_ranked)

    print("\n" + "=" * 60)
    print(f"RESULTS: {len(df_qualified)} qualified wallets")
    print("=" * 60)

    if len(df_qualified) > 0:
        print("\nTop 5 qualified wallets:")
        for i, (_, row) in enumerate(df_qualified.head(5).iterrows(), 1):
            print(f"\n{i}. {row['wallet_address']}")
            print(f"   Tier: {row['tier']} | Strategy: {row['cluster_name']}")
            print(f"   ROI: {row['roi_pct']:.1f}% | Win Rate: {row['profit_token_ratio']:.1%}")
            print(f"   Priority Score: {row['priority_score']:.4f}")

        # Show df_ranked.csv format
        print("\n" + "-" * 60)
        print("df_ranked.csv columns (your exact format):")
        print("-" * 60)
        cols = ['wallet_address', 'source', 'roi_pct', 'median_roi_pct',
                'profit_token_ratio', 'trade_frequency', 'roi_per_trade',
                'x10_ratio', 'x20_ratio', 'x50_ratio', 'x100_ratio',
                'median_hold_time', 'profit_per_hold_second',
                'cluster', 'cluster_label', 'cluster_name',
                'roi_final', 'priority_score', 'tier', 'strategy_bucket']
        available = [c for c in cols if c in df_qualified.columns]
        print(f"Available columns: {len(available)}/{len(cols)}")
        print(df_qualified[available].head(3).to_string())
    else:
        print("\nNo wallets met quality thresholds.")
        print("(This is expected with sample data - real data will have more variation)")

    return df_qualified


if __name__ == "__main__":
    asyncio.run(test_with_sample_data())
