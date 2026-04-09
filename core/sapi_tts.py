"""
sapi_tts.py - Windows SAPI TTS engine.
Fast, built-in, zero-dependency voice for JARVIS.
Uses Windows Speech API (SAPI) via COM — already installed on every Windows PC.
"""
import logging
import threading
import queue
import time
import platform

logger = logging.getLogger(__name__)

# Only available on Windows
if platform.system() != "Windows":
    raise ImportError("SAPI TTS is only available on Windows.")


class SAPITTS:
    """
    Windows SAPI TTS — built into every Windows installation.
    Zero downloads, instant voice, ~50ms latency.

    British male voice recommended (set via Windows Speech settings),
    but falls back gracefully to any installed voice.
    """

    def __init__(self):
        self._engine = None
        self._is_speaking = False
        self._is_available = None
        self._voice_queue = queue.Queue()
        self._speaker_thread: threading.Thread | None = None
        self._running = False

    def _check_availability(self) -> bool:
        """Check if SAPI is available on this system."""
        if self._is_available is not None:
            return self._is_available
        try:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            import win32com.client
            engine = win32com.client.Dispatch("SAPI.SpVoice")
            # Try to speak something very quietly
            engine.Speak("", 3)  # 3 = SPF_PURGEBEFORESPEAK
            engine = None
            self._is_available = True
            logger.info("[SAPI] Available — using Windows built-in voice")
        except Exception as e:
            self._is_available = False
            logger.warning(f"[SAPI] Not available: {e}")
        return self._is_available

    def _get_engine(self):
        """Get (or create) the SAPI engine."""
        if self._engine is None:
            import pythoncom
            import win32com.client
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            self._engine = win32com.client.Dispatch("SAPI.SpVoice")
            # Try to set a British voice if available
            try:
                voices = self._engine.GetVoices()
                for voice in voices:
                    name = voice.GetDescription()
                    # Prefer British voices for JARVIS feel
                    if any(v in name.lower() for v in ["zira", "david", "mark", "henry", "george"]):
                        self._engine.Voice = voice
                        logger.info(f"[SAPI] Using voice: {name}")
                        break
                else:
                    logger.info(f"[SAPI] Using default voice: {voices.Item(0).GetDescription()}")
            except Exception:
                pass
        return self._engine

    def speak(self, text: str, blocking: bool = True) -> bool:
        """
        Speak text using Windows SAPI.
        Returns True if successful, False otherwise.
        """
        if not text or not text.strip():
            return False

        if not self._check_availability():
            return False

        if blocking:
            return self._speak_sync(text)
        else:
            self._voice_queue.put(text)
            self._ensure_speaker_thread()
            return True

    def _speak_sync(self, text: str) -> bool:
        """Synchronous speak — blocks until done."""
        try:
            self._is_speaking = True
            engine = self._get_engine()
            # 1 = SPF_DEFAULT (blocking), 3 = SPF_PURGEBEFORESPEAK
            engine.Speak(text, 1 | 3)
            return True
        except Exception as e:
            logger.error(f"[SAPI] Speak error: {e}")
            return False
        finally:
            self._is_speaking = False

    def _ensure_speaker_thread(self):
        """Start the background speaker thread if not running."""
        if self._speaker_thread is not None and self._speaker_thread.is_alive():
            return
        self._running = True
        self._speaker_thread = threading.Thread(
            target=self._speaker_loop,
            daemon=True,
            name="SAPISpeaker"
        )
        self._speaker_thread.start()

    def _speaker_loop(self):
        """Background thread that dequeues and speaks utterances."""
        import pythoncom
        import win32com.client
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        engine = None

        while self._running:
            try:
                text = self._voice_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                if engine is None:
                    engine = win32com.client.Dispatch("SAPI.SpVoice")
                self._is_speaking = True
                engine.Speak(text, 1 | 3)  # Blocking
                self._is_speaking = False
            except Exception as e:
                logger.debug(f"[SAPI] Queue speak error: {e}")
                self._is_speaking = False

    def stop(self):
        """Stop any current speech."""
        try:
            engine = self._get_engine()
            engine.Speak("", 3)  # Purge
            self._is_speaking = False
        except Exception:
            pass

    def speak_async(self, text: str):
        """Queue text for non-blocking speech."""
        return self.speak(text, blocking=False)

    @property
    def is_ready(self) -> bool:
        return self._check_availability()

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def shutdown(self):
        """Stop the speaker thread cleanly."""
        self._running = False
        self.stop()


# Singleton
_sapi_tts: SAPITTS | None = None


def get_sapi_tts() -> SAPITTS:
    """Get the global SAPI TTS instance."""
    global _sapi_tts
    if _sapi_tts is None:
        _sapi_tts = SAPITTS()
    return _sapi_tts
