"""
Telegram Tools for Hedgehog

Tools for sending messages and notifications via Telegram.
"""
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp

from .base import Tool, ToolResult, SafetyLevel


class TelegramSendTool(Tool):
    """Send a message to a Telegram chat."""

    name = "telegram_send"
    description = """Send a message to a specified Telegram chat.
    Supports markdown formatting. Use for general notifications."""

    safety_level = SafetyLevel.MODERATE
    parameters_schema = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "description": "Telegram chat ID (user or channel)"
            },
            "message": {
                "type": "string",
                "description": "Message text (supports Markdown)"
            },
            "parse_mode": {
                "type": "string",
                "enum": ["Markdown", "HTML", "MarkdownV2"],
                "description": "Message formatting mode",
                "default": "Markdown"
            }
        },
        "required": ["chat_id", "message"]
    }

    async def execute(
        self,
        chat_id: str,
        message: str,
        parse_mode: str = "Markdown"
    ) -> ToolResult:
        """Send Telegram message."""
        try:
            from hedgehog.config import get_config
            config = get_config()

            url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"

            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()

                    if response.status == 200 and result.get("ok"):
                        msg = result.get("result", {})
                        return ToolResult(
                            success=True,
                            data={
                                "message_id": msg.get("message_id"),
                                "chat_id": chat_id,
                                "date": msg.get("date"),
                            }
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=result.get("description", "Unknown error")
                        )

        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class TelegramNotifyAdminTool(Tool):
    """Send a notification to the admin."""

    name = "telegram_notify_admin"
    description = """Send a notification to the admin chat.
    Use for important alerts, errors, and status updates."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Notification title/subject"
            },
            "message": {
                "type": "string",
                "description": "Notification body"
            },
            "level": {
                "type": "string",
                "enum": ["info", "warning", "error", "success"],
                "description": "Notification level",
                "default": "info"
            }
        },
        "required": ["title", "message"]
    }

    LEVEL_ICONS = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "🚨",
        "success": "✅",
    }

    async def execute(
        self,
        title: str,
        message: str,
        level: str = "info"
    ) -> ToolResult:
        """Send admin notification."""
        try:
            from hedgehog.config import get_config
            config = get_config()

            icon = self.LEVEL_ICONS.get(level, "📢")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            formatted_message = f"""
{icon} *{title}*

{message}

_Hedgehog | {timestamp}_
""".strip()

            url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"

            payload = {
                "chat_id": config.admin_chat_id,
                "text": formatted_message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()

                    if response.status == 200 and result.get("ok"):
                        return ToolResult(
                            success=True,
                            data={
                                "message_id": result.get("result", {}).get("message_id"),
                                "level": level,
                            }
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=result.get("description", "Unknown error")
                        )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class TelegramEditMessageTool(Tool):
    """Edit an existing Telegram message."""

    name = "telegram_edit_message"
    description = """Edit an existing Telegram message by ID.
    Use for updating status messages or alerts."""

    safety_level = SafetyLevel.MODERATE
    parameters_schema = {
        "type": "object",
        "properties": {
            "chat_id": {
                "type": "string",
                "description": "Chat ID where message exists"
            },
            "message_id": {
                "type": "integer",
                "description": "Message ID to edit"
            },
            "new_text": {
                "type": "string",
                "description": "New message text"
            }
        },
        "required": ["chat_id", "message_id", "new_text"]
    }

    async def execute(
        self,
        chat_id: str,
        message_id: int,
        new_text: str
    ) -> ToolResult:
        """Edit Telegram message."""
        try:
            from hedgehog.config import get_config
            config = get_config()

            url = f"https://api.telegram.org/bot{config.telegram_bot_token}/editMessageText"

            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": new_text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()

                    if response.status == 200 and result.get("ok"):
                        return ToolResult(
                            success=True,
                            data={"message_id": message_id, "updated": True}
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=result.get("description", "Unknown error")
                        )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class TelegramGetUpdatesTool(Tool):
    """Get recent messages/commands from Telegram."""

    name = "telegram_get_updates"
    description = """Get recent messages and commands from the bot.
    Use for checking if admin sent any commands."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of updates to fetch",
                "default": 10
            }
        },
        "required": []
    }

    async def execute(self, limit: int = 10) -> ToolResult:
        """Get Telegram updates."""
        try:
            from hedgehog.config import get_config
            config = get_config()

            url = f"https://api.telegram.org/bot{config.telegram_bot_token}/getUpdates"

            payload = {
                "limit": limit,
                "timeout": 0,  # Don't wait
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()

                    if response.status == 200 and result.get("ok"):
                        updates = result.get("result", [])

                        # Parse updates
                        parsed = []
                        for update in updates:
                            msg = update.get("message", {})
                            if msg:
                                parsed.append({
                                    "update_id": update.get("update_id"),
                                    "chat_id": msg.get("chat", {}).get("id"),
                                    "from_id": msg.get("from", {}).get("id"),
                                    "text": msg.get("text", ""),
                                    "date": msg.get("date"),
                                })

                        return ToolResult(
                            success=True,
                            data={
                                "updates": parsed,
                                "count": len(parsed),
                            }
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=result.get("description", "Unknown error")
                        )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
