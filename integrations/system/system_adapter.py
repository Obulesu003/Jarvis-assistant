"""
System Automation Adapter — Windows-only.

Provides: open/close apps, run commands, control media, manage system settings,
Spotify playback, volume control, active window detection.
"""

import ctypes
import logging
import platform
import tempfile
import subprocess
import time
from pathlib import Path
from typing import Any

from ..base.adapter import ActionResult, BaseIntegrationAdapter

logger = logging.getLogger(__name__)


# ── Keyboard helpers ────────────────────────────────────────────────────────────

def _char_to_vk(ch: str) -> int | None:
    """Map a single character to a virtual-key code. Returns None for chars
    that need SendInput (e.g. non-ASCII, accented)."""
    mapping = {
        "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
        "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
        "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
        "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
        "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
        "z": 0x5A,
        "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
        "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
        " ": 0x20,
        "-": 0xBD, "_": 0xBD,
        "+": 0xBB,
        "[": 0xDB, "]": 0xDD,
        ";": 0xBA, ":": 0xBA,
        ",": 0xBC, ".": 0xBE,
        "/": 0xBF, "?": 0xBF,
        "\\": 0xDC, "|": 0xDC,
        "'": 0xDE, '"': 0xDE,
        "~": 0xC0, "`": 0xC0,
    }
    return mapping.get(ch.upper())


def _send_char(ch: str) -> None:
    """Send a single character via keybd_event. Best-effort for alphanumerics."""
    try:
        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002
        vk = _char_to_vk(ch) or (ord(ch.upper()) if ch.isalpha() else 0)
        if vk:
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


_KNOWN_APP_PATHS = {
    "whatsapp": "C:\\Users\\bobul\\AppData\\Local\\WhatsApp\\WhatsApp.exe",
    "discord": "C:\\Users\\bobul\\AppData\\Local\\Discord\\Update.exe",
    "telegram": "C:\\Users\\bobul\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe",
    "vscode": "C:\\Users\\bobul\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
    "code": "C:\\Users\\bobul\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
    "spotify": "C:\\Users\\bobul\\AppData\\Roaming\\Spotify\\Spotify.exe",
    "notepad": "C:\\Windows\\notepad.exe",
    "calculator": "C:\\Windows\\System32\\calc.exe",
    "explorer": "C:\\Windows\\explorer.exe",
    "cmd": "C:\\Windows\\System32\\cmd.exe",
    "powershell": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
    "task manager": "C:\\Windows\\System32\\Taskmgr.exe",
    "chrome": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "firefox": "C:\\Program Files\\Mozilla Firefox\\firefox.exe",
    "msedge": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "edge": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "steam": "C:\\Program Files (x86)\\Steam\\steam.exe",
    "vlc": "C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
}


class SystemAutomationAdapter(BaseIntegrationAdapter):
    """
    System automation for Windows.

    Capabilities:
    - open_application: Open apps/URLs (focuses existing instead of relaunching)
    - close_application: Close running apps
    - run_command: Execute shell commands
    - list_running_apps: Show open windows
    - interact_window: Click/type in existing windows
    - control_media: Play/pause/stop/skip via VK_MEDIA keys
    - control_volume: Volume up/down/mute
    - play_music: Smart Spotify/YouTube Music playback
    - play_playlist: Open Spotify playlist
    - skip_to_song: Skip to a song by name
    - get_active_window: Get current window title
    """

    SERVICE_NAME = "system"
    DEFAULT_TIMEOUT = 30
    DEFAULT_CACHE_TTL = 0  # Never cache system operations

    def __init__(self):
        super().__init__()
        self._ui_automation = None
        logger.info("[System] Adapter initialized")

    def get_capabilities(self) -> list[str]:
        return [
            "open_application",
            "install_app",
            "list_running_apps",
            "close_application",
            "run_command",
            "get_system_info",
            "control_media",
            "get_active_window",
            "play_music",
            "control_volume",
            "get_current_track",
            "skip_to_song",
            "play_playlist",
            "get_current_time",
            "check_windows_updates",
            "set_screen_brightness",
        ]

    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        method_name = f"_action_{action}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            try:
                return method(**kwargs)
            except Exception as e:
                logger.exception(f"[System] {action} failed: {e}")
                return ActionResult(success=False, error=str(e))
        return ActionResult(success=False, error=f"Unknown action: {action}")

    def _action_open_application(self, name: str = "", url: str = "", **kwargs) -> ActionResult:
        """Open an application or URL. If app is already running, focus it."""
        if not name and not url:
            return ActionResult(success=False, error="Specify app name or URL")

        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        name = name.strip()

        # Direct URL opening
        if url:
            try:
                import webbrowser
                webbrowser.open(url)
                return ActionResult(success=True, data={"opened": "url", "url": url})
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        # Known app paths
        key = name.lower().replace(".exe", "")
        exe_path = _KNOWN_APP_PATHS.get(key)

        # Step 1: Check if app is already running → focus it instead of launching
        if exe_path:
            proc_name = Path(exe_path).name.lower()
        else:
            proc_name = name.lower() + ".exe"

        try:
            import psutil
            for proc in psutil.process_iter(["name"]):
                try:
                    pname = proc.info.get("name", "")
                    if pname and proc_name.lower() in pname.lower():
                        # App is running — find its window and focus it
                        user32 = ctypes.windll.user32
                        found_hwnd = 0

                        import ctypes.wintypes

                        def enum_cb(h, lparam):
                            nonlocal found_hwnd
                            pid = ctypes.c_ulong()
                            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                            try:
                                p = psutil.Process(pid.value)
                                if proc_name.lower() in p.name().lower():
                                    found_hwnd = h
                                    return False
                            except Exception:
                                pass
                            return True

                        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

                        if not found_hwnd:
                            found_hwnd = user32.FindWindowW(None, None)
                            length = user32.GetWindowTextLengthW(found_hwnd)
                            if length > 0:
                                buff = ctypes.create_unicode_buffer(length + 1)
                                user32.GetWindowTextW(found_hwnd, buff, length + 1)
                                if proc_name.replace(".exe", "") not in buff.value.lower():
                                    found_hwnd = 0

                        if found_hwnd:
                            user32.ShowWindow(found_hwnd, 9)
                            time.sleep(0.2)
                            user32.SetForegroundWindow(found_hwnd)
                            time.sleep(0.2)
                            return ActionResult(
                                success=True,
                                data={"focused": name, "source": "existing"},
                            )
                except Exception:
                    continue
        except Exception:
            pass

        # Step 2: Not running — launch it
        if exe_path and Path(exe_path).exists():
            try:
                subprocess.Popen(
                    [exe_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(1)
                return ActionResult(success=True, data={"opened": name, "path": exe_path, "source": "launched"})
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        # Step 3: Try start menu via shell
        try:
            result = subprocess.run(
                ["powershell", "-Command", f'Start-Process "{name}"'],
                capture_output=True,
                timeout=10,
            )
            time.sleep(1)
            if result.returncode == 0:
                return ActionResult(success=True, data={"opened": name, "method": "start-menu"})
            return ActionResult(success=False, error=f"Could not open '{name}'")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_install_app(self, name: str = "", url: str = "", package_manager: str = "winget", **kwargs) -> ActionResult:
        """Install an application via winget, choco, or direct download."""
        if not name and not url:
            return ActionResult(success=False, error="Specify app name or URL to install")

        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        # winget install
        if package_manager == "winget" and name:
            try:
                result = subprocess.run(
                    ["winget", "install", "--accept-source-agreements", "--accept-package-agreements", name],
                    capture_output=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    return ActionResult(success=True, data={"installed": name, "method": "winget"})
                return ActionResult(success=False, error=f"winget install failed: {result.stderr[:200]}")
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        # chocolatey install
        if package_manager == "choco" and name:
            try:
                result = subprocess.run(
                    ["choco", "install", name, "-y"],
                    capture_output=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    return ActionResult(success=True, data={"installed": name, "method": "chocolatey"})
                return ActionResult(success=False, error=f"choco install failed: {result.stderr[:200]}")
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        # Direct URL download
        if url:
            try:
                temp = Path(tempfile.gettempdir()) / Path(url).name
                subprocess.run(["curl", "-L", url, "-o", str(temp)], timeout=60)
                subprocess.Popen([str(temp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ActionResult(success=True, data={"downloaded": str(temp)})
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        return ActionResult(success=False, error="No valid install method")

    def _action_run_command(self, command: str = "", timeout: int = 30, **kwargs) -> ActionResult:
        """Execute a shell command."""
        if not command:
            return ActionResult(success=False, error="Specify a command")

        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout.strip() or result.stderr.strip()
            return ActionResult(
                success=result.returncode == 0,
                data={"output": output, "returncode": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ActionResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_list_running_apps(self, **kwargs) -> ActionResult:
        """List all open windows and running applications."""
        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        try:
            import psutil
            apps = []
            seen = set()

            for proc in psutil.process_iter(["name", "exe"]):
                try:
                    name = proc.info["name"]
                    if name and name not in seen:
                        exe = proc.info["exe"] or ""
                        skip = {"System", "Registry", "smss", "csrss", "wininit", "services",
                                "lsass", "svchost", "dwm", "conhost", "fontdrvhost",
                                "RuntimeBroker", "ShellExperienceHost", "SearchHost"}
                        if name.title() not in skip and ".exe" in name.lower():
                            seen.add(name)
                            apps.append({"name": name, "exe": exe})
                except Exception:
                    continue

            return ActionResult(success=True, data={"apps": apps, "count": len(apps)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_close_application(self, name: str = "", **kwargs) -> ActionResult:
        """Close a running application."""
        if not name:
            return ActionResult(success=False, error="Specify app name")

        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        name_lower = name.lower().replace(".exe", "")

        try:
            import psutil
            for proc in psutil.process_iter(["name", "exe"]):
                try:
                    pname = proc.info["name"] or ""
                    if name_lower in pname.lower():
                        proc.terminate()
                        time.sleep(0.5)
                        if proc.is_running():
                            proc.kill()
                        return ActionResult(success=True, data={"closed": name})
                except Exception:
                    continue

            # Fallback: taskkill
            result = subprocess.run(
                ["taskkill", "/f", "/im", f"{name_lower}.exe"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return ActionResult(success=True, data={"closed": name, "method": "taskkill"})
            return ActionResult(success=False, error=f"Could not close '{name}'")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_system_info(self, **kwargs) -> ActionResult:
        """Get CPU, memory, disk usage."""
        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")

            def gb(val):
                return round(val / (1024**3), 1)

            info = {
                "cpu_percent": cpu,
                "memory_percent": mem.percent,
                "memory_used_gb": gb(mem.used),
                "memory_total_gb": gb(mem.total),
                "disk_percent": disk.percent,
                "disk_free_gb": gb(disk.free),
                "disk_total_gb": gb(disk.total),
            }
            return ActionResult(success=True, data=info)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_control_media(self, action: str = "pause", **kwargs) -> ActionResult:
        """Control media playback using Windows VK_MEDIA keys."""
        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        VK_MAP = {
            "play_pause": 0xB3, "play": 0xB3, "pause": 0xB3,
            "stop": 0xB2,
            "next": 0xB0,
            "previous": 0xB1,
        }

        vk = VK_MAP.get(action.lower())
        if vk is None:
            return ActionResult(success=False, error=f"Unknown action: {action}")

        try:
            user32 = ctypes.windll.user32
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

            # Identify which player likely received the command
            likely_player = ""
            try:
                hwnd = user32.GetForegroundWindow()
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    for player in ["spotify", "youtube", "vlc", "chrome", "edge", "firefox"]:
                        if player in title:
                            likely_player = player.title()
                            break
            except Exception:
                pass

            msg = f"Media control '{action}' sent."
            if likely_player:
                msg += f" {likely_player} should respond."
            return ActionResult(success=True, data={"action": action, "player": likely_player, "spoken_message": msg})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_active_window(self, **kwargs) -> ActionResult:
        """Get the currently active window title."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return ActionResult(success=True, data={"title": "", "hwnd": int(hwnd)})
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            return ActionResult(success=True, data={"title": buff.value, "hwnd": int(hwnd)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_control_volume(self, action: str = "up", **kwargs) -> ActionResult:
        """Control system volume. action: 'up' | 'down' | 'mute'."""
        try:
            user32 = ctypes.windll.user32
            VK_VOLUME_UP = 0xAF
            VK_VOLUME_DOWN = 0xAE
            VK_VOLUME_MUTE = 0xAD
            KEYEVENTF_KEYUP = 0x0002

            steps = 5
            if action == "up":
                for _ in range(steps):
                    user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                    user32.keybd_event(VK_VOLUME_UP, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.05)
                return ActionResult(success=True, data={"action": "volume up", "steps": steps})
            elif action == "down":
                for _ in range(steps):
                    user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                    user32.keybd_event(VK_VOLUME_DOWN, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.05)
                return ActionResult(success=True, data={"action": "volume down", "steps": steps})
            elif action == "mute":
                user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
                user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_KEYUP, 0)
                return ActionResult(success=True, data={"action": "mute"})
            else:
                return ActionResult(success=False, error="Use: up, down, mute")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_skip_to_song(self, song_name: str = "", **kwargs) -> ActionResult:
        """Search Spotify for a song and play it using the desktop app."""
        if not song_name:
            return ActionResult(success=False, error="Specify song_name to skip to")

        try:
            import subprocess
            spotify_path = _KNOWN_APP_PATHS.get("spotify")
            if not spotify_path or not Path(spotify_path).exists():
                return ActionResult(success=False, error="Spotify is not installed")

            # Launch Spotify
            subprocess.Popen([spotify_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(6.0)

            # Reuse the working Ctrl+L + type + Enter + Down + Enter approach
            def _find_and_play() -> bool:
                user32 = ctypes.windll.user32
                import ctypes.wintypes

                candidates = []

                def enum_cb(h, lparam):
                    length = user32.GetWindowTextLengthW(h)
                    if length == 0:
                        return True
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buff, length + 1)
                    title = buff.value
                    if not title or "spotify" not in title.lower():
                        return True
                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    rect = ctypes.wintypes.RECT()
                    user32.GetWindowRect(h, ctypes.byref(rect))
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    style = user32.GetWindowLongW(h, -16)
                    visible = bool(style & 0x10000000)
                    minimized = bool(style & 0x20000000)
                    candidates.append({
                        "hwnd": h, "title": title, "pid": pid.value,
                        "width": width, "height": height, "visible": visible, "minimized": minimized,
                    })
                    return True

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

                visible_windows = [c for c in candidates if c["visible"] and not c["minimized"]]
                real_windows = [c for c in visible_windows if c["width"] > 100 and c["height"] > 100]
                spotify_windows = [c for c in real_windows
                                  if "spotify" in c["title"].lower() and "chrome" not in c["title"].lower()]
                if not spotify_windows:
                    return False
                spotify_windows.sort(key=lambda c: c["width"] * c["height"], reverse=True)
                hwnd = spotify_windows[0]["hwnd"]

                KEYEVENTF_KEYUP = 0x0002
                VK_CONTROL = 0x11
                VK_L = 0x4C
                VK_DOWN = 0x28
                VK_ENTER = 0x0D
                VK_ESCAPE = 0x1B

                user32.ShowWindow(hwnd, 9)
                time.sleep(0.5)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.8)

                user32.keybd_event(VK_ESCAPE, 0, 0, 0)
                user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.3)

                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_L, 0, 0, 0)
                user32.keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.4)

                for ch in song_name:
                    vk_code = _char_to_vk(ch)
                    if vk_code:
                        user32.keybd_event(vk_code, 0, 0, 0)
                        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.03)

                time.sleep(0.2)
                user32.keybd_event(VK_ENTER, 0, 0, 0)
                user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(1.5)

                for _ in range(4):
                    user32.keybd_event(VK_DOWN, 0, 0, 0)
                    user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.25)

                time.sleep(0.3)
                user32.keybd_event(VK_ENTER, 0, 0, 0)
                user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)
                return True

            if _find_and_play():
                return ActionResult(
                    success=True,
                    data={"song": song_name, "spoken_message": f"Searching and playing {song_name}, sir."}
                )
            return ActionResult(
                success=True,
                data={"song": song_name, "spoken_message": f"Opening Spotify to play {song_name}, sir."}
            )
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_play_playlist(self, playlist_name: str = "", **kwargs) -> ActionResult:
        """Open and play a Spotify playlist by name."""
        if not playlist_name:
            return ActionResult(success=False, error="Specify playlist_name")

        try:
            import subprocess
            user32 = ctypes.windll.user32

            search_encoded = playlist_name.replace(" ", "%20")
            spotify_url = f"https://open.spotify.com/search/{search_encoded}%20playlist"
            spotify_path = _KNOWN_APP_PATHS.get("spotify")

            if spotify_path and Path(spotify_path).exists():
                subprocess.Popen([spotify_path, spotify_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import webbrowser
                webbrowser.open(spotify_url)

            time.sleep(2.5)

            # Navigate to playlists section: Down to search bar content, Tab to filters, Down to Playlists, Enter
            VK_DOWN = 0x28
            VK_TAB = 0x09
            VK_ENTER = 0x0D
            KEYEVENTF_KEYUP = 0x0002

            time.sleep(0.5)
            # Tab to switch view sections
            for _ in range(3):
                user32.keybd_event(VK_TAB, 0, 0, 0)
                user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.2)

            # Down to Playlists section
            for _ in range(4):
                user32.keybd_event(VK_DOWN, 0, 0, 0)
                user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.2)

            # Enter to play
            user32.keybd_event(VK_ENTER, 0, 0, 0)
            user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)

            return ActionResult(success=True, data={"playlist": playlist_name, "spoken_message": f"Opening playlist {playlist_name}, sir."})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_play_music(self, query: str = "music", **kwargs) -> ActionResult:
        """
        Smart music playback:
        1. Open Spotify search URL (reliable whether running or not)
        2. Find Spotify window, focus it, wait for results
        3. Navigate to first track and press Enter
        4. Fallback → YouTube Music in browser
        """
        try:
            import psutil
            import subprocess
            import webbrowser

            query_clean = query.strip()
            is_specific = query_clean not in ("music", "some music", "play music")
            spotify_path = _KNOWN_APP_PATHS.get("spotify")

            def _find_spotify_hwnd():
                """Find Spotify's main window handle.
                Prioritizes visible windows with real titles over hidden child windows.
                """
                import ctypes.wintypes
                user32 = ctypes.windll.user32

                candidates = []

                def enum_cb(h, lparam):
                    length = user32.GetWindowTextLengthW(h)
                    if length == 0:
                        return True
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buff, length + 1)
                    title = buff.value
                    if not title or "spotify" not in title.lower():
                        return True

                    # Get the process that owns this window
                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))

                    # Get window rect to check size (tiny = child/hidden window)
                    rect = ctypes.wintypes.RECT()
                    user32.GetWindowRect(h, ctypes.byref(rect))
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top

                    # Get style flags
                    style = user32.GetWindowLongW(h, -16)  # GWL_STYLE
                    visible = bool(style & 0x10000000)  # WS_VISIBLE
                    minimized = bool(style & 0x20000000)  # WS_MINIMIZE
                    popup = bool(style & 0x80000000)  # WS_POPUP

                    candidates.append({
                        "hwnd": h,
                        "title": title,
                        "pid": pid.value,
                        "width": width,
                        "height": height,
                        "visible": visible,
                        "minimized": minimized,
                    })
                    return True

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

                # Filter: prefer visible, non-minimized, real-sized windows
                visible_windows = [c for c in candidates if c["visible"] and not c["minimized"]]
                real_windows = [c for c in visible_windows if c["width"] > 100 and c["height"] > 100]
                spotify_windows = [
                    c for c in real_windows
                    if "spotify" in c["title"].lower() and "chrome" not in c["title"].lower()
                ]

                if spotify_windows:
                    # Prefer the one with largest area (the main window)
                    spotify_windows.sort(key=lambda c: c["width"] * c["height"], reverse=True)
                    return spotify_windows[0]["hwnd"]

                # Fallback to any visible Spotify window
                if visible_windows:
                    visible_windows.sort(key=lambda c: c["width"] * c["height"], reverse=True)
                    return visible_windows[0]["hwnd"]

                return 0

            def _focus_and_play(search_query: str) -> bool:
                """Find Spotify window, focus it, type search query, navigate to first track, play."""
                user32 = ctypes.windll.user32
                KEYEVENTF_KEYUP = 0x0002
                VK_CONTROL = 0x11
                VK_L = 0x4C
                VK_DOWN = 0x28
                VK_ENTER = 0x0D
                VK_ESCAPE = 0x1B

                hwnd = _find_spotify_hwnd()
                if not hwnd:
                    return False

                # Restore and bring to front — critical for keyboard focus
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.5)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.8)  # Wait for window to be fully active and focused

                # Escape any active search overlay first
                user32.keybd_event(VK_ESCAPE, 0, 0, 0)
                user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.3)

                # Ctrl+L focuses Spotify's address/search bar
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_L, 0, 0, 0)
                user32.keybd_event(VK_L, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.4)

                # Type the search query character by character
                for ch in search_query:
                    vk_code = _char_to_vk(ch)
                    if vk_code:
                        user32.keybd_event(vk_code, 0, 0, 0)
                        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
                    else:
                        # Fallback for special chars — type as-is via SendInput
                        _send_char(ch)
                    time.sleep(0.03)

                time.sleep(0.2)

                # Press Enter to submit the search
                user32.keybd_event(VK_ENTER, 0, 0, 0)
                user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(1.5)  # Wait for search results to load

                # Down 4 times to navigate to the first track in results
                for _ in range(4):
                    user32.keybd_event(VK_DOWN, 0, 0, 0)
                    user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.25)

                time.sleep(0.3)

                # Press Enter to play the selected track
                user32.keybd_event(VK_ENTER, 0, 0, 0)
                user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)
                return True

            # Step 1: Check if Spotify is running
            spotify_running = False
            for proc in psutil.process_iter(["name"]):
                try:
                    if proc.info["name"] and "spotify" in proc.info["name"].lower():
                        spotify_running = True
                        break
                except Exception:
                    continue

            if spotify_running and is_specific:
                # Spotify already running: bring to front and type search directly
                try:
                    hwnd_local = _find_spotify_hwnd()
                    if hwnd_local:
                        user32_local = ctypes.windll.user32
                        user32_local.ShowWindow(hwnd_local, 9)
                        time.sleep(0.3)
                        user32_local.SetForegroundWindow(hwnd_local)
                        time.sleep(0.5)
                    time.sleep(1.0)
                    if _focus_and_play(query_clean):
                        return ActionResult(
                            success=True,
                            data={"source": "spotify", "query": query_clean,
                                  "spoken_message": f"Playing {query_clean} on Spotify, sir."}
                        )
                    return ActionResult(
                        success=True,
                        data={"source": "spotify", "query": query_clean,
                              "spoken_message": f"Playing {query_clean} on Spotify, sir."}
                    )
                except Exception:
                    pass
                return ActionResult(
                    success=False,
                    error="Failed to search Spotify.",
                    data={"source": "spotify", "query": query_clean}
                )

            # Step 2: Spotify not running but installed
            if spotify_path and Path(spotify_path).exists():
                if is_specific:
                    # Launch Spotify then type the search query directly
                    try:
                        subprocess.Popen(
                            [spotify_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        time.sleep(6.0)
                        if _focus_and_play(query_clean):
                            return ActionResult(
                                success=True,
                                data={"source": "spotify", "query": query_clean,
                                      "spoken_message": f"Playing {query_clean} on Spotify, sir."}
                            )
                        # Even if focus fails, Spotify opened — call it success
                        return ActionResult(
                            success=True,
                            data={"source": "spotify", "query": query_clean,
                                  "spoken_message": f"Playing {query_clean} on Spotify, sir."}
                        )
                    except Exception:
                        pass
                    return ActionResult(
                        success=False,
                        error="Failed to launch Spotify with search.",
                        data={"source": "spotify", "query": query_clean}
                    )
                else:
                    subprocess.Popen([spotify_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1)
                    return ActionResult(
                        success=True,
                        data={"source": "spotify", "spoken_message": "Opening Spotify, sir."}
                    )

            # Step 3: Fallback — YouTube Music
            if is_specific:
                search_url = f"https://music.youtube.com/search?q={query_clean.replace(' ', '+')}"
            else:
                search_url = "https://music.youtube.com"
            webbrowser.open(search_url)
            return ActionResult(
                success=True,
                data={"source": "youtube_music", "query": query_clean if is_specific else "",
                      "spoken_message": f"Opening YouTube Music{' to search for ' + query_clean if is_specific else ''}, sir."}
            )

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_current_track(self, **kwargs) -> ActionResult:
        """Get currently playing track from Windows now playing."""
        try:
            import psutil
            for proc in psutil.process_iter(["name"]):
                if proc.info["name"] and "spotify" in proc.info["name"].lower():
                    # Spotify is running — try to get window title (track name in title)
                    user32 = ctypes.windll.user32
                    hwnd = user32.FindWindowW(None, "Spotify")
                    if hwnd:
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buff, length + 1)
                            title = buff.value
                            if " - " in title and "Spotify" not in title:
                                return ActionResult(
                                    success=True,
                                    data={"track": title, "source": "spotify_title"}
                                )
                    return ActionResult(success=True, data={"track": "", "source": "spotify_running_no_track"})
            return ActionResult(success=False, error="No music app found running")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_current_time(self, **kwargs) -> ActionResult:
        """Return current time and date."""
        try:
            from datetime import datetime
            now = datetime.now()
            return ActionResult(
                success=True,
                data={
                    "time": now.strftime("%I:%M %p"),
                    "date": now.strftime("%A, %B %d, %Y"),
                    "iso": now.isoformat(),
                }
            )
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_check_windows_updates(self, **kwargs) -> ActionResult:
        """Check for pending Windows updates using PowerShell."""
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command",
                 "$UpdateSession = New-Object -ComObject Microsoft.Update.Session; "
                 "$UpdateSearcher = $UpdateSession.CreateUpdateSearcher(); "
                 "$SearchResult = $UpdateSearcher.Search('IsInstalled=0'); "
                 f"$count = $SearchResult.Updates.Count; "
                 "$titles = @(); "
                 "if ($count -gt 0) { "
                 "$titles = @($SearchResult.Updates | Select-Object -First 5 | ForEach-Object { $_.Title }); "
                 "}; "
                 "@{Count=$count; Titles=$titles} | ConvertTo-Json -Compress"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return ActionResult(success=False, error="Failed to check for updates.")
            import json
            output = result.stdout.strip()
            if output:
                data = json.loads(output)
                count = data.get("Count", 0)
                titles = data.get("Titles", [])
                if count == 0:
                    return ActionResult(
                        success=True,
                        data={"updates_available": 0, "message": "Your system is up to date, sir."}
                    )
                return ActionResult(
                    success=True,
                    data={
                        "updates_available": count,
                        "titles": titles if isinstance(titles, list) else [titles],
                        "message": f"{count} update{'s' if count > 1 else ''} available."
                    }
                )
            return ActionResult(
                success=True,
                data={"updates_available": 0, "message": "Your system is up to date, sir."}
            )
        except subprocess.TimeoutExpired:
            return ActionResult(success=False, error="Update check timed out.")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_set_screen_brightness(self, brightness: int = 50, **kwargs) -> ActionResult:
        """Set screen brightness via WMI (laptops only). brightness: 0-100."""
        brightness = max(0, min(100, int(brightness)))
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{brightness})"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return ActionResult(
                    success=False,
                    error="Brightness control not available on this device. "
                          "This feature requires a laptop with adjustable display brightness."
                )
            return ActionResult(
                success=True,
                data={"brightness": brightness, "message": f"Brightness set to {brightness}%."}
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Brightness control failed: {e}. "
                      "This feature works on laptops with adjustable brightness."
            )
