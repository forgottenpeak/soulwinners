"""
Hedgehog Configuration
Dynamic paths - works LOCAL and VPS
Complete autonomous trading agent settings
"""
import os
import json
from pathlib import Path

# =============================================================================
# BASE PATHS
# =============================================================================

BASE_DIR = Path(__file__).parent
MEMORY_DIR = BASE_DIR / "memory"

# SoulWinners paths
SOULWINNERS_PATH = Path(os.getenv("SOULWINNERS_PATH", "/root/Soulwinners"))
DEFAULT_DB_PATH = SOULWINNERS_PATH / "soulwinners.db"
LOCAL_TEST_DB = BASE_DIR / "test_data" / "test.db"


def get_db_path() -> Path:
    """Get database path based on environment"""
    env_path = os.getenv("HEDGEHOG_DB_PATH")
    if env_path:
        return Path(env_path)

    if DEFAULT_DB_PATH.exists():
        return DEFAULT_DB_PATH

    return LOCAL_TEST_DB


# =============================================================================
# API KEYS
# =============================================================================

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_TOKENS = json.loads(os.getenv("TELEGRAM_BOT_TOKENS", "{}"))
TELEGRAM_ALERT_CHAT_ID = os.getenv("TELEGRAM_ALERT_CHAT_ID", "")

# LLM APIs
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Solana/Helius
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
SOLANA_RPC_URL = os.getenv(
    "SOLANA_RPC_URL",
    f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}" if HELIUS_API_KEY else ""
)

# Jupiter
JUPITER_API_URL = os.getenv("JUPITER_API_URL", "https://quote-api.jup.ag/v6")

# Wallet (KEEP SECURE - use env vars only)
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")
WALLET_PUBLIC_KEY = os.getenv("WALLET_PUBLIC_KEY", "")

# =============================================================================
# LLM SETTINGS
# =============================================================================

LLM_CONFIG = {
    "default": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "max_tokens": 1024,
        "temperature": 0.7,
    },
    "reasoning": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2048,
        "temperature": 0.5,
    }
}

# ReAct settings
MAX_ITERATIONS = 5
CONVERSATION_HISTORY_LIMIT = 50

# =============================================================================
# TRADING CONFIGURATION
# =============================================================================

TRADING_CONFIG = {
    # Position sizing
    "max_position_percent": float(os.getenv("MAX_POSITION_PERCENT", "10")),  # Max 10% per trade
    "min_trade_sol": float(os.getenv("MIN_TRADE_SOL", "0.01")),  # Minimum trade size
    "max_trade_sol": float(os.getenv("MAX_TRADE_SOL", "1.0")),   # Maximum trade size

    # Slippage and fees
    "default_slippage_bps": int(os.getenv("SLIPPAGE_BPS", "100")),  # 1% default
    "max_slippage_bps": int(os.getenv("MAX_SLIPPAGE_BPS", "500")),  # 5% max

    # Risk management
    "stop_loss_percent": float(os.getenv("STOP_LOSS_PERCENT", "50")),     # -50% stop loss
    "take_profit_percent": float(os.getenv("TAKE_PROFIT_PERCENT", "100")), # 100% take profit

    # Auto-trading (when enabled)
    "auto_trade_enabled": os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true",
    "auto_trade_max_daily_sol": float(os.getenv("AUTO_TRADE_MAX_DAILY", "5.0")),
    "require_approval_above_sol": float(os.getenv("REQUIRE_APPROVAL_SOL", "1.0")),

    # ML thresholds
    "ml_confidence_threshold": float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.7")),
    "elite_wallet_only": os.getenv("ELITE_WALLET_ONLY", "false").lower() == "true",
}

# Token safety requirements
SAFETY_CONFIG = {
    "check_freeze_authority": True,
    "check_mint_authority": True,
    "max_holder_concentration": 80,  # Skip if top 10 holders own >80%
    "min_liquidity_usd": 1000,
    "max_token_age_hours": 24,  # Prefer fresh tokens
}

# =============================================================================
# MONITORING CONFIGURATION
# =============================================================================

MONITORING_CONFIG = {
    "health_check_interval_minutes": 5,
    "alert_severity_threshold": "high",  # low, medium, high, critical
    "auto_fix_enabled": True,
    "auto_fix_actions": [
        "fix_rate_limits",
        "clear_database_locks",
        "optimize_database",
    ],
    "require_approval_actions": [
        "restart_failed_service",
        "toggle_cron_job",
        "rotate_api_key",
    ],
}

# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """You are Hedgehog, an autonomous AI trading agent for the SoulWinners Solana trading system.

CAPABILITIES:

1. TRADING
   - Execute swaps via Jupiter aggregator
   - Copy insider wallet trades
   - Take profit on positions
   - Check wallet balances and positions
   - Verify token safety before buying

2. LEARNING
   - Track trade outcomes (entry, exit, ROI)
   - Rank insider wallets by performance (Elite >80%, Good >60%, Average <60%)
   - Optimize ML confidence thresholds
   - Identify winning patterns

3. SYSTEM MANAGEMENT
   - Monitor webhook, scanner, and bot health
   - Check API rate limits and rotate keys
   - Manage cron jobs
   - Run diagnostics and self-heal issues

4. TELEGRAM
   - Send alerts to channels
   - Check bot health
   - Broadcast messages

SAFETY RULES:
- Never trade more than 10% of wallet in single trade
- Always check token safety before buying
- Require approval for trades >1 SOL
- Stop loss at -50%

APPROVAL REQUIRED FOR:
- execute_swap, copy_insider_trade, take_profit (real trades)
- restart_webhook, restart_bot, restart_failed_service
- toggle_cron_job, rotate_api_key
- update_ml_threshold

When given a task:
1. Use tools to get real data
2. Apply learned patterns and recommendations
3. Warn about risky actions
4. Be concise with numbers and facts

You learn from every trade. Check wallet rankings and ML performance before recommending trades."""
