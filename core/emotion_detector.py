"""
emotion_detector.py - Voice emotion detection using RMS and ZCR analysis.
Detects emotion from speech audio for TTS modulation.
"""
import logging
import numpy as np
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class EmotionType(Enum):
    """Emotion types detected from voice."""
    NEUTRAL = "neutral"
    EXCITED = "excited"      # High RMS, high ZCR
    CALM = "calm"            # Low RMS, low ZCR
    TENSE = "tense"          # Low amplitude, high ZCR
    SAD = "sad"              # Low RMS, very low ZCR


@dataclass
class VoiceMetrics:
    """Audio features extracted from a speech segment."""
    rms: float        # Root mean square (amplitude)
    zcr: float        # Zero crossing rate
    emotion: EmotionType = EmotionType.NEUTRAL
    confidence: float = 0.5


class EmotionDetector:
    """
    Detects emotion from voice audio using lightweight signal analysis.
    Uses RMS (volume energy) and ZCR (pitch/speech rate) metrics.

    Calibration-free, runs on CPU, no ML model needed.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 30,
    ):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * frame_ms / 1000)

        # Thresholds (calibrated from typical speech)
        self._rms_low = 0.02
        self._rms_high = 0.15
        self._zcr_high = 0.25  # voiced/unvoiced threshold

    def analyze(self, audio: np.ndarray) -> VoiceMetrics:
        """
        Analyze audio and return emotion metrics.

        Args:
            audio: Float32 numpy array of audio samples (mono, 16kHz)

        Returns:
            VoiceMetrics with emotion, RMS, ZCR, and confidence
        """
        if audio is None or len(audio) < self.frame_size:
            return VoiceMetrics(rms=0.0, zcr=0.0, emotion=EmotionType.NEUTRAL, confidence=0.0)

        try:
            rms = self._compute_rms(audio)
            zcr = self._compute_zcr(audio)
            emotion, confidence = self._classify(rms, zcr)

            return VoiceMetrics(
                rms=round(rms, 4),
                zcr=round(zcr, 4),
                emotion=emotion,
                confidence=round(confidence, 2),
            )
        except Exception as e:
            logger.debug(f"[EmotionDetector] Analysis failed: {e}")
            return VoiceMetrics(rms=0.0, zcr=0.0, emotion=EmotionType.NEUTRAL, confidence=0.0)

    def _compute_rms(self, audio: np.ndarray) -> float:
        """Compute RMS (root mean square) amplitude."""
        return float(np.sqrt(np.mean(audio**2)))

    def _compute_zcr(self, audio: np.ndarray) -> float:
        """Compute zero crossing rate (normalised to [0,1])."""
        if len(audio) < 2:
            return 0.0
        crossings = np.sum(np.abs(np.diff(np.sign(audio)))) / 2
        return float(crossings / len(audio))

    def _classify(self, rms: float, zcr: float) -> tuple[EmotionType, float]:
        """
        Classify emotion from RMS and ZCR values.

        Returns:
            Tuple of (EmotionType, confidence 0-1)
        """
        # Normalise values to [0,1]
        norm_rms = min(rms / self._rms_high, 1.0)
        norm_zcr = min(zcr / self._zcr_high, 1.0) if self._zcr_high > 0 else 0.0

        # Decision tree
        if norm_rms < 0.15:
            if norm_zcr < 0.3:
                return EmotionType.SAD, 0.6
            else:
                return EmotionType.TENSE, 0.55
        elif norm_rms > 0.7 and norm_zcr > 0.6:
            return EmotionType.EXCITED, 0.7
        elif norm_rms < 0.4 and norm_zcr < 0.4:
            return EmotionType.CALM, 0.6
        else:
            return EmotionType.NEUTRAL, 0.5

    def emotion_to_tone(self, emotion: EmotionType):
        """Map detected emotion to TTS EmotionTone."""
        from core.tts_engine import EmotionTone

        mapping = {
            EmotionType.EXCITED: EmotionTone.EXCITED,
            EmotionType.CALM: EmotionTone.CALM,
            EmotionType.TENSE: EmotionTone.URGENT,
            EmotionType.SAD: EmotionTone.APOLOGETIC,
            EmotionType.NEUTRAL: EmotionTone.NORMAL,
        }
        return mapping.get(emotion, EmotionTone.NORMAL)
