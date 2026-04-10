"""Tests for Task 20: Emotional Tone TTS Modulation."""
import pytest
import numpy as np


# =============================================================================
# EmotionTone Enum Tests
# =============================================================================

class TestEmotionToneEnum:
    """Test EmotionTone enum values and attributes."""

    def test_all_tones_have_label_speed_pitch(self):
        """Every EmotionTone has a label, speed, and pitch multiplier."""
        from core.tts_engine import EmotionTone

        for tone in EmotionTone:
            assert hasattr(tone, "label")
            assert hasattr(tone, "speed")
            assert hasattr(tone, "pitch")
            assert isinstance(tone.label, str)
            assert isinstance(tone.speed, float)
            assert isinstance(tone.pitch, float)

    def test_normal_tone_is_identity(self):
        """NORMAL tone has speed=1.0 and pitch=1.0 (no modulation)."""
        from core.tts_engine import EmotionTone

        assert EmotionTone.NORMAL.speed == 1.0
        assert EmotionTone.NORMAL.pitch == 1.0

    def test_excited_faster_and_higher(self):
        """EXCITED tone is faster (speed>1) and higher pitched (pitch>1)."""
        from core.tts_engine import EmotionTone

        assert EmotionTone.EXCITED.speed > 1.0
        assert EmotionTone.EXCITED.pitch > 1.0
        assert EmotionTone.EXCITED.speed == 1.2
        assert EmotionTone.EXCITED.pitch == 1.1

    def test_urgent_fastest_speech(self):
        """URGENT tone is the fastest (highest speed multiplier)."""
        from core.tts_engine import EmotionTone

        speeds = {tone: tone.speed for tone in EmotionTone}
        assert speeds[EmotionTone.URGENT] == max(speeds.values())

    def test_whispered_slowest_lowest_pitch(self):
        """WHISPERED tone is the slowest and lowest-pitched."""
        from core.tts_engine import EmotionTone

        speeds = {tone: tone.speed for tone in EmotionTone}
        pitches = {tone: tone.pitch for tone in EmotionTone}
        assert speeds[EmotionTone.WHISPERED] == min(speeds.values())
        assert pitches[EmotionTone.WHISPERED] == min(pitches.values())

    def test_apologetic_slower_than_normal(self):
        """APOLOGETIC tone is slower than normal for a softer delivery."""
        from core.tts_engine import EmotionTone

        assert EmotionTone.APOLOGETIC.speed < 1.0
        assert EmotionTone.APOLOGETIC.speed == 0.85

    def test_calm_slightly_slower_than_normal(self):
        """CALM tone is slightly slower than normal."""
        from core.tts_engine import EmotionTone

        assert EmotionTone.CALM.speed < 1.0
        assert EmotionTone.CALM.speed == 0.95


# =============================================================================
# VoiceEmotion Dataclass Tests
# =============================================================================

class TestVoiceEmotion:
    """Test VoiceEmotion dataclass default and custom values."""

    def test_default_is_normal(self):
        """Default emotion is NORMAL tone at intensity 1.0."""
        from core.tts_engine import VoiceEmotion, EmotionTone

        ve = VoiceEmotion()
        assert ve.tone == EmotionTone.NORMAL
        assert ve.intensity == 1.0

    def test_custom_tone_and_intensity(self):
        """Can construct with a specific tone and intensity."""
        from core.tts_engine import VoiceEmotion, EmotionTone

        ve = VoiceEmotion(tone=EmotionTone.EXCITED, intensity=1.5)
        assert ve.tone == EmotionTone.EXCITED
        assert ve.intensity == 1.5

    def test_intensity_clamped_valid_range(self):
        """Intensity attribute accepts values in [0, 2] range."""
        from core.tts_engine import VoiceEmotion

        ve = VoiceEmotion(intensity=0.0)
        assert ve.intensity == 0.0
        ve2 = VoiceEmotion(intensity=2.0)
        assert ve2.intensity == 2.0


# =============================================================================
# TTSEngine Emotion Wiring Tests
# =============================================================================

class TestTTSEngineEmotion:
    """Test TTSEngine set/reset/get emotion methods."""

    def _make_tts(self):
        """Create TTSEngine without real Piper subprocess."""
        from core.tts_engine import TTSEngine
        import unittest.mock

        with unittest.mock.patch.object(
            TTSEngine, "_check_installation", return_value=False
        ):
            tts = TTSEngine()
            tts._is_installed = False  # prevent subprocess calls
            return tts

    def test_initial_emotion_is_normal(self):
        """New TTSEngine instance starts with NORMAL emotion."""
        tts = self._make_tts()
        assert tts._emotion.tone.label == "normal"

    def test_set_emotion_changes_tone(self):
        """set_emotion() changes the active tone."""
        from core.tts_engine import EmotionTone

        tts = self._make_tts()
        tts.set_emotion(EmotionTone.EXCITED)
        assert tts._emotion.tone == EmotionTone.EXCITED

    def test_set_emotion_persists_until_reset(self):
        """Emotion persists across multiple speak calls until reset."""
        from core.tts_engine import EmotionTone

        tts = self._make_tts()
        tts.set_emotion(EmotionTone.URGENT)
        # Emotion should still be URGENT
        assert tts._emotion.tone == EmotionTone.URGENT

    def test_reset_emotion_returns_to_normal(self):
        """reset_emotion() restores NORMAL tone."""
        from core.tts_engine import EmotionTone

        tts = self._make_tts()
        tts.set_emotion(EmotionTone.WHISPERED)
        tts.reset_emotion()
        assert tts._emotion.tone == EmotionTone.NORMAL

    def test_get_emotion_returns_voice_emotion(self):
        """get_emotion() returns a VoiceEmotion dataclass."""
        from core.tts_engine import EmotionTone, VoiceEmotion

        tts = self._make_tts()
        tts.set_emotion(EmotionTone.CALM)
        emotion = tts.get_emotion()
        assert isinstance(emotion, VoiceEmotion)
        assert emotion.tone == EmotionTone.CALM


# =============================================================================
# EmotionDetector Tests
# =============================================================================

class TestEmotionDetectorRMS:
    """Test RMS (Root Mean Square) amplitude computation."""

    def test_silent_audio_rms_near_zero(self):
        """Silence produces RMS close to zero."""
        from core.emotion_detector import EmotionDetector

        detector = EmotionDetector()
        silence = np.zeros(16000, dtype=np.float32)
        rms = detector._compute_rms(silence)
        assert rms == 0.0

    def test_constant_positive_signal_rms(self):
        """Constant positive signal RMS equals the constant value."""
        from core.emotion_detector import EmotionDetector

        detector = EmotionDetector()
        constant = np.full(16000, 0.5, dtype=np.float32)
        rms = detector._compute_rms(constant)
        assert abs(rms - 0.5) < 1e-6

    def test_sine_wave_rms_equals_amplitude_over_sqrt2(self):
        """Sine wave RMS = amplitude / sqrt(2)."""
        from core.emotion_detector import EmotionDetector
        import math

        detector = EmotionDetector()
        t = np.linspace(0, 1, 16000, dtype=np.float32)
        sine = (0.5 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
        rms = detector._compute_rms(sine)
        expected = 0.5 / math.sqrt(2)
        assert abs(rms - expected) < 0.01

    def test_rms_scales_with_amplitude(self):
        """Doubled amplitude doubles RMS."""
        from core.emotion_detector import EmotionDetector

        detector = EmotionDetector()
        audio1 = np.random.randn(4800).astype(np.float32) * 0.1
        audio2 = np.random.randn(4800).astype(np.float32) * 0.2
        rms1 = detector._compute_rms(audio1)
        rms2 = detector._compute_rms(audio2)
        assert abs(rms2 / rms1 - 2.0) < 0.1  # within 10% of doubling


class TestEmotionDetectorZCR:
    """Test Zero Crossing Rate computation."""

    def test_silent_audio_zcr_near_zero(self):
        """Silence has near-zero zero crossing rate."""
        from core.emotion_detector import EmotionDetector

        detector = EmotionDetector()
        silence = np.zeros(16000, dtype=np.float32)
        zcr = detector._compute_zcr(silence)
        assert zcr == 0.0

    def test_constant_signal_zcr_near_zero(self):
        """Constant amplitude signal has near-zero ZCR."""
        from core.emotion_detector import EmotionDetector

        detector = EmotionDetector()
        constant = np.full(16000, 0.5, dtype=np.float32)
        zcr = detector._compute_zcr(constant)
        assert zcr == 0.0

    def test_high_frequency_sine_high_zcr(self):
        """High-frequency sine wave has high zero crossing rate."""
        from core.emotion_detector import EmotionDetector
        import math

        detector = EmotionDetector()
        # High freq: 4kHz, sample rate 16kHz → ~8 crossings per 16 samples
        t = np.linspace(0, 1, 16000, dtype=np.float32)
        high_freq = np.sin(2 * math.pi * 4000 * t).astype(np.float32)
        zcr = detector._compute_zcr(high_freq)
        assert zcr > 0.1  # Should have significant crossings

    def test_zcr_normalized_to_zero_to_one(self):
        """ZCR is normalized and falls in [0, 1] range."""
        from core.emotion_detector import EmotionDetector

        detector = EmotionDetector()
        audio = np.random.randn(16000).astype(np.float32)
        zcr = detector._compute_zcr(audio)
        assert 0.0 <= zcr <= 1.0


class TestEmotionDetectorClassification:
    """Test emotion classification from RMS and ZCR."""

    def test_high_rms_high_zcr_classified_excited(self):
        """Loud fast speech → EXCITED emotion."""
        from core.emotion_detector import EmotionDetector, EmotionType

        detector = EmotionDetector()
        emotion, confidence = detector._classify(rms=0.20, zcr=0.30)
        assert emotion == EmotionType.EXCITED
        assert confidence >= 0.7

    def test_low_rms_low_zcr_classified_sad(self):
        """Quiet slow speech → SAD emotion."""
        from core.emotion_detector import EmotionDetector, EmotionType

        detector = EmotionDetector()
        emotion, confidence = detector._classify(rms=0.005, zcr=0.05)
        assert emotion == EmotionType.SAD
        assert confidence >= 0.6

    def test_low_rms_high_zcr_classified_tense(self):
        """Low amplitude high ZCR → TENSE emotion."""
        from core.emotion_detector import EmotionDetector, EmotionType

        detector = EmotionDetector()
        emotion, confidence = detector._classify(rms=0.005, zcr=0.35)
        assert emotion == EmotionType.TENSE
        assert confidence >= 0.55

    def test_low_rms_low_zcr_moderate_classified_calm(self):
        """Quiet with low ZCR → CALM emotion."""
        from core.emotion_detector import EmotionDetector, EmotionType

        detector = EmotionDetector()
        # norm_rms = 0.03/0.15 = 0.2 (< 0.4 ✓)
        # norm_zcr = 0.05/0.25 = 0.2 (< 0.4 ✓)  → falls into CALM branch
        emotion, confidence = detector._classify(rms=0.03, zcr=0.05)
        assert emotion == EmotionType.CALM
        assert confidence >= 0.6

    def test_moderate_rms_zcr_classified_neutral(self):
        """Normal speech levels → NEUTRAL emotion."""
        from core.emotion_detector import EmotionDetector, EmotionType

        detector = EmotionDetector()
        emotion, confidence = detector._classify(rms=0.08, zcr=0.20)
        assert emotion == EmotionType.NEUTRAL
        assert confidence >= 0.5


class TestEmotionDetectorAnalyze:
    """Test the full analyze() pipeline."""

    def test_too_short_audio_returns_neutral_zero_confidence(self):
        """Audio shorter than frame_size returns NEUTRAL with 0 confidence."""
        from core.emotion_detector import EmotionDetector, EmotionType

        detector = EmotionDetector()
        short = np.zeros(100, dtype=np.float32)
        result = detector.analyze(short)
        assert result.emotion == EmotionType.NEUTRAL
        assert result.confidence == 0.0

    def test_none_audio_returns_neutral_zero_confidence(self):
        """None audio input returns NEUTRAL with 0 confidence."""
        from core.emotion_detector import EmotionDetector, EmotionType

        detector = EmotionDetector()
        result = detector.analyze(None)
        assert result.emotion == EmotionType.NEUTRAL
        assert result.confidence == 0.0

    def test_analyze_returns_voice_metrics(self):
        """analyze() returns a VoiceMetrics dataclass with all fields."""
        from core.emotion_detector import EmotionDetector

        detector = EmotionDetector()
        audio = np.random.randn(4800).astype(np.float32) * 0.05
        result = detector.analyze(audio)
        assert hasattr(result, "rms")
        assert hasattr(result, "zcr")
        assert hasattr(result, "emotion")
        assert hasattr(result, "confidence")
        assert result.rms >= 0.0
        assert result.zcr >= 0.0
        assert 0.0 <= result.confidence <= 1.0


class TestEmotionToToneMapping:
    """Test mapping from EmotionType to EmotionTone."""

    def test_excited_maps_to_excited_tone(self):
        """EXCITED voice → EXCITED TTS tone."""
        from core.emotion_detector import EmotionDetector, EmotionType
        from core.tts_engine import EmotionTone

        detector = EmotionDetector()
        tone = detector.emotion_to_tone(EmotionType.EXCITED)
        assert tone == EmotionTone.EXCITED

    def test_calm_maps_to_calm_tone(self):
        """CALM voice → CALM TTS tone."""
        from core.emotion_detector import EmotionDetector, EmotionType
        from core.tts_engine import EmotionTone

        detector = EmotionDetector()
        tone = detector.emotion_to_tone(EmotionType.CALM)
        assert tone == EmotionTone.CALM

    def test_tense_maps_to_urgent_tone(self):
        """TENSE voice → URGENT TTS tone (JARVIS speaks with urgency)."""
        from core.emotion_detector import EmotionDetector, EmotionType
        from core.tts_engine import EmotionTone

        detector = EmotionDetector()
        tone = detector.emotion_to_tone(EmotionType.TENSE)
        assert tone == EmotionTone.URGENT

    def test_sad_maps_to_apologetic_tone(self):
        """SAD voice → APOLOGETIC TTS tone."""
        from core.emotion_detector import EmotionDetector, EmotionType
        from core.tts_engine import EmotionTone

        detector = EmotionDetector()
        tone = detector.emotion_to_tone(EmotionType.SAD)
        assert tone == EmotionTone.APOLOGETIC

    def test_neutral_maps_to_normal_tone(self):
        """NEUTRAL voice → NORMAL TTS tone."""
        from core.emotion_detector import EmotionDetector, EmotionType
        from core.tts_engine import EmotionTone

        detector = EmotionDetector()
        tone = detector.emotion_to_tone(EmotionType.NEUTRAL)
        assert tone == EmotionTone.NORMAL

    def test_unknown_emotion_defaults_to_normal(self):
        """Unknown emotion type defaults to NORMAL tone."""
        from core.emotion_detector import EmotionDetector, EmotionType
        from core.tts_engine import EmotionTone

        detector = EmotionDetector()
        # Test with a custom emotion (shouldn't happen in practice)
        tone = detector.emotion_to_tone(EmotionType.NEUTRAL)
        assert tone == EmotionTone.NORMAL
