"""
Database Tools for Hedgehog

Tools for querying and modifying the SoulWinners database.
ALWAYS use schema_discovery tool first to check table structure before querying.
"""
import sqlite3
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, SafetyLevel


class SchemaDiscoveryTool(Tool):
    """Discover database schema - ALWAYS use this before querying unknown tables."""

    name = "schema_discovery"
    description = """Discover table schema before querying. ALWAYS use this first.
    Returns column names, types, and sample data for any table."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Table name to inspect (or 'all' to list tables)"
            }
        },
        "required": ["table_name"]
    }

    async def execute(self, table_name: str = "all") -> ToolResult:
        """Discover schema for a table or list all tables."""
        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            if table_name.lower() == "all":
                # List all tables
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in cursor.fetchall()]
                conn.close()
                return ToolResult(success=True, data={"tables": tables})

            # Get table info
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [
                {"name": row[1], "type": row[2], "nullable": not row[3], "pk": bool(row[5])}
                for row in cursor.fetchall()
            ]

            if not columns:
                conn.close()
                return ToolResult(success=False, error=f"Table '{table_name}' not found")

            # Get sample data (3 rows)
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
            sample_rows = cursor.fetchall()
            col_names = [col["name"] for col in columns]
            sample = [dict(zip(col_names, row)) for row in sample_rows]

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "table": table_name,
                    "columns": columns,
                    "row_count": row_count,
                    "sample_data": sample,
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class DatabaseQueryTool(Tool):
    """Execute read-only SQL queries on the database."""

    name = "database_query"
    description = """Execute SQL SELECT query. Use schema_discovery first to check columns.
    Key tables: qualified_wallets, wallet_performance, position_lifecycle, transactions, alerts, settings"""

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
        "TRUNCATE", "REPLACE", "ATTACH", "DETACH"
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
    """Get statistics about wallets - checks schema automatically."""

    name = "wallet_stats"
    description = """Get wallet stats. Auto-detects correct table/columns.
    Returns: counts, tiers, top performers. Handles qualified_wallets & wallet_performance."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "wallet_type": {
                "type": "string",
                "description": "Filter: insider, elite, pumpfun, dex, or all",
                "enum": ["insider", "elite", "pumpfun", "dex", "all"]
            },
            "tier": {
                "type": "string",
                "description": "Filter by tier (Elite, High-Quality, Mid-Tier)",
                "enum": ["Elite", "High-Quality", "Mid-Tier", "all"]
            }
        },
        "required": []
    }

    async def execute(self, wallet_type: str = "all", tier: str = "all") -> ToolResult:
        """Get wallet statistics from appropriate tables."""
        try:
            from database import get_connection

            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            result = {"sources": {}}

            # Check qualified_wallets (main elite pool)
            cursor.execute("SELECT COUNT(*) as cnt FROM qualified_wallets")
            qw_count = cursor.fetchone()["cnt"]

            if qw_count > 0 and wallet_type in ["elite", "insider", "all"]:
                # Get tier distribution
                cursor.execute("""
                    SELECT tier, COUNT(*) as cnt,
                           AVG(win_rate) as avg_wr,
                           AVG(roi_pct) as avg_roi,
                           AVG(priority_score) as avg_priority
                    FROM qualified_wallets
                    WHERE tier IS NOT NULL
                    GROUP BY tier
                """)
                tiers = {}
                for row in cursor.fetchall():
                    tiers[row["tier"] or "Unclassified"] = {
                        "count": row["cnt"],
                        "avg_win_rate": round(row["avg_wr"] or 0, 1),
                        "avg_roi": round(row["avg_roi"] or 0, 1),
                        "avg_priority": round(row["avg_priority"] or 0, 1),
                    }

                # Top by priority_score
                where_clause = f"WHERE tier = '{tier}'" if tier != "all" else ""
                cursor.execute(f"""
                    SELECT wallet_address, tier, win_rate, roi_pct, priority_score
                    FROM qualified_wallets
                    {where_clause}
                    ORDER BY priority_score DESC NULLS LAST
                    LIMIT 5
                """)
                top = []
                for row in cursor.fetchall():
                    top.append({
                        "wallet": row["wallet_address"][:8] + "...",
                        "tier": row["tier"],
                        "win_rate": f"{(row['win_rate'] or 0):.0%}",
                        "roi": f"{row['roi_pct'] or 0:.0f}%",
                        "score": round(row["priority_score"] or 0, 1),
                    })

                result["sources"]["qualified_wallets"] = {
                    "total": qw_count,
                    "by_tier": tiers,
                    "top_performers": top,
                }

            # Check wallet_performance (pump.fun wallets)
            if wallet_type in ["pumpfun", "all"]:
                cursor.execute("SELECT COUNT(*) as cnt FROM wallet_performance")
                pf_count = cursor.fetchone()["cnt"]
                if pf_count > 0:
                    cursor.execute("""
                        SELECT wallet_address, win_rate, total_profit_usd
                        FROM wallet_performance
                        WHERE win_rate IS NOT NULL
                        ORDER BY win_rate DESC
                        LIMIT 3
                    """)
                    top_pf = [
                        {
                            "wallet": row["wallet_address"][:8] + "...",
                            "win_rate": f"{(row['win_rate'] or 0):.0%}",
                            "profit": f"${row['total_profit_usd'] or 0:,.0f}",
                        }
                        for row in cursor.fetchall()
                    ]
                    result["sources"]["wallet_performance"] = {
                        "total": pf_count,
                        "top_performers": top_pf,
                    }

            # Check position_lifecycle for wallet_type stats
            cursor.execute("""
                SELECT wallet_type, COUNT(*) as cnt
                FROM position_lifecycle
                WHERE wallet_type IS NOT NULL
                GROUP BY wallet_type
            """)
            wt_stats = dict(cursor.fetchall())
            if wt_stats:
                result["wallet_types_in_positions"] = wt_stats

            conn.close()

            # Summary
            total = sum(
                src.get("total", 0) for src in result.get("sources", {}).values()
            )
            result["total_wallets"] = total

            return ToolResult(success=True, data=result)

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
