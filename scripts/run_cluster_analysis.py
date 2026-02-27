#!/usr/bin/env python3
"""
Cluster Analysis Cron Script
Runs every 20 minutes to find connected wallet groups
"""
import sys
import asyncio
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.cluster_detector import ClusterDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

logger = logging.getLogger(__name__)


async def main():
    """Run cluster analysis."""
    try:
        logger.info("=" * 60)
        logger.info("CLUSTER ANALYSIS - Starting")
        logger.info("=" * 60)

        # Analyze wallet connections
        logger.info("Analyzing wallet clusters...")
        detector = ClusterDetector()
        await detector.analyze_wallets()
        logger.info("✓ Cluster analysis complete")

        logger.info("=" * 60)
        logger.info("CLUSTER ANALYSIS - Complete")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Cluster analysis failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
