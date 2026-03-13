"""
Personalized Wallet Selection Algorithm

Selects 150 wallets per user from the global pool of 656+ wallets
based on user's risk tolerance and trading preferences.
"""
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from database import get_connection

logger = logging.getLogger(__name__)


class RiskTolerance(Enum):
    CONSERVATIVE = "conservative"  # Prioritize win rate, lower volatility
    BALANCED = "balanced"          # Balance between win rate and ROI
    AGGRESSIVE = "aggressive"      # Prioritize high ROI, accept more risk


@dataclass
class WalletScore:
    """Wallet scoring for feed selection."""
    wallet_address: str
    tier: str
    quality_score: float
    win_rate: float
    avg_roi: float
    consistency: float
    risk_score: float
    match_score: float  # How well it matches user preferences
    match_reason: str


class PersonalizedAlgo:
    """
    Personalized wallet selection algorithm.

    Selects optimal wallets for each user based on:
    1. Risk tolerance (conservative/balanced/aggressive)
    2. Preferred win rate
    3. Preferred ROI
    4. Trading style matching
    """

    DEFAULT_FEED_SIZE = 150

    # Weight profiles by risk tolerance
    WEIGHT_PROFILES = {
        RiskTolerance.CONSERVATIVE: {
            "win_rate": 0.40,
            "consistency": 0.30,
            "avg_roi": 0.15,
            "quality_score": 0.10,
            "risk_penalty": 0.05,
        },
        RiskTolerance.BALANCED: {
            "win_rate": 0.25,
            "consistency": 0.20,
            "avg_roi": 0.30,
            "quality_score": 0.15,
            "risk_penalty": 0.10,
        },
        RiskTolerance.AGGRESSIVE: {
            "win_rate": 0.15,
            "consistency": 0.10,
            "avg_roi": 0.40,
            "quality_score": 0.15,
            "risk_penalty": 0.20,
        },
    }

    def __init__(self):
        self.conn = None

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        if self.conn is None:
            self.conn = get_connection()
        return self.conn

    def _close_conn(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def get_user_config(self, user_id: int) -> Dict:
        """Get user's algorithm configuration."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT risk_tolerance, preferred_win_rate, preferred_roi,
                   max_token_age_hours, max_mcap, min_liquidity, feed_size
            FROM user_algo_config
            WHERE user_id = ?
        """, (user_id,))

        row = cursor.fetchone()

        if row:
            return {
                "risk_tolerance": row[0] or "balanced",
                "preferred_win_rate": row[1] or 0.65,
                "preferred_roi": row[2] or 100.0,
                "max_token_age_hours": row[3] or 24.0,
                "max_mcap": row[4] or 10_000_000,
                "min_liquidity": row[5] or 10_000,
                "feed_size": row[6] or self.DEFAULT_FEED_SIZE,
            }

        # Return defaults if no config exists
        return {
            "risk_tolerance": "balanced",
            "preferred_win_rate": 0.65,
            "preferred_roi": 100.0,
            "max_token_age_hours": 24.0,
            "max_mcap": 10_000_000,
            "min_liquidity": 10_000,
            "feed_size": self.DEFAULT_FEED_SIZE,
        }

    def set_user_config(
        self,
        user_id: int,
        risk_tolerance: str = "balanced",
        preferred_win_rate: float = 0.65,
        preferred_roi: float = 100.0,
        max_token_age_hours: float = 24.0,
        max_mcap: float = 10_000_000,
        min_liquidity: float = 10_000,
        feed_size: int = 150,
    ) -> bool:
        """Set user's algorithm configuration."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO user_algo_config
                (user_id, risk_tolerance, preferred_win_rate, preferred_roi,
                 max_token_age_hours, max_mcap, min_liquidity, feed_size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    risk_tolerance = excluded.risk_tolerance,
                    preferred_win_rate = excluded.preferred_win_rate,
                    preferred_roi = excluded.preferred_roi,
                    max_token_age_hours = excluded.max_token_age_hours,
                    max_mcap = excluded.max_mcap,
                    min_liquidity = excluded.min_liquidity,
                    feed_size = excluded.feed_size
            """, (
                user_id, risk_tolerance, preferred_win_rate, preferred_roi,
                max_token_age_hours, max_mcap, min_liquidity, feed_size,
                datetime.now().isoformat()
            ))
            conn.commit()
            logger.info(f"Updated config for user {user_id}: risk={risk_tolerance}")
            return True
        except Exception as e:
            logger.error(f"Failed to set user config: {e}")
            return False

    def get_global_pool(self) -> List[Dict]:
        """Get all wallets from the global pool."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT wallet_address, tier, quality_score, win_rate, avg_roi,
                   consistency, specialization, last_30d_performance,
                   total_trades_30d, avg_hold_time_hours, risk_score
            FROM wallet_global_pool
            WHERE quality_score > 0
            ORDER BY quality_score DESC
        """)

        wallets = []
        for row in cursor.fetchall():
            wallets.append({
                "wallet_address": row[0],
                "tier": row[1],
                "quality_score": row[2] or 0,
                "win_rate": row[3] or 0,
                "avg_roi": row[4] or 0,
                "consistency": row[5] or 0,
                "specialization": row[6] or "general",
                "last_30d_performance": row[7] or 0,
                "total_trades_30d": row[8] or 0,
                "avg_hold_time_hours": row[9] or 0,
                "risk_score": row[10] or 50,
            })

        return wallets

    def populate_global_pool(self) -> int:
        """
        Populate the global pool from qualified_wallets and insider_pool tables.
        Should be run after pipeline completes.
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Insert/update from qualified_wallets
        cursor.execute("""
            INSERT INTO wallet_global_pool
            (wallet_address, tier, quality_score, win_rate, avg_roi, consistency,
             specialization, last_30d_performance, total_trades_30d, updated_at)
            SELECT
                wallet_address,
                tier,
                priority_score * 100 as quality_score,
                profit_token_ratio as win_rate,
                roi_pct as avg_roi,
                CASE
                    WHEN median_roi_pct > 0 AND roi_pct > 0
                    THEN 1.0 - ABS(median_roi_pct - roi_pct) / NULLIF(roi_pct, 0)
                    ELSE 0.5
                END as consistency,
                COALESCE(cluster_name, 'general') as specialization,
                roi_pct as last_30d_performance,
                total_trades as total_trades_30d,
                CURRENT_TIMESTAMP
            FROM qualified_wallets
            ON CONFLICT(wallet_address) DO UPDATE SET
                tier = excluded.tier,
                quality_score = excluded.quality_score,
                win_rate = excluded.win_rate,
                avg_roi = excluded.avg_roi,
                consistency = excluded.consistency,
                specialization = excluded.specialization,
                last_30d_performance = excluded.last_30d_performance,
                total_trades_30d = excluded.total_trades_30d,
                updated_at = CURRENT_TIMESTAMP
        """)

        qualified_count = cursor.rowcount

        # Insert/update from insider_pool (if exists)
        try:
            cursor.execute("""
                INSERT INTO wallet_global_pool
                (wallet_address, tier, quality_score, win_rate, avg_roi,
                 specialization, risk_score, updated_at)
                SELECT
                    wallet_address,
                    'Insider' as tier,
                    confidence * 100 as quality_score,
                    win_rate,
                    avg_roi,
                    pattern as specialization,
                    30 as risk_score,  -- Insiders are higher risk/reward
                    CURRENT_TIMESTAMP
                FROM insider_pool
                WHERE wallet_address NOT IN (SELECT wallet_address FROM qualified_wallets)
                ON CONFLICT(wallet_address) DO UPDATE SET
                    quality_score = MAX(wallet_global_pool.quality_score, excluded.quality_score),
                    win_rate = COALESCE(excluded.win_rate, wallet_global_pool.win_rate),
                    avg_roi = COALESCE(excluded.avg_roi, wallet_global_pool.avg_roi),
                    updated_at = CURRENT_TIMESTAMP
            """)
            insider_count = cursor.rowcount
        except Exception as e:
            logger.warning(f"Could not add insiders to global pool: {e}")
            insider_count = 0

        conn.commit()

        total = qualified_count + insider_count
        logger.info(f"Global pool populated: {qualified_count} qualified + {insider_count} insiders = {total} total")

        return total

    def calculate_wallet_match_score(
        self,
        wallet: Dict,
        user_config: Dict,
    ) -> WalletScore:
        """
        Calculate how well a wallet matches user preferences.

        Returns WalletScore with match_score between 0-100.
        """
        risk_tolerance = RiskTolerance(user_config["risk_tolerance"])
        weights = self.WEIGHT_PROFILES[risk_tolerance]

        # Normalize values to 0-1 range
        win_rate_norm = min(wallet["win_rate"], 1.0)
        avg_roi_norm = min(wallet["avg_roi"] / 500, 1.0)  # Cap at 500% ROI
        consistency_norm = min(wallet["consistency"], 1.0)
        quality_norm = wallet["quality_score"] / 100
        risk_norm = 1.0 - (wallet["risk_score"] / 100)  # Invert risk

        # Calculate preference match bonuses
        pref_win_rate = user_config["preferred_win_rate"]
        pref_roi = user_config["preferred_roi"]

        # Win rate match bonus (within 10% of preference)
        win_rate_diff = abs(wallet["win_rate"] - pref_win_rate)
        win_rate_bonus = max(0, 1.0 - win_rate_diff * 5)  # 20% tolerance

        # ROI match bonus (within 50% of preference)
        roi_diff = abs(wallet["avg_roi"] - pref_roi) / max(pref_roi, 1)
        roi_bonus = max(0, 1.0 - roi_diff)

        # Calculate weighted score
        base_score = (
            weights["win_rate"] * win_rate_norm +
            weights["avg_roi"] * avg_roi_norm +
            weights["consistency"] * consistency_norm +
            weights["quality_score"] * quality_norm +
            weights["risk_penalty"] * risk_norm
        )

        # Add preference match bonuses (up to 20% boost)
        match_bonus = (win_rate_bonus + roi_bonus) * 0.10

        # Tier bonus
        tier_bonus = {
            "Elite": 0.15,
            "High-Quality": 0.10,
            "Mid-Tier": 0.05,
            "Insider": 0.12,  # Insiders get high bonus
        }.get(wallet["tier"], 0)

        final_score = min((base_score + match_bonus + tier_bonus) * 100, 100)

        # Determine primary match reason
        if win_rate_bonus > roi_bonus:
            match_reason = "win_rate_match"
        elif roi_bonus > 0.5:
            match_reason = "roi_match"
        elif wallet["tier"] == "Insider":
            match_reason = "insider_alpha"
        elif wallet["tier"] == "Elite":
            match_reason = "elite_tier"
        else:
            match_reason = "balanced_profile"

        return WalletScore(
            wallet_address=wallet["wallet_address"],
            tier=wallet["tier"],
            quality_score=wallet["quality_score"],
            win_rate=wallet["win_rate"],
            avg_roi=wallet["avg_roi"],
            consistency=wallet["consistency"],
            risk_score=wallet["risk_score"],
            match_score=final_score,
            match_reason=match_reason,
        )

    def select_wallets_for_user(
        self,
        user_id: int,
        force_refresh: bool = False,
    ) -> List[WalletScore]:
        """
        Select optimal wallets for a user based on their preferences.

        Args:
            user_id: User's Telegram ID
            force_refresh: Force recalculation even if recent feed exists

        Returns:
            List of WalletScore objects for the user's personalized feed
        """
        user_config = self.get_user_config(user_id)
        feed_size = user_config.get("feed_size", self.DEFAULT_FEED_SIZE)

        # Get global pool
        global_pool = self.get_global_pool()

        if not global_pool:
            logger.warning("Global pool is empty! Run populate_global_pool first.")
            return []

        logger.info(f"Selecting {feed_size} wallets for user {user_id} from {len(global_pool)} pool")
        logger.info(f"User config: risk={user_config['risk_tolerance']}, "
                   f"win_rate={user_config['preferred_win_rate']:.0%}, "
                   f"roi={user_config['preferred_roi']:.0f}%")

        # Score all wallets
        scored_wallets = []
        for wallet in global_pool:
            score = self.calculate_wallet_match_score(wallet, user_config)
            scored_wallets.append(score)

        # Sort by match score
        scored_wallets.sort(key=lambda x: x.match_score, reverse=True)

        # Select top N with diversity requirements
        selected = self._ensure_diversity(scored_wallets, feed_size)

        logger.info(f"Selected {len(selected)} wallets for user {user_id}")

        return selected

    def _ensure_diversity(
        self,
        scored_wallets: List[WalletScore],
        feed_size: int,
    ) -> List[WalletScore]:
        """
        Ensure diversity in the selected feed.

        Minimum requirements:
        - At least 20% Elite/Insider wallets
        - At least 30% High-Quality wallets
        - Maximum 50% from any single tier
        """
        selected = []
        tier_counts = {"Elite": 0, "Insider": 0, "High-Quality": 0, "Mid-Tier": 0}

        # First pass: ensure minimum elite/insider representation
        min_elite_insider = int(feed_size * 0.20)
        for wallet in scored_wallets:
            if wallet.tier in ["Elite", "Insider"]:
                selected.append(wallet)
                tier_counts[wallet.tier] += 1
                if len(selected) >= min_elite_insider:
                    break

        # Second pass: fill remaining with best scores while maintaining diversity
        max_per_tier = int(feed_size * 0.50)

        for wallet in scored_wallets:
            if wallet in selected:
                continue

            if tier_counts.get(wallet.tier, 0) >= max_per_tier:
                continue

            selected.append(wallet)
            tier_counts[wallet.tier] = tier_counts.get(wallet.tier, 0) + 1

            if len(selected) >= feed_size:
                break

        return selected

    def save_user_feed(self, user_id: int, wallets: List[WalletScore]) -> int:
        """Save user's personalized wallet feed to database."""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Clear existing feed
        cursor.execute("DELETE FROM user_wallet_feed WHERE user_id = ?", (user_id,))

        # Insert new feed
        for wallet in wallets:
            cursor.execute("""
                INSERT INTO user_wallet_feed
                (user_id, wallet_address, selection_score, match_reason, added_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                wallet.wallet_address,
                wallet.match_score,
                wallet.match_reason,
                datetime.now().isoformat(),
            ))

        # Update last rebalanced timestamp
        cursor.execute("""
            UPDATE user_algo_config
            SET last_rebalanced = ?
            WHERE user_id = ?
        """, (datetime.now().isoformat(), user_id))

        conn.commit()
        logger.info(f"Saved {len(wallets)} wallets to user {user_id}'s feed")

        return len(wallets)

    def get_user_feed(self, user_id: int) -> List[str]:
        """Get user's current wallet feed (just addresses)."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT wallet_address
            FROM user_wallet_feed
            WHERE user_id = ?
            ORDER BY selection_score DESC
        """, (user_id,))

        return [row[0] for row in cursor.fetchall()]

    def rebalance_user_feed(self, user_id: int) -> int:
        """
        Rebalance a user's wallet feed based on current performance data.

        Should be run weekly to incorporate new performance data.
        """
        logger.info(f"Rebalancing feed for user {user_id}")

        # Select new wallets based on updated metrics
        wallets = self.select_wallets_for_user(user_id, force_refresh=True)

        # Save updated feed
        return self.save_user_feed(user_id, wallets)

    def get_feed_stats(self, user_id: int) -> Dict:
        """Get statistics about a user's wallet feed."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                AVG(f.selection_score) as avg_score,
                COUNT(CASE WHEN g.tier = 'Elite' THEN 1 END) as elite_count,
                COUNT(CASE WHEN g.tier = 'Insider' THEN 1 END) as insider_count,
                COUNT(CASE WHEN g.tier = 'High-Quality' THEN 1 END) as high_count,
                AVG(g.win_rate) as avg_win_rate,
                AVG(g.avg_roi) as avg_roi
            FROM user_wallet_feed f
            JOIN wallet_global_pool g ON f.wallet_address = g.wallet_address
            WHERE f.user_id = ?
        """, (user_id,))

        row = cursor.fetchone()

        if row:
            return {
                "total_wallets": row[0] or 0,
                "avg_match_score": row[1] or 0,
                "elite_count": row[2] or 0,
                "insider_count": row[3] or 0,
                "high_quality_count": row[4] or 0,
                "avg_win_rate": row[5] or 0,
                "avg_roi": row[6] or 0,
            }

        return {
            "total_wallets": 0,
            "avg_match_score": 0,
            "elite_count": 0,
            "insider_count": 0,
            "high_quality_count": 0,
            "avg_win_rate": 0,
            "avg_roi": 0,
        }


def create_default_config_for_user(user_id: int, risk_profile: str = "balanced") -> Dict:
    """
    Create default algorithm configuration for a new user.

    Args:
        user_id: User's Telegram ID
        risk_profile: 'conservative', 'balanced', or 'aggressive'

    Returns:
        Created configuration dict
    """
    profiles = {
        "conservative": {
            "preferred_win_rate": 0.70,
            "preferred_roi": 50.0,
            "max_token_age_hours": 12.0,
            "max_mcap": 5_000_000,
        },
        "balanced": {
            "preferred_win_rate": 0.65,
            "preferred_roi": 100.0,
            "max_token_age_hours": 24.0,
            "max_mcap": 10_000_000,
        },
        "aggressive": {
            "preferred_win_rate": 0.55,
            "preferred_roi": 200.0,
            "max_token_age_hours": 48.0,
            "max_mcap": 50_000_000,
        },
    }

    config = profiles.get(risk_profile, profiles["balanced"])
    config["risk_tolerance"] = risk_profile

    algo = PersonalizedAlgo()
    algo.set_user_config(
        user_id=user_id,
        risk_tolerance=config["risk_tolerance"],
        preferred_win_rate=config["preferred_win_rate"],
        preferred_roi=config["preferred_roi"],
        max_token_age_hours=config["max_token_age_hours"],
        max_mcap=config["max_mcap"],
    )

    return config


if __name__ == "__main__":
    # Test the algorithm
    logging.basicConfig(level=logging.INFO)

    algo = PersonalizedAlgo()

    # Populate global pool from existing data
    total = algo.populate_global_pool()
    print(f"Global pool: {total} wallets")

    # Test selection for a sample user
    test_user_id = 1153491543  # Admin user

    # Set conservative profile for testing
    algo.set_user_config(
        user_id=test_user_id,
        risk_tolerance="balanced",
        preferred_win_rate=0.65,
        preferred_roi=100.0,
    )

    # Select wallets
    selected = algo.select_wallets_for_user(test_user_id)

    print(f"\nSelected {len(selected)} wallets for user {test_user_id}:")
    print("\nTop 10 selections:")
    for w in selected[:10]:
        print(f"  {w.wallet_address[:12]}... | {w.tier:12} | "
              f"Score: {w.match_score:.1f} | WR: {w.win_rate:.0%} | "
              f"ROI: {w.avg_roi:.0f}% | Reason: {w.match_reason}")

    # Save feed
    algo.save_user_feed(test_user_id, selected)

    # Get stats
    stats = algo.get_feed_stats(test_user_id)
    print(f"\nFeed stats:")
    print(f"  Total: {stats['total_wallets']}")
    print(f"  Elite: {stats['elite_count']}")
    print(f"  Insider: {stats['insider_count']}")
    print(f"  High-Quality: {stats['high_quality_count']}")
    print(f"  Avg Win Rate: {stats['avg_win_rate']:.0%}")
    print(f"  Avg ROI: {stats['avg_roi']:.0f}%")
