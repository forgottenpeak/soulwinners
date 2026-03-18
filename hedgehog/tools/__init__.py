"""
Hedgehog Tool System v4.0 - Knowledge-First Architecture

Tools are the primary way Hedgehog interacts with the system.
Each tool is a discrete, auditable action with safety classification.

SMART TOOLS: Query knowledge base FIRST, live system SECOND.
95% of queries answered instantly from cache.
"""

from .base import Tool, ToolResult, ToolRegistry

# Smart tools (knowledge-base first) - these REPLACE the originals
from .smart_tools import (
    SmartSchemaDiscoveryTool,
    SmartWalletStatsTool,
    SmartPositionStatsTool,
    SmartSystemStatusTool,
    SmartQuestionTool,
    SmartPnLTool,
    get_smart_tools,
)

# Original database tools (for direct DB access when needed)
from .database_tools import (
    SchemaDiscoveryTool as _OriginalSchemaDiscoveryTool,
    DatabaseQueryTool,
    DatabaseWriteTool,
    WalletStatsTool as _OriginalWalletStatsTool,
    PositionStatsTool as _OriginalPositionStatsTool,
)

# Use SMART versions by default
SchemaDiscoveryTool = SmartSchemaDiscoveryTool
WalletStatsTool = SmartWalletStatsTool
PositionStatsTool = SmartPositionStatsTool

from .system_tools import (
    SystemStatusTool as _OriginalSystemStatusTool,
    ServiceRestartTool,
    LogAnalysisTool,
    ProcessListTool,
    HealthCheckTool,
    CodebaseSearchTool,
    GitHistoryTool,
    AutoHealTool,
)

# Use SMART version by default
SystemStatusTool = SmartSystemStatusTool

from .trading_tools import (
    GetPositionsTool,
    GetWalletPerformanceTool,
    GetTokenInfoTool,
    GetTradeHistoryTool,
    GetMarketOverviewTool,
)
from .telegram_tools import (
    TelegramSendTool,
    TelegramNotifyAdminTool,
    TelegramEditMessageTool,
    TelegramGetUpdatesTool,
)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    # SMART tools (knowledge-base first) - USE THESE
    "SmartSchemaDiscoveryTool",
    "SmartWalletStatsTool",
    "SmartPositionStatsTool",
    "SmartSystemStatusTool",
    "SmartQuestionTool",
    "SmartPnLTool",
    "get_smart_tools",
    # Database tools (aliased to smart versions)
    "SchemaDiscoveryTool",  # -> SmartSchemaDiscoveryTool
    "DatabaseQueryTool",  # Direct SQL (still needed)
    "DatabaseWriteTool",  # Direct SQL (still needed)
    "WalletStatsTool",  # -> SmartWalletStatsTool
    "PositionStatsTool",  # -> SmartPositionStatsTool
    # System tools
    "SystemStatusTool",  # -> SmartSystemStatusTool
    "ServiceRestartTool",
    "LogAnalysisTool",
    "ProcessListTool",
    "HealthCheckTool",
    "CodebaseSearchTool",
    "GitHistoryTool",
    "AutoHealTool",
    # Trading tools
    "GetPositionsTool",
    "GetWalletPerformanceTool",
    "GetTokenInfoTool",
    "GetTradeHistoryTool",
    "GetMarketOverviewTool",
    # Telegram tools
    "TelegramSendTool",
    "TelegramNotifyAdminTool",
    "TelegramEditMessageTool",
    "TelegramGetUpdatesTool",
]
