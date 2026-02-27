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

from collectors.launch_tracker import LaunchTracker
from pipeline.insider_detector import InsiderDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)


async def main():
    """Run insider detection."""
    try:
        logger.info("=" * 60)
        logger.info("INSIDER DETECTION - Starting")
        logger.info("=" * 60)

        # Step 1: Scan for fresh launches
        logger.info("Step 1: Scanning for fresh launches...")
        tracker = LaunchTracker()
        tokens = await tracker.scan_fresh_launches()
        logger.info(f"✓ Fresh launch scan complete - Found {len(tokens)} tokens")
        logger.info(f"  - Fresh creations (0-24h): {len(tokens)}")
        logger.info(f"  - Fresh migrations (0-6h): {len(tracker.fresh_migrations)}")

        # Step 2: Detect insider wallets
        logger.info("Step 2: Detecting insider wallets...")
        detector = InsiderDetector()
        await detector.detect()
        logger.info("✓ Insider detection complete")

        logger.info("=" * 60)
        logger.info("INSIDER DETECTION - Complete")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Insider detection failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
