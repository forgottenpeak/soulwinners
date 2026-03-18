"""
Hedgehog Telegram Automation Skills
Channel management, bot management, and message automation
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from skills.base import get_registry

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_TOKENS = json.loads(os.getenv("TELEGRAM_BOT_TOKENS", "{}"))  # {"bot_name": "token"}
TELEGRAM_ALERT_CHAT_ID = os.getenv("TELEGRAM_ALERT_CHAT_ID", "")
TELEGRAM_API_URL = "https://api.telegram.org"

# Memory for scheduled messages
MEMORY_DIR = Path(__file__).parent.parent / "memory"
SCHEDULED_MESSAGES_PATH = MEMORY_DIR / "scheduled_messages.json"


def _telegram_request(method: str, token: str, data: Dict = None) -> Dict:
    """Make Telegram Bot API request"""
    url = f"{TELEGRAM_API_URL}/bot{token}/{method}"

    try:
        if data:
            req = Request(
                url,
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        else:
            req = Request(url, method="GET")

        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())

            if not result.get("ok"):
                raise Exception(result.get("description", "Telegram API error"))

            return result.get("result", {})

    except HTTPError as e:
        error_body = e.read().decode()
        raise Exception(f"Telegram API error {e.code}: {error_body}")


def _get_bot_token(bot_name: str = None) -> str:
    """Get bot token by name or default"""
    if bot_name and bot_name in TELEGRAM_BOT_TOKENS:
        return TELEGRAM_BOT_TOKENS[bot_name]
    if TELEGRAM_BOT_TOKEN:
        return TELEGRAM_BOT_TOKEN
    raise ValueError("No Telegram bot token configured")


# =============================================================================
# CHANNEL MANAGEMENT
# =============================================================================

def create_channel(name: str, description: str = "", private: bool = True) -> Dict:
    """
    Create a new Telegram channel

    Note: Bots cannot create channels directly via API.
    This returns instructions for manual creation.

    Args:
        name: Channel name
        description: Channel description
        private: Whether channel should be private

    Returns:
        Dict with creation instructions
    """
    return {
        "status": "manual_required",
        "instructions": [
            "1. Open Telegram and tap the pencil icon (new message)",
            "2. Select 'New Channel'",
            f"3. Name: {name}",
            f"4. Description: {description}",
            f"5. Type: {'Private' if private else 'Public'}",
            "6. Add the bot as administrator",
            "7. Share the channel ID with me using /set_channel command",
        ],
        "note": "Telegram API doesn't allow bots to create channels directly",
    }


def add_user_to_channel(channel_id: str, user_id: str) -> Dict:
    """
    Add a user to a channel

    Note: Bot must be admin with invite permissions

    Args:
        channel_id: Channel ID (e.g., -1001234567890)
        user_id: User ID to add

    Returns:
        Dict with result
    """
    try:
        token = _get_bot_token()

        # Create invite link
        result = _telegram_request("createChatInviteLink", token, {
            "chat_id": channel_id,
            "creates_join_request": False,
            "member_limit": 1,
        })

        return {
            "success": True,
            "invite_link": result.get("invite_link"),
            "note": f"Share this link with user {user_id}",
        }

    except Exception as e:
        return {"error": str(e)}


def post_to_channel(channel_id: str, message: str, parse_mode: str = "HTML") -> Dict:
    """
    Post a message to a channel

    Args:
        channel_id: Channel ID (e.g., -1001234567890 or @channelname)
        message: Message text
        parse_mode: "HTML" or "Markdown"

    Returns:
        Dict with message details
    """
    try:
        token = _get_bot_token()

        result = _telegram_request("sendMessage", token, {
            "chat_id": channel_id,
            "text": message,
            "parse_mode": parse_mode,
        })

        return {
            "success": True,
            "message_id": result.get("message_id"),
            "chat_id": channel_id,
            "date": result.get("date"),
        }

    except Exception as e:
        return {"error": str(e)}


def delete_channel(channel_id: str) -> Dict:
    """
    Delete/leave a channel

    REQUIRES APPROVAL - Destructive action

    Note: Bots can only leave channels, not delete them.

    Args:
        channel_id: Channel ID

    Returns:
        Dict with result
    """
    try:
        token = _get_bot_token()

        result = _telegram_request("leaveChat", token, {
            "chat_id": channel_id,
        })

        return {
            "success": True,
            "action": "left_channel",
            "channel_id": channel_id,
            "note": "Bot has left the channel. To delete, the owner must do it manually.",
        }

    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# BOT MANAGEMENT
# =============================================================================

def check_bot_health(bot_name: str = None) -> Dict:
    """
    Check if a bot is responding

    Args:
        bot_name: Bot name (from TELEGRAM_BOT_TOKENS) or None for default

    Returns:
        Dict with health status
    """
    try:
        token = _get_bot_token(bot_name)

        # Get bot info
        me = _telegram_request("getMe", token)

        # Get recent updates to check activity
        updates = _telegram_request("getUpdates", token, {
            "limit": 1,
            "timeout": 1,
        })

        last_update = None
        if updates:
            last_update = updates[-1].get("update_id")

        # Get webhook info
        webhook = _telegram_request("getWebhookInfo", token)

        return {
            "status": "healthy",
            "bot_name": me.get("username"),
            "bot_id": me.get("id"),
            "first_name": me.get("first_name"),
            "can_join_groups": me.get("can_join_groups"),
            "can_read_messages": me.get("can_read_all_group_messages"),
            "webhook_url": webhook.get("url") or "Not set (polling mode)",
            "webhook_pending": webhook.get("pending_update_count", 0),
            "last_error": webhook.get("last_error_message"),
            "last_update_id": last_update,
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "bot_name": bot_name,
            "error": str(e),
        }


def restart_bot(bot_name: str) -> Dict:
    """
    Restart a bot service

    REQUIRES APPROVAL - Service restart

    Args:
        bot_name: Name of the bot to restart

    Returns:
        Dict with restart status
    """
    try:
        # Try systemctl first
        service_name = f"hedgehog-bot-{bot_name}"
        result = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return {
                "success": True,
                "bot_name": bot_name,
                "action": "restarted",
                "service": service_name,
            }

        # Try finding process and restarting
        return {
            "success": False,
            "error": result.stderr or "Service not found",
            "note": f"Try manual restart: systemctl restart {service_name}",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_bot_stats(bot_name: str = None) -> Dict:
    """
    Get bot statistics

    Args:
        bot_name: Bot name or None for default

    Returns:
        Dict with usage stats
    """
    try:
        token = _get_bot_token(bot_name)

        # Get bot info
        me = _telegram_request("getMe", token)

        # Get webhook info for pending updates
        webhook = _telegram_request("getWebhookInfo", token)

        # Count recent messages (last 100 updates)
        updates = _telegram_request("getUpdates", token, {
            "limit": 100,
            "timeout": 1,
        })

        message_count = sum(1 for u in updates if "message" in u)
        unique_users = len(set(
            u.get("message", {}).get("from", {}).get("id")
            for u in updates if "message" in u
        ))

        return {
            "bot_name": me.get("username"),
            "bot_id": me.get("id"),
            "recent_messages": message_count,
            "unique_users_recent": unique_users,
            "pending_updates": webhook.get("pending_update_count", 0),
            "webhook_active": bool(webhook.get("url")),
            "stats_period": "last_100_updates",
        }

    except Exception as e:
        return {"error": str(e)}


def create_bot(name: str, token: str, description: str = "") -> Dict:
    """
    Register a new bot with Hedgehog

    This adds the bot token to the configuration for management.

    Args:
        name: Name to identify the bot
        token: Bot token from @BotFather
        description: What this bot does

    Returns:
        Dict with registration result
    """
    # Validate token by calling getMe
    try:
        me = _telegram_request("getMe", token)

        # Store in memory (in production, store securely)
        bots_file = MEMORY_DIR / "registered_bots.json"
        bots_file.parent.mkdir(exist_ok=True)

        if bots_file.exists():
            bots = json.loads(bots_file.read_text())
        else:
            bots = {}

        bots[name] = {
            "token_preview": f"{token[:10]}...{token[-5:]}",
            "username": me.get("username"),
            "bot_id": me.get("id"),
            "description": description,
            "registered_at": datetime.now().isoformat(),
        }

        bots_file.write_text(json.dumps(bots, indent=2))

        return {
            "success": True,
            "name": name,
            "username": me.get("username"),
            "bot_id": me.get("id"),
            "note": f"Add to env: TELEGRAM_BOT_TOKENS={{..., \"{name}\": \"{token}\"}}",
        }

    except Exception as e:
        return {"error": f"Invalid token: {str(e)}"}


# =============================================================================
# MESSAGE AUTOMATION
# =============================================================================

def send_alert(
    message: str,
    priority: str = "normal",
    chat_id: str = None
) -> Dict:
    """
    Send alert to configured alert channel

    Args:
        message: Alert message
        priority: "low", "normal", "high", "critical"
        chat_id: Override chat ID (uses TELEGRAM_ALERT_CHAT_ID by default)

    Returns:
        Dict with send result
    """
    target_chat = chat_id or TELEGRAM_ALERT_CHAT_ID

    if not target_chat:
        return {"error": "No alert chat configured. Set TELEGRAM_ALERT_CHAT_ID"}

    # Format message with priority
    priority_emoji = {
        "low": "ℹ️",
        "normal": "📢",
        "high": "⚠️",
        "critical": "🚨",
    }

    formatted_message = f"{priority_emoji.get(priority, '📢')} <b>{priority.upper()}</b>\n\n{message}"

    return post_to_channel(target_chat, formatted_message)


def broadcast(message: str, channels: List[str] = None) -> Dict:
    """
    Broadcast message to multiple channels

    Args:
        message: Message to broadcast
        channels: List of channel IDs (uses configured channels if empty)

    Returns:
        Dict with broadcast results
    """
    if not channels:
        # Load configured broadcast channels
        channels_file = MEMORY_DIR / "broadcast_channels.json"
        if channels_file.exists():
            channels = json.loads(channels_file.read_text())
        else:
            return {"error": "No channels specified and none configured"}

    results = []
    success_count = 0
    fail_count = 0

    for channel in channels:
        result = post_to_channel(channel, message)
        if "error" not in result:
            success_count += 1
            results.append({"channel": channel, "status": "sent"})
        else:
            fail_count += 1
            results.append({"channel": channel, "status": "failed", "error": result["error"]})

        # Rate limiting
        time.sleep(0.1)

    return {
        "total_channels": len(channels),
        "successful": success_count,
        "failed": fail_count,
        "results": results,
    }


def schedule_message(message: str, channel: str, send_at: str) -> Dict:
    """
    Schedule a message for later delivery

    Args:
        message: Message text
        channel: Channel ID to send to
        send_at: ISO timestamp for when to send

    Returns:
        Dict with schedule confirmation
    """
    try:
        send_time = datetime.fromisoformat(send_at)

        if send_time <= datetime.now():
            return {"error": "Scheduled time must be in the future"}

        # Load scheduled messages
        SCHEDULED_MESSAGES_PATH.parent.mkdir(exist_ok=True)

        if SCHEDULED_MESSAGES_PATH.exists():
            scheduled = json.loads(SCHEDULED_MESSAGES_PATH.read_text())
        else:
            scheduled = []

        # Add new scheduled message
        msg_id = len(scheduled) + 1
        scheduled.append({
            "id": msg_id,
            "message": message,
            "channel": channel,
            "send_at": send_at,
            "created_at": datetime.now().isoformat(),
            "status": "pending",
        })

        SCHEDULED_MESSAGES_PATH.write_text(json.dumps(scheduled, indent=2))

        return {
            "success": True,
            "message_id": msg_id,
            "channel": channel,
            "scheduled_for": send_at,
            "note": "Message will be sent when schedule checker runs",
        }

    except ValueError as e:
        return {"error": f"Invalid datetime format: {e}"}


def process_scheduled_messages() -> Dict:
    """
    Process and send any pending scheduled messages

    This should be called periodically (e.g., every minute)

    Returns:
        Dict with processing results
    """
    if not SCHEDULED_MESSAGES_PATH.exists():
        return {"processed": 0, "message": "No scheduled messages"}

    scheduled = json.loads(SCHEDULED_MESSAGES_PATH.read_text())
    now = datetime.now()

    sent = 0
    for msg in scheduled:
        if msg.get("status") != "pending":
            continue

        send_at = datetime.fromisoformat(msg["send_at"])
        if send_at <= now:
            # Time to send
            result = post_to_channel(msg["channel"], msg["message"])

            if "error" not in result:
                msg["status"] = "sent"
                msg["sent_at"] = datetime.now().isoformat()
                sent += 1
            else:
                msg["status"] = "failed"
                msg["error"] = result["error"]

    SCHEDULED_MESSAGES_PATH.write_text(json.dumps(scheduled, indent=2))

    return {"processed": sent, "total_pending": sum(1 for m in scheduled if m.get("status") == "pending")}


# =============================================================================
# REGISTER ALL SKILLS
# =============================================================================

registry = get_registry()

# Channel Management
@registry.register(
    name="create_channel",
    description="Get instructions for creating a Telegram channel",
    parameters=[
        {"name": "name", "type": "str", "description": "Channel name"},
        {"name": "description", "type": "str", "description": "Channel description", "optional": True},
        {"name": "private", "type": "bool", "description": "Private channel (default True)", "optional": True}
    ]
)
def _create_channel(name: str, description: str = "", private: bool = True) -> Dict:
    return create_channel(name, description, private)


@registry.register(
    name="add_user_to_channel",
    description="Create invite link to add user to channel",
    parameters=[
        {"name": "channel_id", "type": "str", "description": "Channel ID"},
        {"name": "user_id", "type": "str", "description": "User ID to invite"}
    ]
)
def _add_user_to_channel(channel_id: str, user_id: str) -> Dict:
    return add_user_to_channel(channel_id, user_id)


@registry.register(
    name="post_to_channel",
    description="Post a message to a Telegram channel",
    parameters=[
        {"name": "channel_id", "type": "str", "description": "Channel ID or @username"},
        {"name": "message", "type": "str", "description": "Message text"},
        {"name": "parse_mode", "type": "str", "description": "HTML or Markdown", "optional": True}
    ]
)
def _post_to_channel(channel_id: str, message: str, parse_mode: str = "HTML") -> Dict:
    return post_to_channel(channel_id, message, parse_mode)


@registry.register(
    name="delete_channel",
    description="Leave/delete a Telegram channel (REQUIRES APPROVAL)",
    parameters=[
        {"name": "channel_id", "type": "str", "description": "Channel ID to leave"}
    ]
)
def _delete_channel(channel_id: str) -> Dict:
    return delete_channel(channel_id)


# Bot Management
@registry.register(
    name="check_bot_health",
    description="Check if a Telegram bot is responding",
    parameters=[
        {"name": "bot_name", "type": "str", "description": "Bot name from config", "optional": True}
    ]
)
def _check_bot_health(bot_name: str = None) -> Dict:
    return check_bot_health(bot_name)


@registry.register(
    name="restart_bot",
    description="Restart a Telegram bot service (REQUIRES APPROVAL)",
    parameters=[
        {"name": "bot_name", "type": "str", "description": "Bot name to restart"}
    ]
)
def _restart_bot(bot_name: str) -> Dict:
    return restart_bot(bot_name)


@registry.register(
    name="get_bot_stats",
    description="Get Telegram bot usage statistics",
    parameters=[
        {"name": "bot_name", "type": "str", "description": "Bot name", "optional": True}
    ]
)
def _get_bot_stats(bot_name: str = None) -> Dict:
    return get_bot_stats(bot_name)


@registry.register(
    name="register_bot",
    description="Register a new Telegram bot with Hedgehog",
    parameters=[
        {"name": "name", "type": "str", "description": "Name to identify the bot"},
        {"name": "token", "type": "str", "description": "Bot token from @BotFather"},
        {"name": "description", "type": "str", "description": "What this bot does", "optional": True}
    ]
)
def _register_bot(name: str, token: str, description: str = "") -> Dict:
    return create_bot(name, token, description)


# Message Automation
@registry.register(
    name="send_alert",
    description="Send alert to configured alert channel",
    parameters=[
        {"name": "message", "type": "str", "description": "Alert message"},
        {"name": "priority", "type": "str", "description": "low/normal/high/critical", "optional": True},
        {"name": "chat_id", "type": "str", "description": "Override chat ID", "optional": True}
    ]
)
def _send_alert(message: str, priority: str = "normal", chat_id: str = None) -> Dict:
    return send_alert(message, priority, chat_id)


@registry.register(
    name="broadcast",
    description="Broadcast message to multiple Telegram channels",
    parameters=[
        {"name": "message", "type": "str", "description": "Message to broadcast"},
        {"name": "channels", "type": "str", "description": "Comma-separated channel IDs", "optional": True}
    ]
)
def _broadcast(message: str, channels: str = None) -> Dict:
    channel_list = channels.split(",") if channels else None
    return broadcast(message, channel_list)


@registry.register(
    name="schedule_message",
    description="Schedule a message for later delivery",
    parameters=[
        {"name": "message", "type": "str", "description": "Message text"},
        {"name": "channel", "type": "str", "description": "Channel ID"},
        {"name": "send_at", "type": "str", "description": "ISO timestamp (e.g., 2024-01-01T15:00:00)"}
    ]
)
def _schedule_message(message: str, channel: str, send_at: str) -> Dict:
    return schedule_message(message, channel, send_at)
