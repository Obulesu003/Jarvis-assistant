"""
System automation adapter for native Windows application control.
Uses pywinauto for window automation and subprocess for app management.
"""

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
