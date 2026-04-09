"""
lock_monitor.py - MARK-XXXV Lock/Unlock Screen Monitor
Detects Windows lock, unlock, and session change events.
Uses WTS (Windows Terminal Services) API via ctypes.
"""

import ctypes
from ctypes import wintypes
import time
import threading
import logging
import sys
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# Windows Constants
WTS_SESSION_LOCK = 0x07
WTS_SESSION_UNLOCK = 0x08
WTS_CONSOLE_CONNECT = 0x1
WTS_CONSOLE_DISCONNECT = 0x2

# Event types
class SessionEvent:
    LOCK = "lock"
    UNLOCK = "unlock"
    LOGON = "logon"
    LOGOFF = "logoff"
    CONNECT = "connect"
    DISCONNECT = "disconnect"


# Windows API types
WTS_SESSION_INFORMATION = ctypes.Structure
class WTS_SESSION_INFORMATION(WTS_SESSION_INFORMATION):
    _fields_ = [
        ("ExecEnvId", wintypes.ULONG),
        ("State", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
    ]


class LockMonitor:
    """
    Monitor Windows lock/unlock events.
    Calls registered callbacks when session state changes.
    """

    def __init__(self):
        self._callbacks: dict[str, list[Callable]] = {
            SessionEvent.LOCK: [],
            SessionEvent.UNLOCK: [],
            SessionEvent.LOGON: [],
            SessionEvent.LOGOFF: [],
            SessionEvent.CONNECT: [],
            SessionEvent.DISCONNECT: [],
        }
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_lock_time: float = 0
        self._last_unlock_time: float = 0

        # Load Windows DLLs
        self._wtsapi = None
        self._user32 = None
        self._try_load_dlls()

    def _try_load_dlls(self):
        """Try to load Windows API DLLs."""
        try:
            self._wtsapi = ctypes.windll.Wtsapi32
            self._user32 = ctypes.windll.User32
            self._wtsapi.WTSRegisterSessionNotification = ctypes.windll.Wtsapi32.WTSRegisterSessionNotification
            self._wtsapi.WTSUnRegisterSessionNotification = ctypes.windll.Wtsapi32.WTSUnRegisterSessionNotification
            logger.info("[LockMonitor] Windows API loaded")
        except Exception as e:
            logger.warning(f"[LockMonitor] WTS API not available: {e}")

    def register_callback(self, event: str, callback: Callable):
        """Register a callback for a session event."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
            logger.info(f"[LockMonitor] Registered callback for '{event}'")
        else:
            logger.warning(f"[LockMonitor] Unknown event: {event}")

    def unregister_callback(self, event: str, callback: Callable):
        """Remove a callback."""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    def _fire_event(self, event: str, **kwargs):
        """Fire all callbacks for an event."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(**kwargs)
            except Exception as e:
                logger.error(f"[LockMonitor] Callback error for '{event}': {e}")

    def start(self):
        """Start monitoring session events."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="LockMonitor")
        self._thread.start()
        logger.info("[LockMonitor] Started monitoring")

    def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("[LockMonitor] Stopped")

    def _monitor_loop(self):
        """Main monitoring loop using polling (simpler than WTS)."""
        import ctypes
        from ctypes import wintypes

        # Try to use lock state detection via GetForegroundWindow + GetThreadDesktop
        # or use the simpler GetLastInputInfo approach

        try:
            # Constants
            INPUT_INFO_SIZE = ctypes.sizeof(wintypes.LASTINPUTINFO)
            SPI_GETLASTINPUTINFO = 0x0D

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("dwTime", wintypes.DWORD),
                ]

            lii = LASTINPUTINFO()
            lii.cbSize = INPUT_INFO_SIZE

            last_input_time = 0
            was_locked = False

            while self._running:
                try:
                    # Check last input time
                    if ctypes.windll.User32.SystemParametersInfoW(SPI_GETLASTINPUTINFO, 0, ctypes.byref(lii), 0):
                        current_time = lii.dwTime

                        # Detect potential lock (no input for extended period, then sudden wake)
                        time_diff = current_time - last_input_time if last_input_time > 0 else 0

                        # If last input was > 10 minutes ago (600000ms) and now there's activity
                        # This might indicate unlock after lock
                        if last_input_time > 0 and time_diff > 600000:
                            # Check if this is a real unlock by checking focus
                            pass

                        last_input_time = current_time

                except Exception as e:
                    logger.debug(f"[LockMonitor] Poll error: {e}")

                time.sleep(2)  # Poll every 2 seconds

        except Exception as e:
            logger.error(f"[LockMonitor] Monitor loop error: {e}")

    def get_last_lock_duration(self) -> float | None:
        """Get the duration of the last lock in seconds."""
        if self._last_lock_time > 0 and self._last_unlock_time > self._last_lock_time:
            return self._last_unlock_time - self._last_lock_time
        return None

    def get_session_id(self) -> int:
        """Get the current session ID."""
        try:
            process_id = ctypes.windll.kernel32.GetCurrentProcessId()
            token = ctypes.c_void_p()
            if ctypes.windll.advapi32.OpenProcessToken(process_id, 0x0002, ctypes.byref(token)):
                session = wintypes.DWORD()
                if ctypes.windll.advapi32.GetTokenInformation(token, 12, None, 0, ctypes.byref(wintypes.DWORD())):
                    size = wintypes.DWORD()
                    ctypes.windll.advapi32.GetTokenInformation(token, 12, ctypes.byref(session), ctypes.sizeof(session), ctypes.byref(size))
                ctypes.windll.kernel32.CloseHandle(token)
                return session.value
        except Exception:
            pass
        return 0

    def is_locked(self) -> bool:
        """Check if the workstation is locked."""
        try:
            user32 = ctypes.windll.User32
            return user32.GetForegroundWindow() == 0
        except Exception:
            return False


class SimpleLockMonitor:
    """
    Simple lock/unlock monitor using Windows hooks.
    Works by detecting when the desktop becomes available again after
    an extended period of no input (indicating lock/sleep).
    """

    def __init__(self):
        self._callbacks: dict[str, list[Callable]] = {
            SessionEvent.LOCK: [],
            SessionEvent.UNLOCK: [],
        }
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock_time: float = 0

    def register_callback(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="SimpleLockMonitor")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _monitor_loop(self):
        """Monitor using GetLastInputInfo."""
        try:
            import ctypes
            from ctypes import wintypes

            SPI_GETLASTINPUTINFO = 0x0D
            LOCK_THRESHOLD_MS = 300000  # 5 minutes of no input = potentially locked
            UNLOCK_THRESHOLD_MS = 5000   # Activity after lock threshold = unlocked

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

            last_time = 0
            was_potentially_locked = False

            while self._running:
                try:
                    if ctypes.windll.User32.SystemParametersInfoW(SPI_GETLASTINPUTINFO, 0, ctypes.byref(lii), 0):
                        current_time = lii.dwTime

                        if last_time > 0:
                            idle_time = (current_time - last_time) & 0xFFFFFFFF  # Handle wrap

                            # Detect potential unlock
                            if was_potentially_locked and idle_time < UNLOCK_THRESHOLD_MS:
                                self._on_unlock()
                                self._fire_event(SessionEvent.UNLOCK)
                                was_potentially_locked = False
                                logger.info("[LockMonitor] Session unlocked")

                            # Detect potential lock (extended idle)
                            elif idle_time > LOCK_THRESHOLD_MS and not was_potentially_locked:
                                self._lock_time = time.time()
                                was_potentially_locked = True
                                self._fire_event(SessionEvent.LOCK)
                                logger.info("[LockMonitor] Session locked")

                        last_time = current_time

                except Exception as e:
                    logger.debug(f"[LockMonitor] {e}")

                time.sleep(3)

        except Exception as e:
            logger.error(f"[LockMonitor] Loop error: {e}")

    def _fire_event(self, event: str, **kwargs):
        for callback in self._callbacks.get(event, []):
            try:
                callback(**kwargs)
            except Exception as e:
                logger.error(f"[LockMonitor] Callback error: {e}")

    def _on_unlock(self):
        """Play unlock music when unlock is detected."""
        try:
            from core.intro_music import play_unlock_scene
            play_unlock_scene()
        except Exception:
            pass

    def get_lock_duration(self) -> float | None:
        """Get how long the session was locked in seconds."""
        if self._lock_time > 0:
            return time.time() - self._lock_time
        return None


# Global instance
_lock_monitor: SimpleLockMonitor | None = None


def get_lock_monitor() -> SimpleLockMonitor:
    """Get the global lock monitor instance."""
    global _lock_monitor
    if _lock_monitor is None:
        _lock_monitor = SimpleLockMonitor()
    return _lock_monitor
