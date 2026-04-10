"""
Tests for proactive volunteering in ConversationContextEngine.
"""
import pytest
import time
from unittest.mock import MagicMock, patch
from core.conversation_context import ConversationContextEngine


class TestProactiveVolunteering:
    """Test cases for proactive volunteering."""

    @pytest.fixture
    def engine(self):
        """Create a context engine."""
        return ConversationContextEngine()

    def test_should_volunteer_idle_too_short(self, engine):
        """Should not volunteer when idle less than 5 minutes."""
        engine.idle_since = time.time() - 100  # Only 100 seconds idle
        assert engine.should_volunteer() is False

    def test_should_volunteer_recent_volunteer(self, engine):
        """Should not volunteer within 10 minutes of last volunteer."""
        engine.idle_since = time.time() - 400  # 6+ minutes idle
        engine.last_volunteer_at = time.time() - 100  # Spoke 100 seconds ago
        assert engine.should_volunteer() is False

    def test_should_volunteer_no_significant_change(self, engine):
        """Should not volunteer when no significant changes detected."""
        engine.idle_since = time.time() - 700  # 10+ minutes idle
        engine.last_volunteer_at = time.time() - 700  # Haven't volunteered recently
        # Both _significant_change_detected and _user_likely_available return False
        assert engine.should_volunteer() is False

    def test_volunteer_topic_no_memory(self, engine):
        """volunteer_topic should return None when no memory injected."""
        result = engine.volunteer_topic()
        # Should try all checks and return None
        assert result is None

    def test_volunteer_topic_with_memory(self, engine):
        """volunteer_topic should check memory when available."""
        mock_memory = MagicMock()
        mock_memory.get_recent_topic.return_value = "Python project"
        engine.inject_memory(mock_memory)

        result = engine.volunteer_topic()
        assert result is not None
        assert "Python project" in result

    def test_volunteer_topic_updates_timestamp(self, engine):
        """volunteer_topic should update last_volunteer_at."""
        engine.idle_since = time.time() - 700
        mock_memory = MagicMock()
        mock_memory.get_recent_topic.return_value = "Python"
        engine.inject_memory(mock_memory)

        before = engine.last_volunteer_at
        engine.volunteer_topic()
        assert engine.last_volunteer_at >= before

    def test_volunteer_topic_priority_email(self, engine):
        """volunteer_topic should prioritize email check."""
        engine._check_new_emails = MagicMock(return_value="You have 3 unread messages.")
        engine._upcoming_event = MagicMock(return_value="Event found")
        engine._memory_recall_suggestion = MagicMock(return_value="Memory recall")
        engine._system_health_check = MagicMock(return_value=None)

        result = engine.volunteer_topic()
        assert result == "You have 3 unread messages."

    def test_volunteer_topic_priority_event(self, engine):
        """volunteer_topic should prioritize event check after email."""
        engine._check_new_emails = MagicMock(return_value=None)
        engine._upcoming_event = MagicMock(return_value="You have a meeting at 3 PM")
        engine._memory_recall_suggestion = MagicMock(return_value=None)
        engine._system_health_check = MagicMock(return_value=None)

        result = engine.volunteer_topic()
        assert "meeting" in result

    def test_on_user_turn_resets_idle(self, engine):
        """on_user_turn should reset idle_since."""
        engine.idle_since = time.time() - 1000
        before = engine.idle_since
        engine.on_user_turn("Hello JARVIS")
        assert engine.idle_since >= before
        assert engine.interaction_count == 1

    def test_on_jarvis_turn_clears_interrupted(self, engine):
        """on_jarvis_turn should clear interrupted state."""
        engine.interrupted = True
        engine.interrupted_text = "I was saying..."
        engine.on_jarvis_turn("Here is the response", ["email"])
        assert engine.interrupted is False

    def test_on_interruption_records_text(self, engine):
        """on_interruption should record the interrupted text."""
        engine.on_interruption("I was in the middle of...")
        assert engine.interrupted is True
        assert engine.interrupted_text == "I was in the middle of..."

    def test_get_interrupted_text(self, engine):
        """get_interrupted_text should return interrupted text."""
        engine.interrupted = True
        engine.interrupted_text = "Looking up your"
        result = engine.get_interrupted_text()
        assert result == "Looking up your"

    def test_clear_interrupted(self, engine):
        """clear_interrupted should reset state."""
        engine.interrupted = True
        engine.interrupted_text = "Some text"
        engine.clear_interrupted()
        assert engine.interrupted is False
        assert engine.interrupted_text == ""

    def test_on_jarvis_turn_sets_goal(self, engine):
        """on_jarvis_turn should set current_goal from tools."""
        engine.on_jarvis_turn("Checking emails", ["email"])
        assert engine.current_goal == "composing an email"
