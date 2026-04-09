"""
wake_word.py - JARVIS Wake Word Detection
Uses openWakeWord for local, always-on "Hey JARVIS" wake word detection.
Tiny model (~2MB), runs on CPU, ~2% CPU usage, zero API calls.

Works alongside the existing push-to-talk — JARVIS listens passively
in the background and activates when it hears the wake word.
"""
import logging
import threading
import collections
import time

logger = logging.getLogger(__name__)

# ── Singleton ─────────────────────────────────────────────────────────────────

_wake_word_instance = None


def get_wake_word_detector():
    global _wake_word_instance
    if _wake_word_instance is None:
        _wake_word_instance = WakeWordDetector()
    return _wake_word_instance


class WakeWordDetector:
    """
    Local wake word detection using openWakeWord.
    Tiny, fast, runs entirely on CPU. No cloud, no API key.

    After wake word detected, user speaks command → Gemini processes it.
    """

    # Minimum confidence threshold (0.0-1.0)
    CONFIDENCE_THRESHOLD = 0.5

    # How long to stay "awake" before returning to listening (seconds)
    ACTIVE_DURATION = 8.0

    # Cooldown between wake detections (prevent rapid re-triggering)
    COOLDOWN = 5.0

    def __init__(self):
        self._engine = None
        self._is_available = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._is_awake = False
        self._last_wake_time = 0
        self._last_deactivation = 0

        # Audio buffer (16kHz mono float32)
        self._audio_buffer = collections.deque(maxlen=16000)  # 1 second buffer
        self._stream = None

        # Callbacks
        self._on_wake_callback = None
        self._on_speech_callback = None

        # State
        self._silence_threshold = 0.01
        self._speech_frames = 0
        self._silence_frames = 0

    def _check_availability(self) -> bool:
        """Check if openWakeWord is installed."""
        if self._is_available is not None:
            return self._is_available
        try:
            from openwakeword import WakeWordEngine
            self._is_available = True
            logger.info("[WakeWord] openWakeWord available")
        except ImportError:
            self._is_available = False
            logger.warning("[WakeWord] openWakeWord not installed.")
            logger.info("[WakeWord] Install with: pip install openwakeword")
        return self._is_available

    def initialize(self):
        """Initialize openWakeWord engine (standalone mode)."""
        if self._engine is not None:
            return True

        if not self._check_availability():
            return False

        try:
            from openwakeword import WakeWordEngine
            self._engine = WakeWordEngine(
                models=["hey_jarvis", "alexa", "ok_google"],
                inference_framework="silero",
            )
            logger.info("[WakeWord] Engine initialized — listening for wake words")
            return True
        except Exception as e:
            logger.error(f"[WakeWord] Engine init failed: {e}")
            self._is_available = False
            return False

    def _audio_callback(self, indata, frames, time_info, status):
        """Called every ~32ms with new audio. Must return fast."""
        if status:
            logger.debug(f"[WakeWord] Audio status: {status}")
        audio = indata[:, 0].copy()
        self._audio_buffer.extend(audio)

    def _process_loop(self):
        """Main processing loop — runs in a background thread."""
        import numpy as np

        # Wait for enough audio
        while self._running and len(self._audio_buffer) < 512:
            time.sleep(0.01)

        chunk_size = 512  # ~32ms at 16kHz

        while self._running:
            try:
                if len(self._audio_buffer) < chunk_size:
                    time.sleep(0.01)
                    continue

                chunk = np.array(list(self._audio_buffer)[-chunk_size:], dtype=np.float32)

                if not self._is_awake:
                    # ── LISTENING: Check for wake word ──────────────────────
                    predictions = self._engine.predict(chunk)

                    for wakeword, score in predictions.items():
                        if score > self.CONFIDENCE_THRESHOLD:
                            now = time.time()
                            if now - self._last_wake_time < self.COOLDOWN:
                                continue

                            logger.info(f"[WakeWord] Detected: {wakeword} ({score:.2f})")
                            self._is_awake = True
                            self._last_wake_time = now
                            self._speech_frames = 0
                            self._silence_frames = 0

                            if self._on_wake_callback:
                                try:
                                    self._on_wake_callback(wakeword)
                                except Exception as e:
                                    logger.error(f"[WakeWord] Wake callback error: {e}")
                else:
                    # ── ACTIVE: Listen for speech then deactivate ─────────────
                    audio_level = np.sqrt(np.mean(chunk ** 2))

                    if audio_level > self._silence_threshold:
                        self._speech_frames += 1
                        self._silence_frames = 0
                    else:
                        self._silence_frames += 1
                        self._silence_frames = min(self._silence_frames, 100)

                    timeout = (time.time() - self._last_wake_time) > self.ACTIVE_DURATION
                    too_quiet = self._silence_frames > 30  # ~1 second of silence

                    if timeout or too_quiet:
                        self._is_awake = False
                        self._last_deactivation = time.time()
                        logger.debug("[WakeWord] Returning to listening mode")
                        if self._on_speech_callback:
                            try:
                                self._on_speech_callback()
                            except Exception as e:
                                logger.debug(f"[WakeWord] Deactivate callback: {e}")

            except Exception as e:
                logger.debug(f"[WakeWord] Process error: {e}")

    def detect(self, audio_chunk) -> str | None:
        """
        Pass a 512-sample float32 numpy array normalized to [-1, 1].
        Returns wakeword name if detected, None otherwise.
        (For manual integration with external audio pipelines.)
        """
        if not self._engine or not self._running:
            return None

        try:
            predictions = self._engine.predict(audio_chunk)
            for wakeword, score in predictions.items():
                if score > self.CONFIDENCE_THRESHOLD:
                    logger.info(f"[WakeWord] Detected: {wakeword} ({score:.2f})")
                    return wakeword
        except Exception as e:
            logger.debug(f"[WakeWord] Detection error: {e}")
        return None

    def start(self, on_wake=None, on_deactivate=None):
        """
        Start wake word detection in a background thread.

        Args:
            on_wake: callback(wakeword) when wake word is detected
            on_deactivate: callback() when JARVIS returns to listening mode
        """
        if self._running:
            return

        if not self.initialize():
            return

        self._on_wake_callback = on_wake
        self._on_speech_callback = on_deactivate
        self._running = True

        try:
            import sounddevice as sd
            self._stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                blocksize=512,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as e:
            logger.error(f"[WakeWord] Audio stream failed: {e}")
            self._running = False
            return

        self._thread = threading.Thread(target=self._process_loop, daemon=True, name="WakeWord")
        self._thread.start()
        logger.info("[WakeWord] Started — say 'Hey JARVIS' to activate")

    def stop(self):
        """Stop wake word detection."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("[WakeWord] Stopped")

    def is_listening(self) -> bool:
        """Is JARVIS currently listening for the wake word?"""
        return self._running and not self._is_awake

    def is_awake(self) -> bool:
        """Is JARVIS currently awake (heard wake word, waiting for command)?"""
        return self._is_awake

    def is_running(self) -> bool:
        """Is the wake word detector running?"""
        return self._running

    def set_threshold(self, threshold: float):
        """Set the confidence threshold (0.0-1.0)."""
        self.CONFIDENCE_THRESHOLD = max(0.1, min(1.0, threshold))

    def force_awake(self):
        """Manually activate JARVIS (simulates wake word detection)."""
        self._is_awake = True
        self._last_wake_time = time.time()
        self._speech_frames = 0
        self._silence_frames = 0
        if self._on_wake_callback:
            try:
                self._on_wake_callback("manual")
            except Exception:
                pass

    def enable(self):
        self._running = True

    def disable(self):
        self._running = False

    @property
    def is_ready(self) -> bool:
        return self._engine is not None
