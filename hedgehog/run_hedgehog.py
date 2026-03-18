#!/usr/bin/env python3
"""
Hedgehog Runner - Full Autonomous AI Brain

Usage:
    # Run Telegram bot with proactive monitoring (main mode)
    python -m hedgehog bot

    # Run autonomous monitoring only (no Telegram, checks every 5 min)
    python -m hedgehog monitor

    # Run event processor (cron mode)
    python -m hedgehog process

    # Run health check and self-heal
    python -m hedgehog health

    # Send daily report
    python -m hedgehog report

    # Interactive CLI mode
    python -m hedgehog interactive

    # Handle admin command
    python -m hedgehog command <cmd> [args...]

    # Show status
    python -m hedgehog status
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hedgehog import HedgehogBrain, get_brain, get_router
from hedgehog.config import get_config

# Setup logging
log_path = Path(__file__).parent.parent / "logs" / "hedgehog.log"
log_path.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_path, mode='a'),
    ]
)
logger = logging.getLogger("hedgehog")


def print_banner():
    """Print startup banner."""
    print("""
    ╔═══════════════════════════════════════════╗
    ║  🦔 HEDGEHOG AI BRAIN v3.0                ║
    ║  ─────────────────────────────────────    ║
    ║  AUTONOMOUS SYSTEM OPERATOR               ║
    ║  Schema-aware • Self-healing • Proactive  ║
    ╚═══════════════════════════════════════════╝
    """)


async def run_telegram_bot():
    """Run Telegram bot (main mode) with proactive monitoring."""
    from hedgehog.integrations.telegram_handler import TelegramHedgehogBot

    logger.info("Starting Hedgehog Telegram bot...")

    brain = get_brain()
    bot = TelegramHedgehogBot()

    # Start bot polling
    await bot.start_polling()

    # Start proactive monitoring as background task (every 5 min)
    monitor_task = asyncio.create_task(brain.run_proactive_monitoring())
    logger.info("Proactive monitoring started (5 min interval)")

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        monitor_task.cancel()
        await bot.stop()


async def run_monitor():
    """Run autonomous monitoring only (no Telegram bot)."""
    brain = get_brain()

    logger.info("Starting autonomous monitoring mode...")
    logger.info("Checking logs and health every 5 minutes...")

    try:
        # Initial check
        actions = await brain.run_autonomous_check()
        if actions:
            logger.info(f"Initial check: {len(actions)} actions taken")

        # Continuous monitoring
        await brain.run_proactive_monitoring()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped.")


async def run_process():
    """Process pending events."""
    brain = get_brain()

    logger.info("Processing pending events...")

    # Detect new events
    events = await brain.events.detect_all()
    logger.info(f"Detected {len(events)} new events")

    # Process pending
    pending = brain.events.get_pending_events(limit=10)

    for event in pending:
        try:
            # Simple event processing for now
            brain.events.mark_processed(event.id)
            logger.info(f"Processed event: {event.event_type.value}")
        except Exception as e:
            logger.error(f"Error processing event: {e}")

    # Clear processed
    brain.events.clear_processed()

    return len(pending)


async def run_health_check():
    """Run health check and self-heal."""
    brain = get_brain()

    logger.info("Running health check...")

    # Full health check
    health = await brain.health.run_full_health_check()

    print(json.dumps(health, indent=2, default=str))

    # Self-heal if needed
    if health["overall"] != "healthy":
        logger.warning(f"System status: {health['overall']}")
        actions = await brain.health.self_heal()

        if actions:
            logger.info(f"Self-healing actions: {actions}")

            # Notify admin
            await brain.send_admin_notification(
                f"⚠️ System {health['overall']}\n\n" +
                "\n".join(f"• {a}" for a in actions),
                level="warning",
            )

    return health


async def run_daily_report():
    """Generate and send daily report."""
    brain = get_brain()
    router = get_router()

    logger.info("Generating daily report...")

    # Get stats
    memory_stats = brain.memory.get_stats()
    health = await brain.health.run_full_health_check()
    usage = router.get_usage_summary()

    # Get position stats
    position_tool = brain.tools.get("position_stats")
    position_stats = {}
    if position_tool:
        result = await position_tool.run(hours=24)
        if result.success:
            position_stats = result.data

    # Build report
    report = f"""
📊 *Daily Report* - {datetime.now().strftime('%Y-%m-%d')}

*System Health*
Status: {health['overall']}

*Trading Activity (24h)*
Open Positions: {position_stats.get('open_positions', 'N/A')}
New Positions: {position_stats.get('positions_last_hours', 'N/A')}
Exits: {position_stats.get('recent_exits', 'N/A')}

*AI Brain (Today)*
GPT-4o-mini: ${usage['gpt']['cost_usd']:.4f} ({usage['gpt']['calls']} calls)
Claude Sonnet: ${usage['claude']['cost_usd']:.4f} ({usage['claude']['calls']} calls)
Total Cost: ${usage['total']['cost_usd']:.4f}

*Memory*
Decisions: {memory_stats.get('total_decisions', 0)}
Errors: {memory_stats.get('total_errors', 0)} (resolved: {memory_stats.get('resolved_errors', 0)})

🦔 _Hedgehog AI Brain_
""".strip()

    # Send via Telegram
    await brain.send_admin_notification(report, level="info")

    logger.info("Daily report sent")
    return report


async def run_command(command: str, args: list):
    """Handle an admin command."""
    brain = get_brain()

    logger.info(f"Running command: {command} {args}")

    # Build message
    message = f"/{command}"
    if args:
        message += " " + " ".join(args)

    # Process through brain
    response = await brain.process_message(
        message=message,
        user_id=brain.config.admin_chat_id,
        is_admin=True,
    )

    print(response)
    return response


async def run_interactive():
    """Interactive mode for testing."""
    brain = get_brain()

    print("=" * 60)
    print("Hedgehog Interactive Mode")
    print("=" * 60)
    print("Type commands or natural language. Type 'quit' to exit.")
    print()

    while True:
        try:
            user_input = input("🦔 > ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            # Process through brain
            response = await brain.process_message(
                message=user_input,
                user_id=brain.config.admin_chat_id,
                is_admin=True,
            )

            print()
            print(response)
            print()

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            break
        except Exception as e:
            print(f"Error: {e}")


async def run_status():
    """Show current status."""
    brain = get_brain()
    router = get_router()

    status = brain.get_status()
    usage = router.get_usage_summary()

    print(f"""
🦔 Hedgehog Status
==================

Paused: {status['paused']}
Tools: {status['tools']}
Pending Approvals: {status['pending_approvals']}

AI Usage Today:
  GPT-4o-mini: {usage['gpt']['calls']} calls (${usage['gpt']['cost_usd']:.4f})
  Claude: {usage['claude']['calls']} calls (${usage['claude']['cost_usd']:.4f})
  Total: ${usage['total']['cost_usd']:.4f}

Memory:
  Decisions: {status['memory'].get('total_decisions', 0)}
  Errors: {status['memory'].get('total_errors', 0)}
""")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Hedgehog AI Brain")
    parser.add_argument(
        "mode",
        nargs="?",
        default="status",
        choices=["bot", "monitor", "process", "health", "report", "interactive", "command", "status"],
        help="Mode to run"
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="Additional arguments"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    print_banner()

    config = get_config()
    print(f"Mode: {args.mode}")
    print(f"Primary Model: {config.primary_model.model}")
    print(f"Secondary Model: {config.secondary_model.model}")
    print()

    # Run appropriate mode
    if args.mode == "bot":
        asyncio.run(run_telegram_bot())

    elif args.mode == "monitor":
        asyncio.run(run_monitor())

    elif args.mode == "process":
        count = asyncio.run(run_process())
        print(f"Processed {count} events")

    elif args.mode == "health":
        asyncio.run(run_health_check())

    elif args.mode == "report":
        asyncio.run(run_daily_report())

    elif args.mode == "interactive":
        asyncio.run(run_interactive())

    elif args.mode == "command":
        if not args.args:
            print("Error: command mode requires a command")
            sys.exit(1)
        cmd = args.args[0]
        cmd_args = args.args[1:] if len(args.args) > 1 else []
        asyncio.run(run_command(cmd, cmd_args))

    elif args.mode == "status":
        asyncio.run(run_status())


if __name__ == "__main__":
    main()
