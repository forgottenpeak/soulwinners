"""
SoulWinners System Scanner - Hedgehog's Complete Knowledge of the House

This module scans the ENTIRE SoulWinners system and builds a comprehensive
knowledge base. Hedgehog doesn't guess - it KNOWS.

Like a brain knowing every room, door, and wire in its house.
"""

import os
import json
import sqlite3
import subprocess
import hashlib
import ast
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import threading
import time


# Paths - Auto-detect runtime location (works on LOCAL and VPS)
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # hedgehog/knowledge/soulwinners_map.py -> Soulwinners/
KNOWLEDGE_DIR = BASE_DIR / "hedgehog" / "knowledge"
STATE_FILE = KNOWLEDGE_DIR / "system_state.json"
MAIN_DB = BASE_DIR / "data" / "soulwinners.db"
HEDGEHOG_DB = BASE_DIR / "hedgehog" / "memory" / "hedgehog_memory.db"


@dataclass
class TableInfo:
    """Complete info about a database table"""
    name: str
    columns: List[Dict[str, Any]]  # name, type, nullable, primary_key, default
    row_count: int
    sample_data: List[Dict]  # First 3 rows
    indexes: List[str]


@dataclass
class ServiceInfo:
    """Info about a running service"""
    name: str
    pid: Optional[int]
    status: str  # running, stopped, crashed
    command: str
    memory_mb: float
    cpu_percent: float
    uptime: Optional[str]


@dataclass
class PythonFileInfo:
    """Info about a Python file"""
    path: str
    purpose: str  # Extracted from docstring or inferred
    classes: List[str]
    functions: List[str]
    imports: List[str]
    line_count: int
    last_modified: str


@dataclass
class SystemState:
    """Complete system state - Hedgehog's brain"""
    # Metadata
    scan_time: str
    scan_duration_seconds: float

    # Database knowledge
    databases: Dict[str, Dict[str, TableInfo]]  # db_path -> table_name -> info

    # Live data summaries (key metrics cached)
    wallet_counts: Dict[str, int]  # qualified, user, insider, etc.
    position_counts: Dict[str, int]  # open, closed, by_status
    recent_trades: int  # Last 24h
    total_pnl: float

    # System knowledge
    services: List[ServiceInfo]
    python_files: Dict[str, PythonFileInfo]  # path -> info
    cron_jobs: List[Dict[str, str]]

    # Config knowledge
    api_keys: Dict[str, str]  # name -> status (active/exhausted/invalid)
    thresholds: Dict[str, Any]  # All config thresholds

    # Git knowledge
    current_branch: str
    last_commit: str
    uncommitted_changes: List[str]

    # Health status
    disk_usage_percent: float
    memory_usage_percent: float
    cpu_usage_percent: float


class SoulWinnersScanner:
    """
    Scans the entire SoulWinners system and builds comprehensive knowledge.
    Hedgehog becomes the BRAIN that knows everything.
    """

    def __init__(self):
        self.base_dir = BASE_DIR
        self.state: Optional[SystemState] = None
        self._lock = threading.Lock()
        self._last_scan: Optional[datetime] = None

    def scan_all(self) -> SystemState:
        """
        Full system scan. Called on startup and every 5 minutes.
        Returns complete system knowledge.
        """
        start_time = time.time()

        print("[HEDGEHOG BRAIN] Starting full system scan...")

        # Scan everything
        databases = self._scan_databases()
        wallet_counts, position_counts, recent_trades, total_pnl = self._scan_live_metrics()
        services = self._scan_services()
        python_files = self._scan_python_files()
        cron_jobs = self._scan_cron_jobs()
        api_keys = self._scan_api_keys()
        thresholds = self._scan_config_thresholds()
        git_info = self._scan_git()
        system_health = self._scan_system_health()

        duration = time.time() - start_time

        self.state = SystemState(
            scan_time=datetime.now().isoformat(),
            scan_duration_seconds=round(duration, 2),
            databases=databases,
            wallet_counts=wallet_counts,
            position_counts=position_counts,
            recent_trades=recent_trades,
            total_pnl=total_pnl,
            services=services,
            python_files=python_files,
            cron_jobs=cron_jobs,
            api_keys=api_keys,
            thresholds=thresholds,
            current_branch=git_info['branch'],
            last_commit=git_info['last_commit'],
            uncommitted_changes=git_info['uncommitted'],
            disk_usage_percent=system_health['disk'],
            memory_usage_percent=system_health['memory'],
            cpu_usage_percent=system_health['cpu']
        )

        # Save to file
        self._save_state()

        self._last_scan = datetime.now()
        print(f"[HEDGEHOG BRAIN] Scan complete in {duration:.2f}s")

        return self.state

    def _scan_databases(self) -> Dict[str, Dict[str, Any]]:
        """Scan all database tables with full schema info"""
        databases = {}

        db_paths = [
            (str(MAIN_DB), "main"),
            (str(HEDGEHOG_DB), "hedgehog_memory")
        ]

        for db_path, db_name in db_paths:
            if not os.path.exists(db_path):
                continue

            tables = {}
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Get all tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                table_names = [row[0] for row in cursor.fetchall()]

                for table_name in table_names:
                    try:
                        # Get schema
                        cursor.execute(f"PRAGMA table_info({table_name})")
                        columns = []
                        for col in cursor.fetchall():
                            columns.append({
                                'name': col[1],
                                'type': col[2],
                                'nullable': not col[3],
                                'default': col[4],
                                'primary_key': bool(col[5])
                            })

                        # Get row count
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        row_count = cursor.fetchone()[0]

                        # Get sample data (first 3 rows)
                        cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                        sample_rows = cursor.fetchall()
                        sample_data = [dict(row) for row in sample_rows]

                        # Get indexes
                        cursor.execute(f"PRAGMA index_list({table_name})")
                        indexes = [idx[1] for idx in cursor.fetchall()]

                        tables[table_name] = {
                            'name': table_name,
                            'columns': columns,
                            'row_count': row_count,
                            'sample_data': sample_data,
                            'indexes': indexes
                        }

                    except Exception as e:
                        tables[table_name] = {'error': str(e)}

                conn.close()
                databases[db_name] = tables

            except Exception as e:
                databases[db_name] = {'error': str(e)}

        return databases

    def _scan_live_metrics(self) -> tuple:
        """Scan key live metrics from database"""
        wallet_counts = {}
        position_counts = {}
        recent_trades = 0
        total_pnl = 0.0

        try:
            conn = sqlite3.connect(str(MAIN_DB))
            cursor = conn.cursor()

            # Wallet counts
            tables_to_count = [
                ('qualified_wallets', 'qualified'),
                ('user_wallets', 'user'),
                ('insider_pool', 'insider'),
                ('copy_pool', 'copy_pool'),
                ('wallet_global_pool', 'global_pool')
            ]

            for table, key in tables_to_count:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    wallet_counts[key] = cursor.fetchone()[0]
                except:
                    wallet_counts[key] = 0

            # Position counts
            try:
                cursor.execute("SELECT status, COUNT(*) FROM position_lifecycle GROUP BY status")
                for row in cursor.fetchall():
                    position_counts[row[0] or 'unknown'] = row[1]

                cursor.execute("SELECT COUNT(*) FROM position_lifecycle")
                position_counts['total'] = cursor.fetchone()[0]
            except:
                position_counts = {'total': 0}

            # Recent trades (last 24h)
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions
                    WHERE timestamp > datetime('now', '-1 day')
                """)
                recent_trades = cursor.fetchone()[0]
            except:
                recent_trades = 0

            # Total PnL
            try:
                cursor.execute("SELECT SUM(pnl_sol) FROM position_lifecycle WHERE pnl_sol IS NOT NULL")
                result = cursor.fetchone()[0]
                total_pnl = float(result) if result else 0.0
            except:
                total_pnl = 0.0

            conn.close()

        except Exception as e:
            print(f"Error scanning live metrics: {e}")

        return wallet_counts, position_counts, recent_trades, total_pnl

    def _scan_services(self) -> List[Dict]:
        """Scan running SoulWinners services"""
        services = []

        service_patterns = [
            ('bot', 'telegram'),
            ('webhook', 'webhook_server'),
            ('monitor', 'run_monitor'),
            ('pipeline', 'run_pipeline'),
            ('hedgehog', 'hedgehog')
        ]

        try:
            # Get all python processes
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=10
            )

            for name, pattern in service_patterns:
                matching_lines = [
                    line for line in result.stdout.split('\n')
                    if pattern.lower() in line.lower() and 'python' in line.lower()
                ]

                if matching_lines:
                    line = matching_lines[0]
                    parts = line.split()
                    services.append({
                        'name': name,
                        'status': 'running',
                        'pid': int(parts[1]) if len(parts) > 1 else None,
                        'cpu_percent': float(parts[2]) if len(parts) > 2 else 0,
                        'memory_mb': float(parts[3]) if len(parts) > 3 else 0,
                        'command': ' '.join(parts[10:]) if len(parts) > 10 else pattern
                    })
                else:
                    services.append({
                        'name': name,
                        'status': 'stopped',
                        'pid': None,
                        'cpu_percent': 0,
                        'memory_mb': 0,
                        'command': ''
                    })

        except Exception as e:
            print(f"Error scanning services: {e}")

        return services

    def _scan_python_files(self) -> Dict[str, Dict]:
        """Scan all Python files and extract their purpose"""
        python_files = {}

        # Key directories to scan
        dirs_to_scan = [
            'bot',
            'pipeline',
            'ml',
            'trader',
            'hedgehog',
            'database',
            'config'
        ]

        for dir_name in dirs_to_scan:
            dir_path = self.base_dir / dir_name
            if not dir_path.exists():
                continue

            for py_file in dir_path.rglob('*.py'):
                try:
                    rel_path = str(py_file.relative_to(self.base_dir))
                    content = py_file.read_text(errors='ignore')

                    # Extract info
                    info = self._analyze_python_file(content, py_file)
                    python_files[rel_path] = info

                except Exception as e:
                    pass  # Skip problematic files

        # Also scan root level files
        for py_file in self.base_dir.glob('*.py'):
            try:
                rel_path = py_file.name
                content = py_file.read_text(errors='ignore')
                info = self._analyze_python_file(content, py_file)
                python_files[rel_path] = info
            except:
                pass

        return python_files

    def _analyze_python_file(self, content: str, file_path: Path) -> Dict:
        """Analyze a Python file to extract its purpose and structure"""
        info = {
            'path': str(file_path),
            'purpose': '',
            'classes': [],
            'functions': [],
            'imports': [],
            'line_count': len(content.split('\n')),
            'last_modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
        }

        try:
            tree = ast.parse(content)

            # Get module docstring
            if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
                docstring = tree.body[0].value.value
                info['purpose'] = docstring.strip().split('\n')[0][:200]  # First line, max 200 chars

            # Extract classes, functions, imports
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    info['classes'].append(node.name)
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    if not node.name.startswith('_'):  # Skip private
                        info['functions'].append(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        info['imports'].append(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        info['imports'].append(node.module.split('.')[0])

            # Dedupe
            info['imports'] = list(set(info['imports']))[:20]
            info['classes'] = info['classes'][:20]
            info['functions'] = info['functions'][:30]

            # Infer purpose from filename if no docstring
            if not info['purpose']:
                name = file_path.stem
                purpose_map = {
                    'bot': 'Telegram bot interface',
                    'commands': 'Command handlers',
                    'trader': 'Trading execution',
                    'tracker': 'Position/lifecycle tracking',
                    'monitor': 'System monitoring',
                    'brain': 'AI decision making',
                    'router': 'Request routing',
                    'tools': 'Tool implementations',
                    'detector': 'Pattern detection',
                    'advisor': 'AI recommendations'
                }
                for key, desc in purpose_map.items():
                    if key in name.lower():
                        info['purpose'] = desc
                        break

        except Exception as e:
            info['purpose'] = f"Parse error: {str(e)[:50]}"

        return info

    def _scan_cron_jobs(self) -> List[Dict]:
        """Scan configured cron jobs"""
        cron_jobs = []

        try:
            # Check crontab
            result = subprocess.run(
                ['crontab', '-l'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split()
                        if len(parts) >= 6:
                            cron_jobs.append({
                                'schedule': ' '.join(parts[:5]),
                                'command': ' '.join(parts[5:]),
                                'source': 'crontab'
                            })

            # Check cron scripts in repo
            cron_scripts = ['cron_pipeline.sh', 'setup_cron.sh']
            for script in cron_scripts:
                script_path = self.base_dir / script
                if script_path.exists():
                    content = script_path.read_text()
                    cron_jobs.append({
                        'schedule': 'see script',
                        'command': script,
                        'source': 'script',
                        'content_preview': content[:200]
                    })

        except Exception as e:
            print(f"Error scanning cron: {e}")

        return cron_jobs

    def _scan_api_keys(self) -> Dict[str, str]:
        """Check status of API keys"""
        api_keys = {}

        try:
            # Check settings.py for Helius keys
            settings_path = self.base_dir / 'config' / 'settings.py'
            if settings_path.exists():
                content = settings_path.read_text()

                # Count Helius API keys
                helius_matches = re.findall(r'["\']([a-f0-9-]{36})["\']', content)
                api_keys['helius_keys'] = f"{len(helius_matches)} keys configured"

            # Check .env for Anthropic key
            env_path = self.base_dir / '.env'
            if env_path.exists():
                env_content = env_path.read_text()
                if 'ANTHROPIC_API_KEY' in env_content:
                    api_keys['anthropic'] = 'configured'
                if 'OPENAI_API_KEY' in env_content or 'openai' in env_content.lower():
                    api_keys['openai'] = 'configured'

            # Check hedgehog config
            hh_config = self.base_dir / 'hedgehog' / 'config.py'
            if hh_config.exists():
                hh_content = hh_config.read_text()
                if 'TELEGRAM_BOT_TOKEN' in hh_content or 'bot_token' in hh_content.lower():
                    api_keys['telegram_hedgehog'] = 'configured'

        except Exception as e:
            api_keys['error'] = str(e)

        return api_keys

    def _scan_config_thresholds(self) -> Dict[str, Any]:
        """Extract all configuration thresholds"""
        thresholds = {}

        try:
            settings_path = self.base_dir / 'config' / 'settings.py'
            if settings_path.exists():
                content = settings_path.read_text()

                # Extract key thresholds using regex
                patterns = [
                    (r'MIN_SOL_BALANCE\s*=\s*([\d.]+)', 'min_sol_balance'),
                    (r'MIN_WIN_RATE\s*=\s*([\d.]+)', 'min_win_rate'),
                    (r'MIN_TRADES\s*=\s*(\d+)', 'min_trades'),
                    (r'MAX_DRAWDOWN\s*=\s*([\d.]+)', 'max_drawdown'),
                    (r'ELITE_PERCENTILE\s*=\s*([\d.]+)', 'elite_percentile'),
                    (r'DAILY_COST_LIMIT\s*=\s*([\d.]+)', 'daily_cost_limit'),
                    (r'MAX_POSITION_SIZE\s*=\s*([\d.]+)', 'max_position_size'),
                ]

                for pattern, name in patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        try:
                            thresholds[name] = float(match.group(1))
                        except:
                            thresholds[name] = match.group(1)

            # Also get hedgehog config
            hh_config = self.base_dir / 'hedgehog' / 'config.py'
            if hh_config.exists():
                hh_content = hh_config.read_text()

                hh_patterns = [
                    (r'DAILY_COST_LIMIT\s*=\s*([\d.]+)', 'hedgehog_daily_cost'),
                    (r'MAX_TOOL_ITERATIONS\s*=\s*(\d+)', 'max_tool_iterations'),
                    (r'DAILY_CLAUDE_LIMIT\s*=\s*(\d+)', 'daily_claude_limit'),
                ]

                for pattern, name in hh_patterns:
                    match = re.search(pattern, hh_content, re.IGNORECASE)
                    if match:
                        try:
                            thresholds[name] = float(match.group(1))
                        except:
                            thresholds[name] = match.group(1)

        except Exception as e:
            thresholds['error'] = str(e)

        return thresholds

    def _scan_git(self) -> Dict:
        """Get git status"""
        git_info = {
            'branch': 'unknown',
            'last_commit': 'unknown',
            'uncommitted': []
        }

        try:
            # Current branch
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                git_info['branch'] = result.stdout.strip()

            # Last commit
            result = subprocess.run(
                ['git', 'log', '-1', '--oneline'],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                git_info['last_commit'] = result.stdout.strip()

            # Uncommitted changes
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                git_info['uncommitted'] = [
                    line.strip() for line in result.stdout.split('\n')
                    if line.strip()
                ][:20]  # Max 20

        except Exception as e:
            git_info['error'] = str(e)

        return git_info

    def _scan_system_health(self) -> Dict:
        """Get system health metrics"""
        health = {
            'disk': 0.0,
            'memory': 0.0,
            'cpu': 0.0
        }

        try:
            # Disk usage
            result = subprocess.run(
                ['df', '-h', str(self.base_dir)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    parts = lines[1].split()
                    if len(parts) >= 5:
                        health['disk'] = float(parts[4].replace('%', ''))

            # Memory usage (macOS)
            result = subprocess.run(
                ['vm_stat'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Parse vm_stat output
                lines = result.stdout.split('\n')
                stats = {}
                for line in lines:
                    if ':' in line:
                        key, val = line.split(':')
                        try:
                            stats[key.strip()] = int(val.strip().replace('.', ''))
                        except:
                            pass

                # Calculate memory usage
                page_size = 4096  # macOS page size
                free = stats.get('Pages free', 0) * page_size
                active = stats.get('Pages active', 0) * page_size
                inactive = stats.get('Pages inactive', 0) * page_size
                wired = stats.get('Pages wired down', 0) * page_size

                total = free + active + inactive + wired
                used = active + wired
                if total > 0:
                    health['memory'] = round((used / total) * 100, 1)

            # CPU usage
            result = subprocess.run(
                ['top', '-l', '1', '-n', '0'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'CPU usage' in line:
                        match = re.search(r'([\d.]+)%\s+user', line)
                        if match:
                            health['cpu'] = float(match.group(1))
                        break

        except Exception as e:
            print(f"Error scanning health: {e}")

        return health

    def _save_state(self):
        """Save state to JSON file"""
        try:
            KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

            # Convert to JSON-serializable format
            state_dict = self._to_dict(self.state)

            with open(STATE_FILE, 'w') as f:
                json.dump(state_dict, f, indent=2, default=str)

            print(f"[HEDGEHOG BRAIN] State saved to {STATE_FILE}")

        except Exception as e:
            print(f"Error saving state: {e}")

    def _to_dict(self, obj) -> Any:
        """Convert dataclass/object to dict recursively"""
        if hasattr(obj, '__dataclass_fields__'):
            return {k: self._to_dict(v) for k, v in asdict(obj).items()}
        elif isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._to_dict(v) for v in obj]
        else:
            return obj

    def load_state(self) -> Optional[SystemState]:
        """Load state from file"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r') as f:
                    data = json.load(f)
                print(f"[HEDGEHOG BRAIN] Loaded state from {STATE_FILE}")
                return data  # Return as dict for easier querying
        except Exception as e:
            print(f"Error loading state: {e}")
        return None

    def get_state_age_minutes(self) -> float:
        """How old is the current state in minutes?"""
        if STATE_FILE.exists():
            mtime = STATE_FILE.stat().st_mtime
            age_seconds = time.time() - mtime
            return age_seconds / 60
        return float('inf')


# Background updater thread
class KnowledgeUpdater:
    """Background thread that keeps knowledge fresh"""

    def __init__(self, scanner: SoulWinnersScanner, interval_minutes: int = 5):
        self.scanner = scanner
        self.interval = interval_minutes * 60  # Convert to seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start background updates"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        print(f"[HEDGEHOG BRAIN] Background updater started (every {self.interval//60} min)")

    def stop(self):
        """Stop background updates"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _update_loop(self):
        """Main update loop"""
        while self._running:
            try:
                time.sleep(self.interval)
                if self._running:
                    print("[HEDGEHOG BRAIN] Running scheduled knowledge update...")
                    self.scanner.scan_all()
            except Exception as e:
                print(f"[HEDGEHOG BRAIN] Update error: {e}")


# Global instances
_scanner: Optional[SoulWinnersScanner] = None
_updater: Optional[KnowledgeUpdater] = None


def get_scanner() -> SoulWinnersScanner:
    """Get or create the global scanner"""
    global _scanner
    if _scanner is None:
        _scanner = SoulWinnersScanner()
    return _scanner


def initialize_knowledge(start_updater: bool = True) -> dict:
    """
    Initialize Hedgehog's knowledge base.
    Call this on startup: python -m hedgehog init
    """
    global _scanner, _updater

    print("=" * 60)
    print("[HEDGEHOG BRAIN] Initializing SoulWinners Knowledge Base")
    print("=" * 60)

    _scanner = SoulWinnersScanner()
    state = _scanner.scan_all()

    if start_updater:
        _updater = KnowledgeUpdater(_scanner, interval_minutes=5)
        _updater.start()

    # Return summary
    state_dict = _scanner.load_state()
    return {
        'status': 'initialized',
        'scan_time': state_dict.get('scan_time'),
        'scan_duration': state_dict.get('scan_duration_seconds'),
        'databases': len(state_dict.get('databases', {})),
        'tables': sum(len(tables) for tables in state_dict.get('databases', {}).values()),
        'python_files': len(state_dict.get('python_files', {})),
        'services': len(state_dict.get('services', [])),
        'wallet_counts': state_dict.get('wallet_counts', {}),
        'position_counts': state_dict.get('position_counts', {}),
    }


def get_knowledge() -> Optional[dict]:
    """Get current knowledge state (from file if not in memory)"""
    scanner = get_scanner()

    # Check if we have fresh state
    age = scanner.get_state_age_minutes()

    if age > 10:  # More than 10 min old, rescan
        print(f"[HEDGEHOG BRAIN] Knowledge is {age:.1f} min old, refreshing...")
        scanner.scan_all()

    return scanner.load_state()


if __name__ == '__main__':
    # Test the scanner
    result = initialize_knowledge(start_updater=False)
    print("\n" + "=" * 60)
    print("INITIALIZATION COMPLETE")
    print("=" * 60)
    print(json.dumps(result, indent=2))
