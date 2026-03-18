"""
Hedgehog Gateway - Telegram Interface
Simple message handling and routing to brain
"""
import asyncio
import logging
from typing import Optional

from config import TELEGRAM_TOKEN

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramGateway:
    """
    Telegram bot gateway

    Handles:
    - Receiving messages from Telegram
    - Normalizing input format
    - Routing to brain
    - Sending responses back
    """

    def __init__(self, token: str = None):
        self.token = token or TELEGRAM_TOKEN
        self.application = None
        self.brain = None

    def _init_brain(self):
        """Lazy init brain to avoid circular imports"""
        if self.brain is None:
            from core.brain import get_brain
            self.brain = get_brain()

    async def start_command(self, update, context):
        """Handle /start command"""
        await update.message.reply_text(
            "Hey! I'm Hedgehog, your personal AI assistant.\n\n"
            "I can help you with:\n"
            "- Querying the SoulWinners database\n"
            "- Checking system services\n"
            "- Reading logs\n"
            "- And more!\n\n"
            "Just send me a message to get started."
        )

    async def help_command(self, update, context):
        """Handle /help command"""
        await update.message.reply_text(
            "Available commands:\n"
            "/start - Start the bot\n"
            "/help - Show this help\n"
            "/status - Check system status\n\n"
            "Or just send me a question!"
        )

    async def status_command(self, update, context):
        """Handle /status command"""
        self._init_brain()

        # Quick status check
        response = self.brain.process_sync(
            "Give me a quick status summary of the system.",
            user_id=str(update.effective_user.id)
        )
        await update.message.reply_text(response)

    async def handle_message(self, update, context):
        """Handle incoming text messages"""
        self._init_brain()

        user_id = str(update.effective_user.id)
        user_input = update.message.text

        logger.info(f"Message from {user_id}: {user_input[:50]}...")

        # Send typing indicator
        await update.message.chat.send_action("typing")

        try:
            # Process through brain
            response = self.brain.process_sync(user_input, user_id)

            # Split long messages (Telegram limit is 4096)
            if len(response) > 4000:
                # Split into chunks
                chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await update.message.reply_text(
                f"Sorry, I encountered an error: {str(e)}"
            )

    async def error_handler(self, update, context):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")

    def run(self):
        """Start the Telegram bot"""
        try:
            from telegram import Update
            from telegram.ext import (
                Application,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            print("Error: python-telegram-bot not installed.")
            print("Install with: pip install python-telegram-bot")
            return

        if not self.token:
            print("Error: TELEGRAM_BOT_TOKEN not set")
            print("Set it with: export TELEGRAM_BOT_TOKEN=your_token")
            return

        # Build application
        self.application = Application.builder().token(self.token).build()

        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        self.application.add_error_handler(self.error_handler)

        # Start polling
        logger.info("Starting Hedgehog Telegram bot...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


class CLIGateway:
    """
    Simple CLI gateway for testing without Telegram
    """

    def __init__(self):
        self.brain = None

    def _init_brain(self):
        """Lazy init brain"""
        if self.brain is None:
            from core.brain import get_brain
            self.brain = get_brain()

    def run(self):
        """Run interactive CLI"""
        self._init_brain()

        print("Hedgehog CLI Mode")
        print("Type 'quit' to exit")
        print("-" * 40)

        while True:
            try:
                user_input = input("\nYou: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "q"):
                    print("Goodbye!")
                    break

                response = self.brain.process_sync(user_input, user_id="cli_user")
                print(f"\nHedgehog: {response}")

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"\nError: {e}")
