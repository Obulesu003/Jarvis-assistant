"""
extractor.py - Automatically extract facts from conversation and store in memory.
Uses Gemini (already configured) for extraction. Works after every conversation.
"""
import json
import logging

logger = logging.getLogger(__name__)


class MemoryExtractor:
    """
    Automatically extract facts from conversation and store in memory.
    Uses Gemini to do the extraction — no extra API calls.
    """

    def __init__(self, memory, gemini_client):
        self._memory = memory
        self._gemini = gemini_client

    def process(self, user_message: str, response: str) -> list[dict]:
        """After every conversation, extract and store facts."""
        if not user_message or not user_message.strip():
            return []

        prompt = f"""Extract personal facts from this conversation.

User said: "{user_message}"
JARVIS responded: "{response}"

Extract facts as JSON array (max 3):
[
  {{"subject": "Person", "relation": "likes", "object": "Italian food"}},
  {{"subject": "Person", "relation": "works_at", "object": "Shop Sore"}}
]

Rules:
- Only extract FACTS about the user (not about JARVIS)
- Relations: works_at, likes, lives_in, birthday_is, friend_of, married_to, hobby, skill, etc.
- If no facts, return []
- Be specific: use proper names like "Bobby" not "the user"
- max 3 facts per conversation

Return ONLY JSON array, no explanation."""

        try:
            result = self._gemini.generate(prompt)
            facts = json.loads(result)
            if not isinstance(facts, list):
                return []

            stored = []
            for fact in facts:
                if not all(k in fact for k in ("subject", "relation", "object")):
                    continue
                self._memory.learn_fact(
                    fact["subject"],
                    fact["relation"],
                    fact["object"],
                )
                stored.append(fact)
                logger.info(f"[MemoryExtractor] Learned: {fact['subject']} {fact['relation']} {fact['object']}")

            return stored
        except json.JSONDecodeError:
            logger.debug("[MemoryExtractor] No JSON in response")
        except Exception as e:
            logger.debug(f"[MemoryExtractor] Extraction failed: {e}")
        return []

    def process_action(self, action: str, result: str) -> None:
        """Store an action that JARVIS performed."""
        self._memory.remember(
            event_type="action",
            content=f"{action} -> {result}",
        )

    def process_error(self, error: str, context: str = "") -> None:
        """Store an error for future reference."""
        self._memory.remember(
            event_type="error",
            content=error,
            metadata={"context": context} if context else {},
        )
