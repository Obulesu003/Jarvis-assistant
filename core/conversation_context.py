"""
ConversationContextEngine - Tracks conversational state across turns and enables proactive volunteering.
"""
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.memory_manager import JARVISMemory

logger = logging.getLogger(__name__)

# Language detection word lists
ENGLISH_WORDS = frozenset([
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them", "see",
    "other", "than", "then", "now", "look", "only", "come", "its", "over",
    "think", "also", "back", "after", "use", "two", "how", "our", "work",
    "first", "well", "way", "even", "new", "want", "because", "any", "these",
    "give", "day", "most", "us", "hello", "hi", "hey", "check", "show", "send",
    "weather", "email", "calendar", "reminder", "search", "open", "play", "call",
    "thanks", "fine", "okay", "ok", "great", "awesome",
])

TURKISH_WORDS = frozenset([
    "bir", "ve", "bu", "da", "de", "için", "ile", "ne", "var", "yok",
    "ben", "sen", "o", "biz", "siz", "onlar", "kim", "kime", "nerede", "nasıl",
    "bugün", "yarın", "dün", "şimdi", "sonra", "önce", "daha", "çok", "az",
    "gün", "ay", "yıl", "saat", "dakika", "evet", "hayır", "merhaba", "selam",
    "naber", "nasılsın", "iyiyim", "teşekkür", "tşk", "lütfen", "rica", "edermisin",
    "yap", "yapabilir", "mi", "mı", "mu", "mü", "eğer", "ama", "fakat", "veya",
    "çünkü", "o", "şu", "bunu", "şunu", "kendine", "kendim", "hangi", "kaç",
    "ev", "iş", "okul", "araba", "telefon", "bilgisayar", "su", "yiyecek",
    "hava", "durumu", "gelecek", "plan", "toplantı", "randevu", "hatırlat",
    "mail", "eposta", "mesaj", "ara", "bul", "getir", "göster", "söyle", "anlat",
])


@dataclass
class LanguageContext:
    """Tracks language state for multilingual support."""
    primary: str = "en"  # en | tr | mixed
    confidence: float = 0.5
    history: list = None

    def __post_init__(self):
        if self.history is None:
            self.history = []


class ConversationContextEngine:
    """
    Tracks conversational state across turns, enables proactive volunteering,
    and manages interruptions for the JARVIS assistant.
    """

    def __init__(self) -> None:
        """Initialize all conversation context attributes."""
        self.current_goal: str | None = None
        self.pending_confirmation: list[tuple[str, str]] = []
        self.interrupted: bool = False
        self.interrupted_text: str = ""
        self.idle_since: float = time.time()
        self.interaction_count: int = 0
        self.last_topic: str | None = None
        self.last_volunteer_at: float = 0.0
        self._memory: "JARVISMemory | None" = None
        self._language_context = LanguageContext()
        self._user_language: str = "en"

    def inject_memory(self, memory: "JARVISMemory") -> None:
        """
        Inject a JARVISMemory instance for use in proactive volunteering.

        Args:
            memory: JARVISMemory instance to use for memory operations
        """
        self._memory = memory

    def on_user_turn(self, text: str) -> None:
        """
        Record a user turn, updating idle time, interaction count, and topic.

        Args:
            text: The user's input text
        """
        self.idle_since = time.time()
        self.interaction_count += 1
        self.last_topic = self._extract_topic(text)

    def on_jarvis_turn(self, text: str, tools_used: list[str]) -> None:
        """
        Record a JARVIS turn, updating idle time and potentially setting the current goal.

        Args:
            text: JARVIS's response text
            tools_used: List of tool names used in this turn
        """
        self.idle_since = time.time()
        self.interrupted = False
        if tools_used:
            self.current_goal = self._describe_goal(tools_used)
        else:
            self.current_goal = None

    def on_interruption(self, jarvis_in_progress: str) -> None:
        """
        Record that the user interrupted JARVIS mid-sentence.

        Args:
            jarvis_in_progress: The text JARVIS was saying when interrupted
        """
        self.interrupted = True
        self.interrupted_text = jarvis_in_progress
        self.idle_since = time.time()

    def get_interrupted_text(self) -> str:
        """
        Get the text that was being spoken when the interruption occurred.

        Returns:
            The interrupted text, or empty string if not interrupted
        """
        return self.interrupted_text

    def clear_interrupted(self) -> None:
        """Clear the interrupted state."""
        self.interrupted = False
        self.interrupted_text = ""

    def detect_and_track_language(self, text: str) -> str:
        """
        Detect the language of the input text and update tracking.

        Args:
            text: Input text to analyze

        Returns:
            Language code: "en", "tr", or "mixed"
        """
        if not text or not text.strip():
            return self._user_language

        text_lower = text.lower()
        words = text_lower.split()

        en_count = sum(1 for w in words if w in ENGLISH_WORDS)
        tr_count = sum(1 for w in words if w in TURKISH_WORDS)

        total = en_count + tr_count
        if total == 0:
            return self._user_language

        en_ratio = en_count / total
        tr_ratio = tr_count / total

        if en_ratio > 0.7:
            detected = "en"
        elif tr_ratio > 0.7:
            detected = "tr"
        else:
            detected = "mixed"

        self._user_language = detected
        self._language_context.history.append(detected)
        if len(self._language_context.history) > 5:
            self._language_context.history.pop(0)

        return detected

    def get_language_context(self) -> str:
        """
        Get a language context string for LLM injection.

        Returns:
            A language guidance string for the current language
        """
        if self._user_language == "tr":
            return (
                "The user is communicating primarily in Turkish. "
                "Respond in Turkish with a respectful, formal tone. "
                "Use Turkish grammar and vocabulary naturally."
            )
        elif self._user_language == "mixed":
            return (
                "The user is mixing languages. Match their language mix naturally. "
                "You may respond in either language or mix as they do."
            )
        else:
            return ""

    def update_language(self, lang: str) -> None:
        """
        Manually update the user's preferred language.

        Args:
            lang: Language code (en, tr, mixed)
        """
        self._user_language = lang
        self._language_context.primary = lang

    def should_volunteer(self) -> bool:
        """
        Determine if JARVIS should proactively volunteer information.

        Returns:
            True if conditions suggest JARVIS should volunteer, False otherwise
        """
        now = time.time()
        idle_seconds = now - self.idle_since
        seconds_since_volunteer = now - self.last_volunteer_at

        # Must be idle for at least 5 minutes (300 seconds)
        if idle_seconds < 300:
            return False

        # Must have waited at least 600 seconds since last volunteer
        if seconds_since_volunteer < 600:
            return False

        # Check if there's a significant change or user likely available
        if self._significant_change_detected() or self._user_likely_available():
            return True

        return False

    def volunteer_topic(self) -> str | None:
        """
        Get the topic JARVIS should volunteer about, if any.

        Checks various conditions in priority order:
        1. New emails
        2. Upcoming events
        3. Memory recall suggestions
        4. System health check

        Returns:
            A volunteer message string, or None if no volunteer is appropriate
        """
        # Check new emails
        email_topic = self._check_new_emails()
        if email_topic is not None:
            self.last_volunteer_at = time.time()
            return email_topic

        # Check upcoming events
        event_topic = self._upcoming_event()
        if event_topic is not None:
            self.last_volunteer_at = time.time()
            return event_topic

        # Check memory recall suggestions
        memory_topic = self._memory_recall_suggestion()
        if memory_topic is not None:
            self.last_volunteer_at = time.time()
            return memory_topic

        # Check system health
        health_topic = self._system_health_check()
        if health_topic is not None:
            self.last_volunteer_at = time.time()
            return health_topic

        return None

    def _check_new_emails(self) -> str | None:
        """Check for new emails that should be volunteered."""
        try:
            outlook = __import__(
                "integrations.outlook.outlook_native_adapter",
                fromlist=["OutlookNativeAdapter"],
            )
            adapter = outlook.OutlookNativeAdapter()
            result = adapter.execute_action("get_unread_count", {}) or 0
            if result and result > 0:
                return f"You have {result} unread message{'s' if result > 1 else ''}."
        except Exception as e:
            logger.debug(f"[ContextEngine] Email check failed: {e}")
        return None

    def _upcoming_event(self) -> str | None:
        """Check for upcoming calendar events within the next 2 hours."""
        try:
            cal = __import__(
                "integrations.calendar.calendar_adapter",
                fromlist=["CalendarAdapter"],
            )
            adapter = cal.CalendarAdapter()
            events = adapter.get_upcoming_events(hours=2) or []
            if events:
                ev = events[0]
                title = ev.get("title", "an event")
                start = ev.get("start", "")
                return f"Sir, you have {title} starting at {start}."
        except Exception as e:
            logger.debug(f"[ContextEngine] Calendar check failed: {e}")
        return None

    def _memory_recall_suggestion(self) -> str | None:
        """Check memory for relevant recall suggestions."""
        if self._memory is None:
            return None
        try:
            topic = self._memory.get_recent_topic()
            if topic:
                return f"You were working on {topic}. Would you like to continue?"
        except (AttributeError, TypeError) as e:
            logger.debug(f"[ContextEngine] Memory recall failed: {e}")
        return None

    def _system_health_check(self) -> str | None:
        """Check system health for issues that should be volunteered."""
        try:
            import psutil

            messages = []

            # Battery low
            try:
                battery = psutil.sensors_battery()
                if battery and not battery.power_plugged and battery.percent < 20:
                    messages.append(f"battery is at {battery.percent} percent")
            except Exception:
                pass

            # CPU high
            try:
                cpu = psutil.cpu_percent(interval=0.1)
                if cpu > 90:
                    messages.append(f"CPU usage is at {cpu:.0f} percent")
            except Exception:
                pass

            # Memory high
            try:
                mem = psutil.virtual_memory()
                if mem.percent > 90:
                    messages.append(f"memory is at {mem.percent:.0f} percent")
            except Exception:
                pass

            if messages:
                if self._user_language == "tr":
                    verbs = {
                        "battery is at": "pil şarjı",
                        "CPU usage is at": "işlemci kullanımı",
                        "memory is at": "bellek kullanımı",
                    }
                    tr_messages = []
                    for m in messages:
                        for en, tr in verbs.items():
                            if en in m:
                                tr_messages.append(m.replace(en, tr))
                    return f"Sir, {', '.join(tr_messages)}."
                return f"Sir, {', '.join(messages)}."
        except Exception as e:
            logger.debug(f"[ContextEngine] Health check failed: {e}")
        return None

    def _significant_change_detected(self) -> bool:
        """
        Detect if there has been a significant change that warrants volunteering.

        Returns:
            False by default (placeholder for future implementation)
        """
        return False

    def _user_likely_available(self) -> bool:
        """
        Detect if the user is likely available for interaction.

        Returns:
            False by default (placeholder for future implementation)
        """
        return False

    def _extract_topic(self, text: str) -> str:
        """
        Extract a topic/keyword summary from the user's input.

        Args:
            text: The user's input text

        Returns:
            A topic string
        """
        words = text.split()
        significant_words = [w for w in words if len(w) > 4]

        if significant_words:
            return " ".join(significant_words[:3])
        return text[:30] if text else ""

    def _describe_goal(self, tools_used: list[str]) -> str:
        """
        Map tool names to human-readable goal descriptions.

        Args:
            tools_used: List of tool names that were used

        Returns:
            A description of what JARVIS is working on
        """
        tool_descriptions = {
            "email": "composing an email",
            "calendar": "checking calendar",
            "weather": "checking weather",
            "search": "searching the web",
            "reminder": "setting a reminder",
            "whatsapp": "sending a WhatsApp message",
        }

        for tool in tools_used:
            tool_lower = tool.lower()
            for key, description in tool_descriptions.items():
                if key in tool_lower:
                    return description

        if tools_used:
            return f"working on: {tools_used[0]}"

        return "working"
