"""
proactive_monitor.py - JARVIS's watchful daemon.
Monitors everything and speaks when it matters. Also engages the user when idle.
"""
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class SpeakRef:
    """Holds a reference to the speak function that can be updated later."""
    def __init__(self):
        self._func = None
    def set(self, func):
        self._func = func
    def __call__(self, *args, **kwargs):
        if self._func:
            return self._func(*args, **kwargs)


# ── Idle conversation topics ──────────────────────────────────────────────

_IDLE_FRIENDLY_MESSAGES = [
    "Sir, is there anything I can assist you with?",
    "Sir, I haven't heard from you in a while. Is everything alright?",
    "Just checking in, sir. I'm here if you need me.",
    "Sir, I see you're rather quiet. Feel free to ask me anything.",
    "Standing by, sir. I've noticed you haven't given me a task in some time.",
    "Sir, just a gentle reminder — I'm ready to help whenever you need.",
]


def _get_idle_message() -> str:
    import random
    return random.choice(_IDLE_FRIENDLY_MESSAGES)


# ── ProactiveMonitor ─────────────────────────────────────────────────────────

class ProactiveMonitor:
    """
    JARVIS's watchful daemon. Three jobs:
    1. Monitor system state and speak on changes (email, calendar, system health)
    2. Engage the user when they've been idle too long
    3. Learn from user interactions and adapt

    Runs in a background thread, checks every 30 seconds.
    """

    def __init__(self, speak_func=None, memory=None):
        self._speak_ref = SpeakRef()
        if speak_func:
            self._speak_ref.set(speak_func)
        self._memory = memory
        self._running = False
        from core.conversation_context import ConversationContextEngine
        self._ctx: ConversationContextEngine | None = None
        from core.pattern_learner import InteractionPatternLearner
        self._pattern_learner: InteractionPatternLearner | None = None
        self._thread: threading.Thread | None = None

        # State tracking (only speak on CHANGES)
        self._last_email_count: int | None = None
        self._last_calendar_event: str | None = None
        self._last_system_health: dict | None = None
        self._last_weather: str | None = None

        # Idle detection
        self._idle_since: float = time.time()       # Time of last user interaction
        self._idle_interval: float = 10 * 60         # 10 minutes before friendly ping
        self._idle_patience: float = 15 * 60        # 15 minutes before second ping
        self._last_idle_speak: float = 0            # Last time we spoke about idleness
        self._idle_pings: int = 0                  # How many idle pings we've done

        # Custom monitors
        self._monitors: list[dict] = []

        # HUD alert callback — updated by main.py to show proactive alerts
        self._on_alert: callable | None = None

        # Track last user input time for idle detection
        self._register_input_tracker()

    def _register_input_tracker(self):
        """Track user input to detect idleness."""
        import ctypes
        try:
            SPI_GETLASTINPUTINFO = 0x0D

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

            # Initial read to set baseline
            ctypes.windll.User32.SystemParametersInfoW(SPI_GETLASTINPUTINFO, 0, ctypes.byref(lii), 0)
            self._idle_since = time.time()
            self._baseline_ticks = lii.dwTime
        except Exception:
            self._baseline_ticks = 0

    def set_speak(self, speak_func):
        """Set the speak function."""
        self._speak_ref.set(speak_func)

    def set_context_engine(self, ctx: "ConversationContextEngine"):
        """Inject the ConversationContextEngine from JarvisLive."""
        self._ctx = ctx

    def set_pattern_learner(self, learner: "InteractionPatternLearner"):
        """Inject the InteractionPatternLearner from JarvisLive."""
        self._pattern_learner = learner

    def set_dnd_check(self, dnd_check: callable):
        """
        Set a callable that returns True when JARVIS is in do-not-disturb mode.
        When True, proactive volunteering is suppressed.

        Args:
            dnd_check: A callable that returns bool (e.g. gesture_ctrl.is_do_not_disturb)
        """
        self._dnd_check = dnd_check

    def _is_dnd(self) -> bool:
        """Return True if do-not-disturb mode is active."""
        dnd = getattr(self, "_dnd_check", None)
        return dnd() if dnd else False

    def _get_speak(self):
        """Get the current speak function."""
        return self._speak_ref._func

    def register_monitor(self, check_func: callable, on_change_func: callable):
        """Register a custom monitor. check_func returns current state, on_change_func reacts."""
        self._monitors.append({"check": check_func, "on_change": on_change_func})

    def start(self):
        """Start the proactive monitor daemon."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ProactiveMonitor")
        self._thread.start()
        logger.info("[ProactiveMonitor] Started — JARVIS is watching...")

    def stop(self):
        """Stop the proactive monitor."""
        self._running = False

    def _update_idle_time(self):
        """Update idle detection from Windows last input info."""
        try:
            import ctypes
            SPI_GETLASTINPUTINFO = 0x0D

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.User32.SystemParametersInfoW(SPI_GETLASTINPUTINFO, 0, ctypes.byref(lii), 0):
                current_ticks = lii.dwTime
                # Handle tick counter wrap-around (~49.7 day wrap)
                if current_ticks >= self._baseline_ticks:
                    idle_ms = (current_ticks - self._baseline_ticks) * 10  # ticks are in ms
                else:
                    idle_ms = ((0xFFFFFFFF - self._baseline_ticks) + current_ticks + 1) * 10

                if idle_ms < 1000:  # User provided input within last second
                    self._idle_since = time.time()
                    self._idle_pings = 0  # Reset idle pings when user is active
                self._baseline_ticks = current_ticks
        except Exception:
            pass

    def _loop(self):
        """Main monitoring loop."""
        check_count = 0
        while self._running:
            try:
                self._update_idle_time()
                self._check_all()

                # Idle check — every 5th check (~2.5 minutes) after main checks
                self._check_idle()

            except Exception as e:
                logger.error(f"[ProactiveMonitor] Check error: {e}")
            time.sleep(30)
            check_count += 1

    def _check_idle(self):
        """If user has been idle for too long, engage them with a friendly message."""
        idle_seconds = time.time() - self._idle_since

        # First ping: after _idle_interval (10 min)
        # Second ping: 15 min more
        # Maximum: one ping every 15 minutes
        max_interval = 15 * 60

        if idle_seconds < self._idle_interval:
            return  # User hasn't been idle long enough

        # Respect do-not-disturb mode (gesture: fist)
        if self._is_dnd():
            return

        # Check with ConversationContextEngine
        if self._ctx and self._ctx.should_volunteer():
            topic = self._ctx.volunteer_topic()
            if topic:
                logger.info(f"[ProactiveMonitor] Volunteering: {topic}")
                self._speak_ref(topic)
                self._last_idle_speak = time.time()
                self._idle_pings = 0
                return

        # Speak at most once per max_interval
        if self._last_idle_speak > 0 and (time.time() - self._last_idle_speak) < max_interval:
            return

        # Only speak if user isn't doing anything important (check via last input)
        msg = _get_idle_message()
        if self._speak_ref._func:
            self._speak_ref(msg)
            self._last_idle_speak = time.time()
            logger.info(f"[ProactiveMonitor] Idle ping #{self._idle_pings + 1}")
            self._idle_pings += 1

    def _check_all(self):
        """Check everything in parallel."""
        with ThreadPoolExecutor(max_workers=8) as ex:
            f_email = ex.submit(self._check_emails)
            f_calendar = ex.submit(self._check_calendar)
            f_system = ex.submit(self._check_system)
            f_custom = [ex.submit(m["check"]) for m in self._monitors]

        # Process results — speak only on changes
        self._process_email(f_email.result())
        self._process_calendar(f_calendar.result())
        self._process_system(f_system.result())

        for i, f in enumerate(f_custom):
            try:
                result = f.result(timeout=5)
                self._monitors[i]["on_change"](result)
            except Exception:
                pass

    def record_activity(self):
        """Call this when the user interacts — resets idle timer."""
        self._idle_since = time.time()
        self._idle_pings = 0

    def _check_emails(self) -> dict:
        """Check for new unread emails."""
        try:
            from integrations.outlook.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            result = adapter.execute_action("list_emails", folder="Inbox", max_results=5, unread_only=True)
            if result and hasattr(result, "data"):
                emails = result.data.get("emails", [])
                top = emails[0] if emails else None
                return {
                    "unread": len(emails),
                    "top_sender": top.get("sender", "someone") if top else None,
                    "top_subject": top.get("subject", "") if top else "",
                }
        except Exception as e:
            logger.debug(f"[ProactiveMonitor] Email check failed: {e}")
        return {"unread": 0}

    def _check_calendar(self) -> dict:
        """Check for upcoming calendar events."""
        try:
            from integrations.outlook.outlook_adapter import OutlookAdapter
            from datetime import datetime
            adapter = OutlookAdapter()
            today = datetime.now().strftime("%Y-%m-%d")
            result = adapter.execute_action("list_events", date=today, max_results=10)
            if result and hasattr(result, "data"):
                events = result.data.get("events", [])
                next_event = None
                now = datetime.now()
                for ev in events:
                    start = ev.get("start")
                    if start:
                        try:
                            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                            if dt > now:
                                next_event = ev
                                break
                        except Exception:
                            pass
                return {"next_event": next_event, "all_events": events}
        except Exception as e:
            logger.debug(f"[ProactiveMonitor] Calendar check failed: {e}")
        return {"next_event": None}

    def _check_system(self) -> dict:
        """Check system health metrics."""
        try:
            import psutil
            battery = psutil.sensors_battery()
            return {
                "cpu_percent": psutil.cpu_percent(interval=0.5),
                "ram_percent": psutil.virtual_memory().percent,
                "disk_free_gb": round(psutil.disk_usage("/").free / (1024**3), 1),
                "battery": battery.percent if battery else None,
                "charging": battery.power_plugged if battery else None,
            }
        except Exception as e:
            logger.debug(f"[ProactiveMonitor] System check failed: {e}")
            return {}

    def _process_email(self, data: dict):
        """New email? Tell JARVIS about it."""
        unread = data.get("unread", 0)
        if self._last_email_count is not None and unread > self._last_email_count:
            sender = data.get("top_sender", "someone")
            subject = data.get("top_subject", "")
            msg = f"Sir, you have a new email from {sender}"
            if subject:
                msg += f". Subject: {subject}"
            self._speak(msg)
            if self._memory:
                self._memory.remember("notification", msg)
        self._last_email_count = unread

    def _process_calendar(self, data: dict):
        """Upcoming event in 15 minutes? Warn proactively."""
        event = data.get("next_event")
        if not event:
            return
        title = event.get("title", "event")
        start = event.get("start", "")
        event_key = f"{title}:{start}"
        if event_key == self._last_calendar_event:
            return
        self._last_calendar_event = event_key

        try:
            from datetime import datetime
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            now = datetime.now()
            minutes_until = (dt - now).total_seconds() / 60
            if 10 <= minutes_until <= 20:
                msg = f"Reminder, sir: {title} starts in {int(minutes_until)} minutes."
                self._speak(msg)
                if self._memory:
                    self._memory.remember("reminder", msg)
        except Exception:
            pass

    def _process_system(self, data: dict):
        """System anomaly? Warn immediately."""
        if not data:
            return

        cpu = data.get("cpu_percent", 0)
        disk = data.get("disk_free_gb", 999)
        battery = data.get("battery")

        if cpu > 95 and self._last_system_health and self._last_system_health.get("cpu_percent", 0) <= 95:
            self._speak(f"Sir, CPU usage is critically high at {int(cpu)} percent.")
        elif disk < 5 and self._last_system_health and self._last_system_health.get("disk_free_gb", 999) >= 5:
            self._speak(f"Disk space warning — only {disk} gigabytes remaining.")
        elif battery is not None and battery < 10 and (not self._last_system_health or self._last_system_health.get("battery", 100) >= 10):
            self._speak(f"Battery critically low at {int(battery)} percent, sir. I recommend plugging in.")

        self._last_system_health = data

    def _speak(self, text: str):
        """Speak text via the registered speak function. Also fires _on_alert."""
        func = self._speak_ref._func
        if func:
            try:
                func(text)
            except Exception as e:
                logger.error(f"[ProactiveMonitor] Speak error: {e}")
        # Also update HUD with the alert
        if self._on_alert:
            try:
                self._on_alert(text)
            except Exception:
                pass