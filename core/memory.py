"""
Hedgehog Memory System
File-based JSON storage for system state and conversation history
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import MEMORY_DIR, CONVERSATION_HISTORY_LIMIT


class Memory:
    """Simple file-based memory system"""

    def __init__(self):
        self.memory_dir = MEMORY_DIR
        self.memory_dir.mkdir(exist_ok=True)

        self.state_file = self.memory_dir / "system_state.json"
        self.conversation_file = self.memory_dir / "conversation.json"

        # Load on init
        self.state = self._load_state()
        self.conversations = self._load_conversations()

    def _load_state(self) -> dict:
        """Load system state from file"""
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except json.JSONDecodeError:
                return self._default_state()
        return self._default_state()

    def _default_state(self) -> dict:
        """Default system state"""
        return {
            "last_updated": None,
            "cached_data": {},
            "service_status": {},
        }

    def _load_conversations(self) -> list:
        """Load conversation history from file"""
        if self.conversation_file.exists():
            try:
                return json.loads(self.conversation_file.read_text())
            except json.JSONDecodeError:
                return []
        return []

    def save_state(self):
        """Persist state to disk"""
        self.state["last_updated"] = datetime.now().isoformat()
        self.state_file.write_text(json.dumps(self.state, indent=2, default=str))

    def save_conversations(self):
        """Persist conversations to disk (keep last N)"""
        # Trim to limit
        trimmed = self.conversations[-CONVERSATION_HISTORY_LIMIT:]
        self.conversation_file.write_text(json.dumps(trimmed, indent=2, default=str))

    def add_message(self, role: str, content: str, user_id: str = None):
        """Add a message to conversation history"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
        }
        self.conversations.append(message)
        self.save_conversations()

    def get_recent_messages(self, limit: int = 10) -> list:
        """Get recent conversation messages for context"""
        return self.conversations[-limit:]

    def cache_data(self, key: str, value: Any):
        """Cache data in system state"""
        self.state["cached_data"][key] = {
            "value": value,
            "cached_at": datetime.now().isoformat(),
        }
        self.save_state()

    def get_cached(self, key: str) -> Any:
        """Get cached data"""
        cached = self.state["cached_data"].get(key)
        if cached:
            return cached["value"]
        return None

    def update_service_status(self, service: str, status: dict):
        """Update cached service status"""
        self.state["service_status"][service] = {
            **status,
            "checked_at": datetime.now().isoformat(),
        }
        self.save_state()

    def get_context_messages(self) -> list:
        """Get messages formatted for LLM context"""
        recent = self.get_recent_messages(10)
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in recent
        ]


# Singleton instance
_memory = None

def get_memory() -> Memory:
    """Get or create memory instance"""
    global _memory
    if _memory is None:
        _memory = Memory()
    return _memory
