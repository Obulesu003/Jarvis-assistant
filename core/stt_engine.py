"""
stt_engine.py - Local transcription using Faster-Whisper.
4x faster than standard Whisper, CPU-only with int8 quantization.
"""
import logging
import numpy as np
from typing import Literal

logger = logging.getLogger(__name__)


class STTEngine:
    """
    Faster-Whisper for real-time local transcription.

    Model sizes (choose based on CPU speed):
    - tiny:   39MB  →  fastest,  ~85% accuracy  → good for commands
    - base:   74MB  →  fast,    ~90% accuracy  → recommended fallback
    - small:  244MB →  moderate ~95% accuracy  → RECOMMENDED
    - medium: 769MB →  slower,  ~97% accuracy  → if you have CPU cores to spare
    """

    def __init__(self, model_size: Literal["tiny", "base", "small", "medium"] = "small"):
        self.model_size = model_size
        self._model = None
        self._model_name = None

    def initialize(self):
        """Load Faster-Whisper model."""
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )
            self._model_name = "medium" if self.model_size == "medium" else self.model_size
            logger.info(f"[STT] Loaded model: {self.model_size}")
        except ImportError:
            logger.warning("[STT] faster-whisper not installed. Install with: pip install faster-whisper")
            self._model = None

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a numpy audio array (16kHz mono float32)."""
        if self._model is None:
            return ""
        if len(audio) < 1600:  # Less than 100ms
            return ""

        try:
            segments, info = self._model.transcribe(
                audio,
                beam_size=3,
                best_of=2,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                language="en",
            )
            text = " ".join([s.text for s in segments]).strip()
            return text
        except Exception as e:
            logger.error(f"[STT] Transcription error: {e}")
            return ""

    @property
    def is_ready(self) -> bool:
        return self._model is not None