"""
welcome_briefing.py - MARK-XXXV Morning/Unlock Briefing System
Delivers personalized, epic briefings when JARVIS starts or unlocks.
"""

import sys
import time
import threading
import logging
import json
from pathlib import Path
from typing import Callable
from datetime import datetime

logger = logging.getLogger(__name__)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()

# Music singleton (lazy import to avoid early import issues)
_music_player = None


def _get_music():
    """Lazy-load intro music module."""
    global _music_player
    if _music_player is None:
        from core.intro_music import play_startup_scene, play_unlock_scene, play_wake_scene, preload_music
        _music_player = {
            "startup": play_startup_scene,
            "unlock": play_unlock_scene,
            "wake": play_wake_scene,
            "preload": preload_music,
        }
    return _music_player


def _play_music(scene_type: str = "startup") -> None:
    """Play intro music for a scene."""
    try:
        m = _get_music()
        m[scene_type]()
    except Exception as e:
        logger.debug(f"[Briefing] Music play failed: {e}")


class WelcomeBriefing:
    """
    Generates epic welcome briefings based on time of day and user context.
    Checks: emails, calendar, weather, reminders, news, etc.
    """

    def __init__(self, speak_func: Callable | None = None):
        self._speak = speak_func
        self._briefing_items: list[dict] = []
        self._is_morning = False
        self._is_first_start = True

    def set_speak(self, speak_func: Callable):
        """Set the speak function."""
        self._speak = speak_func

    def speak(self, text: str, priority: str = "normal"):
        """Speak text to the user."""
        if self._speak:
            try:
                self._speak(text)
            except Exception as e:
                logger.error(f"[Briefing] Speak error: {e}")

    def generate_briefing(self) -> list[str]:
        """Generate briefing items to be spoken."""
        items = []

        # Determine time of day
        hour = datetime.now().hour
        self._is_morning = 5 <= hour < 12

        # Play clean JARVIS startup beeps FIRST - the "wow moment"
        _play_music("startup")

        # JARVIS-style greeting - short, crisp, no fluff
        if self._is_first_start:
            if self._is_morning:
                items.append("Good morning, Bobby. All systems online.")
            else:
                items.append("JARVIS online, Bobby. Systems nominal.")
        else:
            if self._is_morning:
                items.append("Good morning. Welcome back, sir.")
            elif 12 <= hour < 17:
                items.append("Good afternoon, Bobby.")
            elif 17 <= hour < 21:
                items.append("Good evening, Bobby.")
            else:
                items.append("Working late, Bobby?")

        self._is_first_start = False
        return items

    async def run_full_briefing(self, ui=None, speak_func: Callable | None = None):
        """Run the complete welcome briefing."""
        if speak_func:
            self._speak = speak_func

        logger.info("[Briefing] Starting welcome briefing...")

        # Generate greeting
        greeting_items = self.generate_briefing()

        # Greet first
        for item in greeting_items:
            if self._speak:
                self._speak(item)
                await self._delay(1500)  # Pause between items

        # Check and report items in parallel for speed
        briefing_items = await self._collect_briefing_items(ui)

        # Report each item with pauses
        for item in briefing_items:
            if item.get("should_speak", True):
                text = item.get("speech", "")
                if text and self._speak:
                    self._speak(text)
                    await self._delay(1000)

        # Final closing
        if self._speak:
            self._speak("Briefing complete. Standing by for your command, sir.")

        logger.info("[Briefing] Briefing complete")

    def run_briefing_sync(self, ui=None):
        """Run briefing synchronously."""
        import asyncio
        try:
            asyncio.run(self.run_full_briefing(ui=ui))
        except Exception as e:
            logger.error(f"[Briefing] Sync run error: {e}")

    async def _collect_briefing_items(self, ui=None) -> list[dict]:
        """Collect all briefing items in parallel."""
        from concurrent.futures import ThreadPoolExecutor
        import asyncio

        items = []

        # Collect data in parallel using threads
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(self._check_emails),
                executor.submit(self._check_calendar),
                executor.submit(self._check_weather),
                executor.submit(self._check_reminders),
                executor.submit(self._check_memory),
                executor.submit(self._check_running_apps),
            ]

            for future in futures:
                try:
                    result = future.result(timeout=10)
                    if result:
                        items.append(result)
                except Exception as e:
                    logger.debug(f"[Briefing] Item collection error: {e}")

        return items

    def _check_emails(self) -> dict | None:
        """Check for new emails using native Outlook (no browser)."""
        try:
            from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
            adapter = OutlookNativeAdapter()
            result = adapter.execute_action("list_emails", folder="Inbox", max_results=5, unread_only=True)

            if result and hasattr(result, 'data'):
                emails = result.data.get("emails", [])
                if emails:
                    count = len(emails)
                    # Show actual subjects - not just a count
                    subjects = [e.get("subject", "No subject") for e in emails[:3]]
                    if count == 1:
                        speech = f"You have one unread email from {emails[0].get('sender', 'someone')}: {emails[0].get('subject', 'No subject')}"
                    elif count <= 3:
                        subject_list = ". ".join(subjects)
                        speech = f"You have {count} unread emails: {subject_list}"
                    else:
                        subject_list = ". ".join(subjects)
                        speech = f"You have {count} unread emails. Top subjects: {subject_list}. And {count - 3} more."
                    return {
                        "category": "email",
                        "speech": speech,
                        "data": emails,
                        "should_speak": True,
                    }
            return None
        except Exception as e:
            logger.debug(f"[Briefing] Email check failed: {e}")
            return None

    def _check_calendar(self) -> dict | None:
        """Check today's calendar events using native Outlook (no browser)."""
        try:
            from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
            adapter = OutlookNativeAdapter()
            today = datetime.now().strftime("%Y-%m-%d")
            result = adapter.execute_action("list_calendar_events", start_date=today, end_date=today, max_results=5)

            if result and hasattr(result, 'data'):
                events = result.data.get("events", [])
                if events:
                    # Show actual event details with times
                    event_parts = []
                    for ev in events[:4]:
                        title = ev.get("title", "Busy")
                        start_str = ev.get("start", "")
                        try:
                            start_dt = datetime.strptime(start_str[:16], "%Y-%m-%d %H:%M:%S")
                            time_str = start_dt.strftime("%-I:%M %p")
                        except Exception:
                            time_str = "TBD"
                        event_parts.append(f"{title} at {time_str}")

                    if len(events) == 1:
                        speech = f"Today's event: {event_parts[0]}"
                    elif len(events) <= 4:
                        event_list = ". ".join(event_parts)
                        speech = f"You have {len(events)} events today: {event_list}"
                    else:
                        event_list = ". ".join(event_parts)
                        speech = f"You have {len(events)} events today. Up next: {event_list}. And {len(events) - 4} more."
                    return {
                        "category": "calendar",
                        "speech": speech,
                        "data": events,
                        "should_speak": True,
                    }
            return None
        except Exception as e:
            logger.debug(f"[Briefing] Calendar check failed: {e}")
            return None

    def _check_weather(self) -> dict | None:
        """Check weather."""
        try:
            # Load user location from memory
            memory = self._load_memory()
            city = memory.get("identity", {}).get("city", {}).get("value", "Istanbul")

            # Use weather action
            from actions.weather_report import weather_action
            result = weather_action({"city": city}, player=None)
            if result:
                return {
                    "category": "weather",
                    "speech": f"Weather in {city}: {result}",
                    "data": result,
                    "should_speak": True,
                }
            return None
        except Exception as e:
            logger.debug(f"[Briefing] Weather check failed: {e}")
            return None

    def _check_reminders(self) -> dict | None:
        """Check active reminders."""
        try:
            from core.scheduler import get_scheduler
            scheduler = get_scheduler()
            schedules = scheduler.list_schedules()

            active = [s for s in schedules if s.get("enabled", True)]
            if active:
                return {
                    "category": "reminders",
                    "speech": f"You have {len(active)} active reminders.",
                    "data": active,
                    "should_speak": True,
                }
            return None
        except Exception as e:
            logger.debug(f"[Briefing] Reminder check failed: {e}")
            return None

    def _check_memory(self) -> dict | None:
        """Check memory for personalized context."""
        try:
            memory = self._load_memory()

            # Check for shop/work schedule
            shop_time = memory.get("notes", {}).get("shop_opening_time", {}).get("value")
            if shop_time:
                hour = datetime.now().hour
                # If it's around shop opening time
                if 14 <= hour <= 17:
                    return {
                        "category": "schedule",
                        "speech": f"Shop opens at {shop_time}.",
                        "data": shop_time,
                        "should_speak": True,
                    }

            return None
        except Exception as e:
            logger.debug(f"[Briefing] Memory check failed: {e}")
            return None

    def _check_running_apps(self) -> dict | None:
        """Check what apps are running and identify the active window."""
        try:
            from integrations.system.system_adapter import SystemAutomationAdapter
            adapter = SystemAutomationAdapter()
            result = adapter.execute_action("list_running_apps")

            if result and hasattr(result, 'data'):
                apps_data = result.data.get("apps", [])

                # Get active window
                try:
                    from core.screen_monitor import ScreenMonitor
                    sm = ScreenMonitor()
                    active_window = sm.get_active_window_title()
                except Exception:
                    active_window = ""

                # Identify media/music players
                media_keywords = ["spotify", "youtube", "vlc", "music", "groove",
                                 "audacity", "chrome", "firefox", "edge", "whatsapp",
                                 "discord", "telegram", "teams", "zoom", "slack",
                                 "notepad", "vscode", "code", "terminal", "cmd",
                                 "powershell", "explorer", "outlook", "excel",
                                 "word", "powerpoint", "paint", "taskbar"]

                notable_apps = []
                for app in apps_data:
                    name_lower = app.get("name", "").lower()
                    for keyword in media_keywords:
                        if keyword in name_lower:
                            display_name = app.get("name", "?").replace(".exe", "")
                            if display_name not in notable_apps:
                                notable_apps.append(display_name)
                            break

                # Build context-aware summary
                parts = []
                if active_window and active_window not in ["Unknown", "No active window"]:
                    parts.append(f"Active window: {active_window}")

                if notable_apps:
                    visible_apps = notable_apps[:6]  # Cap at 6 for brevity
                    if len(notable_apps) > 6:
                        parts.append(f"Running: {', '.join(visible_apps)} and {len(notable_apps) - 6} more")
                    else:
                        parts.append(f"Running: {', '.join(visible_apps)}")

                if parts:
                    return {
                        "category": "apps",
                        "speech": " | ".join(parts),
                        "data": {"active": active_window, "apps": notable_apps},
                        "should_speak": True,
                    }
            return None
        except Exception as e:
            logger.debug(f"[Briefing] Running apps check failed: {e}")
            return None

    def _load_memory(self) -> dict:
        """Load user memory."""
        try:
            from memory.memory_manager import load_memory
            return load_memory()
        except Exception:
            return {}

    async def _delay(self, ms: int):
        """Async delay."""
        import asyncio
        await asyncio.sleep(ms / 1000)

    def generate_epic_startup_message(self) -> str:
        """Generate an epic startup line."""
        import random

        lines = [
            "JARVIS online. All systems nominal.",
            "Running system diagnostics. All clear.",
            "Systems online. Ready to serve.",
            "Welcome back. JARVIS at your service.",
            "Initializing... systems operational.",
            "Good to be back online, sir.",
        ]

        if self._is_morning:
            morning_lines = [
                "Rise and shine. Morning systems check complete.",
                "Good morning. I trust you slept well.",
                "Dawn has broken. All systems report ready.",
            ]
            lines = morning_lines + lines

        return random.choice(lines)

    def generate_unlock_message(self, lock_duration: float | None = None) -> str:
        """Generate message after unlock."""
        import random

        # Play unlock cue music
        _play_music("unlock")

        if lock_duration:
            minutes = int(lock_duration / 60)
            if minutes > 60:
                return f"Welcome back, Bobby. You were away for {minutes // 60} hours."
            elif minutes > 5:
                return f"Back again? You were gone for {minutes} minutes."
            else:
                return "Welcome back."

        return random.choice([
            "Welcome back, sir.",
            "Good to see you again.",
            "You're back. All systems standing by.",
            "Back online.",
        ])


def run_briefing_sync(speak_func: Callable, ui=None):
    """Run briefing synchronously (for thread use)."""
    briefing = WelcomeBriefing(speak_func=speak_func)
    briefing.run_full_briefing(ui=ui)


# Singleton instance
_briefing: WelcomeBriefing | None = None


def get_briefing() -> WelcomeBriefing:
    """Get the global briefing instance."""
    global _briefing
    if _briefing is None:
        _briefing = WelcomeBriefing()
    return _briefing
