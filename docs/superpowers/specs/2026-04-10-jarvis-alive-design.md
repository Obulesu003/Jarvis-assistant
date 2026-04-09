# JARVIS Alive — Making MARK-XXXV Feel Like a Real Assistant

**Date:** 2026-04-10
**Status:** Approved
**Goal:** Make JARVIS feel alive — proactive, interruptible, memory-aware, visually present.

---

## Overview

Five interconnected improvements that transform JARVIS from a reactive voice tool into a living presence:

1. **Proactive Conversations** — JARVIS volunteers information without being asked
2. **Interruption Handling** — Real back-and-forth, stop mid-speech
3. **Memory Intelligence Bridge** — JARVIS uses what it knows about you
4. **Visual Presence** — HUD breathes with live state animations
5. **Systematic Implementation** — Phased execution plan

---

## Architecture — Conversation Context Engine

Central to all five features is the `ConversationContextEngine`: a continuously running singleton that tracks conversational state across turns, enabling interruption, follow-up, and proactive volunteering.

```
┌──────────────────────────────────────────────────────────────┐
│  CONVERSATION CONTEXT ENGINE                                 │
│  Tracks: current goal, pending confirmations, idle time,    │
│  last topic, turn state (who speaks next)                   │
│  Lives across: tool executions, interrupts, pauses            │
└──────────────────────────────────────────────────────────────┘
         │
         ├── Interruption Handler ←── User cuts in at any time
         ├── Proactive Volunteer    ←── JARVIS speaks without being asked
         ├── Memory Bridge         ←── Facts from 4-layer mem → orchestrator
         ├── Visual State Machine  ←── HUD reacts to JARVIS internal state
         └── Turn Tracker          ←── Whose turn is it?
```

---

## Feature 1 — Proactive Conversations

### Problem
JARVIS only reacts. Real JARVIS volunteers: *"Sir, your 3pm meeting was moved."*

### Solution
`ConversationContextEngine` runs in the proactive monitor loop. It decides when to volunteer based on:
- **Idle time**: 5+ minutes since last interaction
- **State changes**: New email, calendar change, weather shift
- **User patterns**: Active at typical times
- **Memory triggers**: JARVIS recalls relevant past work

### Implementation

```python
# core/conversation_context.py

import time
import logging
from typing import TYPE_CHECKING
from collections import deque

if TYPE_CHECKING:
    from memory.j_memory import JARVISMemory

logger = logging.getLogger(__name__)


class ConversationContextEngine:
    """
    Tracks JARVIS's conversational state across turns.
    Enables: follow-up suggestions, interruption, proactive volunteering.
    """

    def __init__(self):
        self.current_goal: str | None = None        # "sending email to John"
        self.pending_confirmation: list[str] = []     # tool results awaiting user OK
        self.interrupted: bool = False                # user cut JARVIS off
        self.interrupted_text: str = ""              # what JARVIS was saying
        self.idle_since: float = time.time()        # last interaction timestamp
        self.interaction_count: int = 0              # total turns this session
        self.last_topic: str | None = None          # what we were discussing
        self.last_volunteer_at: float = 0.0         # last proactive speak time
        self._username: str = "Bobby"               # loaded from memory
        self._memory = None                         # injected after init

    def inject_memory(self, memory: "JARVISMemory"):
        self._memory = memory

    # ── Turn Tracking ──────────────────────────────────────────────────────────

    def on_user_turn(self, text: str):
        """Called after every user input."""
        self.idle_since = time.time()
        self.interaction_count += 1
        self.last_topic = self._extract_topic(text)

    def on_jarvis_turn(self, text: str, tools_used: list[str]):
        """Called after every JARVIS response."""
        self.idle_since = time.time()
        self.interrupted = False

        if tools_used:
            self.current_goal = self._describe_goal(tools_used)
        else:
            self.current_goal = None

    def on_interruption(self, jarvis_in_progress: str):
        """User spoke while JARVIS was mid-sentence."""
        self.interrupted = True
        self.interrupted_text = jarvis_in_progress
        self.idle_since = time.time()

    def get_interrupted_text(self) -> str:
        """Returns what JARVIS was saying when interrupted."""
        return self.interrupted_text

    def clear_interrupted(self):
        self.interrupted = False
        self.interrupted_text = ""

    # ── Proactive Volunteering ─────────────────────────────────────────────────

    def should_volunteer(self) -> bool:
        """JARVIS proactively speaks if conditions are met."""
        idle_minutes = (time.time() - self.idle_since) / 60

        # Too soon after last interaction
        if idle_minutes < 5:
            return False

        # Already volunteered recently (10 min cooldown)
        if time.time() - self.last_volunteer_at < 600:
            return False

        # Significant state change overrides idle threshold
        if self._significant_change_detected():
            return True

        # Check if user is typically available right now
        if self._user_likely_available():
            return True

        return False

    def volunteer_topic(self) -> str | None:
        """Decide what JARVIS should volunteer about. Priority order."""
        checks = [
            (self._check_new_emails, "unread_email"),
            (self._upcoming_event, "calendar"),
            (self._memory_recall_suggestion, "memory"),
            (self._system_health_check, "system"),
        ]

        for check_func, topic in checks:
            result = check_func()
            if result:
                self.last_volunteer_at = time.time()
                return result

        return None

    def _check_new_emails(self) -> str | None:
        try:
            adapter = __import__(
                "integrations.outlook.outlook_native_adapter",
                fromlist=["OutlookNativeAdapter"]
            ).OutlookNativeAdapter()
            count = adapter.execute_action("get_unread_count", {}).get("unread", 0)
            if count > 0:
                return f"Sir, you have {count} unread email{'s' if count > 1 else ''}."
        except Exception:
            pass
        return None

    def _upcoming_event(self) -> str | None:
        try:
            from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
            adapter = OutlookNativeAdapter()
            events = adapter.execute_action("list_calendar_events", {"days": 1})
            if events and events.get("events"):
                next_event = events["events"][0]
                title = next_event.get("subject", next_event.get("title", "Event"))
                start = next_event.get("start", "")
                return f"Next up: {title} at {start}."
        except Exception:
            pass
        return None

    def _memory_recall_suggestion(self) -> str | None:
        """Suggest continuing past work based on memory."""
        if not self._memory:
            return None
        try:
            recent = self._memory.get_recent_topic()
            if recent:
                return f"Sir, you were working on {recent}. Shall I pick up where we left off?"
        except Exception:
            pass
        return None

    def _system_health_check(self) -> str | None:
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery and battery.percent < 15 and not battery.power_plugged:
                return "Battery critically low at {} percent, sir. I recommend plugging in.".format(
                    battery.percent
                )
        except Exception:
            pass
        return None

    def _significant_change_detected(self) -> bool:
        # TODO: Track previous state and compare
        return False

    def _user_likely_available(self) -> bool:
        # TODO: Learn user's active hours from memory
        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_topic(self, text: str) -> str:
        """Simple topic extraction from user text."""
        words = text.lower().split()
        significant = [w for w in words if len(w) > 4][:3]
        return " ".join(significant) if significant else text[:30]

    def _describe_goal(self, tools_used: list[str]) -> str:
        goal_map = {
            "email": "composing an email",
            "calendar": "checking calendar",
            "weather": "checking weather",
            "search": "searching the web",
            "reminder": "setting a reminder",
            "whatsapp": "sending a WhatsApp message",
        }
        for tool in tools_used:
            for key, desc in goal_map.items():
                if key in tool.lower():
                    return desc
        return f"working on: {tools_used[0] if tools_used else 'task'}"
```

---

## Feature 2 — Interruption Handling

### Problem
Current cooldown is time-based. User can't cut JARVIS off naturally.

### Solution
**Turn-based model**: JARVIS and user take turns. If user speaks during JARVIS's turn, JARVIS stops immediately and processes the new input. After responding, JARVIS can offer to resume.

### Changes

#### 1. `core/tts_engine.py` — Add stop capability

```python
def stop_async(self):
    """Stop current speech immediately."""
    self.is_speaking = False
    if self._process and self._process.poll() is None:
        self._process.terminate()
        try:
            self._process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            self._process.kill()
```

#### 2. `main.py` JarvisLive — Turn-based model

```python
class JarvisLive:
    # Replace _speech_cooldown with ConversationTurn:

    def __init__(self, ui: JarvisUI):
        # ... existing init ...
        self._turn_state = "listening"  # listening | jarvis_speaking | interrupted

    def _on_audio_level(self, level: float):
        """Called by audio pipeline with audio levels."""
        if self._turn_state == "jarvis_speaking" and level > 0.1:
            # VAD detected speech while JARVIS is speaking → interruption
            self._handle_interruption()

    def _handle_interruption(self):
        """User spoke while JARVIS was mid-sentence."""
        # 1. Stop JARVIS's speech immediately
        if self._local_tts:
            self._local_tts.stop_async()

        # 2. Record what JARVIS was saying
        in_progress = getattr(self, "_current_speech_text", "")
        self._ctx.on_interruption(in_progress)

        # 3. Don't process the interrupting audio through Gemini
        # The interrupting speech is already being processed via the live session
        logger.info("[TurnModel] User interrupted JARVIS mid-sentence")

    def _on_turn_complete(self, user_text: str, jarvis_text: str):
        """Called when a turn completes."""
        if self._ctx.interrupted:
            # JARVIS was interrupted — offer to resume after response
            interrupted = self._ctx.get_interrupted_text()
            self._ctx.clear_interrupted()
            # After the next response is done, resume logic runs
            self._offer_resume(interrupted)
        else:
            self._ctx.on_user_turn(user_text)
            self._ctx.on_jarvis_turn(jarvis_text, self._last_tools_used)

    def _offer_resume(self, interrupted_text: str):
        """After handling interruption, offer to continue."""
        if len(interrupted_text) < 20:
            return  # Too short to resume meaningfully
        resume_prompt = "Shall I continue where I left off?"
        self._ctx.current_goal = f"resuming: {interrupted_text[:50]}"
        # The resume is optional — don't force it
        self._ctx.pending_confirmation.append(("resume", resume_prompt))
```

---

## Feature 3 — Memory Intelligence Bridge

### Problem
Memory extraction runs but JARVIS doesn't deeply use the 4-layer memory during reasoning.

### Solution
`MemoryBridge` class wires memory into every Gemini request and adds session review.

```python
# core/memory_bridge.py

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.j_memory import JARVISMemory

logger = logging.getLogger(__name__)


class MemoryBridge:
    """
    Wires JARVIS's 4-layer memory into the orchestrator context.
    Called before every Gemini request.
    """

    def __init__(self, memory: "JARVISMemory"):
        self._memory = memory
        self._session_start = time.time()
        self._session_facts_learned: list = []

    # ── Context Injection ───────────────────────────────────────────────────

    def build_context(self, current_request: str) -> str:
        """
        Build memory-aware context string for Gemini.
        Called before every Gemini call in the orchestrator.
        """
        parts = []

        # 1. Recent facts about the user (semantic layer)
        facts = self._memory.semantic.recall(f"facts about {self._memory._username}")
        if facts:
            parts.append(f"WHAT I KNOW ABOUT YOU: {facts}")

        # 2. Current project context (procedural layer)
        active = self._memory.procedural.get_active()
        if active:
            parts.append(f"ACTIVE PROJECTS: {active}")

        # 3. Last conversation topic (episodic layer)
        recent = self._memory.episodic.get_last_topic()
        if recent and recent != current_request:
            parts.append(f"PREVIOUS TOPIC: {recent}")

        # 4. User preferences relevant to this request
        prefs = self._memory.semantic.get_preferences_for(current_request)
        if prefs:
            parts.append(f"USER PREFERENCES: {prefs}")

        return "\n\n".join(parts) if parts else ""

    # ── Session Review ─────────────────────────────────────────────────────

    def on_session_end(self):
        """
        Called when JARVIS shuts down.
        JARVIS reviews what it learned this session.
        """
        session_memories = self._memory.get_session_memories(
            since=self._session_start
        )
        if not session_memories:
            return

        session_minutes = (time.time() - self._session_start) / 60

        review_parts = [
            f"Session lasted {int(session_minutes)} minutes.",
            f"Learned {len(session_memories)} new facts.",
        ]

        # Ask Gemini to synthesize (lightweight call)
        try:
            synthesis = self._synthesize_session_review(session_memories)
            if synthesis:
                review_parts.append(f"Key insight: {synthesis}")
        except Exception as e:
            logger.debug(f"[MemoryBridge] Session review synthesis failed: {e}")

        review = " ".join(review_parts)
        self._memory.remember("session_review", review)
        logger.info(f"[MemoryBridge] Session review: {review}")

    def _synthesize_session_review(
        self, memories: list[dict]
    ) -> str | None:
        """Use Gemini to synthesize a session review."""
        try:
            from google.genai import Client
            client = Client(api_key=self._get_gemini_key())

            memory_text = "\n".join([
                f"- {m.get('content', '')}" for m in memories[:10]
            ])

            prompt = f"""Summarize what JARVIS learned about the user in this session.
            Focus on: new facts discovered, ongoing projects mentioned,
            preferences revealed, and anything actionable.

            Memories:\n{memory_text}

            Respond with 1-2 sentences max. Be specific. No preamble."""

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return response.text.strip()
        except Exception:
            return None

    def _get_gemini_key(self) -> str:
        try:
            from core.api_key_manager import get_gemini_key
            return get_gemini_key() or ""
        except Exception:
            return ""

    # ── Track Learned Facts ───────────────────────────────────────────────

    def on_fact_learned(self, fact: dict):
        """Track facts learned during this session."""
        self._session_facts_learned.append(fact)
```

#### Integration into LLM Orchestrator

In `integrations/core/llm_orchestrator.py`, before calling Gemini:

```python
# In _plan_steps_llm(), inject memory context:
memory_bridge = self._get_memory_bridge()
memory_context = memory_bridge.build_context(request)
if memory_context:
    prompt = f"{memory_context}\n\n---\n\n{prompt}"
```

---

## Feature 4 — Visual Presence

### Problem
HUD is mostly static. JARVIS should feel alive through animation.

### Solution
`JARVISVisualState` enum drives HUD animation. VisualPresenceEngine maps internal states to HUD updates.

```python
# core/visual_presence.py

import time
from collections import deque
from enum import Enum

import logging

logger = logging.getLogger(__name__)


class JARVISVisualState(Enum):
    IDLE          = "idle"
    LISTENING     = "listening"
    THINKING      = "thinking"
    SPEAKING      = "speaking"
    VOLUNTEERING  = "volunteering"
    INTERRUPTED  = "interrupted"


class VisualPresenceEngine:
    """
    Drives the cinematic HUD's visual state.
    Maps JARVIS's internal state → HUD animation.
    """

    # State colors (JARVIS blue palette)
    STATE_COLORS = {
        JARVISVisualState.IDLE:         (60, 60, 60),     # Dim gray
        JARVISVisualState.LISTENING:    (0, 180, 255),    # Bright blue
        JARVISVisualState.THINKING:     (255, 200, 0),   # Amber
        JARVISVisualState.SPEAKING:     (0, 255, 180),    # Green
        JARVISVisualState.VOLUNTEERING: (255, 180, 0),   # Gold
        JARVISVisualState.INTERRUPTED: (255, 100, 100),  # Red
    }

    def __init__(self, hud):
        self._hud = hud
        self._state = JARVISVisualState.IDLE
        self._waveform_data: deque = deque(maxlen=64)
        self._idle_pulse = 0.0

    def set_state(self, state: JARVISVisualState):
        """Update HUD visual state."""
        self._state = state
        color = self.STATE_COLORS[state]
        self._hud.set_status_color(color)
        self._hud.set_state_label(state.value.upper())

        # Trigger state-specific behavior
        if state == JARVISVisualState.VOLUNTEERING:
            self._hud.set_volunteer_mode(True)
        else:
            self._hud.set_volunteer_mode(False)

    def update_waveform(self, audio_level: float):
        """Receive audio levels from audio pipeline for visualization."""
        self._waveform_data.append(audio_level)

        # Only show waveform when actively listening
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
            # Sinusoidal opacity: breathe effect
            alpha = int(80 + 40 * (0.5 + 0.5 * __import__("math").sin(
                self._idle_pulse * 2 * __import__("math").pi
            ))
            self._hud.set_jarcircle_opacity(alpha)
```

### HUD Animation Updates

In `core/hud.py`, add these new methods to the DearPyGui HUD:

```python
def set_status_color(self, rgb: tuple[int, int, int]):
    """Change the JARVIS status circle color."""
    # Update circle color via dpg
    pass

def set_volunteer_mode(self, enabled: bool):
    """Switch to gold volunteer color scheme."""
    color = (255, 180, 0) if enabled else self._current_state_color
    # Update all text elements
    pass

def show_activity(self, text: str):
    """Briefly flash a tool activity indicator."""
    # Show text for 2 seconds in activity bar
    pass

def flash_success(self):
    """Brief green flash on successful tool completion."""
    # Quick green pulse
    pass

def show_preview(self, text: str, duration: float):
    """Show text before JARVIS speaks it proactively."""
    # Overlay preview text, fade out after duration
    pass

def set_jarcircle_opacity(self, alpha: int):
    """Update the JARVIS circle's opacity for breathing effect."""
    pass
```

---

## Feature 5 — Systematic Implementation Plan

### Phase 1: ConversationContextEngine + Turn Tracker
**Time:** 1-2 hrs | **Files:** `core/conversation_context.py`, `main.py`

- Create `ConversationContextEngine` singleton
- Inject into `JarvisLive.__init__`
- Wire `on_user_turn` / `on_jarvis_turn` in receive loop
- Add `should_volunteer()` and `volunteer_topic()` logic

### Phase 2: MemoryBridge
**Time:** 1 hr | **Files:** `core/memory_bridge.py`, `integrations/core/llm_orchestrator.py`

- Create `MemoryBridge` class
- Add `build_context()` for orchestrator context injection
- Add `on_session_end()` for shutdown review
- Wire into `LLMOrchestrator._plan_steps_llm()`
- Update `JARVISMemory` if needed to expose new methods

### Phase 3: Interruption Handling
**Time:** 1-2 hrs | **Files:** `core/tts_engine.py`, `main.py`, `core/audio_pipeline.py`

- Add `stop_async()` to `TTSEngine`
- Wire VAD detection into JarvisLive during speaking state
- Add `_handle_interruption()` and `_offer_resume()`
- Update `_on_turn_complete()` with turn model

### Phase 4: VisualPresenceEngine + HUD Animations
**Time:** 2 hrs | **Files:** `core/visual_presence.py`, `core/hud.py`

- Create `JARVISVisualState` enum
- Create `VisualPresenceEngine`
- Add animation methods to `JARVIS_HUD` (DearPyGui)
- Wire into JarvisLive state changes
- Add waveform visualization (listen/speak states)

### Phase 5: Proactive Volunteering
**Time:** 1-2 hrs | **Files:** `core/proactive_monitor.py`, `core/conversation_context.py`

- Wire `ConversationContextEngine.should_volunteer()` into proactive monitor
- Add `_check_new_emails()`, `_upcoming_event()`, `_memory_recall_suggestion()`
- Implement `show_volunteer_preview()` before speaking
- Add 10-minute cooldown between volunteers

### Phase 6: Session Review + Polish
**Time:** 1 hr | **Files:** `main.py`, `core/memory_bridge.py`

- Wire `MemoryBridge.on_session_end()` into JarvisLive shutdown
- Add JARVIS settings UI (optional, if time permits)
- End-to-end test all five features together

---

## Dependencies

| New Dependency | Purpose | Size |
|---|---|---|
| None | All features use existing libraries | 0 MB |

Existing libraries used: `dearpygui`, `numpy`, `sounddevice`, `psutil`, `chromadb`, `networkx`, `google-genai`.

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| DearPyGui waveform causes performance issues | Low | Test with real audio; fallback to simple bars |
| Proactive volunteering is annoying | Medium | Strong cooldown; user-configurable frequency |
| Interruption false positives (JARVIS stops for background noise) | Medium | VAD threshold tuning required; Silero VAD should handle this |
| Memory injection makes Gemini context too long | Low | Memory context capped at 500 tokens |

---

## Success Criteria

- [ ] JARVIS volunteers at least one piece of information per active session without being asked
- [ ] User can interrupt JARVIS mid-sentence with a single word
- [ ] JARVIS uses a remembered fact about the user in at least one response per session
- [ ] HUD shows distinct visual states for each interaction mode
- [ ] All five features work together without conflicts
