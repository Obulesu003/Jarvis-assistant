"""
Console debug runner for MARK-XXXV LLM Orchestrator.
Run with: python debug_orchestrator.py
Exercises the full orchestrator chain with verbose debug output.
"""
# ruff: noqa: E402, I001
import logging
import sys
from pathlib import Path

# Enable verbose debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
# Suppress noisy third-party loggers
for noisy in ("PIL", "fontTools", "httpx", "httpcore", "anthropic", "google.auth"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

sys.path.insert(0, str(Path(__file__).parent))

from integrations.core.universal_orchestrator import UniversalOrchestrator
from integrations.core.llm_orchestrator import LLMOrchestrator


def create_orchestrator() -> LLMOrchestrator:
    """Wire up all adapters and return the LLM orchestrator."""
    orch = UniversalOrchestrator(ui=None)

    from integrations.outlook.outlook_adapter import OutlookAdapter
    from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
    from integrations.whatsapp.whatsapp_adapter import WhatsAppAdapter
    from integrations.contacts.contacts_adapter import ContactsAdapter
    from integrations.system.system_adapter import SystemAutomationAdapter
    from integrations.system.windows_app_adapter import WindowsAppAdapter
    from integrations.system.scheduler_adapter import SchedulerAdapter

    orch.register_adapter("outlook", OutlookAdapter())
    orch.register_adapter("outlook_native", OutlookNativeAdapter())
    orch.register_adapter("whatsapp", WhatsAppAdapter())
    orch.register_adapter("contacts", ContactsAdapter())
    orch.register_adapter("system", SystemAutomationAdapter())
    orch.register_adapter("windows_app", WindowsAppAdapter())
    orch.register_adapter("scheduler", SchedulerAdapter())

    return LLMOrchestrator(universal_orchestrator=orch, gemini_key=None)


TEST_QUERIES = [
    # Keyword-routed queries (work without Gemini)
    "how many unread emails do I have",
    "open notepad",
    "what time is it",
    # Multi-step patterns (chain results into next step)
    "search for emails from John and forward the first one to Jane",
    # Clipboard
    "copy my clipboard to a notepad file",
    # System
    "list my open windows",
    "get my system info",
]


def run_query(llm: LLMOrchestrator, query: str):
    print(f"\n{'='*70}")
    print(f"QUERY: {query}")
    print(f"{'='*70}")
    try:
        result = llm.execute(query, {})
        print(f"\nRESULT: {result}")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    print()


def main():
    print("MARK-XXXV LLM ORCHESTRATOR DEBUG RUNNER")
    print("=" * 70)
    print("NOTE: Gemini API unavailable = keyword fallback routing only.")
    print("      With a valid Gemini key, LLM-powered routing would activate.")
    print("=" * 70)

    llm = create_orchestrator()

    print(f"\nAdapters registered: {list(llm._orch._adapters.keys())}")
    print(f"Capabilities: {llm._build_capability_prompt().count(chr(10))} actions")

    for query in TEST_QUERIES:
        run_query(llm, query)


if __name__ == "__main__":
    main()
