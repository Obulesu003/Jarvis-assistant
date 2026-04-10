"""
AmbientDashboard - JARVIS ambient awareness display for the HUD overlay.
Shows live system stats: CPU, memory, battery, disk, and unread email count.
Position: bottom-right corner. Auto-refreshes every 30 seconds.
"""
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Color thresholds for usage metrics
COLOR_GREEN = [0, 200, 100]
COLOR_YELLOW = [255, 200, 0]
COLOR_RED = [255, 60, 60]
COLOR_DIM = [120, 120, 120]

# Thresholds
THRESHOLD_LOW = 50      # Green: < 50%
THRESHOLD_MED = 80      # Yellow: 50-80%, Red: > 80%


def _get_color_for_percentage(value: float | None) -> list[int]:
    """Return color based on percentage value thresholds."""
    if value is None:
        return COLOR_DIM
    if value < THRESHOLD_LOW:
        return COLOR_GREEN
    if value < THRESHOLD_MED:
        return COLOR_YELLOW
    return COLOR_RED


class AmbientDashboard:
    """
    Ambient awareness dashboard for JARVIS HUD overlay.
    Displays live system stats in a slim panel at the bottom-right.
    Stats are color-coded: green (<50%), yellow (50-80%), red (>80%).
    """

    REFRESH_INTERVAL = 30.0  # seconds

    def __init__(self, hud, system_snapshot):
        """
        Initialize the ambient dashboard.

        Args:
            hud: The JARVISHUD instance to attach to
            system_snapshot: SystemSnapshot instance for data collection
        """
        self._hud = hud
        self._snapshot = system_snapshot
        self._running = False
        self._thread: threading.Thread | None = None
        self._dpg = None
        self._stats: dict[str, Any] = {}
        self._tags: dict[str, str] = {}

    def _get_dpg(self):
        """Get DearPyGui reference lazily."""
        if self._dpg is None:
            try:
                import dearpygui.dearpygui as dpg
                self._dpg = dpg
            except ImportError:
                logger.warning("[AmbientDashboard] dearpygui not installed")
                return None
        return self._dpg

    def _build_ui(self, dpg, screen_w: int, screen_h: int):
        """Build the dashboard UI in DearPyGui."""
        panel_w = 420
        panel_h = 100
        panel_x = screen_w - panel_w - 16
        panel_y = screen_h - panel_h - 16

        with dpg.window(
            tag="AMBIENT_DASHBOARD",
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_close=True,
            no_bring_to_focus_on_tip=True,
            transparent_frame=True,
            alpha=200,
            show=True,
        ):
            dpg.configure_item(
                "AMBIENT_DASHBOARD",
                pos=[panel_x, panel_y],
                width=panel_w,
                height=panel_h,
            )

            # Title
            with dpg.group(tag="DASH_HEADER"):
                dpg.add_text(
                    "◈  AMBIENT VITALS",
                    color=[0, 180, 255],
                    font=1,
                    tag="DASH_TITLE"
                )
                dpg.add_same_line(x_offset=5)
                dpg.add_text(
                    "",
                    color=[100, 100, 100],
                    tag="DASH_TIME",
                    font=0
                )

            dpg.add_separator()

            # Stats row 1: CPU | Memory
            with dpg.group(tag="DASH_ROW1"):
                # CPU
                dpg.add_text("CPU:", color=[80, 80, 80], tag="CPU_LABEL")
                dpg.add_same_line(x_offset=4)
                dpg.add_text("--", color=COLOR_DIM, tag="CPU_VALUE", font=0)
                dpg.add_same_line(x_offset=8)
                # Mini bar for CPU
                dpg.add_progress_bar(
                    0.0,
                    tag="CPU_BAR",
                    width=60,
                    height=10,
                    overlay=""
                )
                dpg.configure_item("CPU_BAR", pvp_color=[0, 180, 255])

                dpg.add_same_line(x_offset=16)

                # Memory
                dpg.add_text("RAM:", color=[80, 80, 80], tag="RAM_LABEL")
                dpg.add_same_line(x_offset=4)
                dpg.add_text("--", color=COLOR_DIM, tag="RAM_VALUE", font=0)
                dpg.add_same_line(x_offset=8)
                dpg.add_progress_bar(
                    0.0,
                    tag="RAM_BAR",
                    width=60,
                    height=10,
                    overlay=""
                )
                dpg.configure_item("RAM_BAR", pvp_color=[0, 180, 255])

            dpg.add_separator()

            # Stats row 2: Battery | Disk | Email
            with dpg.group(tag="DASH_ROW2"):
                # Battery
                dpg.add_text("BAT:", color=[80, 80, 80], tag="BAT_LABEL")
                dpg.add_same_line(x_offset=4)
                dpg.add_text("--", color=COLOR_DIM, tag="BAT_VALUE", font=0)
                dpg.add_same_line(x_offset=12)

                # Disk
                dpg.add_text("DISK:", color=[80, 80, 80], tag="DISK_LABEL")
                dpg.add_same_line(x_offset=4)
                dpg.add_text("--", color=COLOR_DIM, tag="DISK_VALUE", font=0)
                dpg.add_same_line(x_offset=12)

                # Email indicator
                dpg.add_text("MAIL:", color=[80, 80, 80], tag="MAIL_LABEL")
                dpg.add_same_line(x_offset=4)
                dpg.add_text("0", color=COLOR_DIM, tag="MAIL_VALUE", font=0)
                # Email icon indicator (shows when > 0)
                dpg.add_same_line(x_offset=4)
                dpg.add_text("", color=[255, 200, 0], tag="MAIL_ICON", font=0)

    def _fetch_stats(self) -> dict[str, Any]:
        """Fetch current system stats from snapshot."""
        try:
            return self._snapshot.get_all()
        except Exception as e:
            logger.debug(f"[AmbientDashboard] Stats fetch error: {e}")
            return {}

    def _update_display(self):
        """Update the dashboard display with current stats."""
        dpg = self._get_dpg()
        if not dpg or not self._hud._dpg:
            return

        stats = self._fetch_stats()
        self._stats = stats

        try:
            # Update CPU
            cpu = stats.get("cpu")
            if cpu is not None:
                cpu_val = float(cpu)
                cpu_color = _get_color_for_percentage(cpu_val)
                dpg.configure_item("CPU_VALUE", default_value=f"{cpu_val:.0f}%", color=cpu_color)
                dpg.configure_item("CPU_BAR", default_value=cpu_val / 100.0)
                dpg.configure_item("CPU_BAR", pvp_color=cpu_color)
            else:
                dpg.configure_item("CPU_VALUE", default_value="--", color=COLOR_DIM)
                dpg.configure_item("CPU_BAR", default_value=0.0)

            # Update Memory
            mem = stats.get("memory")
            if mem is not None:
                mem_val = float(mem)
                mem_color = _get_color_for_percentage(mem_val)
                dpg.configure_item("RAM_VALUE", default_value=f"{mem_val:.0f}%", color=mem_color)
                dpg.configure_item("RAM_BAR", default_value=mem_val / 100.0)
                dpg.configure_item("RAM_BAR", pvp_color=mem_color)
            else:
                dpg.configure_item("RAM_VALUE", default_value="--", color=COLOR_DIM)
                dpg.configure_item("RAM_BAR", default_value=0.0)

            # Update Battery
            batt = stats.get("battery")
            charging = stats.get("charging")
            if batt is not None:
                icon = " ⚡" if charging else " 🔋"
                dpg.configure_item("BAT_VALUE", default_value=f"{batt:.0f}%{icon}")
                batt_color = _get_color_for_percentage(batt)
                dpg.configure_item("BAT_VALUE", color=batt_color)
            else:
                dpg.configure_item("BAT_VALUE", default_value="N/A", color=COLOR_DIM)

            # Update Disk
            disk = stats.get("disk_free_gb")
            if disk is not None:
                dpg.configure_item("DISK_VALUE", default_value=f"{disk:.1f}GB", color=[180, 180, 180])
            else:
                dpg.configure_item("DISK_VALUE", default_value="N/A", color=COLOR_DIM)

            # Update Email
            unread = stats.get("unread", 0)
            dpg.configure_item("MAIL_VALUE", default_value=str(unread))
            if unread > 0:
                dpg.configure_item("MAIL_VALUE", color=COLOR_YELLOW)
                dpg.configure_item("MAIL_ICON", default_value="✉")
            else:
                dpg.configure_item("MAIL_VALUE", color=COLOR_DIM)
                dpg.configure_item("MAIL_ICON", default_value="")

            # Update time
            from datetime import datetime
            now = datetime.now().strftime("%H:%M")
            dpg.configure_item("DASH_TIME", default_value=f"[{now}]")

        except Exception as e:
            logger.debug(f"[AmbientDashboard] Display update error: {e}")

    def _loop(self):
        """Background refresh loop."""
        while self._running:
            try:
                self._update_display()
            except Exception as e:
                logger.debug(f"[AmbientDashboard] Loop error: {e}")
            time.sleep(self.REFRESH_INTERVAL)

    def show(self):
        """Show the ambient dashboard on the HUD."""
        dpg = self._get_dpg()
        if not dpg or not self._hud._dpg:
            logger.warning("[AmbientDashboard] Cannot show - HUD not initialized")
            return

        try:
            # Check if already built
            if dpg.does_item_exist("AMBIENT_DASHBOARD"):
                dpg.configure_item("AMBIENT_DASHBOARD", show=True)
            else:
                self._build_ui(dpg, self._hud._screen_w, self._hud._screen_h)

            # Initial display
            self._update_display()

            # Start refresh thread
            self._running = True
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="AmbientDashboard"
            )
            self._thread.start()
            logger.info("[AmbientDashboard] Started")
        except Exception as e:
            logger.error(f"[AmbientDashboard] Failed to show: {e}")

    def hide(self):
        """Hide the ambient dashboard."""
        dpg = self._get_dpg()
        if not dpg:
            return

        self._running = False
        try:
            if dpg.does_item_exist("AMBIENT_DASHBOARD"):
                dpg.configure_item("AMBIENT_DASHBOARD", show=False)
        except Exception as e:
            logger.debug(f"[AmbientDashboard] Hide error: {e}")

    def toggle(self):
        """Toggle the dashboard visibility."""
        dpg = self._get_dpg()
        if not dpg:
            return

        if dpg.does_item_exist("AMBIENT_DASHBOARD"):
            try:
                is_visible = dpg.is_item_visible("AMBIENT_DASHBOARD")
                if is_visible:
                    self.hide()
                else:
                    self.show()
            except Exception:
                self.show()
        else:
            self.show()

    def refresh(self):
        """Manually trigger a refresh of the stats."""
        self._update_display()

    def get_stats(self) -> dict[str, Any]:
        """Return the last fetched stats."""
        return self._stats.copy()

    @property
    def refresh_interval(self) -> float:
        """Return the refresh interval in seconds."""
        return self.REFRESH_INTERVAL
