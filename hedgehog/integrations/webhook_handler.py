"""
Webhook Handler for Hedgehog

Integrates with the existing webhook_server.py to trigger
Hedgehog processing on trading events.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from hedgehog.brain import get_brain
from hedgehog.monitoring.events import Event, EventType, get_event_detector

logger = logging.getLogger(__name__)


class WebhookHandler:
    """
    Handler for webhook events.

    Connects to webhook_server.py to process trading events.
    """

    def __init__(self):
        """Initialize handler."""
        self.brain = None
        self.events = get_event_detector()
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of brain."""
        if not self._initialized:
            self.brain = get_brain()
            self._initialized = True

    async def handle_buy(self, data: Dict[str, Any]) -> Optional[Dict]:
        """
        Handle a BUY event from webhook.

        Args:
            data: Buy event data from webhook_server

        Returns:
            Processing result
        """
        self._ensure_initialized()

        event = Event(
            event_type=EventType.NEW_POSITION,
            source="webhook_buy",
            data={
                "position_id": data.get("position_id"),
                "wallet": data.get("wallet_address"),
                "token": data.get("token_address"),
                "symbol": data.get("token", data.get("symbol", "???")),
                "sol_amount": data.get("sol", data.get("sol_amount", 0)),
                "market_cap": data.get("mc", data.get("market_cap", 0)),
                "wallet_type": data.get("wallet_type"),
                "tier": data.get("tier"),
            },
            priority=3,  # Standard priority
        )

        # Queue event
        self.events.push_event(event)

        # For significant buys, process immediately
        sol_amount = data.get("sol", data.get("sol_amount", 0))
        if sol_amount >= 5:  # Large buy
            event.priority = 6
            decision = await self.brain.process_event(event)
            return {
                "processed": True,
                "decision": decision.decision if decision else None,
            }

        return {"queued": True, "event_id": event.id}

    async def handle_sell(self, data: Dict[str, Any]) -> Optional[Dict]:
        """
        Handle a SELL event from webhook.

        Args:
            data: Sell event data

        Returns:
            Processing result
        """
        self._ensure_initialized()

        event = Event(
            event_type=EventType.POSITION_EXIT,
            source="webhook_sell",
            data={
                "position_id": data.get("position_id"),
                "wallet": data.get("wallet_address"),
                "token": data.get("token_address"),
                "symbol": data.get("token", data.get("symbol", "???")),
                "sol_received": data.get("sol", data.get("sol_received", 0)),
                "roi": data.get("roi", data.get("roi_at_exit", 0)),
                "hold_hours": data.get("hold_hours"),
            },
            priority=2,  # Lower priority than buys
        )

        # Queue event
        self.events.push_event(event)

        # Check for significant ROI
        roi = data.get("roi", data.get("roi_at_exit", 0))
        if roi >= 100 or roi <= -50:  # Big win or big loss
            event.priority = 5
            decision = await self.brain.process_event(event)
            return {
                "processed": True,
                "decision": decision.decision if decision else None,
            }

        return {"queued": True, "event_id": event.id}

    async def handle_error(self, error_data: Dict[str, Any]) -> Optional[Dict]:
        """
        Handle an error event.

        Args:
            error_data: Error details

        Returns:
            Processing result
        """
        self._ensure_initialized()

        event = Event(
            event_type=EventType.SERVICE_ERROR,
            source=error_data.get("source", "unknown"),
            data={
                "error_type": error_data.get("type", "unknown"),
                "error_message": error_data.get("message", ""),
                "context": error_data.get("context", {}),
            },
            priority=7,  # High priority for errors
        )

        # Process immediately
        decision = await self.brain.process_event(event)

        # Try self-healing
        if error_data.get("auto_heal", True):
            actions = await self.brain.self_heal()
            return {
                "processed": True,
                "decision": decision.decision if decision else None,
                "heal_actions": actions,
            }

        return {
            "processed": True,
            "decision": decision.decision if decision else None,
        }

    async def handle_admin_message(self, message: str, chat_id: int) -> str:
        """
        Handle an admin command from Telegram.

        Args:
            message: Command text
            chat_id: Admin chat ID

        Returns:
            Response text
        """
        self._ensure_initialized()

        from hedgehog.config import get_config
        config = get_config()

        # Verify admin
        if chat_id != config.admin_chat_id:
            return "Unauthorized"

        # Parse command
        parts = message.strip().split()
        if not parts:
            return "Empty command"

        # Remove leading / if present
        cmd = parts[0].lstrip("/")
        args = parts[1:] if len(parts) > 1 else []

        # Handle command
        response = await self.brain.handle_admin_command(cmd, args)

        return response


# Flask integration for existing webhook_server.py
def add_hedgehog_routes(app):
    """
    Add Hedgehog routes to existing Flask app.

    Usage in webhook_server.py:
        from hedgehog.integrations.webhook_handler import add_hedgehog_routes
        add_hedgehog_routes(app)
    """
    from flask import request, jsonify

    handler = WebhookHandler()

    @app.route('/hedgehog/health', methods=['GET'])
    def hedgehog_health():
        """Hedgehog health check."""
        handler._ensure_initialized()
        status = handler.brain.get_brain_status()
        return jsonify(status)

    @app.route('/hedgehog/process', methods=['POST'])
    def hedgehog_process():
        """Trigger event processing."""
        async def _process():
            handler._ensure_initialized()
            decisions = await handler.brain.process_pending_events()
            return [{
                "event_type": d.event_type,
                "decision": d.decision[:100],
                "outcome": d.outcome,
            } for d in decisions]

        results = asyncio.run(_process())
        return jsonify({"processed": len(results), "decisions": results})

    @app.route('/hedgehog/event', methods=['POST'])
    def hedgehog_event():
        """Push a custom event."""
        data = request.get_json()

        async def _handle():
            event_type = data.get("type", "ai_decision_needed")
            event = Event(
                event_type=EventType(event_type) if event_type in [e.value for e in EventType] else EventType.AI_DECISION_NEEDED,
                source=data.get("source", "api"),
                data=data.get("data", {}),
                priority=data.get("priority", 5),
            )
            handler.events.push_event(event)
            decision = await handler.brain.process_event(event)
            return {
                "event_id": event.id,
                "decision": decision.decision if decision else None,
                "outcome": decision.outcome if decision else None,
            }

        result = asyncio.run(_handle())
        return jsonify(result)

    @app.route('/hedgehog/command', methods=['POST'])
    def hedgehog_command():
        """Handle admin command."""
        data = request.get_json()
        command = data.get("command", "")
        args = data.get("args", [])

        async def _handle():
            handler._ensure_initialized()
            return await handler.brain.handle_admin_command(command, args)

        response = asyncio.run(_handle())
        return jsonify({"response": response})

    logger.info("Hedgehog routes added to Flask app")


# Singleton handler
_handler: Optional[WebhookHandler] = None


def get_webhook_handler() -> WebhookHandler:
    """Get or create webhook handler."""
    global _handler
    if _handler is None:
        _handler = WebhookHandler()
    return _handler
