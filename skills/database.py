"""
Hedgehog Database Skills
SQL queries against SoulWinners database
"""
import sqlite3
from typing import Any, Dict, List

from config import get_db_path
from skills.base import get_registry


class DatabaseSkills:
    """Database query capabilities"""

    @staticmethod
    def _get_connection():
        """Get database connection"""
        db_path = get_db_path()
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        return sqlite3.connect(db_path)

    @staticmethod
    def query(sql: str) -> List[Dict]:
        """
        Execute a SQL query and return results as list of dicts

        Args:
            sql: SQL query to execute (SELECT only for safety)

        Returns:
            List of row dictionaries
        """
        # Safety: only allow SELECT queries
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed for safety")

        conn = DatabaseSkills._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            # Convert to list of dicts
            result = [dict(row) for row in rows]
            return result
        finally:
            conn.close()

    @staticmethod
    def get_wallet_count() -> int:
        """Get total wallet count from database"""
        try:
            result = DatabaseSkills.query("SELECT COUNT(*) as count FROM wallets")
            return result[0]["count"] if result else 0
        except Exception as e:
            # Table might not exist or have different name
            return f"Error: {str(e)}"

    @staticmethod
    def get_tables() -> List[str]:
        """List all tables in the database"""
        result = DatabaseSkills.query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row["name"] for row in result]


# Register skills
registry = get_registry()

@registry.register(
    name="database_query",
    description="Execute a SQL SELECT query on the SoulWinners database",
    parameters=[{"name": "sql", "type": "str", "description": "SQL SELECT query"}]
)
def database_query(sql: str) -> Any:
    """Execute database query"""
    return DatabaseSkills.query(sql)


@registry.register(
    name="get_wallet_count",
    description="Get the total number of wallets in the database",
    parameters=[]
)
def get_wallet_count() -> int:
    """Get wallet count"""
    return DatabaseSkills.get_wallet_count()


@registry.register(
    name="list_tables",
    description="List all tables in the SoulWinners database",
    parameters=[]
)
def list_tables() -> List[str]:
    """List database tables"""
    return DatabaseSkills.get_tables()
