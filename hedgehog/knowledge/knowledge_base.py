"""
Hedgehog Knowledge Base Query Interface

This is the BRAIN of Hedgehog. All tools query HERE first.
Only goes to live system if knowledge base doesn't have the answer.

Like a brain - instant recall for things it knows, only "looks" when needed.
"""

import json
import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from .soulwinners_map import (
    STATE_FILE, MAIN_DB, HEDGEHOG_DB,
    get_scanner, get_knowledge, initialize_knowledge
)


@dataclass
class QueryResult:
    """Result of a knowledge query"""
    answer: Any
    source: str  # 'knowledge_base', 'live_query', 'computed'
    confidence: float  # 0-1, how confident we are
    cached: bool
    query_time_ms: float


class HedgehogKnowledge:
    """
    Hedgehog's Brain - Query interface for system knowledge.

    Usage:
        kb = HedgehogKnowledge()

        # Ask about wallets
        result = kb.query("How many insider wallets?")

        # Ask about tables
        result = kb.get_table_info("qualified_wallets")

        # Ask about services
        result = kb.get_service_status("bot")

        # Generic question
        result = kb.answer("Is the webhook running?")
    """

    def __init__(self, auto_init: bool = True):
        """
        Initialize knowledge base.

        Args:
            auto_init: If True and no knowledge exists, run initial scan
        """
        self._knowledge: Optional[Dict] = None
        self._load_knowledge(auto_init)

    def _load_knowledge(self, auto_init: bool = True):
        """Load knowledge from file"""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r') as f:
                    self._knowledge = json.load(f)
            except:
                self._knowledge = None

        if self._knowledge is None and auto_init:
            print("[HEDGEHOG KB] No knowledge found, initializing...")
            initialize_knowledge(start_updater=False)
            self._load_knowledge(auto_init=False)

    def _ensure_fresh(self, max_age_minutes: int = 10):
        """Ensure knowledge is fresh enough"""
        if self._knowledge is None:
            self._load_knowledge()
            return

        try:
            scan_time = datetime.fromisoformat(self._knowledge.get('scan_time', ''))
            age = (datetime.now() - scan_time).total_seconds() / 60

            if age > max_age_minutes:
                print(f"[HEDGEHOG KB] Knowledge is {age:.1f}min old, refreshing...")
                scanner = get_scanner()
                scanner.scan_all()
                self._load_knowledge(auto_init=False)
        except:
            pass

    # ============================================================
    # WALLET QUERIES - Instant answers from knowledge base
    # ============================================================

    def get_wallet_count(self, wallet_type: str = 'all') -> QueryResult:
        """
        Get wallet counts instantly from knowledge base.

        Args:
            wallet_type: 'qualified', 'user', 'insider', 'copy_pool', 'global_pool', or 'all'

        Examples:
            kb.get_wallet_count('insider')  # How many insider wallets?
            kb.get_wallet_count('qualified')  # How many qualified wallets?
            kb.get_wallet_count('all')  # All wallet counts
        """
        import time
        start = time.time()

        self._ensure_fresh()

        counts = self._knowledge.get('wallet_counts', {})

        if wallet_type == 'all':
            answer = counts
        else:
            answer = counts.get(wallet_type, 0)

        return QueryResult(
            answer=answer,
            source='knowledge_base',
            confidence=0.95,  # Knowledge base is very reliable
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def get_position_count(self, status: str = 'all') -> QueryResult:
        """
        Get position counts instantly.

        Args:
            status: 'open', 'closed', 'total', or specific status, or 'all'
        """
        import time
        start = time.time()

        self._ensure_fresh()

        counts = self._knowledge.get('position_counts', {})

        if status == 'all':
            answer = counts
        else:
            answer = counts.get(status, 0)

        return QueryResult(
            answer=answer,
            source='knowledge_base',
            confidence=0.95,
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def get_total_pnl(self) -> QueryResult:
        """Get total PnL instantly"""
        import time
        start = time.time()

        self._ensure_fresh()

        return QueryResult(
            answer=self._knowledge.get('total_pnl', 0.0),
            source='knowledge_base',
            confidence=0.90,  # Slightly lower - PnL changes often
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def get_recent_trades_count(self) -> QueryResult:
        """Get recent trades count (last 24h)"""
        import time
        start = time.time()

        self._ensure_fresh()

        return QueryResult(
            answer=self._knowledge.get('recent_trades', 0),
            source='knowledge_base',
            confidence=0.85,  # Can change frequently
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    # ============================================================
    # DATABASE QUERIES - Schema knowledge + live data
    # ============================================================

    def get_table_info(self, table_name: str, db: str = 'main') -> QueryResult:
        """
        Get table schema and row count from knowledge base.

        Args:
            table_name: Name of the table
            db: 'main' or 'hedgehog_memory'
        """
        import time
        start = time.time()

        self._ensure_fresh()

        databases = self._knowledge.get('databases', {})
        tables = databases.get(db, {})

        if table_name in tables:
            return QueryResult(
                answer=tables[table_name],
                source='knowledge_base',
                confidence=0.99,  # Schema doesn't change
                cached=True,
                query_time_ms=(time.time() - start) * 1000
            )
        else:
            return QueryResult(
                answer=None,
                source='knowledge_base',
                confidence=0.0,
                cached=True,
                query_time_ms=(time.time() - start) * 1000
            )

    def get_all_tables(self, db: str = 'main') -> QueryResult:
        """Get list of all tables with row counts"""
        import time
        start = time.time()

        self._ensure_fresh()

        databases = self._knowledge.get('databases', {})
        tables = databases.get(db, {})

        summary = {}
        for name, info in tables.items():
            if isinstance(info, dict) and 'row_count' in info:
                summary[name] = {
                    'rows': info['row_count'],
                    'columns': len(info.get('columns', []))
                }

        return QueryResult(
            answer=summary,
            source='knowledge_base',
            confidence=0.95,
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def get_table_columns(self, table_name: str) -> QueryResult:
        """Get columns for a specific table"""
        result = self.get_table_info(table_name)
        if result.answer and 'columns' in result.answer:
            result.answer = result.answer['columns']
        return result

    def query_live(self, sql: str, db: str = 'main') -> QueryResult:
        """
        Execute a live SQL query (only when knowledge base insufficient).
        Use sparingly - prefer knowledge base queries.
        """
        import time
        start = time.time()

        db_path = MAIN_DB if db == 'main' else HEDGEHOG_DB

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]
            conn.close()

            return QueryResult(
                answer=result,
                source='live_query',
                confidence=1.0,  # Live data is accurate
                cached=False,
                query_time_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return QueryResult(
                answer={'error': str(e)},
                source='live_query',
                confidence=0.0,
                cached=False,
                query_time_ms=(time.time() - start) * 1000
            )

    # ============================================================
    # SERVICE QUERIES
    # ============================================================

    def get_service_status(self, service_name: str = 'all') -> QueryResult:
        """
        Get service status from knowledge base.

        Args:
            service_name: 'bot', 'webhook', 'monitor', 'pipeline', 'hedgehog', or 'all'
        """
        import time
        start = time.time()

        self._ensure_fresh()

        services = self._knowledge.get('services', [])

        if service_name == 'all':
            answer = {s['name']: s for s in services}
        else:
            matching = [s for s in services if s['name'].lower() == service_name.lower()]
            answer = matching[0] if matching else None

        return QueryResult(
            answer=answer,
            source='knowledge_base',
            confidence=0.85,  # Services can change
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def is_service_running(self, service_name: str) -> QueryResult:
        """Quick check: is a service running?"""
        result = self.get_service_status(service_name)
        if result.answer:
            result.answer = result.answer.get('status') == 'running'
        else:
            result.answer = False
        return result

    # ============================================================
    # SYSTEM HEALTH QUERIES
    # ============================================================

    def get_system_health(self) -> QueryResult:
        """Get system health metrics"""
        import time
        start = time.time()

        self._ensure_fresh()

        return QueryResult(
            answer={
                'disk_percent': self._knowledge.get('disk_usage_percent', 0),
                'memory_percent': self._knowledge.get('memory_usage_percent', 0),
                'cpu_percent': self._knowledge.get('cpu_usage_percent', 0)
            },
            source='knowledge_base',
            confidence=0.80,  # Changes frequently
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    # ============================================================
    # CODE/FILE QUERIES
    # ============================================================

    def get_file_info(self, file_path: str) -> QueryResult:
        """Get info about a Python file"""
        import time
        start = time.time()

        self._ensure_fresh()

        files = self._knowledge.get('python_files', {})

        # Try exact match first
        if file_path in files:
            return QueryResult(
                answer=files[file_path],
                source='knowledge_base',
                confidence=0.95,
                cached=True,
                query_time_ms=(time.time() - start) * 1000
            )

        # Try partial match
        matches = {k: v for k, v in files.items() if file_path in k}
        if matches:
            return QueryResult(
                answer=matches,
                source='knowledge_base',
                confidence=0.90,
                cached=True,
                query_time_ms=(time.time() - start) * 1000
            )

        return QueryResult(
            answer=None,
            source='knowledge_base',
            confidence=0.0,
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def find_files_with_class(self, class_name: str) -> QueryResult:
        """Find files containing a specific class"""
        import time
        start = time.time()

        self._ensure_fresh()

        files = self._knowledge.get('python_files', {})
        matches = {}

        for path, info in files.items():
            if class_name in info.get('classes', []):
                matches[path] = info

        return QueryResult(
            answer=matches,
            source='knowledge_base',
            confidence=0.95,
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def find_files_with_function(self, func_name: str) -> QueryResult:
        """Find files containing a specific function"""
        import time
        start = time.time()

        self._ensure_fresh()

        files = self._knowledge.get('python_files', {})
        matches = {}

        for path, info in files.items():
            if func_name in info.get('functions', []):
                matches[path] = info

        return QueryResult(
            answer=matches,
            source='knowledge_base',
            confidence=0.95,
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    # ============================================================
    # CONFIG QUERIES
    # ============================================================

    def get_threshold(self, name: str) -> QueryResult:
        """Get a configuration threshold"""
        import time
        start = time.time()

        self._ensure_fresh()

        thresholds = self._knowledge.get('thresholds', {})

        return QueryResult(
            answer=thresholds.get(name),
            source='knowledge_base',
            confidence=0.99,  # Config rarely changes
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    def get_all_thresholds(self) -> QueryResult:
        """Get all configuration thresholds"""
        import time
        start = time.time()

        self._ensure_fresh()

        return QueryResult(
            answer=self._knowledge.get('thresholds', {}),
            source='knowledge_base',
            confidence=0.99,
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    # ============================================================
    # GIT QUERIES
    # ============================================================

    def get_git_status(self) -> QueryResult:
        """Get git status"""
        import time
        start = time.time()

        self._ensure_fresh()

        return QueryResult(
            answer={
                'branch': self._knowledge.get('current_branch', 'unknown'),
                'last_commit': self._knowledge.get('last_commit', 'unknown'),
                'uncommitted': self._knowledge.get('uncommitted_changes', [])
            },
            source='knowledge_base',
            confidence=0.90,
            cached=True,
            query_time_ms=(time.time() - start) * 1000
        )

    # ============================================================
    # NATURAL LANGUAGE QUERIES
    # ============================================================

    def answer(self, question: str) -> QueryResult:
        """
        Answer a natural language question using knowledge base.

        Examples:
            "How many insider wallets?"
            "Is the bot running?"
            "What's the total PnL?"
            "What tables exist?"
        """
        import time
        start = time.time()

        question_lower = question.lower()

        # Table listing patterns - check early
        if any(w in question_lower for w in ['what tables', 'list tables', 'tables exist', 'show tables', 'all tables']):
            return self.get_all_tables()

        # Wallet count patterns
        if any(w in question_lower for w in ['how many', 'count', 'number of']):
            if 'insider' in question_lower:
                return self.get_wallet_count('insider')
            elif 'qualified' in question_lower:
                return self.get_wallet_count('qualified')
            elif 'user' in question_lower and 'wallet' in question_lower:
                return self.get_wallet_count('user')
            elif 'wallet' in question_lower:
                return self.get_wallet_count('all')
            elif 'position' in question_lower:
                return self.get_position_count('all')
            elif 'trade' in question_lower:
                return self.get_recent_trades_count()
            elif 'table' in question_lower:
                return self.get_all_tables()

        # Service status patterns
        if any(w in question_lower for w in ['running', 'status', 'is the', 'active']):
            for service in ['bot', 'webhook', 'monitor', 'pipeline', 'hedgehog']:
                if service in question_lower:
                    return self.is_service_running(service)

        # PnL patterns
        if any(w in question_lower for w in ['pnl', 'profit', 'loss', 'p&l']):
            return self.get_total_pnl()

        # Health patterns
        if any(w in question_lower for w in ['health', 'memory', 'disk', 'cpu']):
            return self.get_system_health()

        # Git patterns
        if any(w in question_lower for w in ['git', 'branch', 'commit', 'uncommitted']):
            return self.get_git_status()

        # Table patterns
        if 'table' in question_lower:
            # Extract table name
            words = question.split()
            for i, word in enumerate(words):
                if word.lower() == 'table' and i + 1 < len(words):
                    table_name = words[i + 1].strip('?.,')
                    return self.get_table_info(table_name)

        # If we can't answer from knowledge base, return unknown
        return QueryResult(
            answer="I don't have this information cached. Let me query the live system.",
            source='knowledge_base',
            confidence=0.0,
            cached=False,
            query_time_ms=(time.time() - start) * 1000
        )

    # ============================================================
    # METADATA
    # ============================================================

    def get_knowledge_age(self) -> float:
        """Get age of knowledge in minutes"""
        if self._knowledge:
            try:
                scan_time = datetime.fromisoformat(self._knowledge.get('scan_time', ''))
                return (datetime.now() - scan_time).total_seconds() / 60
            except:
                pass
        return float('inf')

    def get_scan_summary(self) -> Dict:
        """Get summary of last scan"""
        if self._knowledge:
            return {
                'scan_time': self._knowledge.get('scan_time'),
                'duration_seconds': self._knowledge.get('scan_duration_seconds'),
                'tables': sum(len(t) for t in self._knowledge.get('databases', {}).values()),
                'files': len(self._knowledge.get('python_files', {})),
                'services': len(self._knowledge.get('services', [])),
                'age_minutes': self.get_knowledge_age()
            }
        return {'error': 'No knowledge loaded'}

    def refresh(self):
        """Force a knowledge refresh"""
        scanner = get_scanner()
        scanner.scan_all()
        self._load_knowledge(auto_init=False)


# Global instance
_kb: Optional[HedgehogKnowledge] = None


def get_kb() -> HedgehogKnowledge:
    """Get or create the global knowledge base"""
    global _kb
    if _kb is None:
        _kb = HedgehogKnowledge()
    return _kb


# Quick access functions
def ask(question: str) -> Any:
    """Quick ask - returns just the answer"""
    return get_kb().answer(question).answer


def wallet_count(wallet_type: str = 'all') -> int:
    """Quick wallet count"""
    result = get_kb().get_wallet_count(wallet_type).answer
    return result if isinstance(result, int) else 0


def is_running(service: str) -> bool:
    """Quick service check"""
    return get_kb().is_service_running(service).answer


def table_rows(table: str) -> int:
    """Quick table row count"""
    result = get_kb().get_table_info(table)
    if result.answer and 'row_count' in result.answer:
        return result.answer['row_count']
    return 0


if __name__ == '__main__':
    # Test the knowledge base
    kb = HedgehogKnowledge()

    print("\n" + "=" * 60)
    print("HEDGEHOG KNOWLEDGE BASE TEST")
    print("=" * 60)

    # Test queries
    tests = [
        ("Wallet counts", kb.get_wallet_count('all')),
        ("Insider wallets", kb.get_wallet_count('insider')),
        ("Position counts", kb.get_position_count('all')),
        ("Total PnL", kb.get_total_pnl()),
        ("Bot running?", kb.is_service_running('bot')),
        ("All services", kb.get_service_status('all')),
        ("System health", kb.get_system_health()),
        ("Git status", kb.get_git_status()),
        ("All tables", kb.get_all_tables()),
        ("qualified_wallets table", kb.get_table_info('qualified_wallets')),
    ]

    for name, result in tests:
        print(f"\n{name}:")
        print(f"  Answer: {result.answer}")
        print(f"  Source: {result.source}, Confidence: {result.confidence}")
        print(f"  Time: {result.query_time_ms:.2f}ms")

    # Test natural language
    print("\n" + "-" * 40)
    print("Natural Language Queries:")

    questions = [
        "How many insider wallets?",
        "Is the bot running?",
        "What's the total PnL?",
        "How many positions are there?",
    ]

    for q in questions:
        result = kb.answer(q)
        print(f"\nQ: {q}")
        print(f"A: {result.answer}")
        print(f"   ({result.source}, {result.query_time_ms:.2f}ms)")
