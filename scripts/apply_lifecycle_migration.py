#!/usr/bin/env python3
"""
Apply Position Lifecycle Migration

Creates the position_lifecycle table and related indexes/views.

Usage:
    python scripts/apply_lifecycle_migration.py
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection


def apply_migration():
    """Apply the position_lifecycle migration."""
    migration_path = Path(__file__).parent.parent / "database" / "migrations" / "002_add_position_lifecycle.sql"

    if not migration_path.exists():
        print(f"❌ Migration file not found: {migration_path}")
        return False

    print(f"📦 Applying migration: {migration_path.name}")

    with open(migration_path, 'r') as f:
        migration_sql = f.read()

    conn = get_connection()

    try:
        conn.executescript(migration_sql)
        conn.commit()
        print("✅ Migration applied successfully!")

        # Verify table exists
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='position_lifecycle'
        """)
        if cursor.fetchone():
            print("✅ Table 'position_lifecycle' created")
        else:
            print("❌ Table 'position_lifecycle' NOT found")
            return False

        # Check indexes
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name LIKE 'idx_position_lifecycle%'
        """)
        indexes = cursor.fetchall()
        print(f"✅ Created {len(indexes)} indexes")

        # Check cron state
        cursor.execute("""
            SELECT enabled FROM cron_states WHERE cron_name = 'lifecycle_tracking'
        """)
        row = cursor.fetchone()
        if row:
            print(f"✅ Cron state 'lifecycle_tracking' enabled: {bool(row[0])}")

        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

    finally:
        conn.close()


def show_table_info():
    """Show position_lifecycle table info."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Table info
        cursor.execute("PRAGMA table_info(position_lifecycle)")
        columns = cursor.fetchall()

        print("\n📊 position_lifecycle table columns:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")

        # Count rows
        cursor.execute("SELECT COUNT(*) FROM position_lifecycle")
        count = cursor.fetchone()[0]
        print(f"\n📈 Current row count: {count}")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    if apply_migration():
        show_table_info()
