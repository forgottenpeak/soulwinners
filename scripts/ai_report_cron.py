#!/usr/bin/env python3
"""
AI Strategy Report Cron Job
Generates and sends AI-powered trading reports to users

Schedule: Every 3 days
Cron example:
0 9 */3 * * cd /path/to/Soulwinners && python scripts/ai_report_cron.py

Environment variables required:
- OPENROUTER_API_KEY: OpenRouter API key for AI
- TELEGRAM_BOT_TOKEN: Telegram bot token for sending reports
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from trader.ai_advisor import generate_report, send_report_to_user

# Default user to send reports to
DEFAULT_USER_ID = 1153491543


async def main():
    print("=" * 50)
    print(f"AI STRATEGY REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # Check required env vars
    if not os.getenv('OPENROUTER_API_KEY'):
        print("ERROR: OPENROUTER_API_KEY not set")
        print("Set it with: export OPENROUTER_API_KEY='your-key-here'")
        sys.exit(1)

    if not os.getenv('TELEGRAM_BOT_TOKEN'):
        print("ERROR: TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    user_id = DEFAULT_USER_ID

    print(f"\nGenerating report for user {user_id}...")
    print("Analyzing last 3 days of trading...")

    # Generate report
    report = generate_report(user_id, days=3)

    if not report.get('success'):
        print(f"\nReport generation failed: {report.get('error')}")
        sys.exit(1)

    # Print stats
    stats = report.get('stats', {})
    print(f"\n📊 Trading Statistics:")
    print(f"  Total trades: {stats.get('total_trades', 0)}")
    print(f"  Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}")
    print(f"  Win rate: {stats.get('win_rate', 0):.1f}%")
    print(f"  P&L: {stats.get('total_pnl_sol', 0):+.4f} SOL")

    # Print suggestions
    suggestions = report.get('suggestions', {})
    print(f"\n💡 AI Suggestions:")
    print(f"  Buy amount: {suggestions.get('buy_amount_percent', 70)}%")
    print(f"  Take profit 1: +{suggestions.get('take_profit_1', 50)}%")
    print(f"  Take profit 2: +{suggestions.get('take_profit_2', 100)}%")
    print(f"  Stop loss: {suggestions.get('stop_loss', -20)}%")

    # Send to user
    print(f"\n📤 Sending report to user {user_id}...")

    result = await send_report_to_user(user_id, report)

    if result.get('success'):
        print("✅ Report sent successfully!")
    else:
        print(f"❌ Failed to send report: {result.get('error')}")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
