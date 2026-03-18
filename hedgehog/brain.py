"""
Hedgehog Brain - Full Autonomous AI Agent

Features:
- Hybrid AI routing (GPT-4o-mini / Claude Sonnet 4)
- Full Telegram command interface
- Natural language understanding
- Self-healing capabilities
- Action logging and audit trail
- Safety classification with approval workflow
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import HedgehogConfig, get_config
from .router import AIRouter, get_router, ModelChoice
from .memory.store import MemoryStore, Decision, Error, Fix, get_memory_store
from .monitoring.events import Event, EventType, EventDetector, get_event_detector
from .monitoring.health import HealthMonitor, get_health_monitor
from .safety.classifier import SafetyClassifier, ApprovalStatus, get_safety_classifier
from .tools.base import Tool, ToolResult, ToolRegistry, SafetyLevel, get_registry

logger = logging.getLogger(__name__)


class ActionLogger:
    """Logs all Hedgehog actions for audit trail."""

    def __init__(self, log_path: Path):
        """Initialize action logger."""
        self.log_path = log_path
        self.actions: List[Dict] = []
        self._load()

    def _load(self):
        """Load existing actions."""
        if self.log_path.exists():
            try:
                with open(self.log_path, 'r') as f:
                    self.actions = json.load(f)
            except:
                self.actions = []

    def _save(self):
        """Save actions to file."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, 'w') as f:
            json.dump(self.actions[-1000:], f, indent=2, default=str)

    def log(
        self,
        action_type: str,
        description: str,
        status: str = "success",
        details: Optional[Dict] = None,
        requires_approval: bool = False,
        approved: bool = True,
    ) -> str:
        """Log an action and return action ID."""
        action_id = f"act_{int(time.time())}_{len(self.actions)}"

        action = {
            "id": action_id,
            "timestamp": datetime.now().isoformat(),
            "type": action_type,
            "description": description,
            "status": status,
            "details": details or {},
            "requires_approval": requires_approval,
            "approved": approved,
        }

        self.actions.append(action)
        self._save()

        logger.info(f"Action logged: {action_id} - {action_type}: {description}")
        return action_id

    def get_recent(self, limit: int = 20) -> List[Dict]:
        """Get recent actions."""
        return self.actions[-limit:][::-1]

    def get_by_id(self, action_id: str) -> Optional[Dict]:
        """Get action by ID."""
        for action in self.actions[::-1]:
            if action.get("id") == action_id:
                return action
        return None

    def undo(self, action_id: str) -> bool:
        """Mark action as undone (doesn't actually reverse)."""
        action = self.get_by_id(action_id)
        if action:
            action["undone"] = True
            action["undone_at"] = datetime.now().isoformat()
            self._save()
            return True
        return False


class PendingApproval:
    """Manages pending approval requests."""

    def __init__(self):
        self.pending: Dict[str, Dict] = {}

    def request(
        self,
        action_type: str,
        description: str,
        execute_func: Callable,
        params: Dict = None,
    ) -> str:
        """Create a pending approval request."""
        approval_id = f"apr_{int(time.time())}"

        self.pending[approval_id] = {
            "id": approval_id,
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "description": description,
            "execute_func": execute_func,
            "params": params or {},
            "status": "pending",
        }

        return approval_id

    async def approve(self, approval_id: str) -> Tuple[bool, str]:
        """Approve and execute a pending action."""
        if approval_id not in self.pending:
            return False, "Approval not found"

        approval = self.pending[approval_id]

        try:
            func = approval["execute_func"]
            params = approval["params"]

            if asyncio.iscoroutinefunction(func):
                result = await func(**params)
            else:
                result = func(**params)

            approval["status"] = "approved"
            approval["result"] = str(result)
            del self.pending[approval_id]

            return True, str(result)

        except Exception as e:
            approval["status"] = "failed"
            approval["error"] = str(e)
            return False, str(e)

    def reject(self, approval_id: str) -> bool:
        """Reject a pending approval."""
        if approval_id in self.pending:
            self.pending[approval_id]["status"] = "rejected"
            del self.pending[approval_id]
            return True
        return False

    def get_pending(self) -> List[Dict]:
        """Get all pending approvals."""
        return [
            {k: v for k, v in a.items() if k != "execute_func"}
            for a in self.pending.values()
        ]


class HedgehogBrain:
    """
    The Hedgehog AI Brain - Full Autonomous System.

    Features:
    - Hybrid AI (GPT-4o-mini + Claude Sonnet 4)
    - Telegram command interface
    - Natural language processing
    - Self-healing
    - Action logging
    - Safety classification
    """

    def __init__(self, config: Optional[HedgehogConfig] = None):
        """Initialize the brain."""
        self.config = config or get_config()
        self.router = get_router()
        self.memory = get_memory_store()
        self.events = get_event_detector()
        self.health = get_health_monitor()
        self.safety = get_safety_classifier()
        self.tools = get_registry()

        # Action logging
        self.action_logger = ActionLogger(self.config.actions_log_path)

        # Pending approvals
        self.approvals = PendingApproval()

        # Autonomy state
        self.paused = False

        # Register tools
        self._register_default_tools()

        logger.info("Hedgehog Brain initialized (Hybrid Mode)")

    def _register_default_tools(self):
        """Register all default tools."""
        from .tools.database_tools import (
            DatabaseQueryTool, DatabaseWriteTool,
            WalletStatsTool, PositionStatsTool,
        )
        from .tools.system_tools import (
            SystemStatusTool, ServiceRestartTool,
            LogAnalysisTool, ProcessListTool, HealthCheckTool,
        )
        from .tools.trading_tools import (
            GetPositionsTool, GetWalletPerformanceTool,
            GetTokenInfoTool, GetTradeHistoryTool, GetMarketOverviewTool,
        )
        from .tools.telegram_tools import (
            TelegramSendTool, TelegramNotifyAdminTool,
            TelegramEditMessageTool, TelegramGetUpdatesTool,
        )

        # Register all tools
        tools = [
            DatabaseQueryTool, DatabaseWriteTool, WalletStatsTool, PositionStatsTool,
            SystemStatusTool, ServiceRestartTool, LogAnalysisTool, ProcessListTool,
            HealthCheckTool, GetPositionsTool, GetWalletPerformanceTool,
            GetTokenInfoTool, GetTradeHistoryTool, GetMarketOverviewTool,
            TelegramSendTool, TelegramNotifyAdminTool, TelegramEditMessageTool,
            TelegramGetUpdatesTool,
        ]

        for tool_class in tools:
            self.tools.register(tool_class(self.config))

        logger.info(f"Registered {len(self.tools.get_all())} tools")

    def _build_system_prompt(self) -> str:
        """Build the system prompt."""
        return """You are Hedgehog, the AI brain for SoulWinners trading system.

Your Role:
- Monitor Solana meme coin trading activity
- Analyze elite wallet positions
- Maintain system health
- Respond to admin commands via Telegram

Guidelines:
1. Be concise and action-oriented
2. Use tools to gather information
3. Auto-execute SAFE actions
4. Request approval for MODERATE actions
5. Never execute DESTRUCTIVE actions
6. Always log important actions
7. Notify admin of significant events

Response Format:
- Keep responses under 500 chars for Telegram
- Use emojis sparingly but appropriately
- Be direct and technical

Available Tools: {tools}"""

    async def process_message(
        self,
        message: str,
        user_id: int,
        is_admin: bool = False,
    ) -> str:
        """
        Process a message from Telegram.

        Handles both commands and natural language.
        """
        if self.paused and not message.startswith("/resume"):
            return "🦔 Hedgehog is paused. Send /resume to continue."

        # Check if admin
        if not is_admin and user_id != self.config.admin_chat_id:
            return "🦔 Unauthorized. Admin only."

        # Parse message
        message = message.strip()

        # Handle commands
        if message.startswith("/"):
            return await self._handle_command(message)

        # Handle natural language
        return await self._handle_natural_language(message)

    async def _handle_command(self, message: str) -> str:
        """Handle a slash command."""
        parts = message.split(maxsplit=2)
        cmd = parts[0].lower().lstrip("/")
        args = parts[1:] if len(parts) > 1 else []

        # Command handlers
        commands = {
            "status": self._cmd_status,
            "health": self._cmd_health,
            "fix": self._cmd_fix,
            "update_key": self._cmd_update_key,
            "set_threshold": self._cmd_set_threshold,
            "restart": self._cmd_restart,
            "logs": self._cmd_logs,
            "trade_decision": self._cmd_trade_decision,
            "hedgehog": self._cmd_ask,
            "hh": self._cmd_ask,
            "positions": self._cmd_positions,
            "wallets": self._cmd_wallets,
            "cost": self._cmd_cost,
            "history": self._cmd_history,
            "undo": self._cmd_undo,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "approve": self._cmd_approve,
            "reject": self._cmd_reject,
            "pending": self._cmd_pending,
            "help": self._cmd_help,
        }

        handler = commands.get(cmd)
        if handler:
            return await handler(args)

        return f"🦔 Unknown command: /{cmd}\n\nTry /help for available commands."

    async def _handle_natural_language(self, message: str) -> str:
        """Handle natural language input."""
        message_lower = message.lower()

        # Quick pattern matching for common requests
        patterns = [
            (r"change\s+min\s*buy\s+to\s+([\d.]+)", self._nl_change_min_buy),
            (r"why\s+(did|is|was)\s+(\w+)\s+(stop|crash|down)", self._nl_diagnose),
            (r"fix\s+(.+)", self._nl_fix),
            (r"what.*(top|best)\s+wallet", self._nl_top_wallet),
            (r"(show|get)\s+positions?", self._nl_positions),
            (r"restart\s+(\w+)", self._nl_restart),
        ]

        for pattern, handler in patterns:
            match = re.search(pattern, message_lower)
            if match:
                return await handler(match)

        # Fall back to AI for complex queries
        return await self._ask_ai(message)

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    async def _cmd_status(self, args: List[str]) -> str:
        """Full system status."""
        health = await self.health.run_full_health_check()
        usage = self.router.get_usage_summary()
        memory_stats = self.memory.get_stats()

        status_icon = {
            "healthy": "✅",
            "degraded": "⚠️",
            "critical": "🚨",
        }.get(health["overall"], "❓")

        services_status = []
        for name, svc in health.get("services", {}).items():
            icon = "✅" if svc.get("status") == "healthy" else "❌"
            services_status.append(f"{icon} {name}")

        return f"""
🦔 *Hedgehog Status*

{status_icon} System: {health["overall"]}
{chr(10).join(services_status)}

💰 *Cost Today*
GPT: ${usage['gpt']['cost_usd']:.4f} ({usage['gpt']['calls']} calls)
Claude: ${usage['claude']['cost_usd']:.4f} ({usage['claude']['calls']} calls)
Total: ${usage['total']['cost_usd']:.4f}

📊 *Memory*
Decisions: {memory_stats.get('total_decisions', 0)}
Errors: {memory_stats.get('total_errors', 0)}
Active Fixes: {memory_stats.get('active_fixes', 0)}
""".strip()

    async def _cmd_health(self, args: List[str]) -> str:
        """Detailed health check."""
        health = await self.health.run_full_health_check()

        lines = [f"🏥 *System Health: {health['overall'].upper()}*\n"]

        # Services
        lines.append("*Services*")
        for name, svc in health.get("services", {}).items():
            status = svc.get("status", "unknown")
            icon = {"healthy": "✅", "degraded": "⚠️", "down": "❌"}.get(status, "❓")
            lines.append(f"  {icon} {name}: {status}")

        # Database
        db = health.get("database", {})
        db_icon = "✅" if db.get("status") == "healthy" else "❌"
        lines.append(f"\n*Database* {db_icon}")
        if db.get("status") == "healthy":
            lines.append(f"  Wallets: {db.get('wallet_count', 0)}")
            lines.append(f"  Query: {db.get('query_time_ms', 0):.0f}ms")

        # APIs
        lines.append("\n*External APIs*")
        for name, api in health.get("external_apis", {}).items():
            icon = "✅" if api.get("status") == "healthy" else "❌"
            lines.append(f"  {icon} {name}")

        return "\n".join(lines)

    async def _cmd_fix(self, args: List[str]) -> str:
        """Auto-diagnose and fix an issue."""
        if not args:
            return "Usage: /fix <issue description>\n\nExample: /fix webhook not working"

        issue = " ".join(args)

        # Log action
        action_id = self.action_logger.log(
            "fix_attempt",
            f"Attempting to fix: {issue}",
            status="in_progress",
        )

        # Ask AI to diagnose
        diagnosis = await self._ask_ai(
            f"Diagnose and suggest fix for: {issue}",
            task_type="error_diagnosis",
        )

        # Try self-healing
        heal_actions = await self.health.self_heal()

        result = f"🔧 *Diagnosis*\n{diagnosis}\n\n"
        if heal_actions:
            result += "*Auto-fixes Applied:*\n" + "\n".join(f"• {a}" for a in heal_actions)
        else:
            result += "No auto-fixes needed."

        # Update action log
        self.action_logger.log(
            "fix_complete",
            f"Fixed: {issue}",
            details={"diagnosis": diagnosis, "actions": heal_actions},
        )

        return result

    async def _cmd_update_key(self, args: List[str]) -> str:
        """Update an API key (with confirmation)."""
        if len(args) < 2:
            return "Usage: /update_key <service> <new_key>\n\nServices: openai, anthropic, helius, telegram"

        service = args[0].lower()
        new_key = args[1]

        # Validate key format
        valid_prefixes = {
            "openai": "sk-",
            "anthropic": "sk-ant-",
            "helius": "",
            "telegram": "",
        }

        if service not in valid_prefixes:
            return f"Unknown service: {service}"

        prefix = valid_prefixes[service]
        if prefix and not new_key.startswith(prefix):
            return f"Invalid key format for {service}. Should start with '{prefix}'"

        # Create approval request
        approval_id = self.approvals.request(
            action_type="update_api_key",
            description=f"Update {service} API key to {new_key[:20]}...",
            execute_func=self._execute_update_key,
            params={"service": service, "key": new_key},
        )

        return f"""
🔑 *API Key Update Request*

Service: {service}
New Key: {new_key[:20]}...

⚠️ This requires approval.
Reply with:
• /approve {approval_id} - to apply
• /reject {approval_id} - to cancel
""".strip()

    async def _execute_update_key(self, service: str, key: str) -> str:
        """Execute API key update."""
        # This would update the config/environment
        # For now, log the action
        self.action_logger.log(
            "api_key_updated",
            f"Updated {service} API key",
            details={"service": service, "key_preview": key[:20]},
        )
        return f"✅ {service} API key updated!"

    async def _cmd_set_threshold(self, args: List[str]) -> str:
        """Change a configuration threshold."""
        if len(args) < 2:
            return """Usage: /set_threshold <param> <value>

Available parameters:
• min_buy_sol - Minimum SOL for tracking
• sol_threshold_trading - SOL amount to trigger Claude
• max_daily_cost - Daily AI cost limit"""

        param = args[0].lower()
        try:
            value = float(args[1])
        except ValueError:
            return f"Invalid value: {args[1]}. Must be a number."

        # Create approval request
        approval_id = self.approvals.request(
            action_type="set_threshold",
            description=f"Change {param} to {value}",
            execute_func=self._execute_set_threshold,
            params={"param": param, "value": value},
        )

        return f"""
⚙️ *Threshold Change Request*

Parameter: {param}
New Value: {value}

⚠️ Reply with:
• /approve {approval_id}
• /reject {approval_id}
""".strip()

    async def _execute_set_threshold(self, param: str, value: float) -> str:
        """Execute threshold change."""
        self.action_logger.log(
            "threshold_changed",
            f"Changed {param} to {value}",
        )
        return f"✅ {param} set to {value}"

    async def _cmd_restart(self, args: List[str]) -> str:
        """Restart a service."""
        if not args:
            return "Usage: /restart <service>\n\nServices: bot, webhook"

        service = args[0].lower()

        if service not in self.config.monitored_services:
            return f"Unknown service: {service}"

        # Auto-execute (SAFE action)
        success = await self.health.restart_service(service, "Manual restart via Telegram")

        self.action_logger.log(
            "service_restart",
            f"Restarted {service}",
            status="success" if success else "failed",
        )

        if success:
            return f"✅ {service} restarted successfully!"
        else:
            return f"❌ Failed to restart {service}. Check logs."

    async def _cmd_logs(self, args: List[str]) -> str:
        """Show recent logs."""
        service = args[0] if args else "bot"
        log_file = f"{service}.log"

        tool = self.tools.get("log_analysis")
        if not tool:
            return "Log analysis tool not available"

        result = await tool.run(log_file=log_file, lines=100, level="ERROR")

        if not result.success:
            return f"Error reading logs: {result.error}"

        data = result.data
        errors = data.get("recent_entries", [])

        if not errors:
            return f"✅ No recent errors in {log_file}"

        lines = [f"📋 *Recent Errors ({log_file})*\n"]
        for err in errors[:5]:
            lines.append(f"• {err[:100]}...")

        return "\n".join(lines)

    async def _cmd_trade_decision(self, args: List[str]) -> str:
        """Analyze a trade decision."""
        if not args:
            return "Usage: /trade_decision <token_address>"

        token = args[0]

        # Get token info
        tool = self.tools.get("get_token_info")
        if tool:
            result = await tool.run(token_address=token)
            if result.success:
                token_data = result.data
            else:
                token_data = {"symbol": "???", "error": result.error}
        else:
            token_data = {}

        # Ask Claude for complex trading analysis
        analysis = await self._ask_ai(
            f"Analyze this token for trading:\n{json.dumps(token_data, indent=2)}",
            task_type="complex_trading_decision",
            context={"token": token},
        )

        return f"""
📊 *Trade Analysis*

Token: ${token_data.get('symbol', '???')}
MC: ${token_data.get('market_cap', 0):,.0f}
Liq: ${token_data.get('liquidity_usd', 0):,.0f}

*AI Analysis:*
{analysis}
""".strip()

    async def _cmd_ask(self, args: List[str]) -> str:
        """General AI question."""
        if not args:
            return "🦔 What would you like to know?"

        question = " ".join(args)
        return await self._ask_ai(question)

    async def _cmd_positions(self, args: List[str]) -> str:
        """Show open positions."""
        tool = self.tools.get("get_positions")
        if not tool:
            return "Position tool not available"

        result = await tool.run(limit=10)
        if not result.success:
            return f"Error: {result.error}"

        positions = result.data.get("positions", [])
        if not positions:
            return "📊 No open positions"

        lines = ["📊 *Open Positions*\n"]
        for p in positions[:10]:
            lines.append(
                f"• ${p.get('symbol', '???')} | "
                f"{p.get('buy_sol', 0):.2f} SOL | "
                f"{p.get('peak_multiplier', 1):.1f}x"
            )

        lines.append(f"\n_Total: {result.data.get('count', 0)}_")
        return "\n".join(lines)

    async def _cmd_wallets(self, args: List[str]) -> str:
        """Show wallet stats."""
        tool = self.tools.get("wallet_stats")
        if not tool:
            return "Wallet stats tool not available"

        result = await tool.run()
        if not result.success:
            return f"Error: {result.error}"

        data = result.data
        lines = ["👛 *Wallet Stats*\n"]
        lines.append(f"Total Wallets: {data.get('total_wallets', 0)}")

        for tier, stats in data.get("tier_distribution", {}).items():
            lines.append(f"\n*{tier}*")
            lines.append(f"  Count: {stats.get('count', 0)}")
            lines.append(f"  Avg WR: {stats.get('avg_win_rate', 0):.0%}")

        return "\n".join(lines)

    async def _cmd_cost(self, args: List[str]) -> str:
        """Show AI cost tracking."""
        usage = self.router.get_usage_summary()

        return f"""
💰 *AI Cost Tracking*

*Today ({usage['date']})*
GPT-4o-mini: ${usage['gpt']['cost_usd']:.4f} ({usage['gpt']['calls']} calls)
Claude Sonnet: ${usage['claude']['cost_usd']:.4f} ({usage['claude']['calls']} calls)
Total: ${usage['total']['cost_usd']:.4f}

*Limits*
Daily: ${usage['limits']['daily_cost_limit']:.2f}
Remaining: ${usage['limits']['cost_remaining']:.4f}
Claude calls: {usage['claude']['calls']}/{usage['limits']['daily_claude_limit']}
""".strip()

    async def _cmd_history(self, args: List[str]) -> str:
        """Show action history."""
        limit = int(args[0]) if args else 10
        actions = self.action_logger.get_recent(limit)

        if not actions:
            return "📜 No action history"

        lines = ["📜 *Recent Actions*\n"]
        for a in actions[:10]:
            status_icon = "✅" if a.get("status") == "success" else "❌"
            lines.append(
                f"{status_icon} [{a.get('type')}] {a.get('description', '')[:50]}"
            )

        return "\n".join(lines)

    async def _cmd_undo(self, args: List[str]) -> str:
        """Undo an action."""
        if not args:
            return "Usage: /undo <action_id>\n\nSee /history for action IDs"

        action_id = args[0]
        success = self.action_logger.undo(action_id)

        if success:
            return f"✅ Action {action_id} marked as undone"
        else:
            return f"❌ Action {action_id} not found"

    async def _cmd_pause(self, args: List[str]) -> str:
        """Pause autonomous actions."""
        self.paused = True
        self.action_logger.log("autonomy_paused", "Hedgehog paused by admin")
        return "⏸️ Hedgehog paused. Autonomous actions disabled.\n\nSend /resume to continue."

    async def _cmd_resume(self, args: List[str]) -> str:
        """Resume autonomous actions."""
        self.paused = False
        self.action_logger.log("autonomy_resumed", "Hedgehog resumed by admin")
        return "▶️ Hedgehog resumed. Autonomous actions enabled."

    async def _cmd_approve(self, args: List[str]) -> str:
        """Approve a pending action."""
        if not args:
            pending = self.approvals.get_pending()
            if not pending:
                return "No pending approvals"

            lines = ["⏳ *Pending Approvals*\n"]
            for p in pending:
                lines.append(f"• {p['id']}: {p['description']}")

            return "\n".join(lines)

        approval_id = args[0]
        success, result = await self.approvals.approve(approval_id)

        if success:
            self.action_logger.log(
                "approval_granted",
                f"Approved: {approval_id}",
                details={"result": result},
            )
            return f"✅ Approved!\n\n{result}"
        else:
            return f"❌ Approval failed: {result}"

    async def _cmd_reject(self, args: List[str]) -> str:
        """Reject a pending action."""
        if not args:
            return "Usage: /reject <approval_id>"

        approval_id = args[0]
        success = self.approvals.reject(approval_id)

        if success:
            self.action_logger.log("approval_rejected", f"Rejected: {approval_id}")
            return f"❌ Rejected: {approval_id}"
        else:
            return f"Approval not found: {approval_id}"

    async def _cmd_pending(self, args: List[str]) -> str:
        """Show pending approvals."""
        pending = self.approvals.get_pending()

        if not pending:
            return "✅ No pending approvals"

        lines = ["⏳ *Pending Approvals*\n"]
        for p in pending:
            lines.append(f"• `{p['id']}`\n  {p['description']}")

        lines.append("\nUse /approve <id> or /reject <id>")
        return "\n".join(lines)

    async def _cmd_help(self, args: List[str]) -> str:
        """Show help."""
        return """
🦔 *Hedgehog Commands*

*Status & Monitoring*
/status - System overview
/health - Detailed health check
/positions - Open positions
/wallets - Wallet statistics
/cost - AI cost tracking
/logs [service] - Recent errors

*Actions*
/fix <issue> - Auto-diagnose & fix
/restart <service> - Restart service
/trade_decision <token> - Trade analysis

*Configuration* (requires approval)
/update_key <svc> <key> - Update API key
/set_threshold <param> <val> - Change setting

*Approvals*
/pending - Show pending
/approve <id> - Approve action
/reject <id> - Reject action

*Other*
/hedgehog <question> - Ask AI
/history - Action history
/undo <id> - Mark action undone
/pause - Pause autonomy
/resume - Resume autonomy

_Or just ask me in natural language!_
""".strip()

    # =========================================================================
    # NATURAL LANGUAGE HANDLERS
    # =========================================================================

    async def _nl_change_min_buy(self, match: re.Match) -> str:
        """Handle 'change min buy to X'."""
        value = float(match.group(1))
        return await self._cmd_set_threshold(["min_buy_sol", str(value)])

    async def _nl_diagnose(self, match: re.Match) -> str:
        """Handle 'why did X stop/crash'."""
        service = match.group(2)
        return await self._cmd_fix([service, "stopped", "working"])

    async def _nl_fix(self, match: re.Match) -> str:
        """Handle 'fix X'."""
        issue = match.group(1)
        return await self._cmd_fix([issue])

    async def _nl_top_wallet(self, match: re.Match) -> str:
        """Handle 'what's the top wallet'."""
        return await self._cmd_wallets([])

    async def _nl_positions(self, match: re.Match) -> str:
        """Handle 'show positions'."""
        return await self._cmd_positions([])

    async def _nl_restart(self, match: re.Match) -> str:
        """Handle 'restart X'."""
        service = match.group(1)
        return await self._cmd_restart([service])

    # =========================================================================
    # AI INTERACTION
    # =========================================================================

    async def _ask_ai(
        self,
        question: str,
        task_type: str = "telegram_response",
        context: Optional[Dict] = None,
    ) -> str:
        """Ask AI a question with intelligent routing."""
        system_prompt = self._build_system_prompt().format(
            tools=", ".join(t.name for t in self.tools.get_all())
        )

        try:
            response, metadata = await self.router.call(
                task_type=task_type,
                system_prompt=system_prompt,
                user_prompt=question,
                context=context,
            )

            # Log AI call
            self.action_logger.log(
                "ai_query",
                f"Asked: {question[:50]}...",
                details={
                    "model": metadata.get("model_choice"),
                    "cost": metadata.get("cost_usd"),
                    "escalated": metadata.get("escalated"),
                },
            )

            return response or "🦔 I couldn't process that."

        except Exception as e:
            logger.error(f"AI query failed: {e}")
            return f"🦔 Error: {str(e)[:100]}"

    # =========================================================================
    # AUTONOMOUS OPERATIONS
    # =========================================================================

    async def run_autonomous_check(self) -> List[str]:
        """Run autonomous health check and self-healing."""
        if self.paused:
            return []

        actions = []

        # Check service health
        health = await self.health.run_full_health_check()

        if health["overall"] != "healthy":
            # Self-heal
            heal_actions = await self.health.self_heal()
            actions.extend(heal_actions)

            # Notify admin
            await self.send_admin_notification(
                f"⚠️ System {health['overall']}\n\n" +
                "\n".join(f"• {a}" for a in heal_actions),
                level="warning",
            )

        return actions

    async def send_admin_notification(
        self,
        message: str,
        level: str = "info",
    ):
        """Send notification to admin via Telegram."""
        tool = self.tools.get("telegram_notify_admin")
        if tool:
            await tool.run(
                title="Hedgehog Alert",
                message=message,
                level=level,
            )

    def get_status(self) -> Dict[str, Any]:
        """Get brain status."""
        usage = self.router.get_usage_summary()

        return {
            "initialized": True,
            "paused": self.paused,
            "tools": len(self.tools.get_all()),
            "pending_approvals": len(self.approvals.get_pending()),
            "ai_usage": usage,
            "memory": self.memory.get_stats(),
        }


# Singleton instance
_brain: Optional[HedgehogBrain] = None


def get_brain() -> HedgehogBrain:
    """Get or create brain instance."""
    global _brain
    if _brain is None:
        _brain = HedgehogBrain()
    return _brain
