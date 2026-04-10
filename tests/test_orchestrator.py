"""Tests for integrations.core.universal_orchestrator."""
from unittest.mock import MagicMock

import pytest


class TestUniversalOrchestrator:
    """Test cases for UniversalOrchestrator."""

    @pytest.fixture
    def orchestrator(self):
        from integrations.core.universal_orchestrator import UniversalOrchestrator
        return UniversalOrchestrator()

    # ── Adapter Registration ────────────────────────────────────────

    def test_register_adapter(self, orchestrator):
        mock_adapter = MagicMock()
        mock_adapter.get_capabilities.return_value = ["action1", "action2"]
        orchestrator.register_adapter("test_adapter", mock_adapter)
        assert orchestrator.get_adapter("test_adapter") is mock_adapter

    def test_get_adapter_not_found(self, orchestrator):
        assert orchestrator.get_adapter("nonexistent") is None

    def test_list_capabilities(self, orchestrator):
        mock_adapter = MagicMock()
        mock_adapter.get_capabilities.return_value = ["a", "b"]
        orchestrator.register_adapter("foo", mock_adapter)
        caps = orchestrator.list_capabilities()
        assert caps["foo"] == ["a", "b"]

    def test_list_capabilities_handles_exception(self, orchestrator):
        mock_adapter = MagicMock()
        mock_adapter.get_capabilities.side_effect = RuntimeError("boom")
        orchestrator.register_adapter("bad", mock_adapter)
        caps = orchestrator.list_capabilities()
        assert caps["bad"] == []

    def test_build_capability_prompt(self, orchestrator):
        mock_adapter = MagicMock()
        mock_adapter.get_capabilities.return_value = ["send", "receive"]
        orchestrator.register_adapter("msg", mock_adapter)
        prompt = orchestrator._build_capability_prompt()
        assert "msg.send" in prompt
        assert "msg.receive" in prompt

    # ── Email Operations ────────────────────────────────────────────

    @pytest.mark.parametrize("request_text,expected_action", [
        ("how many unread emails do I have", "get_unread_count"),
        ("unread count", "get_unread_count"),
        ("new email count", "get_unread_count"),
    ])
    def test_unread_count_routing(self, orchestrator, request_text, expected_action):
        steps = orchestrator._plan_steps(request_text, request_text.lower(), {})
        assert len(steps) == 1
        assert steps[0]["action"] == expected_action
        assert steps[0]["adapter"] == "outlook_native"

    @pytest.mark.parametrize("request_text,expected_action", [
        ("list my recent emails", "list_emails"),
        ("show my emails", "list_emails"),
        ("read my email", "list_emails"),
        ("my emails", "list_emails"),
    ])
    def test_list_emails_routing(self, orchestrator, request_text, expected_action):
        steps = orchestrator._plan_steps(request_text, request_text.lower(), {})
        assert len(steps) == 1
        assert steps[0]["action"] == expected_action

    def test_search_email_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "search emails about project deadline", "search emails about project deadline", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "search_emails"
        assert "project deadline" in steps[0]["params"]["query"]

    def test_send_email_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "send an email to John about the project", "send an email to john about the project", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "send_email"
        assert steps[0]["adapter"] == "outlook_native"

    def test_reply_email_routing_with_context(self, orchestrator):
        steps = orchestrator._plan_steps(
            "reply to this email", "reply to this email", {},
        )
        assert len(steps) == 1

    def test_read_email_from_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "read email from Sarah", "read email from sarah", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "search_emails"

    # ── Calendar Operations ──────────────────────────────────────────

    def test_calendar_today_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "what's on my calendar today", "what's on my calendar today", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "list_calendar_events"

    def test_calendar_tomorrow_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "meeting schedule tomorrow", "meeting schedule tomorrow", {}
        )
        # "schedule" triggers both list + create steps
        assert len(steps) == 2
        actions = [s["action"] for s in steps]
        assert "list_calendar_events" in actions
        assert "create_calendar_event" in actions

    def test_create_meeting_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "schedule a meeting with team on friday", "schedule a meeting with team on friday", {}
        )
        assert len(steps) >= 1
        # Should have list + create steps
        actions = [s["action"] for s in steps]
        assert "list_calendar_events" in actions
        assert "create_calendar_event" in actions

    # ── WhatsApp Operations ───────────────────────────────────────────

    def test_whatsapp_send_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "send whatsapp message to Mom: hello", "send whatsapp message to mom: hello", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "send_message"
        assert steps[0]["adapter"] == "whatsapp"

    def test_whatsapp_chat_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "get whatsapp chat with John", "get whatsapp chat with john", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "get_chat_history"

    # ── System Operations ───────────────────────────────────────────

    def test_open_app_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "open VS Code", "open vs code", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "open_application"
        assert steps[0]["adapter"] == "system"

    def test_install_app_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "install Discord", "install discord", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "install_app"

    def test_close_app_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "close Spotify", "close spotify", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "close_application"

    def test_running_apps_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "show running apps", "show running apps", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "list_running_apps"

    def test_system_info_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "show system info", "show system info", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "get_system_info"

    # ── Teams Operations ─────────────────────────────────────────────

    def test_teams_send_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "send teams message to Alice: hello team", "send teams message to alice: hello team", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "teams_send_message"
        assert steps[0]["adapter"] == "windows_app"

    # ── File Operations ─────────────────────────────────────────────

    def test_file_explorer_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "open File Explorer to Documents", "open file explorer to documents", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "explorer_navigate"

    # ── Contact Operations ───────────────────────────────────────────

    def test_contact_search_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "find contact John Smith", "find contact john smith", {}
        )
        assert len(steps) == 1
        assert steps[0]["action"] == "search_contacts"

    # ── Web Search ──────────────────────────────────────────────────

    def test_web_search_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "search for best restaurants in Istanbul", "search for best restaurants in istanbul", {}
        )
        assert len(steps) == 1
        assert steps[0]["adapter"] == "web_search"
        assert steps[0]["action"] == "search"

    def test_google_routing(self, orchestrator):
        steps = orchestrator._plan_steps(
            "google python tutorial", "google python tutorial", {}
        )
        assert len(steps) == 1
        assert steps[0]["adapter"] == "web_search"

    # ── No Match (Fallback) ─────────────────────────────────────────

    def test_no_match_returns_empty(self, orchestrator):
        steps = orchestrator._plan_steps(
            "completely gibberish nonsense xyz", "completely gibberish nonsense xyz", {}
        )
        assert steps == []

    # ── Response Formatting ─────────────────────────────────────────

    def test_format_response_no_results(self, orchestrator):
        result = orchestrator._format_response("test", [], [])
        assert "couldn't figure out" in result.lower()

    def test_format_response_all_failures(self, orchestrator):
        from integrations.core.universal_orchestrator import StepResult
        result = orchestrator._format_response(
            "test",
            [{"description": "do thing"}],
            [StepResult(step_num=1, success=False, error="it broke")],
        )
        assert "error" in result.lower() or "broke" in result.lower()

    def test_format_response_done(self, orchestrator):
        from integrations.core.universal_orchestrator import StepResult
        result = orchestrator._format_response(
            "test",
            [{"description": "x"}],
            [StepResult(step_num=1, success=True)],
        )
        assert result == "Done."

    def test_format_response_dict_no_emails(self, orchestrator):
        from integrations.core.universal_orchestrator import StepResult
        result = orchestrator._format_response(
            "test",
            [{"description": "x"}],
            [StepResult(step_num=1, success=True, result={})],
        )
        assert result == "Done."

    def test_format_response_generic_string(self, orchestrator):
        from integrations.core.universal_orchestrator import StepResult
        result = orchestrator._format_response(
            "test",
            [{"description": "x"}],
            [StepResult(step_num=1, success=True, result="Some meaningful result")],
        )
        assert "Some meaningful result" in result

    def test_format_response_none_result(self, orchestrator):
        from integrations.core.universal_orchestrator import StepResult
        result = orchestrator._format_response(
            "test",
            [{"description": "x"}],
            [StepResult(step_num=1, success=True, result=None)],
        )
        assert result == "Done."

    # ── Extractors ──────────────────────────────────────────────────

    def test_extract_email_params_to(self, orchestrator):
        params = orchestrator._extract_email_params("send email to john@example.com about the project")
        assert "john@example.com" in params.get("to", "")

    def test_extract_event_params_title(self, orchestrator):
        params = orchestrator._extract_event_params("schedule a meeting with team")
        assert params.get("title") is not None

    def test_extract_whatsapp_params(self, orchestrator):
        params = orchestrator._extract_whatsapp_params("whatsapp mom: how are you")
        assert params.get("receiver") is not None
        assert params.get("message") is not None

    def test_extract_app_name(self, orchestrator):
        assert orchestrator._extract_app_name("open Notepad") == "notepad"
        assert orchestrator._extract_app_name("launch Spotify") == "spotify"
        assert orchestrator._extract_app_name("install VS Code") == "vs code"

    def test_extract_contact_query(self, orchestrator):
        result = orchestrator._extract_contact_query("find contact Sarah Connor")
        assert "sarah connor" in result.lower()

    def test_extract_reply_body(self, orchestrator):
        result = orchestrator._extract_reply_body("reply with: sure, will do")
        assert "sure" in result.lower()

    def test_format_time_invalid(self, orchestrator):
        assert orchestrator._format_time("invalid") == "invalid"

    def test_format_datetime_invalid(self, orchestrator):
        assert orchestrator._format_datetime("") == "TBD"
        assert orchestrator._format_datetime("also invalid") == "also invalid"

    def test_today_format(self, orchestrator):
        result = orchestrator._today_str()
        from datetime import datetime
        assert result == datetime.now().strftime("%Y-%m-%d")

    def test_tomorrow_format(self, orchestrator):
        result = orchestrator._tomorrow_str()
        from datetime import datetime, timedelta
        assert result == (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
