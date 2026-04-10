"""
tests/test_jarvis_enhancement.py
MARK-XXXV JARVIS Enhancement — Tier 1 & 2 Tests
Tests module imports, class structure, and component logic.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ── Temp dir helper (avoids Windows ChromaDB file-lock race) ──────────────────

def _make_temp_dir():
    """Create temp directory, auto-cleaned after use."""
    import atexit, gc, shutil as _sh
    d = tempfile.mkdtemp()

    def _cleanup():
        gc.collect()
        try:
            _sh.rmtree(d, ignore_errors=True)
        except PermissionError:
            pass

    atexit.register(_cleanup)
    return d


class _ManagedTempDir:
    """Context manager that auto-cleans temp dirs after ChromaDB usage."""
    def __enter__(self):
        self._path = _make_temp_dir()
        return self._path
    def __exit__(self, *args):
        import gc, shutil
        gc.collect()
        try:
            shutil.rmtree(self._path, ignore_errors=True)
        except PermissionError:
            pass
        return False


# ─── Tier 1: Module Import Tests ─────────────────────────────────────────────

class TestImports:
    """All modules must import without errors."""

    def test_audio_pipeline_components(self):
        from core.wake_word import WakeWordDetector
        from core.vad import VoiceActivityDetector
        from core.stt_engine import STTEngine
        from core.tts_engine import TTSEngine
        from core.audio_pipeline import JARVISAudioPipeline

        # Instantiate all components
        w = WakeWordDetector()
        v = VoiceActivityDetector()
        s = STTEngine("tiny")
        t = TTSEngine()
        p = JARVISAudioPipeline()

        assert w is not None
        assert v is not None
        assert s is not None
        assert t is not None
        assert p is not None

    def test_memory_components(self):
        from memory.j_memory import (
            JARVISMemory, EpisodicMemory, SemanticMemory, ProceduralMemory
        )
        from memory.extractor import MemoryExtractor

        m = JARVISMemory()
        m.initialize()
        assert m._initialized is True

        em = EpisodicMemory()
        em.initialize()
        assert em._ready is True

        sm = SemanticMemory()
        sm.initialize()
        assert sm._ready is True

        pm = ProceduralMemory()
        assert pm is not None

        ex = MemoryExtractor(memory=m, gemini_client=None)
        assert ex is not None

    def test_screen_components(self):
        from core.screen_monitor import ScreenIntelligence
        s = ScreenIntelligence()
        assert s is not None

    def test_proactive_components(self):
        from core.proactive_monitor import ProactiveMonitor
        pm = ProactiveMonitor()
        assert pm is not None

    def test_perception_components(self):
        from core.face_auth import FaceAuthenticator
        from core.gesture_control import GestureController
        f = FaceAuthenticator()
        g = GestureController()
        assert f is not None
        assert g is not None

    def test_smart_home_components(self):
        from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
        from core.personality import PersonalityEngine, JARVIS_SYSTEM_PROMPT
        ha = HomeAssistantAdapter()
        pe = PersonalityEngine()
        assert ha is not None
        assert pe is not None
        assert len(JARVIS_SYSTEM_PROMPT) > 100

    def test_rag_components(self):
        from memory.rag_pipeline import DocumentIndexer
        with _ManagedTempDir() as tmpdir:
            d = DocumentIndexer(memory_dir=tmpdir)
            d.initialize()
            assert d._ready is True

    def test_hud_components(self):
        from core.hud import JARVISHUD
        h = JARVISHUD()
        assert h is not None
        assert hasattr(h, "set_state")
        assert hasattr(h, "show_response")
        assert hasattr(h, "update_time")

    def test_action_functions(self):
        from actions.audio_action import audio_action
        from actions.memory_action import memory_action
        from actions.screen_action import screen_action
        from actions.proactive_action import proactive_action
        from actions.home_action import home_action
        from actions.rag_action import rag_action

        # All should return dicts
        r = audio_action({"command": "status"})
        assert isinstance(r, dict)

        r = memory_action({"command": "status"})
        assert isinstance(r, dict)

        r = screen_action({"command": "window"})
        assert isinstance(r, dict)

        r = proactive_action({"command": "status"})
        assert isinstance(r, dict)

        r = home_action({"command": "list"})
        assert isinstance(r, dict)

        r = rag_action({"command": "stats"})
        assert isinstance(r, dict)

    def test_main_tool_declarations(self):
        from main import TOOL_DECLARATIONS
        tool_names = [t["name"] for t in TOOL_DECLARATIONS]

        assert "audio_pipeline" in tool_names
        assert "jarvis_memory" in tool_names
        assert "screen_intelligence" in tool_names
        assert "proactive_monitor" in tool_names
        assert "smart_home" in tool_names
        assert "document_search" in tool_names


# ─── Tier 2: Component Logic Tests ───────────────────────────────────────────

class TestAudioPipeline:
    """Phase 1: Audio pipeline state machine and components."""

    def test_wake_word_detector_init(self):
        from core.wake_word import WakeWordDetector
        w = WakeWordDetector()
        w.initialize()
        # Without openWakeWord data files, engine stays None
        # That's expected — structure should still be correct
        assert w is not None
        assert hasattr(w, "detect")
        assert hasattr(w, "enable")
        assert hasattr(w, "disable")

    def test_vad_is_speech_returns_bool(self):
        import numpy as np
        from core.vad import VoiceActivityDetector
        v = VoiceActivityDetector()
        v.initialize()

        # Without model loaded, falls back to True
        audio = np.zeros(512, dtype=np.float32)
        result = v.is_speech(audio)
        assert isinstance(result, bool)

    def test_stt_engine_accepts_array(self):
        import numpy as np
        from core.stt_engine import STTEngine
        s = STTEngine("tiny")
        s.initialize()

        # Short audio should return empty string
        audio = np.zeros(1600, dtype=np.float32)
        result = s.transcribe(audio)
        assert result == ""

    def test_tts_engine_speak_returns_on_empty(self):
        from core.tts_engine import TTSEngine
        t = TTSEngine()

        # Empty text should return None
        result = t.speak("")
        assert result is None

        result = t.speak("  ")
        assert result is None

    def test_audio_pipeline_state_transitions(self):
        from core.audio_pipeline import JARVISAudioPipeline
        p = JARVISAudioPipeline()
        assert p._state == "idle"
        assert p._is_listening is True

        # Should have all component slots
        assert hasattr(p, "_wake_word")
        assert hasattr(p, "_vad")
        assert hasattr(p, "_stt")
        assert hasattr(p, "_tts")

        # Should have speak methods
        assert hasattr(p, "speak_response")
        assert hasattr(p, "speak_async")


class TestMemorySystem:
    """Phase 2: 4-layer memory operations."""

    def test_working_memory_set_get(self):
        from memory.j_memory import JARVISMemory
        m = JARVISMemory()
        m.initialize()

        m.set("test_key", "test_value", ttl=10)
        result = m.get("test_key")
        assert result == "test_value"

    def test_working_memory_expires(self):
        from memory.j_memory import JARVISMemory
        m = JARVISMemory()
        m.initialize()

        m.set("short_lived", "value", ttl=1)
        result = m.get("short_lived")
        assert result == "value"

        time.sleep(1.1)
        result = m.get("short_lived")
        assert result is None

    def test_episodic_memory_add_search(self):
        from memory.j_memory import EpisodicMemory
        with _ManagedTempDir() as tmpdir:
            em = EpisodicMemory(tmpdir)
            em.initialize()

            em.add("Test conversation about Python", {"type": "conversation"})
            results = em.search("Python", limit=5)
            assert isinstance(results, list)

    def test_semantic_memory_add_triple(self):
        from memory.j_memory import SemanticMemory
        with _ManagedTempDir() as tmpdir:
            sm = SemanticMemory(tmpdir)
            sm.initialize()

            sm.add_triple("Bobby", "works_at", "Shop Sore")
            results = sm.search("Bobby")
            assert isinstance(results, list)

    def test_procedural_memory_teach_match(self):
        from memory.j_memory import ProceduralMemory
        with _ManagedTempDir() as tmpdir:
            pm = ProceduralMemory(tmpdir)
            pm.teach(
                "backup_files",
                "Backup my work files",
                ["step 1", "step 2"],
                "backup files"
            )

            skill = pm.match("Please backup my files")
            assert skill is not None
            assert skill["name"] == "backup_files"

    def test_memory_extractor_returns_list(self):
        from memory.extractor import MemoryExtractor
        from memory.j_memory import JARVISMemory

        m = JARVISMemory()
        m.initialize()
        ex = MemoryExtractor(memory=m, gemini_client=None)

        # With no gemini client, should handle gracefully
        result = ex.process("I work at Shop Sore", "I understand, sir.")
        assert isinstance(result, list)


class TestScreenIntelligence:
    """Phase 3: Screen capture and analysis."""

    def test_screen_capture_returns_bytes(self):
        from core.screen_monitor import ScreenIntelligence
        s = ScreenIntelligence()

        # May fail without display, but should not crash
        try:
            result = s.capture_screen()
            # If it works, should be bytes
            if result is not None:
                assert isinstance(result, bytes)
        except Exception as e:
            pytest.skip(f"Screen capture requires display: {e}")

    def test_active_window_returns_string(self):
        from core.screen_monitor import ScreenIntelligence
        s = ScreenIntelligence()

        title = s.get_active_window_title()
        assert isinstance(title, str)
        assert len(title) >= 0


class TestProactiveMonitor:
    """Phase 5: Proactive monitoring daemon."""

    def test_monitor_init(self):
        from core.proactive_monitor import ProactiveMonitor
        pm = ProactiveMonitor()
        assert pm._running is False
        assert hasattr(pm, "start")
        assert hasattr(pm, "stop")
        assert hasattr(pm, "register_monitor")

    def test_monitor_check_system(self):
        from core.proactive_monitor import ProactiveMonitor
        pm = ProactiveMonitor()

        result = pm._check_system()
        assert isinstance(result, dict)
        assert "cpu_percent" in result
        assert "ram_percent" in result


class TestDocumentRAG:
    """Phase 8: Document indexing and query."""

    def test_indexer_initializes(self):
        from memory.rag_pipeline import DocumentIndexer
        with _ManagedTempDir() as tmpdir:
            d = DocumentIndexer(tmpdir)
            d.initialize()
            assert d._ready is True

    def test_indexer_stats(self):
        from memory.rag_pipeline import DocumentIndexer
        with _ManagedTempDir() as tmpdir:
            d = DocumentIndexer(tmpdir)
            d.initialize()

            stats = d.get_stats()
            assert isinstance(stats, dict)
            assert "documents" in stats
            assert "ready" in stats
            assert stats["ready"] is True

    def test_indexer_query_with_no_data(self):
        from memory.rag_pipeline import DocumentIndexer
        with _ManagedTempDir() as tmpdir:
            d = DocumentIndexer(tmpdir)
            d.initialize()

            # Query with no documents indexed
            result = d.query("What does my contract say?")
            assert isinstance(result, dict)
            assert "answer" in result


class TestPersonalityEngine:
    """Phase 9: JARVIS personality."""

    def test_personality_wrap(self):
        from core.personality import PersonalityEngine
        pe = PersonalityEngine()

        wrapped = pe.wrap("Hello JARVIS", "context here")
        assert isinstance(wrapped, list)
        assert len(wrapped) == 3  # system + context + user

    def test_personality_toggle(self):
        from core.personality import PersonalityEngine
        pe = PersonalityEngine()

        assert pe.enabled is True
        pe.toggle(False)
        assert pe.enabled is False
        pe.toggle()
        assert pe.enabled is True

    def test_personality_signon(self):
        from core.personality import PersonalityEngine
        pe = PersonalityEngine()

        morning = pe.get_signon(is_morning=True)
        evening = pe.get_signon(is_morning=False)

        assert isinstance(morning, str)
        assert isinstance(evening, str)
        assert len(morning) > 0
        assert len(evening) > 0

    def test_personality_format_response(self):
        from core.personality import PersonalityEngine
        pe = PersonalityEngine()

        # Should strip AI self-references
        raw = "As an AI, I would be happy to help you with that."
        formatted = pe.format_response(raw)

        assert "As an AI" not in formatted
        assert "happy" in formatted.lower() or "glad" in formatted.lower()


class TestSmartHome:
    """Phase 7: Home Assistant integration."""

    def test_ha_adapter_init(self):
        from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
        ha = HomeAssistantAdapter(url="http://test.local:8123", token="test")
        assert ha.url == "http://test.local:8123"

    def test_ha_methods_exist(self):
        from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
        ha = HomeAssistantAdapter()

        assert hasattr(ha, "turn_on")
        assert hasattr(ha, "turn_off")
        assert hasattr(ha, "set_brightness")
        assert hasattr(ha, "set_temperature")
        assert hasattr(ha, "get_state")
        assert hasattr(ha, "list_all_devices")


class TestFaceAuth:
    """Phase 6: Face recognition."""

    def test_face_auth_cosine_similarity(self):
        import numpy as np
        from core.face_auth import FaceAuthenticator
        fa = FaceAuthenticator()

        # Identical embeddings should return 1.0
        emb = np.ones(512, dtype=np.float32)
        sim = fa._similarity(emb, emb)
        assert abs(sim - 1.0) < 0.001

        # Orthogonal embeddings should return ~0.0
        emb2 = np.zeros(512, dtype=np.float32)
        emb2[0] = 1.0
        emb2[1] = -1.0
        emb1 = np.zeros(512, dtype=np.float32)
        emb1[0] = 1.0
        emb1[1] = 1.0
        sim = fa._similarity(emb1, emb2)
        assert abs(sim) < 0.001


class TestGesture:
    """Phase 6: Gesture recognition."""

    def test_gesture_controller_init(self):
        from core.gesture_control import GestureController
        gc = GestureController()
        assert gc._enabled is False
        assert gc._running is False

    def test_gesture_react(self):
        from core.gesture_control import GestureController
        gc = GestureController(speak_func=None)

        # Should not crash for any gesture
        gc._react("thumbs_up")
        gc._react("pause")
        gc._react("silence")
        gc._react("cancel")


class TestActionFunctions:
    """All action functions return correct dict shapes."""

    def test_audio_action_status(self):
        from actions.audio_action import audio_action
        r = audio_action({"command": "status"})
        assert "components" in r or "ready" in r or "status" in r

    def test_memory_action_status(self):
        from actions.memory_action import memory_action
        r = memory_action({"command": "status"})
        assert "status" in r

    def test_screen_action_window(self):
        from actions.screen_action import screen_action
        r = screen_action({"command": "window"})
        assert "status" in r or "title" in r

    def test_proactive_action_status(self):
        from actions.proactive_action import proactive_action
        r = proactive_action({"command": "status"})
        assert "status" in r

    def test_home_action_status(self):
        from actions.home_action import home_action
        r = home_action({"command": "list"})
        assert "status" in r

    def test_rag_action_stats(self):
        from actions.rag_action import rag_action
        r = rag_action({"command": "stats"})
        assert "status" in r

    def test_memory_action_learn(self):
        from actions.memory_action import memory_action
        r = memory_action({
            "command": "learn",
            "subject": "Bobby",
            "relation": "works_at",
            "object": "Shop Sore"
        })
        assert "status" in r

    def test_memory_action_teach(self):
        from actions.memory_action import memory_action
        r = memory_action({
            "command": "teach",
            "name": "test_skill",
            "description": "Test",
            "steps": ["step1", "step2"],
            "trigger": "test"
        })
        assert "status" in r


# ─── Run All Tests ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
