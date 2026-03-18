"""
Hedgehog Configuration - Hybrid AI Setup

Primary: GPT-4o-mini (cheap, 95% of calls)
Secondary: Claude Sonnet 4 (expensive, critical decisions only)

Cost Target: $3-5/month
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path


@dataclass
class AIModelConfig:
    """Configuration for an AI model."""
    provider: str  # "openai" or "anthropic"
    model: str
    api_key: str
    cost_per_1k_input: float  # USD
    cost_per_1k_output: float  # USD
    max_tokens: int = 1024
    temperature: float = 0.7


@dataclass
class HedgehogConfig:
    """Configuration for Hedgehog AI Brain - Hybrid Setup."""

    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")
    database_path: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data" / "soulwinners.db")
    memory_path: Path = field(default_factory=lambda: Path(__file__).parent / "memory" / "hedgehog_memory.db")
    actions_log_path: Path = field(default_factory=lambda: Path(__file__).parent / "memory" / "actions.json")
    logs_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "logs")

    # =========================================================================
    # TELEGRAM CONFIG
    # =========================================================================
    telegram_bot_token: str = "8483614914:AAFjwtH2pct_OdZgi4zrcPNKq6zWdb62ypQ"
    admin_chat_id: int = 1153491543

    # =========================================================================
    # HYBRID AI SETUP
    # =========================================================================

    # Primary Model: GPT-4o-mini (cheap, fast, 95% of calls)
    primary_model: AIModelConfig = field(default_factory=lambda: AIModelConfig(
        provider="openai",
        model="gpt-4o-mini",
        api_key="os.getenv("OPENAI_API_KEY")",
        cost_per_1k_input=0.00015,   # $0.15/1M tokens
        cost_per_1k_output=0.0006,   # $0.60/1M tokens
        max_tokens=1024,
        temperature=0.7,
    ))

    # Secondary Model: Claude Sonnet 4 (expensive, critical only)
    secondary_model: AIModelConfig = field(default_factory=lambda: AIModelConfig(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key="os.getenv("ANTHROPIC_API_KEY")",
        cost_per_1k_input=0.003,     # $3/1M tokens
        cost_per_1k_output=0.015,    # $15/1M tokens
        max_tokens=2048,
        temperature=0.5,
    ))

    # =========================================================================
    # ROUTING THRESHOLDS - When to escalate to Claude
    # =========================================================================
    escalation_rules: Dict = field(default_factory=lambda: {
        # SOL thresholds
        "sol_threshold_trading": 5.0,      # Escalate if trade > 5 SOL
        "sol_threshold_critical": 10.0,    # Block if > 10 SOL without ML

        # Confidence thresholds
        "min_confidence_gpt": 0.80,        # Escalate if GPT confidence < 80%

        # Task types that always use Claude
        "claude_required_tasks": [
            "self_healing",
            "strategic_analysis",
            "complex_trading_decision",
            "system_failure",
            "security_sensitive",
        ],

        # Task types that always use GPT-4o-mini
        "gpt_only_tasks": [
            "log_analysis",
            "status_check",
            "simple_query",
            "telegram_response",
            "event_monitoring",
            "safety_classification",
        ],
    })

    # =========================================================================
    # COST CONTROL
    # =========================================================================
    max_daily_cost_usd: float = 0.20          # ~$6/month
    max_monthly_cost_usd: float = 5.00        # Hard limit
    max_daily_api_calls: int = 200            # Combined both models
    max_daily_claude_calls: int = 10          # Limit expensive model

    # =========================================================================
    # SAFETY & APPROVAL SETTINGS
    # =========================================================================
    require_approval_for_risky: bool = True
    block_destructive_actions: bool = True
    auto_restart_max_attempts: int = 3

    # Actions that need user approval
    approval_required_actions: List[str] = field(default_factory=lambda: [
        "update_config",
        "change_threshold",
        "add_api_key",
        "remove_api_key",
        "modify_trading_filter",
        "execute_trade",
    ])

    # Actions that are always blocked
    blocked_actions: List[str] = field(default_factory=lambda: [
        "delete_database",
        "drop_table",
        "truncate_table",
        "execute_trade_above_limit",
        "modify_core_logic",
    ])

    # Actions that auto-execute (SAFE)
    auto_execute_actions: List[str] = field(default_factory=lambda: [
        "monitor_logs",
        "restart_crashed_service",
        "fix_unknown_tokens",
        "rotate_api_keys",
        "send_alert",
        "answer_question",
        "check_status",
        "analyze_logs",
    ])

    # =========================================================================
    # SELF-HEALING SETTINGS
    # =========================================================================
    enable_self_healing: bool = True
    health_check_interval_sec: int = 300      # Every 5 minutes
    restart_cooldown_sec: int = 60            # Wait between restarts

    # Services to monitor
    monitored_services: Dict = field(default_factory=lambda: {
        "bot": {
            "pattern": "run_bot.py",
            "command": "python run_bot.py",
            "critical": True,
        },
        "webhook": {
            "pattern": "webhook_server.py",
            "command": "python webhook_server.py --port 8080",
            "critical": True,
        },
    })

    # =========================================================================
    # MEMORY SETTINGS
    # =========================================================================
    max_memory_entries: int = 10000
    error_retention_days: int = 30
    decision_retention_days: int = 90
    action_log_max_entries: int = 1000

    def __post_init__(self):
        """Ensure directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)

        # Override from environment if available
        if os.getenv("OPENAI_API_KEY"):
            self.primary_model.api_key = os.getenv("OPENAI_API_KEY")
        if os.getenv("ANTHROPIC_API_KEY"):
            self.secondary_model.api_key = os.getenv("ANTHROPIC_API_KEY")

    def get_model_for_task(self, task_type: str) -> str:
        """Determine which model to use for a task type."""
        if task_type in self.escalation_rules["claude_required_tasks"]:
            return "claude"
        if task_type in self.escalation_rules["gpt_only_tasks"]:
            return "gpt"
        return "gpt"  # Default to cheap model

    def is_action_auto_approved(self, action: str) -> bool:
        """Check if action can auto-execute without approval."""
        return action in self.auto_execute_actions

    def is_action_blocked(self, action: str) -> bool:
        """Check if action is always blocked."""
        return action in self.blocked_actions

    def requires_approval(self, action: str) -> bool:
        """Check if action needs user approval."""
        return action in self.approval_required_actions


# Global config instance
_config: Optional[HedgehogConfig] = None


def get_config() -> HedgehogConfig:
    """Get or create default config."""
    global _config
    if _config is None:
        _config = HedgehogConfig()
    return _config


def update_config(**kwargs) -> HedgehogConfig:
    """Update config with new values."""
    global _config
    if _config is None:
        _config = HedgehogConfig()

    for key, value in kwargs.items():
        if hasattr(_config, key):
            setattr(_config, key, value)

    return _config
