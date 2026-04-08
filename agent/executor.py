import json
import re
import sys
import threading
import subprocess
import tempfile
import os
import contextlib
import time as _time_module
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


# ── Extraction helpers ─────────────────────────────────────────────────────────

def _extract_city(goal: str) -> str:
    """Extract city name from a weather query."""
    cleaned = re.sub(
        r"(weather|temperature|forecast|in|for|of|at)\s+", " ", goal, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"(what'?s?\s+the\s+)?(weather|temperature|forecast)\s*", "", cleaned, flags=re.IGNORECASE
    )
    return cleaned.strip() or "current location"


def _extract_app_name(goal: str) -> str:
    """Extract app name from 'open/launch/run' phrases."""
    patterns = [
        r"open\s+(?:the\s+)?(.+?)(?:\s+and|\s+then|\s+in|\s+on|$)",
        r"launch\s+(?:the\s+)?(.+?)(?:\s+and|\s+then|\s+in|\s+on|$)",
        r"run\s+(?:the\s+)?(.+?)(?:\s+and|\s+then|\s+in|\s+on|$)",
        r"start\s+(?:the\s+)?(.+?)(?:\s+and|\s+then|\s+in|\s+on|$)",
    ]
    for pat in patterns:
        m = re.search(pat, goal, re.IGNORECASE)
        if m:
            app = m.group(1).strip()
            app = re.sub(r"\s+(app|application|program|software)\s*", "", app, flags=re.IGNORECASE)
            if app:
                return app.title()
    return goal.strip()[:50]


def _extract_reminder(goal: str) -> dict:
    """Extract reminder details from natural language."""
    from datetime import datetime, timedelta
    now = datetime.now()
    m = re.search(r"in\s+(\d+)\s+(minute|minutes|min|mins|hour|hours|h)\b", goal, re.IGNORECASE)
    if m:
        val  = int(m.group(1))
        unit = m.group(2).lower()
        dt   = now + timedelta(hours=val) if unit.startswith("h") else now + timedelta(minutes=val)
        note = re.sub(r"remind me\s*", "", goal, flags=re.IGNORECASE).strip()
        note = re.sub(
            rf"in\s+\d+\s+({'|'.join(['minute','minutes','min','mins','hour','hours','h'])})\s*",
            "", note, flags=re.IGNORECASE
        ).strip()
        return {"date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M"),
                "message": note or "Reminder"}
    return {}


def _extract_message(goal: str, platform: str = "WhatsApp") -> dict:
    """Extract message recipient and text."""
    m = re.search(
        r"to\s+(\w+)\s+(?:on\s+)?(?:WhatsApp|Telegram)?\s*(?:saying|say|that|message|text)\s*[:\-]?\s*(.+)",
        goal, re.IGNORECASE
    )
    if m:
        return {"receiver": m.group(1), "message_text": m.group(2).strip(), "platform": platform}
    return {}


def _extract_browser_url(goal: str) -> dict:
    """Extract URL from browser navigation phrases."""
    m = re.search(r"(?:go to|navigate to|open website|open)\s+(\S+)", goal, re.IGNORECASE)
    if m:
        url = m.group(1)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return {"action": "go_to", "url": url}
    return {"action": "search", "query": goal}


def _extract_wallpaper_url(goal: str) -> str:
    """Extract URL from wallpaper phrase."""
    m = re.search(r"(?:set|change)\s+wallpaper\s+(?:to\s+)?(.+)", goal, re.IGNORECASE)
    if m:
        url = m.group(1).strip().rstrip(".,!?")
        if url.startswith(("http://", "https://")):
            return url
    return ""


def _extract_screen_question(goal: str) -> str:
    """Extract the question from screen analysis phrases."""
    cleaned = re.sub(
        r"(?:what do you see|what's on my screen|analyze my screen|"
        r"look at my screen|describe my screen)\s*",
        "", goal, flags=re.IGNORECASE
    ).strip()
    return cleaned or goal


def _extract_github_repo(goal: str) -> str:
    """Extract GitHub repo from phrases."""
    m = re.search(r"github[:/\s]+([\w\-]+/[\w\-]+)", goal, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(
        r"repo(?:sitory)?\s+(?:stats?\s+(?:for|of)?\s*)?([\w\-]+/[\w\-]+)",
        goal, re.IGNORECASE
    )
    if m:
        return m.group(1)
    return ""


# ── Tool router ────────────────────────────────────────────────────────────────

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:
    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."

    if tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."

    if tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak) or "Done."

    if tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Done."

    if tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."

    if tool == "cmd_control":
        from actions.cmd_control import cmd_control
        return cmd_control(parameters=parameters, player=None) or "Done."

    if tool == "claude_tool":
        from actions.claude_tool import claude_tool
        return claude_tool(parameters=parameters, player=None) or "Done."

    if tool == "claude_session":
        from actions.claude_tool import claude_session
        return claude_session(parameters=parameters, player=None) or "Done."

    if tool == "shell_start":
        from actions.claude_shell import shell_start
        return shell_start(parameters=parameters, player=None) or "Done."

    if tool == "shell_send":
        from actions.claude_shell import shell_send
        return shell_send(parameters=parameters, player=None) or "Done."

    if tool == "shell_status":
        from actions.claude_shell import shell_status
        return shell_status(parameters=parameters, player=None) or "Done."

    if tool == "shell_interrupt":
        from actions.claude_shell import shell_interrupt
        return shell_interrupt(parameters=parameters, player=None) or "Done."

    if tool == "shell_end":
        from actions.claude_shell import shell_end
        return shell_end(parameters=parameters, player=None) or "Done."

    if tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."

    if tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."

    if tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Screen captured and analyzed."

    if tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."

    if tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."

    if tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."

    if tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."

    if tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."

    if tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."

    if tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."

    if tool == "generated_code":
        description = parameters.get("description", "")
        if not description:
            raise ValueError("generated_code requires a 'description' parameter.")
        return _run_generated_code(description, speak=speak)

    if tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."

    print(f"[Executor] Unknown tool '{tool}' -- falling back to generated_code")
    return _run_generated_code(f"Accomplish this task: {parameters}", speak=speak)


# ── Code generation sandbox ────────────────────────────────────────────────────

_DANGEROUS_BUILTINS = frozenset([
    "__import__", "eval", "exec", "compile", "open", "input",
    "breakpoint", "reload", "__builtins__",
])
_SAFE_BUILTINS = {k: v for k, v in __builtins__.items()
                  if k not in _DANGEROUS_BUILTINS}

_RESTRICTED_MODULES = frozenset([
    "os.system", "os.popen", "os.spawn", "os.execl", "os.execv",
    "subprocess.Popen", "shutil.rmtree", "shutil.move",
    "http.server", "socketserver", "ftplib", "telnetlib",
    "cryptography", "hashlib", "ssl", "ctypes",
    "pdb", "sys.settrace",
])

_LOG_DIR = get_base_dir() / "memory" / "execution_logs"


def _log_execution(code: str, description: str) -> Path:
    import datetime as dt
    ts  = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log = _LOG_DIR / f"exec_{ts}.log"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log.write_text(
        f"# MARK XXXV Generated Code Execution\n"
        f"# Time: {dt.datetime.now().isoformat()}\n"
        f"# Goal: {description}\n"
        f"# -----------------------------------------\n\n{code}",
        encoding="utf-8"
    )
    return log


def _sandbox_safe_run(code_path: str) -> subprocess.CompletedProcess:
    sandbox_wrapper = (
        "import builtins, sys, json, traceback\n"
        "_orig_builtins = vars(builtins)\n"
        f"_blocked = frozenset({list(_DANGEROUS_BUILTINS)!r})\n"
        "for _name in _blocked:\n"
        "    if _name in _orig_builtins:\n"
        "        delattr(builtins, _name)\n"
        "for _mod in list(sys.modules):\n"
        "    if any(_mod.startswith(p) for p in (\n"
        "        'ctypes', 'http.', 'telnetlib', 'ssl', 'cryptography',\n"
        "        'http.server', 'socketserver', 'ftplib', 'pdb'\n"
        "    )):\n"
        "        sys.modules.pop(_mod, None)\n"
        "import os, subprocess, pathlib, urllib, tempfile, shutil\n"
        "os.chdir(str(pathlib.Path.home()))\n"
        f"exec(open(r'{code_path}', encoding='utf-8').read())\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix="_sandbox_runner.py", delete=False, encoding="utf-8"
    ) as f:
        f.write(sandbox_wrapper)
        runner = f.name
    try:
        return subprocess.run(
            [sys.executable, runner, code_path],
            capture_output=True, text=True,
            timeout=120, cwd=str(Path.home())
        )
    finally:
        with contextlib.suppress(Exception):
            os.unlink(runner)


def _run_generated_code(description: str, speak: Callable | None = None) -> str:
    from google.genai import Client
    from google.genai.types import GenerateContentConfig
    if speak:
        speak("Writing custom code for this task, sir.")
    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"
    if not desktop.exists():
        try:
            import winreg
            key     = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass
    client = Client(api_key=_get_api_key())
    system_instruction = (
        "You are an expert Python developer. "
        "Write clean, complete, working Python code. "
        "Use standard library + common packages. "
        "Return ONLY the Python code. No explanation, no markdown, no backticks.\n\n"
        f"SYSTEM PATHS:\n"
        f"  Desktop   = r'{desktop}'\n"
        f"  Downloads = r'{downloads}'\n"
        f"  Documents = r'{documents}'\n"
        f"  Home      = r'{home}'\n"
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Write Python code to accomplish this task:\n\n{description}",
            config=GenerateContentConfig(system_instruction=system_instruction)
        )
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name
        log_path = _log_execution(code, description)
        print(f"[Executor] [CODE] Running generated code (logged to {log_path})")
        result = _sandbox_safe_run(tmp_path)
        with contextlib.suppress(Exception):
            os.unlink(tmp_path)
        output = result.stdout.strip()
        error  = result.stderr.strip()
        if result.returncode == 0 and output:
            return output
        if result.returncode == 0:
            return "Task completed successfully."
        if error:
            raise RuntimeError(f"Code error: {error[:400]}")
        return "Completed."
    except subprocess.TimeoutExpired:
        raise RuntimeError("Generated code timed out after 120 seconds.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Generated code failed: {e}")


# ── Context injection ──────────────────────────────────────────────────────────

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params
    params = dict(params)
    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                params["content"] = combined
                print("[Executor] [INJECT] Injected content from previous steps")
    if step_results and "context" not in params:
        prev = {k: str(v)[:500] for k, v in step_results.items() if v}
        if prev:
            params["_previous_results"] = prev
    return params


def _detect_language(text: str) -> str:
    try:
        from google.genai import Client
        client = Client(api_key=_get_api_key())
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=(
                "What language is this text written in? "
                "Reply with ONLY the language name in English.\n\nText: " + text[:200]
            )
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        from google.genai import Client
        client = Client(api_key=_get_api_key())
        target = _detect_language(goal)
        print(f"[Executor] [LANG] Translating to: {target}")
        prompt = (
            f"Translate the following text into {target}.\n"
            f"IMPORTANT: Translate EVERYTHING. Keep facts and structure.\n"
            f"Output ONLY the translated text.\n\nText:\n{content[:4000]}"
        )
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[Executor] WARN Translation failed: {e}")
        return content


# ── Agent Executor ─────────────────────────────────────────────────────────────

class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2
    STUCK_TIMEOUT_SECONDS = 45

    # Fast-path patterns: (priority, trigger_keywords, tool_name, params_factory)
    # Higher priority = checked first. Keywords checked in order within each priority.
    _FAST_PATTERNS: list[tuple[int, tuple[str, ...], str, Callable]] = [
        # Priority 10: System info - exact matches
        (10, ("what is my ip", "my ip address", "show my ip"),
         "cmd_control",     lambda g: {"task": "ip address", "visible": False}),
        (10, ("disk space", "free space on c", "storage used"),
         "cmd_control",     lambda g: {"task": "disk space", "visible": False}),
        (10, ("system info", "computer info", "pc specs", "my hardware"),
         "cmd_control",     lambda g: {"task": "system info", "visible": False}),
        (10, ("task manager", "running processes", "what's running"),
         "cmd_control",     lambda g: {"task": "running processes", "visible": False}),
        (10, ("cpu usage", "processor load"),
         "cmd_control",     lambda g: {"task": "cpu usage", "visible": False}),
        (10, ("memory usage", "ram usage", "how much ram"),
         "cmd_control",     lambda g: {"task": "memory usage", "visible": False}),
        (10, ("windows version", "os version", "which windows"),
         "cmd_control",     lambda g: {"task": "windows version", "visible": False}),
        (10, ("wifi networks", "available wifi", "wireless networks nearby"),
         "cmd_control",     lambda g: {"task": "wifi networks", "visible": False}),
        (10, ("current time", "what time is it", "time now"),
         "cmd_control",     lambda g: {"task": "current time", "visible": False}),
        (10, ("current date", "what day is it", "today's date"),
         "cmd_control",     lambda g: {"task": "current date", "visible": False}),

        # Priority 9: App launching
        (9, ("open notepad", "launch notepad", "start notepad"),
         "open_app",        lambda g: {"app_name": "Notepad"}),
        (9, ("open calculator", "launch calculator", "start calculator", "open calc"),
         "open_app",        lambda g: {"app_name": "Calculator"}),
        (9, ("open task manager", "launch task manager"),
         "open_app",        lambda g: {"app_name": "Task Manager"}),
        (9, ("open settings", "open windows settings", "launch settings"),
         "open_app",        lambda g: {"app_name": "Settings"}),
        (9, ("open file explorer", "open explorer", "launch file explorer"),
         "open_app",        lambda g: {"app_name": "File Explorer"}),
        (9, ("open whatsapp", "launch whatsapp", "start whatsapp"),
         "open_app",        lambda g: {"app_name": "WhatsApp"}),
        (9, ("open spotify", "launch spotify", "start spotify"),
         "open_app",        lambda g: {"app_name": "Spotify"}),
        (9, ("open vscode", "open vs code", "launch vscode"),
         "open_app",        lambda g: {"app_name": "VS Code"}),
        (9, ("open chrome", "launch chrome", "start chrome"),
         "open_app",        lambda g: {"app_name": "Google Chrome"}),
        (9, ("open edge", "launch edge", "start microsoft edge"),
         "open_app",        lambda g: {"app_name": "Microsoft Edge"}),
        (9, ("open discord", "launch discord", "start discord"),
         "open_app",        lambda g: {"app_name": "Discord"}),
        (9, ("open teams", "launch teams", "start microsoft teams"),
         "open_app",        lambda g: {"app_name": "Microsoft Teams"}),
        (9, ("open", "launch", "start"),
         "open_app",        lambda g: {"app_name": _extract_app_name(g)}),

        # Priority 8: Web search
        (8, ("search for", "search", "google", "look up", "find information about",
              "what is", "who is", "how to", "what are", "tell me about", "what's"),
         "web_search",      lambda g: {"query": g}),

        # Priority 7: Weather
        (7, ("weather", "temperature in", "forecast for", "is it raining"),
         "weather_report",  lambda g: {"city": _extract_city(g)}),

        # Priority 6: YouTube
        (6, ("play", "youtube", "watch on youtube", "find on youtube", "search youtube for"),
         "youtube_video",   lambda g: {"action": "play", "query": g}),

        # Priority 6: File listing
        (6, ("list files on desktop", "show desktop files", "files on my desktop"),
         "file_controller", lambda g: {"action": "list", "path": "desktop"}),
        (6, ("list downloads", "show downloads", "files in downloads"),
         "file_controller", lambda g: {"action": "list", "path": "downloads"}),
        (6, ("list documents", "show documents"),
         "file_controller", lambda g: {"action": "list", "path": "documents"}),
        (6, ("list files", "show files", "browse files"),
         "file_controller", lambda g: {"action": "list", "path": "desktop"}),

        # Priority 5: Reminders
        (5, ("remind me in", "set a reminder", "set reminder", "remind me to",
              "in 5 minutes", "in 10 minutes", "in 15 minutes", "in 30 minutes",
              "in 1 hour", "in 2 hours"),
         "reminder",        lambda g: _extract_reminder(g)),

        # Priority 5: Browser navigation
        (5, ("go to", "navigate to", "open website", "browse to"),
         "browser_control",  lambda g: _extract_browser_url(g)),
        (5, ("close browser", "close chrome", "close tab"),
         "browser_control",  lambda g: {"action": "close"}),

        # Priority 5: Computer settings
        (5, ("volume up", "turn up volume", "increase volume"),
         "computer_settings", lambda g: {"action": "volume_up", "value": "5"}),
        (5, ("volume down", "turn down volume", "decrease volume"),
         "computer_settings", lambda g: {"action": "volume_down", "value": "5"}),
        (5, ("mute", "mute audio", "silence"),
         "computer_settings", lambda g: {"action": "mute"}),
        (5, ("unmute", "unmute audio"),
         "computer_settings", lambda g: {"action": "unmute"}),
        (5, ("take screenshot", "screenshot", "capture screen", "screen shot"),
         "computer_control",  lambda g: {"action": "screenshot"}),
        (5, ("brightness up", "increase brightness"),
         "computer_settings", lambda g: {"action": "brightness_up"}),
        (5, ("brightness down", "decrease brightness"),
         "computer_settings", lambda g: {"action": "brightness_down"}),

        # Priority 4: Messages
        (4, ("send whatsapp", "send a whatsapp", "message on whatsapp", "whatsapp message"),
         "send_message",    lambda g: _extract_message(g, "WhatsApp")),
        (4, ("send telegram", "send a telegram", "message on telegram"),
         "send_message",    lambda g: _extract_message(g, "Telegram")),

        # Priority 4: GitHub
        (4, ("my github repos", "list my repositories", "list github repos"),
         "github_tool",      lambda g: {"action": "list_repos"}),
        (4, ("github stats", "repo statistics", "repository stats"),
         "github_tool",      lambda g: {"action": "repo_stats", "repo": _extract_github_repo(g)}),

        # Priority 3: Games
        (3, ("update steam games", "update all games", "update my games"),
         "game_updater",     lambda g: {"action": "update", "platform": "both"}),
        (3, ("list installed games", "what games do i have", "installed games"),
         "game_updater",     lambda g: {"action": "list"}),

        # Priority 2: Desktop control
        (2, ("set wallpaper", "change wallpaper", "wallpaper"),
         "desktop_control",   lambda g: {"action": "wallpaper", "url": _extract_wallpaper_url(g)}),
        (2, ("organize desktop", "clean desktop"),
         "desktop_control",   lambda g: {"action": "organize"}),

        # Priority 1: Screen capture
        (1, ("what do you see", "what's on my screen", "analyze my screen",
              "look at my screen", "describe my screen"),
         "screen_process",    lambda g: {"angle": "screen", "text": _extract_screen_question(g)}),
    ]

    # Maximum number of tool results to keep in conversation context
    MAX_CONTEXT_ENTRIES = 20

    def __init__(self):
        self._completed_actions: dict[str, str] = {}
        self._last_activity_time: float = time.time()
        self._current_step: str | None = None
        # Conversation context buffer: stores recent tool results for context injection
        self._conversation_context: list[dict] = []

    def add_tool_result(self, step_num: str, tool: str, params: dict, result: str) -> None:
        """
        Store a tool execution result in the conversation context buffer.
        Keeps max MAX_CONTEXT_ENTRIES (drops oldest).
        """
        entry = {
            "step": step_num,
            "tool": tool,
            "params": {k: str(v)[:200] for k, v in params.items()},  # Truncate params
            "result": str(result)[:500],  # Truncate result
            "timestamp": datetime.now().isoformat()
        }
        self._conversation_context.append(entry)
        # Drop oldest entries if exceeds max
        while len(self._conversation_context) > self.MAX_CONTEXT_ENTRIES:
            self._conversation_context.pop(0)

    def get_context_for_llm(self) -> str:
        """
        Returns recent conversation context formatted as a string for LLM injection.
        Includes summaries of the last 5 tool executions.
        """
        if not self._conversation_context:
            return ""
        recent = self._conversation_context[-5:]
        lines = ["Context: Recent actions taken:"]
        for entry in recent:
            params_str = ", ".join(f"{k}={v}" for k, v in list(entry["params"].items())[:3])
            result_preview = entry["result"][:80] + ("..." if len(entry["result"]) > 80 else "")
            lines.append(f"  - [{entry['tool']}] {params_str} -> {result_preview}")
        return "\n".join(lines)

    def clear_context(self) -> None:
        """Clear the conversation context buffer."""
        self._conversation_context.clear()

    def _check_stuck_state(self, cancel_flag: threading.Event | None) -> bool:
        """
        Check if the executor is stuck (no activity for STUCK_TIMEOUT_SECONDS).
        Returns True if stuck detected and recovery triggered.
        """
        current_time = time.time()
        if current_time - self._last_activity_time > self.STUCK_TIMEOUT_SECONDS:
            if self._current_step:
                print(f"[Executor] [STUCK] No activity for {self.STUCK_TIMEOUT_SECONDS}s "
                      f"on step: {self._current_step} - attempting recovery")
                if cancel_flag:
                    cancel_flag.set()
                return True
        return False

    def _update_activity(self) -> None:
        """Update the last activity timestamp after a tool completes."""
        self._last_activity_time = time.time()
        self._current_step = None

    def _start_step(self, step_num: str, step_desc: str) -> None:
        """Mark the start of a step for stuck detection."""
        self._current_step = f"Step {step_num}: {step_desc}"
        self._last_activity_time = time.time()

    def _normalize_action_key(self, tool: str, params: dict) -> str:
        """Create a normalized key for action deduplication."""
        key = [tool]
        if tool == "browser_control":
            action = params.get("action", "")
            if action == "go_to":
                key.append(f"goto:{params.get('url', '').lower()}")
            elif action == "search":
                key.append(f"search:{params.get('query', '').lower()}")
            else:
                key.append(f"{action}:{str(sorted(params.items()))[:100]}")
        else:
            key.append(str(sorted(params.items()))[:100])
        return "|".join(key)

    def _is_duplicate_action(self, tool: str, params: dict) -> bool:
        action_key = self._normalize_action_key(tool, params)
        if action_key in self._completed_actions:
            print(f"[Executor] [SKIP] Duplicate action: [{tool}] {params}")
            return True
        return False

    def _mark_action_done(self, tool: str, params: dict, result: str):
        if "error" in result.lower() or "fail" in result.lower():
            return
        action_key = self._normalize_action_key(tool, params)
        self._completed_actions[action_key] = result[:100]

    def _execute_single_step(
        self,
        step: dict,
        step_results: dict,
        goal: str,
        cancel_flag: threading.Event | None,
        speak: Callable | None,
    ) -> tuple[dict | None, str | None, str | None]:
        """Execute a single step with retry logic. Returns (step, error_msg, result)."""
        step_num = step.get("step", "?")
        tool     = step.get("tool", "generated_code")
        desc     = step.get("description", "")
        params   = step.get("parameters", {})

        params = _inject_context(params, tool, step_results, goal=goal)

        if self._is_duplicate_action(tool, params):
            return (step, None, "skipped_duplicate")

        print(f"\n[Executor] Step {step_num}: [{tool}] {desc}")

        attempt = 1
        while attempt <= 3:
            if cancel_flag and cancel_flag.is_set():
                return (None, "cancelled", None)

            try:
                result = _call_tool(tool, params, speak)
                self._mark_action_done(tool, params, str(result))
                # Store result in conversation context buffer
                self.add_tool_result(step_num, tool, params, result)
                return (step, None, result)
            except Exception as e:
                error_msg = str(e)
                print(f"[Executor] FAIL Step {step_num} attempt {attempt}: {error_msg}")
                recovery = analyze_error(step, error_msg, attempt=attempt)
                decision = recovery["decision"]

                if speak and recovery.get("user_message"):
                    speak(recovery["user_message"])

                if decision == ErrorDecision.RETRY:
                    attempt += 1
                    _time_module.sleep(2)
                    continue

                if decision == ErrorDecision.SKIP:
                    print(f"[Executor] [SKIP] Step {step_num}")
                    return (step, None, "skipped")

                if decision == ErrorDecision.ABORT:
                    return (None, f"Task aborted, sir. {recovery.get('reason', '')}", None)

                fix_suggestion = recovery.get("fix_suggestion", "")
                if fix_suggestion and tool != "generated_code":
                    try:
                        fixed_step = generate_fix(step, error_msg, fix_suggestion)
                        if speak:
                            speak("Trying an alternative approach, sir.")
                        res = _call_tool(fixed_step["tool"], fixed_step["parameters"], speak)
                        # Store fixed step result in conversation context
                        self.add_tool_result(step_num, fixed_step["tool"], fixed_step["parameters"], res)
                        return (step, None, res)
                    except Exception as fix_err:
                        print(f"[Executor] WARN Fix failed: {fix_err}")

                return (step, error_msg, None)

        return (step, "Max retries exceeded", None)

    def _try_fast_path(self, goal: str) -> str | None:
        """Return result string if goal is a known single-tool pattern, else None."""
        goal_lower = goal.lower().strip()
        sorted_patterns = sorted(self._FAST_PATTERNS, key=lambda x: -x[0])
        for _, keywords, tool, param_fn in sorted_patterns:
            if any(kw in goal_lower for kw in keywords):
                try:
                    params = param_fn(goal)
                except Exception:
                    continue
                if not params:
                    continue
                try:
                    print(f"[Executor] [FAST] {tool} -- skipping planner")
                    result = _call_tool(tool, params, None)
                    self._mark_action_done(tool, params, str(result))
                    # Track fast path results in context buffer
                    self.add_tool_result("fast", tool, params, result)
                    return self._summarize_fast(goal, tool, result)
                except Exception as e:
                    print(f"[Executor] [FAST] {tool} failed ({e}), falling back to planner")
                    return None
        return None

    def _summarize_fast(self, goal: str, tool: str, result: str) -> str:
        if "error" in str(result).lower() or not result:
            return "Task failed, sir."
        return str(result)[:300]

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Executor] Goal: {goal}")

        self._completed_actions = {}
        self._last_activity_time = time.time()
        self._current_step = None

        # Fast path: single known-tool goals skip the planner
        fast = self._try_fast_path(goal)
        if fast:
            return fast

        replan_attempts = 0
        completed_steps = []
        step_results    = {}
        plan            = create_plan(goal)

        while True:
            steps = plan.get("steps", [])
            if not steps:
                msg = "I couldn't create a valid plan for this task, sir."
                if speak: speak(msg)
                return msg

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Task cancelled, sir.")
                    return "Task cancelled."

                # Check for stuck state before each step
                if self._check_stuck_state(cancel_flag):
                    if speak: speak("Task appeared stuck, attempting recovery, sir.")
                    failed_step = step
                    failed_error = f"Stuck detection triggered on step {step.get('step')}"
                    success = False
                    break

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                # Mark step start for stuck detection
                self._start_step(step_num, desc)

                params = _inject_context(params, tool, step_results, goal=goal)

                if self._is_duplicate_action(tool, params):
                    completed_steps.append(step)
                    self._update_activity()
                    continue

                print(f"\n[Executor] Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    try:
                        result = _call_tool(tool, params, speak)
                        self._mark_action_done(tool, params, str(result))
                        step_results[step_num] = result
                        # Store result in conversation context buffer
                        self.add_tool_result(step_num, tool, params, result)
                        completed_steps.append(step)
                        # Update activity after successful tool execution
                        self._update_activity()
                        print(f"[Executor] OK Step {step_num} done: {str(result)[:100]}")
                        step_ok = True
                        break
                    except Exception as e:
                        error_msg = str(e)
                        print(f"[Executor] FAIL Step {step_num} attempt {attempt}: {error_msg}")
                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        if speak and recovery.get("user_message"):
                            speak(recovery["user_message"])
                        if decision == ErrorDecision.RETRY:
                            attempt += 1
                            _time_module.sleep(2)
                            continue
                        if decision == ErrorDecision.SKIP:
                            print(f"[Executor] [SKIP] Step {step_num}")
                            completed_steps.append(step)
                            self._update_activity()
                            step_ok = True
                            break
                        if decision == ErrorDecision.ABORT:
                            msg = f"Task aborted, sir. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            return msg
                        fix_suggestion = recovery.get("fix_suggestion", "")
                        if fix_suggestion and tool != "generated_code":
                            try:
                                fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                if speak: speak("Trying an alternative approach, sir.")
                                res = _call_tool(fixed_step["tool"], fixed_step["parameters"], speak)
                                step_results[step_num] = res
                                # Store fixed step result in conversation context
                                self.add_tool_result(step_num, fixed_step["tool"], fixed_step["parameters"], res)
                                completed_steps.append(step)
                                self._update_activity()
                                step_ok = True
                                break
                            except Exception as fix_err:
                                print(f"[Executor] WARN Fix failed: {fix_err}")
                        failed_step  = step
                        failed_error = error_msg
                        success      = False
                        break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False
                if not success:
                    break

            if success:
                return self._summarize(goal, completed_steps, speak)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Task failed after {replan_attempts} replan attempts, sir."
                if speak: speak(msg)
                return msg

            if speak: speak("Adjusting my approach, sir.")
            replan_attempts += 1
            plan = replan(goal, completed_steps, failed_step, failed_error)

    def _summarize(self, goal: str, completed_steps: list, speak: Callable | None) -> str:
        fallback = f"All done, sir. Completed {len(completed_steps)} steps for: {goal[:60]}."
        try:
            from google.genai import Client
            client = Client(api_key=_get_api_key())
            steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)
            prompt    = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                "Write a single natural sentence summarizing what was accomplished. "
                "Address the user as 'sir'. Be direct and positive."
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt
            )
            summary = response.text.strip()
            if speak: speak(summary)
            return summary
        except Exception:
            if speak: speak(fallback)
            return fallback
