"""
claude_tool.py — Control Claude Code CLI through JARVIS.

Usage: When the user asks to:
  - "run a claude command" / "use claude code to..."
  - "ask claude about..." / "let claude help with..."
  - "use claude to review / write / explain..."

This tool runs the `claude` CLI with --print flag for non-interactive output,
pipes the request as a prompt, and returns the result for TTS.
"""
import logging  # migrated from print()
from __future__ import annotations

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


def _find_claude_exe() -> str | None:
    """Find the claude CLI executable on PATH."""
    for name in ("claude", "claude.cmd", "claude.bat", "claude.exe"):
        try:
            result = subprocess.run(
                ["where" if sys.platform == "win32" else "which", name],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split("\n")[0].strip()
        except Exception:
            pass

    # Try common install locations on Windows
    if sys.platform == "win32":
        candidates = [
            Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
            Path.home() / "AppData" / "Local" / "npm" / "claude.cmd",
            Path("C:/Program Files/claude/claude.cmd"),
            Path("C:/Program Files (x86)/claude/claude.cmd"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    return None


def _is_safe_request(request: str) -> tuple[bool, str]:
    """Basic safety check on the user's request before passing to Claude."""
    blocked = [
        r"\brm\s+-rf\b", r"\bdel\s+/[fqs]", r"\bformat\b",
        r"\bshutdown\b", r"\brestart\b", r"\bkill\b",
    ]
    combined = "|".join(blocked)
    match = re.search(combined, request, re.IGNORECASE)
    if match:
        return False, f"Blocked pattern: '{match.group()}'"
    return True, "OK"


# ── Claude Code session state ────────────────────────────────────────────────

_session_lock = threading.Lock()
_active_sessions: dict[str, dict[str, Any]] = {}
# Maps session_id -> {"cwd": str, "started": float, "last_used": float}


def _ensure_session(session_id: str, cwd: str | None = None) -> dict[str, Any]:
    with _session_lock:
        if session_id not in _active_sessions:
            _active_sessions[session_id] = {
                "cwd": cwd or str(Path.home()),
                "started": time.time(),
                "last_used": time.time(),
            }
        else:
            _active_sessions[session_id]["last_used"] = time.time()
        return _active_sessions[session_id]


# ── Core function ─────────────────────────────────────────────────────────────

def claude_tool(
    parameters: dict,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Run a Claude Code CLI command via JARVIS.

    Parameters
    ----------
    task : str
        Natural language request for Claude Code (e.g. "explain this code",
        "write a function that...").
    mode : str
        "ask" (default) — ask Claude a question, return answer.
        "write" — ask Claude to write/edit code, return confirmation.
        "review" — ask Claude to review code.
        "run" — ask Claude to run a task via Claude Code.
    project : str
        Optional project directory. Defaults to MARK's project root.
    session_id : str
        Optional session identifier for context persistence.
    timeout : int
        Max seconds to wait for Claude (default 60).
    """
    task      = (parameters or {}).get("task", "").strip()
    mode      = (parameters or {}).get("mode", "ask").strip().lower()
    project   = (parameters or {}).get("project", "").strip()
    session_id = (parameters or {}).get("session_id", "default").strip()
    timeout   = int((parameters or {}).get("timeout", 60))

    if not task:
        return "Please specify what you want Claude to do, sir."

    # Safety check
    safe, reason = _is_safe_request(task)
    if not safe:
        return f"Blocked for safety: {reason}"

    # Find Claude CLI
    claude_exe = _find_claude_exe()
    if not claude_exe:
        return (
            "Claude Code CLI is not installed or not on PATH, sir. "
            "Install it with: npm install -g @anthropic-ai/claude-code"
        )

    # Determine working directory
    if project:
        cwd = str(Path(project).resolve())
        if not Path(cwd).exists():
            return f"Project directory not found: {project}"
    else:
        cwd = str(get_base_dir())

    _ensure_session(session_id, cwd)

    if player:
        player.write_log(f"[Claude] task={task[:60]} mode={mode}")

    # Build the prompt based on mode
    if mode == "ask":
        prompt = task
    elif mode == "write":
        prompt = (
            f"Write or edit the code as requested. "
            f"Only output the code and a brief confirmation. "
            f"Task: {task}"
        )
    elif mode == "review":
        prompt = (
            f"Review the code or files related to this request and provide feedback. "
            f"Be concise. Task: {task}"
        )
    elif mode == "run":
        prompt = (
            f"Execute the following task using Claude Code tools. "
            f"Report what you did and the results. "
            f"Task: {task}"
        )
    else:
        prompt = task

    # Escape prompt for shell
    safe_prompt = prompt.replace('"', '\\"').replace('`', '\\`')

    # Build claude command — use --print for non-interactive output
    # Additional flags: --no-input for no prompting, --output-format for structured output
    cmd = [
        claude_exe,
        "--print",
        "--no-input",
        "--dangerously-skip-permissions",
        "--prompt", safe_prompt,
    ]

    logging.getLogger("Claude").info("Executing: {' '.join(cmd[:4])} ...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )

        output = result.stdout.strip()
        error  = result.stderr.strip()

        if output:
            # Truncate very long outputs for TTS
            if len(output) > 3000:
                output = output[:3000] + "\n\n[Output truncated for speech]"
            logging.getLogger("Claude").debug(f"Output ({len(output)} chars)")
            return output
        if error:
            # Some errors are informational, not critical
            if any(x in error.lower() for x in ["no project", "warning", "deprecated"]):
                logging.getLogger("Claude").warning(f'{error[:300]}')
                return f"Claude completed with a note: {error[:500]}"
            logging.getLogger("Claude").info(f'{error[:300]}')
            return f"Claude encountered an error: {error[:500]}"
        return "Claude completed the task with no output."

    except subprocess.TimeoutExpired:
        return f"Claude timed out after {timeout} seconds. Try a shorter request."
    except FileNotFoundError:
        return "Claude Code CLI not found. Please install it first."
    except Exception as e:
        return f"Claude execution error: {e}"


# ── Persistent session support ───────────────────────────────────────────────

def claude_session(
    parameters: dict,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Start or continue a Claude Code CLI session.

    Use this when the user wants to have a back-and-forth conversation with
    Claude Code, or run multiple related commands in the same project context.

    Parameters
    ----------
    action : str
        "start" — start a new session (requires 'task')
        "continue" — continue existing session with a follow-up (requires 'task')
        "status" — show current session info
        "end" — end the current session
    session_id : str
        Session identifier (default: "default")
    project : str
        Project directory for the session
    task : str
        Task/prompt for the session (for start/continue)
    timeout : int
        Max seconds per response (default 90)
    """
    action     = (parameters or {}).get("action", "").strip().lower()
    session_id = (parameters or {}).get("session_id", "default").strip()
    project    = (parameters or {}).get("project", "").strip()
    task       = (parameters or {}).get("task", "").strip()
    timeout    = int((parameters or {}).get("timeout", 90))

    claude_exe = _find_claude_exe()
    if not claude_exe:
        return (
            "Claude Code CLI is not installed, sir. "
            "Install it with: npm install -g @anthropic-ai/claude-code"
        )

    if action == "status":
        with _session_lock:
            if session_id in _active_sessions:
                s = _active_sessions[session_id]
                age = int(time.time() - s["last_used"])
                return (
                    f"Active Claude session '{session_id}':\n"
                    f"  Working dir: {s['cwd']}\n"
                    f"  Last used: {age}s ago\n"
                    f"  Started: {time.strftime('%H:%M:%S', time.localtime(s['started']))}"
                )
            return f"No active session '{session_id}'. Start one with action='start'."

    if action == "end":
        with _session_lock:
            if session_id in _active_sessions:
                del _active_sessions[session_id]
        return f"Session '{session_id}' ended."

    if action in ("start", "continue"):
        if not task:
            return "Please provide a 'task' (prompt) for the Claude session."

        cwd = project or (get_base_dir() if not project else str(Path(project).resolve()))
        _ensure_session(session_id, cwd)

        safe_prompt = task.replace('"', '\\"').replace('`', '\\`')

        cmd = [
            claude_exe,
            "--print",
            "--no-input",
            "--dangerously-skip-permissions",
            "--prompt", safe_prompt,
        ]

        if player:
            player.write_log(f"[ClaudeSession] [{action}] {task[:60]}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=cwd,
            )

            output = result.stdout.strip()
            error  = result.stderr.strip()

            with _session_lock:
                if session_id in _active_sessions:
                    _active_sessions[session_id]["last_used"] = time.time()

            if output:
                if len(output) > 3000:
                    output = output[:3000] + "\n\n[Output truncated]"
                return output
            if error:
                if any(x in error.lower() for x in ["warning", "deprecated"]):
                    return f"{error[:500]}"
                return f"Error: {error[:500]}"
            return "Claude session completed with no output."

        except subprocess.TimeoutExpired:
            return f"Session timed out after {timeout}s. Try a shorter request."
        except Exception as e:
            return f"Session error: {e}"

    return (
        "Unknown action. Use: start, continue, status, or end. "
        "Example: action='start', task='explain this code in main.py'"
    )
