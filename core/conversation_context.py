"""
ConversationContextEngine - Tracks conversational state across turns and enables proactive volunteering.
"""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.memory_manager import JARVISMemory


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

        # Default: no volunteer needed
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
        """
        Check for new emails that should be volunteered.

        Returns:
            A message about new emails, or None
        """
        if self._memory is None:
            return None
        # Placeholder - actual implementation would check email service
        return None

    def _upcoming_event(self) -> str | None:
        """
        Check for upcoming calendar events that should be volunteered.

        Returns:
            A message about an upcoming event, or None
        """
        if self._memory is None:
            return None
        # Placeholder - actual implementation would check calendar
        return None

    def _memory_recall_suggestion(self) -> str | None:
        """
        Check memory for relevant recall suggestions.

        Returns:
            A memory recall suggestion, or None
        """
        if self._memory is None:
            return None
        try:
            topic = self._memory.get_recent_topic()
            if topic:
                return f"You were working on {topic}. Would you like to continue?"
        except (AttributeError, TypeError) as e:
            logger.debug(f"[ContextEngine] Memory recall failed: {e}")
            return None
        return None

    def _system_health_check(self) -> str | None:
        """
        Check system health for issues that should be volunteered.

        Returns:
            A message about system health, or None
        """
        # Placeholder - actual implementation would check system metrics
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

        Extracts words longer than 4 characters (up to 3), or falls back
        to the first 30 characters of the text.

        Args:
            text: The user's input text

        Returns:
            A topic string
        """
        # Split into words and filter for significant words (>4 chars)
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

        # Return description for first matching tool
        for tool in tools_used:
            tool_lower = tool.lower()
            for key, description in tool_descriptions.items():
                if key in tool_lower:
                    return description

        # Fallback: use first tool name
        if tools_used:
            return f"working on: {tools_used[0]}"

        return "working"
