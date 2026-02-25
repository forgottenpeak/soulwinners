"""
Database module for SoulWinners
"""
import sqlite3
from pathlib import Path
from config.settings import DATABASE_PATH, DATA_DIR


def get_connection():
    """Get database connection."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH)


def init_database():
    """Initialize database with schema."""
    schema_path = Path(__file__).parent / "schema.sql"

    with open(schema_path, 'r') as f:
        schema = f.read()

    conn = get_connection()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print(f"Database initialized at {DATABASE_PATH}")


if __name__ == "__main__":
    init_database()
