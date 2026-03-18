"""
Database Tools for Hedgehog

Tools for querying and modifying the SoulWinners database.
"""
import sqlite3
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, SafetyLevel


class DatabaseQueryTool(Tool):
    """Execute read-only SQL queries on the database."""

    name = "database_query"
    description = """Execute a read-only SQL query on the SoulWinners database.
    Returns query results as a list of dictionaries.
    Only SELECT queries are allowed. Available tables:
    - qualified_wallets: Elite wallet pool with performance metrics
    - position_lifecycle: Tracked positions with entry/exit data
    - wallet_exits: Sell events from elite wallets
    - transactions: Historical transaction data
    - alerts: Telegram alert history
    - settings: Bot configuration"""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to execute"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum rows to return (default 100)",
                "default": 100
            }
        },
        "required": ["query"]
    }

    # Blocked keywords for safety
    BLOCKED_KEYWORDS = [
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
        "TRUNCATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA"
    ]

    async def execute(self, query: str, limit: int = 100) -> ToolResult:
        """Execute read-only query."""
        # Safety check - only SELECT queries
        query_upper = query.upper().strip()

        if not query_upper.startswith("SELECT"):
            return ToolResult(
                success=False,
                error="Only SELECT queries are allowed. Use database_write for modifications."
            )

        # Check for blocked keywords
        for keyword in self.BLOCKED_KEYWORDS:
            if keyword in query_upper:
                return ToolResult(
                    success=False,
                    error=f"Query contains blocked keyword: {keyword}"
                )

        try:
            from database import get_connection

            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Add LIMIT if not present
            if "LIMIT" not in query_upper:
                query = f"{query.rstrip(';')} LIMIT {limit}"

            cursor.execute(query)
            rows = cursor.fetchall()
            conn.close()

            # Convert to list of dicts
            results = [dict(row) for row in rows]

            return ToolResult(
                success=True,
                data=results,
                metadata={"row_count": len(results)}
            )

        except sqlite3.Error as e:
            return ToolResult(success=False, error=f"Database error: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class DatabaseWriteTool(Tool):
    """Execute write operations on the database (with restrictions)."""

    name = "database_write"
    description = """Execute a write operation on the SoulWinners database.
    Supports INSERT and UPDATE operations with safety restrictions.
    Cannot DROP tables or DELETE data without explicit approval."""

    safety_level = SafetyLevel.MODERATE
    parameters_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["insert", "update"],
                "description": "Type of write operation"
            },
            "table": {
                "type": "string",
                "description": "Table to modify"
            },
            "data": {
                "type": "object",
                "description": "Data to insert/update"
            },
            "where": {
                "type": "string",
                "description": "WHERE clause for UPDATE (required for updates)"
            }
        },
        "required": ["operation", "table", "data"]
    }

    # Tables that can be safely modified
    ALLOWED_TABLES = [
        "settings",
        "cron_states",
        "ai_reports",
        "hedgehog_memory",
        "hedgehog_decisions",
    ]

    # Tables that require extra caution
    RESTRICTED_TABLES = [
        "qualified_wallets",
        "position_lifecycle",
        "user_wallets",
        "authorized_users",
    ]

    async def execute(
        self,
        operation: str,
        table: str,
        data: Dict[str, Any],
        where: Optional[str] = None
    ) -> ToolResult:
        """Execute write operation."""
        # Check table permissions
        if table not in self.ALLOWED_TABLES:
            if table in self.RESTRICTED_TABLES:
                return ToolResult(
                    success=False,
                    error=f"Table '{table}' requires admin approval for modifications"
                )
            return ToolResult(
                success=False,
                error=f"Table '{table}' is not in allowed list: {self.ALLOWED_TABLES}"
            )

        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            if operation == "insert":
                columns = ", ".join(data.keys())
                placeholders = ", ".join(["?" for _ in data])
                query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
                cursor.execute(query, list(data.values()))

            elif operation == "update":
                if not where:
                    return ToolResult(
                        success=False,
                        error="UPDATE requires a WHERE clause for safety"
                    )
                set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
                query = f"UPDATE {table} SET {set_clause} WHERE {where}"
                cursor.execute(query, list(data.values()))

            else:
                return ToolResult(
                    success=False,
                    error=f"Unsupported operation: {operation}"
                )

            conn.commit()
            affected = cursor.rowcount
            conn.close()

            return ToolResult(
                success=True,
                data={"affected_rows": affected},
                metadata={"operation": operation, "table": table}
            )

        except sqlite3.Error as e:
            return ToolResult(success=False, error=f"Database error: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WalletStatsTool(Tool):
    """Get statistics about the elite wallet pool."""

    name = "wallet_stats"
    description = """Get statistics about the elite wallet pool.
    Returns counts, tier distribution, and performance metrics."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "tier": {
                "type": "string",
                "description": "Filter by tier (Elite, High-Quality, Mid-Tier)",
                "enum": ["Elite", "High-Quality", "Mid-Tier", "all"]
            }
        },
        "required": []
    }

    async def execute(self, tier: str = "all") -> ToolResult:
        """Get wallet statistics."""
        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            # Total count
            cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
            total = cursor.fetchone()[0]

            # By tier
            cursor.execute("""
                SELECT tier, COUNT(*), AVG(win_rate), AVG(roi_pct)
                FROM qualified_wallets
                GROUP BY tier
            """)
            tier_stats = {}
            for row in cursor.fetchall():
                tier_stats[row[0] or "Unknown"] = {
                    "count": row[1],
                    "avg_win_rate": round(row[2] or 0, 2),
                    "avg_roi": round(row[3] or 0, 2),
                }

            # Top performers
            cursor.execute("""
                SELECT wallet_address, tier, win_rate, roi_pct
                FROM qualified_wallets
                ORDER BY priority_score DESC
                LIMIT 5
            """)
            top_wallets = [
                {
                    "address": row[0][:12] + "...",
                    "tier": row[1],
                    "win_rate": row[2],
                    "roi": row[3],
                }
                for row in cursor.fetchall()
            ]

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "total_wallets": total,
                    "tier_distribution": tier_stats,
                    "top_performers": top_wallets,
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class PositionStatsTool(Tool):
    """Get statistics about tracked positions."""

    name = "position_stats"
    description = """Get statistics about lifecycle positions.
    Returns open/closed counts, performance metrics, and recent activity."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "hours": {
                "type": "integer",
                "description": "Look back N hours (default 24)",
                "default": 24
            }
        },
        "required": []
    }

    async def execute(self, hours: int = 24) -> ToolResult:
        """Get position statistics."""
        try:
            import time
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            cutoff = int(time.time()) - (hours * 3600)

            # Open positions
            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE outcome IS NULL OR outcome = 'open'
            """)
            open_count = cursor.fetchone()[0]

            # Recent positions
            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE entry_timestamp > ?
            """, (cutoff,))
            recent_count = cursor.fetchone()[0]

            # Outcome distribution
            cursor.execute("""
                SELECT outcome, COUNT(*)
                FROM position_lifecycle
                WHERE outcome IS NOT NULL AND outcome != 'open'
                GROUP BY outcome
            """)
            outcomes = dict(cursor.fetchall())

            # Recent exits
            cursor.execute("""
                SELECT COUNT(*), AVG(roi_at_exit)
                FROM wallet_exits
                WHERE exit_timestamp > ?
            """, (cutoff,))
            row = cursor.fetchone()
            recent_exits = row[0] or 0
            avg_exit_roi = round(row[1] or 0, 2)

            # Best recent position
            cursor.execute("""
                SELECT token_symbol, peak_mc_multiplier, wallet_type
                FROM position_lifecycle
                WHERE entry_timestamp > ?
                ORDER BY peak_mc_multiplier DESC
                LIMIT 1
            """, (cutoff,))
            best = cursor.fetchone()
            best_position = None
            if best:
                best_position = {
                    "token": best[0],
                    "peak_multiplier": round(best[1] or 0, 2),
                    "wallet_type": best[2],
                }

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "open_positions": open_count,
                    "positions_last_hours": recent_count,
                    "hours": hours,
                    "outcomes": outcomes,
                    "recent_exits": recent_exits,
                    "avg_exit_roi": avg_exit_roi,
                    "best_position": best_position,
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
