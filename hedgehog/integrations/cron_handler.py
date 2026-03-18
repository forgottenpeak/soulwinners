"""
Cron Handler for Hedgehog - Scheduled Autonomous Tasks

Run via cron for periodic tasks without continuous loops.

Cron Examples:
    # Process events every 5 minutes
    */5 * * * * cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler events

    # Health check and self-heal every 5 minutes
    */5 * * * * cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler heal

    # Daily report at midnight
    0 0 * * * cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler report

    # Cleanup old data weekly
    0 3 * * 0 cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler cleanup
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("hedgehog.cron")


async def run_events():
    """Process pending events."""
    from hedgehog.brain import get_brain

    brain = get_brain()

    # Detect new events
    events = await brain.events.detect_all()
    logger.info(f"Detected {len(events)} new events")

    # Get pending
    pending = brain.events.get_pending_events(limit=10)

    for event in pending:
        try:
            brain.events.mark_processed(event.id)
            logger.info(f"Processed: {event.event_type.value}")
        except Exception as e:
            logger.error(f"Error: {e}")

    brain.events.clear_processed()


async def run_heal():
    """Self-heal system issues."""
    from hedgehog.brain import get_brain

    brain = get_brain()

    # Check health
    health = await brain.health.run_full_health_check()

    if health["overall"] != "healthy":
        logger.warning(f"System unhealthy: {health['overall']}")

        # Self-heal
        actions = await brain.health.self_heal()

        if actions:
            logger.info(f"Self-healing: {actions}")

            # Notify admin
            await brain.send_admin_notification(
                f"⚠️ System {health['overall']}\n\n" +
                "\n".join(f"• {a}" for a in actions),
                level="warning",
            )
    else:
        logger.info("System healthy")


async def run_report():
    """Send daily report."""
    from hedgehog.run_hedgehog import run_daily_report

    await run_daily_report()
    logger.info("Daily report sent")


async def run_cleanup():
    """Clean up old data."""
    from hedgehog.brain import get_brain

    brain = get_brain()

    # Clean up old memory entries
    deleted = brain.memory.cleanup_old_data(days=90)
    logger.info(f"Cleaned up {deleted} old entries")

    # Clean up action log (keep last 1000)
    if len(brain.action_logger.actions) > 1000:
        brain.action_logger.actions = brain.action_logger.actions[-1000:]
        brain.action_logger._save()
        logger.info("Trimmed action log to 1000 entries")


async def run_monitor():
    """Monitor logs for errors (lightweight)."""
    from hedgehog.brain import get_brain

    brain = get_brain()

    # Check for high error rate
    error_event = await brain.events.check_error_rate()

    if error_event:
        logger.warning(f"High error rate detected: {error_event.data}")

        # Notify admin
        await brain.send_admin_notification(
            f"🚨 High error rate detected!\n\n"
            f"Errors in last hour: {error_event.data.get('error_count', 0)}",
            level="error",
        )


def main():
    """Main entry point for cron."""
    if len(sys.argv) < 2:
        print("Usage: python -m hedgehog.integrations.cron_handler <task>")
        print("Tasks: events, heal, report, cleanup, monitor")
        sys.exit(1)

    task = sys.argv[1].lower()

    tasks = {
        "events": run_events,
        "heal": run_heal,
        "report": run_report,
        "cleanup": run_cleanup,
        "monitor": run_monitor,
    }

    if task not in tasks:
        print(f"Unknown task: {task}")
        print(f"Available: {', '.join(tasks.keys())}")
        sys.exit(1)

    logger.info(f"Running cron task: {task}")

    try:
        asyncio.run(tasks[task]())
    except Exception as e:
        logger.error(f"Cron task failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
