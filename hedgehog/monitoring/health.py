"""
Health Monitor and Self-Healing for Hedgehog

Monitors service health and automatically recovers from failures.
"""
import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    """Status of a monitored service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    RESTARTING = "restarting"
    UNKNOWN = "unknown"


@dataclass
class ServiceHealth:
    """Health status of a service."""
    name: str
    status: ServiceStatus
    last_check: datetime = field(default_factory=datetime.now)
    uptime_seconds: Optional[float] = None
    restart_count: int = 0
    last_error: Optional[str] = None
    pid: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "last_check": self.last_check.isoformat(),
            "uptime_seconds": self.uptime_seconds,
            "restart_count": self.restart_count,
            "last_error": self.last_error,
            "pid": self.pid,
        }


class HealthMonitor:
    """
    Monitors service health and performs self-healing.

    Services monitored:
    - run_bot.py (Telegram bot)
    - webhook_server.py (Helius webhooks)
    - Database connectivity
    - External APIs (DexScreener, Helius)

    Self-healing actions:
    - Restart crashed services
    - Clear stuck processes
    - Reconnect to APIs
    - Notify admin of persistent issues
    """

    def __init__(self, config=None):
        """Initialize health monitor."""
        self.config = config
        self.services: Dict[str, ServiceHealth] = {}
        self.restart_attempts: Dict[str, int] = {}
        self.max_restart_attempts = 3
        self.restart_cooldown = 60  # seconds

        # Service definitions
        self.service_configs = {
            "bot": {
                "process_pattern": "run_bot.py",
                "start_command": "python run_bot.py",
                "health_endpoint": None,
                "critical": True,
            },
            "webhook": {
                "process_pattern": "webhook_server.py",
                "start_command": "python webhook_server.py --port 8080",
                "health_endpoint": "http://localhost:8080/health",
                "critical": True,
            },
        }

        # Initialize service health tracking
        for name in self.service_configs:
            self.services[name] = ServiceHealth(
                name=name,
                status=ServiceStatus.UNKNOWN,
            )

    async def check_service(self, name: str) -> ServiceHealth:
        """Check health of a specific service."""
        if name not in self.service_configs:
            return ServiceHealth(name=name, status=ServiceStatus.UNKNOWN)

        config = self.service_configs[name]
        health = self.services.get(name, ServiceHealth(name=name, status=ServiceStatus.UNKNOWN))

        try:
            # Check if process is running
            result = subprocess.run(
                ["pgrep", "-f", config["process_pattern"]],
                capture_output=True,
                timeout=5
            )

            if result.returncode == 0:
                pids = result.stdout.decode().strip().split('\n')
                health.pid = int(pids[0]) if pids else None
                health.status = ServiceStatus.HEALTHY

                # If there's a health endpoint, check it
                if config.get("health_endpoint"):
                    import aiohttp
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                config["health_endpoint"],
                                timeout=aiohttp.ClientTimeout(total=5)
                            ) as response:
                                if response.status != 200:
                                    health.status = ServiceStatus.DEGRADED
                                    health.last_error = f"Health endpoint returned {response.status}"
                    except Exception as e:
                        health.status = ServiceStatus.DEGRADED
                        health.last_error = f"Health check failed: {e}"

            else:
                health.status = ServiceStatus.DOWN
                health.pid = None
                health.last_error = "Process not found"

        except subprocess.TimeoutExpired:
            health.status = ServiceStatus.UNKNOWN
            health.last_error = "Health check timed out"
        except Exception as e:
            health.status = ServiceStatus.UNKNOWN
            health.last_error = str(e)

        health.last_check = datetime.now()
        self.services[name] = health

        return health

    async def check_all(self) -> Dict[str, ServiceHealth]:
        """Check health of all services."""
        for name in self.service_configs:
            await self.check_service(name)

        return self.services

    async def restart_service(self, name: str, reason: str = "") -> bool:
        """
        Restart a service.

        Args:
            name: Service name
            reason: Why restarting

        Returns:
            True if restart successful
        """
        if name not in self.service_configs:
            logger.error(f"Unknown service: {name}")
            return False

        config = self.service_configs[name]
        health = self.services.get(name, ServiceHealth(name=name, status=ServiceStatus.UNKNOWN))

        # Check restart attempts
        attempts = self.restart_attempts.get(name, 0)
        if attempts >= self.max_restart_attempts:
            logger.error(
                f"Service '{name}' exceeded max restart attempts ({self.max_restart_attempts}). "
                "Manual intervention required."
            )
            return False

        logger.warning(f"Restarting service '{name}': {reason}")
        health.status = ServiceStatus.RESTARTING

        try:
            # Kill existing process
            subprocess.run(
                ["pkill", "-f", config["process_pattern"]],
                capture_output=True,
                timeout=5
            )

            # Wait for process to terminate
            await asyncio.sleep(2)

            # Start new process
            base_dir = Path(__file__).parent.parent.parent
            cmd = config["start_command"].split()

            process = subprocess.Popen(
                cmd,
                cwd=str(base_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            # Wait and verify
            await asyncio.sleep(3)

            if process.poll() is None:
                health.status = ServiceStatus.HEALTHY
                health.pid = process.pid
                health.restart_count += 1
                health.last_error = None
                self.restart_attempts[name] = 0

                logger.info(f"Service '{name}' restarted successfully (PID: {process.pid})")
                return True
            else:
                health.status = ServiceStatus.DOWN
                health.last_error = "Process exited immediately after start"
                self.restart_attempts[name] = attempts + 1

                logger.error(f"Service '{name}' failed to start")
                return False

        except Exception as e:
            health.status = ServiceStatus.DOWN
            health.last_error = str(e)
            self.restart_attempts[name] = attempts + 1

            logger.error(f"Error restarting '{name}': {e}")
            return False

        finally:
            self.services[name] = health

    async def self_heal(self) -> List[str]:
        """
        Perform self-healing on unhealthy services.

        Returns:
            List of actions taken
        """
        actions = []

        # Check all services
        await self.check_all()

        for name, health in self.services.items():
            config = self.service_configs.get(name, {})

            # Skip non-critical services
            if not config.get("critical", False):
                continue

            if health.status == ServiceStatus.DOWN:
                success = await self.restart_service(name, "Service down")
                actions.append(
                    f"Restarted {name}: {'success' if success else 'failed'}"
                )

            elif health.status == ServiceStatus.DEGRADED:
                # Log degraded status but don't restart
                actions.append(f"Service {name} degraded: {health.last_error}")

        return actions

    async def check_database(self) -> Dict[str, Any]:
        """Check database connectivity and health."""
        try:
            from database import get_connection
            import time

            start = time.time()
            conn = get_connection()
            cursor = conn.cursor()

            # Test query
            cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
            wallet_count = cursor.fetchone()[0]

            # Check for issues
            cursor.execute("""
                SELECT COUNT(*) FROM position_lifecycle
                WHERE outcome IS NULL OR outcome = 'open'
            """)
            open_positions = cursor.fetchone()[0]

            conn.close()
            query_time = (time.time() - start) * 1000

            return {
                "status": "healthy",
                "query_time_ms": round(query_time, 2),
                "wallet_count": wallet_count,
                "open_positions": open_positions,
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    async def check_external_apis(self) -> Dict[str, Any]:
        """Check external API connectivity."""
        import aiohttp

        results = {}

        # Check DexScreener
        try:
            async with aiohttp.ClientSession() as session:
                start = time.time()
                async with session.get(
                    "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    results["dexscreener"] = {
                        "status": "healthy" if response.status == 200 else "degraded",
                        "response_time_ms": round((time.time() - start) * 1000, 2),
                        "http_code": response.status,
                    }
        except Exception as e:
            results["dexscreener"] = {
                "status": "unhealthy",
                "error": str(e),
            }

        # Check Helius (if configured)
        try:
            from config.settings import HELIUS_API_KEY
            async with aiohttp.ClientSession() as session:
                start = time.time()
                async with session.get(
                    f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}",
                    json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    results["helius"] = {
                        "status": "healthy" if response.status == 200 else "degraded",
                        "response_time_ms": round((time.time() - start) * 1000, 2),
                    }
        except Exception as e:
            results["helius"] = {
                "status": "unhealthy",
                "error": str(e),
            }

        return results

    def get_status_summary(self) -> Dict[str, Any]:
        """Get overall health status summary."""
        overall = "healthy"
        issues = []

        for name, health in self.services.items():
            if health.status == ServiceStatus.DOWN:
                overall = "critical"
                issues.append(f"{name} is down")
            elif health.status == ServiceStatus.DEGRADED:
                if overall != "critical":
                    overall = "degraded"
                issues.append(f"{name} is degraded")

        return {
            "overall_status": overall,
            "services": {
                name: health.to_dict()
                for name, health in self.services.items()
            },
            "issues": issues,
            "total_restarts": sum(h.restart_count for h in self.services.values()),
            "last_check": datetime.now().isoformat(),
        }

    async def run_full_health_check(self) -> Dict[str, Any]:
        """Run comprehensive health check."""
        result = {
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "database": {},
            "external_apis": {},
            "overall": "healthy",
        }

        # Check services
        await self.check_all()
        result["services"] = {
            name: health.to_dict()
            for name, health in self.services.items()
        }

        # Check database
        result["database"] = await self.check_database()

        # Check external APIs
        result["external_apis"] = await self.check_external_apis()

        # Determine overall status
        if any(h.status == ServiceStatus.DOWN for h in self.services.values()):
            result["overall"] = "critical"
        elif any(h.status == ServiceStatus.DEGRADED for h in self.services.values()):
            result["overall"] = "degraded"
        elif result["database"].get("status") != "healthy":
            result["overall"] = "degraded"

        return result


# Singleton instance
_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get or create health monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor()
    return _monitor
