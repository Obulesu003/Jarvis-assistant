"""
Tests for SessionMetadataManager.
"""
import json
import tempfile
from pathlib import Path
import pytest

from memory.session_metadata import SessionMetadataManager, SessionMetadata


class TestSessionMetadataManager:
    """Test cases for SessionMetadataManager."""

    @pytest.fixture
    def temp_sessions_dir(self):
        """Create a temporary directory for sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_sessions_dir):
        """Create a manager with temporary directory."""
        return SessionMetadataManager(sessions_dir=str(temp_sessions_dir))

    def test_start_session_creates_metadata(self, manager):
        """Starting a session should create SessionMetadata."""
        session = manager.start_session()
        assert session is not None
        assert session.session_id is not None
        assert len(session.session_id) == 8
        assert session.started_at is not None

    def test_update_topic(self, manager):
        """update_topic should save the topic."""
        manager.start_session()
        manager.update_topic("Python project")

        path = manager._path
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["last_topic"] == "Python project"
        assert data["total_turns"] == 1

    def test_update_language(self, manager):
        """update_language should save the language."""
        manager.start_session()
        manager.update_language("tr")

        path = manager._path
        data = json.loads(path.read_text())
        assert data["last_language"] == "tr"

    def test_record_interruption(self, manager):
        """record_interruption should increment counter."""
        manager.start_session()
        manager.record_interruption()
        manager.record_interruption()

        path = manager._path
        data = json.loads(path.read_text())
        assert data["interrupted_count"] == 2

    def test_get_resumption_greeting_returns_none_first_time(self, temp_sessions_dir):
        """First run should return None for resumption greeting."""
        manager = SessionMetadataManager(sessions_dir=str(temp_sessions_dir))
        greeting = manager.get_resumption_greeting()
        assert greeting is None

    def test_get_resumption_greeting_with_topic(self, manager):
        """Should return greeting mentioning last topic."""
        manager.start_session()
        manager.update_topic("Machine learning")
        manager.end_session()
        greeting = manager.get_resumption_greeting()
        assert greeting is not None
        assert "Machine learning" in greeting

    def test_get_resumption_greeting_with_turn_count(self, manager):
        """Should return greeting with turn count."""
        manager.start_session()
        for _ in range(3):
            manager.update_topic("test")
        manager.end_session()
        greeting = manager.get_resumption_greeting()
        assert "3 exchanges" in greeting

    def test_end_session_clears_current(self, manager):
        """end_session should clear current session."""
        manager.start_session()
        assert manager._current is not None
        manager.end_session()
        assert manager._current is None

    def test_record_tool_chain(self, manager):
        """record_tool_chain should save unique chains."""
        manager.start_session()
        manager.record_tool_chain(["email", "calendar"])
        manager.record_tool_chain(["email", "calendar"])
        manager.record_tool_chain(["search"])

        path = manager._path
        data = json.loads(path.read_text())
        assert len(data["tool_chains_used"]) == 2
        assert "email -> calendar" in data["tool_chains_used"]
