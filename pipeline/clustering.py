"""
K-Means Clustering Pipeline
Replicates your original 5-cluster strategy archetype assignment
"""
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from typing import Dict, Tuple
import logging
import joblib
from pathlib import Path

from config.settings import (
    KMEANS_N_CLUSTERS,
    KMEANS_FEATURES,
    CLUSTER_ARCHETYPES,
    DATA_DIR
)

logger = logging.getLogger(__name__)


class ClusteringPipeline:
    """
    K-Means clustering pipeline matching your original methodology:
    - 5 clusters
    - Features: trade_frequency, roi_per_trade, median_hold_time, x10_ratio, profit_token_ratio
    - Assigns strategy archetypes based on cluster characteristics
    """

    def __init__(self):
        self.n_clusters = KMEANS_N_CLUSTERS
        self.features = KMEANS_FEATURES
        self.archetypes = CLUSTER_ARCHETYPES
        self.scaler = StandardScaler()
        self.kmeans = KMeans(
            n_clusters=self.n_clusters,
            random_state=42,
            n_init=10
        )
        self.model_path = DATA_DIR / "models"
        self.is_fitted = False

    def prepare_features(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, np.ndarray]:
        """Prepare and validate features for clustering."""
        # Ensure all required features exist
        missing_features = [f for f in self.features if f not in df.columns]
        if missing_features:
            raise ValueError(f"Missing features: {missing_features}")

        # Extract features
        X = df[self.features].copy()

        # Handle missing values
        X = X.fillna(0)

        # Handle infinite values
        X = X.replace([np.inf, -np.inf], 0)

        return df, X.values

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fit the clustering model and transform the data."""
        logger.info(f"Fitting K-Means clustering on {len(df)} wallets")

        df_copy = df.copy()
        df_copy, X = self.prepare_features(df_copy)

        if len(X) < self.n_clusters:
            logger.warning(f"Not enough samples ({len(X)}) for {self.n_clusters} clusters")
            df_copy['cluster'] = 0
            df_copy['cluster_label'] = 'cluster_0'
            df_copy['cluster_name'] = self.archetypes.get(0, 'Unknown')
            return df_copy

        # Fit scaler and transform
        X_scaled = self.scaler.fit_transform(X)

        # Fit K-Means
        self.kmeans.fit(X_scaled)
        self.is_fitted = True

        # Assign clusters
        df_copy['cluster'] = self.kmeans.labels_

        # Analyze cluster characteristics to assign archetypes
        cluster_mapping = self._analyze_clusters(df_copy)

        # Apply archetype labels
        df_copy['cluster_label'] = df_copy['cluster'].apply(lambda x: f'cluster_{x}')
        df_copy['cluster_name'] = df_copy['cluster'].map(cluster_mapping)

        logger.info("Cluster distribution:")
        for cluster, count in df_copy['cluster'].value_counts().sort_index().items():
            name = cluster_mapping.get(cluster, 'Unknown')
            logger.info(f"  Cluster {cluster} ({name}): {count} wallets")

        return df_copy

    def _analyze_clusters(self, df: pd.DataFrame) -> Dict[int, str]:
        """
        Analyze cluster characteristics and map to strategy archetypes.

        Strategy Archetypes:
        - Low-frequency Snipers: Low trade_frequency, high roi_per_trade
        - Moonshot Hunters: High x10_ratio, lower win rate
        - Core Alpha (Active): High trade_frequency, consistent profit_token_ratio
        - Conviction Holders: Long median_hold_time, high profit_token_ratio
        - Dormant/Legacy: Very low trade_frequency
        """
        cluster_stats = df.groupby('cluster')[self.features].mean()

        mapping = {}
        used_archetypes = set()

        # Calculate normalized scores for each archetype characteristic
        for cluster in range(self.n_clusters):
            if cluster not in cluster_stats.index:
                continue

            stats = cluster_stats.loc[cluster]

            # Score each archetype
            scores = {
                "Low-frequency Snipers": (
                    (1 - self._normalize(stats['trade_frequency'], cluster_stats['trade_frequency'])) * 0.5 +
                    self._normalize(stats['roi_per_trade'], cluster_stats['roi_per_trade']) * 0.5
                ),
                "Moonshot Hunters": (
                    self._normalize(stats['x10_ratio'], cluster_stats['x10_ratio']) * 0.6 +
                    (1 - self._normalize(stats['profit_token_ratio'], cluster_stats['profit_token_ratio'])) * 0.4
                ),
                "Core Alpha (Active)": (
                    self._normalize(stats['trade_frequency'], cluster_stats['trade_frequency']) * 0.5 +
                    self._normalize(stats['profit_token_ratio'], cluster_stats['profit_token_ratio']) * 0.5
                ),
                "Conviction Holders": (
                    self._normalize(stats['median_hold_time'], cluster_stats['median_hold_time']) * 0.5 +
                    self._normalize(stats['profit_token_ratio'], cluster_stats['profit_token_ratio']) * 0.5
                ),
                "Dormant/Legacy": (
                    (1 - self._normalize(stats['trade_frequency'], cluster_stats['trade_frequency'])) * 0.7 +
                    (1 - self._normalize(stats['roi_per_trade'], cluster_stats['roi_per_trade'])) * 0.3
                ),
            }

            # Find best matching archetype not yet used
            sorted_archetypes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            for archetype, score in sorted_archetypes:
                if archetype not in used_archetypes:
                    mapping[cluster] = archetype
                    used_archetypes.add(archetype)
                    break

            # Fallback if all archetypes used
            if cluster not in mapping:
                mapping[cluster] = sorted_archetypes[0][0]

        return mapping

    def _normalize(self, value: float, series: pd.Series) -> float:
        """Normalize a value relative to a series (0-1 scale)."""
        min_val = series.min()
        max_val = series.max()
        if max_val == min_val:
            return 0.5
        return (value - min_val) / (max_val - min_val)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform new data using fitted model."""
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call fit_transform first.")

        df_copy = df.copy()
        df_copy, X = self.prepare_features(df_copy)

        X_scaled = self.scaler.transform(X)
        df_copy['cluster'] = self.kmeans.predict(X_scaled)

        # Use stored archetype mapping
        cluster_mapping = {i: self.archetypes.get(i, 'Unknown') for i in range(self.n_clusters)}
        df_copy['cluster_label'] = df_copy['cluster'].apply(lambda x: f'cluster_{x}')
        df_copy['cluster_name'] = df_copy['cluster'].map(cluster_mapping)

        return df_copy

    def save_model(self):
        """Save the fitted model to disk."""
        self.model_path.mkdir(parents=True, exist_ok=True)

        joblib.dump(self.scaler, self.model_path / "scaler.joblib")
        joblib.dump(self.kmeans, self.model_path / "kmeans.joblib")
        logger.info(f"Model saved to {self.model_path}")

    def load_model(self):
        """Load a fitted model from disk."""
        try:
            self.scaler = joblib.load(self.model_path / "scaler.joblib")
            self.kmeans = joblib.load(self.model_path / "kmeans.joblib")
            self.is_fitted = True
            logger.info(f"Model loaded from {self.model_path}")
        except FileNotFoundError:
            logger.warning("No saved model found")


def main():
    """Test the clustering pipeline."""
    # Create sample data
    np.random.seed(42)
    n_samples = 100

    df = pd.DataFrame({
        'wallet_address': [f'wallet_{i}' for i in range(n_samples)],
        'trade_frequency': np.random.exponential(2, n_samples),
        'roi_per_trade': np.random.normal(5, 10, n_samples),
        'median_hold_time': np.random.exponential(3600, n_samples),
        'x10_ratio': np.random.beta(2, 10, n_samples),
        'profit_token_ratio': np.random.beta(5, 3, n_samples),
    })

    pipeline = ClusteringPipeline()
    df_clustered = pipeline.fit_transform(df)

    print("\nCluster Summary:")
    print(df_clustered.groupby(['cluster', 'cluster_name']).size())


if __name__ == "__main__":
    main()
