"""
Hedgehog LLM Router
Cost-optimized model selection: GPT-4o-mini (95%) / Claude Sonnet (5%)
"""
import json
import os
from typing import Any, Dict, Generator, List, Optional, Union

from config import LLM_CONFIG, OPENAI_API_KEY, ANTHROPIC_API_KEY


def is_gpt_only() -> bool:
    """Check if GPT-only mode is enabled"""
    return os.environ.get("HEDGEHOG_GPT_ONLY", "").lower() in ("1", "true", "yes")


class LLMRouter:
    """Routes requests to appropriate LLM based on complexity"""

    # Keywords that suggest complex reasoning needed
    COMPLEX_KEYWORDS = [
        "analyze", "explain why", "debug", "troubleshoot",
        "architecture", "design", "complex", "strategy",
        "optimize", "compare", "evaluate", "security",
    ]

    def __init__(self):
        self.openai_client = None
        self.anthropic_client = None
        self._init_clients()

    def _init_clients(self):
        """Initialize API clients lazily"""
        if OPENAI_API_KEY:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
            except ImportError:
                print("Warning: openai package not installed")

        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self.anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except ImportError:
                print("Warning: anthropic package not installed")

    def _needs_reasoning(self, prompt: str) -> bool:
        """Determine if prompt needs advanced reasoning model"""
        prompt_lower = prompt.lower()
        return any(kw in prompt_lower for kw in self.COMPLEX_KEYWORDS)

    def complete(
        self,
        messages: List[Dict],
        system_prompt: str = None,
        tools: List[Dict] = None,
        force_reasoning: bool = False,
    ) -> Any:
        """
        Get completion from appropriate LLM

        Args:
            messages: List of message dicts with role/content
            system_prompt: Optional system prompt
            tools: Optional list of tool schemas (OpenAI format)
            force_reasoning: Force use of reasoning model

        Returns:
            OpenAI ChatCompletion response object (when tools provided)
            or response text string (when no tools)
        """
        # GPT-only mode: always use default (GPT-4o-mini)
        if is_gpt_only():
            config = LLM_CONFIG["default"]
        else:
            # Check if any message needs reasoning
            needs_reasoning = force_reasoning
            if not needs_reasoning:
                for msg in messages:
                    content = msg.get("content", "")
                    if isinstance(content, str) and self._needs_reasoning(content):
                        needs_reasoning = True
                        break

            config = LLM_CONFIG["reasoning"] if needs_reasoning else LLM_CONFIG["default"]

        # Only OpenAI supports function calling in our setup
        if config["provider"] == "openai" or tools:
            return self._openai_complete(messages, system_prompt, config, tools)
        else:
            return self._anthropic_complete(messages, system_prompt, config)

    def _openai_complete(
        self,
        messages: List[Dict],
        system_prompt: str,
        config: Dict,
        tools: List[Dict] = None,
    ) -> Any:
        """
        Complete using OpenAI

        Returns full response object when tools are provided,
        otherwise returns just the content string.
        """
        if not self.openai_client:
            raise RuntimeError("OpenAI client not initialized. Set OPENAI_API_KEY.")

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        # Build API call kwargs
        kwargs = {
            "model": config["model"],
            "messages": full_messages,
            "max_tokens": config["max_tokens"],
            "temperature": config["temperature"],
        }

        # Add tools if provided
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.openai_client.chat.completions.create(**kwargs)

        # Return full response when using tools (caller needs tool_calls)
        if tools:
            return response

        # Return just content for simple completions
        return response.choices[0].message.content

    def _anthropic_complete(
        self, messages: List[Dict], system_prompt: str, config: Dict
    ) -> str:
        """Complete using Anthropic (no tool support)"""
        if not self.anthropic_client:
            raise RuntimeError("Anthropic client not initialized. Set ANTHROPIC_API_KEY.")

        response = self.anthropic_client.messages.create(
            model=config["model"],
            max_tokens=config["max_tokens"],
            system=system_prompt or "",
            messages=messages,
        )
        return response.content[0].text


# Singleton
_router = None

def get_router() -> LLMRouter:
    """Get or create router instance"""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
