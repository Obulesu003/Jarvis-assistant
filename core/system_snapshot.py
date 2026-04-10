"""
SystemSnapshot - Ambient awareness dashboard for JARVIS.
Provides battery, CPU, memory, disk, and unread email counts.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SystemSnapshot:
    """
    Captures a snapshot of system state for ambient awareness.
    Used by JARVIS to proactively volunteer information about system health.
    """

    def __init__(self):
        # Prime psutil CPU measurement so subsequent calls are non-blocking
        try:
            import psutil
            psutil.cpu_percent()
        except Exception:
            pass

    def get_all(self) -> dict[str, Any]:
        """
        Get a complete system snapshot.

        Returns:
            Dictionary with battery, cpu, memory, disk, and unread counts
        """
        import psutil

        result: dict[str, Any] = {}

        # Battery
        try:
            battery = psutil.sensors_battery()
            if battery:
                result["battery"] = battery.percent
                result["charging"] = battery.power_plugged
            else:
                result["battery"] = None
                result["charging"] = None
        except Exception:
            result["battery"] = None
            result["charging"] = None

        # CPU
        try:
            result["cpu"] = psutil.cpu_percent(interval=None)  # Non-blocking: returns since last call
        except Exception:
            result["cpu"] = None

        # Memory
        try:
            mem = psutil.virtual_memory()
            result["memory"] = mem.percent
        except Exception:
            result["memory"] = None

        # Disk (free space in GB)
        try:
            disk = psutil.disk_usage("C:\\")
            result["disk_free_gb"] = round(disk.free / (1024**3), 1)
        except Exception:
            try:
                disk = psutil.disk_usage("/")
                result["disk_free_gb"] = round(disk.free / (1024**3), 1)
            except Exception:
                result["disk_free_gb"] = None

        # Unread emails
        try:
            outlook = __import__(
                "integrations.outlook.outlook_native_adapter",
                fromlist=["OutlookNativeAdapter"],
            )
            adapter = outlook.OutlookNativeAdapter()
            result["unread"] = adapter.execute_action("get_unread_count", {}) or 0
        except Exception:
            result["unread"] = 0

        return result

    def get_brief_summary(self) -> str:
        """
        Get a brief one-line summary of system state.

        Returns:
            A compact summary string like "Batt: 80% | CPU: 25% | RAM: 50% | Unread: 3"
        """
        snapshot = self.get_all()

        parts = []

        if snapshot.get("battery") is not None:
            batt = snapshot["battery"]
            chg = "[CHG]" if snapshot.get("charging") else ""
            parts.append(f"Batt: {batt}%{chg}")

        if snapshot.get("cpu") is not None:
            parts.append(f"CPU: {snapshot['cpu']:.0f}%")

        if snapshot.get("memory") is not None:
            parts.append(f"RAM: {snapshot['memory']:.0f}%")

        unread = snapshot.get("unread", 0)
        if unread:
            parts.append(f"Unread: {unread}")

        return " | ".join(parts) if parts else ""
