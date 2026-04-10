"""
local_llm.py - Local LLM fallback using Ollama.
Provides phi3-mini responses when Gemini API is unavailable.
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "phi3-mini"
DEFAULT_URL = "http://localhost:11434/api/generate"


class LocalLLM:
    """
    Local LLM fallback via Ollama.
    Uses phi3-mini by default (quantum, 2.2B params, CPU-friendly).

    Falls back gracefully when Ollama is not running.
    """

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_URL):
        self.model = model
        self.base_url = base_url
        self._available: bool | None = None

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is loaded."""
        if self._available is not None:
            return self._available

        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self.base_url.replace('/api/generate', '')}/api/tags",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = resp.read()
                models = __import__("json").loads(data)
                available_models = [m.get("name", "") for m in models.get("models", [])]
                self._available = any(self.model in m for m in available_models)
                if not self._available:
                    logger.warning(
                        f"[LocalLLM] Ollama running but model '{self.model}' not found. "
                        f"Available: {available_models}. "
                        f"Run: ollama pull {self.model}"
                    )
        except Exception as e:
            self._available = False
            logger.debug(f"[LocalLLM] Ollama not available: {e}")
        return self._available

    def generate(self, prompt: str, context: list[dict] | None = None) -> str:
        """
        Generate a response using the local Ollama model.

        Args:
            prompt: The input prompt text
            context: Optional conversation history

        Returns:
            The model's text response, or empty string on failure
        """
        if not self.is_available():
            return ""

        try:
            import urllib.request

            payload: dict[str, Any] = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            }
            if context:
                # Build a simple context string from history
                ctx_parts = []
                for msg in context[-5:]:  # Last 5 messages
                    role = msg.get("role", "user")
                    content = msg.get("content", "")[:200]
                    ctx_parts.append(f"{role}: {content}")
                if ctx_parts:
                    payload["prompt"] = (
                        "Conversation history:\n"
                        + "\n".join(ctx_parts)
                        + f"\n\nUser: {prompt}"
                    )

            body = __import__("json").dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.base_url,
                data=body,
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                result = __import__("json").loads(data)
                return result.get("response", "").strip()

        except Exception as e:
            logger.error(f"[LocalLLM] Generation failed: {e}")
            return ""

    def pull_model(self) -> bool:
        """
        Trigger Ollama to pull the configured model.

        Returns:
            True if successful, False otherwise
        """
        try:
            import urllib.request
            import subprocess

            # Check if ollama CLI is available
            result = subprocess.run(
                ["ollama", "pull", self.model],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                self._available = None  # Re-check
                return True
            logger.error(f"[LocalLLM] ollama pull failed: {result.stderr}")
        except Exception as e:
            logger.error(f"[LocalLLM] pull_model failed: {e}")
        return False


# Singleton instance
_local_llm: LocalLLM | None = None


def get_local_llm() -> LocalLLM:
    """Get the singleton LocalLLM instance."""
    global _local_llm
    if _local_llm is None:
        _local_llm = LocalLLM()
    return _local_llm
