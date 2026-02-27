"""
Test V'ger Bot Setup
Verifies that V'ger can access the database and read OpenClaw data.
"""
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def test_environment():
    """Test environment variables."""
    print("=" * 60)
    print("TESTING V'GER ENVIRONMENT")
    print("=" * 60)
    print()

    # Check bot token
    bot_token = os.getenv('VGER_BOT_TOKEN')
    if bot_token:
        print("✓ VGER_BOT_TOKEN is set")
        print(f"  Token: {bot_token[:20]}...{bot_token[-10:]}")
    else:
        print("✗ VGER_BOT_TOKEN is NOT set")
        return False

    # Check admin ID
    admin_id = os.getenv('VGER_ADMIN_ID')
    if admin_id:
        print(f"✓ VGER_ADMIN_ID is set: {admin_id}")
    else:
        print("✗ VGER_ADMIN_ID is NOT set")
        return False

    return True


def test_database():
    """Test database access."""
    print()
    print("=" * 60)
    print("TESTING DATABASE ACCESS")
    print("=" * 60)
    print()

    db_path = "data/openclaw.db"

    # Check if database exists
    if not Path(db_path).exists():
        print(f"⚠ Database not found: {db_path}")
        print("  This is OK for initial setup.")
        print("  Database will be created when OpenClaw starts.")
        print(f"  Expected location: {Path(db_path).absolute()}")
        return True
    else:
        print(f"✓ Database found: {db_path}")

    # Test database connection
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check tables
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]

        print(f"✓ Database connected")
        print(f"  Tables: {', '.join(tables)}")

        # Check stats
        cursor.execute("SELECT key, value FROM stats")
        stats = cursor.fetchall()

        if stats:
            print()
            print("Database Stats:")
            for key, value in stats:
                print(f"  {key}: {value}")

        # Check positions
        cursor.execute("SELECT COUNT(*) FROM positions")
        position_count = cursor.fetchone()[0]
        print(f"  Total positions: {position_count}")

        # Check trade history
        cursor.execute("SELECT COUNT(*) FROM trade_history")
        trade_count = cursor.fetchone()[0]
        print(f"  Total trades: {trade_count}")

        conn.close()
        return True

    except Exception as e:
        print(f"✗ Database error: {e}")
        return False


def test_imports():
    """Test required imports."""
    print()
    print("=" * 60)
    print("TESTING PYTHON IMPORTS")
    print("=" * 60)
    print()

    # Essential V'ger modules (must have)
    essential_modules = [
        'telegram',
        'telegram.ext',
        'dotenv',
        'sqlite3',
    ]

    # Optional trader modules (needed for full functionality)
    optional_modules = [
        'trader.position_manager',
        'trader.strategy',
    ]

    all_ok = True
    optional_ok = True

    print("Essential modules:")
    for module in essential_modules:
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except ImportError as e:
            print(f"  ✗ {module} - {e}")
            all_ok = False

    print()
    print("Optional modules (needed on VPS):")
    for module in optional_modules:
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except ImportError as e:
            print(f"  ⚠ {module} - Not available (OK for local testing)")
            optional_ok = False

    if not all_ok:
        print()
        print("Missing essential dependencies! Install with:")
        print("  pip install python-telegram-bot python-dotenv")
    elif not optional_ok:
        print()
        print("Note: Trader modules not available locally.")
        print("This is OK. They will be available on the VPS.")

    return all_ok  # Only fail if essential modules missing


def test_bot_token():
    """Test bot token validity."""
    print()
    print("=" * 60)
    print("TESTING BOT TOKEN")
    print("=" * 60)
    print()

    bot_token = os.getenv('VGER_BOT_TOKEN')
    if not bot_token:
        print("✗ Bot token not set")
        return False

    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                bot_info = data['result']
                print("✓ Bot token is valid!")
                print(f"  Bot username: @{bot_info.get('username')}")
                print(f"  Bot name: {bot_info.get('first_name')}")
                print(f"  Bot ID: {bot_info.get('id')}")
                return True

        print(f"✗ Bot token validation failed: {response.text}")
        return False

    except ImportError:
        print("⚠ requests module not available, skipping token validation")
        print("  Install with: pip install requests")
        return True
    except Exception as e:
        print(f"✗ Error validating token: {e}")
        return False


def main():
    """Run all tests."""
    print()
    print("🖖 V'GER SETUP VERIFICATION")
    print()

    results = []

    # Run tests
    results.append(("Environment", test_environment()))
    results.append(("Imports", test_imports()))
    results.append(("Database", test_database()))
    results.append(("Bot Token", test_bot_token()))

    # Summary
    print()
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print()

    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status} - {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("🟢 ALL TESTS PASSED")
        print()
        print("V'ger is ready for deployment!")
        print()
        print("Next steps:")
        print("  1. Deploy to VPS: sudo bash deployment/deploy_vger.sh")
        print("  2. Test in Telegram: Send /start to @vger_bot")
        print()
    else:
        print("🔴 SOME TESTS FAILED")
        print()
        print("Fix the issues above before deployment.")
        print()
        print("Common fixes:")
        print("  • Missing .env file: Copy .env.example to .env")
        print("  • Missing packages: pip install -r requirements.txt")
        print("  • Invalid token: Check VGER_BOT_TOKEN in .env")
        print()

    return all_passed


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
