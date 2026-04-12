"""
System automation adapter for native Windows application control.
Uses pywinauto for window automation and subprocess for app management.
"""

import ctypes
import logging
import platform
import subprocess
import time
from pathlib import Path

from ..base.adapter import ActionResult, BaseIntegrationAdapter

logger = logging.getLogger(__name__)


# Known app paths for fast launch (user-specific)
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
    Native Windows system automation.

    Capabilities:
    - open_application: Launch installed apps
    - install_app: Download and install via winget/choco
    - list_running_apps: Show open windows
    - interact_window: Click/type in existing windows
    - close_application: Close running apps
    - run_command: Execute shell commands
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
        """Open an application or URL."""
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
        if exe_path and Path(exe_path).exists():
            try:
                subprocess.Popen(
                    [exe_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(1)
                return ActionResult(success=True, data={"opened": name, "path": exe_path})
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        # Try start menu via shell
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
                    ["winget", "install", "--id", name, "--silent", "--accept-package-agreements", "--accept-source-agreements"],
                    capture_output=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    return ActionResult(success=True, data={"installed": name, "method": "winget"})
                return ActionResult(
                    success=False,
                    error=f"winget install failed for '{name}': {result.stderr.decode(errors='replace')[:200]}",
                )
            except FileNotFoundError:
                return ActionResult(success=False, error="winget not found. Install Windows Package Manager or use --method=choco")
            except subprocess.TimeoutExpired:
                return ActionResult(success=False, error=f"winget install timed out for '{name}'")
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
                return ActionResult(success=False, error=f"choco install failed: {result.stderr.decode(errors='replace')[:200]}")
            except FileNotFoundError:
                return ActionResult(success=False, error="chocolatey not installed. Install from chocolatey.org")
            except subprocess.TimeoutExpired:
                return ActionResult(success=False, error="choco install timed out")
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        # Direct URL download
        if url:
            try:
                temp = Path.home() / "Downloads"
                temp.mkdir(exist_ok=True)
                filename = name.replace(" ", "_") + ".exe" if name else "installer.exe"
                dest = temp / filename

                import urllib.request
                logger.info(f"[System] Downloading from {url}")
                urllib.request.urlretrieve(url, dest)
                return ActionResult(
                    success=True,
                    data={"downloaded": str(dest), "action": "Run the downloaded file to install"}
                )
            except Exception as e:
                return ActionResult(success=False, error=f"Download failed: {e}")

        return ActionResult(success=False, error="No install method specified")

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
                        # Filter out system processes
                        skip = {"System", "Registry", "smss", "csrss", "wininit", "services",
                                "lsass", "svchost", "dwm", "conhost", "fontdrvhost",
                                "RuntimeBroker", "ShellExperienceHost", "SearchHost"}
                        if name.title() not in skip and ".exe" in name.lower():
                            seen.add(name)
                            apps.append({"name": name, "exe": exe})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            apps.sort(key=lambda x: x["name"].lower())
            return ActionResult(success=True, data={"apps": apps, "count": len(apps)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_close_application(self, name: str = "", force: bool = False, **kwargs) -> ActionResult:
        """Close a running application."""
        if not name:
            return ActionResult(success=False, error="Specify app name to close")

        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        try:
            import psutil
            killed = []
            name_lower = name.lower()

            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    pname = proc.info["name"] or ""
                    if name_lower in pname.lower():
                        p = psutil.Process(proc.info["pid"])
                        if force:
                            p.kill()
                        else:
                            p.terminate()
                        killed.append(pname)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if killed:
                return ActionResult(success=True, data={"closed": list(set(killed))})
            return ActionResult(success=False, error=f"No running process found matching '{name}'")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_run_command(self, command: str = "", wait: bool = True, timeout: int = 60, **kwargs) -> ActionResult:
        """Run a shell command."""
        if not command:
            return ActionResult(success=False, error="Specify a command to run")

        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=timeout,
            )
            output = result.stdout.decode(errors="replace")
            errors = result.stderr.decode(errors="replace")
            return ActionResult(
                success=(result.returncode == 0),
                data={
                    "returncode": result.returncode,
                    "stdout": output[:5000],
                    "stderr": errors[:1000],
                }
            )
        except subprocess.TimeoutExpired:
            return ActionResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_system_info(self, **kwargs) -> ActionResult:
        """Get basic system information."""
        try:
            import psutil

            def bytes_to_gb(b):
                return round(b / (1024**3), 1)

            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")

            info = {
                "cpu_percent": cpu,
                "memory_total_gb": bytes_to_gb(mem.total),
                "memory_used_gb": bytes_to_gb(mem.used),
                "memory_percent": mem.percent,
                "disk_total_gb": bytes_to_gb(disk.total),
                "disk_used_gb": bytes_to_gb(disk.used),
                "disk_percent": disk.percent,
            }

            return ActionResult(success=True, data=info)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_active_window(self, **kwargs) -> ActionResult:
        """Get the currently active window title."""
        try:
            import ctypes
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

            action = action.lower().strip()
            if action == "mute":
                vk, msg = VK_VOLUME_MUTE, "Toggling mute"
            elif action in ("up", "increase", "louder"):
                vk, msg = VK_VOLUME_UP, "Increasing volume"
            elif action in ("down", "decrease", "quieter"):
                vk, msg = VK_VOLUME_DOWN, "Decreasing volume"
            else:
                vk, msg = VK_VOLUME_UP, "Adjusting volume"

            # Press key 3 times for noticeable change
            for _ in range(3):
                user32.keybd_event(vk, 0, 0, 0)
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.05)

            return ActionResult(success=True, data={"action": action, "spoken_message": f"{msg}, sir."})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_current_track(self, **kwargs) -> ActionResult:
        """Get the currently playing track from Spotify window title."""
        try:
            user32 = ctypes.windll.user32

            # Find Spotify window
            spotify_hwnd = user32.FindWindowW(None, "Spotify")
            if not spotify_hwnd:
                # Try to find by partial title
                def enum_windows_callback(hwnd, windows):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        if "spotify" in buff.value.lower():
                            windows.append(hwnd)
                    return True

                windows = []
                try:
                    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
                    user32.EnumWindows(EnumWindowsProc(enum_windows_callback), ctypes.byref(windows))
                    if windows:
                        spotify_hwnd = windows[0]
                except Exception:
                    pass

            if not spotify_hwnd:
                return ActionResult(success=False, error="Spotify is not running")

            # Get window title
            length = user32.GetWindowTextLengthW(spotify_hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(spotify_hwnd, buff, length + 1)
            title = buff.value

            # Parse "Spotify - Track Name - Artist" format
            if " - " in title and "Spotify" in title:
                parts = title.split(" - ", 2)
                track = parts[1] if len(parts) > 1 else parts[0]
                artist = parts[2] if len(parts) > 2 else ""
                return ActionResult(
                    success=True,
                    data={
                        "track": track,
                        "artist": artist,
                        "window_title": title,
                        "spoken_message": f"Now playing: {track} by {artist}" if artist else f"Now playing: {track}",
                    }
                )
            elif title.lower() == "spotify":
                return ActionResult(success=True, data={"track": "", "state": "not playing", "spoken_message": "Spotify is open but nothing is playing, sir."})
            else:
                return ActionResult(success=True, data={"window_title": title, "spoken_message": f"Active window: {title}"})

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_skip_to_song(self, song_name: str = "", **kwargs) -> ActionResult:
        """Skip to a specific song in the current Spotify playlist."""
        if not song_name:
            return ActionResult(success=False, error="Specify song_name to skip to")

        try:
            import subprocess
            user32 = ctypes.windll.user32

            # Open Spotify search with the song name
            search_encoded = song_name.replace(" ", "%20")
            spotify_url = f"https://open.spotify.com/search/{search_encoded}"
            spotify_path = _KNOWN_APP_PATHS.get("spotify")

            if spotify_path and Path(spotify_path).exists():
                subprocess.Popen([spotify_path, spotify_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import webbrowser
                webbrowser.open(spotify_url)

            time.sleep(2.5)

            # Press Down arrow to highlight first result, then Enter
            VK_DOWN = 0x28
            VK_ENTER = 0x0D
            KEYEVENTF_KEYUP = 0x0002

            # Press down once to be on first track (search highlights search bar)
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            # Press down 2 more times to get to tracks section
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            # Enter to play
            user32.keybd_event(VK_ENTER, 0, 0, 0)
            user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)

            return ActionResult(success=True, data={"song": song_name, "spoken_message": f"Searching and playing {song_name}, sir."})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_play_playlist(self, playlist_name: str = "", **kwargs) -> ActionResult:
        """Open and play a Spotify playlist by name."""
        if not playlist_name:
            return ActionResult(success=False, error="Specify playlist_name")

        try:
            import subprocess
            user32 = ctypes.windll.user32

            # Search for the playlist on Spotify
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

            # Down to Playlists
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            # Enter to open first playlist result
            user32.keybd_event(VK_ENTER, 0, 0, 0)
            user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(1.5)
            # Enter again to play
            user32.keybd_event(VK_ENTER, 0, 0, 0)
            user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)

            return ActionResult(success=True, data={"playlist": playlist_name, "spoken_message": f"Opening playlist {playlist_name}, sir."})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _send_enter_to_spotify(self) -> None:
        """Press Enter in Spotify to confirm first search result and start playback."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # Wait for Spotify window to be active
            time.sleep(0.5)
            # Enter key
            user32.keybd_event(0x0D, 0, 0, 0)       # key down
            user32.keybd_event(0x0D, 0, 0x0002, 0)  # key up
        except Exception:
            pass

    def _action_control_media(self, action: str = "pause", **kwargs) -> ActionResult:
        """
        Control media playback using Windows VK_MEDIA keys.
        action: 'play_pause' | 'stop' | 'next' | 'previous'
        """
        if platform.system() != "Windows":
            return ActionResult(success=False, error="Only supported on Windows")

        # Map action to Windows virtual key
        VK_MAP = {
            "play_pause": 0xB3,  # VK_MEDIA_PLAY_PAUSE
            "play": 0xB3,
            "pause": 0xB3,
            "stop": 0xB2,        # VK_MEDIA_STOP
            "next": 0xB0,        # VK_MEDIA_NEXT_TRACK
            "previous": 0xB1,     # VK_MEDIA_PREV_TRACK
        }

        vk = VK_MAP.get(action.lower())
        if vk is None:
            return ActionResult(success=False, error=f"Unknown media action: {action}. Use: play_pause, stop, next, previous")

        try:
            import ctypes
            KEYEVENTF_KEYUP = 0x0002
            user32 = ctypes.windll.user32

            # Press and release the key
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

            # Identify what likely received the command
            likely_player = ""
            try:
                hwnd = user32.GetForegroundWindow()
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    if "spotify" in title:
                        likely_player = "Spotify"
                    elif "youtube" in title:
                        likely_player = "YouTube"
                    elif "vlc" in title:
                        likely_player = "VLC"
                    elif "chrome" in title:
                        likely_player = "Chrome"
                    elif "edge" in title:
                        likely_player = "Edge"
                    elif "firefox" in title:
                        likely_player = "Firefox"
            except Exception:
                pass

            msg = f"Media control '{action}' sent."
            if likely_player:
                msg += f" {likely_player} should respond."
            return ActionResult(success=True, data={"action": action, "player": likely_player, "spoken_message": msg})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_play_music(self, query: str = "music", **kwargs) -> ActionResult:
        """
        Smart music playback. Checks what's available and plays:
        1. If Spotify is running → open search in Spotify app directly
        2. If Spotify is installed → open Spotify with search URL
        3. Fallback → open YouTube Music in browser with search
        """
        try:
            import psutil
            import subprocess
            import webbrowser
            import ctypes

            query_clean = query.strip()
            is_specific = query_clean not in ("music", "some music", "play music")
            search_encoded = query_clean.replace(" ", "%20")

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
                # Open Spotify search directly via spotify: URI
                # This brings Spotify to foreground with the search pre-filled
                spotify_search_uri = f"spotify:search:{query_clean}"
                try:
                    subprocess.Popen(
                        ["powershell", "-Command", f'Start-Process "{spotify_search_uri}"'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    time.sleep(2)
                    # Press Enter to play the first search result
                    self._send_enter_to_spotify()
                    return ActionResult(
                        success=True,
                        data={"source": "spotify_search", "query": query_clean, "spoken_message": f"Playing {query_clean} on Spotify, sir."}
                    )
                except Exception:
                    pass

            # Step 2: Check if Spotify is installed
            spotify_path = _KNOWN_APP_PATHS.get("spotify")
            if spotify_path and Path(spotify_path).exists():
                if is_specific:
                    # Use Spotify search URL — opens Spotify app directly to search page
                    spotify_url = f"https://open.spotify.com/search/{search_encoded}"
                    try:
                        subprocess.Popen(
                            [spotify_path, spotify_url],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        time.sleep(2)
                        # Press Enter to play the first search result
                        self._send_enter_to_spotify()
                        return ActionResult(
                            success=True,
                            data={"source": "spotify", "query": query_clean, "spoken_message": f"Playing {query_clean} on Spotify, sir."}
                        )
                    except Exception:
                        pass
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
                data={"source": "youtube_music", "query": query_clean if is_specific else "", "spoken_message": f"Opening YouTube Music{f' to search for {query_clean}' if is_specific else ''}, sir."}
            )

        except Exception as e:
            return ActionResult(success=False, error=str(e))
