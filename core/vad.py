"""
vad.py - Voice Activity Detection using Silero VAD.
2ms latency, 98%+ accuracy, CPU-only, ~100MB model.
"""
import logging
import numpy as np
import torch
from typing import List

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """Silero VAD — voice activity detection."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._model = None
        self._get_speech_ts = None

    def initialize(self):
        """Load Silero VAD model."""
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

    def is_speech(self, audio: np.ndarray) -> bool:
        """Check if a 512-sample chunk contains speech. audio must be float32 [-1, 1]."""
        if self._model is None:
            return True  # Fallback: assume speech

        try:
            if len(audio) < 512:
                return False
            speech_probs = self._model(audio, sampling_rate=self.sample_rate)
            return speech_probs.item() > 0.5
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