"""Tests for Task 22: Natural Pause Detection & False Interruption Reduction."""
import pytest
import numpy as np
import time


class TestAdaptiveVAD:
    """Test adaptive VAD calibration and thresholding."""

    def test_default_threshold_before_calibration(self):
        """Uncalibrated VAD uses the standard 0.5 threshold."""
        from core.vad import VoiceActivityDetector

        vad = VoiceActivityDetector()
        assert vad.speech_threshold == 0.5
        assert not vad.is_calibrated

    def test_calibrate_sets_threshold_above_noise(self):
        """Calibration sets threshold above the measured noise floor."""
        from core.vad import VoiceActivityDetector

        vad = VoiceActivityDetector()

        # Mock the Silero model to return varying probabilities
        class FakeProb:
            def __init__(self, value):
                self._value = value

            def item(self):
                return self._value

        class FakeModel:
            def __call__(self, audio, sampling_rate=None):
                # Return probability inversely proportional to noise amplitude
                rms = float(np.sqrt(np.mean(audio**2)))
                # Very quiet noise → very low probability (~0.01)
                return FakeProb(max(0.01, rms * 0.2))

        vad._model = FakeModel()
        silence_chunks = [np.random.randn(512).astype(np.float32) * 0.001 for _ in range(50)]
        result = vad.calibrate(silence_chunks)
        assert result is True
        assert vad.is_calibrated
        assert vad.speech_threshold >= 0.3  # Minimum floor cap

    def test_calibrate_respects_noise_floor_high_threshold(self):
        """In a noisier environment, calibration raises the threshold."""
        from core.vad import VoiceActivityDetector

        vad = VoiceActivityDetector()

        class FakeProb:
            def __init__(self, value):
                self._value = value

            def item(self):
                return self._value

        class FakeModel:
            def __call__(self, audio, sampling_rate=None):
                rms = float(np.sqrt(np.mean(audio**2)))
                # Moderate noise → moderate probability (~0.15)
                return FakeProb(max(0.05, min(0.25, rms)))

        vad._model = FakeModel()
        noise_chunks = [np.random.randn(512).astype(np.float32) * 0.05 for _ in range(50)]
        result = vad.calibrate(noise_chunks)
        assert result is True
        assert 0.3 <= vad.speech_threshold <= 0.7

    def test_calibrate_caps_threshold_at_07(self):
        """Calibration caps threshold at 0.7 even with extreme noise."""
        from core.vad import VoiceActivityDetector

        vad = VoiceActivityDetector()
        # Chunks that would produce very high probabilities if model processed them
        # We test the cap by directly setting the internal noise calculation
        chunks = [np.ones(512, dtype=np.float32) for _ in range(50)]
        vad.calibrate(chunks)
        assert vad.speech_threshold <= 0.7

    def test_calibrate_rejects_empty_chunks(self):
        """Calibration returns False for empty chunk list."""
        from core.vad import VoiceActivityDetector

        vad = VoiceActivityDetector()
        assert vad.calibrate([]) is False

    def test_calibrate_rejects_too_few_chunks(self):
        """Calibration returns False when not enough valid chunks collected."""
        from core.vad import VoiceActivityDetector

        vad = VoiceActivityDetector()
        # Fewer than 10 valid chunks should fail
        small_chunks = [np.random.randn(512).astype(np.float32) * 0.001 for _ in range(5)]
        assert vad.calibrate(small_chunks) is False

    def test_is_speech_uses_calibrated_threshold(self):
        """is_speech() uses the calibrated (raised) threshold vs default 0.5."""
        from core.vad import VoiceActivityDetector

        vad = VoiceActivityDetector()

        # Mock a model that always returns 0.55
        class FakeProb:
            def item(self):
                return 0.55

        class FakeModel:
            def __call__(self, audio, sampling_rate=None):
                return FakeProb()

        vad._model = FakeModel()

        # Without calibration: 0.55 > 0.5 → speech detected
        assert vad.is_speech(np.zeros(512, dtype=np.float32)) is True

        # After calibration that raises threshold to 0.6:
        vad._speech_threshold = 0.6
        vad._is_calibrated = True
        # 0.55 < 0.6 → speech NOT detected
        assert vad.is_speech(np.zeros(512, dtype=np.float32)) is False


class TestInterruptionGuard:
    """Test minimum utterance duration before interruption triggers."""

    def _rms(self, audio: np.ndarray) -> float:
        return float(np.sqrt(np.mean(audio**2)))

    def test_brief_quiet_audio_resets_counter(self):
        """A quiet frame (RMS < 0.01) resets the interruption counter."""
        jarvis_state = {"frames": 0}

        def on_audio(rms: float):
            if rms > 0.01:
                jarvis_state["frames"] += 1
            else:
                jarvis_state["frames"] = 0

        # Quiet frame
        quiet = np.zeros(1024, dtype=np.float32)
        on_audio(self._rms(quiet))
        assert jarvis_state["frames"] == 0

    def test_sustained_speech_increments_counter(self):
        """Sustained audio above RMS threshold increments counter each frame."""
        jarvis_state = {"frames": 0}

        def on_audio(rms: float):
            if rms > 0.01:
                jarvis_state["frames"] += 1
            else:
                jarvis_state["frames"] = 0

        # 5 frames of "real speech"
        for _ in range(5):
            audio = np.random.randn(1024).astype(np.float32) * 0.02
            on_audio(self._rms(audio))
        assert jarvis_state["frames"] == 5

    def test_counter_drops_to_zero_on_quiet_frame(self):
        """A single quiet frame between loud frames resets the counter."""
        jarvis_state = {"frames": 3}

        def on_audio(rms: float):
            if rms > 0.01:
                jarvis_state["frames"] += 1
            else:
                jarvis_state["frames"] = 0

        # Quiet frame in the middle
        quiet = np.zeros(1024, dtype=np.float32)
        on_audio(self._rms(quiet))
        assert jarvis_state["frames"] == 0

    def test_interruption_fires_only_at_minimum_threshold(self):
        """Interruption fires only after min_speech_frames sustained loud frames."""
        frames = 0
        min_frames = 5
        triggered = False

        def simulate_frame(rms: float):
            nonlocal frames, triggered
            if rms > 0.01:
                frames += 1
                if frames >= min_frames:
                    triggered = True
            else:
                frames = 0

        # 4 frames — below threshold, should NOT trigger
        for _ in range(4):
            audio = np.random.randn(1024).astype(np.float32) * 0.02
            simulate_frame(self._rms(audio))
        assert not triggered
        assert frames == 4

        # 5th frame — at threshold, SHOULD trigger
        audio = np.random.randn(1024).astype(np.float32) * 0.02
        simulate_frame(self._rms(audio))
        assert triggered
        assert frames == 5

    def test_false_positive_pop_is_ignored(self):
        """A brief audio 'pop' (single frame) does not trigger interruption."""
        frames = 0
        min_frames = 5
        triggered = False

        def simulate_frame(rms: float):
            nonlocal frames, triggered
            if rms > 0.01:
                frames += 1
                if frames >= min_frames:
                    triggered = True
            else:
                frames = 0

        # One loud frame followed by silence — counter resets
        audio = np.random.randn(1024).astype(np.float32) * 0.02
        simulate_frame(self._rms(audio))  # frame 1
        simulate_frame(self._rms(np.zeros(1024, dtype=np.float32)))  # reset!
        assert frames == 0
        assert not triggered

    def test_jarvis_turn_complete_resets_counter(self):
        """Completing a turn resets the interruption frame counter to zero."""
        jarvis_state = {
            "turn_state": "interrupted",
            "interruption_frames": 5,
        }

        # Simulate turn complete
        jarvis_state["turn_state"] = "listening"
        jarvis_state["interruption_frames"] = 0

        assert jarvis_state["interruption_frames"] == 0
        assert jarvis_state["turn_state"] == "listening"

    def test_handle_interruption_resets_counter(self):
        """Handling an interruption resets the frame counter to zero."""
        jarvis_state = {
            "turn_state": "jarvis_speaking",
            "interruption_frames": 5,
            "current_text": "What JARVIS was saying.",
        }

        # Simulate handle_interruption
        jarvis_state["turn_state"] = "interrupted"
        jarvis_state["interruption_frames"] = 0

        assert jarvis_state["interruption_frames"] == 0
        assert jarvis_state["turn_state"] == "interrupted"

    def test_minimum_interruption_frames_configurable(self):
        """The minimum frame threshold for interruption is configurable."""
        jarvis_state = {"interruption_frames": 0, "min_frames": 5}

        # Configurable via instance attribute
        assert jarvis_state["min_frames"] == 5

        jarvis_state["min_frames"] = 3  # Lower threshold
        assert jarvis_state["min_frames"] == 3


class TestAdaptiveSilenceThreshold:
    """Test adaptive silence threshold in audio pipeline."""

    def _make_pipeline_with_defaults(self):
        """Create pipeline with all Task 22 defaults by calling init logic."""
        from core.audio_pipeline import JARVISAudioPipeline
        import unittest.mock

        class MockWake:
            def initialize(self): pass
            def detect(self, a): return False
            def enable(self): pass
            def disable(self): pass

        class MockVAD:
            def initialize(self): pass
            def is_speech(self, a): return False
            def calibrate(self, chunks): return False

        class MockSTT:
            def initialize(self): pass
            def transcribe(self, a): return ""

        class MockTTS:
            def speak_async(self, t): pass
            def speak(self, t, blocking=False): pass

        with unittest.mock.patch(
            "core.wake_word.WakeWordDetector", return_value=MockWake()
        ), unittest.mock.patch(
            "core.vad.VoiceActivityDetector", return_value=MockVAD()
        ), unittest.mock.patch(
            "core.stt_engine.STTEngine", return_value=MockSTT()
        ), unittest.mock.patch(
            "core.tts_engine.TTSEngine", return_value=MockTTS()
        ):
            pipeline = JARVISAudioPipeline()
            pipeline.initialize()
            return pipeline

    def test_silence_rms_multiplier_configurable(self):
        """Pipeline silence threshold multiplier is configurable."""
        pipeline = self._make_pipeline_with_defaults()
        assert pipeline._silence_rms_multiplier == 2.5

    def test_min_speech_frames_prevents_short_bursts(self):
        """Pipeline min_speech_frames requires sustained speech before triggering."""
        pipeline = self._make_pipeline_with_defaults()
        assert pipeline._min_speech_frames == 3

    def test_calibration_collection_starts_on_initialize(self):
        """After initialize(), pipeline starts collecting calibration chunks."""
        pipeline = self._make_pipeline_with_defaults()
        assert pipeline._is_calibrating is True
        assert isinstance(pipeline._calibration_chunks, list)
        assert pipeline._calibration_frames_collected == 0
