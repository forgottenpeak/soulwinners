"""
Telegram Handler for Hedgehog - Full Autonomous Interface

Handles all Telegram commands and natural language interactions.
Integrates with existing bot or runs standalone.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TelegramHedgehogBot:
    """
    Standalone Telegram bot for Hedgehog.

    Can run independently or integrate with existing bot.
    """

    def __init__(self):
        """Initialize bot."""
        self.brain = None
        self._bot = None
        self._app = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization."""
        if not self._initialized:
            from hedgehog.brain import get_brain
            self.brain = get_brain()
            self._initialized = True

    async def handle_message(self, update, context) -> None:
        """Handle incoming messages."""
        self._ensure_initialized()

        user_id = update.effective_user.id
        message = update.message.text
        is_admin = user_id == self.brain.config.admin_chat_id

        # Process message through brain
        response = await self.brain.process_message(
            message=message,
            user_id=user_id,
            is_admin=is_admin,
        )

        # Send response
        await update.message.reply_text(
            response,
            parse_mode="Markdown",
        )

    async def start_polling(self):
        """Start the bot with polling."""
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            MessageHandler,
            filters,
        )

        self._ensure_initialized()

        # Build application
        self._app = Application.builder().token(
            self.brain.config.telegram_bot_token
        ).build()

        # Add handlers
        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_message
        ))

        # Add all command handlers
        commands = [
            "status", "health", "fix", "update_key", "set_threshold",
            "restart", "logs", "trade_decision", "hedgehog", "hh",
            "positions", "wallets", "cost", "history", "undo",
            "pause", "resume", "approve", "reject", "pending", "help",
        ]

        for cmd in commands:
            self._app.add_handler(CommandHandler(cmd, self.handle_message))

        # Start polling
        logger.info("Hedgehog Telegram bot starting...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

        logger.info("Hedgehog Telegram bot running!")

    async def stop(self):
        """Stop the bot."""
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    def run(self):
        """Run the bot (blocking)."""
        asyncio.run(self._run_async())

    async def _run_async(self):
        """Run async."""
        await self.start_polling()

        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self.stop()


def register_with_existing_bot(application):
    """
    Register Hedgehog handlers with existing Telegram application.

    Usage:
        from telegram.ext import Application
        app = Application.builder().token(TOKEN).build()

        from hedgehog.integrations.telegram_handler import register_with_existing_bot
        register_with_existing_bot(app)

        app.run_polling()
    """
    from telegram import Update
    from telegram.ext import CommandHandler, MessageHandler, filters

    bot = TelegramHedgehogBot()

    async def handle_hedgehog(update: Update, context):
        """Route to Hedgehog brain."""
        await bot.handle_message(update, context)

    # Add handlers
    commands = [
        "status", "health", "fix", "update_key", "set_threshold",
        "restart", "logs", "trade_decision", "hedgehog", "hh",
        "positions", "wallets", "cost", "history", "undo",
        "pause", "resume", "approve", "reject", "pending",
    ]

    for cmd in commands:
        application.add_handler(CommandHandler(cmd, handle_hedgehog))

    # Natural language handler (lower priority)
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE,
        handle_hedgehog
    ), group=1)

    logger.info(f"Registered Hedgehog commands: {', '.join(commands)}")


class SimpleTelegramNotifier:
    """Simple notifier for sending messages without full bot."""

    def __init__(self, token: str, chat_id: int):
        self.token = token
        self.chat_id = chat_id

    async def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        """Send a message."""
        import aiohttp

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                }) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False


# Main entry point for standalone bot
def main():
    """Run Hedgehog Telegram bot standalone."""
    import sys
    sys.path.insert(0, str(__file__).replace("/hedgehog/integrations/telegram_handler.py", ""))

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    bot = TelegramHedgehogBot()
    bot.run()


if __name__ == "__main__":
    main()
