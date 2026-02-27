#!/usr/bin/env python3
"""
Database Schema Migration Script
Adds missing columns to insider_pool and wallet_clusters tables
"""
import sys
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection

def column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def migrate_insider_pool(conn):
    """Add missing columns to insider_pool table."""
    cursor = conn.cursor()

    print("\n📊 Migrating insider_pool table...")

    # Check if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='insider_pool'
    """)

    if not cursor.fetchone():
        print("  ⚠️  Table insider_pool doesn't exist, skipping...")
        return

    # List of columns to add
    columns_to_add = [
        ('early_entry_count', 'INTEGER DEFAULT 0'),
        ('win_rate', 'REAL DEFAULT 0.0'),
        ('avg_hold_minutes', 'REAL DEFAULT 0.0'),
        ('tier', "TEXT DEFAULT 'Bronze'"),
        ('discovered_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'),
    ]

    # Add missing columns
    for column_name, column_def in columns_to_add:
        if not column_exists(cursor, 'insider_pool', column_name):
            try:
                cursor.execute(f"ALTER TABLE insider_pool ADD COLUMN {column_name} {column_def}")
                print(f"  ✓ Added column: {column_name}")
            except sqlite3.OperationalError as e:
                print(f"  ✗ Failed to add {column_name}: {e}")
        else:
            print(f"  ○ Column already exists: {column_name}")

    conn.commit()
    print("  ✓ insider_pool migration complete")

def migrate_wallet_clusters(conn):
    """Add missing columns to wallet_clusters table."""
    cursor = conn.cursor()

    print("\n📊 Migrating wallet_clusters table...")

    # Check if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='wallet_clusters'
    """)

    if not cursor.fetchone():
        print("  ⚠️  Table wallet_clusters doesn't exist, skipping...")
        return

    # List of columns to add
    columns_to_add = [
        ('cluster_size', 'INTEGER DEFAULT 0'),
        ('cluster_type', "TEXT DEFAULT 'Unknown'"),
        ('connection_strength', 'REAL DEFAULT 0.0'),
        ('shared_tokens', "TEXT DEFAULT ''"),
    ]

    # Add missing columns
    for column_name, column_def in columns_to_add:
        if not column_exists(cursor, 'wallet_clusters', column_name):
            try:
                cursor.execute(f"ALTER TABLE wallet_clusters ADD COLUMN {column_name} {column_def}")
                print(f"  ✓ Added column: {column_name}")
            except sqlite3.OperationalError as e:
                print(f"  ✗ Failed to add {column_name}: {e}")
        else:
            print(f"  ○ Column already exists: {column_name}")

    conn.commit()
    print("  ✓ wallet_clusters migration complete")

def update_cluster_sizes(conn):
    """Update cluster_size based on cluster_members count."""
    cursor = conn.cursor()

    print("\n📊 Updating cluster sizes...")

    try:
        # Check if cluster_members table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='cluster_members'
        """)

        if not cursor.fetchone():
            print("  ⚠️  Table cluster_members doesn't exist, skipping size update...")
            return

        # Update cluster_size based on member count
        cursor.execute("""
            UPDATE wallet_clusters
            SET cluster_size = (
                SELECT COUNT(*)
                FROM cluster_members
                WHERE cluster_members.cluster_id = wallet_clusters.cluster_id
            )
            WHERE cluster_size = 0
        """)

        updated = cursor.rowcount
        conn.commit()
        print(f"  ✓ Updated {updated} cluster sizes")

    except sqlite3.OperationalError as e:
        print(f"  ⚠️  Could not update cluster sizes: {e}")

def show_schema(conn, table_name):
    """Show the schema of a table."""
    cursor = conn.cursor()

    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    if not columns:
        print(f"\n  Table '{table_name}' doesn't exist")
        return

    print(f"\n📋 Schema for {table_name}:")
    print("  Column Name              Type            Not Null  Default")
    print("  " + "-" * 70)

    for col in columns:
        col_id, name, col_type, not_null, default_val, pk = col
        default_str = str(default_val) if default_val is not None else 'NULL'
        not_null_str = 'YES' if not_null else 'NO'
        print(f"  {name:24} {col_type:15} {not_null_str:9} {default_str}")

def main():
    """Run database migrations."""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          DATABASE SCHEMA MIGRATION                          ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    try:
        # Get database connection
        conn = get_connection()

        # Run migrations
        migrate_insider_pool(conn)
        migrate_wallet_clusters(conn)
        update_cluster_sizes(conn)

        # Show updated schemas
        show_schema(conn, 'insider_pool')
        show_schema(conn, 'wallet_clusters')

        conn.close()

        print("\n" + "="*66)
        print("✅ Migration completed successfully!")
        print("="*66)
        print("\nTest Telegram commands:")
        print("  • /insiders - Should now work without 'early_entry_count' error")
        print("  • /clusters - Should now work without 'cluster_size' error")
        print()

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
