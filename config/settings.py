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
# HELIUS API KEY POOLS (25 WORKING KEYS - TASK-SPECIFIC ALLOCATION)
# =============================================================================
# Each task gets its own dedicated key pool - NO CONFLICTS!
#
# EXCLUDED KEYS (rate limited - DO NOT USE):
#   - 2c353fb3-653a-47d2-8247-2286ac7098a8
#   - ee2a7d3e-2935-4736-8c3f-113c268f5510
#   - b371c9f4-2ff4-4426-8949-7125b814a421
# =============================================================================

# BUY ALERT KEYS (5 keys) - Real-time buy alert monitoring (every 30 sec)
BUY_ALERT_KEYS = [
    "9081e779-6108-4699-8937-26eae13d0963",
    "f3669c59-b5e5-48b1-baf1-13f67b3fa342",
    "0e524dfe-ff4a-4fea-bf8c-cb455dd82707",
    "6dbb8004-88fb-4b33-8a58-b7c17fb577d4",
    "d479b8b9-cc2e-4b19-9e1c-b9c84502c5c4",
]

# INSIDER DETECTION KEYS (11 keys) - Hourly, heavy holder checks
INSIDER_DETECTION_KEYS = [
    "21656a17-a0c0-4c9d-99a1-68ee607b644c",
    "58591b72-7973-4668-bebd-361e170f1748",
    "6dd6522d-b292-4ab5-85e9-567d973beaa5",
    "28afc29b-5ef0-4edf-add2-52dea80854f4",
    "b1a8feb3-bbd3-4ae0-81dc-67aff11b1338",
    "5023062c-f4cd-411f-a462-49df6fa9d5ae",
    "59bf3ee7-582f-415e-8631-c6cc6e9d3bde",
    "c2dc2189-353c-441d-ac66-388c4e58a05c",
    "4cf897ed-a81f-4aa2-9e66-ce735a010e6c",
    "9f554e4c-8801-49aa-8eea-4d5fe308c093",
    "3ea90a39-c079-4c74-a263-82218cc7964e",
]

# PIPELINE KEYS (6 keys) - Hourly, 146 wallets analysis
PIPELINE_KEYS = [
    "fe001c46-9a8e-4e27-a4b9-262b0a61e29f",
    "a4540f52-9396-4ba8-ade5-d0da3d0e287d",
    "d4f4f513-6db4-489b-af3b-166402105d61",
    "c9dbf548-c4b6-4bf3-8efd-bab80cfc5754",
    "a2c1c855-76d2-4ab2-8e9f-189ab4ec8055",
    "69136707-7d02-493f-a8bd-3a4572779277",
]

# CLUSTER KEYS (3 keys) - Every 2 hours
CLUSTER_KEYS = [
    "1c43a63d-cc61-4c17-9adf-5cfc459e3439",
    "075d83bf-112d-4b20-bab7-c1f8e8c72162",
    "c9fd3f13-bcc3-4829-aa8e-b74427ef3381",
]

# =============================================================================
# LEGACY ALIASES (for backwards compatibility)
# =============================================================================
HELIUS_MONITORING_KEYS = BUY_ALERT_KEYS  # Alias for realtime_bot.py
HELIUS_FREE_KEYS = INSIDER_DETECTION_KEYS  # Legacy cron keys
HELIUS_PREMIUM_KEY = BUY_ALERT_KEYS[0]
HELIUS_API_KEYS = PIPELINE_KEYS  # Legacy alias
HELIUS_API_KEY = PIPELINE_KEYS[0]

# RPC URLs (using first key from pipeline pool)
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_PREMIUM_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_PREMIUM_KEY}"

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8483614914:AAFjwtH2pct_OdZgi4zrcPNKq6zWdb62ypQ")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003534177506")
TELEGRAM_CHANNEL_NAME = "@TopwhaleTracker"
TELEGRAM_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "1153491543"))  # Admin user for DM alerts

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
