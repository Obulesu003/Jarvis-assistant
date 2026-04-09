import logging  # migrated from print()
import json
import re
import sys
import threading
import time
from pathlib import Path

try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# ── Plan Cache ────────────────────────────────────────────────────────────────

_PLAN_CACHE_TTL  = 600   # 10 minutes
_PLAN_CACHE_LOCK = threading.Lock()
_PLAN_CACHE: dict[str, tuple[dict, float]] = {}
_PLAN_CACHE_PATH = get_base_dir() / "memory" / "plans_cache.json"


def _load_plan_cache() -> None:
    """Load plan cache from disk on startup."""
    if not _PLAN_CACHE_PATH.exists():
        return
    try:
        data = json.loads(_PLAN_CACHE_PATH.read_text(encoding="utf-8"))
        now  = time.time()
        for key, entry in data.items():
            # Only load entries that haven't expired
            if now - entry.get("_ts", 0) < _PLAN_CACHE_TTL:
                plan = entry.get("plan")
                if plan:
                    _PLAN_CACHE[key] = (plan, entry.get("_ts", 0))
        logging.getLogger("Planner").info(f"Loaded {len(_PLAN_CACHE)} cached plans")
    except Exception as e:
        logging.getLogger("Planner").info(f'Load failed: {e}')


def _save_plan_cache() -> None:
    """Persist plan cache to disk."""
    try:
        _PLAN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {k: {"plan": v[0], "_ts": v[1]} for k, v in _PLAN_CACHE.items()}
        _PLAN_CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logging.getLogger("Planner").info(f'Save failed: {e}')


def _make_cache_key(goal: str) -> str:
    """Normalize goal for cache lookup."""
    normalized = goal.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)  # collapse whitespace
    return normalized


def _get_cached_plan(goal: str) -> dict | None:
    """Return cached plan if fresh, else None."""
    key = _make_cache_key(goal)
    with _PLAN_CACHE_LOCK:
        entry = _PLAN_CACHE.get(key)
        if not entry:
            return None
        plan, cached_at = entry
        if time.time() - cached_at > _PLAN_CACHE_TTL:
            del _PLAN_CACHE[key]
            return None
        logging.getLogger("Planner").info(f'HIT  key={goal[:60]}')
        return plan


def _set_cached_plan(goal: str, plan: dict) -> None:
    """Store plan in cache and persist."""
    key = _make_cache_key(goal)
    now = time.time()
    with _PLAN_CACHE_LOCK:
        _PLAN_CACHE[key] = (plan, now)
    # Async persist (don't block)
    threading.Thread(target=_save_plan_cache, daemon=True).start()


# Load cache on module import
_load_plan_cache()


PLANNER_PROMPT = """You are the planning module of MARK XXV, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- NEVER reference previous step results in parameters. Every step is independent.
- Use web_search for ANY information retrieval, research, or current data.
- Use file_controller to save content to disk.
- Use cmd_control to open files or run system commands.
- Maximum 12 steps. Use the minimum steps needed. Break complex goals into sequential sub-plans if needed.
- For parallel independent tasks (e.g. "search X and Y simultaneously"), mark with "parallel": true in the step. For dependent steps, use "depends_on": [step_number].

AVAILABLE TOOLS AND THEIR PARAMETERS:

open_app
  app_name: string (required)

web_search
  query: string (required) -- write a clear, focused search query
  mode: "search" or "compare" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)

game_updater
  action: "update" | "install" | "list" | "download_status" | "schedule" (required)
  platform: "steam" | "epic" | "both" (optional, default: both)
  game_name: string (optional)
  app_id: string (optional)
  shutdown_when_done: boolean (optional)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "get_text" | "press" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  text: string (for click/type)
  direction: "up" | "down" (for scroll)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (required)
  path: string -- use "desktop" for Desktop folder
  name: string -- filename
  content: string -- file content (for write/create_file)

cmd_control
  task: string (required) -- natural language description of what to do
  visible: boolean (optional)
  action: string (optional) -- "run" (default), "session_start", "session_run", "session_status", "session_end"
  session_id: string (optional) -- for persistent sessions
  speak_output: boolean (optional) -- format output for TTS

claude_tool
  task: string (required) -- what to ask Claude Code to do
  mode: string (optional) -- "ask" (default), "write", "review", "run"
  project: string (optional) -- project directory
  session_id: string (optional) -- session identifier
  timeout: int (optional, default 60)

claude_session
  action: string (required) -- "start" | "continue" | "status" | "end"
  session_id: string (optional, default "default")
  project: string (optional) -- project directory
  task: string (optional) -- prompt for start/continue
  timeout: int (optional, default 90)

shell_start
  session_id: string (optional, default "default") -- shell identifier
  cwd: string (optional) -- working directory for Claude

shell_send
  prompt: string (required) -- what to ask Claude Code
  timeout: int (optional, default 120) -- seconds to wait
  auto_approve: boolean (optional, default false) -- auto-confirm y/n prompts
  session_id: string (optional)

shell_status
  session_id: string (optional)

shell_interrupt
  session_id: string (optional)

shell_end
  session_id: string (optional)

computer_settings
  action: string (required)
  description: string -- natural language description
  value: string (optional)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (required)
  text: string (for type)
  x, y: int (for click)
  keys: string (for hotkey, e.g. "ctrl+c")
  key: string (for press)
  direction: "up" | "down" (for scroll)
  description: string (for screen_find/screen_click)

screen_process
  text: string (required) -- what to analyze or ask about the screen
  angle: "screen" | "camera" (optional)

send_message
  receiver: string (required)
  message_text: string (required)
  platform: string (required)

reminder
  date: string YYYY-MM-DD (required)
  time: string HH:MM (required)
  message: string (required)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "trending" (required)
  query: string (for play)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

dev_agent
  description: string (required)
  language: string (optional)

agent_task
  goal: string (required) -- the task to execute as a subtask
  priority: string (optional) -- low, normal, or high (default: normal)

EXAMPLES:

Goal: "research mechanical engineering and save it to a notepad file"
Steps:

web_search | query: "mechanical engineering overview definition history"
web_search | query: "mechanical engineering applications and future trends"
file_controller | action: write, path: desktop, name: mechanical_engineering.txt, content: "MECHANICAL ENGINEERING RESEARCH\n\nThis file will be filled with web research results."
cmd_control | task: "open mechanical_engineering.txt on desktop with notepad"

Goal: "What is the price of Bitcoin"
Steps:

web_search | query: "Bitcoin price today USD"

Goal: "List the files on the desktop and find the largest 5 files"
Steps:

file_controller | action: list, path: desktop
file_controller | action: largest, path: desktop, count: 5

Goal: "Install PUBG from Steam"
Steps:

game_updater | action: install, platform: steam, game_name: "PUBG"

Goal: "Update all my Steam games"
Steps:

game_updater | action: update, platform: steam

Goal: "Send John a message on WhatsApp saying there is a meeting tomorrow"
Steps:

send_message | receiver: John, message_text: "There is a meeting tomorrow", platform: WhatsApp

Goal: "ask Claude Code to explain the code in main.py"
Steps:

claude_tool | task: "explain the code in main.py", mode: "ask"

Goal: "let Claude review the browser control code"
Steps:

claude_tool | task: "review actions/browser_control.py for quality and bugs", mode: "review"

Goal: "start Claude Code shell and ask it to refactor the executor"
Steps:

shell_start
shell_send | prompt: "refactor agent/executor.py to improve error handling", timeout: 120
shell_status

Goal: "ask Claude to build a new feature, interrupt if it gets stuck"
Steps:

shell_start | session_id: "feature-build"
shell_send | prompt: "implement a logging system for all agent actions", timeout: 120
shell_status
shell_interrupt | session_id: "feature-build"
shell_end | session_id: "feature-build"

Goal: "run a CMD command to check disk space"
Steps:

cmd_control | task: "check disk space", visible: false

Goal: "Open the clock and set a reminder for 30 minutes later"
Steps:

reminder | date: [today], time: [now+30min], message: "Reminder"

OUTPUT -- return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def _get_api_key() -> str:
    if _get_gemini_key is not None:
        return _get_gemini_key()
    # Fallback
    import json
    from pathlib import Path
    cfg = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
    with open(cfg, encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def create_plan(goal: str, context: str = "") -> dict:
    from google.genai import Client
    from google.genai.types import GenerateContentConfig

    # ── Check cache first ───────────────────────────────────────────────────
    cached = _get_cached_plan(goal)
    if cached:
        return cached

    client = Client(api_key=_get_api_key())

    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        # Use gemini-2.0-flash-exp for faster planning (tool routing doesn't need 2.5)
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=user_input,
            config=GenerateContentConfig(system_instruction=PLANNER_PROMPT)
        )
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = json.loads(text)

        if "steps" not in plan or not isinstance(plan["steps"], list):
            msg = "Invalid plan structure"
            raise ValueError(msg)

        for step in plan["steps"]:
            if step.get("tool") in ("generated_code",):
                logging.getLogger("Planner").info("WARN generated_code detected in step {step.get('step')} -- replacing with web_search")
                desc = step.get("description", goal)
                step["tool"] = "web_search"
                step["parameters"] = {"query": desc[:200]}

        logging.getLogger("Planner").info("OK Plan: {len(plan['steps'])} steps")
        for s in plan["steps"]:
            logging.getLogger(__name__).info("Step {s['step']}: [{s['tool']}] {s['description']}")

        # Cache the successful plan
        _set_cached_plan(goal, plan)
        return plan

    except json.JSONDecodeError as e:
        logging.getLogger("Planner").info(f'WARN JSON parse failed: {e}')
        return _fallback_plan(goal)
    except Exception as e:
        logging.getLogger("Planner").info(f'WARN Planning failed: {e}')
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    logging.getLogger("Planner").info('RETRY Fallback plan')
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True
            }
        ]
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    from google.genai import Client
    from google.genai.types import GenerateContentConfig

    client = Client(api_key=_get_api_key())

    completed_summary = "\n".join(
        f"  - Step {s['step']} ({s['tool']}): DONE" for s in completed_steps
    )

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=GenerateContentConfig(system_instruction=PLANNER_PROMPT)
        )
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan     = json.loads(text)

        for step in plan.get("steps", []):
            if step.get("tool") == "generated_code":
                step["tool"] = "web_search"
                step["parameters"] = {"query": step.get("description", goal)[:200]}

        logging.getLogger("Planner").info(f"RETRY Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as e:
        logging.getLogger("Planner").info(f'WARN Replan failed: {e}')
        return _fallback_plan(goal)
