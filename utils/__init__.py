"""
Utils module for SoulWinners
"""
from utils.statistics import (
    calculate_iqr_bounds,
    filter_outliers_iqr,
    robust_mean,
    robust_stats,
    calculate_pool_robust_stats,
)

__all__ = [
    'calculate_iqr_bounds',
    'filter_outliers_iqr',
    'robust_mean',
    'robust_stats',
    'calculate_pool_robust_stats',
]
