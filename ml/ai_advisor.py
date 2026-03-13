"""
AI Advisor Module for V3 Edge Auto-Trader

Uses Anthropic Claude API to provide:
1. User onboarding (risk profile, algo setup)
2. Trade explanations ("Why I approved this")
3. Strategy optimization suggestions
4. Weekly performance reviews
5. Supervise XGBoost decisions (approve/reject)

Implements cost control with per-user monthly budgets.
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from config.settings import (
    ANTHROPIC_API_KEY,
    AI_BUDGET_FREE_USER,
    AI_BUDGET_PAID_USER,
    CLAUDE_INPUT_PRICE,
    CLAUDE_OUTPUT_PRICE,
    CLAUDE_CACHE_PRICE,
)

# Optional import - graceful fallback
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    anthropic = None

logger = logging.getLogger(__name__)


@dataclass
class UsageStats:
    """Track API usage for cost control."""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_cost_usd: float = 0.0
    request_count: int = 0


class CostTracker:
    """Track and enforce per-user AI budget limits."""

    def __init__(self):
        self.current_month = datetime.now().strftime("%Y-%m")

    def get_user_usage(self, user_id: int) -> UsageStats:
        """Get current month's usage for a user."""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT input_tokens, output_tokens, cached_tokens,
                   total_cost_usd, request_count
            FROM user_ai_usage
            WHERE user_id = ? AND month = ?
        """, (user_id, self.current_month))

        row = cursor.fetchone()
        conn.close()

        if row:
            return UsageStats(
                input_tokens=row[0] or 0,
                output_tokens=row[1] or 0,
                cached_tokens=row[2] or 0,
                total_cost_usd=row[3] or 0.0,
                request_count=row[4] or 0,
            )
        return UsageStats()

    def get_user_budget(self, user_id: int) -> float:
        """Get user's monthly budget based on subscription status."""
        conn = get_connection()
        cursor = conn.cursor()

        # Check if user is paid (has active subscription)
        cursor.execute("""
            SELECT status FROM authorized_users WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()

        is_paid = row and row[0] == 'active'
        return AI_BUDGET_PAID_USER if is_paid else AI_BUDGET_FREE_USER

    def check_budget(self, user_id: int) -> Tuple[bool, float, float]:
        """
        Check if user has remaining budget.

        Returns:
            (has_budget, remaining_usd, budget_usd)
        """
        usage = self.get_user_usage(user_id)
        budget = self.get_user_budget(user_id)
        remaining = budget - usage.total_cost_usd

        return remaining > 0, remaining, budget

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> float:
        """Calculate cost in USD for token usage."""
        input_cost = (input_tokens / 1_000_000) * CLAUDE_INPUT_PRICE
        output_cost = (output_tokens / 1_000_000) * CLAUDE_OUTPUT_PRICE
        cache_cost = (cached_tokens / 1_000_000) * CLAUDE_CACHE_PRICE

        return input_cost + output_cost + cache_cost

    def record_usage(
        self,
        user_id: int,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ):
        """Record API usage for a user."""
        cost = self.calculate_cost(input_tokens, output_tokens, cached_tokens)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO user_ai_usage
            (user_id, month, input_tokens, output_tokens, cached_tokens,
             total_cost_usd, request_count, last_request_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id, month) DO UPDATE SET
                input_tokens = input_tokens + excluded.input_tokens,
                output_tokens = output_tokens + excluded.output_tokens,
                cached_tokens = cached_tokens + excluded.cached_tokens,
                total_cost_usd = total_cost_usd + excluded.total_cost_usd,
                request_count = request_count + 1,
                last_request_at = excluded.last_request_at
        """, (
            user_id, self.current_month,
            input_tokens, output_tokens, cached_tokens,
            cost, datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

        logger.debug(f"Recorded usage for user {user_id}: ${cost:.4f}")


class AIAdvisor:
    """
    AI Advisor using Anthropic Claude.

    Provides intelligent guidance for trading decisions while
    respecting per-user budget limits.
    """

    # System prompt for trading context (cached for efficiency)
    SYSTEM_PROMPT = """You are an AI trading advisor for a Solana meme coin trading bot.
Your role is to provide concise, actionable insights on trading decisions.

Context:
- You supervise an XGBoost ML model that predicts runner/rug/sideways outcomes
- Users copy-trade from a pool of 656+ qualified smart money wallets
- Tokens are early-stage meme coins on Pump.fun and Raydium

Guidelines:
- Be direct and concise (max 500 tokens per response)
- Focus on risk/reward analysis
- Reference specific metrics when explaining decisions
- Never give financial advice - only analysis
- Acknowledge uncertainty in predictions"""

    def __init__(self):
        self.cost_tracker = CostTracker()
        self.client = None

        if HAS_ANTHROPIC and ANTHROPIC_API_KEY:
            self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def is_available(self) -> bool:
        """Check if AI advisor is available."""
        return self.client is not None

    async def _call_claude(
        self,
        user_id: int,
        messages: List[Dict],
        max_tokens: int = 500,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Make API call to Claude with budget checking.

        Args:
            user_id: User making the request
            messages: Conversation messages
            max_tokens: Maximum response tokens
            use_cache: Whether to use prompt caching

        Returns:
            Response text or None if budget exceeded
        """
        if not self.is_available():
            logger.warning("AI Advisor not available - no API key")
            return None

        # Check budget
        has_budget, remaining, budget = self.cost_tracker.check_budget(user_id)
        if not has_budget:
            logger.warning(f"User {user_id} exceeded AI budget (${budget:.2f}/month)")
            return None

        try:
            # Build system prompt with caching
            system = self.SYSTEM_PROMPT
            if use_cache:
                system = [
                    {
                        "type": "text",
                        "text": self.SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]

            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )

            # Extract usage
            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cached_tokens = getattr(usage, 'cache_read_input_tokens', 0)

            # Record usage
            self.cost_tracker.record_usage(
                user_id, input_tokens, output_tokens, cached_tokens
            )

            # Extract response text
            return response.content[0].text

        except anthropic.RateLimitError:
            logger.warning("Claude API rate limited")
            return None
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            return None
        except Exception as e:
            logger.error(f"AI Advisor error: {e}")
            return None

    async def explain_trade_decision(
        self,
        user_id: int,
        token_data: Dict,
        prediction: Dict,
        wallet_data: Dict,
    ) -> Optional[str]:
        """
        Generate explanation for why a trade was approved/rejected.

        Args:
            user_id: User requesting explanation
            token_data: Token metrics from DexScreener
            prediction: ML model prediction
            wallet_data: Wallet that made the trade

        Returns:
            Explanation text
        """
        # Build context
        context = f"""Trade Signal Analysis:

Token: ${token_data.get('symbol', '???')} ({token_data.get('name', 'Unknown')})
Market Cap: ${token_data.get('market_cap', 0):,.0f}
Liquidity: ${token_data.get('liquidity', 0):,.0f}
Token Age: {token_data.get('token_age_hours', 0):.1f} hours
Holders: {token_data.get('holders', 'N/A')}

ML Prediction:
- Runner Probability: {prediction.get('prob_runner', 0):.1%}
- Rug Probability: {prediction.get('prob_rug', 0):.1%}
- Expected ROI: {prediction.get('expected_roi', 0):+.0f}%
- Confidence: {prediction.get('confidence', 0):.1%}
- Decision: {prediction.get('decision', 'unknown').upper()}

Wallet Info:
- Tier: {wallet_data.get('tier', 'Unknown')}
- Win Rate: {wallet_data.get('win_rate', 0):.0%}
- Avg ROI: {wallet_data.get('roi_pct', 0):.0f}%"""

        messages = [
            {
                "role": "user",
                "content": f"{context}\n\nExplain this trade decision in 2-3 sentences. Focus on the key risk/reward factors."
            }
        ]

        explanation = await self._call_claude(user_id, messages, max_tokens=200)

        # Cache explanation
        if explanation:
            self._cache_explanation(
                prediction.get('ai_decision_id'),
                token_data.get('address', ''),
                explanation,
            )

        return explanation

    def _cache_explanation(
        self,
        decision_id: Optional[int],
        token_address: str,
        explanation: str,
    ):
        """Cache trade explanation for reuse."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO ai_trade_explanations
                (ai_decision_id, token_address, explanation)
                VALUES (?, ?, ?)
            """, (decision_id, token_address, explanation))
            conn.commit()
        except Exception as e:
            logger.debug(f"Could not cache explanation: {e}")
        finally:
            conn.close()

    async def onboard_user(
        self,
        user_id: int,
        answers: Dict,
    ) -> Dict:
        """
        Process user onboarding and recommend risk profile.

        Args:
            user_id: New user ID
            answers: Dict with onboarding answers

        Returns:
            Recommended configuration
        """
        context = f"""New User Onboarding:

Trading Experience: {answers.get('experience', 'beginner')}
Risk Appetite: {answers.get('risk_appetite', 'moderate')}
Investment Goal: {answers.get('goal', 'growth')}
Available Capital: {answers.get('capital', 'small')} SOL
Time Horizon: {answers.get('time_horizon', 'short')}
Loss Tolerance: {answers.get('loss_tolerance', 'moderate')}"""

        messages = [
            {
                "role": "user",
                "content": f"""{context}

Based on this profile, recommend:
1. Risk tolerance: conservative/balanced/aggressive
2. Target win rate (50-80%)
3. Max position size (0.1-2 SOL)
4. Daily trade limit (5-30)

Respond in JSON format:
{{"risk_tolerance": "...", "target_win_rate": 0.XX, "max_position_sol": X.X, "daily_limit": XX, "brief_reasoning": "..."}}"""
            }
        ]

        response = await self._call_claude(user_id, messages, max_tokens=300)

        if response:
            try:
                # Extract JSON from response
                import re
                json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
                if json_match:
                    config = json.loads(json_match.group())
                    return config
            except json.JSONDecodeError:
                pass

        # Default conservative config if AI fails
        return {
            "risk_tolerance": "balanced",
            "target_win_rate": 0.65,
            "max_position_sol": 0.5,
            "daily_limit": 10,
            "brief_reasoning": "Default balanced profile",
        }

    async def supervise_xgboost_decision(
        self,
        user_id: int,
        prediction: Dict,
        token_data: Dict,
        recent_performance: Dict,
    ) -> Tuple[bool, str]:
        """
        Have Claude supervise/validate XGBoost decision.

        Can override XGBoost if it detects issues.

        Args:
            user_id: User for budget tracking
            prediction: XGBoost prediction
            token_data: Token metrics
            recent_performance: Recent model performance

        Returns:
            (approve, reason) - whether to approve and why
        """
        # Skip supervision if model is very confident
        if prediction.get('confidence', 0) > 0.85:
            return True, "High confidence - auto-approved"

        context = f"""XGBoost Decision Review:

Token: ${token_data.get('symbol', '???')}
MC: ${token_data.get('market_cap', 0):,.0f}
Liq: ${token_data.get('liquidity', 0):,.0f}
Age: {token_data.get('token_age_hours', 0):.1f}h

Model Prediction:
- Runner: {prediction.get('prob_runner', 0):.1%}
- Rug: {prediction.get('prob_rug', 0):.1%}
- Decision: {prediction.get('decision', '?')}
- Confidence: {prediction.get('confidence', 0):.1%}

Recent Model Performance:
- Last 10 trades accuracy: {recent_performance.get('accuracy_10', 0):.0%}
- Last 10 trades ROI: {recent_performance.get('roi_10', 0):+.0f}%"""

        messages = [
            {
                "role": "user",
                "content": f"""{context}

Should this trade be approved? Consider:
1. Is the model's confidence justified?
2. Any red flags in the metrics?
3. Is the model performing well recently?

Respond with JSON: {{"approve": true/false, "reason": "brief reason"}}"""
            }
        ]

        response = await self._call_claude(user_id, messages, max_tokens=150)

        if response:
            try:
                import re
                json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return result.get('approve', True), result.get('reason', '')
            except json.JSONDecodeError:
                pass

        # Default to XGBoost decision if AI fails
        return prediction.get('decision') == 'approve', "AI review unavailable"

    async def generate_weekly_review(
        self,
        user_id: int,
        performance_data: Dict,
    ) -> str:
        """
        Generate weekly performance review and suggestions.

        Args:
            user_id: User ID
            performance_data: Week's trading statistics

        Returns:
            Review text
        """
        context = f"""Weekly Trading Performance:

Period: {performance_data.get('week_start', 'N/A')} to {performance_data.get('week_end', 'N/A')}

Statistics:
- Total Trades: {performance_data.get('total_trades', 0)}
- Wins: {performance_data.get('wins', 0)}
- Losses: {performance_data.get('losses', 0)}
- Win Rate: {performance_data.get('win_rate', 0):.0%}
- Total ROI: {performance_data.get('total_roi', 0):+.0f}%
- Best Trade: {performance_data.get('best_trade', 'N/A')} ({performance_data.get('best_roi', 0):+.0f}%)
- Worst Trade: {performance_data.get('worst_trade', 'N/A')} ({performance_data.get('worst_roi', 0):+.0f}%)

AI Approval Rate: {performance_data.get('ai_approval_rate', 0):.0%}
Model Accuracy: {performance_data.get('model_accuracy', 0):.0%}"""

        messages = [
            {
                "role": "user",
                "content": f"""{context}

Provide a brief weekly review with:
1. Performance summary (1-2 sentences)
2. What went well
3. What to improve
4. 1-2 specific suggestions for next week

Keep it under 200 words."""
            }
        ]

        review = await self._call_claude(user_id, messages, max_tokens=400)

        # Save review
        if review:
            self._save_weekly_review(user_id, performance_data, review)

        return review or "Weekly review unavailable."

    def _save_weekly_review(
        self,
        user_id: int,
        performance_data: Dict,
        review: str,
    ):
        """Save weekly review to database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO ai_weekly_reviews
                (user_id, week_start, review_text, performance_summary_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, week_start) DO UPDATE SET
                    review_text = excluded.review_text,
                    performance_summary_json = excluded.performance_summary_json
            """, (
                user_id,
                performance_data.get('week_start', datetime.now().strftime('%Y-%m-%d')),
                review,
                json.dumps(performance_data),
            ))
            conn.commit()
        except Exception as e:
            logger.debug(f"Could not save review: {e}")
        finally:
            conn.close()

    async def get_strategy_suggestion(
        self,
        user_id: int,
        current_config: Dict,
        recent_results: List[Dict],
    ) -> str:
        """
        Get AI suggestion for strategy optimization.

        Args:
            user_id: User ID
            current_config: Current user configuration
            recent_results: Last N trade results

        Returns:
            Strategy suggestion text
        """
        # Summarize recent results
        wins = sum(1 for r in recent_results if r.get('pnl', 0) > 0)
        losses = len(recent_results) - wins
        total_pnl = sum(r.get('pnl', 0) for r in recent_results)

        context = f"""Strategy Analysis Request:

Current Configuration:
- Risk Tolerance: {current_config.get('risk_tolerance', 'balanced')}
- Target Win Rate: {current_config.get('preferred_win_rate', 0.65):.0%}
- Max Position: {current_config.get('max_position_sol', 0.5)} SOL
- Daily Limit: {current_config.get('daily_trade_limit', 10)}

Last {len(recent_results)} Trades:
- Wins: {wins} | Losses: {losses}
- Net P/L: {total_pnl:+.2f} SOL
- Win Rate: {wins/max(len(recent_results), 1):.0%}"""

        messages = [
            {
                "role": "user",
                "content": f"""{context}

Based on recent performance, suggest 1-2 specific configuration adjustments.
Be concise and actionable."""
            }
        ]

        return await self._call_claude(user_id, messages, max_tokens=250) or "No suggestions available."

    def get_user_usage_summary(self, user_id: int) -> Dict:
        """Get user's AI usage summary for the month."""
        usage = self.cost_tracker.get_user_usage(user_id)
        budget = self.cost_tracker.get_user_budget(user_id)

        return {
            "month": self.cost_tracker.current_month,
            "total_cost_usd": usage.total_cost_usd,
            "budget_usd": budget,
            "remaining_usd": budget - usage.total_cost_usd,
            "usage_percent": (usage.total_cost_usd / budget * 100) if budget > 0 else 0,
            "request_count": usage.request_count,
            "total_tokens": usage.input_tokens + usage.output_tokens,
        }


# Singleton instance
_advisor: Optional[AIAdvisor] = None


def get_ai_advisor() -> AIAdvisor:
    """Get or create AI advisor instance."""
    global _advisor
    if _advisor is None:
        _advisor = AIAdvisor()
    return _advisor


if __name__ == "__main__":
    # Test AI advisor
    import asyncio
    logging.basicConfig(level=logging.INFO)

    advisor = AIAdvisor()

    print(f"AI Advisor available: {advisor.is_available()}")

    # Check usage for test user
    test_user = 1153491543
    summary = advisor.get_user_usage_summary(test_user)

    print(f"\nUsage summary for user {test_user}:")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: ${v:.4f}" if 'usd' in k else f"  {k}: {v:.1f}%")
        else:
            print(f"  {k}: {v}")

    # Test trade explanation (if API key is set)
    if advisor.is_available():
        print("\nTesting trade explanation...")

        async def test():
            explanation = await advisor.explain_trade_decision(
                user_id=test_user,
                token_data={
                    "symbol": "TEST",
                    "name": "Test Token",
                    "market_cap": 500000,
                    "liquidity": 50000,
                    "token_age_hours": 2,
                    "holders": 100,
                },
                prediction={
                    "prob_runner": 0.72,
                    "prob_rug": 0.15,
                    "expected_roi": 45,
                    "confidence": 0.68,
                    "decision": "approve",
                },
                wallet_data={
                    "tier": "Elite",
                    "win_rate": 0.72,
                    "roi_pct": 150,
                },
            )
            print(f"\nExplanation: {explanation}")

        asyncio.run(test())
