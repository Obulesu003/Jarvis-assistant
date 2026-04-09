"""
screen_action.py - Action function for screen intelligence.
Provides: screenshot, screen analysis, active window, OCR text extraction.
"""
import logging

logger = logging.getLogger(__name__)

_screen = None


def get_screen():
    """Get or create the global screen intelligence instance."""
    global _screen
    if _screen is None:
        from core.screen_monitor import ScreenIntelligence
        # Import the Gemini client from the orchestrator
        try:
            from integrations.core.llm_orchestrator import get_client
            gemini = get_client()
        except Exception:
            gemini = None
        _screen = ScreenIntelligence(gemini_client=gemini)
    return _screen


def screen_action(params: dict, player=None):
    """Action to interact with screen intelligence."""
    cmd = params.get("command", "capture")

    s = get_screen()

    if cmd == "capture":
        path = s.take_screenshot(params.get("path", "screenshots"))
        return {"status": "captured", "path": path}

    elif cmd == "describe":
        question = params.get("question", None)
        description = s.describe_screen(question)
        return {"status": "described", "description": description}

    elif cmd == "text":
        text = s.read_screen_text()
        return {"status": "text", "text": text}

    elif cmd == "window":
        title = s.get_active_window_title()
        return {"status": "window", "title": title}

    elif cmd == "analyze":
        question = params.get("question", "What app is open and what is the user doing?")
        description = s.describe_screen(question)
        return {"status": "analyzed", "description": description}

    else:
        return {"status": "error", "message": f"Unknown command: {cmd}"}
