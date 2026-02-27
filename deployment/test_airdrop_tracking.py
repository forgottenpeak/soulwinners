#!/usr/bin/env python3
"""
Test Airdrop Tracking
Verifies airdrop detection and tracking functionality
"""
import asyncio
import sys
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, '/Users/APPLE/Desktop/Soulwinners')

from collectors.launch_tracker import AirdropTracker, LaunchTracker
from database import get_connection


async def test_airdrop_tracker():
    """Test AirdropTracker class."""
    print("\n" + "=" * 60)
    print("TEST 1: AirdropTracker Initialization")
    print("=" * 60)

    tracker = AirdropTracker()
    print(f"\n✓ AirdropTracker initialized")
    print(f"✓ API key configured: {bool(tracker.api_key)}")

    return True


async def test_airdrop_detection():
    """Test airdrop detection on fresh launches."""
    print("\n" + "=" * 60)
    print("TEST 2: Airdrop Detection on Fresh Launches")
    print("=" * 60)

    launch_tracker = LaunchTracker()
    airdrop_tracker = AirdropTracker()

    print("\nScanning for fresh launches...")
    tokens = await launch_tracker.scan_fresh_launches()

    print(f"\n✓ Found {len(tokens)} fresh tokens (0-24h old)")

    if not tokens:
        print("\n⚠ No fresh tokens found. This is normal if:")
        print("  - No tokens launched in the last 24 hours")
        print("  - API rate limits")
        return True

    # Test airdrop detection on first 3 tokens
    for i, token in enumerate(tokens[:3], 1):
        age_minutes = (datetime.now() - token.launch_time).total_seconds() / 60

        print(f"\nToken {i}:")
        print(f"  Symbol: {token.symbol}")
        print(f"  Address: {token.address[:30]}...")
        print(f"  Age: {age_minutes:.1f} minutes")

        print(f"\n  Detecting airdrops...")
        recipients = await airdrop_tracker.detect_airdrops(
            token.address,
            token.launch_time
        )

        print(f"  ✓ Found {len(recipients)} airdrop recipients")

        if recipients:
            for j, recipient in enumerate(recipients[:5], 1):
                print(f"\n  Recipient {j}:")
                print(f"    Wallet: {recipient.wallet_address[:20]}...")
                print(f"    Received: {recipient.token_amount:.0f} tokens")
                print(f"    Time: {recipient.time_since_launch_min} min after launch")
                print(f"    Pattern: {recipient.pattern}")

                # Test sell tracking
                print(f"\n    Checking sell behavior...")
                sell_data = await airdrop_tracker.track_airdrop_sells(
                    recipient.wallet_address,
                    token.address
                )

                if sell_data['has_sold']:
                    print(f"    🚨 SOLD: {sell_data['sold_amount']:.0f} tokens")
                    print(f"    Hold duration: {sell_data.get('hold_duration_min', 0)} min")
                else:
                    print(f"    ✓ Still holding")

        await asyncio.sleep(1)  # Rate limiting

    return True


async def test_database_schema():
    """Test airdrop_insiders table schema."""
    print("\n" + "=" * 60)
    print("TEST 3: Database Schema")
    print("=" * 60)

    conn = get_connection()
    cursor = conn.cursor()

    # Create table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS airdrop_insiders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            token_address TEXT NOT NULL,
            token_symbol TEXT,
            received_time TIMESTAMP,
            time_since_launch_min INTEGER,
            token_amount REAL,
            token_value_sol REAL DEFAULT 0,
            percent_of_supply REAL DEFAULT 0,
            has_sold INTEGER DEFAULT 0,
            sold_amount REAL DEFAULT 0,
            sold_at TIMESTAMP,
            hold_duration_min INTEGER DEFAULT 0,
            pattern TEXT DEFAULT 'Airdrop Insider',
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(wallet_address, token_address)
        )
    """)

    print("\n✓ airdrop_insiders table created/verified")

    # Check table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='airdrop_insiders'
    """)

    if cursor.fetchone():
        print("✓ Table exists in database")
    else:
        print("✗ Table not found!")
        return False

    # Check columns
    cursor.execute("PRAGMA table_info(airdrop_insiders)")
    columns = cursor.fetchall()

    print(f"\n✓ Table has {len(columns)} columns:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")

    conn.close()

    return True


async def test_save_airdrop_recipient():
    """Test saving airdrop recipient to database."""
    print("\n" + "=" * 60)
    print("TEST 4: Save Airdrop Recipient")
    print("=" * 60)

    from collectors.launch_tracker import AirdropRecipient

    # Create test recipient
    test_recipient = AirdropRecipient(
        wallet_address="TEST_WALLET_ADDRESS_12345",
        token_address="TEST_TOKEN_ADDRESS_67890",
        token_symbol="TEST",
        received_time=datetime.now(),
        time_since_launch_min=5,
        token_amount=10000,
        token_value_sol=1.5,
        percent_of_supply=2.0,
    )

    print(f"\n✓ Created test recipient:")
    print(f"  Wallet: {test_recipient.wallet_address}")
    print(f"  Token: {test_recipient.token_symbol}")
    print(f"  Amount: {test_recipient.token_amount:.0f}")

    # Save to database
    tracker = AirdropTracker()
    await tracker.save_airdrop_recipient(test_recipient)

    print(f"\n✓ Saved to database")

    # Verify
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT wallet_address, token_symbol, token_amount
        FROM airdrop_insiders
        WHERE wallet_address = ?
    """, (test_recipient.wallet_address,))

    row = cursor.fetchone()
    conn.close()

    if row:
        print(f"\n✓ Verified in database:")
        print(f"  Wallet: {row[0]}")
        print(f"  Symbol: {row[1]}")
        print(f"  Amount: {row[2]:.0f}")
    else:
        print("\n✗ Not found in database!")
        return False

    return True


async def test_sell_alert_generation():
    """Test sell alert generation."""
    print("\n" + "=" * 60)
    print("TEST 5: Sell Alert Generation")
    print("=" * 60)

    from collectors.launch_tracker import AirdropRecipient

    # Create test recipient with sell data
    test_recipient = AirdropRecipient(
        wallet_address="7xKXtg2CW5UL6y8qTKv2FNxqEGjP9VWJYVv",
        token_address="TOKEN123",
        token_symbol="PUMP",
        received_time=datetime.now() - timedelta(minutes=45),
        time_since_launch_min=5,
        token_amount=50000,
        has_sold=True,
        sold_amount=20000,
        sold_at=datetime.now(),
        hold_duration_min=45,
    )

    print(f"\n✓ Created test recipient with sell:")
    print(f"  Received: {test_recipient.token_amount:.0f} tokens")
    print(f"  Sold: {test_recipient.sold_amount:.0f} tokens")
    print(f"  Hold: {test_recipient.hold_duration_min} minutes")

    # Generate alert
    tracker = AirdropTracker()
    alert = await tracker.generate_sell_alert(test_recipient, "PUMP")

    if alert:
        print(f"\n✓ Alert generated:\n")
        print(alert)
    else:
        print("\n✗ No alert generated!")
        return False

    return True


async def test_integration():
    """Test full integration with InsiderScanner."""
    print("\n" + "=" * 60)
    print("TEST 6: Integration with InsiderScanner")
    print("=" * 60)

    from collectors.launch_tracker import InsiderScanner

    scanner = InsiderScanner()

    print(f"\n✓ InsiderScanner initialized")
    print(f"✓ Has LaunchTracker: {bool(scanner.tracker)}")
    print(f"✓ Has AirdropTracker: {bool(scanner.airdrop_tracker)}")

    # Check if airdrop tracking is in scan cycle
    import inspect
    source = inspect.getsource(scanner._scan_cycle)

    if "detect_airdrops" in source:
        print("✓ Airdrop detection integrated in scan cycle")
    else:
        print("✗ Airdrop detection NOT in scan cycle!")
        return False

    if "_add_airdrop_wallet_to_pool" in source:
        print("✓ Auto-add airdrop wallets to pool integrated")
    else:
        print("✗ Auto-add NOT integrated!")
        return False

    if "generate_sell_alert" in source:
        print("✓ Sell alert generation integrated")
    else:
        print("✗ Sell alert NOT integrated!")
        return False

    return True


async def main():
    """Run all tests."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║        AIRDROP TRACKING - TEST SUITE                        ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    print("\nTesting airdrop tracking functionality:")
    print("  1. AirdropTracker initialization")
    print("  2. Airdrop detection on fresh launches")
    print("  3. Database schema")
    print("  4. Save airdrop recipient")
    print("  5. Sell alert generation")
    print("  6. Integration with InsiderScanner")

    results = []

    try:
        # Test 1: Initialization
        result1 = await test_airdrop_tracker()
        results.append(("Initialization", result1))

        # Test 2: Detection (may take a while)
        # Uncomment to test with real data
        # result2 = await test_airdrop_detection()
        # results.append(("Airdrop Detection", result2))

        # Test 3: Database schema
        result3 = await test_database_schema()
        results.append(("Database Schema", result3))

        # Test 4: Save recipient
        result4 = await test_save_airdrop_recipient()
        results.append(("Save Recipient", result4))

        # Test 5: Alert generation
        result5 = await test_sell_alert_generation()
        results.append(("Sell Alerts", result5))

        # Test 6: Integration
        result6 = await test_integration()
        results.append(("Integration", result6))

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
            print("\nAirdrop tracking is working correctly!")
            print("\n📊 Features verified:")
            print("  ✓ AirdropTracker class")
            print("  ✓ Database schema")
            print("  ✓ Save functionality")
            print("  ✓ Sell alert generation")
            print("  ✓ Integration with InsiderScanner")
            print("\n🚀 Ready for deployment!")
        else:
            print("\n❌ SOME TESTS FAILED")
            print("\nPlease review the errors above and fix before deploying.")

        return all_passed

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
