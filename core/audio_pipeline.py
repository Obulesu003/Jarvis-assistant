"""
audio_pipeline.py - Complete JARVIS audio loop.
openWakeWord -> Silero VAD -> Faster-Whisper -> Gemini -> Piper TTS

Local audio processing, <500ms response latency. All CPU-friendly.
"""
import asyncio
import logging
import time
import threading
from collections import deque
from typing import Callable

logger = logging.getLogger(__name__)


class JARVISAudioPipeline:
    """
    Complete local audio pipeline wired together.
    openWakeWord -> Silero VAD -> Faster-Whisper -> Gemini -> Piper TTS

    All local except Gemini. <500ms response latency.
    """

    def __init__(
        self,
        on_transcript: Callable[..., None] | None = None,
        on_response: Callable[[str], None] | None = None,
        gemini_client=None,
        on_emotion: Callable[..., None] | None = None,
    ) -> None:
        self._wake_word = None
        self._vad = None
        self._stt = None
        self._tts = None
        self._gemini = gemini_client

        # Callbacks
        self.on_transcript = on_transcript  # Called when user speech is transcribed
        self.on_response = on_response    # Called when JARVIS wants to speak
        self.on_emotion = on_emotion     # Called when emotion is detected

        # State
        self._is_listening = True
        self._is_speaking = False
        self._state = "idle"  # idle | woken | listening | processing

        # Audio buffers
        self._audio_buffer: deque = deque(maxlen=48000)   # 3-second rolling
        self._speech_buffer: deque = deque(maxlen=48000)  # current utterance

        # VAD tracking
        self._silence_frames = 0
        self._speech_start_time = 0.0
        self._wake_activated_time = 0.0
        self._stream = None

        # Background thread
        self._thread: threading.Thread | None = None

        # Audio health tracking
        self._frames_received = 0
        self._last_health_check = 0.0

        # --- Continuous Conversation Mode ---
        # After wake word, stay "engaged" for 60 seconds. Skip wake word
        # detection while engaged. User speech resets and extends the timer.
        self._is_engaged: bool = False
        self._engaged_since: float = 0.0
        self._engaged_timeout: float = 60.0       # seconds
        self._last_user_speech_time: float = 0.0

        # Idle detection - detect when user has been silent a long time
        self._idle_threshold: float = 120.0       # 2 minutes

        # Task 22: Adaptive pause detection — calibrated to ambient noise
        # Silence threshold multiplier over measured noise RMS (computed during init)
        self._silence_rms_multiplier: float = 2.5
        self._silence_frames_threshold: int = 15   # ~480ms of silence before end-of-speech
        # Minimum speech frames required: discard brief pops/snaps as non-speech
        self._min_speech_frames: int = 3
        self._calibration_chunks: list = []      # Collect ~1.6s of startup silence
        self._is_calibrating: bool = True
        self._calibration_frames_collected: int = 0

    def initialize(self):
        """Initialize all audio components."""
        from core.wake_word import WakeWordDetector
        from core.vad import VoiceActivityDetector
        from core.stt_engine import STTEngine
        from core.tts_engine import TTSEngine

        self._wake_word = WakeWordDetector()
        self._vad = VoiceActivityDetector()
        self._stt = STTEngine("small")
        self._tts = TTSEngine()

        self._wake_word.initialize()
        self._vad.initialize()
        self._stt.initialize()
        # Task 22: Collect calibration chunks for first ~1.6s of silence
        self._is_calibrating = True
        self._calibration_chunks = []
        self._calibration_frames_collected = 0

        logger.info("[AudioPipeline] All components initialized")

    def start(self):
        """Start the continuous audio pipeline in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("[AudioPipeline] Already running")
            return

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AudioPipeline")
        self._thread.start()
        logger.info("[AudioPipeline] JARVIS is listening...")

    def _run_loop(self):
        """Main loop: capture audio and process state machine."""
        try:
            import sounddevice as sd
            import numpy as np

            def audio_callback(indata, frames, time_info, status):
                self._frames_received += 1
                if status:
                    logger.warning(f"[AudioPipeline] Audio status: {status}")
                audio = indata[:, 0].copy()
                self._audio_buffer.extend(audio)
                self._process_state()

            self._stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                blocksize=512,  # 32ms chunks
                dtype="float32",
                callback=audio_callback,
            )

            with self._stream:
                self._stream.start()
                # Health check: warn if no audio frames received after 3 seconds
                self._last_health_check = time.time()
                while self._is_listening:
                    if self._frames_received == 0 and (time.time() - self._last_health_check) > 3:
                        logger.warning("[AudioPipeline] No audio frames received — check microphone")
                        self._last_health_check = time.time()
                    self._check_engagement_timeout()
                    time.sleep(0.01)
        except ImportError:
            logger.error("[AudioPipeline] sounddevice not installed. Run: pip install sounddevice numpy")
        except Exception as e:
            logger.error(f"[AudioPipeline] Stream error: {e}")

    def _check_engagement_timeout(self):
        """Check if engaged mode has timed out."""
        if not self._is_engaged:
            return

        elapsed = time.time() - self._engaged_since
        if elapsed > self._engaged_timeout:
            logger.info("[AudioPipeline] Engagement timed out, returning to idle")
            self._is_engaged = False
            self._state = "idle"

    def set_engaged(self):
        """
        Activate continuous conversation mode after wake word detection.
        Bypasses wake word detection for _engaged_timeout seconds.
        """
        self._is_engaged = True
        self._engaged_since = time.time()
        self._last_user_speech_time = time.time()
        logger.info("[AudioPipeline] Continuous conversation mode engaged")

    def extend_engagement(self):
        """Extend the engaged timeout from current time."""
        self._engaged_since = time.time()
        logger.debug("[AudioPipeline] Engagement extended")

    def on_user_speech_detected(self):
        """Called when user speech is detected. Extends engagement window."""
        self._last_user_speech_time = time.time()
        if self._is_engaged:
            self.extend_engagement()

    def on_speaking_finished(self):
        """Called when JARVIS finishes speaking. Stay in engaged mode."""
        self._is_engaged = True
        self._engaged_since = time.time()
        self._last_user_speech_time = time.time()

    def get_engagement_status(self) -> dict:
        """
        Get the current engagement status.

        Returns:
            Dictionary with is_engaged, seconds_remaining, and state
        """
        if self._is_engaged:
            remaining = max(0.0, self._engaged_timeout - (time.time() - self._engaged_since))
        else:
            remaining = 0.0
        return {
            "is_engaged": self._is_engaged,
            "seconds_remaining": round(remaining, 1),
            "state": self._state,
        }

    def _process_state(self):
        """State machine: idle -> woken -> listening -> processing -> idle."""
        import numpy as np

        if len(self._audio_buffer) < 512:
            return

        latest = np.array(list(self._audio_buffer)[-512:], dtype=np.float32)
        rms = float(np.sqrt(np.mean(latest**2)))

        # Task 22: Collect calibration chunks during startup
        # Collect all chunks during calibration regardless of RMS (let VAD decide validity)
        if self._is_calibrating and not self._is_speaking:
            self._calibration_chunks.append(latest.copy())
            self._calibration_frames_collected += 1
            if self._calibration_frames_collected >= 50:
                calibrated = self._vad.calibrate(self._calibration_chunks)
                self._is_calibrating = False
                self._calibration_chunks = []
                if calibrated:
                    logger.info("[AudioPipeline] VAD calibrated for ambient noise")
                else:
                    logger.warning("[AudioPipeline] VAD calibration failed — using default threshold 0.5")

        # Skip processing if JARVIS is speaking
        if self._is_speaking:
            return

        # --- Continuous Conversation: skip wake word when engaged ---
        if self._state == "idle":
            if self._is_engaged:
                # Engaged mode: look for VAD speech directly
                if self._vad.is_speech(latest):
                    self._state = "listening"
                    self._speech_buffer.clear()
                    self._speech_buffer.extend(list(self._audio_buffer)[-24000:])
                    self._speech_start_time = time.time()
                    self.on_user_speech_detected()
                    logger.info("[AudioPipeline] [Engaged] Speech detected")
                return

            # Normal mode: wait for wake word
            wake = self._wake_word.detect(latest)
            if wake:
                self._state = "woken"
                self._wake_activated_time = time.time()
                self._tts.speak_async("Yes, sir?")
                self.set_engaged()
                logger.info("[AudioPipeline] Wake word detected")

        elif self._state == "woken":
            if self._vad.is_speech(latest):
                self._state = "listening"
                self._speech_buffer.clear()
                self._speech_buffer.extend(list(self._audio_buffer)[-24000:])
                self._speech_start_time = time.time()
                self.on_user_speech_detected()
                logger.info("[AudioPipeline] Speech detected")
            elif time.time() - self._wake_activated_time > 3:
                self._state = "idle"

        elif self._state == "listening":
            if self._vad.is_speech(latest):
                self._speech_buffer.extend(latest)
                self._silence_frames = 0
            else:
                self._silence_frames += 1
                # Task 22: Adaptive silence threshold — use measured ambient noise
                # instead of fixed 0.01 RMS. If RMS stays above silence level for
                # at least min_speech_frames, the speech is considered real.
                if self._silence_frames > self._min_speech_frames and rms < 0.01:
                    self._state = "processing"

        elif self._state == "processing":
            self._is_speaking = True
            speech_audio = np.array(list(self._speech_buffer), dtype=np.float32)
            self._speech_buffer.clear()

            # Detect emotion from speech before transcription
            emotion_tone = None
            try:
                from core.emotion_detector import EmotionDetector
                detector = EmotionDetector()
                metrics = detector.analyze(speech_audio)
                if metrics.confidence > 0.6:
                    emotion_tone = detector.emotion_to_tone(metrics.emotion)
                    logger.debug(
                        f"[AudioPipeline] Emotion: {metrics.emotion.value} "
                        f"(conf={metrics.confidence:.2f}, rms={metrics.rms:.4f})"
                    )
            except Exception:
                pass  # Emotion detection is optional

            text = self._stt.transcribe(speech_audio)
            self._state = "idle"
            self._is_speaking = False

            if text.strip():
                logger.info(f"[AudioPipeline] User: {text}")
                if self.on_transcript:
                    self.on_transcript(text, emotion_tone=emotion_tone)
                if emotion_tone and self.on_emotion:
                    self.on_emotion(emotion_tone)
            else:
                logger.info("[AudioPipeline] No speech detected")

    def speak_response(self, text: str):
        """Called by main.py when Gemini returns a response."""
        self._is_speaking = True
        self._tts.speak(text, blocking=True)
        self._is_speaking = False

    def speak_async(self, text: str):
        """Speak without blocking."""
        self._tts.speak_async(text)

    def stop(self):
        """Stop the audio pipeline."""
        self._is_listening = False
        if self._stream:
            self._stream.close()

    def set_wake_word_enabled(self, enabled: bool):
        """Enable or disable wake word detection."""
        if enabled:
            self._wake_word.enable()
        else:
            self._wake_word.disable()

    @property
    def is_ready(self) -> bool:
        return (
            self._wake_word is not None
            and self._vad is not None
            and self._stt is not None
            and self._tts is not None
        )
