"""
Hedgehog Self-Healing Skills
Diagnostics, auto-fix, and monitoring capabilities
"""
import json
import os
import sqlite3
import subprocess
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import defaultdict

from skills.base import get_registry

# Configuration
SOULWINNERS_ROOT = Path(os.getenv("SOULWINNERS_PATH", "/root/Soulwinners"))
MEMORY_DIR = Path(__file__).parent.parent / "memory"
HEALTH_REPORT_PATH = MEMORY_DIR / "health_reports.json"

# Services to monitor
MONITORED_SERVICES = [
    "soulwinners-webhook",
    "soulwinners-scanner",
    "hedgehog-telegram",
    "postgresql",
    "nginx",
]

# Log paths to check
LOG_PATHS = [
    SOULWINNERS_ROOT / "logs" / "webhook.log",
    SOULWINNERS_ROOT / "logs" / "scanner.log",
    SOULWINNERS_ROOT / "logs" / "error.log",
    Path("/var/log/syslog"),
]


# =============================================================================
# DIAGNOSTICS
# =============================================================================

def run_system_diagnostics() -> Dict:
    """
    Run comprehensive system diagnostics

    Checks:
    - All monitored services
    - Database connectivity
    - API key status
    - Disk space
    - Memory usage
    - Recent errors

    Returns:
        Dict with diagnostic results
    """
    results = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy",
        "issues_found": 0,
        "checks": {},
    }

    issues = []

    # Check services
    service_results = []
    for service in MONITORED_SERVICES:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                timeout=5,
            )
            is_active = result.stdout.strip() == "active"
            service_results.append({
                "service": service,
                "status": "running" if is_active else "stopped",
            })
            if not is_active:
                issues.append(f"Service {service} is not running")
        except Exception as e:
            service_results.append({
                "service": service,
                "status": "unknown",
                "error": str(e),
            })

    results["checks"]["services"] = service_results

    # Check database
    try:
        db_path = SOULWINNERS_ROOT / "soulwinners.db"
        if db_path.exists():
            conn = sqlite3.connect(db_path, timeout=5)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sqlite_master")
            conn.close()
            results["checks"]["database"] = {"status": "connected", "path": str(db_path)}
        else:
            results["checks"]["database"] = {"status": "not_found", "path": str(db_path)}
            issues.append("Database file not found")
    except Exception as e:
        results["checks"]["database"] = {"status": "error", "error": str(e)}
        issues.append(f"Database error: {str(e)}")

    # Check API keys
    api_keys = {
        "HELIUS_API_KEY": bool(os.getenv("HELIUS_API_KEY")),
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "TELEGRAM_BOT_TOKEN": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
    }
    missing_keys = [k for k, v in api_keys.items() if not v]
    results["checks"]["api_keys"] = {
        "configured": api_keys,
        "missing": missing_keys,
    }
    if missing_keys:
        issues.append(f"Missing API keys: {', '.join(missing_keys)}")

    # Check disk space
    try:
        result = subprocess.run(
            ["df", "-h", "/"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            disk_use = parts[4].replace("%", "") if len(parts) >= 5 else "0"
            results["checks"]["disk_space"] = {
                "usage_percent": int(disk_use),
                "status": "critical" if int(disk_use) > 90 else "warning" if int(disk_use) > 80 else "ok",
            }
            if int(disk_use) > 90:
                issues.append(f"Disk usage critical: {disk_use}%")
    except Exception as e:
        results["checks"]["disk_space"] = {"error": str(e)}

    # Check memory
    try:
        result = subprocess.run(
            ["free", "-m"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 3:
                total = int(parts[1])
                used = int(parts[2])
                percent = (used / total * 100) if total > 0 else 0
                results["checks"]["memory"] = {
                    "total_mb": total,
                    "used_mb": used,
                    "percent": round(percent, 1),
                    "status": "critical" if percent > 90 else "warning" if percent > 80 else "ok",
                }
                if percent > 90:
                    issues.append(f"Memory usage critical: {percent:.1f}%")
    except Exception as e:
        results["checks"]["memory"] = {"error": str(e)}

    # Count recent errors
    error_count = 0
    try:
        for log_path in LOG_PATHS:
            if log_path.exists():
                content = log_path.read_text().split("\n")[-100:]  # Last 100 lines
                error_count += sum(1 for line in content if "error" in line.lower())
        results["checks"]["recent_errors"] = {
            "count_last_100_lines": error_count,
            "status": "warning" if error_count > 10 else "ok",
        }
        if error_count > 20:
            issues.append(f"High error count in logs: {error_count}")
    except Exception as e:
        results["checks"]["recent_errors"] = {"error": str(e)}

    # Set overall status
    results["issues_found"] = len(issues)
    results["issues"] = issues
    if len(issues) >= 3:
        results["overall_status"] = "critical"
    elif len(issues) >= 1:
        results["overall_status"] = "degraded"

    # Save report
    _save_health_report(results)

    return results


def identify_issues() -> Dict:
    """
    Identify current system issues

    Returns:
        Dict with list of detected problems and severity
    """
    diagnostics = run_system_diagnostics()

    issues = []

    for issue in diagnostics.get("issues", []):
        severity = "high"
        if "not running" in issue:
            severity = "critical"
        elif "warning" in issue.lower():
            severity = "medium"

        issues.append({
            "description": issue,
            "severity": severity,
            "detected_at": datetime.now().isoformat(),
        })

    # Check for additional patterns
    # Rate limiting issues
    try:
        from skills.soulwinners import check_api_rate_limits
        rate_limits = check_api_rate_limits()
        rate_limited_keys = [
            k for k in rate_limits.get("keys", [])
            if k.get("status") == "rate_limited"
        ]
        if rate_limited_keys:
            issues.append({
                "description": f"{len(rate_limited_keys)} API key(s) rate limited",
                "severity": "high",
                "auto_fix_available": True,
                "fix_action": "rotate_api_key",
            })
    except:
        pass

    return {
        "total_issues": len(issues),
        "critical": sum(1 for i in issues if i["severity"] == "critical"),
        "high": sum(1 for i in issues if i["severity"] == "high"),
        "medium": sum(1 for i in issues if i["severity"] == "medium"),
        "issues": issues,
    }


def get_error_patterns(hours: int = 24) -> Dict:
    """
    Analyze logs for recurring error patterns

    Args:
        hours: Hours of logs to analyze

    Returns:
        Dict with error patterns and frequencies
    """
    patterns = defaultdict(int)
    error_lines = []

    for log_path in LOG_PATHS:
        if not log_path.exists():
            continue

        try:
            content = log_path.read_text().split("\n")

            for line in content:
                if "error" in line.lower() or "exception" in line.lower():
                    error_lines.append(line)

                    # Extract error type
                    if "ConnectionError" in line:
                        patterns["ConnectionError"] += 1
                    elif "TimeoutError" in line or "timeout" in line.lower():
                        patterns["Timeout"] += 1
                    elif "RateLimitError" in line or "rate limit" in line.lower():
                        patterns["RateLimit"] += 1
                    elif "DatabaseError" in line or "sqlite" in line.lower():
                        patterns["Database"] += 1
                    elif "PermissionError" in line:
                        patterns["Permission"] += 1
                    elif "KeyError" in line:
                        patterns["KeyError"] += 1
                    elif "ValueError" in line:
                        patterns["ValueError"] += 1
                    else:
                        patterns["Other"] += 1
        except Exception:
            continue

    sorted_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)

    return {
        "period_hours": hours,
        "total_errors": sum(patterns.values()),
        "patterns": [{"type": k, "count": v} for k, v in sorted_patterns],
        "most_common": sorted_patterns[0] if sorted_patterns else None,
        "sample_errors": error_lines[-10:],  # Last 10 errors
    }


# =============================================================================
# AUTO-FIX
# =============================================================================

def fix_rate_limits() -> Dict:
    """
    Auto-fix rate limiting by rotating API keys

    This is safe to run automatically.

    Returns:
        Dict with fix result
    """
    try:
        from skills.soulwinners import rotate_api_key
        result = rotate_api_key()

        if result.get("success"):
            _log_auto_fix("rate_limit_rotation", result)

        return {
            "action": "rotate_api_key",
            "result": result,
            "auto_fixed": result.get("success", False),
        }
    except Exception as e:
        return {"error": str(e)}


def restart_failed_service(service_name: str) -> Dict:
    """
    Restart a failed service

    REQUIRES APPROVAL - Service restart

    Args:
        service_name: Name of service to restart

    Returns:
        Dict with restart result
    """
    if service_name not in MONITORED_SERVICES:
        return {
            "error": f"Service '{service_name}' not in monitored services",
            "allowed_services": MONITORED_SERVICES,
        }

    try:
        # Check if actually failed
        check = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )

        was_running = check.stdout.strip() == "active"

        # Restart
        result = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify
        verify = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )

        now_running = verify.stdout.strip() == "active"

        fix_result = {
            "service": service_name,
            "was_running": was_running,
            "now_running": now_running,
            "success": now_running,
        }

        _log_auto_fix("service_restart", fix_result)

        return fix_result

    except Exception as e:
        return {"error": str(e), "service": service_name}


def clear_database_locks() -> Dict:
    """
    Clear stuck database locks

    Safe to run automatically - only clears stale locks.

    Returns:
        Dict with result
    """
    try:
        db_path = SOULWINNERS_ROOT / "soulwinners.db"

        if not db_path.exists():
            return {"error": "Database not found"}

        # Check for lock file
        lock_file = Path(str(db_path) + "-journal")
        wal_file = Path(str(db_path) + "-wal")

        locks_cleared = []

        if lock_file.exists():
            # Check if stale (older than 5 minutes)
            mtime = lock_file.stat().st_mtime
            age = datetime.now().timestamp() - mtime

            if age > 300:  # 5 minutes
                lock_file.unlink()
                locks_cleared.append("journal")

        # Try checkpoint for WAL mode
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            locks_cleared.append("wal_checkpoint")
        except:
            pass

        result = {
            "locks_cleared": locks_cleared,
            "success": True,
        }

        if locks_cleared:
            _log_auto_fix("clear_db_locks", result)

        return result

    except Exception as e:
        return {"error": str(e)}


def optimize_database() -> Dict:
    """
    Optimize database - VACUUM and rebuild indexes

    Safe to run automatically, but may take time.

    Returns:
        Dict with optimization result
    """
    try:
        db_path = SOULWINNERS_ROOT / "soulwinners.db"

        if not db_path.exists():
            return {"error": "Database not found"}

        # Get size before
        size_before = db_path.stat().st_size

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Run VACUUM
        conn.execute("VACUUM")

        # Rebuild indexes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = cursor.fetchall()

        for (index_name,) in indexes:
            if index_name and not index_name.startswith("sqlite_"):
                try:
                    cursor.execute(f"REINDEX {index_name}")
                except:
                    pass

        # Analyze
        conn.execute("ANALYZE")

        conn.close()

        # Get size after
        size_after = db_path.stat().st_size
        saved = size_before - size_after

        result = {
            "success": True,
            "size_before_mb": round(size_before / 1024 / 1024, 2),
            "size_after_mb": round(size_after / 1024 / 1024, 2),
            "saved_mb": round(saved / 1024 / 1024, 2),
            "indexes_rebuilt": len(indexes),
        }

        _log_auto_fix("db_optimization", result)

        return result

    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# MONITORING
# =============================================================================

def setup_health_check(interval_minutes: int = 5) -> Dict:
    """
    Configure health check monitoring interval

    Args:
        interval_minutes: How often to run health checks

    Returns:
        Dict with configuration status
    """
    config_path = MEMORY_DIR / "monitoring_config.json"
    config_path.parent.mkdir(exist_ok=True)

    config = {
        "interval_minutes": interval_minutes,
        "enabled": True,
        "last_check": None,
        "configured_at": datetime.now().isoformat(),
    }

    config_path.write_text(json.dumps(config, indent=2))

    return {
        "success": True,
        "interval_minutes": interval_minutes,
        "note": "Health checks will run at configured interval",
    }


def alert_on_issue(severity: str = "high") -> Dict:
    """
    Auto-alert on issues above severity threshold

    Args:
        severity: Minimum severity to alert on (low/medium/high/critical)

    Returns:
        Dict with alert configuration
    """
    config_path = MEMORY_DIR / "alert_config.json"
    config_path.parent.mkdir(exist_ok=True)

    severity_levels = ["low", "medium", "high", "critical"]
    if severity not in severity_levels:
        return {"error": f"Invalid severity. Use: {severity_levels}"}

    config = {
        "alert_threshold": severity,
        "enabled": True,
        "configured_at": datetime.now().isoformat(),
    }

    config_path.write_text(json.dumps(config, indent=2))

    return {
        "success": True,
        "alert_threshold": severity,
        "note": f"Will alert on {severity} and above issues",
    }


def generate_health_report() -> Dict:
    """
    Generate comprehensive daily health report

    Returns:
        Dict with full system health summary
    """
    # Run fresh diagnostics
    diagnostics = run_system_diagnostics()

    # Get error patterns
    errors = get_error_patterns(24)

    # Get issues
    issues = identify_issues()

    # Load historical data
    history = []
    if HEALTH_REPORT_PATH.exists():
        try:
            history = json.loads(HEALTH_REPORT_PATH.read_text())[-24:]  # Last 24 reports
        except:
            pass

    # Calculate trends
    if len(history) >= 2:
        prev_issues = history[-2].get("issues_found", 0) if len(history) >= 2 else 0
        curr_issues = diagnostics.get("issues_found", 0)
        trend = "improving" if curr_issues < prev_issues else "degrading" if curr_issues > prev_issues else "stable"
    else:
        trend = "unknown"

    report = {
        "report_time": datetime.now().isoformat(),
        "overall_status": diagnostics.get("overall_status"),
        "trend": trend,
        "summary": {
            "total_issues": issues.get("total_issues"),
            "critical_issues": issues.get("critical"),
            "services_running": sum(
                1 for s in diagnostics.get("checks", {}).get("services", [])
                if s.get("status") == "running"
            ),
            "total_services": len(MONITORED_SERVICES),
            "errors_24h": errors.get("total_errors"),
            "most_common_error": errors.get("most_common"),
        },
        "checks": diagnostics.get("checks"),
        "issues": issues.get("issues"),
        "recommendations": _generate_recommendations(diagnostics, errors, issues),
    }

    return report


def _generate_recommendations(diagnostics: Dict, errors: Dict, issues: Dict) -> List[str]:
    """Generate actionable recommendations based on diagnostics"""
    recommendations = []

    # Service recommendations
    for service in diagnostics.get("checks", {}).get("services", []):
        if service.get("status") != "running":
            recommendations.append(f"Restart {service['service']} service")

    # Disk space
    disk = diagnostics.get("checks", {}).get("disk_space", {})
    if disk.get("usage_percent", 0) > 80:
        recommendations.append("Clean up disk space - consider removing old logs")

    # Memory
    memory = diagnostics.get("checks", {}).get("memory", {})
    if memory.get("percent", 0) > 80:
        recommendations.append("High memory usage - consider restarting services")

    # Error patterns
    if errors.get("total_errors", 0) > 50:
        most_common = errors.get("most_common")
        if most_common:
            recommendations.append(f"Investigate {most_common[0]} errors ({most_common[1]} occurrences)")

    # Database
    if diagnostics.get("checks", {}).get("database", {}).get("status") == "error":
        recommendations.append("Check database connectivity and locks")

    return recommendations


def _save_health_report(report: Dict):
    """Save health report to history"""
    HEALTH_REPORT_PATH.parent.mkdir(exist_ok=True)

    if HEALTH_REPORT_PATH.exists():
        try:
            history = json.loads(HEALTH_REPORT_PATH.read_text())
        except:
            history = []
    else:
        history = []

    history.append(report)
    history = history[-100:]  # Keep last 100 reports

    HEALTH_REPORT_PATH.write_text(json.dumps(history, indent=2, default=str))


def _log_auto_fix(action: str, result: Dict):
    """Log auto-fix action"""
    log_path = MEMORY_DIR / "auto_fix_log.json"
    log_path.parent.mkdir(exist_ok=True)

    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text())
        except:
            logs = []
    else:
        logs = []

    logs.append({
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "result": result,
    })

    logs = logs[-500:]
    log_path.write_text(json.dumps(logs, indent=2, default=str))


# =============================================================================
# REGISTER ALL SKILLS
# =============================================================================

registry = get_registry()

# Diagnostics
@registry.register(
    name="run_system_diagnostics",
    description="Run comprehensive system diagnostics (services, DB, APIs, disk, memory)",
    parameters=[]
)
def _run_system_diagnostics() -> Dict:
    return run_system_diagnostics()


@registry.register(
    name="identify_issues",
    description="Identify current system issues with severity levels",
    parameters=[]
)
def _identify_issues() -> Dict:
    return identify_issues()


@registry.register(
    name="get_error_patterns",
    description="Analyze logs for recurring error patterns",
    parameters=[
        {"name": "hours", "type": "int", "description": "Hours to analyze", "optional": True}
    ]
)
def _get_error_patterns(hours: int = 24) -> Dict:
    return get_error_patterns(hours)


# Auto-fix
@registry.register(
    name="fix_rate_limits",
    description="Auto-fix rate limiting by rotating API keys (safe to auto-run)",
    parameters=[]
)
def _fix_rate_limits() -> Dict:
    return fix_rate_limits()


@registry.register(
    name="restart_failed_service",
    description="Restart a failed service (REQUIRES APPROVAL)",
    parameters=[
        {"name": "service_name", "type": "str", "description": "Service to restart"}
    ]
)
def _restart_failed_service(service_name: str) -> Dict:
    return restart_failed_service(service_name)


@registry.register(
    name="clear_database_locks",
    description="Clear stuck database locks (safe to auto-run)",
    parameters=[]
)
def _clear_database_locks() -> Dict:
    return clear_database_locks()


@registry.register(
    name="optimize_database",
    description="Optimize database - VACUUM and rebuild indexes (safe to auto-run)",
    parameters=[]
)
def _optimize_database() -> Dict:
    return optimize_database()


# Monitoring
@registry.register(
    name="setup_health_check",
    description="Configure health check monitoring interval",
    parameters=[
        {"name": "interval_minutes", "type": "int", "description": "Check interval in minutes", "optional": True}
    ]
)
def _setup_health_check(interval_minutes: int = 5) -> Dict:
    return setup_health_check(interval_minutes)


@registry.register(
    name="alert_on_issue",
    description="Configure auto-alerting on issues",
    parameters=[
        {"name": "severity", "type": "str", "description": "Minimum severity (low/medium/high/critical)", "optional": True}
    ]
)
def _alert_on_issue(severity: str = "high") -> Dict:
    return alert_on_issue(severity)


@registry.register(
    name="generate_health_report",
    description="Generate comprehensive system health report",
    parameters=[]
)
def _generate_health_report() -> Dict:
    return generate_health_report()
