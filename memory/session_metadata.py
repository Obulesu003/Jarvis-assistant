"""
SessionMetadataManager - Tracks session state across JARVIS restarts.
"""
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SessionMetadata:
    """Metadata about a JARVIS session."""
    session_id: str
    started_at: str
    last_active: str
    last_topic: str = ""
    last_language: str = "en"
    interrupted_count: int = 0
    total_turns: int = 0
    tool_chains_used: list = field(default_factory=list)


class SessionMetadataManager:
    """
    Manages session metadata across JARVIS restarts.
    Enables cross-session continuity and resumption greetings.
    """

    def __init__(self, sessions_dir: str | None = None):
        if sessions_dir:
            self._sessions_dir = Path(sessions_dir)
        else:
            self._sessions_dir = Path("memory/sessions")
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._sessions_dir / "last_session.json"
        self._current: SessionMetadata | None = None

    def start_session(self) -> SessionMetadata:
        """Start a new session."""
        now = datetime.now().isoformat()
        self._current = SessionMetadata(
            session_id=str(uuid.uuid4())[:8],
            started_at=now,
            last_active=now,
        )
        self._save()
        logger.info(f"[SessionMetadata] Started session {self._current.session_id}")
        return self._current

    def update_topic(self, topic: str) -> None:
        """Update the current topic being discussed."""
        if self._current:
            self._current.last_topic = topic
            self._current.last_active = datetime.now().isoformat()
            self._current.total_turns += 1
            self._save()

    def update_language(self, lang: str) -> None:
        """Update the user's preferred language."""
        if self._current:
            self._current.last_language = lang
            self._save()

    def record_interruption(self) -> None:
        """Record that an interruption occurred this session."""
        if self._current:
            self._current.interrupted_count += 1
            self._save()

    def record_tool_chain(self, tool_chain: list) -> None:
        """Record a tool chain used this session."""
        if self._current and tool_chain:
            chain_key = " -> ".join(tool_chain)
            if chain_key not in self._current.tool_chains_used:
                self._current.tool_chains_used.append(chain_key)
            self._save()

    def end_session(self) -> None:
        """End the current session, saving state to disk."""
        if self._current:
            self._current.last_active = datetime.now().isoformat()
            self._save()
            logger.info(f"[SessionMetadata] Ended session {self._current.session_id}")
        self._current = None

    def get_resumption_greeting(self) -> str | None:
        """
        Get a greeting that references the previous session.

        Returns:
            A resumption greeting string, or None if no previous session
        """
        if not self._path.exists():
            return None

        try:
            prev_data = json.loads(self._path.read_text())
            prev = SessionMetadata(**prev_data)
        except Exception as e:
            logger.debug(f"[SessionMetadata] Could not load previous session: {e}")
            return None

        parts = []
        if prev.last_topic:
            parts.append(f"we were discussing {prev.last_topic}")
        if prev.total_turns > 0:
            parts.append(f"we had {prev.total_turns} exchanges")
        if prev.interrupted_count > 0:
            s = "" if prev.interrupted_count == 1 else "s"
            parts.append(f"you interrupted me {prev.interrupted_count} time{s}")

        if not parts:
            return None

        return f"Sir, welcome back. Last time {', '.join(parts)}."

    def _save(self) -> None:
        """Save current session to disk."""
        if self._current:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(asdict(self._current), indent=2))
            except Exception as e:
                logger.debug(f"[SessionMetadata] Save failed: {e}")
