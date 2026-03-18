"""
Hedgehog Tool System

Tools are the primary way Hedgehog interacts with the system.
Each tool is a discrete, auditable action with safety classification.
"""

from .base import Tool, ToolResult, ToolRegistry
from .database_tools import (
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
)
from .trading_tools import (
    GetPositionsTool,
    GetWalletPerformanceTool,
    GetTokenInfoTool,
    GetTradeHistoryTool,
)
from .telegram_tools import (
    TelegramSendTool,
    TelegramNotifyAdminTool,
    TelegramEditMessageTool,
)

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "DatabaseQueryTool",
    "DatabaseWriteTool",
    "WalletStatsTool",
    "PositionStatsTool",
    "SystemStatusTool",
    "ServiceRestartTool",
    "LogAnalysisTool",
    "ProcessListTool",
    "GetPositionsTool",
    "GetWalletPerformanceTool",
    "GetTokenInfoTool",
    "GetTradeHistoryTool",
    "TelegramSendTool",
    "TelegramNotifyAdminTool",
    "TelegramEditMessageTool",
]
