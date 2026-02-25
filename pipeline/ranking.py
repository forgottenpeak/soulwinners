"""
Ranking System
Priority scoring and tier assignment matching your original methodology
"""
import pandas as pd
import numpy as np
from typing import Dict
import logging

from config.settings import (
    PRIORITY_WEIGHTS,
    TIER_ELITE_PERCENTILE,
    TIER_HIGH_PERCENTILE,
    TIER_MID_PERCENTILE,
    MIN_SOL_BALANCE,
    MIN_TRADES_30D,
    MIN_WIN_RATE,
    MIN_ROI,
)

logger = logging.getLogger(__name__)


class RankingSystem:
    """
    Priority scoring and tier assignment:

    Priority Score Formula (your exact weights):
        priority_score = (
            roi_pct * 0.25 +
            profit_token_ratio * 0.20 +
            roi_per_trade * 0.20 +
            trade_frequency * 0.15 +
            x10_ratio * 0.10 +
            x20_ratio * 0.05 +
            x50_ratio * 0.05
        )

    Tier Assignment:
        - Top 15% → Elite
        - Next 25% → High-Quality
        - Next 40% → Mid-Tier
        - Bottom 20% → Watchlist
    """

    def __init__(self):
        self.weights = PRIORITY_WEIGHTS
        self.tier_percentiles = {
            'Elite': TIER_ELITE_PERCENTILE,
            'High-Quality': TIER_HIGH_PERCENTILE,
            'Mid-Tier': TIER_MID_PERCENTILE,
        }

    def normalize_column(self, series: pd.Series) -> pd.Series:
        """Normalize a series to 0-1 range using min-max scaling."""
        min_val = series.min()
        max_val = series.max()
        if max_val == min_val:
            return pd.Series(0.5, index=series.index)
        return (series - min_val) / (max_val - min_val)

    def calculate_priority_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate priority scores using your exact formula.
        """
        logger.info(f"Calculating priority scores for {len(df)} wallets")

        df_copy = df.copy()

        # Normalize each metric to 0-1 range for fair weighting
        normalized = {}
        for metric in self.weights.keys():
            if metric in df_copy.columns:
                # Handle any inf values
                df_copy[metric] = df_copy[metric].replace([np.inf, -np.inf], 0)
                normalized[metric] = self.normalize_column(df_copy[metric].fillna(0))
            else:
                logger.warning(f"Missing metric: {metric}")
                normalized[metric] = pd.Series(0, index=df_copy.index)

        # Calculate weighted priority score
        df_copy['priority_score'] = sum(
            normalized[metric] * weight
            for metric, weight in self.weights.items()
        )

        # Also store roi_final (same as roi_pct but could be adjusted)
        df_copy['roi_final'] = df_copy['roi_pct']

        logger.info(f"Priority score range: {df_copy['priority_score'].min():.4f} - {df_copy['priority_score'].max():.4f}")

        return df_copy

    def assign_tiers(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assign tiers based on priority score percentiles.

        Top 15% → Elite
        Next 25% (60-85 percentile) → High-Quality
        Next 40% (20-60 percentile) → Mid-Tier
        Bottom 20% → Watchlist
        """
        logger.info("Assigning tiers based on priority scores")

        df_copy = df.copy()

        # Calculate percentile ranks
        df_copy['percentile_rank'] = df_copy['priority_score'].rank(pct=True)

        # Assign tiers
        def get_tier(percentile):
            if percentile >= TIER_ELITE_PERCENTILE:
                return 'Elite'
            elif percentile >= TIER_HIGH_PERCENTILE:
                return 'High-Quality'
            elif percentile >= TIER_MID_PERCENTILE:
                return 'Mid-Tier'
            else:
                return 'Watchlist'

        df_copy['tier'] = df_copy['percentile_rank'].apply(get_tier)

        # Create strategy bucket (combination of cluster and tier)
        if 'cluster_name' in df_copy.columns:
            df_copy['strategy_bucket'] = df_copy['cluster_name'] + ' - ' + df_copy['tier']
        else:
            df_copy['strategy_bucket'] = df_copy['tier']

        # Log tier distribution
        tier_counts = df_copy['tier'].value_counts()
        logger.info("Tier distribution:")
        for tier, count in tier_counts.items():
            pct = count / len(df_copy) * 100
            logger.info(f"  {tier}: {count} ({pct:.1f}%)")

        # Clean up temporary column
        df_copy = df_copy.drop(columns=['percentile_rank'])

        return df_copy

    def rank_and_tier(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate priority scores and assign tiers in one step."""
        df_scored = self.calculate_priority_scores(df)
        df_tiered = self.assign_tiers(df_scored)

        # Sort by priority score descending
        df_tiered = df_tiered.sort_values('priority_score', ascending=False)
        df_tiered = df_tiered.reset_index(drop=True)

        return df_tiered


class QualityFilter:
    """
    Apply quality thresholds to get qualified wallets.

    Your thresholds:
    - SOL balance ≥ 40
    - Trades ≥ 20 (in 30 days)
    - Win rate ≥ 70%
    - Total ROI ≥ 70%
    """

    def __init__(
        self,
        min_sol: float = MIN_SOL_BALANCE,
        min_trades: int = MIN_TRADES_30D,
        min_win_rate: float = MIN_WIN_RATE,
        min_roi: float = MIN_ROI,
    ):
        self.min_sol = min_sol
        self.min_trades = min_trades
        self.min_win_rate = min_win_rate
        self.min_roi = min_roi

    def apply_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply all quality filters and return qualified wallets."""
        logger.info(f"Applying quality filters to {len(df)} wallets")

        df_copy = df.copy()
        initial_count = len(df_copy)

        # Log thresholds
        logger.info(f"  Min SOL balance: {self.min_sol}")
        logger.info(f"  Min trades (30d): {self.min_trades}")
        logger.info(f"  Min win rate: {self.min_win_rate:.0%}")
        logger.info(f"  Min ROI: {self.min_roi:.0%}")

        # Apply filters
        mask = (
            (df_copy['current_balance_sol'] >= self.min_sol) &
            (df_copy['total_trades'] >= self.min_trades) &
            (df_copy['profit_token_ratio'] >= self.min_win_rate) &
            (df_copy['roi_pct'] >= self.min_roi * 100)  # roi_pct is in percentage
        )

        df_filtered = df_copy[mask].copy()

        # Log results
        logger.info(f"Qualified wallets: {len(df_filtered)} / {initial_count}")
        logger.info(f"  Filtered out: {initial_count - len(df_filtered)}")

        if len(df_filtered) > 0:
            logger.info(f"Qualified tier distribution:")
            for tier, count in df_filtered['tier'].value_counts().items():
                logger.info(f"  {tier}: {count}")

        return df_filtered

    def get_filter_stats(self, df: pd.DataFrame) -> Dict:
        """Get statistics on why wallets were filtered out."""
        stats = {
            'total': len(df),
            'failed_sol_balance': len(df[df['current_balance_sol'] < self.min_sol]),
            'failed_trades': len(df[df['total_trades'] < self.min_trades]),
            'failed_win_rate': len(df[df['profit_token_ratio'] < self.min_win_rate]),
            'failed_roi': len(df[df['roi_pct'] < self.min_roi * 100]),
        }
        return stats


def main():
    """Test the ranking system."""
    np.random.seed(42)
    n_samples = 100

    # Create sample data
    df = pd.DataFrame({
        'wallet_address': [f'wallet_{i}' for i in range(n_samples)],
        'roi_pct': np.random.normal(100, 50, n_samples),
        'profit_token_ratio': np.random.beta(5, 3, n_samples),
        'roi_per_trade': np.random.normal(5, 3, n_samples),
        'trade_frequency': np.random.exponential(2, n_samples),
        'x10_ratio': np.random.beta(2, 10, n_samples),
        'x20_ratio': np.random.beta(1, 20, n_samples),
        'x50_ratio': np.random.beta(0.5, 50, n_samples),
        'x100_ratio': np.random.beta(0.2, 100, n_samples),
        'current_balance_sol': np.random.exponential(30, n_samples),
        'total_trades': np.random.poisson(25, n_samples),
        'cluster_name': np.random.choice(['Sniper', 'Hunter', 'Alpha'], n_samples),
    })

    # Test ranking
    ranker = RankingSystem()
    df_ranked = ranker.rank_and_tier(df)

    print("\nTop 5 wallets:")
    print(df_ranked[['wallet_address', 'priority_score', 'tier']].head())

    # Test quality filter
    quality_filter = QualityFilter()
    df_qualified = quality_filter.apply_filters(df_ranked)

    print(f"\nQualified wallets: {len(df_qualified)}")


if __name__ == "__main__":
    main()
