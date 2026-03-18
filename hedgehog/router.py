"""
Hedgehog AI Router - Intelligent Model Selection

Routes requests between:
- GPT-4o-mini (primary, cheap, 95% of calls)
- Claude Sonnet 4 (secondary, expensive, critical only)

Routing Logic:
1. Default: GPT-4o-mini for cost efficiency
2. Escalate to Claude when:
   - Trading decision > 5 SOL
   - System failure detected
   - Strategic analysis needed
   - Complex reasoning required
   - GPT confidence < 80%
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .config import HedgehogConfig, get_config, AIModelConfig

logger = logging.getLogger(__name__)


class ModelChoice(Enum):
    """Which model to use."""
    GPT = "gpt"
    CLAUDE = "claude"


class TaskComplexity(Enum):
    """Task complexity levels."""
    SIMPLE = "simple"       # Status checks, simple queries
    MODERATE = "moderate"   # Log analysis, event monitoring
    COMPLEX = "complex"     # Trading decisions, debugging
    CRITICAL = "critical"   # Self-healing, security, strategy


@dataclass
class RoutingDecision:
    """Result of routing decision."""
    model: ModelChoice
    reason: str
    task_type: str
    complexity: TaskComplexity
    estimated_cost: float = 0.0
    escalated: bool = False


@dataclass
class UsageStats:
    """Track API usage for cost control."""
    date: str = field(default_factory=lambda: date.today().isoformat())
    gpt_calls: int = 0
    gpt_input_tokens: int = 0
    gpt_output_tokens: int = 0
    gpt_cost_usd: float = 0.0
    claude_calls: int = 0
    claude_input_tokens: int = 0
    claude_output_tokens: int = 0
    claude_cost_usd: float = 0.0

    @property
    def total_calls(self) -> int:
        return self.gpt_calls + self.claude_calls

    @property
    def total_cost_usd(self) -> float:
        return self.gpt_cost_usd + self.claude_cost_usd


class AIRouter:
    """
    Intelligent router for hybrid AI setup.

    Routes requests to the appropriate model based on:
    - Task complexity
    - Cost optimization
    - Confidence requirements
    - Daily limits
    """

    def __init__(self, config: Optional[HedgehogConfig] = None):
        """Initialize router."""
        self.config = config or get_config()
        self.usage = UsageStats()
        self._openai_client = None
        self._anthropic_client = None

        # Task complexity mapping
        self.task_complexity_map = {
            # Simple tasks (GPT-4o-mini)
            "status_check": TaskComplexity.SIMPLE,
            "simple_query": TaskComplexity.SIMPLE,
            "telegram_response": TaskComplexity.SIMPLE,
            "answer_question": TaskComplexity.SIMPLE,

            # Moderate tasks (GPT-4o-mini)
            "log_analysis": TaskComplexity.MODERATE,
            "event_monitoring": TaskComplexity.MODERATE,
            "safety_classification": TaskComplexity.MODERATE,
            "fix_unknown_tokens": TaskComplexity.MODERATE,

            # Complex tasks (may escalate to Claude)
            "trading_decision": TaskComplexity.COMPLEX,
            "wallet_analysis": TaskComplexity.COMPLEX,
            "error_diagnosis": TaskComplexity.COMPLEX,

            # Critical tasks (Claude preferred)
            "self_healing": TaskComplexity.CRITICAL,
            "strategic_analysis": TaskComplexity.CRITICAL,
            "system_failure": TaskComplexity.CRITICAL,
            "security_sensitive": TaskComplexity.CRITICAL,
            "complex_trading_decision": TaskComplexity.CRITICAL,
        }

    def _init_clients(self):
        """Initialize API clients lazily."""
        if self._openai_client is None:
            try:
                import openai
                self._openai_client = openai.OpenAI(
                    api_key=self.config.primary_model.api_key
                )
                logger.info("OpenAI client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI: {e}")

        if self._anthropic_client is None:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(
                    api_key=self.config.secondary_model.api_key
                )
                logger.info("Anthropic client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Anthropic: {e}")

    def _reset_daily_stats(self):
        """Reset stats if new day."""
        today = date.today().isoformat()
        if self.usage.date != today:
            logger.info(f"New day - resetting usage stats. Yesterday: ${self.usage.total_cost_usd:.4f}")
            self.usage = UsageStats(date=today)

    def route(
        self,
        task_type: str,
        context: Optional[Dict] = None,
        force_model: Optional[ModelChoice] = None,
    ) -> RoutingDecision:
        """
        Decide which model to use for a task.

        Args:
            task_type: Type of task (e.g., "trading_decision", "log_analysis")
            context: Additional context (e.g., SOL amount, confidence score)
            force_model: Force a specific model (override routing)

        Returns:
            RoutingDecision with model choice and reasoning
        """
        self._reset_daily_stats()
        context = context or {}

        # Force model if specified
        if force_model:
            return RoutingDecision(
                model=force_model,
                reason="Forced by caller",
                task_type=task_type,
                complexity=self.task_complexity_map.get(task_type, TaskComplexity.MODERATE),
            )

        # Get task complexity
        complexity = self.task_complexity_map.get(task_type, TaskComplexity.MODERATE)

        # Check daily limits
        if self.usage.total_cost_usd >= self.config.max_daily_cost_usd:
            logger.warning("Daily cost limit reached - using GPT only")
            return RoutingDecision(
                model=ModelChoice.GPT,
                reason="Daily cost limit reached",
                task_type=task_type,
                complexity=complexity,
            )

        if self.usage.claude_calls >= self.config.max_daily_claude_calls:
            logger.warning("Daily Claude limit reached - using GPT")
            return RoutingDecision(
                model=ModelChoice.GPT,
                reason="Daily Claude call limit reached",
                task_type=task_type,
                complexity=complexity,
            )

        # Check if task requires Claude
        if task_type in self.config.escalation_rules["claude_required_tasks"]:
            return RoutingDecision(
                model=ModelChoice.CLAUDE,
                reason=f"Task type '{task_type}' requires Claude",
                task_type=task_type,
                complexity=complexity,
                escalated=True,
            )

        # Check if task should always use GPT
        if task_type in self.config.escalation_rules["gpt_only_tasks"]:
            return RoutingDecision(
                model=ModelChoice.GPT,
                reason=f"Task type '{task_type}' optimized for GPT",
                task_type=task_type,
                complexity=complexity,
            )

        # Check context-based escalation
        sol_amount = context.get("sol_amount", 0)
        if sol_amount > self.config.escalation_rules["sol_threshold_trading"]:
            return RoutingDecision(
                model=ModelChoice.CLAUDE,
                reason=f"Trade amount ({sol_amount} SOL) exceeds threshold",
                task_type=task_type,
                complexity=complexity,
                escalated=True,
            )

        confidence = context.get("confidence", 1.0)
        if confidence < self.config.escalation_rules["min_confidence_gpt"]:
            return RoutingDecision(
                model=ModelChoice.CLAUDE,
                reason=f"Low confidence ({confidence:.0%}) - escalating",
                task_type=task_type,
                complexity=complexity,
                escalated=True,
            )

        # Check complexity-based routing
        if complexity == TaskComplexity.CRITICAL:
            return RoutingDecision(
                model=ModelChoice.CLAUDE,
                reason="Critical task complexity",
                task_type=task_type,
                complexity=complexity,
                escalated=True,
            )

        # Default to GPT-4o-mini (cost optimization)
        return RoutingDecision(
            model=ModelChoice.GPT,
            reason="Default routing - cost optimized",
            task_type=task_type,
            complexity=complexity,
        )

    async def call(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
        force_model: Optional[ModelChoice] = None,
    ) -> Tuple[Optional[str], Dict]:
        """
        Make an AI API call with intelligent routing.

        Args:
            task_type: Type of task for routing
            system_prompt: System prompt
            user_prompt: User prompt
            context: Additional context for routing
            tools: Tool schemas (optional)
            force_model: Force a specific model

        Returns:
            (response_text, metadata) tuple
        """
        self._init_clients()

        # Route to appropriate model
        decision = self.route(task_type, context, force_model)
        logger.info(f"Routing: {task_type} -> {decision.model.value} ({decision.reason})")

        start_time = time.time()

        try:
            if decision.model == ModelChoice.GPT:
                response, metadata = await self._call_openai(
                    system_prompt, user_prompt, tools
                )
            else:
                response, metadata = await self._call_anthropic(
                    system_prompt, user_prompt, tools
                )

            # Update usage stats
            metadata["model_choice"] = decision.model.value
            metadata["task_type"] = task_type
            metadata["routing_reason"] = decision.reason
            metadata["escalated"] = decision.escalated
            metadata["latency_ms"] = (time.time() - start_time) * 1000

            return response, metadata

        except Exception as e:
            logger.error(f"API call failed: {e}")

            # Try fallback if primary fails
            if decision.model == ModelChoice.GPT and self._anthropic_client:
                logger.warning("GPT failed - falling back to Claude")
                return await self._call_anthropic(system_prompt, user_prompt, tools)

            raise

    async def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[Optional[str], Dict]:
        """Call OpenAI GPT-4o-mini."""
        if not self._openai_client:
            raise RuntimeError("OpenAI client not initialized")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = {
            "model": self.config.primary_model.model,
            "messages": messages,
            "max_tokens": self.config.primary_model.max_tokens,
            "temperature": self.config.primary_model.temperature,
        }

        if tools:
            # Convert to OpenAI format
            kwargs["tools"] = [
                {"type": "function", "function": t} for t in tools
            ]

        response = self._openai_client.chat.completions.create(**kwargs)

        # Extract response
        choice = response.choices[0]
        text = choice.message.content or ""

        # Handle tool calls
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                })

        # Calculate cost
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        cost = (
            input_tokens * self.config.primary_model.cost_per_1k_input / 1000 +
            output_tokens * self.config.primary_model.cost_per_1k_output / 1000
        )

        # Update stats
        self.usage.gpt_calls += 1
        self.usage.gpt_input_tokens += input_tokens
        self.usage.gpt_output_tokens += output_tokens
        self.usage.gpt_cost_usd += cost

        logger.debug(f"GPT call: {input_tokens}+{output_tokens} tokens, ${cost:.4f}")

        return text, {
            "model": "gpt-4o-mini",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "tool_calls": tool_calls,
        }

    async def _call_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[Optional[str], Dict]:
        """Call Anthropic Claude Sonnet 4."""
        if not self._anthropic_client:
            raise RuntimeError("Anthropic client not initialized")

        kwargs = {
            "model": self.config.secondary_model.model,
            "max_tokens": self.config.secondary_model.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        if tools:
            kwargs["tools"] = tools

        response = self._anthropic_client.messages.create(**kwargs)

        # Extract response
        text = ""
        tool_calls = []

        for content in response.content:
            if content.type == "text":
                text += content.text
            elif content.type == "tool_use":
                tool_calls.append({
                    "name": content.name,
                    "arguments": content.input,
                })

        # Calculate cost
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = (
            input_tokens * self.config.secondary_model.cost_per_1k_input / 1000 +
            output_tokens * self.config.secondary_model.cost_per_1k_output / 1000
        )

        # Update stats
        self.usage.claude_calls += 1
        self.usage.claude_input_tokens += input_tokens
        self.usage.claude_output_tokens += output_tokens
        self.usage.claude_cost_usd += cost

        logger.debug(f"Claude call: {input_tokens}+{output_tokens} tokens, ${cost:.4f}")

        return text, {
            "model": "claude-sonnet-4",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "tool_calls": tool_calls,
        }

    def get_usage_summary(self) -> Dict:
        """Get usage summary."""
        self._reset_daily_stats()

        return {
            "date": self.usage.date,
            "gpt": {
                "calls": self.usage.gpt_calls,
                "tokens": self.usage.gpt_input_tokens + self.usage.gpt_output_tokens,
                "cost_usd": round(self.usage.gpt_cost_usd, 4),
            },
            "claude": {
                "calls": self.usage.claude_calls,
                "tokens": self.usage.claude_input_tokens + self.usage.claude_output_tokens,
                "cost_usd": round(self.usage.claude_cost_usd, 4),
            },
            "total": {
                "calls": self.usage.total_calls,
                "cost_usd": round(self.usage.total_cost_usd, 4),
            },
            "limits": {
                "daily_cost_limit": self.config.max_daily_cost_usd,
                "daily_claude_limit": self.config.max_daily_claude_calls,
                "cost_remaining": round(
                    self.config.max_daily_cost_usd - self.usage.total_cost_usd, 4
                ),
            },
        }

    def estimate_cost(self, task_type: str, estimated_tokens: int = 500) -> float:
        """Estimate cost for a task."""
        decision = self.route(task_type)

        if decision.model == ModelChoice.GPT:
            model = self.config.primary_model
        else:
            model = self.config.secondary_model

        # Estimate 50/50 input/output split
        cost = (
            (estimated_tokens / 2) * model.cost_per_1k_input / 1000 +
            (estimated_tokens / 2) * model.cost_per_1k_output / 1000
        )

        return cost


# Singleton instance
_router: Optional[AIRouter] = None


def get_router() -> AIRouter:
    """Get or create router instance."""
    global _router
    if _router is None:
        _router = AIRouter()
    return _router
