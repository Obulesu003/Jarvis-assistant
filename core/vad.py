"""
vad.py - Voice Activity Detection using Silero VAD.
2ms latency, 98%+ accuracy, CPU-only, ~100MB model.

Task 22: Adaptive VAD — calibrates noise floor for better pause detection
in noisy environments. Falls back gracefully when calibration fails.
"""
import logging
import time
import numpy as np
import torch
from typing import List

logger = logging.getLogger(__name__)

# Number of chunks to sample for noise floor calibration (32ms each)
_CALIBRATION_CHUNKS = 50  # ~1.6 seconds of silence


class VoiceActivityDetector:
    """Silero VAD — voice activity detection with adaptive thresholding."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._model = None
        self._get_speech_ts = None
        # Task 22: Adaptive threshold — calibrated to ambient noise
        self._speech_threshold: float = 0.5
        self._is_calibrated: bool = False

    def initialize(self):
        """Load Silero VAD model and calibrate noise floor."""
        try:
            torch.set_num_threads(1)
            model, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            self._model = model
            self._get_speech_ts = utils[0]
            logger.info("[VAD] Silero VAD model loaded")
        except Exception as e:
            logger.error(f"[VAD] Failed to load Silero VAD: {e}")
            self._model = None

    def calibrate(self, audio_chunks: List[np.ndarray]) -> bool:
        """
        Calibrate the speech threshold from a sample of ambient audio chunks.

        Measures the mean speech probability during a known-silence window
        and sets the threshold to that mean + 2x standard deviation,
        so only genuine speech (significantly above noise) triggers detection.

        Args:
            audio_chunks: List of 512-sample float32 arrays from ambient silence

        Returns:
            True if calibration succeeded, False otherwise.
        """
        if not audio_chunks or self._model is None:
            return False

        probs = []
        for chunk in audio_chunks:
            if len(chunk) < 512:
                continue
            try:
                p = self._model(chunk, sampling_rate=self.sample_rate).item()
                probs.append(p)
            except Exception:
                continue

        if len(probs) < 10:
            logger.warning("[VAD] Calibration: not enough valid chunks")
            return False

        mean_prob = np.mean(probs)
        std_prob = np.std(probs)
        # Threshold: mean + 2 std, but cap between 0.3 and 0.7
        threshold = min(0.7, max(0.3, mean_prob + 2 * std_prob))
        self._speech_threshold = threshold
        self._is_calibrated = True
        logger.info(
            f"[VAD] Calibrated: noise_mean={mean_prob:.3f}, "
            f"noise_std={std_prob:.3f}, threshold={threshold:.3f}"
        )
        return True

    def is_speech(self, audio: np.ndarray) -> bool:
        """Check if a 512-sample chunk contains speech. audio must be float32 [-1, 1]."""
        if self._model is None:
            return True  # Fallback: assume speech

        try:
            if len(audio) < 512:
                return False
            speech_probs = self._model(audio, sampling_rate=self.sample_rate)
            return speech_probs.item() > self._speech_threshold
        except Exception as e:
            logger.debug(f"[VAD] Check error: {e}")
            return True

    def get_speech_segments(self, audio: np.ndarray) -> List[dict]:
        """Find all speech regions in a longer audio buffer. Returns list of {start, end}."""
        if self._model is None or self._get_speech_ts is None:
            return []
        try:
            speech_dict = self._get_speech_ts(
                audio,
                sampling_rate=self.sample_rate,
                return_seconds=True,
            )
            return speech_dict.get("segments", [])
        except Exception as e:
            logger.debug(f"[VAD] Segment detection error: {e}")
            return []

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def is_calibrated(self) -> bool:
        """True if adaptive calibration has been applied."""
        return self._is_calibrated

    @property
    def speech_threshold(self) -> float:
        """Current adaptive speech threshold."""
        return self._speech_threshold
