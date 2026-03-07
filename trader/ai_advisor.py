"""
Kimi AI Strategy Advisor
Analyzes trading performance and provides AI-powered recommendations
"""

import os
import json
import sqlite3
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Configuration
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
MODEL = "anthropic/claude-3.5-sonnet"
HTTP_REFERER = "https://soulwinners.app"

# Database paths
OPENCLAW_DB = Path(__file__).parent.parent / "data" / "openclaw.db"
SOULWINNERS_DB = Path(__file__).parent.parent / "data" / "soulwinners.db"


def init_ai_tables():
    """Create ai_reports table if not exists."""
    conn = sqlite3.connect(SOULWINNERS_DB)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            report_text TEXT,
            suggestions_json TEXT,
            trade_stats_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_reports_user ON ai_reports(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_reports_created ON ai_reports(created_at DESC)")

    conn.commit()
    conn.close()
    logger.info("AI reports table initialized")


@dataclass
class TradeStats:
    """Trading statistics for analysis."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl_sol: float = 0.0
    avg_hold_time_seconds: float = 0.0
    max_win_sol: float = 0.0
    max_win_token: str = ""
    max_loss_sol: float = 0.0
    max_loss_token: str = ""
    trades: List[Dict] = None

    def __post_init__(self):
        if self.trades is None:
            self.trades = []


def analyze_performance(user_id: int, days: int = 3) -> TradeStats:
    """
    Analyze user's trading performance over the last N days.

    Args:
        user_id: Telegram user ID
        days: Number of days to analyze (default 3)

    Returns:
        TradeStats object with performance metrics
    """
    stats = TradeStats()

    # Query trade history from OpenClaw database
    if not OPENCLAW_DB.exists():
        logger.warning(f"OpenClaw database not found at {OPENCLAW_DB}")
        return stats

    conn = sqlite3.connect(OPENCLAW_DB)
    cursor = conn.cursor()

    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

    # Get trades from trade_history
    cursor.execute("""
        SELECT
            id, position_id, trade_type, token_mint, token_symbol,
            sol_amount, token_amount, price, pnl_sol, pnl_percent,
            signature, timestamp
        FROM trade_history
        WHERE timestamp >= ?
        AND trade_type != 'entry'
        ORDER BY timestamp DESC
    """, (cutoff_date,))

    trades = cursor.fetchall()
    conn.close()

    if not trades:
        return stats

    # Process trades
    for trade in trades:
        trade_data = {
            'id': trade[0],
            'position_id': trade[1],
            'trade_type': trade[2],
            'token_mint': trade[3],
            'token_symbol': trade[4],
            'sol_amount': trade[5],
            'token_amount': trade[6],
            'price': trade[7],
            'pnl_sol': trade[8] or 0,
            'pnl_percent': trade[9] or 0,
            'signature': trade[10],
            'timestamp': trade[11],
        }
        stats.trades.append(trade_data)

        pnl = trade_data['pnl_sol']
        stats.total_pnl_sol += pnl

        if pnl > 0:
            stats.wins += 1
            if pnl > stats.max_win_sol:
                stats.max_win_sol = pnl
                stats.max_win_token = trade_data['token_symbol']
        else:
            stats.losses += 1
            if pnl < stats.max_loss_sol:
                stats.max_loss_sol = pnl
                stats.max_loss_token = trade_data['token_symbol']

    stats.total_trades = len(trades)
    stats.win_rate = (stats.wins / stats.total_trades * 100) if stats.total_trades > 0 else 0

    # Calculate average hold time from positions
    conn = sqlite3.connect(OPENCLAW_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT AVG(
            CAST((julianday(last_update) - julianday(entry_time)) * 86400 AS INTEGER)
        ) as avg_hold_seconds
        FROM positions
        WHERE status IN ('closed', 'stopped')
        AND entry_time >= ?
    """, (cutoff_date,))

    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        stats.avg_hold_time_seconds = result[0]

    return stats


def get_current_strategy(user_id: int) -> Dict:
    """
    Get user's current strategy settings.
    For now, returns default OpenClaw strategy config.
    """
    # Default strategy from StrategyConfig
    return {
        'buy_amount_percent': 70.0,  # 70% of balance
        'take_profit_1': 50.0,  # +50%
        'take_profit_2': 100.0,  # +100%
        'stop_loss': -20.0,  # -20%
        'max_positions': 3,
        'min_liquidity': 50000,
        'min_bes': 1000,
    }


def generate_report(user_id: int, days: int = 3) -> Dict:
    """
    Generate a comprehensive AI-powered performance report.

    Args:
        user_id: Telegram user ID
        days: Number of days to analyze

    Returns:
        Dict with report text and structured suggestions
    """
    if not OPENROUTER_API_KEY:
        return {
            "success": False,
            "error": "OPENROUTER_API_KEY not configured. Set it in environment variables."
        }

    # Analyze performance
    stats = analyze_performance(user_id, days)
    strategy = get_current_strategy(user_id)

    # Format hold time
    if stats.avg_hold_time_seconds > 3600:
        hold_time_str = f"{stats.avg_hold_time_seconds / 3600:.1f} hours"
    elif stats.avg_hold_time_seconds > 60:
        hold_time_str = f"{stats.avg_hold_time_seconds / 60:.1f} minutes"
    else:
        hold_time_str = f"{stats.avg_hold_time_seconds:.0f} seconds"

    # Build AI prompt
    prompt = f"""You are a Solana trading strategy advisor. Analyze this user's trading performance
from the last {days} days and provide actionable recommendations.

Trading Data:
- Total trades: {stats.total_trades}
- Wins: {stats.wins} | Losses: {stats.losses}
- Win rate: {stats.win_rate:.1f}%
- Total profit/loss: {stats.total_pnl_sol:+.4f} SOL
- Average hold time: {hold_time_str}
- Biggest win: {stats.max_win_sol:+.4f} SOL on {stats.max_win_token or 'N/A'}
- Biggest loss: {stats.max_loss_sol:+.4f} SOL on {stats.max_loss_token or 'N/A'}

Current Strategy:
- Buy amount: {strategy['buy_amount_percent']}% of balance
- Take profit 1: +{strategy['take_profit_1']}%
- Take profit 2: +{strategy['take_profit_2']}%
- Stop loss: {strategy['stop_loss']}%
- Max positions: {strategy['max_positions']}

Provide:
1. What went wrong and why (be specific about patterns you see)
2. Specific strategy improvements with reasoning
3. Recommended new parameters (buy amount %, TP1, TP2, SL)
4. Risk warnings for current market conditions

Format as a friendly report for a trader. Use emojis sparingly. Be concise but actionable."""

    try:
        # Call OpenRouter API
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": HTTP_REFERER,
            "Content-Type": "application/json",
        }

        payload = {
            "model": MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.7,
        }

        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=60
        )

        if response.status_code != 200:
            logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            return {
                "success": False,
                "error": f"API error: {response.status_code}"
            }

        data = response.json()
        report_text = data['choices'][0]['message']['content']

        # Extract suggested parameters (simple parsing)
        suggestions = _extract_suggestions(report_text, strategy)

        # Save report to database
        _save_report(user_id, report_text, suggestions, stats)

        return {
            "success": True,
            "report": report_text,
            "suggestions": suggestions,
            "stats": {
                "total_trades": stats.total_trades,
                "wins": stats.wins,
                "losses": stats.losses,
                "win_rate": stats.win_rate,
                "total_pnl_sol": stats.total_pnl_sol,
            }
        }

    except requests.exceptions.Timeout:
        logger.error("OpenRouter API timeout")
        return {"success": False, "error": "API timeout"}
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return {"success": False, "error": str(e)}


def _extract_suggestions(report_text: str, current_strategy: Dict) -> Dict:
    """
    Extract structured suggestions from AI report.
    Simple pattern matching - can be enhanced with another AI call.
    """
    suggestions = {
        "buy_amount_percent": current_strategy['buy_amount_percent'],
        "take_profit_1": current_strategy['take_profit_1'],
        "take_profit_2": current_strategy['take_profit_2'],
        "stop_loss": current_strategy['stop_loss'],
        "raw_recommendations": [],
    }

    # Extract any percentage recommendations from text
    import re

    # Look for stop loss recommendations
    sl_matches = re.findall(r'stop.?loss[:\s]+(-?\d+(?:\.\d+)?)\s*%', report_text.lower())
    if sl_matches:
        suggestions['stop_loss'] = float(sl_matches[0])
        if suggestions['stop_loss'] > 0:
            suggestions['stop_loss'] = -suggestions['stop_loss']

    # Look for take profit recommendations
    tp_matches = re.findall(r'take.?profit[:\s]+\+?(\d+(?:\.\d+)?)\s*%', report_text.lower())
    if len(tp_matches) >= 1:
        suggestions['take_profit_1'] = float(tp_matches[0])
    if len(tp_matches) >= 2:
        suggestions['take_profit_2'] = float(tp_matches[1])

    # Look for position size recommendations
    pos_matches = re.findall(r'(\d+(?:\.\d+)?)\s*%\s*(?:of\s+)?(?:balance|position)', report_text.lower())
    if pos_matches:
        suggestions['buy_amount_percent'] = float(pos_matches[0])

    return suggestions


def _save_report(user_id: int, report_text: str, suggestions: Dict, stats: TradeStats):
    """Save report to database."""
    conn = sqlite3.connect(SOULWINNERS_DB)
    cursor = conn.cursor()

    stats_json = json.dumps({
        'total_trades': stats.total_trades,
        'wins': stats.wins,
        'losses': stats.losses,
        'win_rate': stats.win_rate,
        'total_pnl_sol': stats.total_pnl_sol,
        'avg_hold_time_seconds': stats.avg_hold_time_seconds,
        'max_win_sol': stats.max_win_sol,
        'max_win_token': stats.max_win_token,
        'max_loss_sol': stats.max_loss_sol,
        'max_loss_token': stats.max_loss_token,
    })

    cursor.execute("""
        INSERT INTO ai_reports (user_id, report_text, suggestions_json, trade_stats_json)
        VALUES (?, ?, ?, ?)
    """, (user_id, report_text, json.dumps(suggestions), stats_json))

    conn.commit()
    conn.close()
    logger.info(f"Saved AI report for user {user_id}")


def suggest_improvements(user_id: int) -> Dict:
    """
    Get the latest AI suggestions for a user.

    Returns:
        Dict with suggested parameter changes
    """
    conn = sqlite3.connect(SOULWINNERS_DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT suggestions_json, created_at
        FROM ai_reports
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"success": False, "error": "No reports found. Generate a report first."}

    return {
        "success": True,
        "suggestions": json.loads(row[0]),
        "generated_at": row[1]
    }


async def send_report_to_user(user_id: int, report: Dict, bot_token: str = None) -> Dict:
    """
    Send the AI report to user via Telegram DM.

    Args:
        user_id: Telegram user ID (chat_id for DM)
        report: Report dict from generate_report()
        bot_token: Telegram bot token (uses env var if not provided)

    Returns:
        Dict with success status
    """
    if not report.get('success'):
        return {"success": False, "error": report.get('error', 'Invalid report')}

    token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        return {"success": False, "error": "TELEGRAM_BOT_TOKEN not configured"}

    bot = Bot(token=token)

    # Format message
    stats = report.get('stats', {})
    report_text = report.get('report', '')

    header = f"""📊 **AI TRADING REPORT**
━━━━━━━━━━━━━━━━━━━━━

📈 **Last 3 Days Summary:**
├ Trades: {stats.get('total_trades', 0)}
├ Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}
├ Win Rate: {stats.get('win_rate', 0):.1f}%
└ P&L: {stats.get('total_pnl_sol', 0):+.4f} SOL

━━━━━━━━━━━━━━━━━━━━━
🤖 **AI Analysis:**

"""

    full_message = header + report_text

    # Telegram has a 4096 char limit, split if needed
    try:
        if len(full_message) <= 4096:
            await bot.send_message(
                chat_id=user_id,
                text=full_message,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # Send header first
            await bot.send_message(
                chat_id=user_id,
                text=header,
                parse_mode=ParseMode.MARKDOWN
            )
            # Split report text into chunks
            chunks = [report_text[i:i+4000] for i in range(0, len(report_text), 4000)]
            for chunk in chunks:
                await bot.send_message(
                    chat_id=user_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN
                )

        logger.info(f"Sent AI report to user {user_id}")
        return {"success": True, "message": "Report sent successfully"}

    except Exception as e:
        logger.error(f"Failed to send report to user {user_id}: {e}")
        return {"success": False, "error": str(e)}


def get_report_history(user_id: int, limit: int = 5) -> List[Dict]:
    """
    Get user's AI report history.

    Args:
        user_id: Telegram user ID
        limit: Max reports to return

    Returns:
        List of report summaries
    """
    conn = sqlite3.connect(SOULWINNERS_DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, trade_stats_json, created_at
        FROM ai_reports
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))

    rows = cursor.fetchall()
    conn.close()

    reports = []
    for row in rows:
        stats = json.loads(row[1]) if row[1] else {}
        reports.append({
            "id": row[0],
            "stats": stats,
            "created_at": row[2]
        })

    return reports


# Initialize tables on import
init_ai_tables()
