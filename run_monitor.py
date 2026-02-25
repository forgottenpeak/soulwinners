#!/usr/bin/env python3
"""
Run the Real-Time Monitor
- Only BUY alerts
- Only transactions < 5 minutes old
- Only buys >= 2 SOL
- Correct alert format
"""
import asyncio
import logging
import sys

sys.path.insert(0, '.')

from bot.realtime_bot import RealTimeBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/monitor.log'),
        logging.StreamHandler()
    ]
)

async def main():
    bot = RealTimeBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        bot.stop()
        print("\nMonitor stopped")

if __name__ == "__main__":
    asyncio.run(main())
