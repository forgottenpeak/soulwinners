#!/usr/bin/env python3
"""
SoulWinners Bot Runner
- Real-time transaction monitor (channel alerts)
- Command bot (private DM commands)
- Both run concurrently
"""
import asyncio
import logging
import sys
import os

sys.path.insert(0, '.')

from bot.realtime_bot import RealTimeBot
from bot.commands import CommandBot

# Setup logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def main():
    """Run both bots concurrently."""
    logger.info("=" * 60)
    logger.info("SOULWINNERS BOT STARTING")
    logger.info("=" * 60)

    # Check if we should skip command bot (if another instance is running)
    import os
    skip_commands = os.environ.get('SKIP_COMMANDS', '').lower() == 'true'

    # Initialize bots
    monitor = RealTimeBot()
    commands = None

    if not skip_commands:
        commands = CommandBot()
        # Load admin ID if exists
        try:
            with open("data/admin_id.txt", "r") as f:
                commands.admin_id = int(f.read().strip())
                logger.info(f"Admin ID loaded: {commands.admin_id}")
        except:
            logger.info("No admin registered yet. Use /register in DM.")

    try:
        # Start command bot first (doesn't block) - skip if another instance running
        if commands:
            try:
                await commands.start()
                logger.info("Command bot started")
            except Exception as e:
                if "Conflict" in str(e):
                    logger.warning("Command bot conflict - another instance running. Continuing with alerts only.")
                    commands = None
                else:
                    raise

        # Start monitor (this runs the polling loop)
        logger.info("Starting real-time monitor...")
        await monitor.start()

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        monitor.stop()
        if commands:
            await commands.stop()
        logger.info("Bots stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")
