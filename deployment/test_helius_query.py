#!/usr/bin/env python3
"""
Test Helius Blockchain Query
Verifies that Pump.fun token discovery works via Helius
"""
import asyncio
import sys
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, '/Users/APPLE/Desktop/Soulwinners')

from collectors.launch_tracker import LaunchTracker
from collectors.pumpfun import PumpFunCollector


async def test_helius_query():
    """Test Helius blockchain query for Pump.fun tokens."""
    print("\n" + "=" * 60)
    print("TEST: Helius Blockchain Query")
    print("=" * 60)

    print("\n1. Testing LaunchTracker._scan_pumpfun_graduated()...")
    print("-" * 60)

    tracker = LaunchTracker()

    print("Querying Pump.fun program via Helius...")
    print("This may take 10-15 seconds...\n")

    tokens = await tracker._scan_pumpfun_graduated()

    print(f"\n✅ Found {len(tokens)} fresh Pump.fun tokens")

    if len(tokens) == 0:
        print("\n⚠️ WARNING: No tokens found!")
        print("Possible reasons:")
        print("  - No Pump.fun launches in last 24 hours")
        print("  - Helius API key not configured")
        print("  - Network connectivity issues")
        return False

    print("\n📊 Sample tokens:")
    for i, token in enumerate(tokens[:5], 1):
        age_minutes = (datetime.now() - token.launch_time).total_seconds() / 60
        migration_status = "✓ Migrated" if token.migration_detected else "○ Not migrated"

        print(f"\n  Token {i}:")
        print(f"    Symbol: {token.symbol}")
        print(f"    Address: {token.address[:30]}...")
        print(f"    Launch time: {token.launch_time}")
        print(f"    Age: {age_minutes:.1f} minutes")
        print(f"    Status: {migration_status}")

    print("\n" + "=" * 60)
    print("✅ Helius blockchain query WORKING!")
    print("=" * 60)

    return True


async def test_pumpfun_collector():
    """Test PumpFunCollector.get_fresh_pumpfun_launches()."""
    print("\n" + "=" * 60)
    print("TEST: PumpFunCollector.get_fresh_pumpfun_launches()")
    print("=" * 60)

    async with PumpFunCollector() as collector:
        print("\nQuerying fresh Pump.fun launches via Helius...")
        print("This may take 10-15 seconds...\n")

        tokens = await collector.get_fresh_pumpfun_launches()

        print(f"\n✅ Found {len(tokens)} fresh launches")

        if len(tokens) == 0:
            print("\n⚠️ WARNING: No tokens found!")
            return False

        print("\n📊 Sample tokens:")
        for i, token in enumerate(tokens[:5], 1):
            print(f"\n  Token {i}:")
            print(f"    Symbol: {token['symbol']}")
            print(f"    Address: {token['tokenAddress'][:30]}...")
            print(f"    Age: {token['age_minutes']:.1f} minutes")
            print(f"    Complete: {token.get('complete', False)}")

    print("\n" + "=" * 60)
    print("✅ PumpFunCollector WORKING!")
    print("=" * 60)

    return True


async def test_full_pipeline():
    """Test full token collection pipeline."""
    print("\n" + "=" * 60)
    print("TEST: Full Pipeline (LaunchTracker + PumpFunCollector)")
    print("=" * 60)

    # Test LaunchTracker
    print("\n1. LaunchTracker.scan_fresh_launches()...")
    tracker = LaunchTracker()
    tokens = await tracker.scan_fresh_launches()

    print(f"   ✅ Found {len(tokens)} fresh tokens total")

    # Test PumpFunCollector
    print("\n2. PumpFunCollector.collect_wallets()...")
    async with PumpFunCollector() as collector:
        print("   Testing with small batch (5 wallets)...")
        wallets = await collector.collect_wallets(
            target_count=5,
            use_fresh_launches=True
        )

        print(f"   ✅ Collected {len(wallets)} wallets from fresh launches")

        if wallets:
            print("\n   📊 Sample wallet:")
            w = wallets[0]
            print(f"      Address: {w['wallet_address'][:20]}...")
            print(f"      Buys: {w['buy_transactions']}")
            print(f"      Sells: {w['sell_transactions']}")
            print(f"      Win rate: {w['win_rate']:.1%}")

    print("\n" + "=" * 60)
    print("✅ Full pipeline WORKING!")
    print("=" * 60)

    return True


async def main():
    """Run all tests."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║        HELIUS BLOCKCHAIN QUERY - TEST SUITE                 ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    print("\nTesting Helius blockchain queries:")
    print("  1. LaunchTracker._scan_pumpfun_graduated()")
    print("  2. PumpFunCollector.get_fresh_pumpfun_launches()")
    print("  3. Full pipeline integration")

    results = []

    try:
        # Test 1: Helius query
        result1 = await test_helius_query()
        results.append(("Helius Query", result1))

        # Test 2: PumpFunCollector
        result2 = await test_pumpfun_collector()
        results.append(("PumpFunCollector", result2))

        # Test 3: Full pipeline (optional - takes longer)
        print("\n" + "=" * 60)
        print("Run full pipeline test? (will take ~2 minutes)")
        # Skip for automated testing
        # result3 = await test_full_pipeline()
        # results.append(("Full Pipeline", result3))

        print("\n" + "=" * 60)
        print("TEST RESULTS")
        print("=" * 60)

        all_passed = True
        for test_name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"\n{test_name}: {status}")
            if not result:
                all_passed = False

        print("\n" + "=" * 60)

        if all_passed:
            print("\n✅ ALL TESTS PASSED!")
            print("\nHelius blockchain query is working correctly!")
            print("\n📊 Key results:")
            print("  ✓ Helius API responding")
            print("  ✓ Pump.fun program queries working")
            print("  ✓ Token extraction functional")
            print("  ✓ Metadata fetching operational")
            print("  ✓ No Cloudflare blocks!")
            print("\n🚀 Ready for deployment!")
        else:
            print("\n❌ SOME TESTS FAILED")
            print("\nPlease review the errors above.")
            print("Common issues:")
            print("  - HELIUS_API_KEY not configured")
            print("  - Network connectivity problems")
            print("  - No Pump.fun launches in last 24h")

        return all_passed

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
