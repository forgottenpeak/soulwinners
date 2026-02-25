"""
Metrics Calculator
Calculates all performance metrics from your original methodology
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """
    Calculate advanced wallet metrics matching your original process:
    - Performance Metrics: roi_pct, median_roi_pct, profit_token_ratio, trade_frequency, roi_per_trade
    - Multi-bagger Stats: x10_ratio, x20_ratio, x50_ratio, x100_ratio
    - Behavior Metrics: median_hold_time, profit_per_hold_second
    """

    def __init__(self, lookback_days: int = 30):
        self.lookback_days = lookback_days

    def calculate_wallet_metrics(
        self,
        wallet_data: Dict[str, Any],
        transactions: List[Dict] = None
    ) -> Dict[str, Any]:
        """Calculate all metrics for a single wallet."""

        metrics = {
            "wallet_address": wallet_data.get("wallet_address"),
            "source": wallet_data.get("source", "unknown"),
            "current_balance_sol": wallet_data.get("current_balance_sol", 0),
        }

        # Extract base stats
        buy_txs = wallet_data.get("buy_transactions", 0)
        sell_txs = wallet_data.get("sell_transactions", 0)
        total_trades = buy_txs + sell_txs
        unique_tokens = wallet_data.get("unique_tokens_traded", 0)

        metrics["total_trades"] = total_trades
        metrics["buy_transactions"] = buy_txs
        metrics["sell_transactions"] = sell_txs
        metrics["unique_tokens_traded"] = unique_tokens

        # =================================================================
        # PERFORMANCE METRICS
        # =================================================================

        # ROI % (Total return on investment)
        total_spent = wallet_data.get("total_sol_spent", 0)
        total_earned = wallet_data.get("total_sol_earned", 0)

        if total_spent > 0:
            metrics["roi_pct"] = ((total_earned - total_spent) / total_spent) * 100
        else:
            metrics["roi_pct"] = 0

        # Median ROI % (from wallet_details if available)
        metrics["median_roi_pct"] = wallet_data.get("median_roi_percent", metrics["roi_pct"])

        # Profit Token Ratio (Win Rate)
        metrics["profit_token_ratio"] = wallet_data.get("win_rate", 0)

        # Trade Frequency (trades per day)
        days_active = wallet_data.get("days_since_first_trade", self.lookback_days)
        if days_active and days_active > 0:
            metrics["trade_frequency"] = total_trades / days_active
        else:
            metrics["trade_frequency"] = total_trades / self.lookback_days

        # ROI per Trade
        if total_trades > 0:
            metrics["roi_per_trade"] = metrics["roi_pct"] / total_trades
        else:
            metrics["roi_per_trade"] = 0

        # =================================================================
        # MULTI-BAGGER RATIOS
        # =================================================================

        tokens_10x = wallet_data.get("tokens_10x_plus", 0)
        tokens_20x = wallet_data.get("tokens_20x_plus", 0)
        tokens_50x = wallet_data.get("tokens_50x_plus", 0)
        tokens_100x = wallet_data.get("tokens_100x_plus", 0)

        if unique_tokens > 0:
            metrics["x10_ratio"] = tokens_10x / unique_tokens
            metrics["x20_ratio"] = tokens_20x / unique_tokens
            metrics["x50_ratio"] = tokens_50x / unique_tokens
            metrics["x100_ratio"] = tokens_100x / unique_tokens
        else:
            metrics["x10_ratio"] = 0
            metrics["x20_ratio"] = 0
            metrics["x50_ratio"] = 0
            metrics["x100_ratio"] = 0

        # =================================================================
        # BEHAVIOR METRICS
        # =================================================================

        # Median Hold Time (in seconds)
        metrics["median_hold_time"] = wallet_data.get(
            "median_hold_time_seconds",
            wallet_data.get("median_first_buy_to_sell_seconds", 0)
        )

        # Profit per Hold Second (ROI efficiency)
        if metrics["median_hold_time"] > 0:
            metrics["profit_per_hold_second"] = metrics["roi_pct"] / metrics["median_hold_time"]
        else:
            metrics["profit_per_hold_second"] = 0

        return metrics

    def calculate_batch_metrics(
        self,
        wallets: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """Calculate metrics for a batch of wallets."""
        logger.info(f"Calculating metrics for {len(wallets)} wallets")

        metrics_list = []
        for wallet in wallets:
            try:
                metrics = self.calculate_wallet_metrics(wallet)
                metrics_list.append(metrics)
            except Exception as e:
                logger.error(f"Error calculating metrics for {wallet.get('wallet_address')}: {e}")

        df = pd.DataFrame(metrics_list)
        logger.info(f"Calculated metrics for {len(df)} wallets")

        return df

    def merge_wallet_sources(
        self,
        pumpfun_wallets: List[Dict],
        dex_wallets: List[Dict]
    ) -> pd.DataFrame:
        """
        Merge wallets from both sources and tag appropriately.
        Wallets in both sources get tagged as 'both' (highest quality).
        """
        logger.info(f"Merging {len(pumpfun_wallets)} pump.fun + {len(dex_wallets)} dex wallets")

        # Convert to DataFrames
        df_pump = pd.DataFrame(pumpfun_wallets) if pumpfun_wallets else pd.DataFrame()
        df_dex = pd.DataFrame(dex_wallets) if dex_wallets else pd.DataFrame()

        if df_pump.empty and df_dex.empty:
            return pd.DataFrame()

        # Set source tags
        if not df_pump.empty:
            df_pump['source'] = 'pumpfun'
        if not df_dex.empty:
            df_dex['source'] = 'dex'

        # Find wallets in both
        if not df_pump.empty and not df_dex.empty:
            pump_wallets = set(df_pump['wallet_address'])
            dex_wallets_set = set(df_dex['wallet_address'])
            both_wallets = pump_wallets & dex_wallets_set

            logger.info(f"Found {len(both_wallets)} multi-platform traders")

            # For wallets in both, prefer pump.fun data but tag as 'both'
            df_pump.loc[df_pump['wallet_address'].isin(both_wallets), 'source'] = 'both'

            # Remove duplicates from dex (keep pump.fun version)
            df_dex = df_dex[~df_dex['wallet_address'].isin(both_wallets)]

        # Concatenate
        df_merged = pd.concat([df_pump, df_dex], ignore_index=True)

        # Calculate metrics for merged data
        wallet_dicts = df_merged.to_dict('records')
        df_metrics = self.calculate_batch_metrics(wallet_dicts)

        logger.info(f"Merged result: {len(df_metrics)} unique wallets")
        return df_metrics


def main():
    """Test the metrics calculator."""
    calculator = MetricsCalculator()

    # Test with sample data
    test_wallet = {
        "wallet_address": "TEST123",
        "source": "pumpfun",
        "current_balance_sol": 50.5,
        "buy_transactions": 100,
        "sell_transactions": 80,
        "unique_tokens_traded": 45,
        "total_sol_spent": 200,
        "total_sol_earned": 500,
        "win_rate": 0.75,
        "days_since_first_trade": 30,
        "tokens_10x_plus": 5,
        "tokens_20x_plus": 2,
        "tokens_50x_plus": 1,
        "tokens_100x_plus": 0,
        "median_hold_time_seconds": 3600,
    }

    metrics = calculator.calculate_wallet_metrics(test_wallet)

    print("Calculated Metrics:")
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
