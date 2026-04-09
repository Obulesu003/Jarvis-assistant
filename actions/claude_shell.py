"""
claude_shell.py — Persistent interactive Claude Code CLI shell.

This provides a full "take over" experience where JARVIS acts as the
front-end to Claude Code CLI:
  - Starts ONE Claude Code process (stays alive)
  - Sends prompts, reads responses, handles approval prompts
  - Supports Ctrl+C interrupts, session resume, history
  - Exposes: shell_start, shell_send, shell_status, shell_interrupt, shell_end

Usage:
  shell_start  → starts Claude Code in background
  shell_send   → sends a prompt, waits for response
  shell_status → shows what's happening
  shell_interrupt → sends Ctrl+C to break current action
  shell_end    → terminates the Claude Code process
"""
import logging  # migrated from print()
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

# ── globals ───────────────────────────────────────────────────────────────────

_shell_lock  = threading.RLock()   # Guards _active_shell
_active_shell: "ClaudeShell | None" = None


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _find_claude_exe() -> str | None:
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
    if sys.platform == "win32":
        candidates = [
            Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
            Path.home() / "AppData" / "Local" / "npm" / "claude.cmd",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return None


# ── ClaudeShell ───────────────────────────────────────────────────────────────

class ClaudeShell:
    """
    Wraps a long-running `claude` subprocess with stdin/stdout buffering.

    Designed for "headless terminal" use: start once, send multiple prompts,
    interrupt mid-action, check status, close cleanly.
    """

    # States
    STATE_STOPPED   = "stopped"
    STATE_STARTING  = "starting"
    STATE_READY      = "ready"      # waiting for input
    STATE_THINKING   = "thinking"   # Claude is processing
    STATE_RESPONSE   = "response"   # output being streamed
    STATE_INTERRUPTED = "interrupted"
    STATE_ERROR     = "error"

    def __init__(self, session_id: str = "default"):
        self.session_id    = session_id
        self.process: subprocess.Popen | None = None
        self.state         = self.STATE_STOPPED
        self.state_changed = threading.Event()

        self._stdout_thread: threading.Thread | None = None
        self._buffer: list[str] = []
        self._buffer_lock = threading.Lock()
        self._response_ready = threading.Event()
        self._error_msg   = ""

        self.prompt_count  = 0
        self.created_at   = time.time()
        self.last_active  = time.time()

        # Project context
        self.cwd = str(get_base_dir())

        self._cmd_prefix = []  # e.g. ["cmd", "/c", "start", ...] or just ["claude"]

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self, cwd: str | None = None) -> tuple[bool, str]:
        """Launch the claude subprocess. Returns (success, message)."""
        with _shell_lock:
            if self.process and self.process.poll() is None:
                return True, f"Claude shell '{self.session_id}' is already running."

        if cwd:
            self.cwd = cwd
        if not Path(self.cwd).exists():
            self.cwd = str(Path.home())

        claude_exe = _find_claude_exe()
        if not claude_exe:
            self.state = self.STATE_ERROR
            self._error_msg = "Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
            return False, self._error_msg

        self.state = self.STATE_STARTING
        self.state_changed.set()
        self._error_msg = ""

        logging.getLogger("ClaudeShell").info(f"Launching: {claude_exe}")
        logging.getLogger("ClaudeShell").info(f"Working dir: {self.cwd}")

        try:
            env = os.environ.copy()
            # Disable Claude's terminal colouring to simplify parsing
            env["NO_COLOR"] = "1"
            env["CLAUDE_DISABLE_COLOR"] = "1"

            self.process = subprocess.Popen(
                [claude_exe],
                stdin  = subprocess.PIPE,
                stdout = subprocess.PIPE,
                stderr = subprocess.PIPE,
                cwd    = self.cwd,
                env    = env,
                text   = True,
                encoding = "utf-8",
                errors = "replace",
                bufsize = 1,           # line-buffered
            )

            self._stdout_thread = threading.Thread(
                target=self._reader_loop,
                name=f"ClaudeOut-{self.session_id}",
                daemon=True,
            )
            self._stdout_thread.start()

            # Wait for startup (give it a few seconds)
            time.sleep(3)

            if self.process.poll() is not None:
                _, stderr = self.process.communicate()
                self.state = self.STATE_ERROR
                self._error_msg = f"Claude exited immediately. stderr: {stderr[:300]}"
                return False, self._error_msg

            self.state = self.STATE_READY
            self.last_active = time.time()
            logging.getLogger("ClaudeShell").debug('Started in {self.cwd}')
            return True, f"Claude Code shell started. Working in: {self.cwd}"

        except FileNotFoundError:
            self.state = self.STATE_ERROR
            self._error_msg = "claude command not found."
            return False, self._error_msg
        except Exception as e:
            self.state = self.STATE_ERROR
            self._error_msg = str(e)
            return False, f"Failed to start: {e}"

    def _reader_loop(self) -> None:
        """Background thread that reads claude's stdout line by line."""
        if not self.process:
            return
        proc = self.process

        while True:
            try:
                line = proc.stdout.readline()
                if not line:
                    # EOF — process ended
                    rc = proc.poll()
                    with self._buffer_lock:
                        self._buffer.append(f"[ClaudeShell] Process ended (exit {rc})")
                    self.state = self.STATE_STOPPED if rc == 0 else self.STATE_ERROR
                    self.state_changed.set()
                    self._response_ready.set()
                    break

                line = line.rstrip("\n\r")

                # Detect state changes from output patterns
                if any(x in line for x in ["Thinking...", "Working..."]):
                    self._set_state(self.STATE_THINKING)
                elif any(x in line for x in ["[y/N]", "[Y/n]", "Approve?", "Continue?"]):
                    self._set_state(self.STATE_RESPONSE)
                    with self._buffer_lock:
                        self._buffer.append(f"[PROMPT] {line}")
                    self._response_ready.set()
                elif re.match(r"^\s*(Done|Completed|Success|Wrote|Moved|Deleted|Copied)", line, re.I):
                    self._set_state(self.STATE_RESPONSE)
                    with self._buffer_lock:
                        self._buffer.append(line)
                    self._response_ready.set()
                else:
                    with self._buffer_lock:
                        self._buffer.append(line)

            except Exception as e:
                with self._buffer_lock:
                    self._buffer.append(f"[Reader error] {e}")
                self._response_ready.set()
                break

    def _set_state(self, new_state: str) -> None:
        self.state = new_state
        self.last_active = time.time()
        self.state_changed.set()

    # ── send ─────────────────────────────────────────────────────────────────

    def send(
        self,
        prompt: str,
        timeout: int = 120,
        auto_approve: bool = False,
    ) -> tuple[str, str]:
        """
        Send a prompt to Claude and wait for the response.

        Returns (output, state)
        output is everything Claude wrote since sending the prompt.
        """
        if not self.process or self.process.poll() is not None:
            return "[ERROR] Claude shell is not running. Call shell_start first.", self.STATE_STOPPED

        with self._buffer_lock:
            # Clear buffer up to this point (skip stale output)
            self._buffer.clear()
        self._response_ready.clear()
        self._set_state(self.STATE_THINKING)

        prompt_text = prompt.strip()
        logging.getLogger("ClaudeShell").info('[{self.session_id}] >> {prompt_text[:80]}')

        try:
            self.process.stdin.write(prompt_text + "\n")
            self.process.stdin.flush()
            self.prompt_count += 1
            self.last_active = time.time()

            # Wait for response with timeout
            got_response = self._response_ready.wait(timeout=timeout)

            if not got_response:
                return "[TIMEOUT] Claude took too long. Use shell_interrupt to cancel.", self.STATE_THINKING

        except (BrokenPipeError, IOError):
            return "[ERROR] Claude process ended unexpectedly.", self.STATE_STOPPED
        except Exception as e:
            return f"[ERROR] {e}", self.STATE_ERROR

        # Collect output
        with self._buffer_lock:
            output_lines = list(self._buffer)
            self._buffer.clear()

        output = "\n".join(output_lines).strip()
        self._set_state(self.STATE_READY)

        # Auto-approve if requested (e.g. --yes flag)
        if auto_approve and any(x in output for x in ["[y/N]", "[Y/n]"]):
            self._set_state(self.STATE_THINKING)
            try:
                self.process.stdin.write("y\n")
                self.process.stdin.flush()
                time.sleep(2)
                with self._buffer_lock:
                    extra = list(self._buffer)
                    self._buffer.clear()
                if extra:
                    output += "\n" + "\n".join(extra)
            except Exception:
                pass

        if not output:
            output = "Claude completed with no output."
        elif len(output) > 4000:
            output = output[:4000] + "\n\n[Output truncated]"

        logging.getLogger("ClaudeShell").debug('Response ({len(output)} chars)')
        return output, self.state

    def interrupt(self) -> str:
        """Send Ctrl+C to break the current Claude action."""
        if not self.process or self.process.poll() is not None:
            return "Claude shell is not running."

        logging.getLogger("ClaudeShell").info('Interrupt sent')
        try:
            # On Windows we can't use SIGINT — use INPUT batch char
            if sys.platform == "win32":
                self.process.stdin.write("\x03")  # Ctrl+C
            else:
                self.process.send_signal(signal.SIGINT)
            self.process.stdin.flush()
            time.sleep(1)
            self._set_state(self.STATE_INTERRUPTED)
            return "Interrupt sent to Claude."
        except Exception as e:
            return f"Interrupt failed: {e}"

    def status(self) -> str:
        """Return a human-readable status snapshot."""
        if not self.process or self.process.poll() is not None:
            state = "stopped"
        else:
            state = self.state

        age = int(time.time() - self.created_at)
        idle = int(time.time() - self.last_active)
        lines_in_buf = len(self._buffer) if self._buffer else 0

        return (
            f"Claude Shell '{self.session_id}':\n"
            f"  State   : {state}\n"
            f"  CWD     : {self.cwd}\n"
            f"  Prompts : {self.prompt_count}\n"
            f"  Age     : {age}s\n"
            f"  Idle    : {idle}s\n"
            f"  Buffer  : {lines_in_buf} lines\n"
            f"  PID     : {self.process.pid if self.process and self.process.poll() is None else 'N/A'}"
        )

    def buffer_lines(self) -> list[str]:
        """Return current buffered output lines (for polling)."""
        with self._buffer_lock:
            return list(self._buffer)

    def end(self) -> str:
        """Terminate the Claude subprocess cleanly."""
        with _shell_lock:
            return self._do_end()

    def _do_end(self) -> str:
        if not self.process:
            return f"Shell '{self.session_id}' was not running."

        proc = self.process
        self.process = None
        self._set_state(self.STATE_STOPPED)

        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        except Exception:
            pass

        self._response_ready.set()  # Unblock any waiting send()
        logging.getLogger("ClaudeShell").info("Shell '{self.session_id}' terminated.")
        return f"Claude shell '{self.session_id}' ended."


# ── global shell management ───────────────────────────────────────────────────

def _get_shell(session_id: str = "default") -> ClaudeShell:
    """Get or create the global shell instance."""
    global _active_shell
    with _shell_lock:
        if _active_shell is None:
            _active_shell = ClaudeShell(session_id=session_id)
        return _active_shell


# ── tool entry points ─────────────────────────────────────────────────────────

def shell_start(
    parameters: dict | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Start a persistent Claude Code CLI shell.

    Parameters
    ----------
    session_id : str — identifier for this shell (default: "default")
    cwd       : str — working directory (default: MARK project root)
    """
    params = parameters or {}
    session_id = params.get("session_id", "default")
    cwd = params.get("cwd", "").strip() or None

    if player:
        player.write_log(f"[ClaudeShell] start session={session_id}")

    shell = _get_shell(session_id)
    success, msg = shell.start(cwd=cwd)
    return msg


def shell_send(
    parameters: dict | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """
    Send a prompt to the running Claude Code shell and get the response.

    Parameters
    ----------
    prompt        : str — what to ask Claude
    timeout       : int — seconds to wait for response (default 120)
    auto_approve  : bool — auto-confirm y/n prompts (default False)
    session_id    : str — shell to use (default: "default")
    """
    params = parameters or {}
    prompt = params.get("prompt", "").strip()
    timeout = int(params.get("timeout", 120))
    auto_approve = bool(params.get("auto_approve", False))
    session_id = params.get("session_id", "default")

    if not prompt:
        return "Please provide a 'prompt' for Claude."

    if player:
        player.write_log(f"[ClaudeShell] prompt={prompt[:60]}")

    shell = _get_shell(session_id)

    if not shell.process or shell.process.poll() is not None:
        # Auto-start if not running
        success, msg = shell.start()
        if not success:
            return f"Could not start Claude shell: {msg}"
        # Give startup time
        time.sleep(2)

    output, state = shell.send(prompt, timeout=timeout, auto_approve=auto_approve)
    return output


def shell_status(
    parameters: dict | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """Check the status of the Claude Code shell."""
    params = parameters or {}
    session_id = params.get("session_id", "default")
    shell = _get_shell(session_id)
    return shell.status()


def shell_interrupt(
    parameters: dict | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """Send Ctrl+C to interrupt the current Claude action."""
    params = parameters or {}
    session_id = params.get("session_id", "default")
    shell = _get_shell(session_id)
    return shell.interrupt()


def shell_end(
    parameters: dict | None = None,
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> str:
    """Terminate the Claude Code shell."""
    global _active_shell
    params = parameters or {}
    session_id = params.get("session_id", "default")
    shell = _get_shell(session_id)
    msg = shell.end()
    with _shell_lock:
        if _active_shell and _active_shell.session_id == session_id:
            _active_shell = None
    return msg
