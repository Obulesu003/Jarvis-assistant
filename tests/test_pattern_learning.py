"""
Tests for InteractionPatternLearner.
"""
import json
import tempfile
from pathlib import Path
import pytest

from core.pattern_learner import InteractionPatternLearner


class TestInteractionPatternLearner:
    """Test cases for InteractionPatternLearner."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def learner(self, temp_dir):
        """Create a learner with temporary directory."""
        return InteractionPatternLearner(memory_dir=str(temp_dir))

    def test_initial_state_empty(self, learner):
        """Initial patterns should be empty."""
        assert learner._patterns["chains"] == {}
        assert learner._patterns["feedback"] == {}

    def test_on_tool_used_tracks_chain(self, learner):
        """on_tool_used should add to current chain."""
        learner.on_tool_used("email")
        learner.on_tool_used("calendar")
        assert learner._current_chain == ["email", "calendar"]

    def test_on_turn_complete_saves_chain(self, learner):
        """on_turn_complete should save the chain."""
        learner.on_tool_used("email")
        learner.on_tool_used("calendar")
        learner.on_turn_complete(helpful=True)

        chain_key = "email -> calendar"
        assert chain_key in learner._patterns["chains"]
        assert learner._patterns["chains"][chain_key]["count"] == 1
        assert learner._patterns["chains"][chain_key]["helpful"] == 1

    def test_on_turn_complete_clears_chain(self, learner):
        """on_turn_complete should clear the current chain."""
        learner.on_tool_used("email")
        learner.on_turn_complete()
        assert learner._current_chain == []

    def test_on_turn_complete_with_unhelpful(self, learner):
        """on_turn_complete with helpful=False should increment unhelpful."""
        learner.on_tool_used("search")
        learner.on_turn_complete(helpful=False)

        chain_key = "search"
        assert learner._patterns["chains"][chain_key]["unhelpful"] == 1

    def test_on_turn_complete_empty_chain(self, learner):
        """on_turn_complete with empty chain should do nothing."""
        learner.on_turn_complete()
        assert learner._patterns["chains"] == {}

    def test_get_adaptive_context_empty(self, learner):
        """get_adaptive_context should return empty string when no patterns."""
        result = learner.get_adaptive_context("test request")
        assert result == ""

    def test_get_adaptive_context_with_patterns(self, temp_dir):
        """get_adaptive_context should return effective patterns."""
        from core.pattern_learner import InteractionPatternLearner
        learner = InteractionPatternLearner(memory_dir=str(temp_dir))
        # Each turn: record tool THEN complete
        for _ in range(3):
            learner.on_tool_used("email")
            learner.on_turn_complete(helpful=True)

        for _ in range(2):
            learner.on_tool_used("search")
            learner.on_turn_complete(helpful=False)

        context = learner.get_adaptive_context("check emails")
        assert "email" in context.lower()
        assert "success rate" in context.lower()

    def test_record_feedback(self, learner):
        """record_feedback should update tool feedback."""
        learner.record_feedback("email", helpful=True)
        learner.record_feedback("email", helpful=True)
        learner.record_feedback("search", helpful=False)

        assert learner._patterns["feedback"]["feedback_email"] == 2
        assert learner._patterns["feedback"]["feedback_search"] == -1

    def test_get_tool_effectiveness(self, learner):
        """get_tool_effectiveness should return tool score."""
        learner.record_feedback("email", helpful=True)
        learner.record_feedback("email", helpful=False)
        score = learner.get_tool_effectiveness("email")
        assert score == 0

    def test_persistence_across_instances(self, temp_dir):
        """Patterns should persist across learner instances."""
        learner1 = InteractionPatternLearner(memory_dir=str(temp_dir))
        learner1.on_tool_used("calendar")
        learner1.on_turn_complete(helpful=True)

        learner2 = InteractionPatternLearner(memory_dir=str(temp_dir))
        chain_key = "calendar"
        assert chain_key in learner2._patterns["chains"]

    def test_multiple_chains_same_tools(self, learner):
        """Multiple turns with same tools should increment count."""
        for _ in range(3):
            learner.on_tool_used("email")
            learner.on_turn_complete()

        chain_key = "email"
        assert learner._patterns["chains"][chain_key]["count"] == 3
