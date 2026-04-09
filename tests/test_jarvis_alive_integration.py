"""
End-to-end tests for JARVIS Alive features.
Tests the complete flow across ConversationContextEngine, MemoryBridge, and VisualPresenceEngine.
"""

import time
import unittest.mock as mock

import pytest

from core.conversation_context import ConversationContextEngine
from core.memory_bridge import MemoryBridge
from core.visual_presence import JARVISVisualState, VisualPresenceEngine


class TestIntegrationTurnModel:
    """Test the complete turn model: user -> JARVIS -> interruption -> resume."""

    def test_full_interruption_flow(self) -> None:
        """Verify complete interruption and resume flow across conversation states."""
        ctx = ConversationContextEngine()

        # User asks a question
        ctx.on_user_turn("What's my battery level?")
        assert ctx.interaction_count == 1
        assert ctx.last_topic is not None

        # JARVIS starts responding
        ctx.on_jarvis_turn("Your battery is at 45 percent.", ["system_check"])
        assert ctx.interrupted is False
        assert ctx.current_goal == "working on: system_check"

        # User interrupts - on_interruption takes what JARVIS was saying
        ctx.on_interruption("Your battery is at 45 percent")
        assert ctx.interrupted is True
        assert "battery" in ctx.get_interrupted_text()

        # After JARVIS responds to the interruption
        ctx.clear_interrupted()
        ctx.on_jarvis_turn("Done, sir.", ["email"])
        assert ctx.interrupted is False

    def test_context_engine_with_memory_bridge(self) -> None:
        """Verify ConversationContextEngine integrates with MemoryBridge context building."""
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = ["You prefer British voice"]
        mock_mem.procedural.get_active.return_value = ["HUD project"]
        mock_mem.get_recent_topic.return_value = "Python scripting"
        mock_mem.get_preferences_for.return_value = []

        ctx = ConversationContextEngine()
        ctx.inject_memory(mock_mem)

        bridge = MemoryBridge(mock_mem)
        ctx_str = bridge.build_context("open files")

        assert "WHAT I KNOW ABOUT YOU" in ctx_str
        assert "British voice" in ctx_str
        assert "ACTIVE PROJECTS" in ctx_str
        assert "HUD project" in ctx_str
        assert "Python scripting" in ctx_str

    def test_volunteer_flow(self) -> None:
        """Verify volunteer topic selection works with memory context."""
        ctx = ConversationContextEngine()
        mock_mem = mock.MagicMock()
        mock_mem.get_recent_topic.return_value = "Python project"
        ctx.inject_memory(mock_mem)

        # volunteer_topic() should return a suggestion based on memory
        # Message format: "You were working on {topic}. Would you like to continue?"
        topic = ctx.volunteer_topic()
        assert topic is not None
        assert "Python project" in topic  # More specific - matches actual format

        # Verify last_volunteer_at is updated after volunteering
        assert ctx.last_volunteer_at > 0

    def test_visual_presence_state_flow(self) -> None:
        """Verify VisualPresenceEngine state transitions and HUD interactions."""
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)

        # Normal listening
        vpe.set_state(JARVISVisualState.LISTENING)
        assert vpe._state == JARVISVisualState.LISTENING
        mock_hud.set_status_color.assert_called_with((0, 180, 255))

        # Tool execution
        vpe.on_tool_start("email")
        mock_hud.show_activity.assert_called_with("email")

        # Tool completion
        vpe.on_tool_complete()
        mock_hud.flash_success.assert_called_once()

        # Volunteer mode
        vpe.set_state(JARVISVisualState.VOLUNTEERING)
        mock_hud.set_volunteer_mode.assert_called_with(True)

        # Interruption
        vpe.on_interrupted("Checking your calendar")
        assert vpe._state == JARVISVisualState.INTERRUPTED

    def test_memory_bridge_preferences_context(self) -> None:
        """Verify MemoryBridge includes user preferences in context."""
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = []
        mock_mem.procedural.get_active.return_value = []
        mock_mem.get_recent_topic.return_value = None
        mock_mem.get_preferences_for.return_value = ["Dark theme preferred", "24-hour time format"]

        bridge = MemoryBridge(mock_mem)
        ctx_str = bridge.build_context("set alarm")

        assert "USER PREFERENCES" in ctx_str
        assert "Dark theme" in ctx_str
        assert "24-hour" in ctx_str

    def test_conversation_topic_extraction(self) -> None:
        """Verify topic extraction from user input across multiple turns."""
        ctx = ConversationContextEngine()

        ctx.on_user_turn("Can you check my unread emails please")
        # Verify topic extraction captured "emails" (6 chars > 4 threshold)
        assert "emails" in ctx.last_topic

        ctx.on_user_turn("Actually, never mind, set a reminder instead")
        # Topic should update - _extract_topic takes first 30 chars when no word >4
        # The input has "actually" (9 chars) but comma included, so checks words
        # Fallback: first 30 chars of text after comma becomes the topic
        assert ctx.last_topic is not None
        assert len(ctx.last_topic) > 0
        # Verify the topic was extracted (either significant words or fallback)
        assert "never" in ctx.last_topic or len(ctx.last_topic) <= 30

    def test_interrupted_text_preservation(self) -> None:
        """Verify interrupted text is preserved until explicitly cleared."""
        ctx = ConversationContextEngine()

        # Simulate interruption mid-sentence
        ctx.on_interruption("I was just about to tell you that your")
        assert ctx.get_interrupted_text() == "I was just about to tell you that your"
        assert ctx.interrupted is True

        # Multiple interruptions - latest wins
        ctx.on_interruption("Another interruption here")
        assert "Another interruption" in ctx.get_interrupted_text()
        assert "about to tell you" not in ctx.get_interrupted_text()

    def test_memory_bridge_empty_context(self) -> None:
        """Verify MemoryBridge returns empty string when no memory exists."""
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = []
        mock_mem.procedural.get_active.return_value = []
        mock_mem.get_recent_topic.return_value = None
        mock_mem.get_preferences_for.return_value = []

        bridge = MemoryBridge(mock_mem)
        ctx_str = bridge.build_context("generic query")

        assert ctx_str == ""

    def test_visual_presence_state_colors(self) -> None:
        """Verify all visual states have correct colors mapped."""
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)

        expected_colors = {
            JARVISVisualState.IDLE: (60, 60, 60),
            JARVISVisualState.LISTENING: (0, 180, 255),
            JARVISVisualState.THINKING: (255, 200, 0),
            JARVISVisualState.SPEAKING: (0, 255, 180),
            JARVISVisualState.VOLUNTEERING: (255, 180, 0),
            JARVISVisualState.INTERRUPTED: (255, 100, 100),
        }

        for state, expected_color in expected_colors.items():
            vpe.set_state(state)
            assert mock_hud.set_status_color.call_args[0][0] == expected_color

    def test_should_not_volunteer_when_recently_volunteered(self) -> None:
        """Verify volunteering is suppressed if attempted too soon."""
        ctx = ConversationContextEngine()
        mock_mem = mock.MagicMock()
        mock_mem.get_recent_topic.return_value = "test"
        ctx.inject_memory(mock_mem)

        # idle_since 400s ago (exceeds 5-min minimum of 300s)
        ctx.idle_since = time.time() - 400
        # last_volunteer_at 100s ago (within 10-min suppression window of 600s)
        ctx.last_volunteer_at = time.time() - 100

        assert ctx.should_volunteer() is False

    def test_should_not_volunteer_when_not_idle_long_enough(self) -> None:
        """Verify volunteering is suppressed if not idle long enough."""
        ctx = ConversationContextEngine()
        mock_mem = mock.MagicMock()
        mock_mem.get_recent_topic.return_value = "test"
        ctx.inject_memory(mock_mem)

        # Only idle for 120s (below 5-min minimum of 300s)
        ctx.idle_since = time.time() - 120
        ctx.last_volunteer_at = 0

        assert ctx.should_volunteer() is False
