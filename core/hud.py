"""
hud.py - JARVIS holographic HUD — transparent, always-on-top overlay.
Shows: status, time, weather, reminders, screen context, waveform.
Position: bottom-right corner. Color scheme: JARVIS blue (#00AAFF).
"""
import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_hud = None  # Singleton
_ambient_dashboard = None  # Ambient dashboard instance


class JARVISHUD:
    """
    JARVIS holographic HUD — transparent, always-on-top, CPU-light.
    Uses DearPyGui for GPU-accelerated overlay rendering.
    """

    def __init__(self):
        self._state = "idle"
        self._response = ""
        self._screen_context = ""
        self._reminders: list[str] = []
        self._weather = ""
        self._time = ""
        self._is_running = False
        self._dpg = None
        self._screen_w = 1920
        self._screen_h = 1080
        self._current_state_color = [0, 180, 255]
        self._context_lock = threading.Lock()

    def _build_ui(self, dpg, screen_w: int, screen_h: int):
        """Build the HUD layout in DearPyGui."""
        with dpg.window(
            tag="HUD_WINDOW",
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_close=True,
            no_bring_to_focus_on_tip=True,
            transparent_frame=True,
            alpha=220,
            show=True,
        ):
            dpg.configure_item(
                "HUD_WINDOW",
                pos=[screen_w - 440, screen_h - 380],
                width=420,
                height=360,
            )

            # Status indicator + label
            with dpg.group(tag="STATUS_ROW"):
                dpg.add_circle(radius=5, color=[0, 180, 255], fill=[0, 180, 255], tag="STATUS_CIRCLE")
                dpg.add_same_line(x_offset=8)
                dpg.add_text("JARVIS", color=[0, 180, 255], bold=True, font=1)
                dpg.add_same_line(x_offset=10)
                dpg.add_text("", tag="STATE_TEXT", color=[150, 150, 150])

            dpg.add_separator()

            # Time display
            dpg.add_text("", tag="TIME_TEXT", color=[80, 160, 220])

            # Weather
            dpg.add_text("", tag="WEATHER_TEXT", color=[180, 180, 180], wrap=400)

            # Reminders
            dpg.add_text("", tag="REMINDER_TEXT", color=[255, 200, 80], wrap=400)

            dpg.add_separator()

            # Screen context
            dpg.add_text("", tag="SCREEN_TEXT", color=[120, 120, 120], wrap=400)

            # Response
            dpg.add_text("", tag="RESPONSE_TEXT", color=[0, 255, 180], wrap=400)

            dpg.add_separator()

            # Waveform placeholder
            with dpg.plot(tag="WAVEFORM", height=30, width=400):
                dpg.add_plot_axis(dpg.mvXAxis, no_tick_labels=True, no_tick_marks=True)
                dpg.add_plot_axis(dpg.mvYAxis, no_tick_labels=True, no_tick_marks=True)
                dpg.add_line_series([], [], color=[0, 180, 255], tag="WAVEFORM_LINE")

    def initialize(self):
        """Initialize the HUD."""
        try:
            import dearpygui.dearpygui as dpg
            self._dpg = dpg
            dpg.create_context()

            # Get screen dimensions via ctypes
            try:
                import ctypes
                user32 = ctypes.windll.user32
                sw = user32.GetSystemMetrics(0)
                sh = user32.GetSystemMetrics(1)
            except Exception:
                sw, sh = 1920, 1080

            self._screen_w = sw
            self._screen_h = sh

            self._build_ui(dpg, sw, sh)

            # Transparent viewport
            viewport = dpg.create_viewport(
                title="JARVIS",
                width=sw,
                height=sh,
                decorated=False,
                transparent=True,
                always_on_top=True,
                resizable=False,
                vsync=True,
                alpha=True,
            )
            dpg.configure_viewport_item(viewport, "HUD_WINDOW")
            dpg.setup_dearpygui()
            logger.info("[HUD] DearPyGui HUD initialized")
        except ImportError:
            logger.warning("[HUD] dearpygui not installed. Run: pip install dearpygui")
            self._dpg = None

    def set_state(self, state: str):
        """Update JARVIS state (idle | listening | processing | speaking)."""
        self._state = state
        if not self._dpg:
            return

        colors = {
            "idle": [100, 100, 100],
            "listening": [0, 180, 255],
            "processing": [255, 200, 0],
            "speaking": [0, 255, 180],
        }
        fill = colors.get(state, [255, 255, 255])
        dpg = self._dpg
        try:
            dpg.configure_item("STATUS_CIRCLE", fill=fill)
            dpg.configure_item("STATE_TEXT", default_value=state.upper(), color=colors.get(state, [255, 255, 255]))
        except Exception:
            pass

    def show_response(self, text: str):
        """Display JARVIS response."""
        self._response = text
        if self._dpg:
            try:
                self._dpg.configure_item("RESPONSE_TEXT", default_value=text)
            except Exception:
                pass

    def set_screen_context(self, description: str):
        """Show what JARVIS sees on screen."""
        self._screen_context = description
        if self._dpg:
            try:
                self._dpg.configure_item("SCREEN_TEXT", default_value=f"Screen: {description[:80]}")
            except Exception:
                pass

    def set_weather(self, text: str):
        """Show weather info."""
        self._weather = text
        if self._dpg:
            try:
                self._dpg.configure_item("WEATHER_TEXT", default_value=text)
            except Exception:
                pass

    def set_reminders(self, reminders: list[str]):
        """Show active reminders."""
        self._reminders = reminders
        if self._dpg:
            try:
                text = " | ".join(reminders[:3]) if reminders else "No active reminders"
                self._dpg.configure_item("REMINDER_TEXT", default_value=text)
            except Exception:
                pass

    def update_time(self) -> None:
        """Update time display."""
        now = datetime.now().strftime("%H:%M:%S")
        self._time = now
        if self._dpg:
            try:
                self._dpg.configure_item("TIME_TEXT", default_value=f"JARVIS — {now}")
            except Exception:
                pass

    def set_status_color(self, rgb: tuple[int, int, int]) -> None:
        """Change the JARVIS status circle color."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("STATUS_CIRCLE", color=rgb, fill=rgb)
            self._current_state_color = rgb
        except Exception:
            pass

    def set_state_label(self, label: str) -> None:
        """Set the state text label."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("STATE_TEXT", default_value=label)
        except Exception:
            pass

    def set_volunteer_mode(self, enabled: bool):
        """Switch to gold volunteer color scheme."""
        if not self._dpg:
            return
        try:
            if enabled:
                self._dpg.configure_item("STATE_TEXT", default_value="JARVIS (PROACTIVE)", color=[255, 180, 0])
                self._dpg.configure_item("STATUS_CIRCLE", color=[255, 180, 0], fill=[255, 180, 0])
            elif hasattr(self, '_current_state_color'):
                self._dpg.configure_item("STATE_TEXT", default_value="JARVIS", color=self._current_state_color)
                self._dpg.configure_item("STATUS_CIRCLE", color=self._current_state_color, fill=self._current_state_color)
        except Exception:
            pass

    def show_activity(self, text: str):
        """Briefly flash a tool activity indicator for 2 seconds."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("SCREEN_TEXT", default_value=f"[Working] {text}")
            def clear():
                time.sleep(2)
                try:
                    with self._context_lock:
                        context = self._screen_context
                    if context:
                        self._dpg.configure_item("SCREEN_TEXT", default_value=f"Screen: {context[:80]}")
                    else:
                        self._dpg.configure_item("SCREEN_TEXT", default_value="")
                except Exception:
                    pass
            threading.Thread(target=clear, daemon=True).start()
        except Exception:
            pass

    def flash_success(self):
        """Brief green flash on successful tool completion."""
        if not self._dpg:
            return
        try:
            original_color = [0, 255, 180]
            self._dpg.configure_item("RESPONSE_TEXT", color=[0, 255, 100])
            def reset():
                time.sleep(0.3)
                try:
                    self._dpg.configure_item("RESPONSE_TEXT", color=original_color)
                except Exception:
                    pass
            threading.Thread(target=reset, daemon=True).start()
        except Exception:
            pass

    def show_preview(self, text: str, duration: float):
        """Show text before JARVIS speaks it proactively."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("RESPONSE_TEXT", default_value=f"[Preview] {text[:80]}")
            def clear():
                time.sleep(duration)
                try:
                    self._dpg.configure_item("RESPONSE_TEXT", default_value="")
                except Exception:
                    pass
            threading.Thread(target=clear, daemon=True).start()
        except Exception:
            pass

    def set_jarcircle_opacity(self, alpha: int):
        """Update the JARVIS circle's opacity for breathing effect."""
        if not self._dpg:
            return
        try:
            r, g, b = self._current_state_color
            self._dpg.configure_item("STATUS_CIRCLE", color=[r, g, b, alpha], fill=alpha)
        except Exception:
            pass

    def update_waveform(self, data: list) -> None:
        """Update the waveform visualization."""
        if not self._dpg or not data:
            return
        try:
            x_vals = list(range(len(data)))
            self._dpg.configure_item("WAVEFORM_LINE", x=x_vals, y=data)
        except Exception:
            pass

    def run(self):
        """Start the HUD render loop."""
        if not self._dpg:
            logger.warning("[HUD] HUD not initialized")
            return

        self._is_running = True
        self._dpg.show_viewport()

        while self._dpg.is_dearpygui_running():
            self.update_time()
            self._dpg.render_dearpygui_frame()
            time.sleep(0.016)  # ~60fps

        self._is_running = False

    def stop(self):
        """Stop the HUD render loop."""
        self._is_running = False
        if self._dpg:
            try:
                self._dpg.stop_dearpygui()
            except Exception:
                pass

    def run_threaded(self):
        """Start HUD in a background thread."""
        thread = threading.Thread(target=self.run, daemon=True, name="HUD")
        thread.start()

    def show_ambient_dashboard(self, show: bool, system_snapshot=None):
        """
        Show or hide the ambient awareness dashboard.

        Args:
            show: True to show, False to hide
            system_snapshot: Optional SystemSnapshot instance for data collection
        """
        global _ambient_dashboard

        if show:
            if _ambient_dashboard is None and system_snapshot is not None:
                from core.ambient_dashboard import AmbientDashboard
                _ambient_dashboard = AmbientDashboard(self, system_snapshot)
            if _ambient_dashboard is not None:
                _ambient_dashboard.show()
        else:
            if _ambient_dashboard is not None:
                _ambient_dashboard.hide()

    def toggle_ambient_dashboard(self, system_snapshot=None):
        """Toggle the ambient dashboard visibility."""
        global _ambient_dashboard

        if _ambient_dashboard is None and system_snapshot is not None:
            from core.ambient_dashboard import AmbientDashboard
            _ambient_dashboard = AmbientDashboard(self, system_snapshot)

        if _ambient_dashboard is not None:
            _ambient_dashboard.toggle()

    def get_ambient_dashboard(self):
        """Get the ambient dashboard instance."""
        global _ambient_dashboard
        return _ambient_dashboard


def get_hud() -> JARVISHUD | None:
    """Get the global HUD instance."""
    global _hud
    if _hud is None:
        _hud = JARVISHUD()
        _hud.initialize()
    return _hud


def start_hud():
    """Create and start the HUD."""
    hud = get_hud()
    if hud:
        hud.run_threaded()
    return hud
