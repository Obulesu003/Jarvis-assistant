"""
Tests for continuous conversation mode in audio_pipeline.py.
"""
import pytest
import time
from unittest.mock import MagicMock, patch


class TestContinuousConversationMode:
    """Test cases for continuous conversation (engaged) mode."""

    @pytest.fixture
    def pipeline(self):
        """Create a JARVISAudioPipeline with mocked components."""
        from core.audio_pipeline import JARVISAudioPipeline
        p = JARVISAudioPipeline()
        p._wake_word = MagicMock()
        p._vad = MagicMock()
        p._stt = MagicMock()
        p._tts = MagicMock()
        p._is_listening = False  # Don't start the audio thread
        return p

    def test_initial_state_not_engaged(self, pipeline):
        """Pipeline should not be engaged initially."""
        assert pipeline._is_engaged is False

    def test_set_engaged_activates_mode(self, pipeline):
        """set_engaged should activate continuous conversation mode."""
        pipeline.set_engaged()
        assert pipeline._is_engaged is True
        assert pipeline._engaged_since > 0

    def test_set_engaged_sets_timer(self, pipeline):
        """set_engaged should set the engaged_since timestamp."""
        before = time.time()
        pipeline.set_engaged()
        after = time.time()
        assert before <= pipeline._engaged_since <= after

    def test_extend_engagement_updates_timer(self, pipeline):
        """extend_engagement should update engaged_since to now."""
        pipeline.set_engaged()
        old_timestamp = pipeline._engaged_since
        time.sleep(0.01)
        pipeline.extend_engagement()
        assert pipeline._engaged_since >= old_timestamp

    def test_on_user_speech_extends_engagement(self, pipeline):
        """on_user_speech_detected should extend engagement."""
        pipeline.set_engaged()
        old = pipeline._engaged_since
        time.sleep(0.01)
        pipeline.on_user_speech_detected()
        assert pipeline._engaged_since >= old

    def test_on_speaking_finished_stays_engaged(self, pipeline):
        """on_speaking_finished should reset engagement timer."""
        pipeline.set_engaged()
        time.sleep(0.01)
        old = pipeline._engaged_since
        pipeline.on_speaking_finished()
        assert pipeline._engaged_since >= old
        assert pipeline._is_engaged is True

    def test_get_engagement_status_not_engaged(self, pipeline):
        """get_engagement_status should show not engaged when inactive."""
        status = pipeline.get_engagement_status()
        assert status["is_engaged"] is False
        assert status["seconds_remaining"] == 0.0

    def test_get_engagement_status_engaged(self, pipeline):
        """get_engagement_status should show seconds remaining when engaged."""
        pipeline.set_engaged()
        status = pipeline.get_engagement_status()
        assert status["is_engaged"] is True
        assert 0 < status["seconds_remaining"] <= 60.0
        assert status["state"] == "idle"

    def test_engagement_timeout_reaches_zero(self, pipeline):
        """Engagement should time out after _engaged_timeout seconds."""
        pipeline._engaged_timeout = 0.1  # 100ms for fast test
        pipeline.set_engaged()
        assert pipeline._is_engaged is True
        time.sleep(0.2)
        pipeline._check_engagement_timeout()
        assert pipeline._is_engaged is False

    def test_engagement_not_timed_out_before_threshold(self, pipeline):
        """Engagement should not timeout before _engaged_timeout."""
        pipeline._engaged_timeout = 10.0
        pipeline.set_engaged()
        pipeline._check_engagement_timeout()
        assert pipeline._is_engaged is True

    def test_multiple_speech_detections_extend_timer(self, pipeline):
        """Multiple speech detections should each extend the timer."""
        pipeline.set_engaged()
        timestamps = [pipeline._engaged_since]
        for _ in range(5):
            time.sleep(0.01)
            pipeline.on_user_speech_detected()
            timestamps.append(pipeline._engaged_since)
        # Each call should extend or maintain the timestamp
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1]

    def test_on_speaking_finished_sets_state_to_engaged(self, pipeline):
        """on_speaking_finished should keep state engaged."""
        pipeline.set_engaged()
        pipeline._is_engaged = False  # Simulate timeout
        pipeline.on_speaking_finished()
        assert pipeline._is_engaged is True
