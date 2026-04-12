"""
Windows Desktop App Automation via pywinauto.
Controls any running Windows application by finding and interacting with UI elements.
Works for Teams, Excel, Notepad, Calculator, File Explorer, and more.
"""

import logging
import os
import time

from pathlib import Path

from ..base.adapter import ActionResult, BaseIntegrationAdapter

logger = logging.getLogger(__name__)


# App-specific window titles and element patterns
_APP_PATTERNS = {
    "teams": {
        "window_title_contains": ["Microsoft Teams", "Teams"],
        "exe": "Teams.exe",
        "chat_list": {"type": "list", "search": "Chat"},
        "new_chat": {"type": "button", "text": "New chat"},
        "search": {"type": "edit", "text": "Search"},
        "message_box": {"type": "edit", "index": -1},
        "send": {"type": "button", "text_contains": "Send"},
        "meet_now": {"type": "button", "text_contains": "Meet now"},
    },
    "excel": {
        "window_title_contains": ["Excel", ".xlsx"],
        "exe": "EXCEL.EXE",
        "cell": {"type": "edit", "class_name": "Edit"},
        "formula_bar": {"type": "edit", "text": "Formula Bar"},
        "save": {"type": "menu_item", "text": "Save"},
    },
    "word": {
        "window_title_contains": ["Word", ".docx"],
        "exe": "WINWORD.EXE",
        "document_area": {"type": "pane", "class_name": "OpusApp"},
        "save": {"type": "menu_item", "text": "Save"},
    },
    "notepad": {
        "window_title_contains": ["Notepad"],
        "exe": "notepad.exe",
        "editor": {"type": "edit", "class_name": "Edit"},
    },
    "calculator": {
        "window_title_contains": ["Calculator"],
        "exe": "Calculator.exe",
        "result": {"type": "static", "text_contains": "Display"},
    },
    "file explorer": {
        "window_title_contains": ["File Explorer", "This PC"],
        "exe": "explorer.exe",
        "address_bar": {"type": "edit", "class_name": "Address Band Root"},
        "search": {"type": "edit", "text_contains": "Search"},
    },
}


class WindowsAppAdapter(BaseIntegrationAdapter):
    """
    Universal Windows desktop app automation.

    Connects to any running app and performs UI operations:
    - Click buttons
    - Type text into fields
    - Read text from UI elements
    - Read window content
    - Launch apps
    - Read Teams messages, send Teams messages
    - Excel cell operations
    - Any app that has standard Windows UI
    """

    SERVICE_NAME = "windows_app"
    DEFAULT_TIMEOUT = 30
    DEFAULT_CACHE_TTL = 0  # Never cache UI operations

    def __init__(self):
        super().__init__()
        self._apps: dict[str, any] = {}  # app_name -> pywinauto app
        logger.info("[Windows App] Adapter initialized")

    def get_capabilities(self) -> list[str]:
        return [
            "connect_app",
            "launch_app",
            "click_button",
            "type_text",
            "read_text",
            "read_window_content",
            "teams_send_message",
            "teams_join_meeting",
            "join_teams_meeting",
            "get_teams_meetings",
            "read_teams_messages",
            "notepad_read",
            "notepad_write",
            "explorer_navigate",
            "list_open_windows",
            "read_clipboard",
            "write_clipboard",
        ]

    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        method_name = f"_action_{action}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            try:
                return method(**kwargs)
            except Exception as e:
                logger.exception(f"[Windows App] {action} failed: {e}")
                return ActionResult(success=False, error=str(e))
        return ActionResult(success=False, error=f"Unknown action: {action}")

    # ------------------------------------------------------------------ #
    # Connection helpers                                                  #
    # ------------------------------------------------------------------ #

    def _connect_to_app(self, app_name: str = "", window_title: str = "") -> any | None:
        """Connect to a running app by name or window title."""
        # Check if already connected
        if app_name and app_name in self._apps:
            try:
                # Verify the app is still running
                self._apps[app_name].window(visible=True)
                return self._apps[app_name]
            except Exception:
                # App window not found, remove from cache
                self._apps.pop(app_name, None)

        try:
            import pywinauto

            if app_name:
                pattern = _APP_PATTERNS.get(app_name.lower())
                if pattern:
                    titles = pattern.get("window_title_contains", [])
                    for title in titles:
                        try:
                            app = pywinauto.Application(backend="win32").connect(
                                title_re=f".*{title}.*",
                                timeout=5,
                            )
                            self._apps[app_name] = app
                            logger.info(f"[Windows App] Connected to {app_name}")
                            return app
                        except Exception:
                            continue
                    # Try process name
                    exe = pattern.get("exe", "")
                    try:
                        app = pywinauto.Application(backend="win32").connect(
                            process=pywinauto.findwindows.find_window(title_re=f".*{titles[0]}.*")
                        )
                        self._apps[app_name] = app
                        return app
                    except Exception:
                        pass

            if window_title:
                try:
                    app = pywinauto.Application(backend="win32").connect(
                        title_re=f".*{window_title}.*",
                        timeout=5,
                    )
                    self._apps[window_title] = app
                    return app
                except Exception:
                    pass

            logger.warning(f"[Windows App] Could not connect to '{app_name or window_title}'")
            return None
        except Exception as e:
            logger.warning(f"[Windows App] Error connecting to '{app_name}': {e}")
            return None

    def _launch_and_connect(self, app_name: str = "", exe_path: str = "") -> any | None:
        """Launch an app and connect to it."""
        try:
            import pywinauto

            if exe_path:
                app = pywinauto.Application(backend="win32").start(exe_path)
                time.sleep(3)
                self._apps[app_name] = app
                return app

            pattern = _APP_PATTERNS.get(app_name.lower())
            if pattern:
                exe = pattern.get("exe", "")
                # Try known paths
                known_paths = {
                    "Teams.exe": [
                        "C:\\Users\\bobul\\AppData\\Local\\Microsoft\\Teams\\Update.exe",
                        "C:\\Users\\bobul\\AppData\\Local\\Programs\\Microsoft Teams\\Teams.exe",
                    ],
                }
                paths = known_paths.get(exe, [])
                for path in paths:
                    from pathlib import Path
                    if Path(path).exists():
                        app = pywinauto.Application(backend="win32").start(f'"{path}" --processStart "Teams.exe"')
                        time.sleep(4)
                        self._apps[app_name] = app
                        return app

            return None
        except Exception as e:
            logger.warning(f"[Windows App] Could not launch '{app_name}': {e}")
            return None

    def _find_element(self, app: any, spec: dict, parent: any | None = None) -> any | None:
        """Find a UI element from a spec dict."""
        try:
            dlg = parent or app.window(visible=True, enabled=True)
            criteria = {}

            elem_type = spec.get("type", "")
            text = spec.get("text", "")
            text_contains = spec.get("text_contains", "")
            class_name = spec.get("class_name", "")

            if text:
                criteria["title_re"] = f".*{text}.*"
            elif text_contains:
                criteria["title_re"] = f".*{text_contains}.*"

            if class_name:
                criteria["class_name"] = class_name

            if not criteria:
                criteria["visible"] = True

            if elem_type == "button":
                criteria["control_type"] = "Button"
            elif elem_type == "edit":
                criteria["control_type"] = "Edit"
            elif elem_type == "list":
                criteria["control_type"] = "List"

            if "index" in spec:
                elements = dlg.children(**criteria)
                if spec["index"] < len(elements):
                    return elements[spec["index"]]

            return dlg.child_window(**criteria)
        except Exception as e:
            logger.debug(f"[Windows App] Element not found: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Generic UI operations                                               #
    # ------------------------------------------------------------------ #

    def _action_list_open_windows(self, **kwargs) -> ActionResult:
        """List all open application windows."""
        try:
            from pywinauto import Desktop
            desktop = Desktop(backend='win32')
            windows = [w for w in desktop.windows()]
            apps = []
            seen = set()
            for w in windows:
                try:
                    # Use window_text() (the correct method)
                    title = w.window_text()
                    if title and len(title) > 2:
                        # Deduplicate by title
                        key = title[:50]
                        if key not in seen:
                            seen.add(key)
                            apps.append({
                                "title": title[:100],
                                "class": w.class_name(),
                            })
                except Exception:
                    continue
            apps.sort(key=lambda x: x["title"].lower())
            return ActionResult(success=True, data={"windows": apps[:50], "count": len(apps)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_connect_app(self, app_name: str = "", window_title: str = "", **kwargs) -> ActionResult:
        """Connect to a running app."""
        app = self._connect_to_app(app_name, window_title)
        if app:
            try:
                dlg = app.window(visible=True)
                return ActionResult(success=True, data={
                    "connected": True,
                    "app_name": app_name or window_title,
                    "title": dlg.window_text()[:100],
                })
            except Exception:
                return ActionResult(success=True, data={"connected": True, "app_name": app_name})
        return ActionResult(success=False, error=f"App '{app_name or window_title}' is not running")

    def _action_launch_app(self, app_name: str = "", exe_path: str = "", **kwargs) -> ActionResult:
        """Launch and connect to an app."""
        app = self._launch_and_connect(app_name, exe_path)
        if app:
            return ActionResult(success=True, data={"launched": True, "app_name": app_name})
        return ActionResult(success=False, error=f"Could not launch '{app_name}'")

    def _action_click_button(self, app_name: str = "", button_text: str = "", index: int = 0, **kwargs) -> ActionResult:
        """Click a button in an app."""
        app = self._apps.get(app_name) or self._connect_to_app(app_name)
        if not app:
            return ActionResult(success=False, error=f"Not connected to '{app_name}'")

        try:
            dlg = app.window(visible=True, enabled=True)
            # Try to find the button
            try:
                btn = dlg.child_window(title_re=f".*{button_text}.*", control_type="Button")
                btn.click()
            except Exception:
                # Try by index
                btns = [w for w in dlg.children() if "button" in w.class_name().lower()]
                if index < len(btns):
                    btns[index].click()
                else:
                    return ActionResult(success=False, error=f"Button '{button_text}' not found")
            return ActionResult(success=True, data={"clicked": button_text})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_type_text(self, app_name: str = "", text: str = "", field_text: str = "", clear_first: bool = True, **kwargs) -> ActionResult:
        """Type text into an app's focused field."""
        import pywinauto.keyboard
        try:
            app = self._apps.get(app_name) or self._connect_to_app(app_name)
            if not app:
                return ActionResult(success=False, error=f"App '{app_name}' is not running. Use open_app first to launch it.")

            dlg = app.window(visible=True)
            if field_text:
                try:
                    # Try to find the field with the label text
                    field = dlg.child_window(title_re=f".*{field_text}.*", control_type="Edit")
                    field.set_edit_text(text)
                    time.sleep(0.2)
                except Exception:
                    # Try finding the field by index (usually the main text area)
                    try:
                        field = dlg.child_window(control_type="Edit")
                        if clear_first:
                            field.type_keys("^a")
                        field.set_edit_text(text)
                        time.sleep(0.2)
                    except Exception:
                        # Last resort: just paste text
                        pywinauto.keyboard.send_keys("^a")
                        time.sleep(0.1)
                        pyperclip = self._get_pyperclip()
                        if pyperclip:
                            old = pyperclip.paste()
                            pyperclip.copy(text)
                            pywinauto.keyboard.send_keys("^v")
                            time.sleep(0.2)
                            pyperclip.copy(old)
                        else:
                            pywinauto.keyboard.send_keys(text)
            else:
                # Type directly using clipboard to handle special characters
                try:
                    pyperclip = self._get_pyperclip()
                    if pyperclip:
                        old = pyperclip.paste()
                        pyperclip.copy(text)
                        if clear_first:
                            pywinauto.keyboard.send_keys("^a")
                        pywinauto.keyboard.send_keys("^v")
                        time.sleep(0.2)
                        pyperclip.copy(old)
                    else:
                        if clear_first:
                            pywinauto.keyboard.type_keys("^a")
                        pywinauto.keyboard.send_keys(text)
                except Exception:
                    pywinauto.keyboard.send_keys(text)

            return ActionResult(success=True, data={"typed": text[:50]})
        except Exception as e:
            return ActionResult(success=False, error=f"Could not type in '{app_name}': {e}")

    def _get_pyperclip(self):
        """Safely get pyperclip module."""
        try:
            import pyperclip
            return pyperclip
        except ImportError:
            return None

    def _action_read_text(self, app_name: str = "", element_text: str = "", max_length: int = 500, **kwargs) -> ActionResult:
        """Read text from a UI element."""
        app = self._apps.get(app_name) or self._connect_to_app(app_name)
        if not app:
            return ActionResult(success=False, error=f"Not connected to '{app_name}'")

        try:
            dlg = app.window(visible=True)
            if element_text:
                try:
                    elem = dlg.child_window(title_re=f".*{element_text}.*")
                    text = elem.window_text()[:max_length]
                    return ActionResult(success=True, data={"element": element_text, "text": text})
                except Exception:
                    return ActionResult(success=False, error=f"Element '{element_text}' not found")
            else:
                # Read entire window
                text = dlg.window_text()[:max_length]
                return ActionResult(success=True, data={"window_text": text})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_read_window_content(self, app_name: str = "", **kwargs) -> ActionResult:
        """Read all visible text content from an app window."""
        app = self._apps.get(app_name) or self._connect_to_app(app_name)
        if not app:
            return ActionResult(success=False, error=f"Not connected to '{app_name}'")

        try:
            dlg = app.window(visible=True)
            texts = []
            for child in dlg.descendants():
                try:
                    t = child.window_text()
                    if t and len(t) > 1:
                        ctrl_type = child.control_type()
                        texts.append(f"[{ctrl_type}] {t}")
                except Exception:
                    continue
            return ActionResult(success=True, data={"content": texts[:100], "count": len(texts)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Teams-specific operations                                           #
    # ------------------------------------------------------------------ #

    def _action_teams_send_message(self, recipient: str = "", message: str = "", **kwargs) -> ActionResult:
        """Send a message in Microsoft Teams."""
        app = self._apps.get("teams") or self._connect_to_app("teams")
        if not app:
            # Try to launch Teams
            app = self._launch_and_connect("teams")
            if not app:
                return ActionResult(success=False, error="Teams is not running. Launch it first or use the web version.")
            time.sleep(5)

        try:
            dlg = app.window(visible=True)
            # Click search
            try:
                search = dlg.child_window(title_re=".*Search.*", control_type="Edit")
                search.click_input()
                time.sleep(0.5)
            except Exception:
                pass

            # Type recipient
            import pywinauto.keyboard
            pywinauto.keyboard.send_keys(recipient)
            time.sleep(1)
            pywinauto.keyboard.send_keys("{ENTER}")
            time.sleep(2)

            # Find message box and type
            msg_box = dlg.child_window(control_type="Edit", found_index=-1)
            msg_box.set_edit_text(message)
            time.sleep(0.5)

            # Send (Ctrl+Enter)
            pywinauto.keyboard.send_keys("^~")
            time.sleep(1)

            return ActionResult(success=True, data={"sent": True, "to": recipient, "message": message[:50]})
        except Exception as e:
            return ActionResult(success=False, error=f"Teams send failed: {e}")

    def _action_teams_join_meeting(self, meeting_link: str = "", **kwargs) -> ActionResult:
        """Join a Teams meeting."""
        if meeting_link:
            # Open the link in Teams
            try:
                import subprocess
                subprocess.run(["cmd", "/c", "start", meeting_link], shell=True)
                time.sleep(3)
                return ActionResult(success=True, data={"joined": True, "method": "meeting_link"})
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        app = self._apps.get("teams") or self._connect_to_app("teams")
        if not app:
            return ActionResult(success=False, error="Teams is not running")

        try:
            dlg = app.window(visible=True)
            # Click "Meet now" or calendar
            try:
                meet_btn = dlg.child_window(title_re=".*Meet.*now.*", control_type="Button")
                meet_btn.click()
                time.sleep(2)
                return ActionResult(success=True, data={"action": "meet_now_clicked"})
            except Exception:
                return ActionResult(success=False, error="Could not find 'Meet now' button in Teams")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Notepad                                                            #
    # ------------------------------------------------------------------ #

    def _action_notepad_read(self, max_length: int = 5000, **kwargs) -> ActionResult:
        """Read content from Notepad."""
        app = self._apps.get("notepad") or self._connect_to_app("notepad")
        if not app:
            return ActionResult(success=False, error="Notepad is not running")

        try:
            dlg = app.window(visible=True)
            editor = dlg.child_window(class_name="Edit")
            text = editor.window_text()[:max_length]
            return ActionResult(success=True, data={"content": text, "length": len(text)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_notepad_write(self, text: str = "", append: bool = False, **kwargs) -> ActionResult:
        """Write text to Notepad."""
        app = self._apps.get("notepad") or self._connect_to_app("notepad")
        if not app:
            return ActionResult(success=False, error="Notepad is not running")

        try:
            dlg = app.window(visible=True)
            editor = dlg.child_window(class_name="Edit")
            if append:
                current = editor.window_text()
                text = current + "\n" + text
            editor.set_edit_text(text)
            return ActionResult(success=True, data={"written": True, "length": len(text)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # File Explorer                                                      #
    # ------------------------------------------------------------------ #

    def _action_explorer_navigate(self, path: str = "", **kwargs) -> ActionResult:
        """Navigate File Explorer to a path."""
        app = self._apps.get("file explorer") or self._connect_to_app("file explorer")
        if not app:
            # Launch File Explorer
            try:
                import subprocess
                subprocess.Popen(["explorer.exe"])
                time.sleep(2)
                app = self._connect_to_app("file explorer")
            except Exception as e:
                return ActionResult(success=False, error=str(e))

        if not app:
            return ActionResult(success=False, error="Could not connect to File Explorer")

        try:
            dlg = app.window(visible=True)
            # Click address bar and type path
            try:
                addr = dlg.child_window(class_name="Address Band Root")
                addr.click_input()
                time.sleep(0.3)
            except Exception:
                pass

            import pywinauto.keyboard
            pywinauto.keyboard.send_keys("^a")
            pywinauto.keyboard.send_keys(path)
            pywinauto.keyboard.send_keys("{ENTER}")
            time.sleep(1)
            return ActionResult(success=True, data={"navigated": True, "path": path})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Clipboard                                                            #
    # ------------------------------------------------------------------ #

    def _action_read_clipboard(self, max_length: int = 5000, **kwargs) -> ActionResult:
        """Read text from the system clipboard."""
        try:
            import pyperclip
            text = pyperclip.paste()
            if len(text) > max_length:
                text = text[:max_length] + f"\n... [truncated, {len(text)} total chars]"
            return ActionResult(success=True, data={"text": text, "length": len(text)})
        except ImportError:
            return ActionResult(success=False, error="pyperclip not installed. Run: pip install pyperclip")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_write_clipboard(self, text: str = "", append: bool = False, **kwargs) -> ActionResult:
        """Write text to the system clipboard."""
        try:
            import pyperclip
            if append:
                existing = pyperclip.paste()
                text = existing + text
            pyperclip.copy(text)
            return ActionResult(success=True, data={"written": len(text), "length": len(text)})
        except ImportError:
            return ActionResult(success=False, error="pyperclip not installed. Run: pip install pyperclip")
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Teams deep automation                                               #
    # ------------------------------------------------------------------ #

    def _find_teams_exe(self) -> str | None:
        """Find Teams executable path."""
        paths = [
            Path(os.path.expandvars("%LOCALAPPDATA%")) / "Microsoft" / "Teams" / "Update.exe",
            Path(os.path.expandvars("%APPDATA%")) / "Microsoft" / "Teams" / "Update.exe",
            Path("C:/Users") / os.getenv("USERNAME", "") / "AppData" / "Local" / "Microsoft" / "Teams" / "Update.exe",
        ]
        for p in paths:
            if p.exists():
                return str(p)
        return None

    def _action_join_teams_meeting(self, meeting_name: str = "", meeting_link: str = "", **kwargs) -> ActionResult:
        """Join a Teams meeting by name or link."""
        try:
            import subprocess
            import ctypes

            # If a direct link is provided, open it
            if meeting_link:
                subprocess.Popen(["cmd", "/c", "start", "", meeting_link],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3)
                return ActionResult(success=True, data={"action": "join", "meeting_link": meeting_link, "spoken_message": "Joining Teams meeting from link, sir."})

            if not meeting_name:
                return ActionResult(success=False, error="Specify meeting_name or meeting_link")

            # Launch Teams and search for the meeting
            teams_path = self._find_teams_exe()
            if teams_path:
                subprocess.Popen([teams_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(4)

            # Use pywinauto to interact with Teams
            try:
                from pywinauto import Application
                app = Application(backend="uia").connect(title_re="Microsoft Teams.*", timeout=5)
                win = app.window(title_re="Microsoft Teams.*")
                win.set_focus()
                time.sleep(1)

                user32 = ctypes.windll.user32

                # Try Calendar view first (key combo Ctrl+2)
                user32.keybd_event(0x11, 0, 0, 0)  # Ctrl
                user32.keybd_event(0x32, 0, 0, 0)   # 2
                user32.keybd_event(0x32, 0, 0x0002, 0)
                user32.keybd_event(0x11, 0, 0x0002, 0)
                time.sleep(2)

                # Search for meeting
                search = win.child_window(auto_id="searchInput", control_type="Edit")
                if search.exists():
                    search.set_edit_text(meeting_name)
                    time.sleep(2)
                    user32.keybd_event(0x0D, 0, 0, 0)  # Enter
                    user32.keybd_event(0x0D, 0, 0x0002, 0)
                    time.sleep(2)

                # Try to find and click Join button
                try:
                    join_btn = win.child_window(title="Join", control_type="Button")
                    if join_btn.exists():
                        join_btn.click()
                        time.sleep(3)
                        # Confirm joining
                        join_btn2 = win.child_window(title="Join now", control_type="Button")
                        if join_btn2.exists():
                            join_btn2.click()
                except Exception:
                    pass

                return ActionResult(success=True, data={"meeting": meeting_name, "spoken_message": f"Searching for and joining {meeting_name}, sir."})

            except ImportError:
                return ActionResult(success=False, error="pywinauto not installed. Run: pip install pywinauto")
            except Exception:
                return ActionResult(success=False, error="Could not connect to Teams window")

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_teams_meetings(self, **kwargs) -> ActionResult:
        """Get today's upcoming Teams meetings from calendar."""
        try:
            import subprocess
            import ctypes

            teams_path = self._find_teams_exe()
            if not teams_path:
                return ActionResult(success=False, error="Microsoft Teams not installed")

            subprocess.Popen([teams_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(4)

            try:
                from pywinauto import Application
                user32 = ctypes.windll.user32

                app = Application(backend="uia").connect(title_re="Microsoft Teams.*", timeout=5)
                win = app.window(title_re="Microsoft Teams.*")
                win.set_focus()
                time.sleep(1)

                # Go to Calendar (Ctrl+2)
                user32.keybd_event(0x11, 0, 0, 0)
                user32.keybd_event(0x32, 0, 0, 0)
                user32.keybd_event(0x32, 0, 0x0002, 0)
                user32.keybd_event(0x11, 0, 0x0002, 0)
                time.sleep(2)

                # Try to read calendar content
                meetings = []
                try:
                    calendar_pane = win.child_window(control_type="Pane")
                    if calendar_pane.exists():
                        text = calendar_pane.window_text()
                        if text:
                            lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]
                            meetings = lines[:10]
                except Exception:
                    pass

                if meetings:
                    return ActionResult(success=True, data={"meetings": meetings, "count": len(meetings), "spoken_message": f"Found {len(meetings)} meetings today."})
                return ActionResult(success=True, data={"meetings": [], "spoken_message": "No meetings found for today, sir."})

            except ImportError:
                return ActionResult(success=False, error="pywinauto not installed")
            except Exception:
                return ActionResult(success=False, error="Could not read Teams calendar")

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_read_teams_messages(self, channel: str = "General", count: int = 10, **kwargs) -> ActionResult:
        """Read recent messages from a Teams channel."""
        try:
            import subprocess
            import ctypes

            teams_path = self._find_teams_exe()
            if teams_path:
                subprocess.Popen([teams_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(4)

            try:
                from pywinauto import Application
                user32 = ctypes.windll.user32

                app = Application(backend="uia").connect(title_re="Microsoft Teams.*", timeout=5)
                win = app.window(title_re="Microsoft Teams.*")
                win.set_focus()
                time.sleep(1)

                # Go to Teams (Ctrl+1)
                user32.keybd_event(0x11, 0, 0, 0)
                user32.keybd_event(0x31, 0, 0, 0)
                user32.keybd_event(0x31, 0, 0x0002, 0)
                user32.keybd_event(0x11, 0, 0x0002, 0)
                time.sleep(2)

                # Search for channel
                search = win.child_window(auto_id="searchInput", control_type="Edit")
                if search.exists():
                    search.set_edit_text(channel)
                    time.sleep(2)
                    user32.keybd_event(0x0D, 0, 0, 0)
                    user32.keybd_event(0x0D, 0, 0x0002, 0)
                    time.sleep(2)

                # Try to read messages from chat pane
                messages = []
                try:
                    chat_pane = win.child_window(control_type="Document")
                    if chat_pane.exists():
                        text = chat_pane.window_text()
                        if text:
                            lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 2]
                            messages = lines[-count:] if len(lines) > count else lines
                except Exception:
                    pass

                if messages:
                    msg_text = " | ".join(messages[:5])
                    return ActionResult(success=True, data={"channel": channel, "messages": messages, "count": len(messages), "spoken_message": f"Recent from {channel}: {msg_text}"})
                return ActionResult(success=True, data={"channel": channel, "messages": [], "spoken_message": f"No messages found in {channel}"})

            except ImportError:
                return ActionResult(success=False, error="pywinauto not installed")
            except Exception:
                return ActionResult(success=False, error="Could not read Teams channel")

        except Exception as e:
            return ActionResult(success=False, error=str(e))
