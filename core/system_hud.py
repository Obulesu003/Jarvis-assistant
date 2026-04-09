"""
system_hud.py - JARVIS System HUD Overlay
A translucent always-on-top panel showing system stats in JARVIS style.
JARVIS blue (#00AAFF) on dark translucent background.
"""
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── HUD singleton ──────────────────────────────────────────────────────────────

_hud_instance = None


def get_system_hud():
    global _hud_instance
    if _hud_instance is None:
        _hud_instance = SystemHUD()
    return _hud_instance


class SystemHUD:
    """
    JARVIS System HUD — always-on-top translucent overlay.
    Shows: time, CPU, RAM, battery, network status.
    Position: bottom-right corner of screen.
    """

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._root = None
        self._labels: dict = {}
        self._stats = {
            "cpu": "—",
            "ram": "—",
            "disk": "—",
            "battery": "—",
            "net": "—",
        }

    def _create_window(self):
        """Create the HUD Tkinter window."""
        import tkinter as tk
        from tkinter import ttk

        self._root = tk.Tk()
        self._root.overrideredirect(True)  # No title bar
        self._root.attributes(
            "-topmost", True,
            "-transparentcolor", "#000001",
            "-alpha", 0.92,
        )
        self._root.configure(bg="#000001")

        # Position: bottom-right, above taskbar
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        w, h = 260, 180
        x = sw - w - 16
        y = sh - h - 48
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        # Style
        bg = "#0D1B2A"
        accent = "#00AAFF"
        gold = "#FFB800"
        text = "#B8D4E8"
        dim = "#4A6B8A"

        # Main frame
        frame = tk.Frame(self._root, bg=bg, bd=1, relief="flat")
        frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Title bar
        title_bar = tk.Frame(frame, bg=bg)
        title_bar.pack(fill="x")

        tk.Label(
            title_bar, text="◈  JARVIS SYS",
            font=("Consolas", 9, "bold"),
            fg=accent, bg=bg, anchor="w"
        ).pack(side="left", padx=8, pady=4)

        self._labels["time"] = tk.Label(
            title_bar, text="--:--:--",
            font=("Consolas", 9, "normal"),
            fg=accent, bg=bg, anchor="e"
        )
        self._labels["time"].pack(side="right", padx=8, pady=4)

        # Separator
        sep = tk.Frame(frame, bg=accent, height=1)
        sep.pack(fill="x", padx=4)

        # Stats grid
        grid_frame = tk.Frame(frame, bg=bg)
        grid_frame.pack(fill="both", expand=True, padx=8, pady=4)

        stats = [
            ("CPU", "cpu"),
            ("RAM", "ram"),
            ("DISK", "disk"),
            ("BATT", "battery"),
            ("NET", "net"),
        ]

        for i, (label_text, key) in enumerate(stats):
            row = i // 2
            col = (i % 2) * 2

            # Label
            tk.Label(
                grid_frame, text=f"{label_text}:",
                font=("Consolas", 8, "bold"),
                fg=dim, bg=bg, anchor="w", width=6
            ).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=1)

            # Value
            self._labels[key] = tk.Label(
                grid_frame, text="—",
                font=("Consolas", 8, "normal"),
                fg=text, bg=bg, anchor="w", width=8
            )
            self._labels[key].grid(row=row, column=col + 1, sticky="w", pady=1)

        # Status bar at bottom
        status_frame = tk.Frame(frame, bg=bg)
        status_frame.pack(fill="x", padx=8, pady=(2, 4))

        tk.Label(
            status_frame, text="● ONLINE",
            font=("Consolas", 7, "bold"),
            fg="#00FF88", bg=bg, anchor="w"
        ).pack(side="left")

        self._labels["status"] = tk.Label(
            status_frame, text="MARK XXXV",
            font=("Consolas", 7, "normal"),
            fg=dim, bg=bg, anchor="e"
        )
        self._labels["status"].pack(side="right")

        # Make window draggable
        self._make_draggable(frame)

    def _make_draggable(self, widget):
        """Make the HUD window draggable."""
        def on_drag_start(event):
            self._drag_x = event.x
            self._drag_y = event.y

        def on_drag_motion(event):
            dx = event.x - self._drag_x
            dy = event.y - self._drag_y
            new_x = self._root.winfo_x() + dx
            new_y = self._root.winfo_y() + dy
            self._root.geometry(f"+{new_x}+{new_y}")

        widget.bind("<Button-1>", on_drag_start)
        widget.bind("<B1-Motion>", on_drag_motion)
        widget.configure(cursor="fleur")

    def _update_stats(self):
        """Collect system stats."""
        try:
            import psutil
            battery = psutil.sensors_battery()

            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Network
            net = psutil.net_io_counters()
            net_mb = (net.bytes_sent + net.bytes_recv) / (1024 * 1024)
            net_str = f"{(net_mb):.0f} MB"

            self._stats = {
                "cpu": f"{cpu:>5.1f}%",
                "ram": f"{ram.percent:>5.1f}%",
                "disk": f"{disk.percent:>5.1f}%",
                "battery": f"{battery.percent:.0f}% {'⚡' if battery.power_plugged else '🔋'}" if battery else "—",
                "net": net_str,
                "time": datetime.now().strftime("%H:%M:%S"),
            }

            # Color coding
            if cpu > 90:
                self._colors = {"cpu": "#FF4444"}
            elif cpu > 75:
                self._colors = {"cpu": "#FFB800"}
            else:
                self._colors = {"cpu": "#00AAFF"}

            if ram.percent > 90:
                self._colors["ram"] = "#FF4444"
            elif ram.percent > 75:
                self._colors["ram"] = "#FFB800"
            else:
                self._colors["ram"] = "#B8D4E8"

        except Exception as e:
            logger.debug(f"[HUD] Stats error: {e}")

    def _refresh_labels(self):
        """Update all label values."""
        if self._root is None:
            return
        try:
            for key, value in self._stats.items():
                if key in self._labels and key != "time":
                    color = self._colors.get(key, "#B8D4E8")
                    self._labels[key].config(text=value, fg=color)
            if "time" in self._labels:
                self._labels["time"].config(text=self._stats.get("time", ""))
        except Exception:
            pass

    def _loop(self):
        """Background update loop."""
        while self._running:
            try:
                self._update_stats()
                self._refresh_labels()
            except Exception as e:
                logger.debug(f"[HUD] Update error: {e}")
            time.sleep(2)  # Update every 2 seconds

    def start(self):
        """Start the HUD overlay."""
        if self._running:
            return
        self._running = True
        self._colors = {}
        try:
            self._create_window()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="SystemHUD")
            self._thread.start()
            logger.info("[SystemHUD] Started")
        except Exception as e:
            logger.error(f"[SystemHUD] Failed to start: {e}")
            self._running = False

    def stop(self):
        """Stop and close the HUD."""
        self._running = False
        if self._root:
            try:
                self._root.destroy()
                self._root = None
            except Exception:
                pass

    def update(self, key: str, value: str, color: str | None = None):
        """Update a specific stat value from outside."""
        self._stats[key] = value
        if key in self._labels:
            self._labels[key].config(text=value, fg=color or "#B8D4E8")

    def set_status(self, text: str, color: str = "#00FF88"):
        """Update the status text."""
        if "status" in self._labels:
            self._labels["status"].config(text=text, fg=color)
