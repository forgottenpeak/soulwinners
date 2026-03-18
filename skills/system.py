"""
Hedgehog System Skills
System monitoring and service management
"""
import subprocess
import platform
from pathlib import Path
from typing import Any

from skills.base import get_registry


class SystemSkills:
    """System monitoring capabilities"""

    @staticmethod
    def check_service(name: str) -> dict:
        """
        Check if a system service is running

        Args:
            name: Service name (e.g., 'nginx', 'postgresql')

        Returns:
            Dict with status info
        """
        system = platform.system().lower()

        if system == "linux":
            return SystemSkills._check_linux_service(name)
        elif system == "darwin":
            return SystemSkills._check_macos_service(name)
        else:
            return {"running": False, "error": f"Unsupported OS: {system}"}

    @staticmethod
    def _check_linux_service(name: str) -> dict:
        """Check service on Linux using systemctl"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            is_active = result.stdout.strip() == "active"

            # Get more details if active
            if is_active:
                status = subprocess.run(
                    ["systemctl", "status", name, "--no-pager", "-l"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return {
                    "running": True,
                    "status": "active",
                    "details": status.stdout[:500],  # Truncate
                }

            return {"running": False, "status": result.stdout.strip()}

        except subprocess.TimeoutExpired:
            return {"running": False, "error": "Timeout checking service"}
        except FileNotFoundError:
            return {"running": False, "error": "systemctl not found"}
        except Exception as e:
            return {"running": False, "error": str(e)}

    @staticmethod
    def _check_macos_service(name: str) -> dict:
        """Check service on macOS using launchctl or pgrep"""
        try:
            # Try pgrep first (works for most services)
            result = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                pids = result.stdout.strip().split("\n")
                return {
                    "running": True,
                    "status": "active",
                    "pids": pids,
                }

            return {"running": False, "status": "not running"}

        except Exception as e:
            return {"running": False, "error": str(e)}

    @staticmethod
    def read_logs(service: str, lines: int = 50) -> str:
        """
        Read recent log entries for a service

        Args:
            service: Service name
            lines: Number of lines to read (default 50)

        Returns:
            Log content as string
        """
        system = platform.system().lower()

        # Common log paths
        log_paths = [
            f"/var/log/{service}.log",
            f"/var/log/{service}/{service}.log",
            f"/var/log/{service}/error.log",
        ]

        if system == "linux":
            # Try journalctl first
            try:
                result = subprocess.run(
                    ["journalctl", "-u", service, "-n", str(lines), "--no-pager"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout
            except:
                pass

        # Fall back to log files
        for log_path in log_paths:
            path = Path(log_path)
            if path.exists():
                try:
                    result = subprocess.run(
                        ["tail", "-n", str(lines), str(path)],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        return result.stdout
                except:
                    continue

        return f"No logs found for service: {service}"

    @staticmethod
    def get_system_info() -> dict:
        """Get basic system information"""
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
        }


# Register skills
registry = get_registry()


@registry.register(
    name="check_service",
    description="Check if a system service is running",
    parameters=[{"name": "name", "type": "str", "description": "Service name"}]
)
def check_service(name: str) -> dict:
    """Check service status"""
    return SystemSkills.check_service(name)


@registry.register(
    name="read_logs",
    description="Read recent log entries for a service",
    parameters=[
        {"name": "service", "type": "str", "description": "Service name"},
        {"name": "lines", "type": "int", "description": "Number of lines (default 50)"},
    ]
)
def read_logs(service: str, lines: int = 50) -> str:
    """Read service logs"""
    return SystemSkills.read_logs(service, lines)


@registry.register(
    name="system_info",
    description="Get basic system information",
    parameters=[]
)
def system_info() -> dict:
    """Get system info"""
    return SystemSkills.get_system_info()
