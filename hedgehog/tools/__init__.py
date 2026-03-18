"""
Hedgehog Tool System

Tools are the primary way Hedgehog interacts with the system.
Each tool is a discrete, auditable action with safety classification.
"""

from .base import Tool, ToolResult, ToolRegistry
from .database_tools import (
    SchemaDiscoveryTool,
    DatabaseQueryTool,
    DatabaseWriteTool,
    WalletStatsTool,
    PositionStatsTool,
)
from .system_tools import (
    SystemStatusTool,
    ServiceRestartTool,
    LogAnalysisTool,
    ProcessListTool,
    HealthCheckTool,
    CodebaseSearchTool,
    GitHistoryTool,
    AutoHealTool,
)
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
    # Database tools
    "SchemaDiscoveryTool",
    "DatabaseQueryTool",
    "DatabaseWriteTool",
    "WalletStatsTool",
    "PositionStatsTool",
    # System tools
    "SystemStatusTool",
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
