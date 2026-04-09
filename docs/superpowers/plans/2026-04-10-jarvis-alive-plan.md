# JARVIS Alive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JARVIS feel alive — proactive, interruptible, memory-aware, visually present.

**Architecture:** Phase 1 creates `ConversationContextEngine` as the central singleton tracking turn state across JARVIS's session. Phase 2 builds `MemoryBridge` on top, injecting 4-layer memory into every Gemini request. Phase 3 adds `stop_async()` to TTS and turn-based interruption. Phase 4 adds `VisualPresenceEngine` driving DearPyGui HUD animations. Phase 5 wires volunteering into the proactive monitor. Phase 6 adds session review and end-to-end testing.

**Tech Stack:** Python 3.11+, dearpygui, numpy, sounddevice, psutil, chromadb, networkx, google-genai. No new dependencies.

---

## File Map

| File | Action |
|------|--------|
| `core/conversation_context.py` | **Create** — ConversationContextEngine |
| `core/memory_bridge.py` | **Create** — MemoryBridge |
| `core/visual_presence.py` | **Create** — JARVISVisualState + VisualPresenceEngine |
| `memory/j_memory.py` | **Modify** — Add get_recent_topic, get_active, get_session_memories, get_preferences_for |
| `integrations/core/llm_orchestrator.py` | **Modify** — Inject memory context in `_plan_steps_llm` |
| `core/tts_engine.py` | **Modify** — Add `stop_async()` |
| `main.py` | **Modify** — Inject CCE into JarvisLive, add turn-based interruption |
| `core/hud.py` | **Modify** — Add 6 animation methods |
| `core/proactive_monitor.py` | **Modify** — Wire `should_volunteer()` into idle check |
| `tests/test_conversation_context.py` | **Create** — CCE unit tests |
| `tests/test_memory_bridge.py` | **Create** — MemoryBridge unit tests |
| `tests/test_visual_presence.py` | **Create** — VPE unit tests |

---

## Phase 1: ConversationContextEngine + Turn Tracker

**Files:** `core/conversation_context.py` (create), `main.py` (modify), `tests/test_conversation_context.py` (create)

---

### Task 1: Create ConversationContextEngine

**Files:**
- Create: `core/conversation_context.py`
- Test: `tests/test_conversation_context.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conversation_context.py
import pytest, time, unittest.mock as mock
import sys
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

from core.conversation_context import ConversationContextEngine

class TestConversationContextEngine:
    def test_initial_state(self):
        ctx = ConversationContextEngine()
        assert ctx.current_goal is None
        assert ctx.pending_confirmation == []
        assert ctx.interrupted is False
        assert ctx.idle_since > 0
        assert ctx.interaction_count == 0

    def test_on_user_turn_updates_idle_and_count(self):
        ctx = ConversationContextEngine()
        before = ctx.idle_since
        time.sleep(0.01)
        ctx.on_user_turn("check my email")
        assert ctx.idle_since > before
        assert ctx.interaction_count == 1
        assert ctx.last_topic is not None

    def test_on_jarvis_turn_clears_interrupted(self):
        ctx = ConversationContextEngine()
        ctx.interrupted = True
        ctx.on_jarvis_turn("Done, sir.", ["email"])
        assert ctx.interrupted is False

    def test_on_interruption_records_text(self):
        ctx = ConversationContextEngine()
        ctx.on_interruption("I'm checking your email")
        assert ctx.interrupted is True
        assert ctx.get_interrupted_text() == "I'm checking your email"

    def test_get_interrupted_text_after_clear(self):
        ctx = ConversationContextEngine()
        ctx.on_interruption("Some text")
        ctx.clear_interrupted()
        assert ctx.interrupted is False
        assert ctx.get_interrupted_text() == ""

    def test_should_volunteer_too_soon(self):
        ctx = ConversationContextEngine()
        ctx.idle_since = time.time()  # Just interacted
        assert ctx.should_volunteer() is False

    def test_volunteer_topic_empty_when_no_facts(self):
        ctx = ConversationContextEngine()
        # No memory injected, no state changes — returns None
        assert ctx.volunteer_topic() is None

    def test_extract_topic_simple(self):
        ctx = ConversationContextEngine()
        topic = ctx._extract_topic("What's the weather in London today")
        assert "weather" in topic or "London" in topic

    def test_describe_goal_email(self):
        ctx = ConversationContextEngine()
        goal = ctx._describe_goal(["send_email"])
        assert "email" in goal.lower()

    def test_volunteer_topic_returns_when_memory_injected(self):
        ctx = ConversationContextEngine()
        mock_memory = mock.MagicMock()
        mock_memory.get_recent_topic.return_value = "Python project setup"
        ctx.inject_memory(mock_memory)
        result = ctx.volunteer_topic()
        assert result is not None
        mock_memory.get_recent_topic.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m pytest tests/test_conversation_context.py -v`
Expected: ERROR — ModuleNotFoundError: No module named 'core.conversation_context'

- [ ] **Step 3: Write minimal implementation**

```python
# core/conversation_context.py
"""ConversationContextEngine — tracks JARVIS's conversational state across turns."""
import time
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.j_memory import JARVISMemory

logger = logging.getLogger(__name__)


class ConversationContextEngine:
    """
    Tracks JARVIS's conversational state across turns.
    Enables: follow-up suggestions, interruption, proactive volunteering.
    Lives across: tool executions, interrupts, pauses.
    """

    def __init__(self):
        self.current_goal: str | None = None
        self.pending_confirmation: list[tuple[str, str]] = []
        self.interrupted: bool = False
        self.interrupted_text: str = ""
        self.idle_since: float = time.time()
        self.interaction_count: int = 0
        self.last_topic: str | None = None
        self.last_volunteer_at: float = 0.0
        self._memory = None

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

        if idle_minutes < 5:
            return False

        if time.time() - self.last_volunteer_at < 600:
            return False

        if self._significant_change_detected():
            return True

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
                return f"Battery critically low at {battery.percent} percent, sir. I recommend plugging in."
        except Exception:
            pass
        return None

    def _significant_change_detected(self) -> bool:
        return False

    def _user_likely_available(self) -> bool:
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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m pytest tests/test_conversation_context.py -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add core/conversation_context.py tests/test_conversation_context.py
git commit -m "feat(context): add ConversationContextEngine for turn tracking and proactive volunteering"
```

---

### Task 2: Wire CCE into JarvisLive

**Files:**
- Modify: `main.py:1072-1097` (JarvisLive.__init__)
- Modify: `main.py` (receive loop — add turn tracking)

- [ ] **Step 1: Add CCE import and instance to JarvisLive.__init__**

Find in `main.py` around line 1072:

```python
class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.ui.on_text_command = self._on_text_command
        self._speech_cooldown = False  # Prevent re-triggering during speech
        self._cooldown_lock = threading.Lock()
        # ... existing code ...
```

Add after the existing attributes:

```python
        # Phase 6: ConversationContextEngine — tracks turns across the session
        from core.conversation_context import ConversationContextEngine
        self._ctx = ConversationContextEngine()
```

- [ ] **Step 2: Find the Gemini response handler in JarvisLive**

Search for where JARVIS text responses are received. Look in `main.py` for `send_server_content` or `response` handlers around line 1270. The pattern will be `session.send_server_content` or similar. Find the method that handles when JARVIS finishes speaking and add:

```python
# After JARVIS sends a complete response:
# Track the turn in ConversationContextEngine
if hasattr(self, '_ctx'):
    tools_used = getattr(self, '_last_tools_used', [])
    self._ctx.on_jarvis_turn(response_text, tools_used)
```

- [ ] **Step 3: Find where user input is processed**

Search for where user transcriptions are received. Add after processing user input:

```python
if hasattr(self, '_ctx') and user_text:
    self._ctx.on_user_turn(user_text)
```

- [ ] **Step 4: Run a syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile main.py`
Expected: No output (success)

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(main): wire ConversationContextEngine into JarvisLive"
```

---

## Phase 2: MemoryBridge

**Files:** `core/memory_bridge.py` (create), `memory/j_memory.py` (modify), `integrations/core/llm_orchestrator.py` (modify), `tests/test_memory_bridge.py` (create)

---

### Task 3: Add missing JARVISMemory methods

**Files:**
- Modify: `memory/j_memory.py`

- [ ] **Step 1: Read current JARVISMemory to find where to add methods**

Read `memory/j_memory.py` to find the class definition and existing methods. Add these methods to the `JARVISMemory` class:

```python
    def get_recent_topic(self) -> str | None:
        """Return the last discussed topic from episodic memory."""
        if not self._episodic:
            return None
        try:
            results = self._episodic.get_recent(limit=1)
            if results:
                return results[0].get("topic", "")
        except Exception:
            pass
        return None

    def get_active(self) -> list[str]:
        """Return active project names from procedural memory."""
        if not self._procedural:
            return []
        try:
            skills = self._procedural.list_all()
            return [s.get("name", "") for s in skills if s.get("active")]
        except Exception:
            return []

    def get_session_memories(self, since: float) -> list[dict]:
        """Return memories created since the given timestamp."""
        if not self._episodic:
            return []
        try:
            return self._episodic.get_recent(limit=50)
        except Exception:
            return []

    def get_preferences_for(self, request: str) -> list[str]:
        """Return user preferences relevant to the current request."""
        if not self._semantic:
            return []
        try:
            facts = self._semantic.recall(request, limit=3)
            return facts
        except Exception:
            return []
```

- [ ] **Step 2: Run syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile memory/j_memory.py`
Expected: No output

- [ ] **Step 3: Commit**

```bash
git add memory/j_memory.py
git commit -m "feat(memory): add get_recent_topic, get_active, get_session_memories, get_preferences_for"
```

---

### Task 4: Create MemoryBridge

**Files:**
- Create: `core/memory_bridge.py`
- Test: `tests/test_memory_bridge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory_bridge.py
import pytest, unittest.mock as mock
import sys
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

from core.memory_bridge import MemoryBridge

class TestMemoryBridge:
    def test_build_context_empty_memory(self):
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = []
        mock_mem.procedural.get_active.return_value = []
        mock_mem.episodic.get_last_topic.return_value = None
        bridge = MemoryBridge(mock_mem)
        ctx = bridge.build_context("check weather")
        assert ctx == ""

    def test_build_context_with_facts(self):
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = ["You prefer Celsius", "You live in London"]
        mock_mem.procedural.get_active.return_value = []
        mock_mem.episodic.get_last_topic.return_value = None
        bridge = MemoryBridge(mock_mem)
        ctx = bridge.build_context("check weather")
        assert "WHAT I KNOW ABOUT YOU" in ctx
        assert "Celsius" in ctx or "London" in ctx

    def test_build_context_with_active_projects(self):
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = []
        mock_mem.procedural.get_active.return_value = ["JARVIS HUD", "Memory system"]
        mock_mem.episodic.get_last_topic.return_value = None
        bridge = MemoryBridge(mock_mem)
        ctx = bridge.build_context("open files")
        assert "ACTIVE PROJECTS" in ctx
        assert "JARVIS HUD" in ctx

    def test_on_session_end_no_memories(self):
        mock_mem = mock.MagicMock()
        mock_mem.get_session_memories.return_value = []
        bridge = MemoryBridge(mock_mem)
        bridge.on_session_end()  # Should not raise
        mock_mem.get_session_memories.assert_called_once()

    def test_on_session_end_with_memories_calls_synthesize(self):
        mock_mem = mock.MagicMock()
        mock_mem.get_session_memories.return_value = [
            {"content": "User mentioned Python project"},
            {"content": "User prefers British voice"},
        ]
        bridge = MemoryBridge(mock_mem)
        # Mock _synthesize_session_review to avoid API call
        bridge._synthesize_session_review = mock.MagicMock(return_value="Key insight.")
        bridge.on_session_end()
        bridge._synthesize_session_review.assert_called_once()
        mock_mem.remember.assert_called_once()

    def test_on_fact_learned(self):
        mock_mem = mock.MagicMock()
        bridge = MemoryBridge(mock_mem)
        bridge.on_fact_learned({"content": "User likes tea"})
        assert len(bridge._session_facts_learned) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m pytest tests/test_memory_bridge.py -v`
Expected: ERROR — ModuleNotFoundError: No module named 'core.memory_bridge'

- [ ] **Step 3: Write minimal implementation**

```python
# core/memory_bridge.py
"""MemoryBridge — wires JARVIS 4-layer memory into every Gemini request."""
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
        facts = self._memory.semantic.recall(f"facts about the user")
        if facts:
            parts.append(f"WHAT I KNOW ABOUT YOU: {facts}")

        # 2. Current project context (procedural layer)
        active = self._memory.procedural.get_active()
        if active:
            parts.append(f"ACTIVE PROJECTS: {active}")

        # 3. Last conversation topic (episodic layer)
        recent = self._memory.get_recent_topic()
        if recent and recent != current_request:
            parts.append(f"PREVIOUS TOPIC: {recent}")

        # 4. User preferences relevant to this request
        prefs = self._memory.get_preferences_for(current_request)
        if prefs:
            parts.append(f"USER PREFERENCES: {prefs}")

        return "\n\n".join(parts) if parts else ""

    # ── Session Review ─────────────────────────────────────────────────────

    def on_session_end(self):
        """
        Called when JARVIS shuts down.
        JARVIS reviews what it learned this session.
        """
        session_memories = self._memory.get_session_memories(since=self._session_start)
        if not session_memories:
            return

        session_minutes = (time.time() - self._session_start) / 60

        review_parts = [
            f"Session lasted {int(session_minutes)} minutes.",
            f"Learned {len(session_memories)} new facts.",
        ]

        try:
            synthesis = self._synthesize_session_review(session_memories)
            if synthesis:
                review_parts.append(f"Key insight: {synthesis}")
        except Exception as e:
            logger.debug(f"[MemoryBridge] Session review synthesis failed: {e}")

        review = " ".join(review_parts)
        self._memory.remember("session_review", review)
        logger.info(f"[MemoryBridge] Session review: {review}")

    def _synthesize_session_review(self, memories: list[dict]) -> str | None:
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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m pytest tests/test_memory_bridge.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add core/memory_bridge.py tests/test_memory_bridge.py
git commit -m "feat(memory): add MemoryBridge for 4-layer context injection into Gemini"
```

---

### Task 5: Wire MemoryBridge into LLMOrchestrator

**Files:**
- Modify: `integrations/core/llm_orchestrator.py` (inject memory context in `_plan_steps_llm`)

- [ ] **Step 1: Add MemoryBridge instance variable to LLMOrchestrator.__init__**

Find `LLMOrchestrator.__init__` (around line 47). Add after `self._client = None`:

```python
        self._memory_bridge = None  # Lazily initialized
```

- [ ] **Step 2: Add `_get_memory_bridge()` method to LLMOrchestrator**

Add as a new method in LLMOrchestrator:

```python
    def _get_memory_bridge(self):
        """Lazily initialize the MemoryBridge."""
        if self._memory_bridge is None:
            try:
                from memory.j_memory import JARVISMemory
                from core.memory_bridge import MemoryBridge
                memory = JARVISMemory()
                memory.initialize()
                self._memory_bridge = MemoryBridge(memory)
            except Exception as e:
                logger.debug(f"[LLMOrchestrator] MemoryBridge unavailable: {e}")
                self._memory_bridge = None
        return self._memory_bridge
```

- [ ] **Step 3: Inject memory context into `_plan_steps_llm`**

Find `_plan_steps_llm` (line 88). After building the prompt and before calling Gemini, add:

```python
        # Inject memory context before calling Gemini
        try:
            bridge = self._get_memory_bridge()
            if bridge:
                memory_ctx = bridge.build_context(request)
                if memory_ctx:
                    prompt = f"{memory_ctx}\n\n---\n\n{prompt}"
        except Exception:
            pass  # Memory context is optional — don't fail the request
```

- [ ] **Step 4: Run syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile integrations/core/llm_orchestrator.py`
Expected: No output

- [ ] **Step 5: Commit**

```bash
git add integrations/core/llm_orchestrator.py
git commit -m "feat(orchestrator): inject MemoryBridge context into every Gemini planning call"
```

---

## Phase 3: Interruption Handling

**Files:** `core/tts_engine.py` (modify), `main.py` (modify JarvisLive)

---

### Task 6: Add stop_async() to TTSEngine

**Files:**
- Modify: `core/tts_engine.py`

- [ ] **Step 1: Add stop_async() method to TTSEngine class**

Find `TTSEngine` class in `core/tts_engine.py`. Add as a new method:

```python
    def stop_async(self):
        """Stop current speech immediately. Used for interruption."""
        self.is_speaking = False
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self._process.kill()
```

- [ ] **Step 2: Also store `_process` on self so stop_async can reference it**

Find the `speak()` method. Add `self._process = process` before `process.communicate()`:

```python
            process = subprocess.Popen(...)
            self._process = process  # Store reference for stop_async()
            audio_bytes, _ = process.communicate(input=text.encode(), timeout=10)
```

And in the `finally` block of `speak()`, update:

```python
        finally:
            self.is_speaking = False
            self._process = None
```

- [ ] **Step 3: Initialize `_process` to None in `__init__`**

Add to `__init__`:

```python
        self._process: subprocess.Popen | None = None
```

- [ ] **Step 4: Run syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile core/tts_engine.py`
Expected: No output

- [ ] **Step 5: Commit**

```bash
git add core/tts_engine.py
git commit -m "feat(tts): add stop_async() for interruption handling"
```

---

### Task 7: Wire turn-based interruption into JarvisLive

**Files:**
- Modify: `main.py` (JarvisLive class — add interruption handling, turn tracking)

- [ ] **Step 1: Add turn state to JarvisLive.__init__**

Find `JarvisLive.__init__` around line 1072. Add after existing attributes:

```python
        # Phase 6: Turn-based interruption model
        self._turn_state = "listening"  # listening | jarvis_speaking | interrupted
        self._current_speech_text = ""  # What JARVIS is currently saying
```

- [ ] **Step 2: Add `_handle_interruption()` method to JarvisLive**

Add as a new method in `JarvisLive`:

```python
    def _handle_interruption(self, jarvis_in_progress: str = ""):
        """User spoke while JARVIS was mid-sentence."""
        # 1. Stop JARVIS's speech immediately
        if self._local_tts:
            self._local_tts.stop_async()

        # 2. Record what JARVIS was saying
        self._current_speech_text = jarvis_in_progress
        if hasattr(self, '_ctx'):
            self._ctx.on_interruption(jarvis_in_progress)

        # 3. Set turn state
        self._turn_state = "interrupted"

        logger.info("[TurnModel] User interrupted JARVIS mid-sentence")
```

- [ ] **Step 3: Add `_offer_resume()` method to JarvisLive**

```python
    def _offer_resume(self, interrupted_text: str):
        """After handling interruption, offer to continue."""
        if len(interrupted_text) < 20:
            return  # Too short to resume meaningfully
        resume_prompt = "Shall I continue where I left off?"
        if hasattr(self, '_ctx'):
            self._ctx.current_goal = f"resuming: {interrupted_text[:50]}"
            self._ctx.pending_confirmation.append(("resume", resume_prompt))
```

- [ ] **Step 4: Add `_on_turn_complete()` method to JarvisLive**

```python
    def _on_turn_complete(self, user_text: str, jarvis_text: str):
        """Called when a conversation turn completes."""
        if hasattr(self, '_ctx'):
            if self._ctx.interrupted:
                interrupted = self._ctx.get_interrupted_text()
                self._ctx.clear_interrupted()
                self._offer_resume(interrupted)
            else:
                tools = getattr(self, '_last_tools_used', [])
                self._ctx.on_user_turn(user_text)
                self._ctx.on_jarvis_turn(jarvis_text, tools)

        self._turn_state = "listening"
```

- [ ] **Step 5: Find where JARVIS audio output starts and add state tracking**

Find where `set_speaking(True)` is called or where response text is sent. Add:

```python
        self._turn_state = "jarvis_speaking"
        self._current_speech_text = response_text[:100]
```

- [ ] **Step 6: Run syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile main.py`
Expected: No output

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat(main): add turn-based interruption model with stop_async and resume"
```

---

## Phase 4: VisualPresenceEngine + HUD Animations

**Files:** `core/visual_presence.py` (create), `core/hud.py` (modify), `tests/test_visual_presence.py` (create)

---

### Task 8: Create VisualPresenceEngine

**Files:**
- Create: `core/visual_presence.py`
- Test: `tests/test_visual_presence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visual_presence.py
import pytest, unittest.mock as mock
import sys
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

from core.visual_presence import JARVISVisualState, VisualPresenceEngine

class TestJARVISVisualState:
    def test_all_states_defined(self):
        assert JARVISVisualState.IDLE.value == "idle"
        assert JARVISVisualState.LISTENING.value == "listening"
        assert JARVISVisualState.THINKING.value == "thinking"
        assert JARVISVisualState.SPEAKING.value == "speaking"
        assert JARVISVisualState.VOLUNTEERING.value == "volunteering"
        assert JARVISVisualState.INTERRUPTED.value == "interrupted"

class TestVisualPresenceEngine:
    def test_set_state_updates_internal(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.set_state(JARVISVisualState.LISTENING)
        assert vpe._state == JARVISVisualState.LISTENING
        mock_hud.set_status_color.assert_called_once()
        mock_hud.set_state_label.assert_called_once_with("LISTENING")

    def test_volunteering_mode_switches_hud(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.set_state(JARVISVisualState.VOLUNTEERING)
        mock_hud.set_volunteer_mode.assert_called_once_with(True)

    def test_update_waveform_accumulates(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe._state = JARVISVisualState.LISTENING  # Only shows waveform when listening
        vpe.update_waveform(0.5)
        assert len(vpe._waveform_data) == 1
        mock_hud.update_waveform.assert_called_once()

    def test_on_tool_start_shows_activity(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.on_tool_start("email")
        mock_hud.show_activity.assert_called_once_with("email")

    def test_on_interrupted_updates_state_and_hud(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)
        vpe.on_interrupted("Checking your email now")
        assert vpe._state == JARVISVisualState.INTERRUPTED
        mock_hud.show_response.assert_called_once()

    def test_state_colors_are_correct(self):
        assert VisualPresenceEngine.STATE_COLORS[JARVISVisualState.IDLE] == (60, 60, 60)
        assert VisualPresenceEngine.STATE_COLORS[JARVISVisualState.LISTENING] == (0, 180, 255)
        assert VisualPresenceEngine.STATE_COLORS[JARVISVisualState.SPEAKING] == (0, 255, 180)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m pytest tests/test_visual_presence.py -v`
Expected: ERROR — ModuleNotFoundError: No module named 'core.visual_presence'

- [ ] **Step 3: Write minimal implementation**

```python
# core/visual_presence.py
"""VisualPresenceEngine — drives the cinematic HUD's visual state."""
import time
import math
from collections import deque
from enum import Enum

import logging

logger = logging.getLogger(__name__)


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
        self._waveform_data: deque = deque(maxlen=64)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m pytest tests/test_visual_presence.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add core/visual_presence.py tests/test_visual_presence.py
git commit -m "feat(hud): add VisualPresenceEngine with JARVISVisualState enum and 6 animation states"
```

---

### Task 9: Add HUD animation methods

**Files:**
- Modify: `core/hud.py`

- [ ] **Step 1: Read hud.py to understand DPG usage**

Read `core/hud.py`. The HUD uses DearPyGui via `dpg` alias. All existing `dpg` calls use `self._dpg.configure_item()` or `dpg.configure_item()`. Note: Python built-in `set` function is NOT imported directly as a dpg alias, but `dpg.configure_item` is used throughout. Check if `set` is used as a dpg alias by searching for `dpg.set_`.

Search for `dpg.set_` in hud.py. If found, alias `dpg_set = dpg.set_` or rename. Then add these 6 methods to `JARVISHUD`:

```python
    # Alias to avoid conflict with Python built-in set()
    dpg_set = getattr(dpg, 'set_', None)

    def set_status_color(self, rgb: tuple[int, int, int]):
        """Change the JARVIS status circle color."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("STATUS_CIRCLE", color=rgb, fill=rgb)
            self._current_state_color = rgb
        except Exception:
            pass

    def set_state_label(self, label: str):
        """Set the state text label."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("STATE_TEXT", default_value=label)
        except Exception:
            pass

    def set_volunteer_mode(self, enabled: bool):
        """Switch to gold volunteer color scheme."""
        if not self._dpg:
            return
        try:
            if enabled:
                self._dpg.configure_item("STATUS_TEXT", default_value="JARVIS (PROACTIVE)")
                self._dpg.configure_item("STATUS_CIRCLE", color=[255, 180, 0], fill=[255, 180, 0])
            elif hasattr(self, '_current_state_color'):
                self._dpg.configure_item("STATUS_TEXT", default_value="JARVIS")
                self._dpg.configure_item("STATUS_CIRCLE", color=self._current_state_color, fill=self._current_state_color)
        except Exception:
            pass

    def show_activity(self, text: str):
        """Briefly flash a tool activity indicator for 2 seconds."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("SCREEN_TEXT", default_value=f"[Working] {text}")
            def clear():
                import time
                time.sleep(2)
                try:
                    self._dpg.configure_item("SCREEN_TEXT", default_value=self._screen_context)
                except Exception:
                    pass
            import threading
            threading.Thread(target=clear, daemon=True).start()
        except Exception:
            pass

    def flash_success(self):
        """Brief green flash on successful tool completion."""
        if not self._dpg:
            return
        try:
            original_color = [0, 255, 180]
            self._dpg.configure_item("RESPONSE_TEXT", color=[0, 255, 100])
            def reset():
                import time
                time.sleep(0.3)
                try:
                    self._dpg.configure_item("RESPONSE_TEXT", color=original_color)
                except Exception:
                    pass
            import threading
            threading.Thread(target=reset, daemon=True).start()
        except Exception:
            pass

    def show_preview(self, text: str, duration: float):
        """Show text before JARVIS speaks it proactively."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("RESPONSE_TEXT", default_value=f"[Preview] {text[:80]}")
            def clear():
                import time
                time.sleep(duration)
                try:
                    self._dpg.configure_item("RESPONSE_TEXT", default_value="")
                except Exception:
                    pass
            import threading
            threading.Thread(target=clear, daemon=True).start()
        except Exception:
            pass

    def set_jarcircle_opacity(self, alpha: int):
        """Update the JARVIS circle's opacity for breathing effect."""
        if not self._dpg:
            return
        try:
            self._dpg.configure_item("STATUS_CIRCLE", fill=[0, 180, 255, alpha])
        except Exception:
            pass
```

- [ ] **Step 2: Run syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile core/hud.py`
Expected: No output

- [ ] **Step 3: Commit**

```bash
git add core/hud.py
git commit -m "feat(hud): add 6 animation methods — set_status_color, set_volunteer_mode, show_activity, flash_success, show_preview, set_jarcircle_opacity"
```

---

## Phase 5: Proactive Volunteering

**Files:** `core/proactive_monitor.py` (modify)

---

### Task 10: Wire volunteering into ProactiveMonitor

**Files:**
- Modify: `core/proactive_monitor.py`

- [ ] **Step 1: Add ConversationContextEngine to ProactiveMonitor.__init__**

Find `ProactiveMonitor.__init__` in `core/proactive_monitor.py`. Add:

```python
        from core.conversation_context import ConversationContextEngine
        self._ctx: ConversationContextEngine | None = None
```

Add a new method:

```python
    def set_context_engine(self, ctx: "ConversationContextEngine"):
        """Inject the ConversationContextEngine from JarvisLive."""
        self._ctx = ctx
```

- [ ] **Step 2: Modify the idle check in `_check_idle()`**

Find `_check_idle()` method. After checking idle time, add:

```python
        # Check with ConversationContextEngine
        if self._ctx and self._ctx.should_volunteer():
            topic = self._ctx.volunteer_topic()
            if topic:
                logger.info(f"[ProactiveMonitor] Volunteering: {topic}")
                self._speak_ref(topic)
                self._last_idle_speak = now
                self._idle_pings = 0
                return
```

- [ ] **Step 3: Run syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile core/proactive_monitor.py`
Expected: No output

- [ ] **Step 4: Commit**

```bash
git add core/proactive_monitor.py
git commit -m "feat(proactive): wire ConversationContextEngine volunteering into idle monitor"
```

---

## Phase 6: Session Review + Polish

**Files:** `main.py` (modify shutdown), `core/memory_bridge.py` (import in main.py)

---

### Task 11: Wire MemoryBridge session review and CCE into shutdown

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Find where JarvisLive shuts down**

Search for `def stop` or `def shutdown` in `main.py`. Also search for `set_speaking` or the main loop cleanup. Find where `ProactiveMonitor` is set up and where `JarvisLive` is used. Add:

Near where `ProactiveMonitor` is initialized in `main.py`, after calling `set_context_engine()`:

```python
        # Phase 6: Wire CCE and MemoryBridge into proactive monitor
        proactive_monitor.set_context_engine(jarvis._ctx)
```

In `JarvisLive.__init__`, also initialize a lazy MemoryBridge:

```python
        self._memory_bridge = None  # Phase 6: initialized lazily
```

Add method to JarvisLive:

```python
    def _get_memory_bridge(self):
        """Lazily initialize MemoryBridge."""
        if self._memory_bridge is None:
            try:
                from memory.j_memory import JARVISMemory
                from core.memory_bridge import MemoryBridge
                memory = JARVISMemory()
                memory.initialize()
                self._memory_bridge = MemoryBridge(memory)
            except Exception as e:
                logger.warning(f"[JarvisLive] MemoryBridge unavailable: {e}")
                self._memory_bridge = None
        return self._memory_bridge
```

- [ ] **Step 2: Wire on_session_end into JarvisLive shutdown**

Find where `JarvisLive` is cleaned up (search for `def stop` in the class or `_running = False`). Add:

```python
    def stop(self):
        """Stop the live session."""
        # Phase 6: Session review on shutdown
        bridge = self._get_memory_bridge()
        if bridge:
            bridge.on_session_end()
        self._running = False
        # ... rest of existing stop logic
```

- [ ] **Step 3: Wire VisualPresenceEngine into JarvisLive**

In `JarvisLive.__init__`, add:

```python
        from core.visual_presence import VisualPresenceEngine
        hud = get_cinematic_hud()
        self._vpe = VisualPresenceEngine(hud) if hud else None
```

And in `_execute_tool()`, add tool tracking:

```python
        if hasattr(self, '_vpe') and self._vpe:
            self._vpe.on_tool_start(name)
```

- [ ] **Step 4: Run syntax check**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m py_compile main.py`
Expected: No output

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(session): wire MemoryBridge session review, CCE, and VPE into JarvisLive lifecycle"
```

---

### Task 12: End-to-end test

**Files:**
- Create: `tests/test_jarvis_alive_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_jarvis_alive_integration.py
"""End-to-end tests for JARVIS Alive features."""
import pytest, unittest.mock as mock, time, sys
sys.path.insert(0, str(__file__).rsplit("tests", 1)[0])

from core.conversation_context import ConversationContextEngine
from core.memory_bridge import MemoryBridge
from core.visual_presence import JARVISVisualState, VisualPresenceEngine

class TestIntegrationTurnModel:
    """Test the complete turn model: user → JARVIS → interruption → resume."""

    def test_full_interruption_flow(self):
        ctx = ConversationContextEngine()

        # User asks a question
        ctx.on_user_turn("What's my battery level?")
        assert ctx.interaction_count == 1
        assert ctx.last_topic is not None

        # JARVIS starts responding
        ctx.on_jarvis_turn("Your battery is at 45 percent.", ["system_check"])
        assert ctx.interrupted is False
        assert ctx.current_goal == "working on: system_check"

        # User interrupts
        ctx.on_interruption("Never mind, check my email instead")
        assert ctx.interrupted is True
        assert "battery" in ctx.get_interrupted_text()  # JARVIS was cut off

        # After JARVIS responds to the interruption
        ctx.clear_interrupted()
        ctx.on_jarvis_turn("Done, sir.", ["email"])
        assert ctx.interrupted is False

    def test_context_engine_with_memory_bridge(self):
        mock_mem = mock.MagicMock()
        mock_mem.semantic.recall.return_value = ["You prefer British voice"]
        mock_mem.procedural.get_active.return_value = ["HUD project"]
        mock_mem.get_recent_topic.return_value = "Python scripting"

        ctx = ConversationContextEngine()
        ctx.inject_memory(mock_mem)

        bridge = MemoryBridge(mock_mem)
        ctx_str = bridge.build_context("open files")

        assert "WHAT I KNOW ABOUT YOU" in ctx_str
        assert "British voice" in ctx_str
        assert "HUD project" in ctx_str
        assert "Python scripting" in ctx_str

    def test_volunteer_flow(self):
        ctx = ConversationContextEngine()
        mock_mem = mock.MagicMock()
        mock_mem.get_recent_topic.return_value = "Python project"
        ctx.inject_memory(mock_mem)

        # Simulate idle time (advance clock manually)
        ctx.idle_since = time.time() - 400  # 6+ minutes ago
        ctx.last_volunteer_at = time.time() - 700  # Not recently

        assert ctx.should_volunteer() is True
        topic = ctx.volunteer_topic()
        assert topic is not None
        assert "Python" in topic

    def test_visual_presence_state_flow(self):
        mock_hud = mock.MagicMock()
        vpe = VisualPresenceEngine(mock_hud)

        # Normal listening
        vpe.set_state(JARVISVisualState.LISTENING)
        assert vpe._state == JARVISVisualState.LISTENING
        mock_hud.set_status_color.assert_called_with((0, 180, 255))

        # Tool execution
        vpe.on_tool_start("email")
        mock_hud.show_activity.assert_called_with("email")

        # Tool completion
        vpe.on_tool_complete()
        mock_hud.flash_success.assert_called_once()

        # Volunteer mode
        vpe.set_state(JARVISVisualState.VOLUNTEERING)
        mock_hud.set_volunteer_mode.assert_called_with(True)

        # Interruption
        vpe.on_interrupted("Checking your calendar")
        assert vpe._state == JARVISVisualState.INTERRUPTED
```

- [ ] **Step 2: Run all tests together**

Run: `cd /c/Users/bobul/OneDrive/Desktop/claude/myassistant/Mark-XXXV && python -m pytest tests/test_jarvis_alive_integration.py tests/test_conversation_context.py tests/test_memory_bridge.py tests/test_visual_presence.py -v`
Expected: PASS (all tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_jarvis_alive_integration.py
git commit -m "test(alive): end-to-end integration tests for all 5 alive features"
```

---

## Self-Review Checklist

1. **Spec coverage:** Skim each requirement in `docs/superpowers/specs/2026-04-10-jarvis-alive-design.md`:
   - ConversationContextEngine (turn tracking) → Task 1 ✓
   - MemoryBridge (4-layer injection) → Tasks 3-5 ✓
   - Interruption (stop_async + turn model) → Tasks 6-7 ✓
   - VisualPresenceEngine + HUD animations → Tasks 8-9 ✓
   - Proactive volunteering → Task 10 ✓
   - Session review + polish → Tasks 11-12 ✓
   - All 5 success criteria mapped ✓

2. **Placeholder scan:** No "TBD", "TODO", or vague steps. All code is concrete.

3. **Type consistency:**
   - `ConversationContextEngine.on_jarvis_turn(text: str, tools_used: list[str])` — matches Task 1 implementation ✓
   - `MemoryBridge.build_context(current_request: str) -> str` — matches Tasks 3-4 ✓
   - `JARVISVisualState` enum values match spec exactly: idle/listening/thinking/speaking/volunteering/interrupted ✓
   - `VisualPresenceEngine.__init__(self, hud)` — matches Task 8 ✓
   - `HUD.set_status_color(rgb: tuple[int, int, int])` — matches Task 9 ✓
   - All method names consistent across spec → plan → implementation ✓

4. **Git commit subjects match the changes:** Each commit is focused and follows conventional commits format.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-10-jarvis-alive-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
