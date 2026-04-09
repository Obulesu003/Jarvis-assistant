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

        # Play epic intro music FIRST - the "wow moment"
        _play_music("startup")

        # Base greeting with JARVIS personality
        if self._is_morning:
            if self._is_first_start:
                items.append("Good morning, Bobby. I hope you slept well.")
                items.append("JARVIS is online. Systems operational.")
            else:
                items.append("Good morning. Welcome back.")
        elif 12 <= hour < 17:
            items.append("Good afternoon, Bobby.")
        elif 17 <= hour < 21:
            items.append("Good evening, Bobby.")
        else:
            items.append("Good night, Bobby. Working late?")

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
            self._speak("Briefing complete. How may I assist you?")

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
        """Check for new emails."""
        try:
            from integrations.outlook.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            result = adapter.execute_action("list_emails", folder="Inbox", max_results=5, unread_only=True)

            if result and hasattr(result, 'data'):
                emails = result.data.get("emails", [])
                if emails:
                    count = len(emails)
                    if count == 1:
                        return {
                            "category": "email",
                            "speech": f"You have one unread email.",
                            "data": emails,
                            "should_speak": True,
                        }
                    else:
                        return {
                            "category": "email",
                            "speech": f"You have {count} unread emails.",
                            "data": emails,
                            "should_speak": True,
                        }
            return None
        except Exception as e:
            logger.debug(f"[Briefing] Email check failed: {e}")
            return None

    def _check_calendar(self) -> dict | None:
        """Check today's calendar events."""
        try:
            from integrations.outlook.outlook_adapter import OutlookAdapter
            adapter = OutlookAdapter()
            today = datetime.now().strftime("%Y-%m-%d")
            result = adapter.execute_action("list_events", date=today, max_results=5)

            if result and hasattr(result, 'data'):
                events = result.data.get("events", [])
                if events:
                    if len(events) == 1:
                        return {
                            "category": "calendar",
                            "speech": f"You have one event today: {events[0].get('title', 'Busy')}",
                            "data": events,
                            "should_speak": True,
                        }
                    else:
                        return {
                            "category": "calendar",
                            "speech": f"You have {len(events)} events today.",
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
