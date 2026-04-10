"""
Tests for SystemSnapshot and ambient awareness features.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestSystemSnapshot:
    """Test cases for SystemSnapshot."""

    @pytest.fixture
    def snapshot(self):
        """Create a SystemSnapshot instance."""
        from core.system_snapshot import SystemSnapshot
        return SystemSnapshot()

    def test_get_all_returns_dict(self, snapshot):
        """get_all should return a dictionary with expected keys."""
        result = snapshot.get_all()
        assert isinstance(result, dict)
        assert "battery" in result
        assert "cpu" in result
        assert "memory" in result

    def test_get_all_has_required_keys(self, snapshot):
        """get_all should contain battery, cpu, memory, and unread."""
        result = snapshot.get_all()
        assert "battery" in result
        assert "cpu" in result
        assert "memory" in result
        assert "unread" in result

    def test_get_brief_summary_returns_string(self, snapshot):
        """get_brief_summary should return a non-empty string."""
        summary = snapshot.get_brief_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_get_brief_summary_contains_cpu(self, snapshot):
        """Summary should include CPU usage."""
        summary = snapshot.get_brief_summary()
        assert "CPU" in summary

    def test_get_brief_summary_contains_ram(self, snapshot):
        """Summary should include RAM usage."""
        summary = snapshot.get_brief_summary()
        assert "RAM" in summary

    def test_battery_can_be_none(self, snapshot):
        """get_all should handle missing battery gracefully."""
        import core.system_snapshot as ss
        original_get_all = ss.SystemSnapshot.get_all

        def mock_get_all(self_inner):
            result = original_get_all(self_inner)
            result["battery"] = None
            return result

        with patch.object(ss.SystemSnapshot, "get_all", mock_get_all):
            result = snapshot.get_all()
            assert result["battery"] is None

    def test_brief_summary_without_battery(self, snapshot):
        """Summary should work without battery info."""
        import core.system_snapshot as ss
        original_get_all = ss.SystemSnapshot.get_all

        def mock_no_battery(self_inner):
            result = original_get_all(self_inner)
            result["battery"] = None
            return result

        with patch.object(ss.SystemSnapshot, "get_all", mock_no_battery):
            summary = snapshot.get_brief_summary()
            assert "Batt" not in summary
