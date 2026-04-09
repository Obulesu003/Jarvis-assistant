"""
tts_engine.py - Local voice output using Piper TTS.
Fast, natural-sounding, CPU-only. British voice for JARVIS feel.
"""
import logging
import subprocess
import numpy as np
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class TTSEngine:
    """
    Piper TTS — local, fast, natural-sounding voice output.
    No API calls, no cloud, no network latency.
    """

    def __init__(self, voice_path: str = "models/voices/en_GB-alan-medium.onnx"):
        self.voice_path = voice_path
        self.is_speaking = False
        self._is_installed = None
        self._process: subprocess.Popen | None = None

    def _check_installation(self) -> bool:
        """Check if Piper CLI is available."""
        if self._is_installed is not None:
            return self._is_installed
        try:
            result = subprocess.run(["piper", "--help"], capture_output=True, text=True, timeout=5)
            self._is_installed = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._is_installed = False
        if not self._is_installed:
            logger.warning("[TTS] Piper not installed. Download from: https://github.com/rhasspy/piper/releases")
            logger.warning("[TTS] Or install via: pip install piper-tts")
        return self._is_installed

    def speak(self, text: str, blocking: bool = True) -> np.ndarray | None:
        """Convert text to speech. Returns audio as numpy float32 array."""
        if not text or not text.strip():
            return None
        if not self._check_installation():
            return None

        self.is_speaking = True
        try:
            if not Path(self.voice_path).exists():
                logger.warning(f"[TTS] Voice file not found: {self.voice_path}")
                logger.info("[TTS] Download with:")
                logger.info("  wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx -P models/voices/")
                return None

            process = subprocess.Popen(
                ["piper", "--model", self.voice_path, "--output-raw", "-- Sentence-level punctuation"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._process = process  # Store reference for stop_async()
            audio_bytes, _ = process.communicate(input=text.encode(), timeout=10)

            # Piper outputs raw PCM 16-bit mono at 22050Hz
            audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_float32 = audio_int16.astype(np.float32) / 32768.0

            if blocking:
                self._play_audio(audio_float32)
            return audio_float32
        except subprocess.TimeoutExpired:
            logger.error("[TTS] TTS generation timed out")
            return None
        except FileNotFoundError:
            logger.error("[TTS] Piper executable not found in PATH")
            self._is_installed = False
            return None
        except Exception as e:
            logger.error(f"[TTS] Error: {e}")
            return None
        finally:
            self.is_speaking = False
            self._process = None

    def _play_audio(self, audio: np.ndarray, samplerate: int = 22050):
        """Play audio through speakers using sounddevice."""
        try:
            import sounddevice as sd
            sd.play(audio, samplerate=samplerate)
            sd.wait()
        except ImportError:
            logger.warning("[TTS] sounddevice not installed")
        except Exception as e:
            logger.error(f"[TTS] Playback error: {e}")

    def speak_async(self, text: str):
        """Speak without blocking (can be interrupted)."""
        thread = threading.Thread(target=self.speak, args=(text, True), daemon=True)
        thread.start()

    def stop_async(self):
        """Stop current speech immediately. Used for interruption."""
        self.is_speaking = False
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    @property
    def is_ready(self) -> bool:
        return self._check_installation() and Path(self.voice_path).exists()