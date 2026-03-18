"""
Memory Store for Hedgehog

Persistent storage for:
- Decisions made and their outcomes
- Errors encountered and their fixes
- Learned patterns and solutions
"""
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    """Record of a decision made by Hedgehog."""
    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""
    event_data: Dict[str, Any] = field(default_factory=dict)
    decision: str = ""
    reasoning: str = ""
    action_taken: str = ""
    tool_used: Optional[str] = None
    outcome: Optional[str] = None  # success, failure, pending
    outcome_details: Optional[str] = None
    cost_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "event_type": self.event_type,
            "event_data": self.event_data,
            "decision": self.decision,
            "reasoning": self.reasoning,
            "action_taken": self.action_taken,
            "tool_used": self.tool_used,
            "outcome": self.outcome,
            "outcome_details": self.outcome_details,
            "cost_tokens": self.cost_tokens,
        }


@dataclass
class Error:
    """Record of an error encountered."""
    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    error_type: str = ""
    error_message: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    resolved: bool = False
    fix_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "context": self.context,
            "stack_trace": self.stack_trace,
            "resolved": self.resolved,
            "fix_id": self.fix_id,
        }


@dataclass
class Fix:
    """Record of a fix/solution for an error."""
    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    error_pattern: str = ""  # Regex or keyword pattern
    fix_description: str = ""
    fix_action: str = ""  # Tool/action to apply
    fix_params: Dict[str, Any] = field(default_factory=dict)
    success_count: int = 0
    failure_count: int = 0
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "error_pattern": self.error_pattern,
            "fix_description": self.fix_description,
            "fix_action": self.fix_action,
            "fix_params": self.fix_params,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "enabled": self.enabled,
        }

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0


class MemoryStore:
    """
    Persistent memory storage for Hedgehog.

    Uses SQLite for durable storage of decisions, errors, and fixes.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize memory store."""
        if db_path is None:
            db_path = Path(__file__).parent / "hedgehog_memory.db"

        self.db_path = db_path
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Decisions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT,
                event_data TEXT,
                decision TEXT,
                reasoning TEXT,
                action_taken TEXT,
                tool_used TEXT,
                outcome TEXT,
                outcome_details TEXT,
                cost_tokens INTEGER DEFAULT 0
            )
        """)

        # Errors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                error_type TEXT,
                error_message TEXT,
                context TEXT,
                stack_trace TEXT,
                resolved INTEGER DEFAULT 0,
                fix_id INTEGER,
                FOREIGN KEY (fix_id) REFERENCES fixes(id)
            )
        """)

        # Fixes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fixes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                error_pattern TEXT NOT NULL,
                fix_description TEXT,
                fix_action TEXT,
                fix_params TEXT,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1
            )
        """)

        # Event log table (for audit)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT,
                event_source TEXT,
                event_data TEXT,
                processed INTEGER DEFAULT 0
            )
        """)

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_decisions_timestamp
            ON decisions(timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_errors_timestamp
            ON errors(timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_errors_resolved
            ON errors(resolved)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_fixes_pattern
            ON fixes(error_pattern)
        """)

        conn.commit()
        conn.close()

        logger.debug(f"Memory database initialized at {self.db_path}")

    # ==================== Decisions ====================

    def save_decision(self, decision: Decision) -> int:
        """Save a decision to memory."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO decisions (
                timestamp, event_type, event_data, decision, reasoning,
                action_taken, tool_used, outcome, outcome_details, cost_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision.timestamp.isoformat(),
            decision.event_type,
            json.dumps(decision.event_data),
            decision.decision,
            decision.reasoning,
            decision.action_taken,
            decision.tool_used,
            decision.outcome,
            decision.outcome_details,
            decision.cost_tokens,
        ))

        decision_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.debug(f"Saved decision #{decision_id}: {decision.decision[:50]}")
        return decision_id

    def update_decision_outcome(
        self,
        decision_id: int,
        outcome: str,
        details: Optional[str] = None
    ):
        """Update the outcome of a decision."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE decisions
            SET outcome = ?, outcome_details = ?
            WHERE id = ?
        """, (outcome, details, decision_id))

        conn.commit()
        conn.close()

    def get_recent_decisions(self, limit: int = 10) -> List[Decision]:
        """Get recent decisions."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM decisions
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        decisions = []
        for row in cursor.fetchall():
            decisions.append(Decision(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                event_type=row["event_type"],
                event_data=json.loads(row["event_data"] or "{}"),
                decision=row["decision"],
                reasoning=row["reasoning"],
                action_taken=row["action_taken"],
                tool_used=row["tool_used"],
                outcome=row["outcome"],
                outcome_details=row["outcome_details"],
                cost_tokens=row["cost_tokens"],
            ))

        conn.close()
        return decisions

    def get_decisions_by_type(self, event_type: str, limit: int = 20) -> List[Decision]:
        """Get decisions for a specific event type."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM decisions
            WHERE event_type = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (event_type, limit))

        decisions = []
        for row in cursor.fetchall():
            decisions.append(Decision(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                event_type=row["event_type"],
                event_data=json.loads(row["event_data"] or "{}"),
                decision=row["decision"],
                reasoning=row["reasoning"],
                action_taken=row["action_taken"],
                tool_used=row["tool_used"],
                outcome=row["outcome"],
                outcome_details=row["outcome_details"],
                cost_tokens=row["cost_tokens"],
            ))

        conn.close()
        return decisions

    # ==================== Errors ====================

    def save_error(self, error: Error) -> int:
        """Save an error to memory."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO errors (
                timestamp, error_type, error_message, context,
                stack_trace, resolved, fix_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            error.timestamp.isoformat(),
            error.error_type,
            error.error_message,
            json.dumps(error.context),
            error.stack_trace,
            1 if error.resolved else 0,
            error.fix_id,
        ))

        error_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.debug(f"Saved error #{error_id}: {error.error_type}")
        return error_id

    def mark_error_resolved(self, error_id: int, fix_id: Optional[int] = None):
        """Mark an error as resolved."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE errors
            SET resolved = 1, fix_id = ?
            WHERE id = ?
        """, (fix_id, error_id))

        conn.commit()
        conn.close()

    def get_unresolved_errors(self, limit: int = 20) -> List[Error]:
        """Get unresolved errors."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM errors
            WHERE resolved = 0
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        errors = []
        for row in cursor.fetchall():
            errors.append(Error(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                error_type=row["error_type"],
                error_message=row["error_message"],
                context=json.loads(row["context"] or "{}"),
                stack_trace=row["stack_trace"],
                resolved=bool(row["resolved"]),
                fix_id=row["fix_id"],
            ))

        conn.close()
        return errors

    def find_similar_errors(self, error_message: str, limit: int = 5) -> List[Error]:
        """Find similar past errors."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Simple keyword matching
        keywords = error_message.split()[:3]  # First 3 words
        pattern = "%".join(keywords)

        cursor.execute("""
            SELECT * FROM errors
            WHERE error_message LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (f"%{pattern}%", limit))

        errors = []
        for row in cursor.fetchall():
            errors.append(Error(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                error_type=row["error_type"],
                error_message=row["error_message"],
                context=json.loads(row["context"] or "{}"),
                stack_trace=row["stack_trace"],
                resolved=bool(row["resolved"]),
                fix_id=row["fix_id"],
            ))

        conn.close()
        return errors

    # ==================== Fixes ====================

    def save_fix(self, fix: Fix) -> int:
        """Save a fix to memory."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO fixes (
                timestamp, error_pattern, fix_description,
                fix_action, fix_params, success_count, failure_count, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fix.timestamp.isoformat(),
            fix.error_pattern,
            fix.fix_description,
            fix.fix_action,
            json.dumps(fix.fix_params),
            fix.success_count,
            fix.failure_count,
            1 if fix.enabled else 0,
        ))

        fix_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Saved fix #{fix_id}: {fix.fix_description[:50]}")
        return fix_id

    def find_fix_for_error(self, error_message: str) -> Optional[Fix]:
        """Find a fix that matches an error."""
        import re

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM fixes
            WHERE enabled = 1
            ORDER BY success_count DESC
        """)

        for row in cursor.fetchall():
            pattern = row["error_pattern"]
            try:
                if re.search(pattern, error_message, re.IGNORECASE):
                    conn.close()
                    return Fix(
                        id=row["id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        error_pattern=row["error_pattern"],
                        fix_description=row["fix_description"],
                        fix_action=row["fix_action"],
                        fix_params=json.loads(row["fix_params"] or "{}"),
                        success_count=row["success_count"],
                        failure_count=row["failure_count"],
                        enabled=bool(row["enabled"]),
                    )
            except re.error:
                # Invalid regex, try simple contains
                if pattern.lower() in error_message.lower():
                    conn.close()
                    return Fix(
                        id=row["id"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                        error_pattern=row["error_pattern"],
                        fix_description=row["fix_description"],
                        fix_action=row["fix_action"],
                        fix_params=json.loads(row["fix_params"] or "{}"),
                        success_count=row["success_count"],
                        failure_count=row["failure_count"],
                        enabled=bool(row["enabled"]),
                    )

        conn.close()
        return None

    def update_fix_stats(self, fix_id: int, success: bool):
        """Update fix success/failure stats."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if success:
            cursor.execute("""
                UPDATE fixes
                SET success_count = success_count + 1
                WHERE id = ?
            """, (fix_id,))
        else:
            cursor.execute("""
                UPDATE fixes
                SET failure_count = failure_count + 1
                WHERE id = ?
            """, (fix_id,))

        conn.commit()
        conn.close()

    def get_all_fixes(self) -> List[Fix]:
        """Get all fixes."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM fixes
            ORDER BY success_count DESC
        """)

        fixes = []
        for row in cursor.fetchall():
            fixes.append(Fix(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                error_pattern=row["error_pattern"],
                fix_description=row["fix_description"],
                fix_action=row["fix_action"],
                fix_params=json.loads(row["fix_params"] or "{}"),
                success_count=row["success_count"],
                failure_count=row["failure_count"],
                enabled=bool(row["enabled"]),
            ))

        conn.close()
        return fixes

    # ==================== Event Log ====================

    def log_event(
        self,
        event_type: str,
        event_source: str,
        event_data: Dict[str, Any]
    ) -> int:
        """Log an event for processing."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO event_log (timestamp, event_type, event_source, event_data)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            event_type,
            event_source,
            json.dumps(event_data),
        ))

        event_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return event_id

    def get_unprocessed_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get unprocessed events."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM event_log
            WHERE processed = 0
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limit,))

        events = []
        for row in cursor.fetchall():
            events.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "event_source": row["event_source"],
                "event_data": json.loads(row["event_data"] or "{}"),
            })

        conn.close()
        return events

    def mark_event_processed(self, event_id: int):
        """Mark an event as processed."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE event_log
            SET processed = 1
            WHERE id = ?
        """, (event_id,))

        conn.commit()
        conn.close()

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()

        stats = {}

        # Decision stats
        cursor.execute("SELECT COUNT(*) FROM decisions")
        stats["total_decisions"] = cursor.fetchone()[0]

        cursor.execute("""
            SELECT outcome, COUNT(*)
            FROM decisions
            WHERE outcome IS NOT NULL
            GROUP BY outcome
        """)
        stats["decision_outcomes"] = dict(cursor.fetchall())

        # Error stats
        cursor.execute("SELECT COUNT(*) FROM errors")
        stats["total_errors"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM errors WHERE resolved = 1")
        stats["resolved_errors"] = cursor.fetchone()[0]

        # Fix stats
        cursor.execute("SELECT COUNT(*) FROM fixes WHERE enabled = 1")
        stats["active_fixes"] = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(success_count) FROM fixes")
        stats["total_fix_successes"] = cursor.fetchone()[0] or 0

        conn.close()
        return stats

    def cleanup_old_data(self, days: int = 90):
        """Clean up data older than N days."""
        from datetime import timedelta

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()

        # Keep decisions but remove event_data for old ones
        cursor.execute("""
            UPDATE decisions
            SET event_data = '{}'
            WHERE timestamp < ?
        """, (cutoff,))

        # Delete old processed events
        cursor.execute("""
            DELETE FROM event_log
            WHERE timestamp < ? AND processed = 1
        """, (cutoff,))

        conn.commit()
        deleted = cursor.rowcount
        conn.close()

        logger.info(f"Cleaned up {deleted} old event log entries")
        return deleted


# Singleton instance
_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    """Get or create memory store instance."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
