"""
screen_monitor.py - JARVIS's eyes. Captures screen and asks Gemini what it sees.
Uses Gemini vision API (free tier) + MSS for screen capture. CPU-only.
"""
import base64
import io
import logging
from typing import Literal

logger = logging.getLogger(__name__)


# ── Screen singleton ─────────────────────────────────────────────────────────

_screen_instance = None


def get_screen_monitor():
    """Get or create the global screen monitor instance."""
    global _screen_instance
    if _screen_instance is None:
        _screen_instance = ScreenIntelligence()
    return _screen_instance


class ScreenIntelligence:
    """
    JARVIS sees what you see.
    Uses MSS for capture + Gemini free vision API for understanding. No GPU needed.
    """

    def __init__(self, gemini_client=None):
        self._gemini = gemini_client
        self._sct = None
        self._ocr_reader = None

    def _get_sct(self):
        """Lazy-load mss screen capture."""
        if self._sct is None:
            try:
                import mss
                self._sct = mss.mss()
            except ImportError:
                logger.warning("[Screen] mss not installed. Run: pip install mss")
        return self._sct

    def capture_screen(self) -> bytes | None:
        """Capture full screen as PNG bytes."""
        sct = self._get_sct()
        if not sct:
            return None
        try:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            return screenshot.rgb
        except Exception as e:
            logger.error(f"[Screen] Capture failed: {e}")
            return None

    def capture_to_base64(self, quality: int = 80) -> tuple[bytes, int, int] | None:
        """Capture screen and return as JPEG base64 with dimensions."""
        sct = self._get_sct()
        if not sct:
            return None
        try:
            from PIL import Image
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb, "raw", "BGRX")
            w, h = img.size
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            return buffer.getvalue(), w, h
        except ImportError as e:
            logger.warning(f"[Screen] Pillow needed: {e}")
            return None
        except Exception as e:
            logger.error(f"[Screen] Capture failed: {e}")
            return None

    def describe_screen(self, question: str | None = None) -> str:
        """
        Ask Gemini what it sees on screen. Uses the free vision API.
        Example: "What error message is on screen?" "What app am I using?"
        """
        if not self._gemini:
            return "Gemini not configured."

        data = self.capture_to_base64()
        if not data:
            return "Screen capture unavailable."

        img_bytes, w, h = data
        img_base64 = base64.b64encode(img_bytes).decode()

        prompt = question or (
            "Describe what's on this screen in detail. "
            "What app is open? What is the user working on? "
            "Are there any error messages or important notifications? "
            "Be specific about text you can read."
        )

        try:
            response = self._gemini.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[prompt, img_base64]
            )
            return response.text if hasattr(response, "text") else str(response)
        except Exception as e:
            logger.error(f"[Screen] Gemini vision failed: {e}")
            return "Screen analysis unavailable."

    def read_screen_text(self) -> str:
        """Extract all text from screen using EasyOCR (CPU-only)."""
        try:
            if self._ocr_reader is None:
                import easyocr
                self._ocr_reader = easyocr.Reader(["en"], gpu=False)

            data = self.capture_to_base64()
            if not data:
                return ""
            img_bytes, w, h = data

            from PIL import Image
            import numpy as np
            img = Image.frombytes("RGB", (w, h), img_bytes, "raw", "BGRX")
            results = self._ocr_reader.readtext(np.array(img))
            text = " ".join([r[1] for r in results if r[2] > 0.3])
            return text
        except ImportError:
            logger.warning("[Screen] EasyOCR not installed. Run: pip install easyocr")
            return ""
        except Exception as e:
            logger.debug(f"[Screen] OCR failed: {e}")
            return ""

    def get_active_window_title(self) -> str:
        """Get the title of the currently focused window via Windows API."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return "No active window"
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            return buff.value or "Unknown"
        except Exception as e:
            logger.debug(f"[Screen] Window title failed: {e}")
            return "Unknown"

    def take_screenshot(self, path: str = "screenshots") -> str | None:
        """Save screenshot to file."""
        try:
            import os
            from datetime import datetime
            sct = self._get_sct()
            if not sct:
                return None
            os.makedirs(path, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(path, f"screenshot_{ts}.png")
            monitor = sct.monitors[1]
            sct.shot(output=out_path)
            return out_path
        except Exception as e:
            logger.error(f"[Screen] Screenshot save failed: {e}")
            return None
