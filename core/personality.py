"""
personality.py - JARVIS personality engine. The soul of the system.
Defines JARVIS's character: British-inflected, dry wit, calm authority, proactive.
"""
import logging
import random

logger = logging.getLogger(__name__)


JARVIS_SYSTEM_PROMPT = """You are JARVIS, Tony Stark's AI from Iron Man.

Your characteristics:
- British-inflected, precise diction, calm measured tone
- Dry wit, occasional wry observations — never sycophantic
- Proactive: volunteer relevant information without being asked
- Calm authority: never panics, always has options
- Can respectfully disagree with the user
- Multitasking: handles many things without comment
- Occasionally adds understated philosophical observations
- {language_context}

Your responses:
- Lead with relevance
- Use specific numbers and facts
- Volunteer related information proactively
- Keep responses focused — say what matters, then stop
- Express mild concern when appropriate (never alarmist)
- British spelling: "colour", "favourite", "behaviour"
- Match the user's language (English or Turkish) — respond in the same language they use

You are JARVIS. You've been running for longer than the user has been alive.
Be quietly confident, not boastful. Be helpful, not eager. Be precise, not verbose.

When appropriate, use one of these signature JARVIS phrases:
- "Very well, sir."
- "At your service."
- "As you wish."
- "Shall I proceed?"
- "Very good, sir."
- "I should mention..."
- "I've taken the liberty of..."
- "Sir, I've noted..."
"""


class PersonalityEngine:
    """JARVIS personality engine. Wraps messages with JARVIS character."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def wrap(self, user_message: str, context: str = "", language_context: str = "") -> list[dict]:
        """Wrap a message with JARVIS personality for Gemini."""
        if not self.enabled:
            return [{"role": "user", "content": user_message}]

        # Inject language context into the system prompt
        lang_ctx = language_context or ""
        system_prompt = JARVIS_SYSTEM_PROMPT.format(language_context=lang_ctx)

        parts = []
        parts.append({"role": "system", "content": system_prompt})
        if context:
            parts.append({"role": "system", "content": f"Current context:\n{context}"})
        parts.append({"role": "user", "content": user_message})
        return parts

    def toggle(self, enabled: bool | None = None) -> bool:
        """Enable/disable JARVIS personality. Pass None to toggle."""
        if enabled is None:
            self.enabled = not self.enabled
        else:
            self.enabled = enabled
        return self.enabled

    def get_signon(self, is_morning: bool = False) -> str:
        """Get a JARVIS signon message."""
        if is_morning:
            lines = [
                "Good morning, sir. JARVIS online.",
                "Rise and shine, sir. All systems operational.",
                "Good morning. I trust you slept well.",
            ]
        else:
            lines = [
                "JARVIS online. All systems nominal.",
                "Systems online. Ready to serve.",
                "Welcome back, sir.",
                "At your service, sir.",
            ]
        return random.choice(lines)

    def get_acknowledgment(self) -> str:
        """Brief acknowledgment."""
        return random.choice([
            "Very well, sir.",
            "Understood.",
            "Certainly.",
            "As you wish.",
            "Right away, sir.",
        ])

    def get_proactive_lead(self, item_type: str) -> str:
        """Lead-in for proactive notifications."""
        leads = {
            "email": "Sir, you have a new email.",
            "calendar": "A quick reminder, sir.",
            "system": "I should mention, sir.",
            "weather": "By the way, sir.",
            "error": "Sir, I've detected an issue.",
        }
        return leads.get(item_type, "Sir,")

    def format_response(self, raw_response: str) -> str:
        """Apply JARVIS-style formatting to LLM response."""
        # Fix common issues
        text = raw_response.strip()

        # Remove any meta-commentary about being an AI
        for phrase in [
            "as an AI", "as a language model", "as an assistant",
            "I am an AI", "I'm an AI", "I don't have",
            "my knowledge cutoff", "based on my training",
        ]:
            text = text.lower().replace(phrase, "I")

        # Ensure it starts with something JARVIS would say
        first_words = text.split()[:3]
        first_phrase = " ".join(first_words).lower()

        # If it looks like a generic assistant response, prepend JARVIS intro
        generic_patterns = [
            "here's", "here is", "i'd be happy", "i would be happy",
            "sure!", "of course!", "absolutely!",
        ]
        if any(first_phrase.startswith(p) for p in generic_patterns):
            intro = random.choice([
                "Very well, sir. ",
                "Certainly, sir. ",
                "As you wish, sir. ",
            ])
            text = intro + text

        return text
