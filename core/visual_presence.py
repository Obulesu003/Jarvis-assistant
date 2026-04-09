"""VisualPresenceEngine — drives the cinematic HUD's visual state."""
import math
from collections import deque
from enum import Enum
from typing import Deque


class JARVISVisualState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    VOLUNTEERING = "volunteering"
    INTERRUPTED = "interrupted"


class VisualPresenceEngine:
    """
    Drives the cinematic HUD's visual state.
    Maps JARVIS's internal state → HUD animation.
    """

    STATE_COLORS = {
        JARVISVisualState.IDLE: (60, 60, 60),
        JARVISVisualState.LISTENING: (0, 180, 255),
        JARVISVisualState.THINKING: (255, 200, 0),
        JARVISVisualState.SPEAKING: (0, 255, 180),
        JARVISVisualState.VOLUNTEERING: (255, 180, 0),
        JARVISVisualState.INTERRUPTED: (255, 100, 100),
    }

    def __init__(self, hud):
        self._hud = hud
        self._state = JARVISVisualState.IDLE
        self._waveform_data: Deque[float] = deque(maxlen=64)
        self._idle_pulse = 0.0

    def set_state(self, state: JARVISVisualState):
        """Update HUD visual state."""
        self._state = state
        color = self.STATE_COLORS[state]
        self._hud.set_status_color(color)
        self._hud.set_state_label(state.value.upper())

        if state == JARVISVisualState.VOLUNTEERING:
            self._hud.set_volunteer_mode(True)
        else:
            self._hud.set_volunteer_mode(False)

    def update_waveform(self, audio_level: float):
        """Receive audio levels from audio pipeline for visualization."""
        self._waveform_data.append(audio_level)

        if self._state == JARVISVisualState.LISTENING:
            self._hud.update_waveform(list(self._waveform_data))

    def on_tool_start(self, tool_name: str):
        """HUD briefly shows which tool JARVIS is using."""
        self._hud.show_activity(tool_name)

    def on_tool_complete(self):
        """Brief flash on tool completion."""
        self._hud.flash_success()

    def on_interrupted(self, interrupted_text: str):
        """HUD reacts to user interruption."""
        self.set_state(JARVISVisualState.INTERRUPTED)
        self._hud.show_response(f"[interrupted] {interrupted_text[:60]}...")

    def show_volunteer_preview(self, text: str):
        """Before proactively speaking, briefly show the text on HUD."""
        self._hud.show_preview(text, duration=3.0)

    def update_idle_pulse(self):
        """Called every ~16ms. Drives the idle breathing animation."""
        self._idle_pulse = (self._idle_pulse + 0.02) % 1.0
        if self._state == JARVISVisualState.IDLE:
            alpha = int(80 + 40 * (0.5 + 0.5 * math.sin(
                self._idle_pulse * 2 * math.pi
            )))
            self._hud.set_jarcircle_opacity(alpha)
