"""
SoulWinners Configuration Settings
"""
import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# =============================================================================
# HELIUS API KEY POOLS
# =============================================================================
# TWO SEPARATE POOLS for different workloads:
#
# POOL 1: MONITORING KEYS (3 keys) - Real-time buy alert monitoring
#         - 30-second polling for qualified/insider/watchlist wallets
#         - High priority, low latency requirements
#
# POOL 2: CRON KEYS (10 keys) - Background pipeline jobs
#         - Main pipeline (every 2 hours)
#         - Insider detection (every 15 min)
#         - Cluster analysis (every 20 min)
#         - Cleanup scripts, holder detection
#
# =============================================================================
# ⚠️  DO NOT COMMIT ACTUAL KEYS TO GIT!
#     Replace these placeholders on VPS after pulling code.
# =============================================================================

# MONITORING KEYS (3 keys) - For real-time buy alert monitoring
# These keys are dedicated to the realtime_bot.py polling loop
# Replace on VPS with:
#   1. 9081e779-6108-4699-8937-26eae13d0963
#   2. f3669c59-b5e5-48b1-baf1-13f67b3fa342
#   3. 0e524dfe-ff4a-4fea-bf8c-cb455dd82707
HELIUS_MONITORING_KEYS = [
    os.getenv("HELIUS_MONITOR_KEY_1", "PLACEHOLDER_MONITOR_KEY_1"),
    os.getenv("HELIUS_MONITOR_KEY_2", "PLACEHOLDER_MONITOR_KEY_2"),
    os.getenv("HELIUS_MONITOR_KEY_3", "PLACEHOLDER_MONITOR_KEY_3"),
]

# CRON KEYS (10 keys) - For background pipeline/cron jobs
# These keys are used by: pipeline, insider detection, cluster analysis, cleanup
# Replace on VPS with:
#   1. 21656a17-a0c0-4c9d-99a1-68ee607b644c
#   2. 58591b72-7973-4668-bebd-361e170f1748
#   3. 6dd6522d-b292-4ab5-85e9-567d973beaa5
#   4. 28afc29b-5ef0-4edf-add2-52dea80854f4
#   5. b1a8feb3-bbd3-4ae0-81dc-67aff11b1338
#   6. 5023062c-f4cd-411f-a462-49df6fa9d5ae
#   7. 59bf3ee7-582f-415e-8631-c6cc6e9d3bde
#   8. 4cf897ed-a81f-4aa2-9e66-ce735a010e6c
#   9. c9fd3f13-bcc3-4829-aa8e-b74427ef3381
#   10. 59648c8b-a691-451b-b1ee-3542ad7afd36
HELIUS_FREE_KEYS = [
    os.getenv("HELIUS_CRON_KEY_1", "PLACEHOLDER_CRON_KEY_1"),
    os.getenv("HELIUS_CRON_KEY_2", "PLACEHOLDER_CRON_KEY_2"),
    os.getenv("HELIUS_CRON_KEY_3", "PLACEHOLDER_CRON_KEY_3"),
    os.getenv("HELIUS_CRON_KEY_4", "PLACEHOLDER_CRON_KEY_4"),
    os.getenv("HELIUS_CRON_KEY_5", "PLACEHOLDER_CRON_KEY_5"),
    os.getenv("HELIUS_CRON_KEY_6", "PLACEHOLDER_CRON_KEY_6"),
    os.getenv("HELIUS_CRON_KEY_7", "PLACEHOLDER_CRON_KEY_7"),
    os.getenv("HELIUS_CRON_KEY_8", "PLACEHOLDER_CRON_KEY_8"),
    os.getenv("HELIUS_CRON_KEY_9", "PLACEHOLDER_CRON_KEY_9"),
    os.getenv("HELIUS_CRON_KEY_10", "PLACEHOLDER_CRON_KEY_10"),
]

# Legacy aliases for backwards compatibility
HELIUS_PREMIUM_KEY = HELIUS_MONITORING_KEYS[0]  # First monitoring key
HELIUS_API_KEYS = HELIUS_FREE_KEYS  # All cron keys
HELIUS_API_KEY = HELIUS_FREE_KEYS[0]  # Default single key

# RPC URLs (using first key from each pool)
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_PREMIUM_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_PREMIUM_KEY}"

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8483614914:AAFjwtH2pct_OdZgi4zrcPNKq6zWdb62ypQ")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003534177506")
TELEGRAM_CHANNEL_NAME = "@TopwhaleTracker"

# Database
DATABASE_PATH = DATA_DIR / "soulwinners.db"

# =============================================================================
# QUALITY FILTER THRESHOLDS (Strict filters for high-quality wallets)
# =============================================================================
MIN_SOL_BALANCE = 10          # Minimum SOL balance
MIN_TRADES_30D = 15           # Minimum trades in 30 days
MIN_WIN_RATE = 0.60           # 60% win rate
MIN_ROI = 0.50                # 50% total ROI

# =============================================================================
# TIER PERCENTILES (From your original methodology)
# =============================================================================
TIER_ELITE_PERCENTILE = 0.85      # Top 15%
TIER_HIGH_PERCENTILE = 0.60       # Next 25% (85% - 60%)
TIER_MID_PERCENTILE = 0.20        # Next 40% (60% - 20%)
# Bottom 20% = Watchlist

# =============================================================================
# PRIORITY SCORE WEIGHTS (From your original methodology)
# =============================================================================
PRIORITY_WEIGHTS = {
    "roi_pct": 0.25,
    "profit_token_ratio": 0.20,
    "roi_per_trade": 0.20,
    "trade_frequency": 0.15,
    "x10_ratio": 0.10,
    "x20_ratio": 0.05,
    "x50_ratio": 0.05,
}

# =============================================================================
# K-MEANS CLUSTERING CONFIG (From your original methodology)
# =============================================================================
KMEANS_N_CLUSTERS = 5
KMEANS_FEATURES = [
    "trade_frequency",
    "roi_per_trade",
    "median_hold_time",
    "x10_ratio",
    "profit_token_ratio",
]

CLUSTER_ARCHETYPES = {
    0: "Low-frequency Snipers",
    1: "Moonshot Hunters",
    2: "Core Alpha (Active)",
    3: "Conviction Holders",
    4: "Dormant/Legacy",
}

# =============================================================================
# DATA COLLECTION CONFIG
# =============================================================================
TARGET_WALLETS_DAILY = 200        # Reduced target for reliable collection
TRANSACTION_HISTORY_DAYS = 30     # 30-day lookback
REFRESH_HOUR_UTC = 0              # Midnight UTC refresh

# API Rate Limits (with 4-key rotation = 4x capacity)
HELIUS_RATE_LIMIT = 3             # Concurrent requests per collector
DEXSCREENER_RATE_LIMIT = 3        # Concurrent requests
