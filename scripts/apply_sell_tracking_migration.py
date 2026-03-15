#!/usr/bin/env python3
"""
Apply Sell Tracking Migration (004)

Adds:
- wallet_exits table for tracking elite wallet sells
- New columns to position_lifecycle for momentum metrics
- Views for position exits and active tokens

Usage:
    python scripts/apply_sell_tracking_migration.py [--check] [--force]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection


def check_migration_status():
    """Check if migration has already been applied."""
    conn = get_connection()
    cursor = conn.cursor()

    status = {
        'wallet_exits_table': False,
        'elite_exit_count_column': False,
        'momentum_score_column': False,
        'mc_samples_column': False,
    }

    try:
        # Check for wallet_exits table
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='wallet_exits'
        """)
        status['wallet_exits_table'] = cursor.fetchone() is not None

        # Check for new columns in position_lifecycle
        cursor.execute("PRAGMA table_info(position_lifecycle)")
        columns = {row[1] for row in cursor.fetchall()}

        status['elite_exit_count_column'] = 'elite_exit_count' in columns
        status['momentum_score_column'] = 'momentum_score' in columns
        status['mc_samples_column'] = 'mc_samples' in columns

    except Exception as e:
        print(f"Error checking migration status: {e}")

    finally:
        conn.close()

    return status


def apply_migration(force: bool = False):
    """Apply the migration."""
    status = check_migration_status()

    # Check if already applied
    all_applied = all(status.values())
    if all_applied and not force:
        print("✅ Migration already applied!")
        print("\nStatus:")
        for key, value in status.items():
            emoji = "✅" if value else "❌"
            print(f"  {emoji} {key}")
        return True

    print("Applying migration 004: Sell Tracking...")
    print(f"  Force mode: {force}")
    print()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1. Create wallet_exits table
        if not status['wallet_exits_table'] or force:
            print("Creating wallet_exits table...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wallet_exits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL,
                    wallet_address TEXT NOT NULL,
                    token_address TEXT NOT NULL,
                    exit_timestamp INTEGER NOT NULL,
                    sell_sol_received REAL NOT NULL,
                    exit_mc REAL,
                    hold_duration_hours REAL,
                    roi_at_exit REAL,
                    signature TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (position_id) REFERENCES position_lifecycle(id)
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_exits_position ON wallet_exits(position_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_exits_token ON wallet_exits(token_address)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_exits_wallet ON wallet_exits(wallet_address)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_exits_timestamp ON wallet_exits(exit_timestamp DESC)")
            print("  ✅ wallet_exits table created")

        # 2. Add columns to position_lifecycle (one at a time, ignore if exists)
        new_columns = [
            ("elite_exit_count", "INTEGER DEFAULT 0"),
            ("elite_still_holding", "INTEGER DEFAULT 0"),
            ("first_elite_exit_timestamp", "INTEGER"),
            ("momentum_score", "REAL DEFAULT 0"),
            ("momentum_trend", "TEXT DEFAULT 'neutral'"),
            ("volume_trend", "TEXT DEFAULT 'stable'"),
            ("volume_change_1h", "REAL DEFAULT 0"),
            ("volume_change_24h", "REAL DEFAULT 0"),
            ("new_holders_24h", "INTEGER DEFAULT 0"),
            ("holder_change_rate", "REAL DEFAULT 0"),
            ("mc_samples", "TEXT DEFAULT '[]'"),
            ("prev_volume_1h", "REAL DEFAULT 0"),
            ("prev_holder_count", "INTEGER DEFAULT 0"),
        ]

        print("Adding columns to position_lifecycle...")
        for col_name, col_type in new_columns:
            try:
                cursor.execute(f"ALTER TABLE position_lifecycle ADD COLUMN {col_name} {col_type}")
                print(f"  ✅ Added column: {col_name}")
            except Exception as e:
                if "duplicate column" in str(e).lower():
                    print(f"  ⏭️  Column exists: {col_name}")
                else:
                    print(f"  ⚠️  Error adding {col_name}: {e}")

        # 3. Create indexes
        print("Creating indexes...")
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_position_lifecycle_dup_check
                ON position_lifecycle(wallet_address, token_address, entry_timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_position_lifecycle_token_open
                ON position_lifecycle(token_address, outcome)
            """)
            print("  ✅ Indexes created")
        except Exception as e:
            print(f"  ⚠️  Index error: {e}")

        # 4. Create views
        print("Creating views...")
        try:
            cursor.execute("DROP VIEW IF EXISTS v_position_exits")
            cursor.execute("""
                CREATE VIEW v_position_exits AS
                SELECT
                    pl.id as position_id,
                    pl.token_address,
                    pl.token_symbol,
                    pl.entry_timestamp,
                    pl.entry_mc,
                    pl.peak_mc,
                    pl.current_mc,
                    pl.outcome,
                    pl.elite_exit_count,
                    pl.elite_still_holding,
                    pl.momentum_score,
                    pl.volume_trend,
                    COUNT(we.id) as total_exits,
                    MIN(we.exit_timestamp) as first_exit,
                    MAX(we.exit_timestamp) as last_exit,
                    AVG(we.roi_at_exit) as avg_exit_roi
                FROM position_lifecycle pl
                LEFT JOIN wallet_exits we ON we.position_id = pl.id
                GROUP BY pl.id
            """)
            print("  ✅ v_position_exits view created")
        except Exception as e:
            print(f"  ⚠️  View error: {e}")

        try:
            cursor.execute("DROP VIEW IF EXISTS v_active_tokens")
            cursor.execute("""
                CREATE VIEW v_active_tokens AS
                SELECT DISTINCT
                    token_address,
                    token_symbol,
                    COUNT(DISTINCT wallet_address) as tracking_wallets,
                    MIN(entry_timestamp) as first_entry,
                    MAX(entry_timestamp) as last_entry
                FROM position_lifecycle
                WHERE outcome IS NULL OR outcome = 'open'
                GROUP BY token_address
            """)
            print("  ✅ v_active_tokens view created")
        except Exception as e:
            print(f"  ⚠️  View error: {e}")

        conn.commit()
        print()
        print("✅ Migration 004 applied successfully!")

        # Verify
        new_status = check_migration_status()
        print("\nVerification:")
        for key, value in new_status.items():
            emoji = "✅" if value else "❌"
            print(f"  {emoji} {key}")

        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Apply sell tracking migration"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check migration status only"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force apply even if partially applied"
    )

    args = parser.parse_args()

    if args.check:
        status = check_migration_status()
        print("Migration 004 Status:")
        print()
        for key, value in status.items():
            emoji = "✅" if value else "❌"
            print(f"  {emoji} {key}")
        print()
        if all(status.values()):
            print("Migration fully applied!")
        else:
            print("Migration NOT fully applied. Run without --check to apply.")
    else:
        apply_migration(force=args.force)


if __name__ == "__main__":
    main()
