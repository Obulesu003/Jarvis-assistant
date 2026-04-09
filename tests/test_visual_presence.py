import sys
import unittest.mock as mock
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

from core.visual_presence import JARVISVisualState, VisualPresenceEngine

class TestJARVISVisualState:
    def test_all_states_defined(self):
        assert JARVISVisualState.IDLE.value == "idle"
        assert JARVISVisualState.LISTENING.value == "listening"
        assert JARVISVisualState.THINKING.value == "thinking"
        assert JARVISVisualState.SPEAKING.value == "speaking"
        assert JARVISVisualState.VOLUNTEERING.value == "volunteering"
        assert JARVISVisualState.INTERRUPTED.value == "interrupted"

class TestVisualPresenceEngine:
    def test_set_state_updates_internal(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.set_state(JARVISVisualState.LISTENING)
        assert vpe._state == JARVISVisualState.LISTENING
        mock_hud.set_status_color.assert_called_once()
        mock_hud.set_state_label.assert_called_once_with("LISTENING")

    def test_volunteering_mode_switches_hud(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.set_state(JARVISVisualState.VOLUNTEERING)
        mock_hud.set_volunteer_mode.assert_called_once_with(True)

    def test_update_waveform_accumulates(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe._state = JARVISVisualState.LISTENING
        vpe.update_waveform(0.5)
        assert len(vpe._waveform_data) == 1
        mock_hud.update_waveform.assert_called_once()

    def test_on_tool_start_shows_activity(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.on_tool_start("email")
        mock_hud.show_activity.assert_called_once_with("email")

    def test_on_interrupted_updates_state_and_hud(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.on_interrupted("Checking your email now")
        assert vpe._state == JARVISVisualState.INTERRUPTED
        mock_hud.show_response.assert_called_once()

    def test_state_colors_are_correct(self):
        assert VisualPresenceEngine.STATE_COLORS[JARVISVisualState.IDLE] == (60, 60, 60)
        assert VisualPresenceEngine.STATE_COLORS[JARVISVisualState.LISTENING] == (0, 180, 255)
        assert VisualPresenceEngine.STATE_COLORS[JARVISVisualState.SPEAKING] == (0, 255, 180)

    def test_update_idle_pulse_breathes(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe._state = JARVISVisualState.IDLE
        vpe._idle_pulse = 0.0  # Start at beginning of cycle
        # After one call, pulse advances
        vpe.update_idle_pulse()
        assert vpe._idle_pulse > 0.0
        # HUD should be called with breathing alpha
        mock_hud.set_jarcircle_opacity.assert_called()
