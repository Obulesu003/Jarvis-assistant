"""
audio_pipeline.py - Complete JARVIS audio loop.
openWakeWord → Silero VAD → Faster-Whisper → Gemini → Piper TTS

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
    openWakeWord → Silero VAD → Faster-Whisper → Gemini → Piper TTS

    All local except Gemini. <500ms response latency.
    """

    def __init__(
        self,
        on_transcript: Callable[[str], None] | None = None,
        on_response: Callable[[str], None] | None = None,
        gemini_client=None,
    ):
        self._wake_word = None
        self._vad = None
        self._stt = None
        self._tts = None
        self._gemini = gemini_client

        # Callbacks
        self.on_transcript = on_transcript  # Called when user speech is transcribed
        self.on_response = on_response      # Called when JARVIS wants to speak

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
                if status:
                    logger.debug(f"[AudioPipeline] Audio status: {status}")
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
                while self._is_listening:
                    time.sleep(0.01)
        except ImportError:
            logger.error("[AudioPipeline] sounddevice not installed. Run: pip install sounddevice numpy")
        except Exception as e:
            logger.error(f"[AudioPipeline] Stream error: {e}")

    def _process_state(self):
        """State machine: idle → woken → listening → processing → idle."""
        import numpy as np

        if len(self._audio_buffer) < 512:
            return

        latest = np.array(list(self._audio_buffer)[-512:], dtype=np.float32)

        # Skip processing if JARVIS is speaking
        if self._is_speaking:
            return

        if self._state == "idle":
            # Wait for wake word
            wake = self._wake_word.detect(latest)
            if wake:
                self._state = "woken"
                self._wake_activated_time = time.time()
                self._tts.speak_async("Yes, sir?")
                logger.info("[AudioPipeline] Wake word detected")

        elif self._state == "woken":
            if self._vad.is_speech(latest):
                self._state = "listening"
                self._speech_buffer.clear()
                # Capture last 1.5s of audio before speech started
                self._speech_buffer.extend(list(self._audio_buffer)[-24000:])
                self._speech_start_time = time.time()
                logger.info("[AudioPipeline] Speech detected")
            elif time.time() - self._wake_activated_time > 3:
                self._state = "idle"

        elif self._state == "listening":
            if self._vad.is_speech(latest):
                self._speech_buffer.extend(latest)
                self._silence_frames = 0
            else:
                self._silence_frames += 1
                # ~800ms of silence (25 frames × 32ms) = end of utterance
                if self._silence_frames > 25:
                    self._state = "processing"

        elif self._state == "processing":
            self._is_speaking = True
            speech_audio = np.array(list(self._speech_buffer), dtype=np.float32)
            self._speech_buffer.clear()

            text = self._stt.transcribe(speech_audio)
            self._state = "idle"
            self._is_speaking = False

            if text.strip():
                logger.info(f"[AudioPipeline] User: {text}")
                if self.on_transcript:
                    self.on_transcript(text)
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