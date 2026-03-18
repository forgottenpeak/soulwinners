"""
Trading Tools for Hedgehog

Tools for querying trading data, positions, and wallet performance.
Read-only tools that provide insights into trading activity.
"""
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from .base import Tool, ToolResult, SafetyLevel


class GetPositionsTool(Tool):
    """Get current open positions from lifecycle tracking."""

    name = "get_positions"
    description = """Get open positions from the lifecycle tracking system.
    Returns positions with entry data, current status, and performance."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "wallet_type": {
                "type": "string",
                "enum": ["qualified", "insider", "all"],
                "description": "Filter by wallet type",
                "default": "all"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum positions to return (default 20)",
                "default": 20
            },
            "sort_by": {
                "type": "string",
                "enum": ["entry_time", "buy_amount", "mc_multiplier"],
                "description": "Sort order",
                "default": "entry_time"
            }
        },
        "required": []
    }

    async def execute(
        self,
        wallet_type: str = "all",
        limit: int = 20,
        sort_by: str = "entry_time"
    ) -> ToolResult:
        """Get open positions."""
        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            # Build query
            where_clause = "WHERE (outcome IS NULL OR outcome = 'open')"
            if wallet_type != "all":
                where_clause += f" AND wallet_type = '{wallet_type}'"

            order_map = {
                "entry_time": "entry_timestamp DESC",
                "buy_amount": "buy_sol_amount DESC",
                "mc_multiplier": "peak_mc_multiplier DESC",
            }
            order_by = order_map.get(sort_by, "entry_timestamp DESC")

            cursor.execute(f"""
                SELECT
                    id, wallet_address, token_address, token_symbol,
                    entry_timestamp, entry_mc, buy_sol_amount,
                    peak_mc, peak_mc_multiplier, wallet_type, wallet_tier
                FROM position_lifecycle
                {where_clause}
                ORDER BY {order_by}
                LIMIT ?
            """, (limit,))

            positions = []
            for row in cursor.fetchall():
                entry_time = datetime.fromtimestamp(row[4]) if row[4] else None
                positions.append({
                    "id": row[0],
                    "wallet": row[1][:12] + "..." if row[1] else None,
                    "token": row[2][:12] + "..." if row[2] else None,
                    "symbol": row[3],
                    "entry_time": entry_time.isoformat() if entry_time else None,
                    "entry_mc": row[5],
                    "buy_sol": row[6],
                    "peak_mc": row[7],
                    "peak_multiplier": round(row[8] or 1, 2),
                    "wallet_type": row[9],
                    "tier": row[10],
                })

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "positions": positions,
                    "count": len(positions),
                    "filter": wallet_type,
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetWalletPerformanceTool(Tool):
    """Get performance metrics for a specific wallet."""

    name = "get_wallet_performance"
    description = """Get detailed performance metrics for a wallet.
    Returns win rate, ROI, trade history, and tier information."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "wallet_address": {
                "type": "string",
                "description": "Wallet address to look up"
            }
        },
        "required": ["wallet_address"]
    }

    async def execute(self, wallet_address: str) -> ToolResult:
        """Get wallet performance."""
        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            # Get from qualified_wallets
            cursor.execute("""
                SELECT
                    wallet_address, tier, win_rate, roi_pct, total_trades,
                    x10_ratio, x20_ratio, priority_score, cluster_name
                FROM qualified_wallets
                WHERE wallet_address = ?
            """, (wallet_address,))

            row = cursor.fetchone()
            if not row:
                conn.close()
                return ToolResult(
                    success=False,
                    error=f"Wallet not found in qualified pool: {wallet_address[:16]}..."
                )

            wallet_data = {
                "address": row[0],
                "tier": row[1],
                "win_rate": round(row[2] or 0, 2),
                "roi_pct": round(row[3] or 0, 2),
                "total_trades": row[4],
                "x10_ratio": round(row[5] or 0, 4),
                "x20_ratio": round(row[6] or 0, 4),
                "priority_score": round(row[7] or 0, 4),
                "cluster": row[8],
            }

            # Get recent positions
            cursor.execute("""
                SELECT
                    token_symbol, outcome, buy_sol_amount, peak_mc_multiplier
                FROM position_lifecycle
                WHERE wallet_address = ?
                ORDER BY entry_timestamp DESC
                LIMIT 5
            """, (wallet_address,))

            recent_positions = [
                {
                    "symbol": row[0],
                    "outcome": row[1],
                    "sol": row[2],
                    "peak_x": round(row[3] or 1, 2),
                }
                for row in cursor.fetchall()
            ]

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "wallet": wallet_data,
                    "recent_positions": recent_positions,
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetTokenInfoTool(Tool):
    """Get token information from DexScreener."""

    name = "get_token_info"
    description = """Get current token information from DexScreener.
    Returns price, market cap, liquidity, and volume data."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "token_address": {
                "type": "string",
                "description": "Solana token address"
            }
        },
        "required": ["token_address"]
    }

    async def execute(self, token_address: str) -> ToolResult:
        """Get token info from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            error=f"DexScreener API error: {response.status}"
                        )

                    data = await response.json()

            if not data or len(data) == 0:
                return ToolResult(
                    success=False,
                    error="Token not found on DexScreener"
                )

            pair = data[0]
            token_info = {
                "address": token_address,
                "symbol": pair.get("baseToken", {}).get("symbol", "???"),
                "name": pair.get("baseToken", {}).get("name", "Unknown"),
                "price_usd": float(pair.get("priceUsd", 0) or 0),
                "market_cap": float(pair.get("marketCap", 0) or 0),
                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                "volume_5m": float(pair.get("volume", {}).get("m5", 0) or 0),
                "volume_1h": float(pair.get("volume", {}).get("h1", 0) or 0),
                "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
                "price_change_5m": float(pair.get("priceChange", {}).get("m5", 0) or 0),
                "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0) or 0),
                "dex": pair.get("dexId", "unknown"),
                "pair_created_at": pair.get("pairCreatedAt"),
            }

            return ToolResult(success=True, data=token_info)

        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetTradeHistoryTool(Tool):
    """Get recent trade history from alerts."""

    name = "get_trade_history"
    description = """Get recent trade history from the alerts table.
    Shows buy/sell alerts sent to Telegram."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "hours": {
                "type": "integer",
                "description": "Look back N hours (default 24)",
                "default": 24
            },
            "alert_type": {
                "type": "string",
                "enum": ["buy", "sell", "all"],
                "description": "Filter by alert type",
                "default": "all"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum alerts to return",
                "default": 50
            }
        },
        "required": []
    }

    async def execute(
        self,
        hours: int = 24,
        alert_type: str = "all",
        limit: int = 50
    ) -> ToolResult:
        """Get trade history."""
        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            cutoff = datetime.now().timestamp() - (hours * 3600)
            cutoff_str = datetime.fromtimestamp(cutoff).isoformat()

            where_clause = f"WHERE sent_at > '{cutoff_str}'"
            if alert_type != "all":
                where_clause += f" AND alert_type = '{alert_type}'"

            cursor.execute(f"""
                SELECT
                    wallet_address, token_symbol, token_name,
                    alert_type, tier, strategy, sent_at
                FROM alerts
                {where_clause}
                ORDER BY sent_at DESC
                LIMIT ?
            """, (limit,))

            alerts = [
                {
                    "wallet": row[0][:12] + "..." if row[0] else None,
                    "symbol": row[1],
                    "name": row[2],
                    "type": row[3],
                    "tier": row[4],
                    "strategy": row[5],
                    "time": row[6],
                }
                for row in cursor.fetchall()
            ]

            # Get summary stats
            cursor.execute(f"""
                SELECT alert_type, COUNT(*)
                FROM alerts
                {where_clause.replace("WHERE", "")}
                GROUP BY alert_type
            """)
            type_counts = dict(cursor.fetchall())

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "alerts": alerts,
                    "count": len(alerts),
                    "hours": hours,
                    "type_counts": type_counts,
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetMarketOverviewTool(Tool):
    """Get Solana meme coin market overview."""

    name = "get_market_overview"
    description = """Get overview of Solana meme coin market.
    Returns trending tokens, volume stats, and market sentiment."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self) -> ToolResult:
        """Get market overview."""
        try:
            # Get trending from DexScreener
            url = "https://api.dexscreener.com/token-boosts/top/v1"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        trending = await response.json()
                    else:
                        trending = []

            # Filter Solana tokens
            sol_trending = [
                {
                    "symbol": t.get("tokenAddress", "")[:8],
                    "chain": t.get("chainId"),
                    "amount": t.get("amount"),
                }
                for t in (trending or [])
                if t.get("chainId") == "solana"
            ][:10]

            # Get internal stats
            from database import get_connection
            conn = get_connection()
            cursor = conn.cursor()

            # Positions opened today
            today_start = int(time.time()) - (int(time.time()) % 86400)
            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE entry_timestamp > ?
            """, (today_start,))
            positions_today = cursor.fetchone()[0]

            # Active wallets today
            cursor.execute("""
                SELECT COUNT(DISTINCT wallet_address) FROM position_lifecycle
                WHERE entry_timestamp > ?
            """, (today_start,))
            active_wallets = cursor.fetchone()[0]

            conn.close()

            return ToolResult(
                success=True,
                data={
                    "timestamp": datetime.now().isoformat(),
                    "trending_solana": sol_trending,
                    "positions_today": positions_today,
                    "active_wallets_today": active_wallets,
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
