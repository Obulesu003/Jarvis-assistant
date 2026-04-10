"""
LLM-Powered Orchestrator — the brain of MARK-XXXV's assistant.

Uses Gemini to classify intent and plan execution steps, replacing fragile
keyword matching with natural language understanding.

Phase 2 of the build plan.
"""

import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# 30-second timeout per request — prevents hangs when API is slow
REQUEST_TIMEOUT = 30

# Gemini free tier: 5 requests/minute → retry with backoff
MAX_RETRIES = 2
INITIAL_BACKOFF = 8  # seconds (reduced from 15 — faster retry on free tier)

# How many recent steps to include as context
CONTEXT_HISTORY_LIMIT = 5


class LLMOrchestrator:
    """
    LLM-powered orchestrator that uses Gemini for intent classification.

    Architecture:
        User Request
              │
              ▼
        Gemini (fast model)
              │ "Classify intent, plan steps. Return JSON."
              ▼
        Steps: [{"adapter": "...", "action": "...", "params": {...}}]
              │
              ▼
        UniversalOrchestrator executes → results
              │
              ▼
        Gemini formats natural response from results
    """

    # Cached capability prompt — rebuilt only when adapters change
    _capabilities_cache: str = ""
    _capabilities_cache_key: str = ""

    def __init__(self, universal_orchestrator: Any, gemini_key: str | None = None):
        self._orch = universal_orchestrator
        self._gemini_key = gemini_key or self._get_gemini_key()
        self._model = None  # Lazily initialized
        self._client = None  # Lazily initialized for google.genai Client
        self._memory_bridge = None  # Lazily initialized
        self._pattern_learner = None  # Lazily initialized
        self._gemini_key_cache: str | None = None  # Cache decrypted key

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def execute(self, user_request: str, context: dict[str, Any] | None = None) -> str:
        """
        Execute a user request using LLM-powered intent classification.

        Falls back to keyword matching if LLM is unavailable.
        """
        context = context or {}

        logger.info("[LLMOrchestrator] Request: %s", user_request[:100])

        # Phase 1: Plan steps using LLM
        steps = self._plan_steps_llm(user_request, context)

        if not steps:
            # Fallback to keyword matching
            logger.info("[LLMOrchestrator] LLM returned no steps, trying keyword fallback")
            steps = self._plan_steps_keyword(user_request, user_request.lower(), context)

        if steps:
            # Phase 2: Execute steps
            results = self._execute_steps(steps)

            # Phase 3: Format response using LLM
            return self._format_response_llm(user_request, steps, results)

        # Final fallback: return a graceful response when nothing works
        logger.warning("[LLMOrchestrator] All planning methods failed — returning fallback response")
        return self._fallback_response()

    # ------------------------------------------------------------------ #
    # LLM Planning                                                        #
    # ------------------------------------------------------------------ #

    def _plan_steps_llm(
        self, request: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Use Gemini to classify intent and plan execution steps.

        Returns a list of steps with: adapter, action, params, description.
        Returns empty list on failure (triggers keyword fallback).
        """
        try:
            client = self._get_client()
        except Exception as e:
            logger.warning("[LLMOrchestrator] Gemini unavailable: %s", e)
            return []

        capabilities = self._build_capability_prompt()
        context_str = self._build_context_string(context)
        history_str = self._build_history_string(context.get("recent_steps", []))

        prompt = PLANNING_PROMPT.format(
            request=request,
            capabilities=capabilities,
            context=context_str,
            history=history_str,
        )

        # Inject memory context before calling Gemini
        try:
            bridge = self._get_memory_bridge()
            if bridge:
                memory_ctx = bridge.build_context(request)
                if memory_ctx:
                    prompt = f"{memory_ctx}\n\n---\n\n{prompt}"
        except Exception:
            pass  # Memory context is optional — don't fail the request

        # Inject pattern learning context
        try:
            learner = self._get_pattern_learner()
            if learner:
                adaptive = learner.get_adaptive_context(request)
                if adaptive:
                    prompt = f"{prompt}\n\n---\nLearned patterns:\n{adaptive}"
        except Exception:
            pass

        for attempt in range(MAX_RETRIES):
            try:
                client = self._get_client()
                response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                text = response.text.strip()
                logger.debug("[LLMOrchestrator] LLM response: %s", text[:500])
                return self._parse_steps_from_response(text)
            except Exception as e:
                error_str = str(e).lower()
                # Check for rate limit (429) — retry with backoff
                if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
                    if attempt < MAX_RETRIES - 1:
                        backoff = INITIAL_BACKOFF * (2 ** attempt)
                        logger.warning(
                            "[LLMOrchestrator] Rate limited (attempt %d/%d), waiting %ds",
                            attempt + 1, MAX_RETRIES, backoff,
                        )
                        time.sleep(backoff)
                        continue
                # Non-rate-limit error or exhausted retries
                logger.warning("[LLMOrchestrator] Gemini call failed: %s", e)
                return []
        return []

    def _parse_steps_from_response(self, text: str) -> list[dict[str, Any]]:
        """Parse JSON steps from LLM response."""
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\})\s*```", text, re.DOTALL)
        json_str = json_match.group(1) if json_match else text.strip()

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("[LLMOrchestrator] Failed to parse JSON from LLM response")
            return []

        # Handle both single step {"adapter": ...} and multiple steps {"steps": [...]}
        if "steps" in parsed:
            steps = parsed["steps"]
        elif "adapter" in parsed:
            steps = [parsed]
        else:
            logger.warning("[LLMOrchestrator] Unexpected LLM response format")
            return []

        # Validate steps
        valid_steps = []
        for step in steps:
            if isinstance(step, dict) and "adapter" in step and "action" in step:
                step["params"] = step.get("params", {})
                step["description"] = step.get("description", f"{step['adapter']}.{step['action']}")
                valid_steps.append(step)

        return valid_steps

    # ------------------------------------------------------------------ #
    # LLM Response Formatting                                            #
    # ------------------------------------------------------------------ #

    def _format_response_llm(
        self, request: str, steps: list[dict], results: list[Any]
    ) -> str:
        """Use Gemini to format execution results into natural language."""
        try:
            client = self._get_client()
        except Exception:
            return self._format_response_fallback(steps, results)

        results_summary = self._build_results_summary(results)

        prompt = RESPONSE_PROMPT.format(
            request=request,
            results_summary=results_summary,
        )

        for attempt in range(MAX_RETRIES):
            try:
                client = self._get_client()
                response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                text = response.text.strip()
                if text:
                    return text
                # Empty response — don't retry formatting, fall through to fallback
                break
            except Exception as e:
                error_str = str(e).lower()
                if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
                    if attempt < MAX_RETRIES - 1:
                        backoff = INITIAL_BACKOFF * (2 ** attempt)
                        logger.warning(
                            "[LLMOrchestrator] Rate limited during formatting "
                            "(attempt %d/%d), waiting %ds",
                            attempt + 1, MAX_RETRIES, backoff,
                        )
                        time.sleep(backoff)
                        continue
                logger.warning("[LLMOrchestrator] Response formatting failed: %s", e)
                break

        return self._format_response_fallback(steps, results)

    def _build_results_summary(self, results: list[Any]) -> str:
        """Build a summary string of all results for the LLM."""
        parts = []
        for i, r in enumerate(results):
            if r is None:
                parts.append(f"Step {i+1}: No result")
                continue
            if isinstance(r, dict):
                # Summarize common result types
                if "emails" in r:
                    emails = r.get("emails", [])
                    parts.append(f"Step {i+1}: Found {len(emails)} emails")
                elif "unread" in r:
                    parts.append(f"Step {i+1}: {r.get('unread', 0)} unread emails")
                elif "events" in r:
                    events = r.get("events", [])
                    parts.append(f"Step {i+1}: {len(events)} calendar events")
                elif "success" in r:
                    status = "succeeded" if r.get("success") else "failed"
                    parts.append(f"Step {i+1}: {status}")
                elif "error" in r:
                    parts.append(f"Step {i+1}: Error - {r.get('error')}")
                else:
                    parts.append(f"Step {i+1}: {str(r)[:100]}")
            elif isinstance(r, str):
                parts.append(f"Step {i+1}: {r[:100]}")
            else:
                parts.append(f"Step {i+1}: {str(r)[:100]}")
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Step Execution                                                      #
    # ------------------------------------------------------------------ #

    def _execute_steps(self, steps: list[dict[str, Any]]) -> list[Any]:
        """Execute steps using the underlying orchestrator.

        Supports parameter substitution from previous step results using
        ${steps[N].result.field} syntax (e.g., ${steps[0].result.id}).
        Also auto-launches apps when WhatsApp/Teams fails due to not being open.
        """
        results = []
        for i, step in enumerate(steps):
            # Resolve ${steps[N].result.field} substitutions from previous results
            resolved_params = self._resolve_params(step.get("params", {}), results)
            step = {**step, "params": resolved_params}

            # Attempt execution
            try:
                result = self._orch._execute_step(step)
            except Exception as e:
                logger.warning("[LLMOrchestrator] Step %d failed: %s", i + 1, e)
                result = {"error": str(e), "success": False}

            # Auto-launch retry for WhatsApp when not connected
            if isinstance(result, dict) and not result.get("success", True):
                if self._is_not_connected_error(result):
                    if self._auto_launch_for_step(step):
                        logger.info("[LLMOrchestrator] Retrying step %d after auto-launch", i + 1)
                        result = self._orch._execute_step(step)

            results.append(result)
        return results

    def _resolve_params(self, params: dict[str, Any], results: list[Any]) -> dict[str, Any]:
        """Resolve ${steps[N].result.field} substitutions in params."""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_value(value, results)
            elif isinstance(value, dict):
                resolved[key] = {k: self._resolve_value(v, results) if isinstance(v, str) else v
                                for k, v in value.items()}
            elif isinstance(value, list):
                resolved[key] = [self._resolve_value(v, results) if isinstance(v, str) else v
                                 for v in value]
            else:
                resolved[key] = value
        return resolved

    def _resolve_value(self, value: str, results: list[Any]) -> str:
        """Resolve a single substitution pattern in a string value.

        Supports ${steps[N].result.field} syntax.
        Replaces only the matched substitution, preserving surrounding text.
        """
        # Use double-backslash strings to produce the correct regex pattern:
        # match: ${steps[N].result.field}
        pattern = "\\$\\{steps\\[(\\d+)\\]\\.result\\.(\\w+)\\}"
        match = re.search(pattern, value)
        if not match:
            return value
        try:
            step_idx = int(match.group(1))
            field = match.group(2)
            if 0 <= step_idx < len(results):
                result = results[step_idx]
                if isinstance(result, dict):
                    field_value = result.get(field)
                    if field_value is not None:
                        # Replace only the matched substitution, not the whole string
                        return value[:match.start()] + str(field_value) + value[match.end():]
            return value
        except (ValueError, IndexError):
            return value

    AUTO_LAUNCH_MAP = {
        "whatsapp": "https://web.whatsapp.com",
        "whatsapp_web": "https://web.whatsapp.com",
    }

    def _is_not_connected_error(self, result: Any) -> bool:
        """Check if a result indicates the app is not connected/open."""
        if not isinstance(result, dict):
            return False
        error = result.get("error", "")
        lower = error.lower()
        # Match only explicit not-connected/session patterns
        triggers = [
            "qr code", "scan it", "scan the qr",
            "session expired", "session invalid",
            "not connected", "not logged in",
            "please scan", "phone not linked",
        ]
        return any(t in lower for t in triggers)

    def _auto_launch_for_step(self, step: dict[str, Any]) -> bool:
        """Attempt to auto-launch the required app for a step."""
        adapter = step.get("adapter", "")
        if adapter not in self.AUTO_LAUNCH_MAP:
            return False
        url = self.AUTO_LAUNCH_MAP[adapter]
        try:
            import webbrowser
            webbrowser.open(url)
            import time
            time.sleep(3)  # Give browser time to open
            logger.info("[LLMOrchestrator] Auto-launched %s at %s", adapter, url)
            return True
        except Exception as e:
            logger.warning("[LLMOrchestrator] Auto-launch failed: %s", e)
            return False

    # ------------------------------------------------------------------ #
    # Keyword Fallback                                                   #
    # ------------------------------------------------------------------ #

    def _plan_steps_keyword(
        self, request: str, request_lower: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Fallback: delegate to keyword-based planning in the base orchestrator."""
        return self._orch._plan_steps(request, request_lower, context)

    def _fallback_response(self) -> str:
        """Called when no steps could be planned at all."""
        return self._orch._fallback_response("")

    # ------------------------------------------------------------------ #
    # Gemini Helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_client(self) -> Any:
        """Get or create the Gemini client using the google.genai Client API."""
        if self._client is None:
            try:
                from google.genai import Client
                self._client = Client(api_key=self._gemini_key)
            except ImportError:
                msg = "google-genai not installed. Run: pip install google-genai"
                raise RuntimeError(msg)
        return self._client

    def _get_memory_bridge(self):
        """Lazily initialize and cache the MemoryBridge."""
        if self._memory_bridge is None:
            try:
                from memory.j_memory import JARVISMemory
                from core.memory_bridge import MemoryBridge
                memory = JARVISMemory()
                memory.initialize()
                self._memory_bridge = MemoryBridge(memory)
            except Exception as e:
                logger.debug(f"[LLMOrchestrator] MemoryBridge unavailable: {e}")
                self._memory_bridge = False  # Mark as unavailable, not None
        return self._memory_bridge if self._memory_bridge else None

    def _get_pattern_learner(self):
        """Lazily initialize and cache the InteractionPatternLearner."""
        if self._pattern_learner is None:
            try:
                from core.pattern_learner import InteractionPatternLearner
                self._pattern_learner = InteractionPatternLearner()
            except Exception as e:
                logger.debug(f"[LLMOrchestrator] PatternLearner unavailable: {e}")
                self._pattern_learner = False  # Mark as unavailable
        return self._pattern_learner if self._pattern_learner else None

    def _get_model(self) -> Any:
        """Get or create the Gemini models interface."""
        if self._model is None:
            self._get_client()
            self._model = self._client.models
        return self._model

    def _get_gemini_key(self) -> str:
        """Get Gemini API key with in-memory caching (avoids repeated Fernet decryption)."""
        if self._gemini_key_cache is not None:
            return self._gemini_key_cache
        try:
            from core.api_key_manager import get_gemini_key
            key = get_gemini_key()
            if key:
                self._gemini_key_cache = key
                return key
        except Exception:
            pass

        # Try environment variable
        key = os.environ.get("GEMINI_API_KEY", "")
        self._gemini_key_cache = key
        return key

    # ------------------------------------------------------------------ #
    # Prompt Building                                                     #
    # ------------------------------------------------------------------ #

    def _build_capability_prompt(self) -> str:
        """Build a prompt fragment listing all available capabilities (cached)."""
        # Build a cache key from current adapter names
        adapter_keys = tuple(sorted(self._orch._adapters.keys()))
        cache_key = str(adapter_keys)

        if cache_key == self._capabilities_cache_key and self._capabilities_cache:
            return self._capabilities_cache

        lines = ["Available actions (ADAPTER.ACTION format):"]
        for name, adapter in self._orch._adapters.items():
            try:
                for cap in adapter.get_capabilities():
                    lines.append(f"  {name}.{cap}")
            except Exception:
                pass
        self._capabilities_cache = "\n".join(lines)
        self._capabilities_cache_key = cache_key
        return self._capabilities_cache

    def _build_context_string(self, context: dict[str, Any]) -> str:
        """Build a context string from the context dict."""
        if not context:
            return "No additional context."

        parts = []
        for key, value in context.items():
            if key in ("recent_steps", "last_email_id"):
                continue  # Handled separately
            if value:
                parts.append(f"- {key}: {str(value)[:200]}")

        return "\n".join(parts) if parts else "No additional context."

    def _build_history_string(self, recent_steps: list[dict]) -> str:
        """Build a string describing recent steps for context."""
        if not recent_steps:
            return "No recent steps."

        lines = []
        for step in recent_steps[-CONTEXT_HISTORY_LIMIT:]:
            desc = step.get("description", f"{step.get('adapter')}.{step.get('action')}")
            lines.append(f"- {desc}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Response Formatting Fallback                                        #
    # ------------------------------------------------------------------ #

    def _format_response_fallback(
        self, steps: list[dict], results: list[Any]
    ) -> str:
        """Fallback response formatter when LLM is unavailable.

        Handles strings (from adapter.execute_action), dicts (ActionResult from
        _execute_step), and StepResult objects (from UniversalOrchestrator.execute).
        Uses smart summarization to avoid reading out long lists item by item.
        """
        if not results:
            return "Done."
        first = results[0]
        if isinstance(first, str):
            # adapter.execute_action returns a human-readable string
            parts = [str(r) for r in results]
            return " | ".join(parts) if parts else "Done."
        if isinstance(first, dict):
            # ActionResult dict from _execute_step: format each with summarization
            summaries = []
            for r in results:
                if isinstance(r, dict):
                    if r.get("success") is False:
                        summaries.append(f"Failed: {r.get('error', 'unknown error')}")
                    else:
                        formatted = self._summarize_result(r)
                        if formatted:
                            summaries.append(formatted)
                else:
                    summaries.append(str(r))
            return " | ".join(summaries) if summaries else "Done."
        # Assume StepResult objects — delegate to orchestrator
        return self._orch._format_response("", steps, results)

    # ------------------------------------------------------------------ #
    # Smart Summarization                                                  #
    # ------------------------------------------------------------------ #

    MAX_TTS_ITEMS = 3  # Never read more than this many items aloud

    def _summarize_result(self, r: dict[str, Any]) -> str:
        """Format a single result dict into a human-friendly summary.

        Designed for TTS: summarizes large lists, reads sender+subject for emails.
        """
        # Handle failure cases (called directly, not from _format_response_fallback)
        if isinstance(r, dict) and r.get("success") is False:
            return f"Failed: {r.get('error', 'unknown error')}"

        data = r.get("data", r)

        # Unread count — the most common query
        if isinstance(data, dict) and "unread" in data:
            unread = data["unread"]
            if unread == 0:
                return "You have no unread emails."
            if unread == 1:
                return "You have 1 unread email."
            return f"You have {unread} unread emails."

        # Email list — summarize by sender, time, and count
        if isinstance(data, dict) and "emails" in data:
            emails = data["emails"]
            if not emails:
                return "No emails found."
            total = len(emails)
            today = self._count_today(emails)
            top = self._top_sender(emails)
            parts = []
            if total <= self.MAX_TTS_ITEMS:
                for e in emails[: self.MAX_TTS_ITEMS]:
                    sender = e.get("sender", "Unknown")
                    subject = e.get("subject", "(no subject)")
                    time_ = e.get("time", "")
                    parts.append(f"{sender}: {subject} {time_}".strip())
                return "; ".join(parts)
            # Large list — summarize
            parts.append(f"{total} emails found")
            if today > 0:
                parts.append(f"{today} from today")
            if top:
                parts.append(f"top sender: {top}")
            return ", ".join(parts)

        # Calendar events — summarize by time
        if isinstance(data, dict) and "events" in data:
            events = data["events"]
            if not events:
                return "No calendar events found."
            total = len(events)
            if total <= self.MAX_TTS_ITEMS:
                times = [e.get("start", "") or e.get("time", "") for e in events]
                times = [t for t in times if t]
                titles = [e.get("subject", e.get("title", "Event")) for e in events]
                parts = [f"{t}: {title}" for t, title in zip(times, titles) if t]
                if parts:
                    return "; ".join(parts)
                return f"{total} events found."
            # Many events — summarize
            times = [e.get("start", "") or e.get("time", "") for e in events]
            times = [t for t in times if t][:3]
            return f"{total} events. {', '.join(times)}" if times else f"{total} events."

        # Generic: prefer data field over raw dict
        if data and data != r:
            return str(data)
        return str(r)

    def _count_today(self, emails: list[dict]) -> int:
        """Count emails with a 'today' indicator."""
        import datetime
        today = datetime.date.today()
        count = 0
        for e in emails:
            date_str = e.get("date") or e.get("time") or ""
            if isinstance(date_str, str) and str(today) in date_str:
                count += 1
        return count

    def _top_sender(self, emails: list[dict]) -> str | None:
        """Return the most common sender name (not email address)."""
        from collections import Counter
        senders = []
        for e in emails:
            sender = e.get("sender", "")
            if sender:
                # Strip email address part if present
                if "<" in sender:
                    sender = sender.split("<")[0].strip()
                senders.append(sender)
        if not senders:
            return None
        by_count = Counter(senders)
        top = by_count.most_common(1)[0]
        if top[1] >= 2:
            return top[0]
        return None


# ======================================================================= #
# PROMPTS                                                                  #
# ======================================================================= #

PLANNING_PROMPT = """
You are the planning module of MARK-XXXV, a Windows personal assistant.

Your job: Given a user request, classify their intent and plan the execution steps.

RULES:
1. Return ONLY valid JSON (no markdown, no explanation)
2. Each step needs: adapter, action, params, description
3. Use ADAPTER.ACTION format for actions
4. Params should match what the action expects
5. Be precise — wrong adapter/action = action fails
6. If the request is ambiguous, make a reasonable guess
7. If you genuinely can't help, return {{}}

Available adapters and their capabilities:
{capabilities}

Context from the session:
{context}

Recent steps (for "reply to that" / "send the same" patterns):
{history}

User request: "{request}"

Respond with a JSON object like:
{{
  "steps": [
    {{
      "adapter": "outlook_native",
      "action": "search_emails",
      "params": {{"query": "John"}},
      "description": "Search for emails from John"
    }}
  ]
}}

Or for a single step:
{{
  "adapter": "system",
  "action": "open_application",
  "params": {{"name": "notepad"}},
  "description": "Open Notepad"
}}
""".strip()

RESPONSE_PROMPT = """
You are the response formatter for MARK-XXXV personal assistant.

Given the user's original request and the results of execution steps,
format a natural, concise response designed for TEXT-TO-SPEECH output.

RULES:
1. Be conversational, not robotic — this is spoken aloud
2. ALWAYS summarize large lists (never read out every item)
3. Emails: "Found N emails, M from today, top sender: John"
4. Calendar: "3 events tomorrow — 9am standup, 2pm review, 5pm sync"
5. If an action failed, explain what happened and suggest a fix
6. Keep it under 3 sentences unless detail is necessary
7. Never output raw JSON, lists with bullets, or table-like formats

User request: "{request}"

Execution results:
{results_summary}

Respond with only the response text (no JSON, no markdown).
""".strip()
