# core/conversation_manager.py
# Rolling conversation buffer with periodic summarization.
# Compresses long conversations into key facts to maintain context.

import contextlib
import io
import sys

for _s in (sys.stdout, sys.stderr):
    if isinstance(_s, io.TextIOWrapper):
        with contextlib.suppress(Exception): _s.reconfigure(encoding="utf-8", errors="replace")
import json
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR           = get_base_dir()
CONVERSATIONS_DIR  = BASE_DIR / "memory" / "conversations"
MAX_TURNS          = 20        # Rolling buffer size
SUMMARIZE_EVERY   = 10        # Summarize after every N turns
QUIET_THRESHOLD_S = 60        # Summarize after N seconds of silence
SUMMARIZE_CHAR_LIMIT = 4000  # Summarize when conversation exceeds this length


@dataclass
class Turn:
    role:    str   # "user" | "jarvis" | "tool"
    content: str
    tool:    str = ""
    ts:      float = field(default_factory=time.time)


class ConversationManager:
    """
    Manages the rolling conversation buffer and periodic summarization.
    """

    def __init__(self):
        self._turns:    deque[Turn]  = deque(maxlen=MAX_TURNS)
        self._lock:    threading.Lock = threading.Lock()
        self._summary: str            = ""
        self._last_activity: float    = time.time()
        self._speak:   Callable | None = None

    def set_speak(self, speak: Callable | None):
        self._speak = speak

    def add_turn(self, role: str, content: str, tool: str = ""):
        if not content or not content.strip():
            return
        with self._lock:
            self._turns.append(Turn(role=role, content=content, tool=tool, ts=time.time()))
            self._last_activity = time.time()
        # Auto-summarize if conversation gets too long
        self._summarize_conversation()

    def add_user_turn(self, text: str):
        self.add_turn("user", text)

    def add_jarvis_turn(self, text: str):
        self.add_turn("jarvis", text)

    def add_tool_turn(self, tool: str, result: str):
        self.add_turn("tool", result[:500], tool=tool)  # Truncate tool results

    def should_summarize(self) -> bool:
        """Returns True if it's time to summarize."""
        with self._lock:
            if len(self._turns) >= SUMMARIZE_EVERY:
                return True
            return bool(len(self._turns) >= 3 and time.time() - self._last_activity > QUIET_THRESHOLD_S)

    def get_context_for_prompt(self) -> str:
        """
        Returns the current conversation context as a formatted string
        for injection into the system prompt.
        """
        with self._lock:
            if not self._turns:
                return ""
            if self._summary:
                return f"[CONVERSATION SUMMARY]\n{self._summary}\n\n[RECENT TURNS]\n" + self._format_recent_turns()
            return "[CURRENT CONVERSATION]\n" + self._format_recent_turns()

    def _format_recent_turns(self) -> str:
        """Formats the last 6 turns for context."""
        recent = list(self._turns)[-6:]
        lines = []
        for t in recent:
            if t.role == "user":
                lines.append(f"User: {t.content[:200]}")
            elif t.role == "jarvis":
                lines.append(f"JARVIS: {t.content[:200]}")
            elif t.role == "tool":
                lines.append(f"[Tool: {t.tool}] {t.content[:100]}")
        return "\n".join(lines)

    def summarize(self) -> str:
        """
        Generates a summary of the conversation using Gemini.
        Returns the summary string.
        """
        with self._lock:
            turns_snapshot = list(self._turns)
            old_summary    = self._summary

        if len(turns_snapshot) < 3:
            return ""

        try:
            prompt = self._build_summary_prompt(turns_snapshot, old_summary)
            summary = _gemini_summarize(prompt)
            with self._lock:
                self._summary = summary
            self._save_to_disk()
            return summary
        except Exception as e:
            print(f"[ConversationManager] Summarization failed: {e}")
            return ""

    def _summarize_conversation(self) -> None:
        """
        Condenses long conversations to save context window space.
        Keeps the last 3 exchanges + a one-line summary.
        Called automatically when conversation exceeds SUMMARIZE_CHAR_LIMIT.
        """
        with self._lock:
            total_chars = sum(len(t.content) for t in self._turns)

        if total_chars < SUMMARIZE_CHAR_LIMIT:
            return

        print(f"[ConversationManager] Summarizing conversation ({total_chars} chars)")

        with self._lock:
            turns_snapshot = list(self._turns)

        if len(turns_snapshot) <= 6:
            return  # Already short enough

        try:
            # Generate a brief summary of the full conversation
            summary_prompt = self._build_summary_prompt(turns_snapshot, self._summary)
            brief_summary = _gemini_summarize(summary_prompt)

            # Keep only last 3 exchanges (6 turns: user + jarvis pairs)
            # and rebuild with the summary prepended
            recent_turns = list(self._turns)[-6:]

            with self._lock:
                self._turns.clear()
                self._summary = brief_summary
                for turn in recent_turns:
                    self._turns.append(turn)

            self._save_to_disk()
            print(f"[ConversationManager] Conversation condensed: {total_chars} -> ~{len(brief_summary) + sum(len(t.content) for t in recent_turns)} chars")
        except Exception as e:
            print(f"[ConversationManager] Condensation failed: {e}")

    def _build_summary_prompt(self, turns: list[Turn], old_summary: str) -> str:
        lines = []
        for t in turns:
            if t.role == "user":
                lines.append(f"USER: {t.content}")
            elif t.role == "jarvis":
                lines.append(f"JARVIS: {t.content}")
            elif t.role == "tool":
                lines.append(f"[{t.tool}]: {t.content[:200]}")

        conversation = "\n".join(lines)
        context = f"Previous summary:\n{old_summary}\n\n" if old_summary else ""

        return (
            f"{context}Summarize this conversation. Extract:\n"
            f"- Key topics discussed\n"
            f"- Important decisions made\n"
            f"- User preferences or facts revealed\n"
            f"- Current task or goal in progress\n"
            f"- Any pending or incomplete actions\n\n"
            f"Format: 3-5 concise sentences. Be factual. Include all important details.\n\n"
            f"CONVERSATION:\n{conversation}"
        )

    def _save_to_disk(self):
        """Persist conversation to disk for recovery."""
        try:
            CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            filepath = CONVERSATIONS_DIR / f"session_{ts}.json"

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({
                    "summary": self._summary,
                    "turns": [
                        {"role": t.role, "content": t.content, "tool": t.tool, "ts": t.ts}
                        for t in self._turns
                    ],
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ConversationManager] Could not save conversation: {e}")

    def clear(self):
        """Clears the conversation buffer."""
        with self._lock:
            self._turns.clear()
            self._summary = ""
            self._last_activity = time.time()

    def get_turn_count(self) -> int:
        with self._lock:
            return len(self._turns)


def _gemini_summarize(prompt: str) -> str:
    """Uses Gemini to summarize the conversation."""
    if _get_gemini_key is None:
        return _simple_summarize(prompt)

    try:
        from google.genai import Client
        client = Client(api_key=_get_gemini_key())
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"[ConversationManager] Gemini summarize failed: {e}")
        return _simple_summarize(prompt)


def _simple_summarize(prompt: str) -> str:
    """Fallback summarization without AI."""
    lines = prompt.split("\n")
    topics = []
    for line in lines:
        if line.startswith("USER:"):
            topics.append(line[6:].strip()[:80])
    if topics:
        return f"Discussed: {'; '.join(topics[-3:])}"
    return ""


# Singleton instance
_manager: ConversationManager | None = None
_init_lock = threading.Lock()


def get_conversation_manager() -> ConversationManager:
    global _manager
    if _manager is None:
        with _init_lock:
            if _manager is None:
                _manager = ConversationManager()
    return _manager
