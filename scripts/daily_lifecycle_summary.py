#!/usr/bin/env python3
"""
Daily Lifecycle Tracking Summary

Sends admin a daily summary of lifecycle tracking progress.
One clean message per day - no spam!

Cron schedule (daily at 9 AM):
    0 9 * * * cd /root/Soulwinners && ./venv/bin/python3 scripts/daily_lifecycle_summary.py >> logs/daily_summary.log 2>&1

Usage:
    python scripts/daily_lifecycle_summary.py [--test]
"""
import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from telegram import Bot
from config.settings import BOT_TOKEN, ADMIN_USER_IDS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def send_daily_summary(test_mode: bool = False):
    """Generate and send daily lifecycle summary."""
    logger.info("=" * 60)
    logger.info("DAILY LIFECYCLE SUMMARY")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Time ranges
        now = int(time.time())
        last_7d = now - (7 * 86400)

        # === POSITIONS CREATED (Last 24h) ===
        cursor.execute("""
            SELECT COUNT(*) FROM position_lifecycle
            WHERE created_at > datetime('now', '-1 day')
        """)
        new_positions_24h = cursor.fetchone()[0] or 0

        # === POSITIONS LABELED (Last 24h) ===
        cursor.execute("""
            SELECT
                outcome,
                COUNT(*) as count
            FROM position_lifecycle
            WHERE outcome_labeled_at > datetime('now', '-1 day')
            AND outcome IS NOT NULL AND outcome != 'open'
            GROUP BY outcome
        """)
        labeled_24h = cursor.fetchall()

        # === OPEN POSITIONS ===
        cursor.execute("""
            SELECT COUNT(*) FROM position_lifecycle
            WHERE outcome IS NULL OR outcome = 'open'
        """)
        open_positions = cursor.fetchone()[0] or 0

        # === TOTAL DATASET ===
        cursor.execute("""
            SELECT
                outcome,
                COUNT(*) as count
            FROM position_lifecycle
            WHERE outcome IS NOT NULL AND outcome != 'open'
            GROUP BY outcome
        """)
        total_labeled = cursor.fetchall()

        # Calculate totals
        total_count = sum(count for _, count in total_labeled)
        outcome_dict = {outcome: count for outcome, count in total_labeled}

        # === TOP PERFORMING WALLETS (by importance score) ===
        cursor.execute("""
            SELECT
                wgp.wallet_address,
                wgp.tier,
                COALESCE(wgp.importance_score, 0) as importance,
                COUNT(pl.id) as positions_7d
            FROM wallet_global_pool wgp
            LEFT JOIN position_lifecycle pl ON pl.wallet_address = wgp.wallet_address
                AND pl.entry_timestamp > ?
            WHERE wgp.importance_score IS NOT NULL
            GROUP BY wgp.wallet_address
            ORDER BY wgp.importance_score DESC
            LIMIT 5
        """, (last_7d,))
        top_wallets = cursor.fetchall()

        conn.close()

        # === BUILD MESSAGE ===
        message = f"📊 *DAILY LIFECYCLE REPORT*\n"
        message += f"_{datetime.now().strftime('%B %d, %Y')}_\n\n"

        # New positions
        message += f"🆕 *New Positions (24h):* {new_positions_24h}\n"

        # Newly labeled
        if labeled_24h:
            message += f"\n🏷️ *Labeled (24h):*\n"
            for outcome, count in labeled_24h:
                emoji = "🚀" if outcome == "runner" else "💀" if outcome == "rug" else "📊"
                message += f"  {emoji} {outcome.capitalize()}: {count}\n"
        else:
            message += f"\n🏷️ *Labeled (24h):* 0 (positions still maturing)\n"

        # Open positions
        message += f"\n⏳ *Open Positions:* {open_positions}\n"
        message += f"   _(Being tracked for 48h)_\n"

        # Total dataset
        if total_count > 0:
            message += f"\n📈 *Total Training Data:*\n"
            message += f"  Total: {total_count:,} labeled events\n"

            for outcome in ['runner', 'rug', 'sideways']:
                count = outcome_dict.get(outcome, 0)
                pct = (count / total_count * 100) if total_count > 0 else 0
                emoji = "🚀" if outcome == "runner" else "💀" if outcome == "rug" else "📊"
                message += f"  {emoji} {outcome.capitalize()}: {count:,} ({pct:.1f}%)\n"
        else:
            message += f"\n📈 *Total Training Data:* 0 (just started)\n"

        # Top wallets
        if top_wallets:
            message += f"\n🏆 *Top Wallets (by Importance):*\n"
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            for i, (wallet, tier, score, positions) in enumerate(top_wallets[:5]):
                medal = medals[i] if i < len(medals) else f"{i+1}."
                message += f"{medal} `{wallet[:6]}...{wallet[-4:]}` ({tier or 'N/A'})\n"
                message += f"   Score: {score:+.1f} | {positions} positions (7d)\n"

        # Next milestone
        if total_count < 100:
            message += f"\n🎯 *Next:* {100 - total_count} more to 100 events"
        elif total_count < 500:
            message += f"\n🎯 *Next:* {500 - total_count} more to 500 events"
        elif total_count < 1000:
            message += f"\n🎯 *Next:* {1000 - total_count} more to 1K events"
        elif total_count < 3000:
            message += f"\n🎯 *Next:* {3000 - total_count} more to 3K events (ML ready!)"
        else:
            message += f"\n✅ *Dataset ready for production ML training!*"

        # Test mode - just print
        if test_mode:
            print("\n" + "=" * 60)
            print("TEST MODE - Message preview:")
            print("=" * 60)
            print(message.replace('*', '').replace('_', ''))
            print("=" * 60)
            return

        # Send to admins
        bot = Bot(token=BOT_TOKEN)

        for admin_id in ADMIN_USER_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"✅ Sent daily summary to admin {admin_id}")
            except Exception as e:
                logger.error(f"Failed to send to admin {admin_id}: {e}")

        logger.info("Daily summary sent successfully")

    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise

    finally:
        try:
            conn.close()
        except:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Send daily lifecycle tracking summary to admin"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode - print message instead of sending"
    )

    args = parser.parse_args()
    asyncio.run(send_daily_summary(test_mode=args.test))


if __name__ == "__main__":
    main()
