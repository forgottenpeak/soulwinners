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
from database import get_connection

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

        # Get qualified wallets to analyze
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wallet_address FROM qualified_wallets
            ORDER BY priority_score DESC
            LIMIT 50
        """)
        wallets = [row[0] for row in cursor.fetchall()]
        conn.close()

        logger.info(f"Analyzing {len(wallets)} qualified wallets for connections...")

        # Analyze wallet connections
        detector = ClusterDetector()
        for wallet in wallets:
            try:
                connections = await detector.analyze_wallet_connections(wallet)

                for conn in connections:
                    # Store connection
                    key = (min(conn.wallet_a, conn.wallet_b), max(conn.wallet_a, conn.wallet_b))
                    detector.connections[key] = conn
                    await detector.save_connection_to_db(conn)

                await asyncio.sleep(0.5)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to analyze {wallet[:15]}...: {e}")

        logger.info(f"✓ Analyzed connections for {len(wallets)} wallets")

        # Build clusters from connections
        logger.info("Building clusters...")
        clusters = detector.build_clusters()
        logger.info(f"✓ Found {len(clusters)} clusters")

        # Save clusters
        for cluster in clusters:
            await detector.save_cluster_to_db(cluster)
            logger.info(f"  - {cluster.label}: {len(cluster.wallets)} wallets (risk: {cluster.risk_score:.2f})")

        logger.info("=" * 60)
        logger.info("CLUSTER ANALYSIS - Complete")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Cluster analysis failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
