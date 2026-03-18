"""
Event Detection for Hedgehog

Detects events that should trigger AI brain processing.
Event-driven architecture - no continuous polling loops.
"""
import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events Hedgehog responds to."""

    # Trading Events
    NEW_POSITION = "new_position"           # New lifecycle position created
    POSITION_EXIT = "position_exit"         # Wallet sold
    POSITION_MILESTONE = "position_milestone"  # 2x, 5x, 10x reached
    POSITION_RUG = "position_rug"           # Token rugged

    # System Events
    SERVICE_DOWN = "service_down"           # A service stopped/crashed
    SERVICE_ERROR = "service_error"         # Service threw error
    HIGH_ERROR_RATE = "high_error_rate"     # Error rate spike
    DISK_FULL = "disk_full"                 # Disk space low
    MEMORY_HIGH = "memory_high"             # Memory usage high

    # Database Events
    WALLET_DEGRADED = "wallet_degraded"     # Wallet win rate dropped
    NEW_INSIDER = "new_insider"             # New insider wallet detected
    PIPELINE_COMPLETE = "pipeline_complete" # Daily pipeline finished

    # Admin Events
    ADMIN_COMMAND = "admin_command"         # Admin sent command via Telegram
    DAILY_REPORT = "daily_report"           # Time to send daily report
    SCHEDULED_TASK = "scheduled_task"       # Scheduled task triggered

    # AI Events
    AI_DECISION_NEEDED = "ai_decision_needed"  # Complex decision required
    ANOMALY_DETECTED = "anomaly_detected"      # Unusual pattern detected


@dataclass
class Event:
    """An event that triggers Hedgehog processing."""
    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: EventType = EventType.AI_DECISION_NEEDED
    source: str = ""  # What generated the event
    data: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = more urgent
    processed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "source": self.source,
            "data": self.data,
            "priority": self.priority,
            "processed": self.processed,
        }

    def to_prompt(self) -> str:
        """Convert event to prompt text for AI."""
        return f"""
Event Type: {self.event_type.value}
Source: {self.source}
Time: {self.timestamp.isoformat()}
Priority: {self.priority}
Data:
{json.dumps(self.data, indent=2, default=str)}
""".strip()


class EventDetector:
    """
    Detects and queues events for Hedgehog processing.

    Designed for event-driven operation:
    - No continuous polling loops
    - Events are pushed or checked on-demand
    - Integrates with webhooks, cron, and system signals
    """

    def __init__(self, config=None):
        """Initialize event detector."""
        self.config = config
        self.event_queue: List[Event] = []
        self.handlers: Dict[EventType, List[Callable]] = {}
        self.last_check_times: Dict[str, float] = {}

        # Thresholds for detection
        self.thresholds = {
            "error_rate_per_hour": 50,
            "memory_percent": 85,
            "disk_percent": 90,
            "position_milestone_x": [2, 5, 10, 20, 50],
        }

    def register_handler(self, event_type: EventType, handler: Callable):
        """Register a handler for an event type."""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)
        logger.debug(f"Registered handler for {event_type.value}")

    def push_event(self, event: Event):
        """Push an event to the queue."""
        self.event_queue.append(event)
        logger.info(f"Event queued: {event.event_type.value} from {event.source}")

        # Notify handlers immediately for high-priority events
        if event.priority >= 5:
            asyncio.create_task(self._notify_handlers(event))

    async def _notify_handlers(self, event: Event):
        """Notify registered handlers of an event."""
        handlers = self.handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Handler error for {event.event_type.value}: {e}")

    def get_pending_events(self, limit: int = 10) -> List[Event]:
        """Get pending events from queue, sorted by priority."""
        pending = [e for e in self.event_queue if not e.processed]
        pending.sort(key=lambda e: (-e.priority, e.timestamp))
        return pending[:limit]

    def mark_processed(self, event_id: int):
        """Mark an event as processed."""
        for event in self.event_queue:
            if event.id == event_id:
                event.processed = True
                break

    def clear_processed(self):
        """Clear processed events from queue."""
        self.event_queue = [e for e in self.event_queue if not e.processed]

    # ==================== Event Detection Methods ====================

    async def check_new_positions(self) -> List[Event]:
        """Check for new positions since last check."""
        events = []
        check_key = "new_positions"

        last_check = self.last_check_times.get(check_key, time.time() - 300)

        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, wallet_address, token_address, token_symbol,
                       entry_timestamp, buy_sol_amount, entry_mc
                FROM position_lifecycle
                WHERE entry_timestamp > ?
                ORDER BY entry_timestamp DESC
                LIMIT 20
            """, (int(last_check),))

            for row in cursor.fetchall():
                events.append(Event(
                    event_type=EventType.NEW_POSITION,
                    source="position_lifecycle",
                    data={
                        "position_id": row[0],
                        "wallet": row[1],
                        "token": row[2],
                        "symbol": row[3],
                        "entry_time": row[4],
                        "buy_sol": row[5],
                        "entry_mc": row[6],
                    },
                    priority=3,
                ))

            conn.close()
            self.last_check_times[check_key] = time.time()

        except Exception as e:
            logger.error(f"Error checking new positions: {e}")

        return events

    async def check_position_exits(self) -> List[Event]:
        """Check for recent position exits."""
        events = []
        check_key = "position_exits"

        last_check = self.last_check_times.get(check_key, time.time() - 300)

        try:
            from database import get_connection

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT we.id, we.position_id, we.wallet_address, we.token_address,
                       we.exit_timestamp, we.sell_sol_received, we.roi_at_exit,
                       pl.token_symbol
                FROM wallet_exits we
                JOIN position_lifecycle pl ON we.position_id = pl.id
                WHERE we.exit_timestamp > ?
                ORDER BY we.exit_timestamp DESC
                LIMIT 20
            """, (int(last_check),))

            for row in cursor.fetchall():
                events.append(Event(
                    event_type=EventType.POSITION_EXIT,
                    source="wallet_exits",
                    data={
                        "exit_id": row[0],
                        "position_id": row[1],
                        "wallet": row[2],
                        "token": row[3],
                        "exit_time": row[4],
                        "sell_sol": row[5],
                        "roi": row[6],
                        "symbol": row[7],
                    },
                    priority=2,
                ))

            conn.close()
            self.last_check_times[check_key] = time.time()

        except Exception as e:
            logger.error(f"Error checking position exits: {e}")

        return events

    async def check_error_rate(self) -> Optional[Event]:
        """Check if error rate is high."""
        check_key = "error_rate"

        # Only check once per 10 minutes
        last_check = self.last_check_times.get(check_key, 0)
        if time.time() - last_check < 600:
            return None

        try:
            log_path = Path(__file__).parent.parent.parent / "logs" / "bot.log"

            if not log_path.exists():
                return None

            # Read last 1000 lines
            with open(log_path, 'r') as f:
                lines = f.readlines()[-1000:]

            # Count errors in last hour
            one_hour_ago = datetime.now().timestamp() - 3600
            error_count = 0

            for line in lines:
                if " - ERROR - " in line:
                    # Try to parse timestamp
                    try:
                        ts_str = line[:23]  # YYYY-MM-DD HH:MM:SS,mmm
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f")
                        if ts.timestamp() > one_hour_ago:
                            error_count += 1
                    except:
                        pass

            self.last_check_times[check_key] = time.time()

            if error_count > self.thresholds["error_rate_per_hour"]:
                return Event(
                    event_type=EventType.HIGH_ERROR_RATE,
                    source="log_analysis",
                    data={
                        "error_count": error_count,
                        "threshold": self.thresholds["error_rate_per_hour"],
                        "period": "1 hour",
                    },
                    priority=7,
                )

        except Exception as e:
            logger.error(f"Error checking error rate: {e}")

        return None

    async def check_service_health(self) -> List[Event]:
        """Check health of SoulWinners services."""
        events = []
        check_key = "service_health"

        # Only check once per minute
        last_check = self.last_check_times.get(check_key, 0)
        if time.time() - last_check < 60:
            return events

        import subprocess

        services = {
            "bot": "run_bot.py",
            "webhook": "webhook_server.py",
        }

        for name, pattern in services.items():
            try:
                result = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode != 0:
                    events.append(Event(
                        event_type=EventType.SERVICE_DOWN,
                        source="health_check",
                        data={
                            "service": name,
                            "pattern": pattern,
                            "status": "not_running",
                        },
                        priority=8,
                    ))
            except Exception as e:
                logger.error(f"Error checking service {name}: {e}")

        self.last_check_times[check_key] = time.time()
        return events

    async def check_disk_space(self) -> Optional[Event]:
        """Check disk space."""
        check_key = "disk_space"

        # Only check once per 5 minutes
        last_check = self.last_check_times.get(check_key, 0)
        if time.time() - last_check < 300:
            return None

        try:
            import shutil

            total, used, free = shutil.disk_usage("/")
            percent_used = (used / total) * 100

            self.last_check_times[check_key] = time.time()

            if percent_used > self.thresholds["disk_percent"]:
                return Event(
                    event_type=EventType.DISK_FULL,
                    source="disk_check",
                    data={
                        "percent_used": round(percent_used, 1),
                        "free_gb": round(free / (1024**3), 2),
                        "threshold": self.thresholds["disk_percent"],
                    },
                    priority=9,
                )

        except Exception as e:
            logger.error(f"Error checking disk space: {e}")

        return None

    async def detect_all(self) -> List[Event]:
        """Run all detection methods and return events."""
        all_events = []

        # Run checks
        new_positions = await self.check_new_positions()
        all_events.extend(new_positions)

        exits = await self.check_position_exits()
        all_events.extend(exits)

        error_event = await self.check_error_rate()
        if error_event:
            all_events.append(error_event)

        service_events = await self.check_service_health()
        all_events.extend(service_events)

        disk_event = await self.check_disk_space()
        if disk_event:
            all_events.append(disk_event)

        # Add to queue
        for event in all_events:
            event.id = len(self.event_queue) + 1
            self.event_queue.append(event)

        return all_events

    def create_event(
        self,
        event_type: EventType,
        source: str,
        data: Dict[str, Any],
        priority: int = 5
    ) -> Event:
        """Create and queue an event."""
        event = Event(
            id=len(self.event_queue) + 1,
            event_type=event_type,
            source=source,
            data=data,
            priority=priority,
        )
        self.event_queue.append(event)
        return event


# Singleton instance
_detector: Optional[EventDetector] = None


def get_event_detector() -> EventDetector:
    """Get or create event detector instance."""
    global _detector
    if _detector is None:
        _detector = EventDetector()
    return _detector
