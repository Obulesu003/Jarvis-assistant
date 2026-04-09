"""
screen_watchdog.py - JARVIS Screen Watchdog
Periodically captures the screen, analyzes it with AI, and alerts on important changes.
"Sir, I noticed a error message on screen" / "There's a new notification from WhatsApp"
"""
import base64
import io
import logging
import threading
import time
import collections

logger = logging.getLogger(__name__)

# ── Singleton ─────────────────────────────────────────────────────────────────

_watchdog_instance = None


def get_screen_watchdog():
    global _watchdog_instance
    if _watchdog_instance is None:
        _watchdog_instance = ScreenWatchdog()
    return _watchdog_instance


class ScreenWatchdog:
    """
    JARVIS watches your screen proactively.
    Every INTERVAL seconds: capture → analyze → alert if important.

    Alerts generated for:
    - Error dialogs / crash messages
    - New notifications (email, WhatsApp, etc.)
    - Low battery warning
    - Meeting reminder notifications
    - Download complete / file saved confirmations
    - Any text that looks important but was not there last time
    """

    INTERVAL = 30  # seconds between captures
    MAX_HISTORY = 10  # keep last N descriptions for comparison

    def __init__(self, gemini_client=None):
        self._gemini = gemini_client
        self._running = False
        self._thread: threading.Thread | None = None
        self._speak_func = None
        self._last_description = ""
        self._description_history = collections.deque(maxlen=self.MAX_HISTORY)
        self._last_alert_time = 0
        self._alert_cooldown = 300  # minimum 5 min between alerts

        # Track what was visible in the last capture
        self._last_window_title = ""
        self._last_notification_area = ""

        # Important patterns to look for
        self._important_keywords = [
            "error", "crash", "failed", "warning", "alert",
            "unread", "new message", "notification", "battery low",
            "meeting", "reminder", "download complete", "update available",
            "memory", "storage", "disk full", "connection lost",
            "permission", "access denied", "timeout", "offline",
        ]

    def set_speak(self, func):
        """Set the speak function for alerts."""
        self._speak_func = func

    def _capture_screen(self) -> bytes | None:
        """Capture the screen as JPEG bytes."""
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb, "raw", "BGRX")
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=60)  # Low quality = smaller = faster
                return buffer.getvalue()
        except Exception as e:
            logger.debug(f"[Watchdog] Capture failed: {e}")
            return None

    def _get_window_title(self) -> str:
        """Get the currently active window title."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return ""
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            return buff.value or ""
        except Exception:
            return ""

    def _analyze_screen(self, img_bytes: bytes, window_title: str) -> dict:
        """
        Send screenshot to Gemini for analysis.
        Returns dict with: description, is_important, alert_message
        """
        if not self._gemini:
            return {"description": "", "is_important": False, "alert_message": ""}

        img_base64 = base64.b64encode(img_bytes).decode()

        prompt = """You are JARVIS's screen analyzer. Look at this screenshot and:
1. Describe what's on screen briefly (1-2 sentences)
2. Note any ERROR MESSAGES, WARNING dialogs, CRASH reports, or IMPORTANT NOTIFICATIONS
3. Note the active application/window
4. Note any NEW items that appeared since last time

Be concise. Focus on anything that requires user attention.

Respond ONLY as JSON:
{"description": "brief description", "important": true/false, "reason": "what is important", "app": "active app name"}"""

        try:
            response = self._gemini.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[prompt, img_base64]
            )
            text = response.text if hasattr(response, "text") else str(response)

            # Parse JSON response
            import json
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "description": data.get("description", ""),
                    "is_important": data.get("important", False),
                    "alert_message": data.get("reason", ""),
                    "app": data.get("app", window_title),
                }
            else:
                # Fallback: check for keywords in text
                text_lower = text.lower()
                is_important = any(kw in text_lower for kw in self._important_keywords)
                return {
                    "description": text[:200],
                    "is_important": is_important,
                    "alert_message": "Important content detected on screen" if is_important else "",
                    "app": window_title,
                }
        except Exception as e:
            logger.debug(f"[Watchdog] Analysis failed: {e}")
            return {"description": "", "is_important": False, "alert_message": "", "app": window_title}

    def _check_keyword_alerts(self, description: str, window_title: str) -> str | None:
        """
        Quick keyword-based alert check.
        Returns alert message if something important is detected.
        """
        desc_lower = description.lower()

        # Check window title changes
        if window_title and window_title != self._last_window_title:
            # New window appeared — check if it's an error dialog
            title_lower = window_title.lower()
            if any(kw in title_lower for kw in ["error", "warning", "crash", "alert", "failed"]):
                return f"Sir, I see an error dialog: {window_title}"

        # Check description for important keywords
        for kw in self._important_keywords:
            if kw in desc_lower:
                # Check if we mentioned this recently
                if kw not in self._last_description.lower():
                    return f"Sir, I noticed a {kw} message on screen"

        return None

    def _loop(self):
        """Main watchdog loop."""
        last_check_time = 0
        consecutive_failures = 0

        while self._running:
            try:
                now = time.time()
                if now - last_check_time < self.INTERVAL:
                    time.sleep(5)
                    continue

                last_check_time = now

                # Capture
                img_bytes = self._capture_screen()
                if not img_bytes:
                    consecutive_failures += 1
                    if consecutive_failures > 3:
                        logger.warning("[Watchdog] Multiple capture failures")
                    continue

                consecutive_failures = 0
                window_title = self._get_window_title()

                # Quick keyword check first (fast)
                # Re-capture for analysis (higher quality)
                img_bytes_hq = self._capture_screen()
                if not img_bytes_hq:
                    img_bytes_hq = img_bytes

                # Analyze with AI
                result = self._analyze_screen(img_bytes_hq, window_title)
                description = result.get("description", "")
                is_important = result.get("is_important", False)

                # Store history
                self._description_history.append(description)
                self._last_description = description

                # Generate alert
                alert_msg = None

                # Priority 1: Keyword-based alert (fast)
                kw_alert = self._check_keyword_alerts(description, window_title)
                if kw_alert:
                    alert_msg = kw_alert

                # Priority 2: AI-detected important content
                elif is_important and description:
                    alert_msg = f"Sir, {result.get('alert_message', 'something on screen requires your attention')}"

                # Priority 3: App change detection
                if result.get("app") and result["app"] != self._last_window_title:
                    self._last_window_title = result["app"]

                # Speak alert if meaningful and not too frequent
                if alert_msg and self._speak_func:
                    if now - self._last_alert_time > self._alert_cooldown:
                        self._speak_func(alert_msg)
                        self._last_alert_time = now
                        logger.info(f"[Watchdog] Alert: {alert_msg}")

            except Exception as e:
                logger.debug(f"[Watchdog] Loop error: {e}")

            time.sleep(5)

    def start(self):
        """Start the screen watchdog."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ScreenWatchdog")
        self._thread.start()
        logger.info("[Watchdog] Screen watchdog started")

    def stop(self):
        """Stop the screen watchdog."""
        self._running = False

    def set_interval(self, seconds: int):
        """Change the check interval."""
        self.INTERVAL = max(10, seconds)

    def force_check(self) -> str:
        """Force an immediate screen check. Returns description."""
        img_bytes = self._capture_screen()
        if not img_bytes:
            return "Screen capture unavailable."
        window_title = self._get_window_title()
        result = self._analyze_screen(img_bytes, window_title)
        return result.get("description", "Nothing notable on screen.")

    def get_last_description(self) -> str:
        """Get the last screen description."""
        return self._last_description
