"""
InteractionPatternLearner - Learns from user interaction patterns.
Tracks tool chains, effectiveness, and adapts LLM context.
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class InteractionPatternLearner:
    """
    Learns from repeated user interactions to provide adaptive context.

    Tracks:
    - Tool chains (sequences of tools used together)
    - Tool effectiveness based on user feedback
    - Provides suggestions to LLM based on learned patterns
    """

    def __init__(self, memory_dir: str | None = None):
        if memory_dir:
            self._dir = Path(memory_dir)
        else:
            self._dir = Path("memory/patterns")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "tool_patterns.json"
        self._patterns: dict[str, Any] = self._load()
        self._current_chain: list[str] = []
        self._last_save_time: float = 0.0
        self._save_interval: float = 60.0  # Save at most once per 60 seconds

    def _load(self) -> dict[str, Any]:
        """Load patterns from disk."""
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception as e:
                logger.debug(f"[PatternLearner] Load failed: {e}")
        return {"chains": {}, "feedback": {}}

    def _save(self):
        """Persist patterns to disk (debounced: max once per _save_interval seconds)."""
        import time as _time
        now = _time.time()
        if now - self._last_save_time < self._save_interval:
            return
        self._last_save_time = now
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._patterns, indent=2))
        except Exception as e:
            logger.debug(f"[PatternLearner] Save failed: {e}")

    def on_tool_used(self, tool_name: str) -> None:
        """
        Record a tool usage as part of the current tool chain.

        Args:
            tool_name: Name of the tool
        """
        self._current_chain.append(tool_name)

    def on_turn_complete(self, helpful: bool | None = None) -> None:
        """
        Record the completion of a conversation turn.

        Args:
            helpful: Optional feedback (True=helpful, False=unhelpful, None=no feedback)
        """
        if not self._current_chain:
            return

        chain_key = " -> ".join(self._current_chain)
        if chain_key not in self._patterns["chains"]:
            self._patterns["chains"][chain_key] = {
                "count": 0,
                "helpful": 0,
                "unhelpful": 0,
            }

        self._patterns["chains"][chain_key]["count"] += 1
        if helpful is True:
            self._patterns["chains"][chain_key]["helpful"] += 1
        elif helpful is False:
            self._patterns["chains"][chain_key]["unhelpful"] += 1

        self._current_chain = []
        self._save()

    def get_adaptive_context(self, current_request: str) -> str:
        """
        Get adaptive context based on learned patterns.

        Args:
            current_request: The current user request

        Returns:
            Context string with pattern suggestions, or empty string
        """
        if not self._patterns["chains"]:
            return ""

        parts = []
        for chain, data in self._patterns["chains"].items():
            if data["helpful"] >= 2:
                ratio = data["helpful"] / max(data["count"], 1)
                if ratio > 0.7:
                    parts.append(
                        f"Effective tool chain: {chain} "
                        f"(success rate: {int(ratio * 100)}%)"
                    )

        if parts:
            return "\n".join(parts[:3])
        return ""

    def record_feedback(self, tool: str, helpful: bool) -> None:
        """
        Record explicit feedback for a tool.

        Args:
            tool: Tool name
            helpful: True if helpful, False if not
        """
        key = f"feedback_{tool}"
        self._patterns["feedback"][key] = (
            self._patterns["feedback"].get(key, 0) + (1 if helpful else -1)
        )
        self._save()

    def get_tool_effectiveness(self, tool_name: str) -> float:
        """
        Get the effectiveness score for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Effectiveness score
        """
        key = f"feedback_{tool_name}"
        return self._patterns["feedback"].get(key, 0)
