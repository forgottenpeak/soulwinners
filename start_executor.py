#!/usr/bin/env python3
"""Start the task executor"""
import sys
sys.path.insert(0, '/root/Soulwinners')

from bot.executor import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
