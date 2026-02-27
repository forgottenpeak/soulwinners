#!/usr/bin/env python3
"""
Insider Detection Cron Script
Runs every 15 minutes to detect fresh launch insiders
"""
import sys
import asyncio
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.launch_tracker import InsiderScanner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)


async def main():
    """Run insider detection (one cycle)."""
    try:
        logger.info("=" * 60)
        logger.info("INSIDER DETECTION - Starting")
        logger.info("=" * 60)

        # Run one insider detection scan cycle
        # InsiderScanner handles: fresh launches, wallets, airdrops, patterns
        scanner = InsiderScanner()
        await scanner._scan_cycle()

        logger.info("=" * 60)
        logger.info("INSIDER DETECTION - Complete")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Insider detection failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
