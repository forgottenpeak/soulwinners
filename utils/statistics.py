"""
Statistical Utilities for SoulWinners
Implements IQR-based outlier filtering for robust averages
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
import logging

logger = logging.getLogger(__name__)


def calculate_iqr_bounds(
    data: np.ndarray,
    multiplier: float = 1.5
) -> Tuple[float, float]:
    """
    Calculate IQR bounds for outlier detection.

    Args:
        data: Array of values
        multiplier: IQR multiplier (default 1.5, use 3.0 for less aggressive filtering)

    Returns:
        Tuple of (lower_bound, upper_bound)
    """
    if len(data) < 4:
        return float('-inf'), float('inf')

    q1 = np.percentile(data, 25)
    q3 = np.percentile(data, 75)
    iqr = q3 - q1

    lower_bound = q1 - (multiplier * iqr)
    upper_bound = q3 + (multiplier * iqr)

    return lower_bound, upper_bound


def filter_outliers_iqr(
    data: np.ndarray,
    multiplier: float = 1.5
) -> np.ndarray:
    """
    Filter outliers using IQR method.

    Args:
        data: Array of values
        multiplier: IQR multiplier (default 1.5)

    Returns:
        Filtered array without outliers
    """
    if len(data) < 4:
        return data

    lower, upper = calculate_iqr_bounds(data, multiplier)
    mask = (data >= lower) & (data <= upper)
    return data[mask]


def robust_mean(
    data: np.ndarray,
    multiplier: float = 1.5
) -> float:
    """
    Calculate mean after removing outliers.

    Args:
        data: Array of values
        multiplier: IQR multiplier

    Returns:
        Robust mean value
    """
    filtered = filter_outliers_iqr(data, multiplier)
    if len(filtered) == 0:
        return np.nanmean(data)  # Fall back to raw mean
    return float(np.nanmean(filtered))


def robust_stats(
    data: np.ndarray,
    multiplier: float = 1.5
) -> Dict[str, float]:
    """
    Calculate comprehensive statistics with outlier filtering.

    Args:
        data: Array of values
        multiplier: IQR multiplier

    Returns:
        Dictionary with raw and robust statistics
    """
    data = np.array(data)
    data = data[~np.isnan(data)]  # Remove NaN

    if len(data) == 0:
        return {
            'raw_mean': 0,
            'raw_median': 0,
            'raw_std': 0,
            'raw_min': 0,
            'raw_max': 0,
            'robust_mean': 0,
            'robust_median': 0,
            'robust_std': 0,
            'outliers_removed': 0,
            'outlier_pct': 0,
            'lower_bound': 0,
            'upper_bound': 0,
        }

    # Raw stats
    raw_mean = float(np.mean(data))
    raw_median = float(np.median(data))
    raw_std = float(np.std(data))
    raw_min = float(np.min(data))
    raw_max = float(np.max(data))

    # Filter outliers
    lower, upper = calculate_iqr_bounds(data, multiplier)
    filtered = data[(data >= lower) & (data <= upper)]
    outliers_removed = len(data) - len(filtered)

    # Robust stats
    if len(filtered) > 0:
        robust_mean_val = float(np.mean(filtered))
        robust_median = float(np.median(filtered))
        robust_std = float(np.std(filtered))
    else:
        robust_mean_val = raw_mean
        robust_median = raw_median
        robust_std = raw_std

    return {
        'raw_mean': raw_mean,
        'raw_median': raw_median,
        'raw_std': raw_std,
        'raw_min': raw_min,
        'raw_max': raw_max,
        'robust_mean': robust_mean_val,
        'robust_median': robust_median,
        'robust_std': robust_std,
        'outliers_removed': outliers_removed,
        'outlier_pct': (outliers_removed / len(data)) * 100 if len(data) > 0 else 0,
        'lower_bound': lower,
        'upper_bound': upper,
    }


def calculate_pool_robust_stats(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """
    Calculate robust statistics for all key metrics in a wallet pool.

    Args:
        df: DataFrame with wallet data (must have roi_pct, win_rate, trade_frequency, etc.)

    Returns:
        Dictionary with robust stats for each metric
    """
    metrics_to_analyze = [
        'roi_pct',
        'win_rate',
        'profit_token_ratio',  # Alternative name for win_rate
        'trade_frequency',
        'median_hold_time',
        'roi_per_trade',
        'current_balance_sol',
        'x10_ratio',
    ]

    results = {}

    for metric in metrics_to_analyze:
        if metric in df.columns:
            data = df[metric].dropna().values
            if len(data) > 0:
                results[metric] = robust_stats(data)
                logger.debug(
                    f"{metric}: raw_avg={results[metric]['raw_mean']:.2f}, "
                    f"robust_avg={results[metric]['robust_mean']:.2f}, "
                    f"outliers={results[metric]['outliers_removed']}"
                )

    return results


def cap_impossible_values(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cap impossible values (e.g., win rate > 100%) to valid ranges.

    Args:
        df: DataFrame with wallet metrics

    Returns:
        DataFrame with capped values
    """
    df = df.copy()

    # Win rate: 0-100%
    if 'win_rate' in df.columns:
        df['win_rate'] = df['win_rate'].clip(0, 1)
    if 'profit_token_ratio' in df.columns:
        df['profit_token_ratio'] = df['profit_token_ratio'].clip(0, 1)

    # X ratios: 0-1
    for col in ['x10_ratio', 'x20_ratio', 'x50_ratio', 'x100_ratio']:
        if col in df.columns:
            df[col] = df[col].clip(0, 1)

    # Trade frequency: min 0
    if 'trade_frequency' in df.columns:
        df['trade_frequency'] = df['trade_frequency'].clip(lower=0)

    # Hold time: min 0
    if 'median_hold_time' in df.columns:
        df['median_hold_time'] = df['median_hold_time'].clip(lower=0)

    return df


def get_performance_health_score(wallet_data: Dict[str, Any]) -> float:
    """
    Calculate a health score for a wallet based on recent performance.

    Args:
        wallet_data: Dictionary with wallet metrics

    Returns:
        Health score from 0.0 (poor) to 1.0 (excellent)
    """
    score = 0.0
    weights_sum = 0.0

    # ROI contribution (weight: 0.3)
    roi = wallet_data.get('roi_pct', 0)
    if roi > 0:
        roi_score = min(roi / 500, 1.0)  # Cap at 500% ROI
        score += roi_score * 0.3
    weights_sum += 0.3

    # Win rate contribution (weight: 0.3)
    win_rate = wallet_data.get('win_rate', wallet_data.get('profit_token_ratio', 0))
    if win_rate > 0:
        score += win_rate * 0.3  # Already 0-1 scale
    weights_sum += 0.3

    # Activity contribution (weight: 0.2)
    trade_freq = wallet_data.get('trade_frequency', 0)
    if trade_freq > 0:
        activity_score = min(trade_freq / 5, 1.0)  # Cap at 5 trades/day
        score += activity_score * 0.2
    weights_sum += 0.2

    # Balance contribution (weight: 0.2)
    balance = wallet_data.get('current_balance_sol', 0)
    if balance > 0:
        balance_score = min(balance / 100, 1.0)  # Cap at 100 SOL
        score += balance_score * 0.2
    weights_sum += 0.2

    return score / weights_sum if weights_sum > 0 else 0.0


def format_comparison_stats(raw: float, robust: float, label: str) -> str:
    """
    Format raw vs robust stats for display.

    Args:
        raw: Raw average
        robust: Robust (IQR-filtered) average
        label: Metric label

    Returns:
        Formatted string showing both values
    """
    diff_pct = ((raw - robust) / robust * 100) if robust != 0 else 0

    if abs(diff_pct) > 50:
        indicator = " (!)"  # Major skew indicator
    elif abs(diff_pct) > 20:
        indicator = " (*)"  # Moderate skew
    else:
        indicator = ""

    return f"{label}: {robust:.1f} (raw: {raw:.1f}){indicator}"
