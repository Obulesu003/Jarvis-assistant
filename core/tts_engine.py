"""
tts_engine.py - Local voice output using Piper TTS.
Fast, natural-sounding, CPU-only. British voice for JARVIS feel.
"""
import logging
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class EmotionTone(Enum):
    """
    Emotional tone modifiers for JARVIS TTS.
    Speed and pitch multipliers adjust how Piper speaks.
    """

    CALM = ("calm", 0.95, 1.0)
    EXCITED = ("excited", 1.2, 1.1)
    APOLOGETIC = ("apologetic", 0.85, 0.95)
    URGENT = ("urgent", 1.3, 1.05)
    WHISPERED = ("whispered", 0.7, 0.85)
    NORMAL = ("normal", 1.0, 1.0)

    def __init__(self, label: str, speed: float, pitch: float):
        self.label = label
        self.speed = speed
        self.pitch = pitch


@dataclass
class VoiceEmotion:
    """Tracks JARVIS's emotional state for TTS modulation."""
    tone: EmotionTone = EmotionTone.NORMAL
    intensity: float = 1.0  # 0.0 to 2.0


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
        self._lock = threading.Lock()
        self._emotion = VoiceEmotion()

    def set_emotion(self, tone: EmotionTone) -> None:
        """Set JARVIS's emotional tone for the next spoken phrase."""
        self._emotion.tone = tone

    def reset_emotion(self) -> None:
        """Reset to normal tone after emotional phrase."""
        self._emotion.tone = EmotionTone.NORMAL

    def get_emotion(self) -> VoiceEmotion:
        """Get the current emotional state."""
        return self._emotion

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

        with self._lock:
            self.is_speaking = True
            self._process = None
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
            with self._lock:
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
            with self._lock:
                self._process = None
                self.is_speaking = False

    def _play_audio(self, audio: np.ndarray, samplerate: int = 22050):
        """Play audio through speakers using sounddevice, with emotion modulation."""
        try:
            import sounddevice as sd

            tone = self._emotion.tone
            if tone != EmotionTone.NORMAL:
                # Adjust playback speed (simulates speaking rate)
                adjusted_sr = int(samplerate / tone.speed)
                # Pitch shift via simple resampling (lightweight approximation)
                if tone.pitch != 1.0:
                    indices = np.arange(0, len(audio), tone.pitch)
                    audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
                self.reset_emotion()
            else:
                adjusted_sr = samplerate

            sd.play(audio, samplerate=adjusted_sr)
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
        with self._lock:
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