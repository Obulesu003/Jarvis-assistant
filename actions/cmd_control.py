"""
cmd_control.py — Control Windows CMD / PowerShell / Terminal through JARVIS.

Supports:
  - One-shot commands (hidden, visible)
  - Persistent interactive CMD sessions
  - Output parsing and speech-friendly formatting
  - Claude Code CLI control via the `claude_tool` action
"""
from __future__ import annotations

import logging  # migrated from print()

import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

# ── helpers ──────────────────────────────────────────────────────────────────

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None

def _get_api_key() -> str:
    if _get_gemini_key is not None:
        return _get_gemini_key()
    BASE_DIR = get_base_dir()
    API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
    with open(API_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _get_platform() -> str:
    if sys.platform == "win32":  return "windows"
    if sys.platform == "darwin": return "macos"
    return "linux"

# ── persistent CMD session state ──────────────────────────────────────────────

_session_lock  = threading.Lock()
_cmd_sessions: dict[str, dict] = {}
# session_id -> {"process": Popen, "started": float, "history": [(cmd, output)]}


def _cleanup_stale_sessions(max_age: int = 300) -> None:
    """Remove sessions older than max_age seconds."""
    now = time.time()
    stale = [sid for sid, s in _cmd_sessions.items() if now - s.get("last_used", 0) > max_age]
    for sid in stale:
        proc = _cmd_sessions[sid].get("process")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        del _cmd_sessions[sid]

# ── hardcoded command map ─────────────────────────────────────────────────────

WIN_COMMAND_MAP = [
    (["disk space", "disk usage", "storage", "free space", "c drive space"],
     "wmic logicaldisk get caption,freespace,size /format:list", False),
    (["running processes", "list processes", "show processes", "active processes", "tasklist"],
     "tasklist /fo table", False),
    (["ip address", "my ip", "network info", "ipconfig"],
     "ipconfig /all", False),
    (["ping", "internet connection", "connected to internet"],
     "ping -n 4 google.com", False),
    (["open ports", "listening ports", "netstat"],
     "netstat -an | findstr LISTENING", False),
    (["wifi networks", "available wifi", "wireless networks"],
     "netsh wlan show networks", False),
    (["system info", "computer info", "hardware info", "pc info", "specs"],
     "systeminfo", False),
    (["cpu usage", "processor usage"],
     "wmic cpu get loadpercentage", False),
    (["memory usage", "ram usage"],
     "wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /Value", False),
    (["windows version", "os version"],
     "ver", False),
    (["installed programs", "installed software", "installed apps"],
     "wmic product get name,version /format:table", False),
    (["battery", "battery level", "power status"],
     "powershell (Get-WmiObject -Class Win32_Battery).EstimatedChargeRemaining", False),
    (["current time", "what time", "system time"],
     "time /t", False),
    (["current date", "what date", "system date"],
     "date /t", False),
    (["desktop files", "files on desktop"],
     f'dir "{Path.home() / "Desktop"}" /b', False),
    (["downloads", "files in downloads"],
     f'dir "{Path.home() / "Downloads"}" /b', False),
    (["large files", "biggest files", "largest files"],
     'powershell "Get-ChildItem C:\\ -Recurse -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 10 FullName,Length | Format-Table -AutoSize"', False),
]

def _find_hardcoded(task: str) -> str | None:
    task_lower = task.lower()

    if "notepad" in task_lower or any(ext in task_lower for ext in [".txt", ".log", ".md", ".csv"]):
        file_match = re.search(r'["\']?([\S]+\.(?:txt|log|md|csv|json|xml))["\']?', task, re.IGNORECASE)
        if file_match:
            filename = file_match.group(1)
            desktop  = Path.home() / "Desktop"
            filepath = Path(filename) if Path(filename).is_absolute() else desktop / filename
            return f'notepad "{filepath}"'
        if "notepad" in task_lower:
            return "notepad"

    pip_match = re.search(r"install\s+([\w\-]+)", task_lower)
    if pip_match:
        package = pip_match.group(1)
        return f"pip install {package}"

    for keywords, command, _ in WIN_COMMAND_MAP:
        if command and any(kw in task_lower for kw in keywords):
            return command

    return None

# ── safety ────────────────────────────────────────────────────────────────────

BLOCKED_PATTERNS = [
    r"\brm\s+-rf\b", r"\brmdir\s+/s\b", r"\bdel\s+/[fqs]",
    r"\bformat\b", r"\bdiskpart\b", r"\bfdisk\b",
    r"\breg\s+(delete|add)\b", r"\bbcdedit\b",
    r"\bnet\s+localgroup\b",
    r"\bshutdown\b", r"\brestart-computer\b",
    r"\bstop-process\b", r"\bkill\s+-9\b", r"\btaskkill\b",
    r"\beval\b", r"\b__import__\b",
    r"\bDEL\s+/[FQS]", r"\bFORMAT\b",
]
_BLOCKED_RE = re.compile("|".join(BLOCKED_PATTERNS), re.IGNORECASE)

def _is_safe(command: str) -> tuple[bool, str]:
    match = _BLOCKED_RE.search(command)
    if match:
        return False, f"Blocked pattern: '{match.group()}'"
    return True, "OK"

# ── TTS-friendly output formatter ─────────────────────────────────────────────

def _format_for_speech(output: str, max_len: int = 2000) -> str:
    """
    Strip ANSI codes, normalize whitespace, truncate, and make output
    speech-friendly for TTS.
    """
    # Remove ANSI escape codes
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
    # Collapse multiple spaces/newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()

    if len(text) > max_len:
        text = text[:max_len] + "\n\n[Output truncated for speech]"
    return text


# ── command execution ─────────────────────────────────────────────────────────

def _run_silent(command: str, timeout: int = 20) -> str:
    try:
        platform = _get_platform()
        if platform == "windows":
            is_ps = command.strip().lower().startswith("powershell")
            if is_ps:
                cmd_inner = re.sub(r'^powershell\s+"?', '', command, flags=re.IGNORECASE).rstrip('"')
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd_inner],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout
                )
            else:
                result = subprocess.run(
                    ["cmd", "/c", command],
                    capture_output=True, text=True,
                    encoding="cp1252", errors="replace",
                    timeout=timeout, cwd=str(Path.home())
                )
        else:
            shell = "/bin/zsh" if platform == "macos" else "/bin/bash"
            result = subprocess.run(
                command, shell=True, executable=shell,
                capture_output=True, text=True,
                errors="replace", timeout=timeout,
                cwd=str(Path.home())
            )

        output = result.stdout.strip()
        error  = result.stderr.strip()
        if output:  return _format_for_speech(output)
        if error:   return f"[stderr]: {_format_for_speech(error[:500])}"
        return "Command executed with no output."

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except Exception as e:
        return f"Execution error: {e}"


def _run_visible(command: str) -> None:
    try:
        platform = _get_platform()
        if platform == "windows":
            subprocess.Popen(
                f'cmd /k "{command}"',
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        elif platform == "macos":
            subprocess.Popen(["osascript", "-e",
                f'tell application "Terminal" to do script "{command}"'])
        else:
            for term in ["gnome-terminal", "xterm", "konsole"]:
                try:
                    subprocess.Popen([term, "--", "bash", "-c", f"{command}; exec bash"])
                    break
                except FileNotFoundError:
                    continue
    except Exception as e:
        logging.getLogger("CMD").warning(f'Terminal open failed: {e}')


# ── Gemini fallback ───────────────────────────────────────────────────────────

def _ask_gemini(task: str) -> str:
    try:
        from google.genai import Client
        client = Client(api_key=_get_api_key())

        prompt = (
            f"Convert this request to a single Windows CMD command.\n"
            f"Output ONLY the command. No explanation, no markdown, no backticks.\n"
            f"If unsafe or impossible, output: UNSAFE\n\n"
            f"Request: {task}\n\nCommand:"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt
        )
        command  = response.text.strip().strip("`").strip()
        if command.startswith("```"):
            lines   = command.split("\n")
            command = "\n".join(lines[1:-1]).strip()
        return command
    except Exception as e:
        return f"ERROR: {e}"


# ── session helpers ────────────────────────────────────────────────────────────

def _start_cmd_session(session_id: str, cwd: str | None = None) -> dict:
    """Start an interactive CMD session (persistent process)."""
    _cleanup_stale_sessions()

    work_dir = cwd or str(Path.home())
    proc = subprocess.Popen(
        ["cmd", "/k"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=work_dir,
        encoding="cp1252",
        errors="replace",
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
    )
    entry = {
        "process":   proc,
        "cwd":       work_dir,
        "started":   time.time(),
        "last_used": time.time(),
        "history":   [],
    }
    with _session_lock:
        _cmd_sessions[session_id] = entry
    return entry


def _send_session_command(session_id: str, command: str, timeout: int = 30) -> str:
    """Send a command to a persistent CMD session and read output."""
    with _session_lock:
        if session_id not in _cmd_sessions:
            return f"No active session '{session_id}'. Start one first."
        entry = _cmd_sessions[session_id]

    proc = entry["process"]
    if proc.poll() is not None:
        with _session_lock:
            del _cmd_sessions[session_id]
        return "Session ended. Please start a new one."

    try:
        # Send command + newline
        proc.stdin.write(command + "\n")
        proc.stdin.flush()
        time.sleep(1.5)  # Allow output to buffer

        # Read available output
        import select
        lines = []
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], 0.5)
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip())

        output = "\n".join(lines)
        entry["last_used"] = time.time()
        entry["history"].append((command, output))
        return _format_for_speech(output)

    except Exception as e:
        return f"Session error: {e}"


def _close_session(session_id: str) -> str:
    """Terminate a CMD session."""
    with _session_lock:
        if session_id not in _cmd_sessions:
            return f"No active session '{session_id}'."
        entry = _cmd_sessions.pop(session_id)

    proc = entry["process"]
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return f"Session '{session_id}' closed."


# ── main function ─────────────────────────────────────────────────────────────

def cmd_control(
    parameters: dict | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Control CMD / PowerShell via JARVIS.

    Parameters
    ----------
    action : str
        "run" (default) — run a one-shot command
        "session_start" — start a persistent interactive session
        "session_run" — run command in persistent session
        "session_status" — show session info
        "session_end" — close a persistent session
    task : str
        Natural language description of what to do (for auto command generation).
    command : str
        Direct CMD/PowerShell command to run.
    visible : bool
        If True, also open a visible terminal (default True).
    session_id : str
        Session identifier for persistent sessions (default: "default").
    cwd : str
        Working directory for the session (default: user home).
    timeout : int
        Command timeout in seconds (default 20 for run, 30 for session).
    speak_output : bool
        If True, format output to be TTS-friendly (default True).
    """
    parameters = parameters or {}
    action      = parameters.get("action", "run").strip().lower()
    task        = parameters.get("task", "").strip()
    command     = parameters.get("command", "").strip()
    visible     = parameters.get("visible", True)
    session_id  = parameters.get("session_id", "default").strip()
    cwd         = parameters.get("cwd", "").strip()
    timeout     = int(parameters.get("timeout", 20))
    speak_output = parameters.get("speak_output", True)

    # ── session management actions ──────────────────────────────────────────
    if action == "session_status":
        _cleanup_stale_sessions()
        with _session_lock:
            if session_id in _cmd_sessions:
                entry = _cmd_sessions[session_id]
                age = int(time.time() - entry["last_used"])
                hist = len(entry["history"])
                return (
                    f"CMD session '{session_id}' is active.\n"
                    f"  Working dir: {entry['cwd']}\n"
                    f"  Last used: {age}s ago\n"
                    f"  Commands run: {hist}"
                )
            return f"No active CMD session '{session_id}'."

    if action == "session_end":
        return _close_session(session_id)

    if action == "session_start":
        _cleanup_stale_sessions()
        work_dir = cwd or str(Path.home())
        entry = _start_cmd_session(session_id, work_dir)
        return f"CMD session '{session_id}' started in {work_dir}."

    if action == "session_run":
        if not command:
            return "Provide 'command' to run in the session."
        safe, reason = _is_safe(command)
        if not safe:
            return f"Blocked: {reason}"
        if player:
            player.write_log(f"[CMD-Session] {command[:60]}")
        return _send_session_command(session_id, command, timeout=timeout)

    # ── one-shot run ────────────────────────────────────────────────────────
    if not task and not command:
        return "Please describe what you want to do, sir."

    if not command:
        command = _find_hardcoded(task)
        if command:
            logging.getLogger("CMD").info(f'Hardcoded: {command[:80]}')
        else:
            logging.getLogger("CMD").info(f'Gemini fallback for: {task}')
            command = _ask_gemini(task)
            logging.getLogger("CMD").info(f'Generated: {command[:80]}')
            if command == "UNSAFE":
                return "I cannot generate a safe command for that request, sir."
            if command.startswith("ERROR:"):
                return f"Could not generate command: {command}"

    safe, reason = _is_safe(command)
    if not safe:
        return f"Blocked for safety: {reason}"

    if player:
        player.write_log(f"[CMD] {command[:60]}")

    # Open apps directly (no exec needed)
    if any(x in command.lower() for x in ["notepad", "explorer", "start "]):
        subprocess.Popen(command, shell=True)
        return f"Opened: {command}"

    if visible:
        _run_visible(command)
        output = _run_silent(command, timeout=timeout)
        if speak_output:
            return output
        return f"Terminal opened.\n\nOutput:\n{output}"
    return _run_silent(command, timeout=timeout)
