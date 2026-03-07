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
from database import get_connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)


def is_cron_enabled(cron_name: str) -> bool:
    """Check if cron job is enabled in database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT enabled FROM cron_states WHERE cron_name = ?", (cron_name,))
        row = cursor.fetchone()
        conn.close()
        return bool(row[0]) if row else True
    except:
        return True


async def main():
    """Run insider detection (one cycle)."""
    try:
        # Check if enabled
        if not is_cron_enabled('insider_detection'):
            logger.info("INSIDER DETECTION - SKIPPED (disabled in cron_states)")
            return

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
