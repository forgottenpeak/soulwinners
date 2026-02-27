"""
SoulWinners Configuration Settings
"""
import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# API Keys - Helius Developer Plan
HELIUS_API_KEYS = [
    "896e7489-2609-4746-a57e-558dabfa3273",  # $50/month Developer plan (1000 req/sec)
]

# Default key for backwards compatibility
HELIUS_API_KEY = HELIUS_API_KEYS[0]
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
