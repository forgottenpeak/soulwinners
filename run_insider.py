#!/usr/bin/env python3
"""
Run Insider Detection Pipeline
Finds early buyers, insiders, and connected wallet clusters
"""
import asyncio
import argparse
import logging
import sys

from database import init_database
from pipeline.insider_detector import InsiderPipeline, InsiderDetector
from pipeline.cluster_detector import ClusterDetector
from collectors.launch_tracker import LaunchTracker


async def run_pipeline():
    """Run the full insider detection pipeline."""
    pipeline = InsiderPipeline()

    try:
        await pipeline.start()
    except KeyboardInterrupt:
        print("\nStopping pipeline...")
        pipeline.stop()


async def scan_fresh_launches():
    """Scan for fresh token launches."""
    tracker = LaunchTracker()

    print("Scanning for fresh launches (< 24h old)...")
    tokens = await tracker.scan_fresh_launches()

    print(f"\nFound {len(tokens)} fresh tokens:\n")
    for token in tokens[:20]:
        age_hours = (datetime.now() - token.launch_time).total_seconds() / 3600
        print(f"  {token.symbol:12} | {age_hours:.1f}h old | {token.address[:30]}...")

        # Get first buyers
        buyers = await tracker.get_first_buyers(token.address, limit=3)
        if buyers:
            print(f"    First buyers: {len(buyers)}")
            for buyer in buyers[:2]:
                print(f"      {buyer[:40]}...")


async def analyze_wallet(wallet: str):
    """Analyze a single wallet for insider patterns."""
    detector = InsiderDetector()

    print(f"\nAnalyzing wallet: {wallet}\n")

    profile = await detector.analyze_wallet(wallet)

    if profile:
        print(f"Pattern: {profile.pattern}")
        print(f"Confidence: {profile.confidence:.0%}")
        print(f"\nSignals:")
        for signal in profile.signals:
            print(f"  • {signal}")
        print(f"\nStats:")
        for key, value in profile.stats.items():
            print(f"  {key}: {value}")
    else:
        print("No insider patterns detected.")


async def find_connections(wallet: str):
    """Find all wallets connected to a given wallet."""
    detector = ClusterDetector()

    print(f"\nFinding connections for: {wallet[:30]}...\n")

    connections = await detector.analyze_wallet_connections(wallet)

    if connections:
        print(f"Found {len(connections)} connections:\n")
        for conn in connections[:10]:
            print(f"  {conn.connection_type:15} | Strength: {conn.strength:.2f}")
            print(f"    → {conn.wallet_b[:40]}...")
            for evidence in conn.evidence:
                print(f"      {evidence}")
            print()
    else:
        print("No connections found.")


async def show_insiders():
    """Show all detected insiders."""
    from database import get_connection as db_conn

    conn = db_conn()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT wallet_address, pattern, confidence, win_rate, avg_roi, promoted_to_main
            FROM insider_pool
            ORDER BY confidence DESC
            LIMIT 20
        """)

        rows = cursor.fetchall()

        if rows:
            print("\nDetected Insiders:\n")
            print(f"{'Wallet':<45} {'Pattern':<20} {'Conf':<6} {'WR':<6} {'ROI':<8} {'Main'}")
            print("-" * 95)
            for row in rows:
                wallet, pattern, conf, wr, roi, promoted = row
                print(f"{wallet[:43]:45} {pattern or 'Unknown':<20} {(conf or 0)*100:>4.0f}% {(wr or 0)*100:>4.0f}% {roi or 0:>6.0f}% {'✓' if promoted else ''}")
        else:
            print("No insiders detected yet. Run the pipeline to start scanning.")

    except Exception as e:
        print(f"Error: {e}")
        print("Run 'python run_insider.py' to start the pipeline first.")

    finally:
        conn.close()


async def show_clusters():
    """Show detected wallet clusters."""
    from database import get_connection as db_conn

    conn = db_conn()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT cluster_id, label, wallet_count, risk_score
            FROM wallet_clusters
            ORDER BY wallet_count DESC
            LIMIT 10
        """)

        rows = cursor.fetchall()

        if rows:
            print("\nWallet Clusters:\n")
            print(f"{'Cluster ID':<20} {'Label':<20} {'Wallets':<10} {'Risk'}")
            print("-" * 55)
            for row in rows:
                cid, label, count, risk = row
                print(f"{cid:<20} {label or 'Unknown':<20} {count:<10} {(risk or 0)*100:.0f}%")
        else:
            print("No clusters detected yet.")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Insider Detection Pipeline')
    parser.add_argument('--scan', action='store_true', help='Scan for fresh launches')
    parser.add_argument('--analyze', type=str, help='Analyze a specific wallet')
    parser.add_argument('--connections', type=str, help='Find connections for a wallet')
    parser.add_argument('--insiders', action='store_true', help='Show detected insiders')
    parser.add_argument('--clusters', action='store_true', help='Show wallet clusters')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize database
    init_database()

    from datetime import datetime

    if args.scan:
        asyncio.run(scan_fresh_launches())
    elif args.analyze:
        asyncio.run(analyze_wallet(args.analyze))
    elif args.connections:
        asyncio.run(find_connections(args.connections))
    elif args.insiders:
        asyncio.run(show_insiders())
    elif args.clusters:
        asyncio.run(show_clusters())
    else:
        # Default: run full pipeline
        print("=" * 50)
        print("INSIDER DETECTION PIPELINE")
        print("=" * 50)
        print("\nStarting scanners...")
        print("  • Launch Tracker: Monitoring fresh tokens")
        print("  • Cluster Scanner: Building wallet graph")
        print("  • Insider Detector: Analyzing patterns")
        print("\nPress Ctrl+C to stop\n")

        asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
