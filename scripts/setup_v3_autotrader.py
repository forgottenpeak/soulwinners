#!/usr/bin/env python3
"""
V3 Edge Auto-Trader Setup Script

Sets up the database tables and initial configuration for the ML-powered auto-trader.

Usage:
    python scripts/setup_v3_autotrader.py [--migrate] [--populate-pool] [--verify]

Steps:
1. Apply database migrations (new tables for ML)
2. Populate global wallet pool from existing qualified + insider wallets
3. Verify setup is complete
"""
import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from config.settings import DATABASE_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def apply_migrations():
    """Apply database migrations for ML tables."""
    logger.info("=" * 60)
    logger.info("STEP 1: Applying Database Migrations")
    logger.info("=" * 60)

    migration_file = Path(__file__).parent.parent / "database" / "migrations" / "001_add_ml_tables.sql"

    if not migration_file.exists():
        logger.error(f"Migration file not found: {migration_file}")
        return False

    try:
        with open(migration_file, 'r') as f:
            sql = f.read()

        conn = get_connection()
        conn.executescript(sql)
        conn.commit()
        conn.close()

        logger.info("Migration applied successfully!")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


def populate_global_pool():
    """Populate global wallet pool from existing data."""
    logger.info("=" * 60)
    logger.info("STEP 2: Populating Global Wallet Pool")
    logger.info("=" * 60)

    try:
        from bot.personalized_algo import PersonalizedAlgo

        algo = PersonalizedAlgo()
        total = algo.populate_global_pool()

        logger.info(f"Global pool populated with {total} wallets")
        return total

    except Exception as e:
        logger.error(f"Failed to populate global pool: {e}")
        return 0


def verify_setup():
    """Verify all tables and settings are properly configured."""
    logger.info("=" * 60)
    logger.info("STEP 3: Verifying Setup")
    logger.info("=" * 60)

    conn = get_connection()
    cursor = conn.cursor()

    checks = []

    # Check new tables exist
    tables_to_check = [
        "user_algo_config",
        "user_wallet_feed",
        "wallet_global_pool",
        "trade_events",
        "token_lifecycle",
        "ml_features",
        "ml_models",
        "ai_decisions",
        "auto_trades",
    ]

    for table in tables_to_check:
        cursor.execute(f"""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
        """, (table,))

        exists = cursor.fetchone() is not None
        checks.append((f"Table: {table}", exists))

    # Check settings exist
    settings_to_check = [
        "ai_gate_enabled",
        "autotrader_enabled",
        "autotrader_min_prob_runner",
        "autotrader_max_prob_rug",
    ]

    for setting in settings_to_check:
        cursor.execute("SELECT value FROM settings WHERE key = ?", (setting,))
        row = cursor.fetchone()
        checks.append((f"Setting: {setting}", row is not None))

    # Check cron states
    cursor.execute("SELECT cron_name FROM cron_states WHERE cron_name = 'autotrader'")
    checks.append(("Cron: autotrader", cursor.fetchone() is not None))

    # Check global pool
    cursor.execute("SELECT COUNT(*) FROM wallet_global_pool")
    pool_count = cursor.fetchone()[0]
    checks.append((f"Global pool wallets: {pool_count}", pool_count > 0))

    conn.close()

    # Print results
    all_passed = True
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False

    return all_passed


def show_status():
    """Show current V3 Auto-Trader status."""
    logger.info("=" * 60)
    logger.info("V3 EDGE AUTO-TRADER STATUS")
    logger.info("=" * 60)

    conn = get_connection()
    cursor = conn.cursor()

    # Get settings
    print("\n📊 Current Settings:")
    cursor.execute("""
        SELECT key, value FROM settings
        WHERE key LIKE 'ai_gate%' OR key LIKE 'autotrader%' OR key LIKE 'ml_%'
    """)
    for key, value in cursor.fetchall():
        print(f"  {key}: {value}")

    # Global pool stats
    print("\n🌐 Global Wallet Pool:")
    cursor.execute("SELECT COUNT(*) FROM wallet_global_pool")
    print(f"  Total wallets: {cursor.fetchone()[0]}")

    cursor.execute("""
        SELECT tier, COUNT(*) FROM wallet_global_pool GROUP BY tier
    """)
    for tier, count in cursor.fetchall():
        print(f"  {tier}: {count}")

    # Trade events stats
    print("\n📈 Trade Events:")
    cursor.execute("SELECT COUNT(*) FROM trade_events")
    total = cursor.fetchone()[0]
    print(f"  Total events: {total}")

    if total > 0:
        cursor.execute("""
            SELECT outcome, COUNT(*)
            FROM trade_events
            WHERE outcome IS NOT NULL
            GROUP BY outcome
        """)
        print("  By outcome:")
        for outcome, count in cursor.fetchall():
            print(f"    {outcome}: {count}")

    # ML models
    print("\n🤖 ML Models:")
    cursor.execute("""
        SELECT model_version, model_type, accuracy, is_active, training_date
        FROM ml_models
        ORDER BY training_date DESC
        LIMIT 5
    """)
    models = cursor.fetchall()
    if models:
        for version, mtype, acc, active, trained in models:
            status = "🟢 ACTIVE" if active else ""
            print(f"  {version} ({mtype}) - Accuracy: {acc:.2%} {status}")
    else:
        print("  No models trained yet")

    # Auto-trades today
    print("\n💰 Auto-Trades Today:")
    cursor.execute("""
        SELECT status, COUNT(*), SUM(sol_amount)
        FROM auto_trades
        WHERE DATE(created_at) = DATE('now')
        GROUP BY status
    """)
    trades = cursor.fetchall()
    if trades:
        for status, count, sol in trades:
            print(f"  {status}: {count} trades ({sol or 0:.2f} SOL)")
    else:
        print("  No trades today")

    # AI Advisor usage
    print("\n🧠 AI Advisor Usage (This Month):")
    cursor.execute("""
        SELECT user_id, total_cost_usd, request_count
        FROM user_ai_usage
        WHERE month = strftime('%Y-%m', 'now')
        ORDER BY total_cost_usd DESC
        LIMIT 5
    """)
    usage = cursor.fetchall()
    if usage:
        for user_id, cost, requests in usage:
            print(f"  User {user_id}: ${cost:.4f} ({requests} requests)")
    else:
        print("  No AI usage this month")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Setup V3 Edge Auto-Trader"
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Apply database migrations"
    )
    parser.add_argument(
        "--populate-pool",
        action="store_true",
        help="Populate global wallet pool"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify setup is complete"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full setup (migrate + populate + verify)"
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.full or args.migrate:
        if not apply_migrations():
            logger.error("Migration failed, aborting")
            sys.exit(1)

    if args.full or args.populate_pool:
        populate_global_pool()

    if args.full or args.verify:
        all_passed = verify_setup()
        if not all_passed:
            logger.warning("Some checks failed!")
            sys.exit(1)

    if args.full:
        print("\n" + "=" * 60)
        print("V3 EDGE AUTO-TRADER SETUP COMPLETE!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Build historical dataset:")
        print("   python scripts/build_historical_dataset.py")
        print("\n2. Label trade outcomes:")
        print("   python ml/continuous_learning.py --label-outcomes")
        print("\n3. Train ML model:")
        print("   python ml/train_model.py --save --deploy")
        print("\n4. Enable AI gate (XGBoost filtering):")
        print("   sqlite3 data/soulwinners.db \"UPDATE settings SET value='true' WHERE key='ai_gate_enabled'\"")
        print("\n5. Enable Claude AI Advisor (optional - supervises XGBoost):")
        print("   sqlite3 data/soulwinners.db \"UPDATE settings SET value='true' WHERE key='ai_advisor_enabled'\"")
        print("\n6. Enable auto-trader (optional - executes trades):")
        print("   sqlite3 data/soulwinners.db \"UPDATE settings SET value='true' WHERE key='autotrader_enabled'\"")
        print("\n7. Test AI Advisor:")
        print("   python ml/ai_advisor.py")

    if not any([args.migrate, args.populate_pool, args.verify, args.full, args.status]):
        parser.print_help()


if __name__ == "__main__":
    main()
