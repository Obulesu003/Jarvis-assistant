import pytest
import unittest.mock as mock
import sys
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

from core.memory_bridge import MemoryBridge


class TestMemoryBridge:
    def test_build_context_empty_memory(self):
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = []
        mock_mem.procedural.get_active.return_value = []
        mock_mem.get_recent_topic.return_value = None
        mock_mem.get_preferences_for.return_value = []
        bridge = MemoryBridge(mock_mem)
        ctx = bridge.build_context("check weather")
        assert ctx == ""

    def test_build_context_with_facts(self):
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = ["You prefer Celsius", "You live in London"]
        mock_mem.procedural.get_active.return_value = []
        mock_mem.get_recent_topic.return_value = None
        mock_mem.get_preferences_for.return_value = []
        bridge = MemoryBridge(mock_mem)
        ctx = bridge.build_context("check weather")
        assert "WHAT I KNOW ABOUT YOU" in ctx

    def test_build_context_with_active_projects(self):
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = []
        mock_mem.procedural.get_active.return_value = ["JARVIS HUD", "Memory system"]
        mock_mem.get_recent_topic.return_value = None
        mock_mem.get_preferences_for.return_value = []
        bridge = MemoryBridge(mock_mem)
        ctx = bridge.build_context("open files")
        assert "ACTIVE PROJECTS" in ctx
        assert "JARVIS HUD" in ctx

    def test_on_session_end_no_memories(self):
        mock_mem = mock.MagicMock()
        mock_mem.get_session_memories.return_value = []
        bridge = MemoryBridge(mock_mem)
        bridge.on_session_end()  # Should not raise
        mock_mem.get_session_memories.assert_called_once()

    def test_on_session_end_with_memories_calls_synthesize(self):
        mock_mem = mock.MagicMock()
        mock_mem.get_session_memories.return_value = [
            {"content": "User mentioned Python project"},
            {"content": "User prefers British voice"},
        ]
        bridge = MemoryBridge(mock_mem)
        bridge._synthesize_session_review = mock.MagicMock(return_value="Key insight.")
        bridge.on_session_end()
        bridge._synthesize_session_review.assert_called_once()
        mock_mem.remember.assert_called_once()

    def test_on_fact_learned(self):
        mock_mem = mock.MagicMock()
        bridge = MemoryBridge(mock_mem)
        bridge.on_fact_learned({"content": "User likes tea"})
        assert len(bridge._session_facts_learned) == 1
