"""
Hedgehog SoulWinners Skills
Deep integration with SoulWinners trading system
"""
import json
import os
import pickle
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from skills.base import get_registry

# Configurable paths
SOULWINNERS_ROOT = Path(os.getenv("SOULWINNERS_PATH", "/root/Soulwinners"))
SOULWINNERS_DB = SOULWINNERS_ROOT / "soulwinners.db"
ML_MODEL_PATH = SOULWINNERS_ROOT / "best_predictor.pkl"
WEBHOOK_LOG = SOULWINNERS_ROOT / "logs" / "webhook.log"
CRON_LOG = SOULWINNERS_ROOT / "logs" / "cron.log"

# Helius API keys (check these paths/env vars)
HELIUS_KEYS_ENV = [
    "HELIUS_API_KEY",
    "HELIUS_API_KEY_2",
    "HELIUS_API_KEY_3",
    "HELIUS_API_KEY_4",
    "HELIUS_API_KEY_5",
]


def _get_db_connection():
    """Get database connection"""
    if not SOULWINNERS_DB.exists():
        raise FileNotFoundError(f"SoulWinners database not found: {SOULWINNERS_DB}")
    conn = sqlite3.connect(SOULWINNERS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _query_db(sql: str, params: tuple = ()) -> List[Dict]:
    """Execute query and return results as list of dicts"""
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# =============================================================================
# WEBHOOK MANAGEMENT
# =============================================================================

def check_webhook_health() -> Dict:
    """
    Check webhook service health and stats

    Returns:
        Dict with running status, uptime, and recent activity
    """
    result = {
        "running": False,
        "pid": None,
        "uptime": None,
        "recent_requests": 0,
        "last_request": None,
        "errors_24h": 0,
    }

    # Check if webhook process is running
    try:
        ps_result = subprocess.run(
            ["pgrep", "-f", "webhook"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if ps_result.returncode == 0:
            result["running"] = True
            result["pid"] = ps_result.stdout.strip().split("\n")[0]
    except Exception as e:
        result["error"] = str(e)

    # Check webhook log for recent activity
    if WEBHOOK_LOG.exists():
        try:
            # Count recent requests (last 24h)
            yesterday = datetime.now() - timedelta(hours=24)
            log_content = WEBHOOK_LOG.read_text().split("\n")[-1000:]  # Last 1000 lines

            request_count = 0
            error_count = 0
            last_timestamp = None

            for line in log_content:
                if "request" in line.lower() or "position" in line.lower():
                    request_count += 1
                if "error" in line.lower():
                    error_count += 1
                # Try to extract timestamp
                if line and line[0].isdigit():
                    last_timestamp = line[:19]  # Assume ISO format start

            result["recent_requests"] = request_count
            result["errors_24h"] = error_count
            result["last_request"] = last_timestamp
        except Exception as e:
            result["log_error"] = str(e)

    return result


def get_webhook_positions(hours: int = 24) -> Dict:
    """
    Get recent positions received via webhook

    Args:
        hours: Number of hours to look back (default 24)

    Returns:
        Dict with position counts and recent entries
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Get position counts by source
        positions = _query_db("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN source = 'webhook' THEN 1 ELSE 0 END) as webhook_count,
                SUM(CASE WHEN source = 'scanner' THEN 1 ELSE 0 END) as scanner_count
            FROM positions
            WHERE created_at >= ?
        """, (cutoff_str,))

        # Get recent webhook positions
        recent = _query_db("""
            SELECT token_address, entry_price, current_price, pnl_percent, created_at
            FROM positions
            WHERE created_at >= ? AND source = 'webhook'
            ORDER BY created_at DESC
            LIMIT 10
        """, (cutoff_str,))

        return {
            "period_hours": hours,
            "total_positions": positions[0]["total"] if positions else 0,
            "webhook_positions": positions[0]["webhook_count"] if positions else 0,
            "scanner_positions": positions[0]["scanner_count"] if positions else 0,
            "recent_webhook": recent,
        }
    except Exception as e:
        return {"error": str(e)}


def restart_webhook() -> Dict:
    """
    Restart the webhook service

    REQUIRES APPROVAL - This restarts a critical service

    Returns:
        Dict with restart status
    """
    try:
        # Try systemctl first
        result = subprocess.run(
            ["systemctl", "restart", "soulwinners-webhook"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return {"success": True, "message": "Webhook service restarted"}
        else:
            # Fallback: try to find and restart the process
            return {
                "success": False,
                "error": result.stderr,
                "note": "Try manual restart: cd /root/Soulwinners && python webhook.py &"
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# CRON JOB MANAGEMENT
# =============================================================================

def list_cron_jobs() -> Dict:
    """
    List all SoulWinners cron jobs and their status

    Returns:
        Dict with cron job list and status
    """
    jobs = []

    try:
        # Get current crontab
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and "Soulwinners" in line:
                    # Parse cron line
                    parts = line.split()
                    if len(parts) >= 6:
                        schedule = " ".join(parts[:5])
                        command = " ".join(parts[5:])

                        # Extract job name from command
                        job_name = "unknown"
                        if "python" in command:
                            # Try to get script name
                            for part in parts:
                                if part.endswith(".py"):
                                    job_name = Path(part).stem
                                    break

                        jobs.append({
                            "name": job_name,
                            "schedule": schedule,
                            "command": command[:100],  # Truncate
                            "enabled": True,
                        })
                elif line.startswith("#") and "Soulwinners" in line:
                    # Disabled job
                    jobs.append({
                        "name": "disabled_job",
                        "schedule": line[1:].strip()[:50],
                        "enabled": False,
                    })

        return {
            "total_jobs": len(jobs),
            "active_jobs": sum(1 for j in jobs if j.get("enabled", False)),
            "jobs": jobs,
        }
    except Exception as e:
        return {"error": str(e)}


def get_cron_last_run(job_name: str) -> Dict:
    """
    Get when a cron job last ran

    Args:
        job_name: Name of the job (script name without .py)

    Returns:
        Dict with last run info
    """
    result = {
        "job_name": job_name,
        "last_run": None,
        "status": "unknown",
    }

    # Check cron log
    if CRON_LOG.exists():
        try:
            log_content = CRON_LOG.read_text().split("\n")
            for line in reversed(log_content[-500:]):
                if job_name in line:
                    result["last_log_entry"] = line[:200]
                    # Try to extract timestamp
                    if line and line[0].isdigit():
                        result["last_run"] = line[:19]
                    if "success" in line.lower() or "completed" in line.lower():
                        result["status"] = "success"
                    elif "error" in line.lower() or "failed" in line.lower():
                        result["status"] = "failed"
                    break
        except Exception as e:
            result["log_error"] = str(e)

    # Also check syslog for cron entries
    try:
        grep_result = subprocess.run(
            ["grep", "-i", job_name, "/var/log/syslog"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if grep_result.returncode == 0:
            lines = grep_result.stdout.strip().split("\n")
            if lines:
                result["syslog_last"] = lines[-1][:200]
    except:
        pass

    return result


def toggle_cron_job(job_name: str, enabled: bool) -> Dict:
    """
    Enable or disable a cron job

    REQUIRES APPROVAL - This modifies scheduled tasks

    Args:
        job_name: Name of the job to toggle
        enabled: True to enable, False to disable

    Returns:
        Dict with toggle status
    """
    try:
        # Get current crontab
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {"success": False, "error": "Could not read crontab"}

        lines = result.stdout.split("\n")
        modified = False
        new_lines = []

        for line in lines:
            if job_name in line:
                if enabled and line.startswith("#"):
                    # Uncomment to enable
                    new_lines.append(line[1:].lstrip())
                    modified = True
                elif not enabled and not line.startswith("#"):
                    # Comment to disable
                    new_lines.append("# " + line)
                    modified = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        if not modified:
            return {"success": False, "error": f"Job '{job_name}' not found or already in desired state"}

        # Write new crontab
        new_crontab = "\n".join(new_lines)
        write_result = subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if write_result.returncode == 0:
            return {"success": True, "job": job_name, "enabled": enabled}
        else:
            return {"success": False, "error": write_result.stderr}

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

def check_api_rate_limits() -> Dict:
    """
    Check rate limit status for all Helius API keys

    Returns:
        Dict with rate limit info per key
    """
    keys_status = []

    for i, env_var in enumerate(HELIUS_KEYS_ENV, 1):
        key = os.getenv(env_var)
        status = {
            "key_number": i,
            "env_var": env_var,
            "configured": bool(key),
            "key_preview": f"{key[:8]}...{key[-4:]}" if key and len(key) > 12 else "N/A",
        }

        if key:
            # Try a test request to check rate limit headers
            try:
                import urllib.request
                import urllib.error

                url = f"https://api.helius.xyz/v0/addresses/So11111111111111111111111111111111111111112/balances?api-key={key}"
                req = urllib.request.Request(url, method="GET")

                with urllib.request.urlopen(req, timeout=10) as response:
                    # Check rate limit headers
                    status["rate_limit_remaining"] = response.headers.get("x-ratelimit-remaining", "unknown")
                    status["rate_limit_limit"] = response.headers.get("x-ratelimit-limit", "unknown")
                    status["status"] = "active"

            except urllib.error.HTTPError as e:
                if e.code == 429:
                    status["status"] = "rate_limited"
                    status["retry_after"] = e.headers.get("retry-after", "unknown")
                else:
                    status["status"] = f"error_{e.code}"
            except Exception as e:
                status["status"] = "error"
                status["error"] = str(e)[:50]

        keys_status.append(status)

    active_keys = sum(1 for k in keys_status if k.get("status") == "active")

    return {
        "total_keys": len(HELIUS_KEYS_ENV),
        "configured_keys": sum(1 for k in keys_status if k["configured"]),
        "active_keys": active_keys,
        "keys": keys_status,
    }


def get_api_usage() -> Dict:
    """
    Get API usage statistics per key

    Returns:
        Dict with usage stats
    """
    # Try to read from a usage log or database table
    usage_data = {
        "period": "last_24h",
        "keys": [],
    }

    try:
        # Check if there's a usage tracking table
        usage = _query_db("""
            SELECT
                api_key_index,
                COUNT(*) as requests,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed
            FROM api_requests
            WHERE created_at >= datetime('now', '-24 hours')
            GROUP BY api_key_index
        """)

        for row in usage:
            usage_data["keys"].append({
                "key_index": row["api_key_index"],
                "requests_24h": row["requests"],
                "successful": row["successful"],
                "failed": row["failed"],
                "success_rate": f"{(row['successful']/row['requests']*100):.1f}%" if row["requests"] > 0 else "N/A",
            })

    except Exception as e:
        # Table might not exist
        usage_data["note"] = f"Usage tracking not available: {str(e)[:50]}"
        usage_data["keys"] = [{"key_index": i, "requests_24h": "unknown"} for i in range(1, 6)]

    return usage_data


def rotate_api_key() -> Dict:
    """
    Rotate to the next available API key

    REQUIRES APPROVAL - This changes the active API key

    Returns:
        Dict with rotation status
    """
    # Find current key index and rotate
    current_key_file = SOULWINNERS_ROOT / ".current_api_key"

    try:
        current_index = 0
        if current_key_file.exists():
            current_index = int(current_key_file.read_text().strip())

        # Find next active key
        for i in range(1, 6):
            next_index = (current_index + i) % 5
            env_var = HELIUS_KEYS_ENV[next_index]
            if os.getenv(env_var):
                # Write new index
                current_key_file.write_text(str(next_index))
                return {
                    "success": True,
                    "previous_key": current_index + 1,
                    "new_key": next_index + 1,
                    "env_var": env_var,
                }

        return {"success": False, "error": "No available API keys found"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# ML SYSTEM
# =============================================================================

def get_ml_accuracy() -> Dict:
    """
    Get current ML model accuracy and stats

    Returns:
        Dict with model accuracy metrics
    """
    result = {
        "model_path": str(ML_MODEL_PATH),
        "model_exists": ML_MODEL_PATH.exists(),
    }

    if not ML_MODEL_PATH.exists():
        result["error"] = "Model file not found"
        return result

    try:
        # Load the model to get metadata
        with open(ML_MODEL_PATH, "rb") as f:
            model_data = pickle.load(f)

        # Extract accuracy info (structure depends on how model was saved)
        if isinstance(model_data, dict):
            result["accuracy"] = model_data.get("accuracy", "unknown")
            result["precision"] = model_data.get("precision", "unknown")
            result["recall"] = model_data.get("recall", "unknown")
            result["f1_score"] = model_data.get("f1_score", "unknown")
            result["trained_at"] = model_data.get("trained_at", "unknown")
            result["training_samples"] = model_data.get("n_samples", "unknown")
            result["features"] = model_data.get("features", [])[:10]  # First 10 features
        else:
            # Model object - try to get attributes
            result["model_type"] = type(model_data).__name__
            if hasattr(model_data, "score"):
                result["note"] = "Model loaded, call get_ml_predictions for live accuracy"

        # Get file modification time
        mtime = ML_MODEL_PATH.stat().st_mtime
        result["last_modified"] = datetime.fromtimestamp(mtime).isoformat()

    except Exception as e:
        result["error"] = f"Error loading model: {str(e)}"

    return result


def get_ml_predictions(hours: int = 24) -> Dict:
    """
    Get recent ML predictions and their outcomes

    Args:
        hours: Number of hours to look back

    Returns:
        Dict with predictions and accuracy
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Get predictions with outcomes
        predictions = _query_db("""
            SELECT
                p.token_address,
                p.ml_confidence,
                p.ml_prediction,
                p.actual_outcome,
                p.pnl_percent,
                p.created_at
            FROM positions p
            WHERE p.created_at >= ? AND p.ml_confidence IS NOT NULL
            ORDER BY p.created_at DESC
            LIMIT 50
        """, (cutoff_str,))

        # Calculate accuracy
        correct = sum(1 for p in predictions
                     if p.get("ml_prediction") == p.get("actual_outcome")
                     and p.get("actual_outcome") is not None)
        total_with_outcome = sum(1 for p in predictions if p.get("actual_outcome") is not None)

        # Breakdown by prediction type
        runners_predicted = sum(1 for p in predictions if p.get("ml_prediction") == "runner")
        actual_runners = sum(1 for p in predictions if p.get("actual_outcome") == "runner")

        return {
            "period_hours": hours,
            "total_predictions": len(predictions),
            "predictions_with_outcome": total_with_outcome,
            "correct_predictions": correct,
            "accuracy": f"{(correct/total_with_outcome*100):.1f}%" if total_with_outcome > 0 else "N/A",
            "runners_predicted": runners_predicted,
            "actual_runners": actual_runners,
            "recent_predictions": predictions[:10],
        }

    except Exception as e:
        return {"error": str(e)}


def update_ml_threshold(new_threshold: float) -> Dict:
    """
    Update the ML confidence threshold for trading

    REQUIRES APPROVAL - This affects trading decisions

    Args:
        new_threshold: New confidence threshold (0.0 to 1.0)

    Returns:
        Dict with update status
    """
    if not 0.0 <= new_threshold <= 1.0:
        return {"success": False, "error": "Threshold must be between 0.0 and 1.0"}

    config_file = SOULWINNERS_ROOT / "config.json"

    try:
        # Read current config
        if config_file.exists():
            config = json.loads(config_file.read_text())
        else:
            config = {}

        old_threshold = config.get("ml_confidence_threshold", 0.7)
        config["ml_confidence_threshold"] = new_threshold

        # Write updated config
        config_file.write_text(json.dumps(config, indent=2))

        return {
            "success": True,
            "old_threshold": old_threshold,
            "new_threshold": new_threshold,
            "config_file": str(config_file),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# DATABASE INSIGHTS
# =============================================================================

def get_wallet_breakdown() -> Dict:
    """
    Get breakdown of wallet types (insider vs qualified)

    Returns:
        Dict with wallet counts and stats
    """
    try:
        # Get counts by wallet type
        counts = _query_db("""
            SELECT
                wallet_type,
                COUNT(*) as count,
                AVG(win_rate) as avg_win_rate,
                AVG(total_trades) as avg_trades
            FROM wallets
            GROUP BY wallet_type
        """)

        # Get total
        total = _query_db("SELECT COUNT(*) as total FROM wallets")

        breakdown = {
            "total_wallets": total[0]["total"] if total else 0,
            "by_type": {},
        }

        for row in counts:
            wtype = row["wallet_type"] or "unknown"
            breakdown["by_type"][wtype] = {
                "count": row["count"],
                "avg_win_rate": f"{row['avg_win_rate']:.1f}%" if row["avg_win_rate"] else "N/A",
                "avg_trades": int(row["avg_trades"]) if row["avg_trades"] else 0,
            }

        # Expected counts for reference
        breakdown["expected"] = {
            "insider": 665,
            "qualified": 231,
        }

        return breakdown

    except Exception as e:
        return {"error": str(e)}


def get_position_stats(hours: int = 24) -> Dict:
    """
    Get position statistics by outcome type

    Args:
        hours: Number of hours to look back

    Returns:
        Dict with position stats (runner/rug/sideways)
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Get stats by outcome
        stats = _query_db("""
            SELECT
                outcome,
                COUNT(*) as count,
                AVG(pnl_percent) as avg_pnl,
                MIN(pnl_percent) as min_pnl,
                MAX(pnl_percent) as max_pnl
            FROM positions
            WHERE created_at >= ?
            GROUP BY outcome
        """, (cutoff_str,))

        # Get total
        total = _query_db("""
            SELECT COUNT(*) as total, AVG(pnl_percent) as avg_pnl
            FROM positions WHERE created_at >= ?
        """, (cutoff_str,))

        result = {
            "period_hours": hours,
            "total_positions": total[0]["total"] if total else 0,
            "overall_avg_pnl": f"{total[0]['avg_pnl']:.2f}%" if total and total[0]["avg_pnl"] else "N/A",
            "by_outcome": {},
        }

        for row in stats:
            outcome = row["outcome"] or "unknown"
            result["by_outcome"][outcome] = {
                "count": row["count"],
                "avg_pnl": f"{row['avg_pnl']:.2f}%" if row["avg_pnl"] else "N/A",
                "min_pnl": f"{row['min_pnl']:.2f}%" if row["min_pnl"] else "N/A",
                "max_pnl": f"{row['max_pnl']:.2f}%" if row["max_pnl"] else "N/A",
            }

        return result

    except Exception as e:
        return {"error": str(e)}


def find_recent_runners(hours: int = 24) -> Dict:
    """
    Find recent positions that achieved 2x or more

    Args:
        hours: Number of hours to look back

    Returns:
        Dict with runner positions
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    try:
        runners = _query_db("""
            SELECT
                token_address,
                entry_price,
                max_price,
                pnl_percent,
                hold_time_minutes,
                wallet_type,
                ml_confidence,
                created_at
            FROM positions
            WHERE created_at >= ? AND pnl_percent >= 100
            ORDER BY pnl_percent DESC
            LIMIT 20
        """, (cutoff_str,))

        return {
            "period_hours": hours,
            "runner_count": len(runners),
            "runners": runners,
            "best_runner": runners[0] if runners else None,
            "avg_gain": f"{sum(r['pnl_percent'] for r in runners)/len(runners):.1f}%" if runners else "N/A",
        }

    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# REGISTER ALL SKILLS
# =============================================================================

registry = get_registry()

# Webhook Management
@registry.register(
    name="check_webhook_health",
    description="Check if SoulWinners webhook is running and get health stats",
    parameters=[]
)
def _check_webhook_health() -> Dict:
    return check_webhook_health()


@registry.register(
    name="get_webhook_positions",
    description="Get recent positions received via webhook",
    parameters=[
        {"name": "hours", "type": "int", "description": "Hours to look back (default 24)", "optional": True}
    ]
)
def _get_webhook_positions(hours: int = 24) -> Dict:
    return get_webhook_positions(hours)


@registry.register(
    name="restart_webhook",
    description="Restart the webhook service (REQUIRES APPROVAL - critical service)",
    parameters=[]
)
def _restart_webhook() -> Dict:
    return restart_webhook()


# Cron Job Management
@registry.register(
    name="list_cron_jobs",
    description="List all SoulWinners cron jobs and their status",
    parameters=[]
)
def _list_cron_jobs() -> Dict:
    return list_cron_jobs()


@registry.register(
    name="get_cron_last_run",
    description="Get when a specific cron job last ran",
    parameters=[
        {"name": "job_name", "type": "str", "description": "Name of the job (script name without .py)"}
    ]
)
def _get_cron_last_run(job_name: str) -> Dict:
    return get_cron_last_run(job_name)


@registry.register(
    name="toggle_cron_job",
    description="Enable or disable a cron job (REQUIRES APPROVAL - modifies scheduled tasks)",
    parameters=[
        {"name": "job_name", "type": "str", "description": "Name of the job to toggle"},
        {"name": "enabled", "type": "bool", "description": "True to enable, False to disable"}
    ]
)
def _toggle_cron_job(job_name: str, enabled: bool) -> Dict:
    return toggle_cron_job(job_name, enabled)


# API Key Management
@registry.register(
    name="check_api_rate_limits",
    description="Check rate limit status for all 5 Helius API keys",
    parameters=[]
)
def _check_api_rate_limits() -> Dict:
    return check_api_rate_limits()


@registry.register(
    name="get_api_usage",
    description="Get API usage statistics per key for the last 24 hours",
    parameters=[]
)
def _get_api_usage() -> Dict:
    return get_api_usage()


@registry.register(
    name="rotate_api_key",
    description="Rotate to the next available Helius API key (REQUIRES APPROVAL)",
    parameters=[]
)
def _rotate_api_key() -> Dict:
    return rotate_api_key()


# ML System
@registry.register(
    name="get_ml_accuracy",
    description="Get current ML model accuracy and performance metrics",
    parameters=[]
)
def _get_ml_accuracy() -> Dict:
    return get_ml_accuracy()


@registry.register(
    name="get_ml_predictions",
    description="Get recent ML predictions and their outcomes",
    parameters=[
        {"name": "hours", "type": "int", "description": "Hours to look back (default 24)", "optional": True}
    ]
)
def _get_ml_predictions(hours: int = 24) -> Dict:
    return get_ml_predictions(hours)


@registry.register(
    name="update_ml_threshold",
    description="Update ML confidence threshold for trading (REQUIRES APPROVAL - affects trading)",
    parameters=[
        {"name": "new_threshold", "type": "float", "description": "New threshold between 0.0 and 1.0"}
    ]
)
def _update_ml_threshold(new_threshold: float) -> Dict:
    return update_ml_threshold(new_threshold)


# Database Insights
@registry.register(
    name="get_wallet_breakdown",
    description="Get breakdown of wallet types (insider 665 + qualified 231)",
    parameters=[]
)
def _get_wallet_breakdown() -> Dict:
    return get_wallet_breakdown()


@registry.register(
    name="get_position_stats",
    description="Get position statistics by outcome type (runner/rug/sideways)",
    parameters=[
        {"name": "hours", "type": "int", "description": "Hours to look back (default 24)", "optional": True}
    ]
)
def _get_position_stats(hours: int = 24) -> Dict:
    return get_position_stats(hours)


@registry.register(
    name="find_recent_runners",
    description="Find recent positions that achieved 2x or more gains",
    parameters=[
        {"name": "hours", "type": "int", "description": "Hours to look back (default 24)", "optional": True}
    ]
)
def _find_recent_runners(hours: int = 24) -> Dict:
    return find_recent_runners(hours)
