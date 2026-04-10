"""
Tests for language detection in ConversationContextEngine.
"""
import pytest
from core.conversation_context import ConversationContextEngine


class TestLanguageDetection:
    """Test cases for language detection."""

    @pytest.fixture
    def engine(self):
        """Create a context engine."""
        return ConversationContextEngine()

    def test_initial_language_is_english(self, engine):
        """Default language should be English."""
        assert engine._user_language == "en"

    def test_detect_english_text(self, engine):
        """Should detect English text."""
        text = "Hello, how are you today? I want to check my emails."
        result = engine.detect_and_track_language(text)
        assert result == "en"

    def test_detect_turkish_text(self, engine):
        """Should detect Turkish text."""
        text = "Merhaba, nasılsın? Bugün ne yapıyorsun?"
        result = engine.detect_and_track_language(text)
        assert result == "tr"

    def test_detect_mixed_text(self, engine):
        """Should detect mixed language when both languages present."""
        # "Hello how are you" (4 EN) + "nasıl" (1 TR) = 1/5 TR = 20% < 70%, so EN
        # We need at least 30% of each to be "mixed". Test with 2 EN + 2 TR words.
        text = "Hello how are you nasıl ne yapıyorum"
        result = engine.detect_and_track_language(text)
        assert result == "mixed"

    def test_language_history_tracking(self, engine):
        """Language history should track last 5 detections."""
        texts = [
            "Hello there", "Good morning", "How are you",
            "Thanks okay", "Weather today"
        ]
        for text in texts:
            engine.detect_and_track_language(text)
        assert len(engine._language_context.history) == 5
        assert engine._user_language == "en"

    def test_get_language_context_english(self, engine):
        """get_language_context should return empty for English."""
        context = engine.get_language_context()
        assert context == ""

    def test_get_language_context_turkish(self, engine):
        """get_language_context should return Turkish guidance."""
        engine._user_language = "tr"
        context = engine.get_language_context()
        assert "tr" in context or "Turkish" in context

    def test_empty_text_keeps_previous_language(self, engine):
        """Empty text should not change language."""
        engine._user_language = "tr"
        result = engine.detect_and_track_language("")
        assert result == "tr"

    def test_single_word_english(self, engine):
        """Single English word should detect correctly."""
        result = engine.detect_and_track_language("the")
        assert result == "en"

    def test_single_word_turkish(self, engine):
        """Single Turkish word should detect correctly."""
        result = engine.detect_and_track_language("bir")
        assert result == "tr"

    def test_update_language_directly(self, engine):
        """update_language should save language."""
        engine.update_language("tr")
        assert engine._user_language == "tr"

    def test_history_max_5_items(self, engine):
        """History should not exceed 5 items."""
        for _ in range(10):
            engine.detect_and_track_language("hello world")
        assert len(engine._language_context.history) <= 5
