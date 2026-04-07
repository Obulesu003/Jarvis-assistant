"""
Universal Orchestrator — the brain of MARK-XXXV's assistant.

Instead of predefined tools with fixed actions, this orchestrator:
1. Takes ANY natural language request from the user
2. Plans the steps needed to accomplish it
3. Executes using the right adapters and methods
4. Returns a natural language response

No action is too complex or off-menu — it figures out what to do.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from ..base.adapter import BaseIntegrationAdapter

logger = logging.getLogger(__name__)

# Maps orchestrator adapter names to their constructor functions.
# Adapters are instantiated lazily and cached as singletons per orchestrator instance.
_ADAPTER_REGISTRY: dict[str, type] = {}


def register_adapter_class(name: str, cls: type) -> None:
    """Register an adapter class so the orchestrator can instantiate it lazily."""
    _ADAPTER_REGISTRY[name] = cls


class StepResult:
    """Result of a single execution step."""

    def __init__(self, *, step_num: int, success: bool, result: Any = None, error: str = ""):
        self.step_num = step_num
        self.success = success
        self.result = result
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step_num,
            "success": self.success,
            "result": self.result,
            "error": self.error,
        }


class UniversalOrchestrator:
    """
    The central brain. Routes any user request to the right actions,
    chains multiple steps, and returns natural language results.

    Works by:
    - Introspecting all available adapters and their capabilities
    - Matching the user's request to the best action
    - Executing steps in sequence or parallel
    - Aggregating results into a natural response

    Adapters are registered via register_adapter() and instantiated lazily on first use.
    """

    def __init__(self, ui: Any | None = None):
        self.ui: Any | None = ui
        self._adapters: dict[str, BaseIntegrationAdapter] = {}
        self._initialized: bool = False

    # ------------------------------------------------------------------ #
    # Adapter registration                                                #
    # ------------------------------------------------------------------ #

    def register_adapter(self, name: str, adapter: BaseIntegrationAdapter) -> None:
        """Register an already-instantiated adapter."""
        self._adapters[name] = adapter
        try:
            cap_count = len(adapter.get_capabilities())
        except Exception:
            cap_count = 0
        logger.info("[Orchestrator] Registered adapter: %s (%s capabilities)", name, cap_count)

    def get_adapter(self, name: str) -> BaseIntegrationAdapter | None:
        """Get a registered adapter, or lazily instantiate from the registry."""
        if name in self._adapters:
            return self._adapters[name]
        if name in _ADAPTER_REGISTRY:
            adapter = _ADAPTER_REGISTRY[name]()
            self._adapters[name] = adapter
            logger.info("[Orchestrator] Lazy-loaded adapter: %s", name)
            return adapter
        return None

    def list_capabilities(self) -> dict[str, list[str]]:
        """List all available capabilities across all registered adapters."""
        caps: dict[str, list[str]] = {}
        for name, adapter in self._adapters.items():
            try:
                caps[name] = adapter.get_capabilities()
            except Exception:
                caps[name] = []
        # Also include registry entries not yet instantiated
        for name in _ADAPTER_REGISTRY:
            if name not in caps:
                caps[name] = []
        return caps

    def _build_capability_prompt(self) -> str:
        """Build a capability summary for the LLM to reason with."""
        lines = ["Available actions (ADAPTER.ACTION format):"]
        for name, adapter in self._adapters.items():
            try:
                for cap in adapter.get_capabilities():
                    lines.append(f"  {name}.{cap}")
            except Exception:
                pass
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Core execution                                                     #
    # ------------------------------------------------------------------ #

    def execute(self, user_request: str, context: dict[str, Any] | None = None) -> str:
        """
        Execute a user request. This is the main entry point.

        Args:
            user_request: Natural language request from the user
            context: Optional context (recent emails, current window, etc.)

        Returns:
            Natural language result string
        """
        context = context or {}
        user_lower = user_request.lower()

        logger.info("[Orchestrator] Request: %s", user_request[:100])

        # Phase 1: Plan steps
        steps = self._plan_steps(user_request, user_lower, context)

        if not steps:
            return self._fallback_response(user_request)

        # Phase 2: Execute steps
        results: list[StepResult] = []
        for i, step in enumerate(steps):
            step_num = i + 1
            try:
                result = self._execute_step(step)
                results.append(StepResult(step_num=step_num, success=True, result=result))
            except Exception as e:
                logger.exception("[Orchestrator] Step %d failed: %s", step_num, step)
                results.append(StepResult(step_num=step_num, success=False, error=str(e)))

        # Phase 3: Format response
        return self._format_response(user_request, steps, results)

    # ------------------------------------------------------------------ #
    # Planning                                                          #
    # ------------------------------------------------------------------ #

    def _plan_steps(
        self, request: str, request_lower: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Plan the execution steps for a request.
        Returns a list of steps, each with: adapter, action, params.
        """
        steps: list[dict[str, Any]] = []
        rl = request_lower

        # ================================================================ #
        # EMAIL OPERATIONS                                                #
        # ================================================================ #

        # Unread count
        if any(kw in rl for kw in ["how many unread", "unread count", "how many new email", "new email count", "got new email"]):
            steps.append({
                "adapter": "outlook_native",
                "action": "get_unread_count",
                "params": {},
                "description": "Get unread email count",
            })
            return steps

        # List emails
        if any(kw in rl for kw in ["list my email", "show my email", "show me email", "read my email", "latest emails", "recent emails", "my emails"]):
            unread_only = "unread" in rl
            steps.append({
                "adapter": "outlook_native",
                "action": "list_emails",
                "params": {"folder": "Inbox", "max_results": 20, "unread_only": unread_only},
                "description": "List recent emails",
            })
            return steps

        # Check emails (but NOT for reminder/schedule requests)
        if "check email" in rl and not any(kw in rl for kw in ["remind", "reminder", "schedule me", "set reminder", "every morning", "every evening", "every night", "every day", "every weekday", "every hour"]):
            unread_only = "unread" in rl
            steps.append({
                "adapter": "outlook_native",
                "action": "list_emails",
                "params": {"folder": "Inbox", "max_results": 20, "unread_only": unread_only},
                "description": "Check emails",
            })
            return steps
        if "search email" in rl or "find email" in rl or "emails about" in rl:
            query = self._extract_search_query(request, request_lower)
            steps.append({
                "adapter": "outlook_native",
                "action": "search_emails",
                "params": {"query": query, "max_results": 10},
                "description": f"Search emails for '{query}'",
            })
            return steps

        # Send email
        if any(kw in rl for kw in ["send email", "send an email", "write email", "compose email", "email to"]):
            params = self._extract_email_params(request)
            steps.append({
                "adapter": "outlook_native",
                "action": "send_email",
                "params": params,
                "description": f"Send email to {params.get('to', 'recipient')}",
            })
            return steps

        # Reply to email
        if any(kw in rl for kw in ["reply to", "reply this email", "reply email"]):
            email_id = context.get("last_email_id")
            if email_id:
                body = self._extract_reply_body(request)
                steps.append({
                    "adapter": "outlook_native",
                    "action": "reply_email",
                    "params": {"email_id": email_id, "body": body, "reply_all": "reply all" in rl},
                    "description": "Reply to email",
                })
            else:
                steps.append({
                    "adapter": "outlook_native",
                    "action": "search_emails",
                    "params": {"query": request, "max_results": 5},
                    "description": "Find email to reply to",
                })
            return steps

        # Read a specific email (by subject or sender)
        if any(kw in rl for kw in ["read email from", "open email from", "show email from"]):
            query = self._extract_after_prefix(rl, ["read email from", "open email from", "show email from"])
            steps.append({
                "adapter": "outlook_native",
                "action": "search_emails",
                "params": {"query": query, "max_results": 3},
                "description": f"Find email from '{query}'",
            })
            return steps

        # ================================================================ #
        # SCHEDULER                                                     #
        # ================================================================ #

        # "what schedules do I have" / "list reminders" → list schedules
        if any(kw in rl for kw in [
            "what schedules", "list schedules", "list reminders",
            "my reminders", "show schedules", "show reminders",
            "what reminders",
        ]):
            steps.append({
                "adapter": "scheduler",
                "action": "list_schedules",
                "params": {},
                "description": "List all schedules",
            })
            return steps

        # "delete/remind/cancel schedule/reminder X" → remove
        if any(kw in rl for kw in [
            "delete reminder", "cancel reminder", "remove reminder",
            "delete schedule", "cancel schedule", "remove schedule",
            "stop reminder", "stop schedule",
        ]):
            goal = self._extract_reminder_goal(request, rl)
            steps.append({
                "adapter": "scheduler",
                "action": "remove_schedule",
                "params": {"goal": goal},
                "description": f"Remove schedule: {goal}",
            })
            return steps

        # "remind me" / "schedule" → add schedule
        # NOTE: placed BEFORE calendar to catch "remind me" patterns that shouldn't
        # be confused with calendar events. Must come before the "schedule" keyword
        # in the Calendar section below.
        if any(kw in rl for kw in [
            "remind me", "set a reminder", "set reminder",
            "schedule me", "schedule task", "every morning",
            "every evening", "every night", "every day",
            "every weekday", "every hour",
        ]):
            params = self._extract_schedule_params(request, rl)
            steps.append({
                "adapter": "scheduler",
                "action": "add_schedule",
                "params": params,
                "description": f"Schedule: {params.get('goal', 'reminder')}",
            })
            return steps

        # ================================================================ #
        # CALENDAR OPERATIONS                                             #
        # ================================================================ #

        if any(kw in rl for kw in ["calendar", "meeting", "appointments"]):
            if "today" in rl:
                steps.append({
                    "adapter": "outlook_native",
                    "action": "list_calendar_events",
                    "params": {"start_date": self._today_str(), "end_date": self._today_str(), "max_results": 20},
                    "description": "Today's calendar",
                })
            elif "tomorrow" in rl:
                steps.append({
                    "adapter": "outlook_native",
                    "action": "list_calendar_events",
                    "params": {"start_date": self._tomorrow_str(), "end_date": self._tomorrow_str(), "max_results": 20},
                    "description": "Tomorrow's calendar",
                })
            else:
                steps.append({
                    "adapter": "outlook_native",
                    "action": "list_calendar_events",
                    "params": {"max_results": 20},
                    "description": "Upcoming calendar events",
                })

            # If also creating an event
            if any(kw in rl for kw in ["create", "schedule", "add"]):
                event_params = self._extract_event_params(request)
                steps.append({
                    "adapter": "outlook_native",
                    "action": "create_calendar_event",
                    "params": event_params,
                    "description": f"Create event: {event_params.get('title', '')}",
                })
            return steps

        # ================================================================ #
        # WHATSAPP OPERATIONS                                             #
        # ================================================================ #

        if "whatsapp" in rl or "whats app" in rl:
            if "send" in rl and ("message" in rl or "to " in rl):
                params = self._extract_whatsapp_params(request)
                steps.append({
                    "adapter": "whatsapp",
                    "action": "send_message",
                    "params": params,
                    "description": f"Send WhatsApp to {params.get('receiver', 'contact')}",
                })
                return steps

            if "message" in rl or "chat" in rl or "conversation" in rl:
                query = self._extract_whatsapp_chat_query(rl)
                steps.append({
                    "adapter": "whatsapp",
                    "action": "get_chat_history",
                    "params": {"chat_name": query, "limit": 20},
                    "description": f"Get WhatsApp chat with {query}",
                })
                return steps

        # ================================================================ #
        # SYSTEM / APP OPERATIONS                                         #
        # ================================================================ #

        # File Explorer must be checked BEFORE generic "open" to avoid "explorer" being
        # treated as an app name (it would route to open_application instead).
        if "file explorer" in rl or ("open" in rl and ("folder" in rl or "directory" in rl)):
            path = self._extract_path(request)
            steps.append({
                "adapter": "windows_app",
                "action": "explorer_navigate",
                "params": {"path": path or "This PC"},
                "description": f"Open File Explorer at {path or 'This PC'}",
            })
            return steps

        if any(kw in rl for kw in ["open", "launch", "start", "run"]):
            app_name = self._extract_app_name(request)
            if app_name:
                steps.append({
                    "adapter": "system",
                    "action": "open_application",
                    "params": {"name": app_name},
                    "description": f"Open {app_name}",
                })
                return steps

        if "install" in rl:
            app_name = self._extract_app_name(request)
            if app_name:
                steps.append({
                    "adapter": "system",
                    "action": "install_app",
                    "params": {"name": app_name},
                    "description": f"Install {app_name}",
                })
                return steps

        if any(kw in rl for kw in ["close", "quit", "kill"]) and not any(kw in rl for kw in ["email", "app"]):
            app_name = self._extract_app_name(request)
            if app_name:
                steps.append({
                    "adapter": "system",
                    "action": "close_application",
                    "params": {"name": app_name},
                    "description": f"Close {app_name}",
                })
                return steps

        if "running" in rl and any(kw in rl for kw in ["apps", "windows", "programs"]):
            steps.append({
                "adapter": "system",
                "action": "list_running_apps",
                "params": {},
                "description": "List running apps",
            })
            return steps

        if any(kw in rl for kw in ["system info", "cpu", "memory", "disk"]):
            steps.append({
                "adapter": "system",
                "action": "get_system_info",
                "params": {},
                "description": "Get system info",
            })
            return steps

        # ================================================================ #
        # TEAMS OPERATIONS                                                #
        # ================================================================ #

        if "teams" in rl:
            if "send" in rl or "message" in rl:
                params = self._extract_teams_params(request)
                steps.append({
                    "adapter": "windows_app",
                    "action": "teams_send_message",
                    "params": params,
                    "description": f"Send Teams message to {params.get('recipient', 'contact')}",
                })
                return steps

            if "join" in rl and "meeting" in rl:
                meeting_link = context.get("meeting_link", "")
                steps.append({
                    "adapter": "windows_app",
                    "action": "teams_join_meeting",
                    "params": {"meeting_link": meeting_link},
                    "description": "Join Teams meeting",
                })
                return steps

        # ================================================================ #
        # FILE / NOTEPAD OPERATIONS                                       #
        # ================================================================ #

        if "notepad" in rl or ("read" in rl and "file" in rl) or ("open" in rl and "file" in rl):
            file_path = self._extract_file_path(request)
            if file_path:
                steps.append({
                    "adapter": "system",
                    "action": "run_command",
                    "params": {"command": f'notepad.exe "{file_path}"'},
                    "description": f"Open file in Notepad: {file_path}",
                })
                return steps

        # ================================================================ #
        # CONTACTS                                                       #
        # ================================================================ #

        if any(kw in rl for kw in ["contact", "phone number", "email address", "find person"]):
            query = self._extract_contact_query(request)
            steps.append({
                "adapter": "contacts",
                "action": "search_contacts",
                "params": {"query": query},
                "description": f"Find contact: {query}",
            })
            return steps

        # ================================================================ #
        # WEB SEARCH / GENERAL                                           #
        # ================================================================ #

        if any(kw in rl for kw in ["search for", "look up", "google", "what is", "who is", "where is", "how to"]):
            query = self._extract_search_query(request, request_lower)
            steps.append({
                "adapter": "web_search",
                "action": "search",
                "params": {"query": query},
                "description": f"Web search: {query}",
            })
            return steps

        # ================================================================ #
        # CUSTOM SHELL COMMANDS                                           #
        # ================================================================ #

        if any(kw in rl for kw in ["run ", "execute ", "cmd ", "powershell ", "terminal"]):
            cmd = self._extract_after_prefix(rl, ["run ", "execute ", "cmd ", "powershell ", "terminal "])
            steps.append({
                "adapter": "system",
                "action": "run_command",
                "params": {"command": cmd, "timeout": 60},
                "description": f"Run: {cmd[:50]}",
            })
            return steps

        return []

    # ------------------------------------------------------------------ #
    # Step execution                                                     #
    # ------------------------------------------------------------------ #

    def _execute_step(self, step: dict[str, Any]) -> Any:
        """Execute a single step, using a cached adapter instance."""
        adapter_name = step["adapter"]
        action = step["action"]
        params = step.get("params", {})

        adapter = self.get_adapter(adapter_name)
        if adapter is None:
            msg = f"No adapter registered: {adapter_name}"
            raise ValueError(msg)

        return adapter.execute_action(action, **params)

    # ------------------------------------------------------------------ #
    # Response formatting                                               #
    # ------------------------------------------------------------------ #

    def _format_response(
        self, request: str, steps: list[dict[str, Any]], results: list[StepResult]
    ) -> str:
        """Format execution results into a natural language response."""
        if not results:
            return "I couldn't figure out how to do that. Could you rephrase?"

        all_failed = all(not r.success for r in results)
        if all_failed:
            return (
                f"I tried to {steps[0]['description']}, but ran into an error: "
                f"{results[0].error}"
            )

        parts: list[str] = []
        for step_result in results:
            if not step_result.success:
                continue
            r = step_result.result
            if r is None:
                continue

            formatted = self._format_single_result(r)
            if formatted:
                parts.append(formatted)

        if not parts:
            return "Done."

        return "\n".join(parts)

    def _format_single_result(self, r: Any) -> str | None:
        """Format a single result value into a string."""
        if isinstance(r, str) and r and not r.startswith("Failed:"):
            return r

        if isinstance(r, dict):
            if not r:
                return None  # Empty dict has nothing useful to report
            # Email list
            if "emails" in r:
                emails = r["emails"]
                if not emails:
                    return "No emails found."
                lines = []
                for e in emails[:10]:
                    unread = "[NEW] " if e.get("unread") else ""
                    sender = e.get("sender", "?")
                    subject = e.get("subject", "(no subject)")
                    received = self._format_time(e.get("received", ""))
                    lines.append(f"  {unread}From: {sender}")
                    lines.append(f"  Subject: {subject}")
                    lines.append(f"  {received}")
                    preview = e.get("preview", "")
                    if preview:
                        lines.append(f"  Preview: {preview[:80]}")
                    lines.append("")
                return "Here are your emails:\n" + "\n".join(lines)

            # Unread count
            if "unread" in r:
                count = r["unread"]
                folder = r.get("folder", "Inbox")
                if count == 0:
                    return f"You have no unread emails in {folder}."
                if count == 1:
                    return f"You have 1 unread email in {folder}."
                return f"You have {count} unread emails in {folder}."

            # Search results
            if "results" in r:
                results_list = r["results"]
                if not results_list:
                    return "No emails found matching your search."
                parts = [f"Found {len(results_list)} emails:"]
                for e in results_list[:5]:
                    parts.append(
                        f"  - From {e.get('sender', '?')}: {e.get('subject', '?')} "
                        f"({self._format_time(e.get('received', ''))})"
                    )
                return "\n".join(parts)

            # Calendar events
            if "events" in r:
                events = r["events"]
                if not events:
                    return "No events scheduled."
                lines = []
                for ev in events[:10]:
                    title = ev.get("title", "No title")
                    start = self._format_datetime(ev.get("start", ""))
                    location = ev.get("location", "")
                    line = f"  - {title} at {start}"
                    if location:
                        line += f" ({location})"
                    lines.append(line)
                return "Your upcoming events:\n" + "\n".join(lines)

            # Running apps
            if "apps" in r:
                apps = r["apps"]
                if not apps:
                    return "No applications found."
                lines = [f"{len(apps)} apps running:"]
                for app in apps[:30]:
                    lines.append(f"  - {app['name']}")
                return "\n".join(lines)

            # System info
            if "cpu_percent" in r:
                lines = [
                    "System status:",
                    f"  CPU: {r.get('cpu_percent', '?')}%",
                    f"  Memory: {r.get('memory_used_gb', '?')}GB / "
                    f"{r.get('memory_total_gb', '?')}GB ({r.get('memory_percent', '?')}%)",
                    f"  Disk: {r.get('disk_used_gb', '?')}GB / "
                    f"{r.get('disk_total_gb', '?')}GB ({r.get('disk_percent', '?')}%)",
                ]
                return "\n".join(lines)

            # Email sent
            if r.get("sent"):
                return f"Email sent to {r.get('to', 'recipient')} with subject: {r.get('subject', '')}"

            # Generic fields
            for key, label in [
                ("downloaded", "Downloaded to:"),
                ("installed", "Installed:"),
                ("opened", "Opened:"),
                ("closed", "Closed:"),
            ]:
                if key in r:
                    return f"{label} {r.get(key)}"

        s = str(r) if r is not None else ""
        if s and s not in ("None", "Done."):
            return s

        return None

    def _fallback_response(self, request: str) -> str:
        """Called when no steps could be planned."""
        capabilities = self.list_capabilities()
        available: list[str] = []
        for name, caps in capabilities.items():
            available.extend([f"{name}.{c}" for c in caps])

        return (
            "I'm not sure how to do that yet. I understand requests like:\n"
            "  - 'How many unread emails do I have?'\n"
            "  - 'List my recent emails'\n"
            "  - 'Send an email to John about the project'\n"
            "  - \"What's on my calendar today?\"\n"
            "  - 'Send a WhatsApp message to Mom'\n"
            "  - 'Open Notepad'\n"
            "  - 'Show running apps'\n"
            "  - 'Install VS Code'\n"
            "  - 'Search for hotels in Istanbul'\n\n"
            f"I have {len(available)} total actions available. Try rephrasing your request."
        )

    # ------------------------------------------------------------------ #
    # Extractors                                                         #
    # ------------------------------------------------------------------ #

    def _extract_search_query(self, request: str, request_lower: str) -> str:
        """Extract search query from a request."""
        for prefix in ["search for ", "look up ", "google ", "search emails about ", "find emails about "]:
            if prefix in request_lower:
                return request_lower.split(prefix)[1].strip().rstrip("?.,")
        return request

    def _extract_after_prefix(self, text: str, prefixes: list[str]) -> str:
        """Extract text after the first matching prefix."""
        for prefix in prefixes:
            if prefix in text:
                return text.split(prefix)[1].strip().rstrip("?.,")
        return text

    def _extract_email_params(self, request: str) -> dict[str, str]:
        """Extract to, subject, body from a send email request."""
        params: dict[str, str] = {}

        to_match = re.search(
            r"(?:to|email to|send (?:an )?email to)\s+([^,\n?]+)", request, re.IGNORECASE
        )
        if to_match:
            params["to"] = to_match.group(1).strip()

        about_match = re.search(r"(?:about|subject:)\s+([^\n?]+)", request, re.IGNORECASE)
        if about_match:
            params["subject"] = about_match.group(1).strip().strip('"')
        else:
            remaining = request
            for prefix in ["send email", "send an email", "write email", "compose email"]:
                if prefix in request.lower():
                    remaining = request.lower().split(prefix)[1].strip()
                    break
            if params.get("to"):
                for t in [params["to"], ","]:
                    if t in remaining:
                        remaining = remaining.split(t)[1].strip()
            params["body"] = remaining
            params["subject"] = remaining[:80] if remaining else "No subject"

        return params

    def _extract_event_params(self, request: str) -> dict[str, str]:
        """Extract calendar event params."""
        params: dict[str, str] = {}
        for prefix in ["create event ", "schedule ", "schedule a meeting ", "add to calendar "]:
            if prefix in request.lower():
                params["title"] = request.lower().split(prefix)[1].strip().rstrip(".")
                break
        if not params.get("title"):
            params["title"] = request[:60]
        return params

    def _extract_whatsapp_params(self, request: str) -> dict[str, str]:
        """Extract receiver and message from WhatsApp request."""
        params: dict[str, str] = {}
        match = re.search(r"(?:to|whatsapp)\s+(\w+)\s*[:\-]\s*(.+)", request, re.IGNORECASE)
        if match:
            params["receiver"] = match.group(1)
            params["message"] = match.group(2)
        else:
            match2 = re.search(r"(?:to|send to)\s+(\w+)\s+(.+)", request, re.IGNORECASE)
            if match2:
                params["receiver"] = match2.group(1)
                params["message"] = match2.group(2)
        return params

    def _extract_whatsapp_chat_query(self, request_lower: str) -> str:
        """Extract chat name from WhatsApp chat request."""
        if "from" in request_lower:
            return request_lower.split("from")[1].strip().split()[0]
        if "with" in request_lower:
            return request_lower.split("with")[1].strip().split()[0]
        return ""

    def _extract_teams_params(self, request: str) -> dict[str, str]:
        """Extract Teams recipient and message."""
        params: dict[str, str] = {}
        match = re.search(
            r"(?:teams|on teams)\s+(?:to|message)\s+(\w+)\s*[:\-]?\s*(.+)", request, re.IGNORECASE
        )
        if match:
            params["recipient"] = match.group(1)
            params["message"] = match.group(2)
        return params

    def _extract_app_name(self, request: str) -> str:
        """Extract app name from request."""
        for prefix in ["open ", "launch ", "start ", "run ", "close ", "quit ", "kill ", "install "]:
            if prefix in request.lower():
                return request.lower().split(prefix)[1].strip().rstrip(".,?!")
        return ""

    def _extract_file_path(self, request: str) -> str:
        """Extract file path from request."""
        match = re.search(r'"([^"]+\.\w+)"', request)
        if match:
            return match.group(1)
        return ""

    def _extract_path(self, request: str) -> str:
        """Extract folder path from request."""
        match = re.search(r'(?:folder|directory|at|to)\s+"([^"]+)"', request)
        if match:
            return match.group(1)
        match2 = re.search(r'(?:folder|directory|at|to)\s+(\S+)', request)
        if match2:
            return match2.group(1)
        return ""

    def _extract_contact_query(self, request: str) -> str:
        """Extract contact search query."""
        for prefix in ["contact ", "find ", "phone number of ", "email of ", "email address of "]:
            if prefix in request.lower():
                return request.lower().split(prefix)[1].strip().rstrip("?.,")
        return request

    def _extract_reply_body(self, request: str) -> str:
        """Extract reply body."""
        for prefix in ["reply ", "reply with ", "say "]:
            if prefix in request.lower():
                return request.lower().split(prefix)[1].strip()
        return ""

    def _extract_reminder_goal(self, request: str, request_lower: str) -> str:
        """Extract the goal/task from a delete-reminder request."""
        # "delete reminder to/check emails" → "check emails"
        for prefix in [
            "delete reminder ", "cancel reminder ", "remove reminder ",
            "delete schedule ", "cancel schedule ", "remove schedule ",
            "stop reminder ", "stop schedule ",
        ]:
            if prefix in request_lower:
                goal = request_lower.split(prefix)[1].strip().rstrip("?.,")
                # Strip leading "to " that often follows "reminder to X"
                if goal.startswith("to "):
                    goal = goal[3:]
                return goal
        # Try more generic extraction
        for prefix in ["reminder ", "schedule "]:
            if prefix in request_lower:
                after = request_lower.split(prefix, 1)[1].strip()
                # Remove leading "to" if present
                if after.startswith("to "):
                    after = after[3:]
                return after.rstrip("?.,")
        return request

    def _extract_schedule_params(self, request: str, request_lower: str) -> dict[str, Any]:
        """Extract goal, time, and schedule type from a reminder request."""
        params: dict[str, Any] = {"schedule": "daily"}

        # Extract goal (the thing to be reminded about)
        goal = ""
        for prefix in [
            "remind me ", "set a reminder ", "set reminder ",
            "reminder to ", "remind me to ",
        ]:
            if prefix in request_lower:
                raw = request_lower.split(prefix)[1].strip()
                # Strip schedule period first (before looking for stop markers)
                for period in ["every morning ", "every evening ", "every night ", "every day ", "every hour ", "daily ", "hourly "]:
                    if period in raw:
                        raw = raw.replace(period, " ").strip()
                # Stop at time/schedule markers (NOT " every " — that's part of schedule type)
                for stop in [" at ", " in the ", " on "]:
                    if stop in raw:
                        goal = raw.split(stop)[0].strip()
                        break
                if not goal:
                    goal = raw.rstrip("?.,")
                if not goal:
                    goal = raw.rstrip("?.,")
                # Strip leading "to " that follows "remind me to X"
                if goal.startswith("to "):
                    goal = goal[3:]
                break
        if not goal:
            # Try "schedule task" / "schedule me" patterns
            for prefix in ["schedule task ", "schedule me ", "schedule "]:
                if prefix in request_lower:
                    goal = request_lower.split(prefix)[1].strip().rstrip("?.,")
                    break
        if not goal:
            goal = request

        params["goal"] = goal

        # Extract time (HH:MM format)
        time_match = re.search(r"at\s+(\d{1,2})[:.]?(\d{2})?\s*(am|pm)?", request, re.IGNORECASE)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or "0")
            meridian = time_match.group(3) or ""
            if meridian.lower() == "pm" and hour < 12:
                hour += 12
            elif meridian.lower() == "am" and hour == 12:
                hour = 0
            params["time"] = f"{hour:02d}:{minute:02d}"
        else:
            # Default: 8am for morning, 6pm for evening/night
            if any(w in request_lower for w in ["every morning", "in the morning"]):
                params["time"] = "08:00"
            elif any(w in request_lower for w in ["every evening", "every night", "at night"]):
                params["time"] = "20:00"
            elif "every hour" in request_lower:
                params["schedule"] = "interval"
                params["interval"] = 60
                return params

        # Determine schedule type
        if "every weekday" in request_lower or "weekdays" in request_lower:
            params["schedule"] = "weekly"
            params["days"] = "Mon,Tue,Wed,Thu,Fri"
        elif "every week" in request_lower or "weekly" in request_lower:
            params["schedule"] = "weekly"
            params["days"] = "Mon"
        elif "every hour" in request_lower:
            params["schedule"] = "interval"
            params["interval"] = 60
        elif "every day" in request_lower or "daily" in request_lower:
            params["schedule"] = "daily"
        else:
            params["schedule"] = "daily"

        return params

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _tomorrow_str(self) -> str:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    def _format_time(self, t: str) -> str:
        """Format a datetime string for display."""
        if not t:
            return ""
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            return dt.strftime("%b %d, %I:%M %p")
        except Exception:
            return t

    def _format_datetime(self, t: str) -> str:
        """Format a datetime string for events."""
        if not t:
            return "TBD"
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            return dt.strftime("%b %d, %I:%M %p")
        except Exception:
            return t
