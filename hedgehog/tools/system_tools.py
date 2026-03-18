"""
System Tools for Hedgehog

Tools for system monitoring, service management, and log analysis.
"""
import asyncio
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Tool, ToolResult, SafetyLevel


class SystemStatusTool(Tool):
    """Get system status and resource usage."""

    name = "system_status"
    description = """Get current system status including:
    - CPU and memory usage
    - Disk space
    - Running processes
    - Service health"""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "include_processes": {
                "type": "boolean",
                "description": "Include process list (default False)",
                "default": False
            }
        },
        "required": []
    }

    async def execute(self, include_processes: bool = False) -> ToolResult:
        """Get system status."""
        try:
            import psutil
        except ImportError:
            # Fallback without psutil
            return await self._execute_basic()

        try:
            # CPU and memory
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()

            # Disk
            disk = psutil.disk_usage("/")

            # System info
            status = {
                "timestamp": datetime.now().isoformat(),
                "cpu_percent": cpu_percent,
                "memory": {
                    "total_gb": round(memory.total / (1024**3), 2),
                    "used_gb": round(memory.used / (1024**3), 2),
                    "percent": memory.percent,
                },
                "disk": {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "percent": disk.percent,
                },
                "load_average": list(os.getloadavg()) if hasattr(os, 'getloadavg') else None,
            }

            # Process list if requested
            if include_processes:
                processes = []
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                    try:
                        info = proc.info
                        if info['cpu_percent'] > 1 or info['memory_percent'] > 1:
                            processes.append(info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                status["top_processes"] = sorted(
                    processes,
                    key=lambda x: x.get('cpu_percent', 0),
                    reverse=True
                )[:10]

            return ToolResult(success=True, data=status)

        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _execute_basic(self) -> ToolResult:
        """Basic execution without psutil."""
        try:
            # Get basic info via subprocess
            result = subprocess.run(
                ["uptime"],
                capture_output=True,
                text=True,
                timeout=5
            )
            uptime = result.stdout.strip() if result.returncode == 0 else "unknown"

            result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True,
                text=True,
                timeout=5
            )
            disk = result.stdout.strip() if result.returncode == 0 else "unknown"

            return ToolResult(
                success=True,
                data={
                    "timestamp": datetime.now().isoformat(),
                    "uptime": uptime,
                    "disk": disk,
                    "note": "Install psutil for detailed metrics"
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ServiceRestartTool(Tool):
    """Restart a SoulWinners service."""

    name = "service_restart"
    description = """Restart a SoulWinners service (bot, monitor, webhook).
    This is a RISKY operation that requires confirmation."""

    safety_level = SafetyLevel.RISKY
    parameters_schema = {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "enum": ["bot", "monitor", "webhook", "pipeline"],
                "description": "Service to restart"
            },
            "reason": {
                "type": "string",
                "description": "Reason for restart (logged)"
            }
        },
        "required": ["service", "reason"]
    }

    # Service commands
    SERVICE_COMMANDS = {
        "bot": "python run_bot.py",
        "monitor": "python run_monitor.py",
        "webhook": "python webhook_server.py --port 8080",
        "pipeline": "python run_pipeline.py",
    }

    async def execute(self, service: str, reason: str) -> ToolResult:
        """Restart a service."""
        if service not in self.SERVICE_COMMANDS:
            return ToolResult(
                success=False,
                error=f"Unknown service: {service}"
            )

        try:
            # Log the restart
            self.logger.warning(f"Restarting service '{service}': {reason}")

            # Find and kill existing process
            result = subprocess.run(
                ["pkill", "-f", self.SERVICE_COMMANDS[service]],
                capture_output=True,
                timeout=5
            )

            # Wait for process to terminate
            await asyncio.sleep(2)

            # Start new process
            base_dir = Path(__file__).parent.parent.parent
            cmd = self.SERVICE_COMMANDS[service]

            # Start in background
            process = subprocess.Popen(
                cmd.split(),
                cwd=str(base_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            await asyncio.sleep(2)

            # Check if started
            if process.poll() is None:
                return ToolResult(
                    success=True,
                    data={
                        "service": service,
                        "pid": process.pid,
                        "reason": reason,
                        "status": "started"
                    }
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Service {service} failed to start"
                )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Timeout during restart")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class LogAnalysisTool(Tool):
    """Analyze log files for errors and patterns."""

    name = "log_analysis"
    description = """Analyze log files for errors, warnings, and patterns.
    Returns recent errors, warning counts, and anomalies."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "log_file": {
                "type": "string",
                "description": "Log file to analyze (bot.log, webhook.log, etc.)",
                "default": "bot.log"
            },
            "lines": {
                "type": "integer",
                "description": "Number of recent lines to analyze (default 500)",
                "default": 500
            },
            "level": {
                "type": "string",
                "enum": ["ERROR", "WARNING", "INFO", "all"],
                "description": "Filter by log level",
                "default": "ERROR"
            }
        },
        "required": []
    }

    async def execute(
        self,
        log_file: str = "bot.log",
        lines: int = 500,
        level: str = "ERROR"
    ) -> ToolResult:
        """Analyze log file."""
        try:
            base_dir = Path(__file__).parent.parent.parent
            log_path = base_dir / "logs" / log_file

            if not log_path.exists():
                return ToolResult(
                    success=False,
                    error=f"Log file not found: {log_path}"
                )

            # Read recent lines
            with open(log_path, 'r') as f:
                all_lines = f.readlines()

            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

            # Count by level
            counts = {"ERROR": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
            errors = []
            warnings = []

            for line in recent_lines:
                for lvl in counts:
                    if f" - {lvl} - " in line:
                        counts[lvl] += 1
                        if lvl == "ERROR":
                            errors.append(line.strip()[:200])
                        elif lvl == "WARNING" and len(warnings) < 10:
                            warnings.append(line.strip()[:200])
                        break

            # Filter based on requested level
            if level == "ERROR":
                filtered = errors[-20:]  # Last 20 errors
            elif level == "WARNING":
                filtered = warnings[-20:]
            else:
                filtered = [l.strip()[:200] for l in recent_lines[-20:]]

            return ToolResult(
                success=True,
                data={
                    "log_file": log_file,
                    "lines_analyzed": len(recent_lines),
                    "counts": counts,
                    "recent_entries": filtered,
                    "error_rate": round(counts["ERROR"] / max(len(recent_lines), 1) * 100, 2),
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ProcessListTool(Tool):
    """List SoulWinners-related processes."""

    name = "process_list"
    description = """List all SoulWinners-related processes.
    Shows running bots, monitors, and webhook servers."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    PATTERNS = [
        "run_bot.py",
        "run_monitor.py",
        "webhook_server.py",
        "run_pipeline.py",
        "run_insider.py",
        "soulwinners",
    ]

    async def execute(self) -> ToolResult:
        """List SoulWinners processes."""
        try:
            processes = []

            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return ToolResult(success=False, error="Failed to list processes")

            for line in result.stdout.split('\n'):
                for pattern in self.PATTERNS:
                    if pattern.lower() in line.lower():
                        parts = line.split()
                        if len(parts) >= 11:
                            processes.append({
                                "user": parts[0],
                                "pid": parts[1],
                                "cpu": parts[2],
                                "mem": parts[3],
                                "command": " ".join(parts[10:])[:100],
                            })
                        break

            return ToolResult(
                success=True,
                data={
                    "processes": processes,
                    "count": len(processes),
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Process list timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class HealthCheckTool(Tool):
    """Check health of all SoulWinners services."""

    name = "health_check"
    description = """Check health of all SoulWinners services.
    Returns status of bot, webhook, database, and external APIs."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": []
    }

    async def execute(self) -> ToolResult:
        """Check service health."""
        import aiohttp
        from database import get_connection

        health = {
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "overall": "healthy"
        }

        # Check database
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
            count = cursor.fetchone()[0]
            conn.close()
            health["services"]["database"] = {
                "status": "healthy",
                "wallet_count": count
            }
        except Exception as e:
            health["services"]["database"] = {"status": "unhealthy", "error": str(e)}
            health["overall"] = "degraded"

        # Check webhook server
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "http://localhost:8080/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        health["services"]["webhook"] = {"status": "healthy"}
                    else:
                        health["services"]["webhook"] = {
                            "status": "unhealthy",
                            "http_code": response.status
                        }
        except Exception as e:
            health["services"]["webhook"] = {"status": "not_running", "error": str(e)}

        # Check DexScreener API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    health["services"]["dexscreener"] = {
                        "status": "healthy" if response.status == 200 else "degraded",
                        "response_time_ms": response.headers.get('x-response-time', 'unknown')
                    }
        except Exception as e:
            health["services"]["dexscreener"] = {"status": "unreachable", "error": str(e)}

        return ToolResult(success=True, data=health)


class CodebaseSearchTool(Tool):
    """Search the codebase to understand how things work."""

    name = "codebase_search"
    description = """Search codebase for functions, classes, or patterns.
    Use this to understand how the system works before taking action."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term (function name, class, error message, etc.)"
            },
            "file_type": {
                "type": "string",
                "description": "File extension filter (py, js, sql, etc.)",
                "default": "py"
            },
            "context_lines": {
                "type": "integer",
                "description": "Lines of context around matches (default 3)",
                "default": 3
            }
        },
        "required": ["query"]
    }

    async def execute(
        self, query: str, file_type: str = "py", context_lines: int = 3
    ) -> ToolResult:
        """Search codebase for a pattern."""
        try:
            base_dir = Path(__file__).parent.parent.parent

            # Use grep for search
            result = subprocess.run(
                [
                    "grep", "-rn", f"--include=*.{file_type}",
                    f"-C{context_lines}", query, str(base_dir)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            matches = []
            current_file = None
            current_match = []

            for line in result.stdout.split('\n')[:100]:  # Limit output
                if line.startswith(str(base_dir)):
                    if current_match:
                        matches.append({
                            "file": current_file,
                            "content": "\n".join(current_match)
                        })
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        current_file = parts[0].replace(str(base_dir) + "/", "")
                        current_match = [f"L{parts[1]}: {parts[2]}"]
                elif line.strip() and current_match:
                    current_match.append(line)

            if current_match:
                matches.append({
                    "file": current_file,
                    "content": "\n".join(current_match)
                })

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "matches": matches[:20],  # Limit to 20 matches
                    "total_matches": len(matches),
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Search timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitHistoryTool(Tool):
    """Check recent git changes to understand what changed."""

    name = "git_history"
    description = """Check recent git commits and changes.
    Useful for debugging: 'what changed recently that might have broken X?'"""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of commits to show (default 10)",
                "default": 10
            },
            "file_path": {
                "type": "string",
                "description": "Filter to specific file/directory (optional)"
            },
            "show_diff": {
                "type": "boolean",
                "description": "Include file changes in output (default False)",
                "default": False
            }
        },
        "required": []
    }

    async def execute(
        self, limit: int = 10, file_path: str = None, show_diff: bool = False
    ) -> ToolResult:
        """Get recent git history."""
        try:
            base_dir = Path(__file__).parent.parent.parent

            # Get recent commits
            cmd = [
                "git", "log", f"-{limit}",
                "--pretty=format:%h|%s|%ar|%an",
            ]
            if file_path:
                cmd.append("--")
                cmd.append(file_path)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(base_dir)
            )

            commits = []
            for line in result.stdout.split('\n'):
                if '|' in line:
                    parts = line.split('|', 3)
                    if len(parts) >= 4:
                        commits.append({
                            "hash": parts[0],
                            "message": parts[1][:80],
                            "time": parts[2],
                            "author": parts[3],
                        })

            # Get changed files if requested
            changes = []
            if show_diff and commits:
                result = subprocess.run(
                    ["git", "diff", "--name-status", f"HEAD~{min(limit, 5)}..HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(base_dir)
                )
                for line in result.stdout.split('\n'):
                    if line.strip():
                        parts = line.split('\t', 1)
                        if len(parts) == 2:
                            changes.append({
                                "status": {"M": "modified", "A": "added", "D": "deleted"}.get(parts[0], parts[0]),
                                "file": parts[1],
                            })

            # Get current branch
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(base_dir)
            )
            current_branch = branch_result.stdout.strip()

            return ToolResult(
                success=True,
                data={
                    "branch": current_branch,
                    "recent_commits": commits,
                    "changed_files": changes if show_diff else None,
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Git command timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class AutoHealTool(Tool):
    """Proactively check and fix common issues."""

    name = "auto_heal"
    description = """Automatically diagnose and fix common issues.
    Safe fixes are applied immediately. Reports what was fixed."""

    safety_level = SafetyLevel.SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "check_only": {
                "type": "boolean",
                "description": "Only diagnose, don't fix (default False)",
                "default": False
            }
        },
        "required": []
    }

    async def execute(self, check_only: bool = False) -> ToolResult:
        """Run auto-healing checks."""
        issues = []
        fixes = []

        base_dir = Path(__file__).parent.parent.parent

        # Check 1: Database connectivity
        try:
            from database import get_connection
            conn = get_connection()
            conn.execute("SELECT 1")
            conn.close()
        except Exception as e:
            issues.append(f"Database: {e}")

        # Check 2: Log files growing too large
        logs_dir = base_dir / "logs"
        if logs_dir.exists():
            for log_file in logs_dir.glob("*.log"):
                size_mb = log_file.stat().st_size / (1024 * 1024)
                if size_mb > 100:
                    issues.append(f"Log file too large: {log_file.name} ({size_mb:.0f}MB)")
                    if not check_only:
                        # Truncate to last 10000 lines
                        try:
                            with open(log_file, 'r') as f:
                                lines = f.readlines()
                            with open(log_file, 'w') as f:
                                f.writelines(lines[-10000:])
                            fixes.append(f"Truncated {log_file.name}")
                        except Exception:
                            pass

        # Check 3: Stale PID files
        for pid_file in base_dir.glob("*.pid"):
            try:
                pid = int(pid_file.read_text().strip())
                # Check if process exists
                os.kill(pid, 0)
            except (ValueError, OSError):
                issues.append(f"Stale PID file: {pid_file.name}")
                if not check_only:
                    pid_file.unlink()
                    fixes.append(f"Removed stale {pid_file.name}")

        # Check 4: Temp files older than 1 day
        tmp_dir = base_dir / "tmp"
        if tmp_dir.exists():
            import time
            now = time.time()
            for tmp_file in tmp_dir.glob("*"):
                if now - tmp_file.stat().st_mtime > 86400:
                    issues.append(f"Old temp file: {tmp_file.name}")
                    if not check_only:
                        tmp_file.unlink()
                        fixes.append(f"Cleaned {tmp_file.name}")

        return ToolResult(
            success=True,
            data={
                "issues_found": len(issues),
                "issues": issues,
                "fixes_applied": fixes if not check_only else [],
                "status": "healthy" if not issues else "needs_attention",
            }
        )
