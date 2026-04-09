"""
system_tray.py - JARVIS System Tray Icon
Shows JARVIS in the Windows notification area with right-click menu.
"""
import io
import logging
import threading
import sys

logger = logging.getLogger(__name__)

_tray_instance = None


def get_system_tray():
    global _tray_instance
    if _tray_instance is None:
        _tray_instance = SystemTray()
    return _tray_instance


class SystemTray:
    """
    JARVIS system tray icon — always-on presence in Windows notification area.
    Right-click menu: Open HUD, Status, Stop JARVIS.
    """

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._tray = None
        self._on_stop_callback: callable | None = None

    def set_stop_callback(self, func: callable):
        """Set callback for Stop JARVIS menu item."""
        self._on_stop_callback = func

    def _make_icon(self):
        """Create a simple JARVIS-blue icon from raw bytes (avoids PIL dependency)."""
        try:
            from PIL import Image, ImageDraw
            # 16x16 JARVIS blue icon
            img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # Draw a simple "J" shape in JARVIS blue
            draw.ellipse([2, 2, 14, 14], fill=(0, 170, 255), outline=(0, 140, 220), width=1)
            draw.rectangle([5, 5, 11, 8], fill=(0, 170, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except ImportError:
            # No PIL — try loading from face.png
            try:
                from pathlib import Path
                face_path = Path("face.png")
                if face_path.exists():
                    from PIL import Image
                    img = Image.open(face_path).convert("RGBA").resize((16, 16))
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    return buf.getvalue()
            except Exception:
                pass
            return None

    def _run_loop(self):
        """Run the tray icon loop."""
        try:
            import pystray
            from PIL import Image

            icon_bytes = self._make_icon()
            if icon_bytes:
                img = Image.open(io.BytesIO(icon_bytes))
            else:
                # Fallback: solid JARVIS blue square
                img = Image.new("RGB", (16, 16), (0, 170, 255))

            menu = pystray.Menu(
                pystray.MenuItem("JARVIS MARK XXXV", lambda _: None, enabled=False),
                pystray.MenuItem("Status: Online", lambda _: None, enabled=False),
                pystray.MenuItem("─", lambda _: None, enabled=False),
                pystray.MenuItem("Show Cinematic HUD", self._show_hud),
                pystray.MenuItem("Show System Stats", self._show_stats),
                pystray.MenuItem("─", lambda _: None, enabled=False),
                pystray.MenuItem("Stop JARVIS", self._stop_jarvis),
            )

            self._tray = pystray.Icon(
                "JARVIS",
                img,
                "JARVIS MARK XXXV — Online",
                menu,
            )
            self._tray.run()
        except ImportError:
            logger.warning("[Tray] pystray not installed. Run: pip install pystray")
        except Exception as e:
            logger.error(f"[Tray] Failed to start: {e}")

    def _show_hud(self):
        """Show the cinematic HUD."""
        try:
            from core.hud import get_hud
            hud = get_hud()
            logger.info("[Tray] Show HUD clicked")
        except Exception as e:
            logger.debug(f"[Tray] Show HUD: {e}")

    def _show_stats(self):
        """Show system stats."""
        try:
            import psutil
            battery = psutil.sensors_battery()
            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory().percent
            msg = f"CPU: {cpu:.0f}% | RAM: {ram:.0f}%"
            if battery:
                msg += f" | Battery: {battery.percent:.0f}%"
            logger.info(f"[Tray] Stats: {msg}")
        except Exception as e:
            logger.debug(f"[Tray] Stats: {e}")

    def _stop_jarvis(self):
        """Stop JARVIS from tray menu."""
        logger.info("[Tray] Stop JARVIS clicked")
        if self._on_stop_callback:
            try:
                self._on_stop_callback()
            except Exception:
                pass
        self.stop()
        # Exit the whole process
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass
        sys.exit(0)

    def start(self):
        """Start the system tray icon in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="SystemTray")
        self._thread.start()
        logger.info("[SystemTray] Started")

    def stop(self):
        """Stop and remove the tray icon."""
        self._running = False
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None

