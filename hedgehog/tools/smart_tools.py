"""
Smart Tools for Hedgehog - Knowledge Base First

These tools query Hedgehog's knowledge base FIRST.
Only hit live system when knowledge base doesn't have the answer.

This is how a brain works - instant recall for things it knows,
only "looks" when needed.
"""

import sqlite3
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, SafetyLevel

# Import knowledge base
try:
    from hedgehog.knowledge import get_kb, HedgehogKnowledge
except ImportError:
    get_kb = None
    HedgehogKnowledge = None


def _get_kb():
    """Safely get knowledge base"""
    if get_kb is None:
        return None
    try:
        return get_kb()
    except Exception as e:
        print(f"[SMART TOOLS] KB not available: {e}")
        return None


class SmartSchemaDiscoveryTool(Tool):
    """
    Discover database schema - uses KNOWLEDGE BASE first.
    Instant answers from cached schema, no database hit for 95% of queries.
    """

    name = "schema_discovery"
    description = """Discover table schema. Uses cached knowledge for instant answers.
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
        """Discover schema - knowledge base first, live second."""

        # Try knowledge base first
        kb = _get_kb()
        if kb:
            if table_name.lower() == "all":
                result = kb.get_all_tables()
                if result.confidence > 0.8:
                    return ToolResult(
                        success=True,
                        data={
                            "tables": result.answer,
                            "source": "knowledge_base",
                            "query_time_ms": result.query_time_ms
                        }
                    )
            else:
                result = kb.get_table_info(table_name)
                if result.confidence > 0.8 and result.answer:
                    return ToolResult(
                        success=True,
                        data={
                            **result.answer,
                            "source": "knowledge_base",
                            "query_time_ms": result.query_time_ms
                        }
                    )

        # Fall back to live query
        return await self._live_query(table_name)

    async def _live_query(self, table_name: str) -> ToolResult:
        """Live database query (fallback)"""
        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            if table_name.lower() == "all":
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in cursor.fetchall()]
                conn.close()
                return ToolResult(
                    success=True,
                    data={"tables": tables, "source": "live_query"}
                )

            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [
                {"name": row[1], "type": row[2], "nullable": not row[3], "pk": bool(row[5])}
                for row in cursor.fetchall()
            ]

            if not columns:
                conn.close()
                return ToolResult(success=False, error=f"Table '{table_name}' not found")

            cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
            sample_rows = cursor.fetchall()
            col_names = [col["name"] for col in columns]
            sample = [dict(zip(col_names, row)) for row in sample_rows]

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
                    "source": "live_query"
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class SmartWalletStatsTool(Tool):
    """
    Get wallet statistics - INSTANT answers from knowledge base.
    No SQL needed for simple questions like "how many insider wallets?"
    """

    name = "wallet_stats"
    description = """Get wallet stats INSTANTLY from knowledge base.
    Questions like 'how many wallets?' are answered in <1ms.
    Returns: counts, tiers, top performers."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "wallet_type": {
                "type": "string",
                "description": "Filter: insider, qualified, user, copy_pool, global_pool, or all",
                "enum": ["insider", "qualified", "user", "copy_pool", "global_pool", "all"]
            },
            "question": {
                "type": "string",
                "description": "Natural language question like 'how many insider wallets?'"
            }
        },
        "required": []
    }

    async def execute(
        self,
        wallet_type: str = "all",
        question: Optional[str] = None
    ) -> ToolResult:
        """Get wallet stats - knowledge base first."""

        kb = _get_kb()
        if kb:
            # If natural language question, use smart answering
            if question:
                result = kb.answer(question)
                if result.confidence > 0.5:
                    return ToolResult(
                        success=True,
                        data={
                            "answer": result.answer,
                            "source": result.source,
                            "confidence": result.confidence,
                            "query_time_ms": result.query_time_ms
                        }
                    )

            # Direct wallet count query
            result = kb.get_wallet_count(wallet_type)
            if result.confidence > 0.5:
                return ToolResult(
                    success=True,
                    data={
                        "counts": result.answer,
                        "wallet_type": wallet_type,
                        "source": result.source,
                        "query_time_ms": result.query_time_ms
                    }
                )

        # Fall back to live query for detailed stats
        return await self._live_query(wallet_type)

    async def _live_query(self, wallet_type: str) -> ToolResult:
        """Live database query (fallback for detailed stats)"""
        try:
            from database import get_connection

            conn = get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            result = {"sources": {}, "source": "live_query"}

            # Get counts from various tables
            tables = {
                "qualified": "qualified_wallets",
                "insider": "insider_pool",
                "user": "user_wallets",
                "copy_pool": "copy_pool",
                "global_pool": "wallet_global_pool"
            }

            if wallet_type == "all":
                for key, table in tables.items():
                    try:
                        cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                        result["sources"][key] = cursor.fetchone()["cnt"]
                    except:
                        result["sources"][key] = 0
            else:
                table = tables.get(wallet_type)
                if table:
                    cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                    result["count"] = cursor.fetchone()["cnt"]

            conn.close()
            return ToolResult(success=True, data=result)

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class SmartPositionStatsTool(Tool):
    """
    Get position statistics - knowledge base first for quick counts.
    """

    name = "position_stats"
    description = """Get position statistics. Quick counts from knowledge base,
    detailed stats from live query. Instant for 'how many positions?'"""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "hours": {
                "type": "integer",
                "description": "Look back N hours for detailed stats (default 24)",
                "default": 24
            },
            "question": {
                "type": "string",
                "description": "Natural language question like 'how many open positions?'"
            }
        },
        "required": []
    }

    async def execute(
        self,
        hours: int = 24,
        question: Optional[str] = None
    ) -> ToolResult:
        """Get position stats - knowledge base first."""

        kb = _get_kb()
        if kb:
            # Try natural language first
            if question:
                result = kb.answer(question)
                if result.confidence > 0.5:
                    return ToolResult(
                        success=True,
                        data={
                            "answer": result.answer,
                            "source": result.source,
                            "confidence": result.confidence,
                            "query_time_ms": result.query_time_ms
                        }
                    )

            # Quick position counts
            result = kb.get_position_count('all')
            if result.confidence > 0.5 and hours >= 24:  # Only for simple queries
                return ToolResult(
                    success=True,
                    data={
                        "positions": result.answer,
                        "source": result.source,
                        "query_time_ms": result.query_time_ms
                    }
                )

        # Fall back to live for detailed time-based stats
        return await self._live_query(hours)

    async def _live_query(self, hours: int) -> ToolResult:
        """Live query for detailed position stats"""
        try:
            import time
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            cutoff = int(time.time()) - (hours * 3600)

            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE outcome IS NULL OR outcome = 'open'
            """)
            open_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE entry_timestamp > ?
            """, (cutoff,))
            recent_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT outcome, COUNT(*)
                FROM position_lifecycle
                WHERE outcome IS NOT NULL AND outcome != 'open'
                GROUP BY outcome
            """)
            outcomes = dict(cursor.fetchall())

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "open_positions": open_count,
                    "positions_last_hours": recent_count,
                    "hours": hours,
                    "outcomes": outcomes,
                    "source": "live_query"
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class SmartSystemStatusTool(Tool):
    """
    Get system status - INSTANT from knowledge base.
    No shell commands needed for basic status checks.
    """

    name = "system_status"
    description = """Get system status INSTANTLY from knowledge base.
    CPU, memory, disk, services - all cached and ready.
    'Is bot running?' answered in <1ms."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Natural language question like 'is the bot running?'"
            },
            "service": {
                "type": "string",
                "description": "Specific service to check: bot, webhook, monitor, pipeline, hedgehog"
            }
        },
        "required": []
    }

    async def execute(
        self,
        question: Optional[str] = None,
        service: Optional[str] = None
    ) -> ToolResult:
        """Get system status - knowledge base first."""

        kb = _get_kb()
        if kb:
            # Natural language question
            if question:
                result = kb.answer(question)
                if result.confidence > 0.5:
                    return ToolResult(
                        success=True,
                        data={
                            "answer": result.answer,
                            "source": result.source,
                            "query_time_ms": result.query_time_ms
                        }
                    )

            # Service status
            if service:
                result = kb.get_service_status(service)
                return ToolResult(
                    success=True,
                    data={
                        "service": result.answer,
                        "source": result.source,
                        "query_time_ms": result.query_time_ms
                    }
                )

            # Full system health
            health = kb.get_system_health()
            services = kb.get_service_status('all')

            return ToolResult(
                success=True,
                data={
                    "health": health.answer,
                    "services": services.answer,
                    "source": "knowledge_base",
                    "query_time_ms": health.query_time_ms
                }
            )

        # Fallback to live
        return await self._live_status()

    async def _live_status(self) -> ToolResult:
        """Live system status check"""
        import subprocess

        try:
            # CPU/Memory via top
            result = subprocess.run(
                ['top', '-l', '1', '-n', '0'],
                capture_output=True,
                text=True,
                timeout=10
            )

            cpu = 0
            memory = 0
            for line in result.stdout.split('\n'):
                if 'CPU usage' in line:
                    import re
                    match = re.search(r'([\d.]+)%\s+user', line)
                    if match:
                        cpu = float(match.group(1))
                if 'PhysMem' in line:
                    pass  # Parse memory if needed

            return ToolResult(
                success=True,
                data={
                    "cpu_percent": cpu,
                    "source": "live_query"
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class SmartQuestionTool(Tool):
    """
    Answer ANY question about SoulWinners system.
    This is Hedgehog's brain - it knows everything.
    """

    name = "ask_system"
    description = """Answer any question about the SoulWinners system.
    This is Hedgehog's brain - instant answers about:
    - Wallets: 'how many insider wallets?'
    - Positions: 'what's the total PnL?'
    - Services: 'is the bot running?'
    - Database: 'what tables exist?'
    - Code: 'where is the trading logic?'
    - Config: 'what's the min win rate threshold?'
    """

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Any question about the system"
            }
        },
        "required": ["question"]
    }

    async def execute(self, question: str) -> ToolResult:
        """Answer any system question."""

        kb = _get_kb()
        if not kb:
            return ToolResult(
                success=False,
                error="Knowledge base not initialized. Run: python -m hedgehog init"
            )

        result = kb.answer(question)

        if result.confidence > 0.5:
            return ToolResult(
                success=True,
                data={
                    "answer": result.answer,
                    "confidence": result.confidence,
                    "source": result.source,
                    "cached": result.cached,
                    "query_time_ms": result.query_time_ms
                }
            )
        else:
            # Low confidence - try to help
            return ToolResult(
                success=True,
                data={
                    "answer": result.answer,
                    "confidence": result.confidence,
                    "source": result.source,
                    "note": "Low confidence - may need live query for accurate answer"
                }
            )


class SmartPnLTool(Tool):
    """Get PnL stats instantly from knowledge base."""

    name = "pnl_stats"
    description = """Get PnL statistics. Instant from knowledge base.
    Total PnL, recent trades, performance metrics."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self) -> ToolResult:
        """Get PnL stats."""

        kb = _get_kb()
        if kb:
            pnl = kb.get_total_pnl()
            trades = kb.get_recent_trades_count()
            positions = kb.get_position_count('all')

            return ToolResult(
                success=True,
                data={
                    "total_pnl_sol": pnl.answer,
                    "recent_trades_24h": trades.answer,
                    "positions": positions.answer,
                    "source": "knowledge_base",
                    "query_time_ms": pnl.query_time_ms
                }
            )

        return ToolResult(
            success=False,
            error="Knowledge base not initialized"
        )


# Export smart tools to replace the originals
SMART_TOOLS = [
    SmartSchemaDiscoveryTool,
    SmartWalletStatsTool,
    SmartPositionStatsTool,
    SmartSystemStatusTool,
    SmartQuestionTool,
    SmartPnLTool,
]


def get_smart_tools() -> List[Tool]:
    """Get all smart tools instances"""
    return [tool() for tool in SMART_TOOLS]
