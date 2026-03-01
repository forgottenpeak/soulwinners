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
# HELIUS API KEY POOLS (Separate free vs premium for cost optimization)
# =============================================================================

# FREE KEYS - Use for background jobs (4 keys = 400 req/sec capacity)
# - Main pipeline (every 2 hours)
# - Insider detection (every 15 min)
# - Cluster analysis (every 20 min)
HELIUS_FREE_KEYS = [
    "59648c8b-a691-451b-b1ee-3542ad7afd36",  # Free Key 1
    "2c353fb3-653a-47d2-8247-2286ac7098a8",  # Free Key 2
    "ee2a7d3e-2935-4736-8c3f-113c268f5510",  # Free Key 3
    "b371c9f4-2ff4-4426-8949-7125b814a421",  # Free Key 4
]

# PREMIUM KEY - Use ONLY for real-time monitoring ($49/month)
# - Real-time wallet monitoring (60-sec polling)
# - Buy alert detection
# - Higher rate limits, priority access
HELIUS_PREMIUM_KEY = os.getenv(
    "HELIUS_PREMIUM_KEY",
    "59648c8b-a691-451b-b1ee-3542ad7afd36"  # Default to free key if not set
)

# Legacy: All keys combined for backwards compatibility
HELIUS_API_KEYS = HELIUS_FREE_KEYS

# Default key for backwards compatibility
HELIUS_API_KEY = HELIUS_FREE_KEYS[0]
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# Premium RPC URL for real-time monitoring
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
