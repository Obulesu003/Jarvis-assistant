"""
Tests for AmbientDashboard - JARVIS ambient awareness display.
"""
import sys
import time
import unittest.mock as mock
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

import pytest

from core.ambient_dashboard import (
    AmbientDashboard,
    _get_color_for_percentage,
    COLOR_GREEN,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_DIM,
    THRESHOLD_LOW,
    THRESHOLD_MED,
)


class TestColorCoding:
    """Test color coding thresholds for usage metrics."""

    def test_green_below_50_percent(self):
        """Values below 50% should return green."""
        color = _get_color_for_percentage(0)
        assert color == COLOR_GREEN

        color = _get_color_for_percentage(25)
        assert color == COLOR_GREEN

        color = _get_color_for_percentage(49)
        assert color == COLOR_GREEN

    def test_yellow_between_50_and_80_percent(self):
        """Values between 50-80% should return yellow."""
        color = _get_color_for_percentage(50)
        assert color == COLOR_YELLOW

        color = _get_color_for_percentage(65)
        assert color == COLOR_YELLOW

        color = _get_color_for_percentage(79)
        assert color == COLOR_YELLOW

    def test_red_above_80_percent(self):
        """Values above 80% should return red."""
        color = _get_color_for_percentage(80)
        assert color == COLOR_RED

        color = _get_color_for_percentage(90)
        assert color == COLOR_RED

        color = _get_color_for_percentage(100)
        assert color == COLOR_RED

    def test_none_value_returns_dim(self):
        """None values should return dim color."""
        color = _get_color_for_percentage(None)
        assert color == COLOR_DIM

    def test_thresholds_are_correct(self):
        """Verify threshold constants."""
        assert THRESHOLD_LOW == 50
        assert THRESHOLD_MED == 80


class TestAmbientDashboard:
    """Test cases for AmbientDashboard class."""

    @pytest.fixture
    def mock_hud(self):
        """Create a mock HUD object."""
        hud = mock.MagicMock()
        hud._dpg = mock.MagicMock()
        hud._screen_w = 1920
        hud._screen_h = 1080
        return hud

    @pytest.fixture
    def mock_snapshot(self):
        """Create a mock SystemSnapshot."""
        snapshot = mock.MagicMock()
        snapshot.get_all.return_value = {
            "battery": 80,
            "charging": False,
            "cpu": 35,
            "memory": 45,
            "disk_free_gb": 150.5,
            "unread": 0,
        }
        return snapshot

    @pytest.fixture
    def dashboard(self, mock_hud, mock_snapshot):
        """Create an AmbientDashboard instance."""
        return AmbientDashboard(mock_hud, mock_snapshot)

    def test_initialization(self, dashboard, mock_hud, mock_snapshot):
        """Dashboard should initialize with correct properties."""
        assert dashboard._hud is mock_hud
        assert dashboard._snapshot is mock_snapshot
        assert dashboard._running is False
        assert dashboard._thread is None
        assert dashboard._dpg is None

    def test_refresh_interval_is_30_seconds(self, dashboard):
        """Refresh interval should be 30 seconds."""
        assert dashboard.refresh_interval == 30.0
        assert AmbientDashboard.REFRESH_INTERVAL == 30.0

    def test_fetch_stats_returns_snapshot_data(self, dashboard, mock_snapshot):
        """_fetch_stats should call snapshot.get_all()."""
        stats = dashboard._fetch_stats()
        mock_snapshot.get_all.assert_called_once()
        assert stats["cpu"] == 35
        assert stats["memory"] == 45
        assert stats["battery"] == 80

    def test_fetch_stats_handles_errors(self, mock_hud, mock_snapshot):
        """_fetch_stats should handle exceptions gracefully."""
        mock_snapshot.get_all.side_effect = Exception("Test error")
        dashboard = AmbientDashboard(mock_hud, mock_snapshot)
        stats = dashboard._fetch_stats()
        assert stats == {}

    def test_get_stats_returns_empty_initially(self, dashboard):
        """get_stats should return empty dict before first fetch."""
        assert dashboard.get_stats() == {}

    def test_get_stats_returns_last_fetched(self, dashboard, mock_snapshot):
        """get_stats should return the last fetched stats."""
        # Manually set stats as _fetch_stats would
        dashboard._stats = {
            "battery": 80,
            "charging": False,
            "cpu": 35,
            "memory": 45,
            "disk_free_gb": 150.5,
            "unread": 0,
        }
        stats = dashboard.get_stats()
        assert "cpu" in stats
        assert stats["cpu"] == 35

    def test_color_coding_for_cpu(self, dashboard, mock_snapshot):
        """CPU color should follow thresholds."""
        # Green: < 50%
        mock_snapshot.get_all.return_value = {"cpu": 35, "memory": 45, "battery": 80}
        dashboard._fetch_stats()
        assert _get_color_for_percentage(35) == COLOR_GREEN

        # Yellow: 50-80%
        mock_snapshot.get_all.return_value = {"cpu": 65, "memory": 45, "battery": 80}
        dashboard._fetch_stats()
        assert _get_color_for_percentage(65) == COLOR_YELLOW

        # Red: > 80%
        mock_snapshot.get_all.return_value = {"cpu": 90, "memory": 45, "battery": 80}
        dashboard._fetch_stats()
        assert _get_color_for_percentage(90) == COLOR_RED

    def test_email_count_shows_when_nonzero(self, dashboard, mock_snapshot):
        """Email count should be accessible when > 0."""
        mock_snapshot.get_all.return_value = {
            "cpu": 35,
            "memory": 45,
            "battery": 80,
            "unread": 5,
        }
        stats = dashboard._fetch_stats()
        assert stats["unread"] == 5

    def test_email_count_shows_when_zero(self, dashboard, mock_snapshot):
        """Email count should be accessible when 0."""
        mock_snapshot.get_all.return_value = {
            "cpu": 35,
            "memory": 45,
            "battery": 80,
            "unread": 0,
        }
        stats = dashboard._fetch_stats()
        assert stats["unread"] == 0

    def test_battery_charging_indicator(self, dashboard, mock_snapshot):
        """Battery should indicate charging state."""
        # Not charging
        mock_snapshot.get_all.return_value = {
            "battery": 80,
            "charging": False,
        }
        stats = dashboard._fetch_stats()
        assert stats["charging"] is False

        # Charging
        mock_snapshot.get_all.return_value = {
            "battery": 80,
            "charging": True,
        }
        stats = dashboard._fetch_stats()
        assert stats["charging"] is True

    def test_disk_free_space_reported(self, dashboard, mock_snapshot):
        """Disk free space should be reported in GB."""
        mock_snapshot.get_all.return_value = {
            "disk_free_gb": 150.5,
        }
        stats = dashboard._fetch_stats()
        assert stats["disk_free_gb"] == 150.5

    def test_battery_none_handled(self, dashboard, mock_snapshot):
        """Battery None should be handled gracefully."""
        mock_snapshot.get_all.return_value = {
            "battery": None,
            "charging": None,
        }
        stats = dashboard._fetch_stats()
        assert stats["battery"] is None
        assert _get_color_for_percentage(None) == COLOR_DIM

    def test_cpu_none_handled(self, dashboard, mock_snapshot):
        """CPU None should be handled gracefully."""
        mock_snapshot.get_all.return_value = {
            "cpu": None,
        }
        stats = dashboard._fetch_stats()
        assert stats["cpu"] is None
        assert _get_color_for_percentage(None) == COLOR_DIM

    def test_memory_none_handled(self, dashboard, mock_snapshot):
        """Memory None should be handled gracefully."""
        mock_snapshot.get_all.return_value = {
            "memory": None,
        }
        stats = dashboard._fetch_stats()
        assert stats["memory"] is None
        assert _get_color_for_percentage(None) == COLOR_DIM


class TestAmbientDashboardWithMockedDpg:
    """Test cases for AmbientDashboard with mocked DearPyGui."""

    @pytest.fixture
    def mock_dpg_module(self):
        """Create a mock DearPyGui module."""
        mock_dpg = mock.MagicMock()
        mock_dpg.does_item_exist.return_value = False
        mock_dpg.is_item_visible.return_value = True
        return mock_dpg

    @pytest.fixture
    def mock_hud(self):
        """Create a mock HUD object with DPG."""
        hud = mock.MagicMock()
        hud._dpg = mock.MagicMock()
        hud._screen_w = 1920
        hud._screen_h = 1080
        return hud

    @pytest.fixture
    def mock_snapshot(self):
        """Create a mock SystemSnapshot with test data."""
        snapshot = mock.MagicMock()
        snapshot.get_all.return_value = {
            "battery": 75,
            "charging": False,
            "cpu": 42,
            "memory": 58,
            "disk_free_gb": 200.0,
            "unread": 3,
        }
        return snapshot

    def test_show_creates_ui_when_not_exists(self, mock_dpg_module, mock_hud, mock_snapshot):
        """show() should create UI when AMBIENT_DASHBOARD doesn't exist."""
        dashboard = AmbientDashboard(mock_hud, mock_snapshot)
        dashboard._dpg = mock_dpg_module

        dashboard.show()

        # Verify window was created
        mock_dpg_module.window.assert_called()

    def test_show_updates_display_on_existing(self, mock_dpg_module, mock_hud, mock_snapshot):
        """show() should update display when AMBIENT_DASHBOARD exists."""
        mock_dpg_module.does_item_exist.return_value = True

        dashboard = AmbientDashboard(mock_hud, mock_snapshot)
        dashboard._dpg = mock_dpg_module
        dashboard.show()

        # Should configure to show
        mock_dpg_module.configure_item.assert_called()

    def test_hide_stops_refresh_thread(self, mock_dpg_module, mock_hud, mock_snapshot):
        """hide() should set _running to False."""
        dashboard = AmbientDashboard(mock_hud, mock_snapshot)
        dashboard._dpg = mock_dpg_module
        dashboard._running = True

        dashboard.hide()

        assert dashboard._running is False

    def test_toggle_calls_show_when_hidden(self, mock_dpg_module, mock_hud, mock_snapshot):
        """toggle() should call show() when dashboard is hidden."""
        mock_dpg_module.does_item_exist.return_value = True
        mock_dpg_module.is_item_visible.return_value = False

        dashboard = AmbientDashboard(mock_hud, mock_snapshot)
        dashboard._dpg = mock_dpg_module

        with mock.patch.object(dashboard, 'show') as mock_show:
            dashboard.toggle()
            mock_show.assert_called_once()

    def test_toggle_calls_hide_when_visible(self, mock_dpg_module, mock_hud, mock_snapshot):
        """toggle() should call hide() when dashboard is visible."""
        mock_dpg_module.does_item_exist.return_value = True
        mock_dpg_module.is_item_visible.return_value = True

        dashboard = AmbientDashboard(mock_hud, mock_snapshot)
        dashboard._dpg = mock_dpg_module

        with mock.patch.object(dashboard, 'hide') as mock_hide:
            dashboard.toggle()
            mock_hide.assert_called_once()

    def test_refresh_triggers_update(self, mock_dpg_module, mock_hud, mock_snapshot):
        """refresh() should trigger _update_display()."""
        dashboard = AmbientDashboard(mock_hud, mock_snapshot)
        dashboard._dpg = mock_dpg_module

        with mock.patch.object(dashboard, '_update_display') as mock_update:
            dashboard.refresh()
            mock_update.assert_called_once()


class TestAmbientDashboardIntegration:
    """Integration-style tests with minimal mocking."""

    def test_color_coding_edge_cases(self):
        """Test edge cases for color coding."""
        # Exactly at threshold
        assert _get_color_for_percentage(50.0) == COLOR_YELLOW
        assert _get_color_for_percentage(80.0) == COLOR_RED

        # Near threshold boundaries
        assert _get_color_for_percentage(49.9) == COLOR_GREEN
        assert _get_color_for_percentage(50.1) == COLOR_YELLOW
        assert _get_color_for_percentage(79.9) == COLOR_YELLOW
        assert _get_color_for_percentage(80.1) == COLOR_RED

        # Zero and max
        assert _get_color_for_percentage(0) == COLOR_GREEN
        assert _get_color_for_percentage(100) == COLOR_RED

    def test_colors_are_distinct(self):
        """Verify all color constants are distinct."""
        assert COLOR_GREEN != COLOR_YELLOW
        assert COLOR_GREEN != COLOR_RED
        assert COLOR_YELLOW != COLOR_RED
        assert COLOR_GREEN != COLOR_DIM
        assert COLOR_YELLOW != COLOR_DIM
        assert COLOR_RED != COLOR_DIM

    def test_colors_are_valid_rgb(self):
        """Verify colors are valid RGB tuples."""
        for color in [COLOR_GREEN, COLOR_YELLOW, COLOR_RED, COLOR_DIM]:
            assert len(color) == 3
            for component in color:
                assert 0 <= component <= 255
                assert isinstance(component, int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
