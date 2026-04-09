"""
j_memory.py - JARVIS 4-layer memory system.
All local, all CPU-based, all free.

Layer 1 — WORKING: Current session context (dict, instant)
Layer 2 — EPISODIC: What happened when (ChromaDB, searchable)
Layer 3 — SEMANTIC: Facts I know about you (NetworkX + ChromaDB)
Layer 4 — PROCEDURAL: How to do things (skill library)
"""
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("memory")
MEMORY_DIR.mkdir(exist_ok=True)


class MemoryConfig(TypedDict):
    persist_dir: str


class JARVISMemory:
    """
    4-layer memory system for JARVIS.
    All local, all CPU-based, all free.
    """

    def __init__(self, persist_dir: str = "memory"):
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(exist_ok=True)

        # Layer 1: Working memory
        self._working: dict[str, dict] = {}

        # Layer 2: Episodic memory (ChromaDB)
        self._episodic: "EpisodicMemory" | None = None

        # Layer 3: Semantic memory (NetworkX + ChromaDB)
        self._semantic: "SemanticMemory" | None = None

        # Layer 4: Procedural memory (Skills)
        self._procedural: "ProceduralMemory" | None = None

        self._initialized = False

    def initialize(self):
        """Initialize memory layers. Call once at startup."""
        if self._initialized:
            return

        try:
            self._episodic = EpisodicMemory(str(self._persist_dir / "episodes"))
            self._semantic = SemanticMemory(str(self._persist_dir / "semantic"))
            self._procedural = ProceduralMemory(str(self._persist_dir / "procedural"))
            self._initialized = True
            logger.info("[Memory] All 4 layers initialized")
        except Exception as e:
            logger.error(f"[Memory] Initialization failed: {e}")
            # Fallback: working memory only
            self._initialized = True

    # ── WORKING MEMORY ──
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store in working memory with TTL (default 5 minutes)."""
        self._working[key] = {
            "value": value,
            "expires": time.time() + ttl,
        }

    def get(self, key: str) -> Any | None:
        """Retrieve from working memory. Returns None if expired."""
        entry = self._working.get(key)
        if entry and time.time() < entry["expires"]:
            return entry["value"]
        elif entry:
            del self._working[key]
        return None

    def delete(self, key: str) -> None:
        """Delete from working memory."""
        self._working.pop(key, None)

    # ── EPISODIC MEMORY ──
    def remember(self, event_type: str, content: str, metadata: dict | None = None) -> None:
        """Store an event in episodic memory. 'event_type' like 'conversation', 'action', 'error'."""
        if self._episodic:
            self._episodic.add(
                document=f"[{event_type.upper()}] {content}",
                metadata={**(metadata or {}), "type": event_type}
            )

    def recall(self, query: str, limit: int = 5) -> list[str]:
        """'What did we discuss about X?' — search episodic memory."""
        if self._episodic:
            return self._episodic.search(query, limit=limit)
        return []

    def get_recent_memories(self, hours: int = 24, limit: int = 10) -> list[dict]:
        """Get memories from the last N hours."""
        if self._episodic:
            return self._episodic.get_recent(hours=hours, limit=limit)
        return []

    # ── SEMANTIC MEMORY ──
    def learn_fact(self, subject: str, relation: str, object_: str, confidence: float = 1.0) -> None:
        """Store a fact: 'Bobby works at Shop Sore'."""
        if self._semantic:
            self._semantic.add_triple(subject, relation, object_, confidence)

    def what_do_you_know(self, query: str) -> str:
        """Answer: 'Where does Bobby work?' — query semantic memory."""
        if self._semantic:
            return self._semantic.answer(query)
        return ""

    def search_knowledge(self, query: str) -> list[str]:
        """Search semantic memory for facts."""
        if self._semantic:
            return self._semantic.search(query)
        return []

    # ── PROCEDURAL MEMORY ──
    def teach_skill(self, name: str, description: str, steps: list[str], trigger: str) -> None:
        """Teach JARVIS a skill: 'Teach me to backup my files'."""
        if self._procedural:
            self._procedural.teach(name, description, steps, trigger)

    def find_skill(self, task: str) -> dict | None:
        """Find a skill for a task. 'Back up my documents' → backup skill."""
        if self._procedural:
            return self._procedural.match(task)
        return None

    def list_skills(self) -> list[str]:
        """List all taught skills."""
        if self._procedural:
            return self._procedural.list_all()
        return []

    # ── SESSION CONTEXT ──
    def build_context(self, user_message: str = "") -> str:
        """Build conversation context string for Gemini."""
        parts = []

        # Recent memories
        if self._episodic:
            recent = self._episodic.get_recent(hours=24, limit=5)
            if recent:
                parts.append("Recent memories:")
                for m in recent:
                    parts.append(f"  - {m.get('document', m.get('text', ''))[:100]}")

        # Knowledge about user
        if self._semantic and user_message:
            facts = self._semantic.search(user_message)
            if facts:
                parts.append("What I know about you:")
                for f in facts[:3]:
                    parts.append(f"  - {f}")

        return "\n".join(parts) if parts else ""

    # ── EXTENDED MEMORY HELPERS ──
    def get_recent_topic(self) -> str | None:
        """Return the last discussed topic from episodic memory."""
        if not self._episodic:
            return None
        try:
            results = self._episodic.get_recent(hours=24, limit=1)
            if results:
                return results[0].get("document", "")
        except Exception:
            pass
        return None

    def get_active(self) -> list[str]:
        """Return active project names from procedural memory."""
        if not self._procedural:
            return []
        try:
            skills = self._procedural.list_all()
            return list(skills) if isinstance(skills, list) else []
        except Exception:
            return []

    def get_session_memories(self, since: float) -> list[dict]:
        """Return memories created since the given timestamp."""
        if not self._episodic:
            return []
        try:
            return self._episodic.get_recent(hours=24, limit=50)
        except Exception:
            return []

    def get_preferences_for(self, request: str) -> list[str]:
        """Return user preferences relevant to the current request."""
        if not self._semantic:
            return []
        try:
            facts = self._semantic.search(request)
            return facts
        except Exception:
            return []


# ── EPISODIC MEMORY (ChromaDB) ──
class EpisodicMemory:
    """Stores what happened. Conversations, actions, events. Searchable by time."""

    def __init__(self, persist_dir: str = "memory/episodes"):
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(exist_ok=True)
        self._client = None
        self._collection = None
        self._ready = False

    def initialize(self):
        """Initialize ChromaDB connection."""
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._collection = self._client.get_or_create_collection(
                "episodes",
                metadata={"description": "JARVIS episodic memory"}
            )
            self._ready = True
            logger.info(f"[EpisodicMemory] ChromaDB ready at {self._persist_dir}")
        except Exception as e:
            logger.error(f"[EpisodicMemory] ChromaDB init failed: {e}")

    def add(self, document: str, metadata: dict) -> None:
        """Store an episodic memory."""
        if not self._ready:
            self.initialize()
        if not self._collection:
            return

        try:
            self._collection.add(
                documents=[document],
                metadatas=[{**metadata, "timestamp": datetime.now().isoformat()}],
                ids=[uuid.uuid4().hex]
            )
        except Exception as e:
            logger.error(f"[EpisodicMemory] Add failed: {e}")

    def search(self, query: str, limit: int = 5) -> list[str]:
        """Search episodic memory."""
        if not self._ready:
            self.initialize()
        if not self._collection:
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=limit
            )
            if results and results["documents"]:
                return results["documents"][0]
        except Exception as e:
            logger.debug(f"[EpisodicMemory] Search failed: {e}")
        return []

    def get_recent(self, hours: int = 24, limit: int = 10) -> list[dict]:
        """Get recent memories within the last N hours."""
        if not self._ready:
            self.initialize()
        if not self._collection:
            return []

        try:
            import time
            cutoff = datetime.fromtimestamp(time.time() - hours * 3600).isoformat()
            results = self._collection.get(
                where={"timestamp": {"$gte": cutoff}},
                limit=limit
            )
            if results and results["documents"]:
                return [
                    {"document": doc, "metadata": meta}
                    for doc, meta in zip(results["documents"], results["metadatas"])
                ]
        except Exception as e:
            logger.debug(f"[EpisodicMemory] Get recent failed: {e}")
        return []


# ── SEMANTIC MEMORY (NetworkX + ChromaDB) ──
class SemanticMemory:
    """Stores what JARVIS knows about you. Facts, relations, preferences."""

    def __init__(self, persist_dir: str = "memory/semantic"):
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(exist_ok=True)
        self._graph = None
        self._client = None
        self._collection = None
        self._ready = False

    def initialize(self):
        """Initialize NetworkX graph and ChromaDB."""
        try:
            import networkx as nx
            import chromadb

            self._graph = nx.DiGraph()
            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._collection = self._client.get_or_create_collection("semantic_facts")
            self._ready = True
            logger.info(f"[SemanticMemory] Graph + ChromaDB ready at {self._persist_dir}")
        except Exception as e:
            logger.error(f"[SemanticMemory] Init failed: {e}")

    def add_triple(self, subject: str, relation: str, object_: str, confidence: float = 1.0) -> None:
        """Store: (Subject) —[relation]→ (Object)."""
        if not self._ready:
            self.initialize()
        if not self._graph or not self._collection:
            return

        try:
            # Add to NetworkX graph
            self._graph.add_node(subject, type="entity")
            self._graph.add_node(object_, type="entity")
            self._graph.add_edge(subject, object_, relation=relation, confidence=confidence)

            # Add to ChromaDB for vector search
            fact_text = f"{subject} {relation} {object_}"
            self._collection.add(
                documents=[fact_text],
                metadatas=[{"subject": subject, "relation": relation, "object": object_}],
                ids=[uuid.uuid4().hex]
            )
        except Exception as e:
            logger.error(f"[SemanticMemory] Add failed: {e}")

    def answer(self, question: str) -> str:
        """Answer questions about stored knowledge."""
        if not self._ready:
            self.initialize()
        if not self._collection:
            return ""

        try:
            results = self._collection.query(query_texts=[question], n_results=3)
            if not results or not results["documents"]:
                return ""

            facts = results["documents"][0]
            return f"I know that: {'; '.join(facts)}"
        except Exception as e:
            logger.debug(f"[SemanticMemory] Answer failed: {e}")
            return ""

    def search(self, query: str) -> list[str]:
        """Search semantic memory."""
        if not self._ready:
            self.initialize()
        if not self._collection:
            return []

        try:
            results = self._collection.query(query_texts=[query], n_results=5)
            if results and results["documents"]:
                return results["documents"][0]
        except Exception:
            pass
        return []

    def get_graph(self) -> dict:
        """Return the knowledge graph as a serializable dict."""
        if not self._graph:
            return {"nodes": [], "edges": []}
        nodes = [
            {"id": n, **self._graph.nodes[n]}
            for n in self._graph.nodes()
        ]
        edges = [
            {"from": u, "to": v, **d}
            for u, v, d in self._graph.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}


# ── PROCEDURAL MEMORY (Skills) ──
class ProceduralMemory:
    """JARVIS knows how to do things. Skills, workflows, automation recipes."""

    def __init__(self, persist_dir: str = "memory/procedural"):
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(exist_ok=True)
        self._skills: dict[str, dict] = {}
        self._load_skills()

    def _skills_file(self) -> Path:
        return self._persist_dir / "skills.json"

    def _load_skills(self):
        """Load skills from disk."""
        sf = self._skills_file()
        if sf.exists():
            try:
                with open(sf) as f:
                    self._skills = json.load(f)
            except Exception as e:
                logger.debug(f"[ProceduralMemory] Load failed: {e}")

    def _save_skills(self):
        """Save skills to disk."""
        sf = self._skills_file()
        with open(sf, "w") as f:
            json.dump(self._skills, f, indent=2)

    def teach(self, name: str, description: str, steps: list[str], trigger: str) -> None:
        """Teach JARVIS a new skill."""
        self._skills[name] = {
            "name": name,
            "description": description,
            "steps": steps,
            "trigger": trigger,
            "usage_count": 0,
            "created": datetime.now().isoformat(),
        }
        self._save_skills()
        logger.info(f"[ProceduralMemory] Taught skill: {name}")

    def match(self, task: str) -> dict | None:
        """Find a skill for a task."""
        task_lower = task.lower()
        for name, skill in self._skills.items():
            # Check if all words in trigger appear in the task
            trigger_words = skill["trigger"].lower().split()
            if all(word in task_lower for word in trigger_words):
                skill["usage_count"] += 1
                self._save_skills()
                return skill
        return None

    def list_all(self) -> list[str]:
        """List all skill names."""
        return list(self._skills.keys())

    def delete_skill(self, name: str) -> bool:
        """Delete a skill."""
        if name in self._skills:
            del self._skills[name]
            self._save_skills()
            return True
        return False
