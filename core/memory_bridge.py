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
        facts = self._memory.semantic.recall("facts about the user")
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
        """Called when JARVIS shuts down. JARVIS reviews what it learned this session."""
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
