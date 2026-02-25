"""
Insider Detector Pipeline
Combines Launch Tracking + Cluster Analysis to find hidden alpha wallets

Detection Patterns:
1. Migration Sniper - Buys within 2 min of Raydium migration
2. Accumulation Insider - Multiple small buys before pump
3. Silent Whale - Large quiet buys, no social presence
4. Dev Associate - Connected to token dev wallets
5. Copy Trader - Always follows same elite wallets
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass

from database import get_connection
from collectors.launch_tracker import LaunchTracker, InsiderScanner
from pipeline.cluster_detector import ClusterDetector, ClusterScanner

logger = logging.getLogger(__name__)


@dataclass
class InsiderProfile:
    """Complete profile of a detected insider."""
    wallet_address: str
    pattern: str
    confidence: float  # 0-1
    signals: List[str]
    stats: Dict
    cluster_info: Optional[Dict] = None
    discovered_at: datetime = None


class InsiderDetector:
    """
    Main insider detection system.

    Combines multiple signals:
    1. Fresh launch buying patterns
    2. Wallet clustering / connections
    3. Trading behavior analysis
    4. Success rate tracking
    """

    def __init__(self):
        self.launch_tracker = LaunchTracker()
        self.cluster_detector = ClusterDetector()

    async def analyze_wallet(self, wallet: str) -> Optional[InsiderProfile]:
        """
        Full insider analysis for a wallet.
        Returns InsiderProfile if insider patterns detected.
        """
        signals = []
        confidence = 0.0
        stats = {}

        # 1. Check launch buying patterns
        launch_patterns = await self.launch_tracker.analyze_buyer_patterns(wallet)
        if launch_patterns.get('detected_pattern'):
            signals.append(f"Pattern: {launch_patterns['detected_pattern']}")
            confidence += 0.4
            stats['launch_patterns'] = launch_patterns

        # 2. Check wallet connections / clusters
        cluster_info = await self.cluster_detector.get_wallet_cluster_info(wallet)
        if cluster_info:
            signals.append(f"Cluster: {cluster_info['label']} ({cluster_info['wallet_count']} wallets)")
            confidence += 0.2
            stats['cluster'] = cluster_info

        # 3. Check trading success rate
        success_stats = await self._get_trading_stats(wallet)
        if success_stats['win_rate'] > 0.7:
            signals.append(f"High win rate: {success_stats['win_rate']*100:.0f}%")
            confidence += 0.2

        if success_stats['avg_roi'] > 100:
            signals.append(f"High ROI: {success_stats['avg_roi']:.0f}%")
            confidence += 0.2

        stats['trading'] = success_stats

        # 4. Check for specific insider behaviors
        behaviors = await self._detect_behaviors(wallet)
        for behavior in behaviors:
            signals.append(behavior)
            confidence += 0.1

        # Return profile if any signals detected
        if signals:
            # Determine primary pattern
            pattern = launch_patterns.get('detected_pattern') or 'Unknown'
            if cluster_info and cluster_info['label'] == 'Dev Cluster':
                pattern = 'Dev Associate'

            return InsiderProfile(
                wallet_address=wallet,
                pattern=pattern,
                confidence=min(confidence, 1.0),
                signals=signals,
                stats=stats,
                cluster_info=cluster_info,
                discovered_at=datetime.now(),
            )

        return None

    async def _get_trading_stats(self, wallet: str) -> Dict:
        """Get trading statistics for wallet."""
        conn = get_connection()
        cursor = conn.cursor()

        stats = {
            'win_rate': 0,
            'avg_roi': 0,
            'total_trades': 0,
            'profitable_trades': 0,
        }

        try:
            # Check if in qualified_wallets
            cursor.execute("""
                SELECT profit_token_ratio, roi_pct, total_trades
                FROM qualified_wallets
                WHERE wallet_address = ?
            """, (wallet,))

            row = cursor.fetchone()
            if row:
                stats['win_rate'] = row[0] or 0
                stats['avg_roi'] = row[1] or 0
                stats['total_trades'] = row[2] or 0

        except:
            pass
        finally:
            conn.close()

        return stats

    async def _detect_behaviors(self, wallet: str) -> List[str]:
        """Detect specific insider behaviors."""
        behaviors = []

        # Check if wallet is active at unusual hours (bot behavior)
        # Check if wallet follows specific elite wallets (copy trader)
        # Check if wallet only buys tokens that moon (insider info)

        # These would require more transaction history analysis
        # Placeholder for now

        return behaviors

    async def scan_and_detect(self, wallets: List[str]) -> List[InsiderProfile]:
        """Scan multiple wallets and return detected insiders."""
        insiders = []

        for wallet in wallets:
            try:
                profile = await self.analyze_wallet(wallet)
                if profile and profile.confidence >= 0.3:
                    insiders.append(profile)
                    logger.info(f"Insider detected: {wallet[:15]}... - {profile.pattern} ({profile.confidence:.0%})")

                await asyncio.sleep(0.3)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to analyze {wallet[:15]}...: {e}")

        return insiders

    async def save_insider(self, profile: InsiderProfile):
        """Save insider profile to database."""
        conn = get_connection()
        cursor = conn.cursor()

        # Ensure table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insider_pool (
                wallet_address TEXT PRIMARY KEY,
                pattern TEXT,
                confidence REAL,
                signals TEXT,
                win_rate REAL,
                avg_roi REAL,
                cluster_id TEXT,
                cluster_label TEXT,
                discovered_at TIMESTAMP,
                last_updated TIMESTAMP,
                promoted_to_main INTEGER DEFAULT 0
            )
        """)

        # Get stats
        win_rate = profile.stats.get('trading', {}).get('win_rate', 0)
        avg_roi = profile.stats.get('trading', {}).get('avg_roi', 0)
        cluster_id = profile.cluster_info.get('cluster_id') if profile.cluster_info else None
        cluster_label = profile.cluster_info.get('label') if profile.cluster_info else None

        cursor.execute("""
            INSERT OR REPLACE INTO insider_pool (
                wallet_address, pattern, confidence, signals, win_rate, avg_roi,
                cluster_id, cluster_label, discovered_at, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile.wallet_address,
            profile.pattern,
            profile.confidence,
            ', '.join(profile.signals),
            win_rate,
            avg_roi,
            cluster_id,
            cluster_label,
            profile.discovered_at.isoformat() if profile.discovered_at else datetime.now().isoformat(),
            datetime.now().isoformat(),
        ))

        conn.commit()
        conn.close()


class InsiderPipeline:
    """
    Full insider detection pipeline.
    Runs continuously to find and track insiders.
    """

    def __init__(self):
        self.detector = InsiderDetector()
        self.launch_scanner = InsiderScanner()
        self.cluster_scanner = ClusterScanner()
        self.running = False

    async def start(self):
        """Start all scanners in parallel."""
        self.running = True
        logger.info("Starting Insider Detection Pipeline")

        # Run all scanners
        await asyncio.gather(
            self._run_detection_loop(),
            self.launch_scanner.start(),
            self.cluster_scanner.start(),
        )

    async def _run_detection_loop(self):
        """Main detection loop."""
        while self.running:
            try:
                # Get candidates from insider_pool that haven't been fully analyzed
                conn = get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT wallet_address FROM insider_pool
                    WHERE confidence < 0.5 OR last_updated < datetime('now', '-1 hour')
                    LIMIT 20
                """)

                wallets = [row[0] for row in cursor.fetchall()]
                conn.close()

                if wallets:
                    insiders = await self.detector.scan_and_detect(wallets)
                    for insider in insiders:
                        await self.detector.save_insider(insider)

                # Also check first buyers of fresh tokens
                tokens = await self.detector.launch_tracker.scan_fresh_launches()
                for token in tokens[:5]:
                    buyers = await self.detector.launch_tracker.get_first_buyers(token.address, limit=10)
                    insiders = await self.detector.scan_and_detect(buyers)
                    for insider in insiders:
                        await self.detector.save_insider(insider)

            except Exception as e:
                logger.error(f"Detection loop error: {e}")

            await asyncio.sleep(300)  # 5 minutes

    async def promote_insiders(self):
        """Promote successful insiders to main qualified_wallets pool."""
        conn = get_connection()
        cursor = conn.cursor()

        # Find high-confidence insiders with good stats
        cursor.execute("""
            SELECT wallet_address, pattern, win_rate, avg_roi
            FROM insider_pool
            WHERE confidence >= 0.7
            AND win_rate >= 0.6
            AND promoted_to_main = 0
        """)

        for row in cursor.fetchall():
            wallet, pattern, win_rate, avg_roi = row

            # Add to qualified_wallets
            cursor.execute("""
                INSERT OR IGNORE INTO qualified_wallets (
                    wallet_address, source, tier, cluster_name,
                    profit_token_ratio, roi_pct, qualified_at
                ) VALUES (?, 'insider', 'Elite', ?, ?, ?, ?)
            """, (
                wallet,
                f"Insider: {pattern}",
                win_rate,
                avg_roi,
                datetime.now().isoformat(),
            ))

            # Mark as promoted
            cursor.execute("""
                UPDATE insider_pool SET promoted_to_main = 1
                WHERE wallet_address = ?
            """, (wallet,))

            logger.info(f"Promoted insider: {wallet[:15]}... ({pattern})")

        conn.commit()
        conn.close()

    def stop(self):
        """Stop all scanners."""
        self.running = False
        self.launch_scanner.stop()
        self.cluster_scanner.stop()


async def run_insider_pipeline():
    """Run the insider detection pipeline."""
    pipeline = InsiderPipeline()

    try:
        await pipeline.start()
    except KeyboardInterrupt:
        logger.info("Stopping pipeline...")
        pipeline.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(run_insider_pipeline())
