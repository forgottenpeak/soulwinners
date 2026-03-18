"""
Base Tool Classes

Foundation for all Hedgehog tools with safety classification and auditing.
"""
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)

# Default timeout for tool executions (seconds)
DEFAULT_TOOL_TIMEOUT = 10


def with_timeout(seconds: float = DEFAULT_TOOL_TIMEOUT):
    """
    Decorator to add timeout to async tool functions.

    If the function times out, returns a ToolResult with timeout error
    so the AI can still respond gracefully.

    Args:
        seconds: Timeout in seconds (default: 10)

    Usage:
        @with_timeout(15)
        async def my_slow_tool(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                logger.warning(f"Tool {func.__name__} timed out after {seconds}s")
                return ToolResult(
                    success=False,
                    error=f"Tool timed out after {seconds}s",
                    metadata={"timeout": True, "timeout_seconds": seconds}
                )
        return wrapper
    return decorator


class SafetyLevel(Enum):
    """Safety classification for tool actions."""
    SAFE = 0        # Read-only, no side effects
    MODERATE = 1    # Write operations with bounded impact
    RISKY = 2       # Operations that could affect system state
    DESTRUCTIVE = 3 # Operations that could cause data loss or system failure


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


@dataclass
class ToolCall:
    """Record of a tool invocation."""
    tool_name: str
    parameters: Dict[str, Any]
    safety_level: SafetyLevel
    result: Optional[ToolResult] = None
    timestamp: datetime = field(default_factory=datetime.now)
    approved_by: Optional[str] = None  # "auto", "admin", None


class Tool(ABC):
    """
    Base class for all Hedgehog tools.

    Each tool must declare:
    - name: Unique identifier
    - description: What the tool does
    - safety_level: Risk classification
    - parameters_schema: JSON schema for parameters
    - timeout: Execution timeout in seconds (default: 10)
    """

    name: str = "base_tool"
    description: str = "Base tool - do not use directly"
    safety_level: SafetyLevel = SafetyLevel.SAFE
    parameters_schema: Dict[str, Any] = {}
    timeout: float = DEFAULT_TOOL_TIMEOUT  # Timeout in seconds

    def __init__(self, config=None):
        """Initialize tool with optional config."""
        self.config = config
        self.logger = logging.getLogger(f"hedgehog.tools.{self.name}")

    @abstractmethod
    async def execute(self, **params) -> ToolResult:
        """
        Execute the tool with given parameters.

        Must be implemented by subclasses.
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> Optional[str]:
        """
        Validate parameters against schema.

        Returns error message if invalid, None if valid.
        """
        required = self.parameters_schema.get("required", [])
        properties = self.parameters_schema.get("properties", {})

        # Check required fields
        for field in required:
            if field not in params:
                return f"Missing required parameter: {field}"

        # Check types
        for key, value in params.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    return f"Parameter '{key}' must be string"
                if expected_type == "integer" and not isinstance(value, int):
                    return f"Parameter '{key}' must be integer"
                if expected_type == "number" and not isinstance(value, (int, float)):
                    return f"Parameter '{key}' must be number"
                if expected_type == "boolean" and not isinstance(value, bool):
                    return f"Parameter '{key}' must be boolean"
                if expected_type == "array" and not isinstance(value, list):
                    return f"Parameter '{key}' must be array"

        return None

    async def run(self, **params) -> ToolResult:
        """
        Run tool with validation, timing, and timeout.

        This is the main entry point for tool execution.
        Automatically applies timeout to prevent hanging.
        """
        import time

        # Validate parameters
        validation_error = self.validate_params(params)
        if validation_error:
            return ToolResult(
                success=False,
                error=validation_error,
            )

        # Execute with timing and timeout
        start_time = time.time()
        try:
            # Apply timeout to prevent hanging
            result = await asyncio.wait_for(
                self.execute(**params),
                timeout=self.timeout
            )
            result.execution_time_ms = (time.time() - start_time) * 1000
            return result
        except asyncio.TimeoutError:
            elapsed_ms = (time.time() - start_time) * 1000
            self.logger.warning(
                f"Tool {self.name} timed out after {self.timeout}s"
            )
            return ToolResult(
                success=False,
                error=f"Tool timed out after {self.timeout}s. The operation took too long.",
                execution_time_ms=elapsed_ms,
                metadata={"timeout": True, "timeout_seconds": self.timeout}
            )
        except Exception as e:
            self.logger.error(f"Tool execution error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    def get_schema(self) -> Dict[str, Any]:
        """Get tool schema for Claude API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters_schema,
        }

    def to_openai_schema(self) -> Dict[str, Any]:
        """Get tool schema for OpenAI API."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }


class ToolRegistry:
    """
    Registry for all available tools.

    Manages tool registration, lookup, and safety classification.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._by_safety: Dict[SafetyLevel, List[str]] = {
            level: [] for level in SafetyLevel
        }

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._by_safety[tool.safety_level].append(tool.name)
        logger.debug(f"Registered tool: {tool.name} (safety: {tool.safety_level.name})")

    def get(self, name: str) -> Optional[Tool]:
        """Get tool by name."""
        return self._tools.get(name)

    def get_all(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_by_safety(self, level: SafetyLevel) -> List[Tool]:
        """Get tools by safety level."""
        return [self._tools[name] for name in self._by_safety.get(level, [])]

    def get_safe_tools(self) -> List[Tool]:
        """Get only SAFE tools."""
        return self.get_by_safety(SafetyLevel.SAFE)

    def get_schemas(self, max_safety: SafetyLevel = SafetyLevel.RISKY) -> List[Dict[str, Any]]:
        """Get schemas for tools up to given safety level."""
        schemas = []
        for tool in self._tools.values():
            if tool.safety_level.value <= max_safety.value:
                schemas.append(tool.get_schema())
        return schemas

    def is_safe_for_auto_execute(self, tool_name: str) -> bool:
        """Check if tool can be auto-executed without approval."""
        tool = self.get(tool_name)
        if not tool:
            return False
        return tool.safety_level in [SafetyLevel.SAFE, SafetyLevel.MODERATE]


# Global registry
_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Get or create global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def register_tool(tool_class: Type[Tool], config=None) -> Tool:
    """Register a tool class and return instance."""
    tool = tool_class(config=config)
    get_registry().register(tool)
    return tool


async def run_tool_with_timeout(
    tool: Tool,
    timeout: Optional[float] = None,
    **params
) -> ToolResult:
    """
    Run a tool with explicit timeout override.

    This is useful when you need a different timeout than
    the tool's default for a specific call.

    Args:
        tool: The tool to execute
        timeout: Custom timeout in seconds (uses tool.timeout if None)
        **params: Parameters to pass to the tool

    Returns:
        ToolResult with success/failure and data or error message
    """
    import time

    effective_timeout = timeout if timeout is not None else tool.timeout

    # Validate parameters
    validation_error = tool.validate_params(params)
    if validation_error:
        return ToolResult(
            success=False,
            error=validation_error,
        )

    start_time = time.time()
    try:
        result = await asyncio.wait_for(
            tool.execute(**params),
            timeout=effective_timeout
        )
        result.execution_time_ms = (time.time() - start_time) * 1000
        return result
    except asyncio.TimeoutError:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.warning(f"Tool {tool.name} timed out after {effective_timeout}s")
        return ToolResult(
            success=False,
            error=f"Tool timed out after {effective_timeout}s. The operation took too long.",
            execution_time_ms=elapsed_ms,
            metadata={"timeout": True, "timeout_seconds": effective_timeout}
        )
    except Exception as e:
        logger.error(f"Tool execution error: {e}", exc_info=True)
        return ToolResult(
            success=False,
            error=str(e),
            execution_time_ms=(time.time() - start_time) * 1000,
        )
