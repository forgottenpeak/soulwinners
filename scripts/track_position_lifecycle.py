#!/usr/bin/env python3
"""
Position Lifecycle Tracker - Hourly Cron Job

Updates open positions with current market cap, tracks peaks,
and auto-labels positions after 48 hours.

Cron schedule (every hour):
    0 * * * * cd /root/Soulwinners && ./venv/bin/python3 scripts/track_position_lifecycle.py >> logs/lifecycle_tracking.log 2>&1

Usage:
    python scripts/track_position_lifecycle.py [--force] [--stats]
"""
import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

import aiohttp

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from bot.lifecycle_tracker import get_lifecycle_tracker

# Comprehensive tracking (momentum, confluence, dev tracking)
try:
    from bot.comprehensive_tracker import get_comprehensive_tracker
    HAS_COMPREHENSIVE = True
except ImportError:
    HAS_COMPREHENSIVE = False
    get_comprehensive_tracker = None

# Lifecycle stage detection
try:
    from bot.lifecycle_stages import get_stage_detector, STAGES
    HAS_STAGE_DETECTOR = True
except ImportError:
    HAS_STAGE_DETECTOR = False
    get_stage_detector = None
    STAGES = {}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def is_cron_enabled() -> bool:
    """Check if lifecycle_tracking cron is enabled."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT enabled FROM cron_states WHERE cron_name = 'lifecycle_tracking'")
        row = cursor.fetchone()
        conn.close()
        return bool(row[0]) if row else True
    except:
        return True


async def fetch_token_mc(token_address: str, session: aiohttp.ClientSession) -> float:
    """Fetch current market cap from DexScreener."""
    try:
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    return float(data[0].get('marketCap', 0) or 0)
    except Exception as e:
        logger.debug(f"Could not fetch MC for {token_address[:12]}...: {e}")
    return 0


async def fetch_token_metrics(token_address: str, session: aiohttp.ClientSession) -> dict:
    """
    Fetch comprehensive token metrics from DexScreener.

    Returns dict with:
    - market_cap
    - volume_1h, volume_24h
    - holder_count (if available)
    - buys_1h, sells_1h
    """
    try:
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    pair = data[0]
                    volume = pair.get('volume', {})
                    txns = pair.get('txns', {})
                    txns_h1 = txns.get('h1', {})
                    info = pair.get('info', {})

                    return {
                        'market_cap': float(pair.get('marketCap', 0) or 0),
                        'volume_1h': float(volume.get('h1', 0) or 0),
                        'volume_24h': float(volume.get('h24', 0) or 0),
                        'holder_count': int(info.get('holders', 0) or 0),
                        'buys_1h': int(txns_h1.get('buys', 0) or 0),
                        'sells_1h': int(txns_h1.get('sells', 0) or 0),
                    }
    except Exception as e:
        logger.debug(f"Could not fetch metrics for {token_address[:12]}...: {e}")

    return {
        'market_cap': 0,
        'volume_1h': 0,
        'volume_24h': 0,
        'holder_count': 0,
        'buys_1h': 0,
        'sells_1h': 0,
    }


async def update_open_positions(tracker, max_positions: int = 1000, comprehensive: bool = True) -> Dict:
    """
    Update all open positions with comprehensive metrics.

    Tracks:
    - Market cap / peak tracking
    - Volume & momentum (5m, 1h, 24h)
    - Wallet confluence (insiders, elites)
    - Holder dynamics
    - Auto-labels after 48 hours based on TOKEN lifecycle

    Args:
        tracker: PositionLifecycleTracker instance
        max_positions: Max positions to update per run (cap at 1000)
        comprehensive: If True, fetch all metrics (default). False = MC only.

    Returns:
        Dict with update statistics
    """
    logger.info("=" * 60)
    logger.info("POSITION LIFECYCLE UPDATE" + (" (COMPREHENSIVE)" if comprehensive else ""))
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    stats = {
        'positions_checked': 0,
        'peaks_updated': 0,
        'dead_tokens': 0,
        'confluence_updated': 0,
        'stage_transitions': 0,
        'breakouts_detected': 0,
        'auto_labeled': 0,
        'errors': 0,
        'outcomes': {'runner': 0, 'rug': 0, 'sideways': 0}
    }

    # Get comprehensive tracker if available
    comp_tracker = None
    if comprehensive and HAS_COMPREHENSIVE:
        comp_tracker = get_comprehensive_tracker()
        logger.info("✅ Comprehensive tracking enabled")

    # Get stage detector if available
    stage_detector = None
    if HAS_STAGE_DETECTOR:
        stage_detector = get_stage_detector()
        logger.info("✅ Lifecycle stage detection enabled")

    # Get open positions (capped)
    open_positions = tracker.get_open_positions(limit=min(max_positions, 1000))
    logger.info(f"Found {len(open_positions)} open positions to monitor")

    if not open_positions:
        logger.info("No open positions to update")
        return stats

    # Create aiohttp session for batch requests
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(connector=connector) as session:

        # Process in batches of 50 for rate limiting
        batch_size = 50
        total_batches = (len(open_positions) + batch_size - 1) // batch_size

        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(open_positions))
            batch = open_positions[start_idx:end_idx]

            logger.info(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch)} positions)")

            for position in batch:
                try:
                    position_id = position['id']
                    token_address = position['token_address']
                    token_symbol = position['token_symbol'] or '???'
                    prev_holder_count = position.get('holder_count')

                    if comp_tracker:
                        # COMPREHENSIVE: Fetch all metrics
                        metrics = await comp_tracker.fetch_comprehensive_metrics(
                            token_address, session
                        )

                        if metrics['current_mc'] <= 0:
                            stats['dead_tokens'] += 1
                            logger.debug(f"No MC data for {token_symbol} (dead?)")
                            tracker.update_position_mc(position_id, 0)
                            continue

                        # Check wallet confluence
                        confluence = comp_tracker.check_wallet_confluence(token_address)

                        # Update with all metrics
                        comp_tracker.update_position_comprehensive(
                            position_id=position_id,
                            metrics=metrics,
                            confluence=confluence,
                            prev_holder_count=prev_holder_count,
                        )

                        stats['positions_checked'] += 1

                        # Check for new peak
                        if metrics['current_mc'] > (position.get('peak_mc') or 0):
                            stats['peaks_updated'] += 1
                            logger.info(f"📈 New peak: {token_symbol} -> ${metrics['current_mc']:,.0f}")

                        # Log confluence if significant
                        if confluence['insider_count'] >= 3 or confluence['elite_count'] >= 2:
                            stats['confluence_updated'] += 1
                            logger.info(
                                f"👥 Confluence: {token_symbol} has "
                                f"{confluence['insider_count']} insiders + "
                                f"{confluence['elite_count']} elites"
                            )

                        # LIFECYCLE STAGE DETECTION
                        if stage_detector:
                            # Update MC history for consolidation detection
                            stage_detector.update_mc_history(position_id, metrics['current_mc'])

                            # Build position dict with all current data
                            pos_with_metrics = dict(position)
                            pos_with_metrics.update(metrics)
                            pos_with_metrics['insider_wallet_count'] = confluence['insider_count']
                            pos_with_metrics['elite_wallet_count'] = confluence['elite_count']

                            # Detect current stage
                            current_stage = stage_detector.detect_stage(pos_with_metrics)

                            # Check for breakouts from consolidation
                            breakout = stage_detector.detect_breakout(
                                position, metrics['current_mc']
                            )

                            # Track stage transitions
                            old_stage = position.get('lifecycle_stage')
                            if current_stage != old_stage:
                                stats['stage_transitions'] += 1
                                stage_name = STAGES.get(current_stage, current_stage)
                                logger.info(f"📊 Stage: {token_symbol} -> {stage_name}")

                            transitions = stage_detector.track_stage_transitions(
                                pos_with_metrics, current_stage
                            )

                            # Update stage in DB
                            stage_detector.update_position_stage(
                                position_id, current_stage, breakout
                            )

                            # Alert on breakouts
                            if breakout and breakout != 'in_range':
                                stats['breakouts_detected'] += 1
                                logger.info(
                                    f"🚨 {breakout.upper()}: {token_symbol} "
                                    f"broke {'above' if breakout == 'breakout_up' else 'below'} range!"
                                )

                    else:
                        # ENHANCED BASIC: Fetch metrics and update with momentum
                        metrics = await fetch_token_metrics(token_address, session)
                        current_mc = metrics['market_cap']

                        if current_mc <= 0:
                            stats['dead_tokens'] += 1
                            tracker.update_position_mc(position_id, 0)
                            continue

                        # Use enhanced update with momentum calculation
                        result = tracker.update_position_with_metrics(
                            position_id=position_id,
                            current_mc=current_mc,
                            volume_1h=metrics['volume_1h'],
                            volume_24h=metrics['volume_24h'],
                            holder_count=metrics['holder_count'],
                            buys_1h=metrics['buys_1h'],
                            sells_1h=metrics['sells_1h'],
                        )
                        stats['positions_checked'] += 1

                        if result.get('new_peak'):
                            stats['peaks_updated'] += 1
                            logger.info(
                                f"📈 New peak: {token_symbol} -> ${current_mc:,.0f} "
                                f"(momentum: {result.get('momentum_score', 0):+.1f})"
                            )

                        # Log momentum changes
                        if result.get('momentum_trend') == 'up':
                            logger.debug(f"🚀 {token_symbol}: Momentum UP ({result.get('momentum_score'):+.1f})")
                        elif result.get('momentum_trend') == 'down':
                            logger.debug(f"📉 {token_symbol}: Momentum DOWN ({result.get('momentum_score'):+.1f})")

                        # Basic stage detection (even without comprehensive)
                        if stage_detector:
                            stage_detector.update_mc_history(position_id, current_mc)
                            pos_with_mc = dict(position)
                            pos_with_mc['current_mc'] = current_mc
                            current_stage = stage_detector.detect_stage(pos_with_mc)
                            old_stage = position.get('lifecycle_stage')
                            if current_stage != old_stage:
                                stats['stage_transitions'] += 1
                            stage_detector.track_stage_transitions(pos_with_mc, current_stage)
                            stage_detector.update_position_stage(position_id, current_stage)

                    # Rate limit between requests
                    await asyncio.sleep(0.3)

                except Exception as e:
                    logger.warning(f"Error updating position {position.get('id')}: {e}")
                    stats['errors'] += 1

            # Longer pause between batches
            if batch_idx < total_batches - 1:
                await asyncio.sleep(2)

    # Auto-label old positions (48h+) based on TOKEN lifecycle
    logger.info("\n🏷️  Checking for positions ready to label (48h+)...")
    old_positions = tracker.get_positions_needing_label()
    logger.info(f"Found {len(old_positions)} positions to auto-label")

    for position in old_positions:
        try:
            result = tracker.auto_label_old_position(position['id'])

            if 'outcome' in result:
                stats['auto_labeled'] += 1
                outcome = result['outcome']
                stats['outcomes'][outcome] = stats['outcomes'].get(outcome, 0) + 1

                wallet_note = ""
                if result.get('wallet_roi_percent') is not None:
                    wallet_note = f" | wallet sold at {result['wallet_roi_percent']:+.1f}%"

                logger.info(
                    f"🏷️  Labeled: {position.get('token_symbol', '???')} -> {outcome} "
                    f"(token peak: {result.get('token_peak_roi', 0):+.1f}%{wallet_note})"
                )

        except Exception as e:
            logger.warning(f"Error labeling position {position['id']}: {e}")
            stats['errors'] += 1

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("UPDATE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Positions checked: {stats['positions_checked']}")
    logger.info(f"Peaks updated: {stats['peaks_updated']}")
    logger.info(f"Stage transitions: {stats['stage_transitions']}")
    logger.info(f"Breakouts detected: {stats['breakouts_detected']}")
    logger.info(f"Confluence alerts: {stats['confluence_updated']}")
    logger.info(f"Dead tokens: {stats['dead_tokens']}")
    logger.info(f"Auto-labeled: {stats['auto_labeled']}")
    if stats['auto_labeled'] > 0:
        for outcome, count in stats['outcomes'].items():
            if count > 0:
                logger.info(f"  - {outcome}: {count}")
    logger.info(f"Errors: {stats['errors']}")

    return stats


def show_stats():
    """Display lifecycle tracking statistics."""
    tracker = get_lifecycle_tracker()
    stats = tracker.get_stats()

    print("\n" + "=" * 60)
    print("POSITION LIFECYCLE STATISTICS")
    print("=" * 60)
    print(f"Total positions tracked: {stats.get('total_positions', 0):,}")
    print(f"Open positions: {stats.get('open_positions', 0):,}")
    print(f"Positions (24h): {stats.get('positions_24h', 0):,}")

    print("\nBy Outcome:")
    for outcome, count in stats.get('by_outcome', {}).items():
        total = stats.get('total_positions', 0) - stats.get('open_positions', 0)
        pct = count / max(total, 1) * 100
        print(f"  {outcome}: {count:,} ({pct:.1f}%)")

    print("\nAverage ROI by Outcome:")
    for outcome, avg_roi in stats.get('avg_roi_by_outcome', {}).items():
        print(f"  {outcome}: {avg_roi:+.1f}%")


async def main():
    parser = argparse.ArgumentParser(
        description="Position Lifecycle Tracker - Updates open positions hourly"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if cron is disabled"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show statistics only"
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=500,
        help="Maximum positions to update per run"
    )

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    # Check if cron is enabled
    if not args.force and not is_cron_enabled():
        logger.info("Lifecycle tracking is DISABLED (cron_states)")
        return

    tracker = get_lifecycle_tracker()
    await update_open_positions(tracker, max_positions=args.max_positions)


if __name__ == "__main__":
    asyncio.run(main())
