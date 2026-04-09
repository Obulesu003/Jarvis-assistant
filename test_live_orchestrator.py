"""
Live test script for the LLM orchestrator.
Tests actual routing, multi-step chaining, clipboard, and auto-launch detection.

Key insight: adapter.execute_action() returns human-readable STRINGS,
not dicts. The _action_* methods return ActionResult (dicts), but
execute_action wraps them into strings. This means multi-step chaining
via ${steps[N].result.field} needs structured step results from the
_action_* methods, not execute_action output.
"""
import logging  # migrated from print()
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from integrations.core.llm_orchestrator import LLMOrchestrator
from integrations.core.universal_orchestrator import UniversalOrchestrator


def create_llm_orchestrator() -> LLMOrchestrator:
    """Create a fully wired LLM orchestrator for testing."""
    orch = UniversalOrchestrator(ui=None)

    from integrations.contacts.contacts_adapter import ContactsAdapter
    from integrations.outlook.outlook_adapter import OutlookAdapter
    from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
    from integrations.system.system_adapter import SystemAutomationAdapter
    from integrations.system.windows_app_adapter import WindowsAppAdapter
    from integrations.system.scheduler_adapter import SchedulerAdapter
    from integrations.whatsapp.whatsapp_adapter import WhatsAppAdapter

    orch.register_adapter("outlook", OutlookAdapter())
    orch.register_adapter("outlook_native", OutlookNativeAdapter())
    orch.register_adapter("whatsapp", WhatsAppAdapter())
    orch.register_adapter("contacts", ContactsAdapter())
    orch.register_adapter("system", SystemAutomationAdapter())
    orch.register_adapter("windows_app", WindowsAppAdapter())
    orch.register_adapter("scheduler", SchedulerAdapter())

    return LLMOrchestrator(universal_orchestrator=orch, gemini_key=None)


def test_capabilities():
    """Verify all adapters register their capabilities."""
    logging.getLogger(__name__).info('\\n=== Test: Capabilities ===')
    llm = create_llm_orchestrator()
    caps = llm._build_capability_prompt()
    logging.getLogger(__name__).info('Adapters: {list(llm._orch._adapters.keys())}')

    # Must have clipboard
    assert "windows_app.read_clipboard" in caps, "read_clipboard missing"
    assert "windows_app.write_clipboard" in caps, "write_clipboard missing"
    # Must have whatsapp
    assert "whatsapp.send_message" in caps, "whatsapp.send_message missing"
    # Must have outlook
    assert "outlook_native.get_unread_count" in caps, "outlook missing"
    logging.getLogger(__name__).info('PASS: {caps.count(chr(10))} capability lines registered')


def test_clipboard_write_and_read():
    """Test clipboard write then read back — full roundtrip."""
    logging.getLogger(__name__).info('\\n=== Test: Clipboard Roundtrip ===')
    llm = create_llm_orchestrator()

    test_text = "MARK-XXXV TEST"

    # Write
    write_result = llm._orch._execute_step({
        "adapter": "windows_app",
        "action": "write_clipboard",
        "params": {"text": test_text},
    })
    write_str = write_result  # execute_action returns string
    logging.getLogger(__name__).info('Write: {write_str}')
    assert "Failed" not in write_str, f"Write failed: {write_str}"

    # Read back
    read_result = llm._orch._execute_step({
        "adapter": "windows_app",
        "action": "read_clipboard",
        "params": {"max_length": 5000},
    })
    read_str = read_result
    logging.getLogger(__name__).info('Read:  {read_str}')
    assert test_text in read_str, f"Expected '{test_text}' in '{read_str}'"
    logging.getLogger(__name__).info('PASS: Clipboard roundtrip works')


def test_resolve_params_basic():
    """Test that _resolve_params works on plain params."""
    logging.getLogger(__name__).info('\\n=== Test: Resolve Params (no substitution) ===')
    llm = create_llm_orchestrator()
    params = {"email_id": "123", "body": "Hello world"}
    resolved = llm._resolve_params(params, [])
    assert resolved["email_id"] == "123"
    assert resolved["body"] == "Hello world"
    logging.getLogger(__name__).info('PASS: Plain params pass through')


def test_resolve_params_with_dict_results():
    """Test that _resolve_params substitutes from dict results."""
    logging.getLogger(__name__).info('\\n=== Test: Resolve Params (dict results) ===')
    llm = create_llm_orchestrator()

    # Results from _action_* methods are dicts
    results = [{"success": True, "email_id": "abc-123", "sender": "John"}]
    params = {"id": "${steps[0].result.email_id}"}
    resolved = llm._resolve_params(params, results)
    logging.getLogger(__name__).info('Input: {params}')
    logging.getLogger(__name__).info('Resolved: {resolved}')
    assert resolved["id"] == "abc-123", f"Got {resolved['id']}"
    logging.getLogger(__name__).info('PASS: Dict substitution works')


def test_resolve_value_preserves_surrounding_text():
    """Test that _resolve_value replaces only the substitution, not whole string."""
    logging.getLogger(__name__).info('\\n=== Test: Resolve Value (surrounding text) ===')
    llm = create_llm_orchestrator()

    results = [{"name": "Alice"}]
    value = "Hello ${steps[0].result.name}, how are you?"
    resolved = llm._resolve_value(value, results)
    logging.getLogger(__name__).info('Input:  {value}')
    logging.getLogger(__name__).info('Output: {resolved}')
    assert resolved == "Hello Alice, how are you?", f"Got: {resolved}"
    logging.getLogger(__name__).info('PASS: Surrounding text preserved')


def test_resolve_value_partial_replacement():
    """Test partial replacement in multi-substitution."""
    logging.getLogger(__name__).info('\\n=== Test: Resolve Value (multiple subs) ===')
    llm = create_llm_orchestrator()

    results = [{"id": "xyz"}, {"extra": "data"}]
    params = {"to": "${steps[0].result.id}", "subject": "Re: ${steps[1].result.extra}"}
    resolved = llm._resolve_params(params, results)
    logging.getLogger(__name__).info('Resolved: {resolved}')
    assert resolved["to"] == "xyz"
    assert resolved["subject"] == "Re: data"
    logging.getLogger(__name__).info('PASS: Multiple substitutions work')


def test_auto_launch_whatsapp_map():
    """Test that WhatsApp is in the auto-launch map."""
    logging.getLogger(__name__).info('\\n=== Test: Auto-Launch Map ===')
    llm = create_llm_orchestrator()
    assert "whatsapp" in llm.AUTO_LAUNCH_MAP
    assert llm.AUTO_LAUNCH_MAP["whatsapp"] == "https://web.whatsapp.com"
    logging.getLogger(__name__).info('Auto-launch map: {llm.AUTO_LAUNCH_MAP}')
    logging.getLogger(__name__).info('PASS: Auto-launch map configured')


def test_is_not_connected_detection():
    """Test that not-connected errors are correctly detected."""
    logging.getLogger(__name__).info('\\n=== Test: Not-Connected Detection ===')
    llm = create_llm_orchestrator()

    triggers = [
        "QR code visible — scan it in the browser window",
        "Session expired. Please scan again.",
        "Please scan the QR code to connect",
        "WhatsApp not connected. Please scan QR code.",
        "Could not find contact: John",  # Should NOT trigger (not a session issue)
        "Invalid recipient name",  # Should NOT trigger
    ]
    expected = [True, True, True, True, False, False]

    all_pass = True
    for error, exp in zip(triggers, expected):
        result = {"success": False, "error": error}
        detected = llm._is_not_connected_error(result)
        status = "PASS" if detected == exp else "FAIL"
        logging.getLogger(__name__).info("{status}: '{error[:50]}' -> {detected} (expected {exp})")
        if detected != exp:
            all_pass = False

    assert all_pass
    logging.getLogger(__name__).info('PASS: Not-connected detection correct')


def test_results_summary_formats():
    """Test that results summary formats various result types."""
    logging.getLogger(__name__).info('\\n=== Test: Results Summary ===')
    llm = create_llm_orchestrator()

    results = [
        {"success": True, "data": {"unread": 5}},
        {"success": True, "data": {"emails": [{"sender": "John"}, {"sender": "Jane"}]}},
        {"success": True, "data": {"events": [1, 2, 3]}},
        {"success": False, "error": "Connection refused"},
    ]
    summary = llm._build_results_summary(results)
    logging.getLogger(__name__).info('Summary:\\n{summary}')
    assert "Step 1:" in summary
    assert "Step 4:" in summary
    logging.getLogger(__name__).info('PASS: Results summary formats correctly')


def test_execute_steps_handles_string_results():
    """Test that _execute_steps handles string results from execute_action."""
    logging.getLogger(__name__).info('\\n=== Test: Execute Steps (string results) ===')
    llm = create_llm_orchestrator()

    # First write something known
    llm._orch._execute_step({
        "adapter": "windows_app",
        "action": "write_clipboard",
        "params": {"text": "hello from step chain"},
    })

    # Two-step: read then append
    steps = [
        {"adapter": "windows_app", "action": "read_clipboard", "params": {"max_length": 100}},
        {"adapter": "windows_app", "action": "write_clipboard", "params": {"text": " CHAINED", "append": False}},
    ]
    results = llm._execute_steps(steps)
    logging.getLogger(__name__).info('Step 0 result: {results[0]}')
    logging.getLogger(__name__).info('Step 1 result: {results[1]}')
    assert len(results) == 2
    # Results are strings from execute_action
    assert "Failed" not in results[1], f"Step 1 should succeed: {results[1]}"
    logging.getLogger(__name__).info('PASS: Multi-step execution works')


def test_unknown_action_returns_error_string():
    """Test that unknown actions return an error string."""
    logging.getLogger(__name__).info('\\n=== Test: Unknown Action Error ===')
    llm = create_llm_orchestrator()

    result = llm._execute_steps([{
        "adapter": "windows_app",
        "action": "nonexistent_action",
        "params": {},
    }])
    logging.getLogger(__name__).info('Result: {result[0]}')
    assert "Unknown" in result[0] or "Failed" in result[0]
    logging.getLogger(__name__).info('PASS: Unknown action handled')


def test_keyword_fallback_no_crash():
    """Test that keyword fallback doesn't crash (Gemini unavailable)."""
    logging.getLogger(__name__).info('\\n=== Test: Keyword Fallback ===')
    llm = create_llm_orchestrator()

    # Gemini unavailable → falls back to keyword matching
    result = llm.execute("how many unread emails do I have", {})
    logging.getLogger(__name__).info('Result: {result[:150]}')
    assert isinstance(result, str)
    assert len(result) > 0
    logging.getLogger(__name__).info('PASS: Keyword fallback works (Gemini unavailable -> keyword fallback)')


def run_all_tests():
    logging.getLogger(__name__).info('=')
    logging.getLogger(__name__).info('MARK-XXXV LLM ORCHESTRATOR LIVE TESTS')
    logging.getLogger(__name__).info('=')

    tests = [
        test_capabilities,
        test_clipboard_write_and_read,
        test_resolve_params_basic,
        test_resolve_params_with_dict_results,
        test_resolve_value_preserves_surrounding_text,
        test_resolve_value_partial_replacement,
        test_auto_launch_whatsapp_map,
        test_is_not_connected_detection,
        test_results_summary_formats,
        test_execute_steps_handles_string_results,
        test_unknown_action_returns_error_string,
        test_keyword_fallback_no_crash,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            logging.getLogger(__name__).info('FAIL: {test.__name__}: {e}')
            import traceback
            traceback.print_exc()
            failed += 1

    logging.getLogger(__name__).info('\\n')
    logging.getLogger(__name__).info('RESULTS: {passed} passed, {failed} failed')
    if failed == 0:
        logging.getLogger(__name__).info('ALL TESTS PASSED!')
    logging.getLogger(__name__).info('=')
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
