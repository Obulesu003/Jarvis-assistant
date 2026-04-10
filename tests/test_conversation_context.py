"""
Tests for ConversationContextEngine.
"""

import time
from unittest.mock import MagicMock

import pytest

from core.conversation_context import ConversationContextEngine


class TestConversationContextEngine:
    """Test cases for ConversationContextEngine."""

    def test_initial_state(self):
        """Verify all attributes initialized correctly."""
        engine = ConversationContextEngine()

        assert engine.current_goal is None
        assert engine.pending_confirmation == []
        assert engine.interrupted is False
        assert engine.interrupted_text == ""
        assert isinstance(engine.idle_since, float)
        assert engine.interaction_count == 0
        assert engine.last_topic is None
        assert engine.last_volunteer_at == 0.0
        assert engine._memory is None

    def test_on_user_turn_updates_idle_and_count(self):
        """After calling on_user_turn, verify idle_since increased and interaction_count == 1."""
        engine = ConversationContextEngine()
        initial_idle = engine.idle_since

        # Small delay to ensure time difference
        time.sleep(0.01)

        engine.on_user_turn("Hello, how are you?")

        assert engine.idle_since > initial_idle
        assert engine.interaction_count == 1

    def test_on_jarvis_turn_clears_interrupted(self):
        """Set interrupted=True, call on_jarvis_turn, verify interrupted is False."""
        engine = ConversationContextEngine()
        engine.interrupted = True
        engine.interrupted_text = "I was in the middle of"

        engine.on_jarvis_turn("Hello user!", [])

        assert engine.interrupted is False

    def test_on_interruption_records_text(self):
        """Call on_interruption, verify interrupted is True and get_interrupted_text() returns correct text."""
        engine = ConversationContextEngine()

        engine.on_interruption("I was about to say something important")

        assert engine.interrupted is True
        assert engine.get_interrupted_text() == "I was about to say something important"

    def test_get_interrupted_text_after_clear(self):
        """Interrupt then clear, verify get_interrupted_text() returns empty."""
        engine = ConversationContextEngine()

        engine.on_interruption("Some interrupted text")
        engine.clear_interrupted()

        assert engine.get_interrupted_text() == ""
        assert engine.interrupted is False

    def test_should_volunteer_too_soon(self):
        """Set idle_since = time.time(), verify should_volunteer() is False."""
        engine = ConversationContextEngine()

        # Set idle_since to now (not enough idle time)
        engine.idle_since = time.time()

        result = engine.should_volunteer()

        assert result is False

    def test_volunteer_topic_empty_when_no_facts(self):
        """With no memory injected, volunteer_topic() returns None."""
        engine = ConversationContextEngine()
        engine._system_health_check = MagicMock(return_value=None)

        result = engine.volunteer_topic()

        assert result is None

    def test_extract_topic_simple(self):
        """Verify topic extraction picks significant words."""
        engine = ConversationContextEngine()

        # Test with longer words
        topic = engine._extract_topic("I want to set up a Python project")
        assert "Python" in topic
        assert "project" in topic

        # Test with short words only - only "there" is > 4 chars
        topic_short = engine._extract_topic("Hi there")
        assert topic_short == "there"  # Only words > 4 chars are returned

    def test_describe_goal_email(self):
        """Verify 'email' tool maps to 'composing an email'."""
        engine = ConversationContextEngine()

        goal = engine._describe_goal(["email"])
        assert goal == "composing an email"

    def test_volunteer_topic_returns_when_memory_injected(self):
        """Mock memory's get_recent_topic() to return 'Python project setup', verify volunteer returns a suggestion."""
        engine = ConversationContextEngine()

        # Create a mock memory
        mock_memory = MagicMock()
        mock_memory.get_recent_topic.return_value = "Python project setup"

        engine.inject_memory(mock_memory)

        result = engine.volunteer_topic()

        assert result is not None
        assert "Python project setup" in result
        mock_memory.get_recent_topic.assert_called_once()
