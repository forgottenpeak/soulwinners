"""
Hedgehog Brain - ReAct Loop with OpenAI Function Calling
Integrates learning system for pattern recognition
"""
import json
from typing import Any, Dict, Generator, List, Optional

from config import SYSTEM_PROMPT, MAX_ITERATIONS
from core.memory import get_memory
from core.router import get_router
from core.learning import get_learner
from skills.base import get_registry


class Brain:
    """
    ReAct-based agent brain using OpenAI function calling

    Pattern:
    1. Send message with tools
    2. If tool_calls in response, execute them
    3. Send tool results back
    4. Loop until text response (no tool calls)

    Learning integration:
    - Records trade outcomes
    - Checks wallet rankings before trades
    - Applies learned patterns
    """

    # Trading skills that should be tracked
    TRADE_SKILLS = {"execute_swap", "copy_insider_trade", "take_profit"}

    def __init__(self):
        self.memory = get_memory()
        self.router = get_router()
        self.registry = get_registry()
        self.learner = get_learner()

        # Load learned insights on startup
        self._load_insights()

    def _load_insights(self):
        """Load learned patterns and insights on startup"""
        try:
            insights = self.learner.get_insights()
            self.insights = insights.get("insights", [])
        except Exception:
            self.insights = []

    def _get_system_prompt(self) -> str:
        """Get system prompt with learned insights"""
        base_prompt = f"""{SYSTEM_PROMPT}

You have access to tools for trading, analysis, and system management.
Use tools when you need real data. Be concise and helpful.
Max {MAX_ITERATIONS} tool calls per query."""

        # Add learned insights if available
        if self.insights:
            insights_text = "\n".join(f"- {i}" for i in self.insights[:5])
            base_prompt += f"""

LEARNED INSIGHTS (from past trades):
{insights_text}"""

        # Add wallet tier info
        try:
            rankings = self.learner.get_wallet_rankings()
            if rankings.get("elite_count", 0) > 0:
                base_prompt += f"""

WALLET TIERS:
- Elite wallets (>80% win rate): {rankings.get('elite_count', 0)}
- Good wallets (>60% win rate): {rankings.get('good_count', 0)}
- Prefer Elite/Good wallets for copying trades"""
        except:
            pass

        return base_prompt

    def _get_tools(self) -> List[Dict]:
        """Get OpenAI tools schema from registry"""
        return self.registry.get_tools_schema()

    def _execute_tool(self, name: str, arguments: str) -> str:
        """
        Execute a tool and return result as string

        Also tracks trades for learning.

        Args:
            name: Tool/skill name
            arguments: JSON string of arguments

        Returns:
            Result as string for tool message
        """
        try:
            kwargs = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"Error: Invalid JSON arguments: {arguments}"

        # Pre-trade recommendation for trading skills
        if name in self.TRADE_SKILLS:
            recommendation = self._get_trade_recommendation(name, kwargs)
            if recommendation:
                # Include recommendation with result
                pass

        success, result = self.registry.execute(name, **kwargs)

        # Post-trade recording
        if success and name in self.TRADE_SKILLS:
            self._record_trade(name, kwargs, result)

        if success:
            # Format result for readability
            if isinstance(result, (dict, list)):
                return json.dumps(result, indent=2, default=str)
            return str(result)
        else:
            return f"Error: {result}"

    def _get_trade_recommendation(self, skill_name: str, kwargs: Dict) -> Optional[Dict]:
        """Get trading recommendation from learner"""
        try:
            wallet_source = kwargs.get("wallet_address")
            ml_confidence = kwargs.get("ml_confidence")

            if wallet_source or ml_confidence:
                return self.learner.should_trade(
                    wallet_source=wallet_source,
                    ml_confidence=ml_confidence,
                )
        except Exception:
            pass
        return None

    def _record_trade(self, skill_name: str, kwargs: Dict, result: Any):
        """Record trade in learning system"""
        try:
            if skill_name == "execute_swap":
                token_out = kwargs.get("token_out")
                amount = kwargs.get("amount_in", 0)

                if token_out and token_out.upper() != "SOL":
                    # This is a buy
                    self.learner.record_trade(
                        token_address=token_out,
                        entry_price=result.get("output_amount", 0) if isinstance(result, dict) else 0,
                        amount_sol=amount,
                        wallet_source=kwargs.get("wallet_source"),
                        ml_confidence=kwargs.get("ml_confidence"),
                        trade_type="buy",
                    )

            elif skill_name == "copy_insider_trade":
                self.learner.record_trade(
                    token_address=kwargs.get("token_address"),
                    entry_price=0,  # Will be updated from result
                    amount_sol=result.get("input_amount", 0) if isinstance(result, dict) else 0,
                    wallet_source=kwargs.get("wallet_address"),
                    trade_type="buy",
                )

            elif skill_name == "take_profit":
                # Record as sell/outcome
                token = kwargs.get("token_address")
                if isinstance(result, dict) and not result.get("error"):
                    # Get ROI from the result
                    self.learner.record_outcome(
                        token_address=token,
                        exit_price=result.get("output_amount", 0),
                        roi_percent=None,  # Calculate later
                    )
        except Exception as e:
            # Don't fail the trade if learning fails
            print(f"Learning record failed: {e}")

    def process(self, user_input: str, user_id: str = None) -> Generator[str, None, None]:
        """
        Process user input through ReAct loop with function calling

        Yields response chunks for streaming

        Args:
            user_input: The user's message
            user_id: Optional user identifier

        Yields:
            Response text chunks
        """
        # Store user message in memory
        self.memory.add_message("user", user_input, user_id)

        # Build conversation context
        context_messages = self.memory.get_context_messages()

        # Current conversation for this request
        messages = context_messages + [{"role": "user", "content": user_input}]

        system_prompt = self._get_system_prompt()
        tools = self._get_tools()
        iteration = 0
        final_answer = None

        while iteration < MAX_ITERATIONS:
            iteration += 1

            # Get LLM response with tools
            try:
                response = self.router.complete(
                    messages=messages,
                    system_prompt=system_prompt,
                    tools=tools,
                )
            except Exception as e:
                yield f"Error calling LLM: {str(e)}"
                return

            # Get the assistant message
            assistant_message = response.choices[0].message

            # Check if there are tool calls
            if assistant_message.tool_calls:
                # Add assistant message with tool calls to conversation
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ],
                })

                # Execute each tool and add results
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments

                    result = self._execute_tool(tool_name, tool_args)

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
            else:
                # No tool calls - we have the final answer
                final_answer = assistant_message.content
                break

        # If we hit max iterations without answer
        if final_answer is None:
            final_answer = "I wasn't able to complete the task within the allowed iterations. Please try a more specific question."

        # Store assistant response
        self.memory.add_message("assistant", final_answer, user_id)

        # Yield the final answer
        yield final_answer

    def process_sync(self, user_input: str, user_id: str = None) -> str:
        """Synchronous version of process - returns full response"""
        chunks = list(self.process(user_input, user_id))
        return "".join(chunks)

    def get_learning_status(self) -> Dict:
        """Get current learning system status"""
        return {
            "trade_stats": self.learner.get_trade_stats(24),
            "wallet_rankings": self.learner.get_wallet_rankings(),
            "ml_analysis": self.learner.analyze_ml_performance(),
            "patterns": self.learner.get_patterns(),
            "insights": self.insights,
        }


# Singleton
_brain = None

def get_brain() -> Brain:
    """Get or create brain instance"""
    global _brain
    if _brain is None:
        _brain = Brain()
    return _brain
