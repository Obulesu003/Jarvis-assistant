"""Tests for integrations.core.llm_orchestrator."""
import pytest


class TestLLMOrchestrator:
    """Test cases for LLMOrchestrator."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock universal orchestrator for testing."""
        from unittest.mock import MagicMock

        from integrations.core.llm_orchestrator import LLMOrchestrator
        from integrations.core.universal_orchestrator import UniversalOrchestrator

        mock_base = MagicMock(spec=UniversalOrchestrator)
        mock_base._adapters = {}
        mock_base._plan_steps = MagicMock(return_value=[])
        mock_base._execute_step = MagicMock(return_value={"success": True})
        mock_base._format_response = MagicMock(return_value="Done.")
        mock_base._fallback_response = MagicMock(return_value="I couldn't figure that out.")
        mock_base._build_capability_prompt = MagicMock(
            return_value="Available actions:\n  outlook_native.get_unread_count"
        )

        return LLMOrchestrator(
            universal_orchestrator=mock_base,
            gemini_key="fake-key",
        )

    # ------------------------------------------------------------------ #
    # JSON Parsing                                                       #
    # ------------------------------------------------------------------ #

    def test_parse_steps_from_json_with_markdown(self, mock_orchestrator):
        text = '```json\n{"adapter": "outlook_native", "action": "get_unread_count", "params": {}}\n```'
        steps = mock_orchestrator._parse_steps_from_response(text)
        assert len(steps) == 1
        assert steps[0]["adapter"] == "outlook_native"
        assert steps[0]["action"] == "get_unread_count"

    def test_parse_steps_from_json_without_markdown(self, mock_orchestrator):
        text = '{"adapter": "system", "action": "open_application", "params": {"name": "notepad"}}'
        steps = mock_orchestrator._parse_steps_from_response(text)
        assert len(steps) == 1
        assert steps[0]["adapter"] == "system"
        assert steps[0]["action"] == "open_application"
        assert steps[0]["params"]["name"] == "notepad"

    def test_parse_steps_multiple_steps(self, mock_orchestrator):
        text = '''```json
{
  "steps": [
    {"adapter": "outlook_native", "action": "search_emails", "params": {"query": "John"}},
    {"adapter": "outlook_native", "action": "send_email", "params": {"to": "John"}}
  ]
}
```'''
        steps = mock_orchestrator._parse_steps_from_response(text)
        assert len(steps) == 2
        assert steps[0]["action"] == "search_emails"
        assert steps[1]["action"] == "send_email"

    def test_parse_steps_invalid_json_returns_empty(self, mock_orchestrator):
        text = "This is not JSON at all!"
        steps = mock_orchestrator._parse_steps_from_response(text)
        assert steps == []

    def test_parse_steps_missing_adapter(self, mock_orchestrator):
        text = '{"action": "get_unread_count"}'
        steps = mock_orchestrator._parse_steps_from_response(text)
        assert steps == []

    def test_parse_steps_missing_action(self, mock_orchestrator):
        text = '{"adapter": "outlook_native"}'
        steps = mock_orchestrator._parse_steps_from_response(text)
        assert steps == []

    # ------------------------------------------------------------------ #
    # Context Building                                                   #
    # ------------------------------------------------------------------ #

    def test_build_context_string_empty(self, mock_orchestrator):
        result = mock_orchestrator._build_context_string({})
        assert "No additional context" in result

    def test_build_context_string_with_data(self, mock_orchestrator):
        context = {"last_email_id": "123", "last_sender": "John"}
        result = mock_orchestrator._build_context_string(context)
        assert "last_sender" in result
        assert "John" in result

    def test_build_history_string_empty(self, mock_orchestrator):
        result = mock_orchestrator._build_history_string([])
        assert "No recent steps" in result

    def test_build_history_string_with_steps(self, mock_orchestrator):
        steps = [
            {"adapter": "outlook", "action": "list_emails", "description": "List emails"},
            {"adapter": "system", "action": "open_app", "description": "Open Notepad"},
        ]
        result = mock_orchestrator._build_history_string(steps)
        assert "List emails" in result
        assert "Open Notepad" in result

    # ------------------------------------------------------------------ #
    # Results Summary                                                    #
    # ------------------------------------------------------------------ #

    def test_build_results_summary_empty(self, mock_orchestrator):
        result = mock_orchestrator._build_results_summary([])
        assert result == ""  # Empty list produces empty string

    def test_build_results_summary_email_count(self, mock_orchestrator):
        results = [{"unread": 5}]
        result = mock_orchestrator._build_results_summary(results)
        assert "5 unread emails" in result

    def test_build_results_summary_emails_list(self, mock_orchestrator):
        results = [{"emails": [{"sender": "John"}, {"sender": "Jane"}]}]
        result = mock_orchestrator._build_results_summary(results)
        assert "Found 2 emails" in result

    def test_build_results_summary_events(self, mock_orchestrator):
        results = [{"events": [{}, {}, {}]}]
        result = mock_orchestrator._build_results_summary(results)
        assert "3 calendar events" in result

    def test_build_results_summary_error(self, mock_orchestrator):
        # When success is False, it shows "failed" instead of the error message
        # because success check comes before error check in the formatter
        results = [{"error": "Connection failed", "success": False}]
        result = mock_orchestrator._build_results_summary(results)
        assert "failed" in result

    def test_build_results_summary_error_only(self, mock_orchestrator):
        # Error dict without success key shows the error message
        results = [{"error": "Connection failed"}]
        result = mock_orchestrator._build_results_summary(results)
        assert "Connection failed" in result

    def test_build_results_summary_string(self, mock_orchestrator):
        results = ["Email sent successfully"]
        result = mock_orchestrator._build_results_summary(results)
        assert "Email sent successfully" in result

    # ------------------------------------------------------------------ #
    # Keyword Fallback                                                   #
    # ------------------------------------------------------------------ #

    def test_keyword_fallback_delegates(self, mock_orchestrator):
        """Keyword fallback should call the base orchestrator's _plan_steps."""
        mock_orchestrator._plan_steps_keyword(
            "how many unread emails",
            "how many unread emails",
            {}
        )
        mock_orchestrator._orch._plan_steps.assert_called_once()

    # ------------------------------------------------------------------ #
    # Step Execution                                                      #
    # ------------------------------------------------------------------ #

    def test_execute_steps_success(self, mock_orchestrator):
        steps = [
            {"adapter": "outlook", "action": "get_unread_count", "params": {}},
        ]
        mock_orchestrator._orch._execute_step.return_value = {"unread": 3}
        results = mock_orchestrator._execute_steps(steps)
        assert len(results) == 1
        assert results[0]["unread"] == 3

    def test_execute_steps_failure(self, mock_orchestrator):
        mock_orchestrator._orch._execute_step.side_effect = Exception("Network error")
        steps = [
            {"adapter": "outlook", "action": "get_unread_count", "params": {}},
        ]
        results = mock_orchestrator._execute_steps(steps)
        assert len(results) == 1
        assert results[0]["error"] == "Network error"
        assert not results[0]["success"]

    # ------------------------------------------------------------------ #
    # Parameter Substitution                                               #
    # ------------------------------------------------------------------ //

    def test_resolve_params_simple(self, mock_orchestrator):
        results = [{"id": "123", "name": "John"}]
        params = {"email_id": "456"}
        resolved = mock_orchestrator._resolve_params(params, results)
        assert resolved["email_id"] == "456"

    def test_resolve_params_with_substitution(self, mock_orchestrator):
        results = [{"email_id": "abc123", "sender": "John"}]
        email_raw = "${steps[0].result.email_id}"
        params = {"email_id": email_raw}
        resolved = mock_orchestrator._resolve_params(params, results)
        assert resolved["email_id"] == "abc123"

    def test_resolve_params_nested_substitution(self, mock_orchestrator):
        results = [{"id": "xyz"}, {"extra": "data"}]
        # Use double braces to escape the f-string since {steps[1]} would be evaluated
        subject_raw = "Re: ${steps[1].result.extra}"
        params = {"to": "${steps[0].result.id}", "subject": subject_raw}
        resolved = mock_orchestrator._resolve_params(params, results)
        assert resolved["to"] == "xyz"
        assert resolved["subject"] == "Re: data"

    def test_resolve_params_invalid_index(self, mock_orchestrator):
        results = [{"id": "123"}]
        raw = "${steps[5].result.id}"
        params = {"email_id": raw}
        resolved = mock_orchestrator._resolve_params(params, results)
        # Falls back to original since step index 5 doesn't exist
        assert resolved["email_id"] == raw

    def test_resolve_params_no_pattern(self, mock_orchestrator):
        results = []
        params = {"message": "Hello world"}
        resolved = mock_orchestrator._resolve_params(params, results)
        assert resolved["message"] == "Hello world"

    # ------------------------------------------------------------------ #
    # Auto-Launch & Not-Connected Detection                               #
    # ------------------------------------------------------------------ #

    def test_is_not_connected_qr_code(self, mock_orchestrator):
        result = {"success": False, "error": "QR code visible — scan it in the browser window"}
        assert mock_orchestrator._is_not_connected_error(result) is True

    def test_is_not_connected_scan(self, mock_orchestrator):
        result = {"success": False, "error": "Please scan the QR code to connect"}
        assert mock_orchestrator._is_not_connected_error(result) is True

    def test_is_not_connected_session_expired(self, mock_orchestrator):
        result = {"success": False, "error": "Session expired. Please scan again."}
        assert mock_orchestrator._is_not_connected_error(result) is True

    def test_is_not_connected_not_triggered(self, mock_orchestrator):
        result = {"success": False, "error": "Invalid recipient name"}
        assert mock_orchestrator._is_not_connected_error(result) is False

    def test_is_not_connected_contact_not_triggered(self, mock_orchestrator):
        result = {"success": False, "error": "Could not find contact: John"}
        assert mock_orchestrator._is_not_connected_error(result) is False

    def test_is_not_connected_success(self, mock_orchestrator):
        result = {"success": True, "sent": True}
        assert mock_orchestrator._is_not_connected_error(result) is False

    def test_auto_launch_map(self, mock_orchestrator):
        assert "whatsapp" in mock_orchestrator.AUTO_LAUNCH_MAP
        assert mock_orchestrator.AUTO_LAUNCH_MAP["whatsapp"] == "https://web.whatsapp.com"

    # ------------------------------------------------------------------ #
    # Rate Limit Retry                                                    #
    # ------------------------------------------------------------------ //

    def test_plan_steps_retries_on_429(self, mock_orchestrator):
        """Should retry with backoff when Gemini returns 429 rate limit."""
        import unittest.mock

        call_count = 0

        def fake_generate(content):
            nonlocal call_count
            call_count += 1
            # Fail first MAX_RETRIES-1 attempts, succeed on last
            if call_count <= 2:
                err_msg = "429 Too Many Requests"
                raise Exception(err_msg)
            # Succeed on last attempt
            class R:
                text = '{"adapter": "outlook", "action": "get_unread_count", "params": {}}'
            return R()

        mock_model = unittest.mock.MagicMock()
        mock_model.generate_content = fake_generate
        mock_orchestrator._model = mock_model

        with unittest.mock.patch(
            "integrations.core.llm_orchestrator.time.sleep"
        ) as mock_sleep:
            steps = mock_orchestrator._plan_steps_llm("how many unread emails", {})
            assert call_count == 3
            assert mock_sleep.call_count == 2
            assert len(steps) == 1
            assert steps[0]["action"] == "get_unread_count"

    def test_plan_steps_falls_back_on_permanent_error(self, mock_orchestrator):
        """Should fall back to keyword matching after max retries on permanent error."""
        import unittest.mock

        mock_model = unittest.mock.MagicMock()
        mock_model.generate_content.side_effect = Exception("429 Too Many Requests")
        mock_orchestrator._model = mock_model

        with unittest.mock.patch(
            "integrations.core.llm_orchestrator.time.sleep"
        ) as mock_sleep:
            # Directly test _plan_steps_llm returns [] after exhausting retries
            steps = mock_orchestrator._plan_steps_llm("how many unread emails", {})
            assert steps == []
            # All retry sleeps were called
            assert mock_sleep.call_count == 2  # MAX_RETRIES-1 = 2
