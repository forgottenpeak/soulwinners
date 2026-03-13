"""
Feature Engineering for ML Model

Builds features from trade events for model training and live prediction.

Features Categories:
1. Token Metrics - MC/Liq ratio, age, price velocity
2. Volume Metrics - Volume acceleration, buy/sell ratio
3. Wallet Confluence - Smart money count in token
4. Risk Indicators - Dev sold, liquidity removed
"""
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import numpy as np
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection

logger = logging.getLogger(__name__)


@dataclass
class FeatureVector:
    """Feature vector for a single trade event."""
    trade_event_id: int
    token_address: str
    wallet_address: str
    timestamp: int

    # Token features
    mc_to_liq_ratio: float
    token_age_normalized: float
    price_velocity: float
    volume_acceleration: float
    buy_sell_ratio: float
    holder_growth_rate: float

    # Wallet confluence features
    insider_count: int
    elite_count: int
    high_quality_count: int
    total_smart_money: int

    # Risk features
    dev_sold: int
    liquidity_removed: int
    large_holder_concentration: float

    # Outcome (for training)
    outcome_label: Optional[int] = None  # 0=rug, 1=sideways, 2=runner
    roi_label: Optional[float] = None


class FeatureEngineer:
    """
    Build features from trade events.

    Designed to work with:
    1. Historical data (batch processing for training)
    2. Live data (real-time prediction)
    """

    # Normalization parameters (will be fit on training data)
    NORMALIZATION = {
        "mc_to_liq_ratio": {"mean": 10.0, "std": 15.0, "clip": (0, 100)},
        "token_age_hours": {"mean": 24.0, "std": 48.0, "clip": (0, 168)},
        "volume_24h": {"mean": 100000, "std": 500000, "clip": (0, 10000000)},
        "holder_count": {"mean": 500, "std": 1000, "clip": (0, 10000)},
    }

    def __init__(self):
        self.conn = None

    def _get_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = get_connection()
        return self.conn

    def normalize(self, value: float, param_name: str) -> float:
        """Normalize a value using z-score with clipping."""
        params = self.NORMALIZATION.get(param_name)
        if not params:
            return value

        # Clip to range
        min_val, max_val = params.get("clip", (-np.inf, np.inf))
        value = max(min_val, min(value, max_val))

        # Z-score normalization
        mean = params["mean"]
        std = params["std"]

        return (value - mean) / std if std > 0 else 0

    def get_smart_money_in_token(
        self,
        token_address: str,
        timestamp: int,
        window_hours: int = 24,
    ) -> Dict[str, int]:
        """
        Get count of smart money wallets that bought this token recently.

        Args:
            token_address: Token contract address
            timestamp: Reference timestamp
            window_hours: Lookback window in hours

        Returns:
            Dict with counts by tier
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        start_ts = timestamp - (window_hours * 3600)

        cursor.execute("""
            SELECT wallet_tier, COUNT(DISTINCT wallet_address) as count
            FROM trade_events
            WHERE token_address = ?
            AND timestamp BETWEEN ? AND ?
            AND trade_type = 'buy'
            GROUP BY wallet_tier
        """, (token_address, start_ts, timestamp))

        counts = {
            "insider": 0,
            "elite": 0,
            "high_quality": 0,
            "mid_tier": 0,
        }

        for row in cursor.fetchall():
            tier = row[0].lower() if row[0] else "mid_tier"
            if "insider" in tier:
                counts["insider"] = row[1]
            elif "elite" in tier:
                counts["elite"] = row[1]
            elif "high" in tier:
                counts["high_quality"] = row[1]
            else:
                counts["mid_tier"] = row[1]

        counts["total"] = sum(counts.values())

        return counts

    def calculate_price_velocity(
        self,
        token_address: str,
        timestamp: int,
    ) -> float:
        """
        Calculate price momentum based on recent trades.

        Positive = price going up
        Negative = price going down
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get recent trades (last 1 hour)
        start_ts = timestamp - 3600

        cursor.execute("""
            SELECT trade_type, sol_amount, token_amount
            FROM trade_events
            WHERE token_address = ?
            AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """, (token_address, start_ts, timestamp))

        buys_value = 0
        sells_value = 0

        for row in cursor.fetchall():
            trade_type, sol_amount, token_amount = row
            if trade_type == 'buy':
                buys_value += sol_amount
            else:
                sells_value += sol_amount

        total = buys_value + sells_value
        if total == 0:
            return 0

        # Velocity: -1 (all sells) to +1 (all buys)
        velocity = (buys_value - sells_value) / total

        return velocity

    def calculate_volume_acceleration(
        self,
        token_address: str,
        timestamp: int,
    ) -> float:
        """
        Calculate volume acceleration (is volume increasing or decreasing?).

        Compares last 30 min volume to previous 30 min.
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Recent window (last 30 min)
        recent_start = timestamp - 1800
        recent_end = timestamp

        # Previous window (30-60 min ago)
        prev_start = timestamp - 3600
        prev_end = recent_start

        # Get recent volume
        cursor.execute("""
            SELECT SUM(sol_amount)
            FROM trade_events
            WHERE token_address = ?
            AND timestamp BETWEEN ? AND ?
        """, (token_address, recent_start, recent_end))
        recent_vol = cursor.fetchone()[0] or 0

        # Get previous volume
        cursor.execute("""
            SELECT SUM(sol_amount)
            FROM trade_events
            WHERE token_address = ?
            AND timestamp BETWEEN ? AND ?
        """, (token_address, prev_start, prev_end))
        prev_vol = cursor.fetchone()[0] or 0

        if prev_vol == 0:
            return 1.0 if recent_vol > 0 else 0

        # Acceleration: ratio of recent to previous
        acceleration = (recent_vol - prev_vol) / prev_vol

        return max(-2.0, min(2.0, acceleration))  # Clip to [-2, 2]

    def calculate_buy_sell_ratio(
        self,
        token_address: str,
        timestamp: int,
        window_hours: int = 1,
    ) -> float:
        """Calculate buy/sell ratio in recent window."""
        conn = self._get_conn()
        cursor = conn.cursor()

        start_ts = timestamp - (window_hours * 3600)

        cursor.execute("""
            SELECT
                SUM(CASE WHEN trade_type = 'buy' THEN sol_amount ELSE 0 END) as buys,
                SUM(CASE WHEN trade_type = 'sell' THEN sol_amount ELSE 0 END) as sells
            FROM trade_events
            WHERE token_address = ?
            AND timestamp BETWEEN ? AND ?
        """, (token_address, start_ts, timestamp))

        row = cursor.fetchone()
        buys = row[0] or 0
        sells = row[1] or 0

        if sells == 0:
            return 10.0 if buys > 0 else 1.0  # Cap at 10x

        return min(buys / sells, 10.0)

    def check_dev_activity(self, token_address: str) -> Dict:
        """
        Check developer wallet activity (sold tokens? removed liquidity?).

        Returns dict with dev_sold and liquidity_removed flags.
        """
        # This would require additional data from Helius or other sources
        # For now, return defaults
        return {
            "dev_sold": 0,
            "liquidity_removed": 0,
            "large_holder_concentration": 0.0,
        }

    def build_features_for_event(
        self,
        trade_event: Dict,
        include_outcome: bool = True,
    ) -> FeatureVector:
        """
        Build feature vector for a single trade event.

        Args:
            trade_event: Dict with trade event data
            include_outcome: Whether to include outcome labels

        Returns:
            FeatureVector object
        """
        token_address = trade_event["token_address"]
        wallet_address = trade_event["wallet_address"]
        timestamp = trade_event["timestamp"]

        # Token metrics
        marketcap = trade_event.get("marketcap_at_trade", 0) or 0
        liquidity = trade_event.get("liquidity_at_trade", 0) or 0
        token_age = trade_event.get("token_age_hours", 0) or 0
        holders = trade_event.get("holder_count_at_trade", 0) or 0

        # Calculate derived metrics
        mc_to_liq = marketcap / liquidity if liquidity > 0 else 0
        token_age_norm = self.normalize(token_age, "token_age_hours")

        # Get smart money confluence
        smart_money = self.get_smart_money_in_token(token_address, timestamp)

        # Calculate momentum metrics
        price_velocity = self.calculate_price_velocity(token_address, timestamp)
        vol_acceleration = self.calculate_volume_acceleration(token_address, timestamp)
        buy_sell_ratio = self.calculate_buy_sell_ratio(token_address, timestamp)

        # Check dev activity
        dev_activity = self.check_dev_activity(token_address)

        # Holder growth (would need historical data)
        holder_growth = 0  # Placeholder

        # Build feature vector
        features = FeatureVector(
            trade_event_id=trade_event.get("id", 0),
            token_address=token_address,
            wallet_address=wallet_address,
            timestamp=timestamp,
            # Token features
            mc_to_liq_ratio=min(mc_to_liq, 100),  # Cap at 100
            token_age_normalized=token_age_norm,
            price_velocity=price_velocity,
            volume_acceleration=vol_acceleration,
            buy_sell_ratio=buy_sell_ratio,
            holder_growth_rate=holder_growth,
            # Confluence
            insider_count=smart_money["insider"],
            elite_count=smart_money["elite"],
            high_quality_count=smart_money["high_quality"],
            total_smart_money=smart_money["total"],
            # Risk
            dev_sold=dev_activity["dev_sold"],
            liquidity_removed=dev_activity["liquidity_removed"],
            large_holder_concentration=dev_activity["large_holder_concentration"],
        )

        # Add outcomes if requested and available
        if include_outcome:
            outcome = trade_event.get("outcome")
            roi = trade_event.get("final_roi_percent")

            if outcome:
                outcome_map = {"rug": 0, "sideways": 1, "runner": 2}
                features.outcome_label = outcome_map.get(outcome, 1)

            if roi is not None:
                features.roi_label = roi

        return features

    def to_numpy(self, features: FeatureVector) -> np.ndarray:
        """Convert FeatureVector to numpy array for model input."""
        return np.array([
            features.mc_to_liq_ratio,
            features.token_age_normalized,
            features.price_velocity,
            features.volume_acceleration,
            features.buy_sell_ratio,
            features.holder_growth_rate,
            features.insider_count,
            features.elite_count,
            features.high_quality_count,
            features.total_smart_money,
            features.dev_sold,
            features.liquidity_removed,
            features.large_holder_concentration,
        ], dtype=np.float32)

    def get_feature_names(self) -> List[str]:
        """Get ordered list of feature names."""
        return [
            "mc_to_liq_ratio",
            "token_age_normalized",
            "price_velocity",
            "volume_acceleration",
            "buy_sell_ratio",
            "holder_growth_rate",
            "insider_count",
            "elite_count",
            "high_quality_count",
            "total_smart_money",
            "dev_sold",
            "liquidity_removed",
            "large_holder_concentration",
        ]

    def build_training_dataset(
        self,
        limit: int = None,
        only_with_outcomes: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray, List[int]]:
        """
        Build full training dataset from trade_events table.

        Args:
            limit: Maximum number of events to process
            only_with_outcomes: Only include events with labeled outcomes

        Returns:
            (X, y, event_ids) - features, labels, and event IDs
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Get trade events
        query = """
            SELECT id, wallet_address, token_address, timestamp, trade_type,
                   sol_amount, token_amount, token_age_hours, marketcap_at_trade,
                   liquidity_at_trade, volume_24h_at_trade, holder_count_at_trade,
                   outcome, final_roi_percent
            FROM trade_events
            WHERE trade_type = 'buy'
        """

        if only_with_outcomes:
            query += " AND outcome IS NOT NULL"

        query += " ORDER BY timestamp DESC"

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        logger.info(f"Building features for {len(rows)} trade events...")

        X_list = []
        y_list = []
        event_ids = []

        for row in rows:
            trade_event = dict(zip(columns, row))

            try:
                features = self.build_features_for_event(trade_event)
                X_list.append(self.to_numpy(features))

                if features.outcome_label is not None:
                    y_list.append(features.outcome_label)
                else:
                    y_list.append(1)  # Default to sideways

                event_ids.append(trade_event["id"])

            except Exception as e:
                logger.warning(f"Error building features for event {trade_event['id']}: {e}")
                continue

        X = np.vstack(X_list) if X_list else np.array([])
        y = np.array(y_list)

        logger.info(f"Built dataset: {X.shape[0]} samples, {X.shape[1]} features")

        return X, y, event_ids

    def save_features_to_db(self, features: FeatureVector):
        """Save computed features to ml_features table."""
        conn = self._get_conn()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO ml_features
                (trade_event_id, mc_to_liq_ratio, token_age_normalized, price_velocity,
                 volume_acceleration, buy_sell_ratio, holder_growth_rate,
                 insider_count, elite_count, high_quality_count, total_smart_money,
                 dev_sold, liquidity_removed, large_holder_concentration,
                 outcome_label, roi_label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_event_id) DO UPDATE SET
                    mc_to_liq_ratio = excluded.mc_to_liq_ratio,
                    token_age_normalized = excluded.token_age_normalized,
                    price_velocity = excluded.price_velocity,
                    volume_acceleration = excluded.volume_acceleration,
                    buy_sell_ratio = excluded.buy_sell_ratio
            """, (
                features.trade_event_id,
                features.mc_to_liq_ratio,
                features.token_age_normalized,
                features.price_velocity,
                features.volume_acceleration,
                features.buy_sell_ratio,
                features.holder_growth_rate,
                features.insider_count,
                features.elite_count,
                features.high_quality_count,
                features.total_smart_money,
                features.dev_sold,
                features.liquidity_removed,
                features.large_holder_concentration,
                features.outcome_label,
                features.roi_label,
            ))
            conn.commit()

        except Exception as e:
            logger.error(f"Error saving features: {e}")


def build_live_features(
    wallet_data: Dict,
    token_data: Dict,
    parsed_tx: Dict,
) -> np.ndarray:
    """
    Build feature vector for live prediction.

    Called from realtime_bot.py when a new buy is detected.

    Args:
        wallet_data: Wallet info from qualified_wallets
        token_data: Token info from DexScreener
        parsed_tx: Parsed transaction data

    Returns:
        Feature vector as numpy array
    """
    engineer = FeatureEngineer()

    # Build pseudo trade event
    trade_event = {
        "id": 0,
        "wallet_address": wallet_data.get("wallet_address", ""),
        "token_address": parsed_tx.get("token_address", ""),
        "timestamp": parsed_tx.get("timestamp", int(datetime.now().timestamp())),
        "marketcap_at_trade": token_data.get("market_cap", 0),
        "liquidity_at_trade": token_data.get("liquidity", 0),
        "token_age_hours": token_data.get("token_age_hours", 0),
        "holder_count_at_trade": token_data.get("holders", 0),
        "volume_24h_at_trade": token_data.get("volume_24h", 0),
    }

    features = engineer.build_features_for_event(trade_event, include_outcome=False)

    return engineer.to_numpy(features)


if __name__ == "__main__":
    # Test feature engineering
    logging.basicConfig(level=logging.INFO)

    engineer = FeatureEngineer()

    # Build test dataset
    X, y, ids = engineer.build_training_dataset(limit=100, only_with_outcomes=False)

    print(f"\nDataset shape: {X.shape}")
    print(f"Labels shape: {y.shape}")
    print(f"Feature names: {engineer.get_feature_names()}")

    if len(X) > 0:
        print(f"\nFeature statistics:")
        for i, name in enumerate(engineer.get_feature_names()):
            print(f"  {name}: mean={X[:, i].mean():.3f}, std={X[:, i].std():.3f}")

        print(f"\nLabel distribution:")
        for label in [0, 1, 2]:
            count = (y == label).sum()
            pct = count / len(y) * 100
            label_name = ["rug", "sideways", "runner"][label]
            print(f"  {label_name}: {count} ({pct:.1f}%)")
