import logging  # migrated from print()
import asyncio
import concurrent.futures
import contextlib
import threading
import time

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright


class _BrowserThread:

    def __init__(self):
        self._loop          = None
        self._thread        = None
        self._ready         = threading.Event()
        self._playwright    = None
        self._browser       = None
        self._context       = None       # Normal context
        self._incog_context = None       # Incognito/private context
        self._page          = None       # Normal page
        self._incog_page    = None       # Incognito page
        self._pywinauto_app = None       # pywinauto app for UI control

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BrowserThread"
        )
        self._thread.start()
        self._ready.wait(timeout=15)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._init())
        self._ready.set()
        self._loop.run_forever()

    async def _init(self):
        self._playwright = await async_playwright().start()

    def run(self, coro, timeout: int = 30):
        if not self._loop:
            msg = "BrowserThread not started."
            raise RuntimeError(msg)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # -- Connect to system Chrome ---------------------------------------------

    async def _connect_to_existing_chrome(self) -> bool:
        """Try to connect to an already-running Chrome via pywinauto."""
        try:
            import pywinauto
            from pywinauto import Desktop

            # Find Chrome windows
            desktop = Desktop(backend='win32')
            chrome_windows = []

            for w in desktop.windows():
                try:
                    title = w.window_text()
                    if title and ('chrome' in title.lower() or 'google' in title.lower()):
                        chrome_windows.append(w)
                except Exception:
                    continue

            if chrome_windows:
                # Connect to the first Chrome window
                app = pywinauto.Application(backend='win32').connect(
                    handle=chrome_windows[0].handle
                )
                self._pywinauto_app = app
                logging.getLogger("Browser").debug('Connected to existing Chrome via pywinauto')
                return True
        except Exception as e:
            logging.getLogger("Browser").info(f'pywinauto Chrome connect failed: {e}')
        return False

    async def _launch_browser_if_needed(self):
        """Try to connect to existing Chrome, or launch with channel='chrome' as fallback."""
        if self._browser and self._browser.is_connected():
            return

        # Try pywinauto first to use existing Chrome
        connected = await self._connect_to_existing_chrome()
        if connected:
            return

        # Fallback: try CDP to any running Chrome with debug port
        import os
        try:
            browser = await self._playwright.chromium.connect_over_cdp("ws://localhost:9222")
            if browser.is_connected():
                self._browser = browser
                logging.getLogger("Browser").debug('Connected via CDP debug port')
                return
        except Exception:
            pass

        # Last resort: launch Chrome with persistent profile
        chrome_user_data = r"C:\Users\bobul\AppData\Local\Google\Chrome\User Data"
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                channel="chrome",
                args=[
                    "--start-maximized",
                    f"--user-data-dir={chrome_user_data}",
                    "--profile-directory=Default",
                ],
            )
            logging.getLogger("Browser").debug('Launched Chrome with persistent profile')
        except Exception as e:
            # Fallback to current behavior if profile fails
            logging.getLogger("Browser").warning(f'Persistent profile failed ({e}), trying default launch')
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=False,
                    channel="chrome",
                    args=["--start-maximized"],
                )
                logging.getLogger("Browser").debug('Launched Chrome (fallback)')
            except Exception as fallback_e:
                logging.getLogger("Browser").error(f'Could not connect to Chrome: {fallback_e}')
                logging.getLogger("Browser").info('Please open Chrome manually and try again')
                raise

    async def _get_page(self, incognito: bool = False):
        """
        Returns a page. Uses pywinauto if already connected to Chrome,
        otherwise tries Playwright with existing sessions.
        """
        # If we have pywinauto connection, we can't create new pages
        # Just note this and return a message
        if self._pywinauto_app:
            return None  # Will use pywinauto instead

        await self._launch_browser_if_needed()

        if incognito:
            return await self._get_incognito_page()
        return await self._get_normal_page()

    async def _get_normal_page(self):
        if self._page is None or self._page.is_closed():
            if self._context is None or not self._context.pages:
                self._context = await self._browser.new_context(
                    viewport=None,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                )
            self._page = await self._context.new_page()
        return self._page

    async def _get_incognito_page(self):
        """
        Opens a new incognito context in the existing Chrome (via CDP).
        Each incognito page is a separate isolated context but same Chrome window.
        """
        if self._incog_page and not self._incog_page.is_closed():
            return self._incog_page

        if self._incog_context:
            with contextlib.suppress(Exception):
                await self._incog_context.close()

        self._incog_context = await self._browser.new_context(
            viewport=None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        self._incog_page = await self._incog_context.new_page()
        logging.getLogger("Browser").debug('Incognito page ready in your Chrome.')
        return self._incog_page

    # -- Actions -------------------------------------------------------------

    async def _go_to(self, url: str, incognito: bool = False) -> str:
        if not url.startswith("http"):
            url = "https://" + url

        # If using pywinauto (connected to existing Chrome), open URL properly
        if self._pywinauto_app:
            return await self._pywinauto_open_url(url)

        page = await self._get_page(incognito=incognito)
        if page is None:
            return f"Could not connect to browser for: {url}"

        try:
            # Skip navigation if already at this URL
            if page.url and (url in page.url or page.url in url):
                return f"Already at: {page.url}"
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            mode = " [private]" if incognito else ""
            return f"Opened{mode}: {page.url}"
        except PlaywrightTimeout:
            return f"Timeout loading: {url}"
        except Exception as e:
            return f"Navigation error: {e}"

    async def _search(self, query: str, engine: str = "google", incognito: bool = False) -> str:
        engines = {
            "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing":       f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
        }
        url = engines.get(engine.lower(), engines["google"])
        return await self._go_to(url, incognito=incognito)

    async def _click(self, selector=None, text=None, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            if text:
                await page.get_by_text(text, exact=False).first.click(timeout=8000)
                return f"Clicked: '{text}'"
            if selector:
                await page.click(selector, timeout=8000)
                return f"Clicked: {selector}"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found or not clickable."
        except Exception as e:
            return f"Click error: {e}"

    async def _type(self, selector=None, text: str = "", clear_first: bool = True, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            element = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await element.clear()
            await element.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def _scroll(self, direction: str = "down", amount: int = 500, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def _press(self, key: str, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Press error: {e}"

    async def _get_text(self, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            text = await page.inner_text("body")
            return text[:4000] if len(text) > 4000 else text
        except Exception as e:
            return f"Could not get page text: {e}"

    async def _fill_form(self, fields: dict, incognito: bool = False) -> str:
        page    = await self._get_page(incognito=incognito)
        results = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"[OK] {selector}")
            except Exception as e:
                results.append(f"[FAIL] {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def _smart_click(self, description: str, incognito: bool = False) -> str:
        page       = await self._get_page(incognito=incognito)

        # If no page (using pywinauto), try pywinauto approach
        if page is None:
            return await self._pywinauto_click(description)

        desc_lower = description.lower()

        role_hints = {
            "button":    ["button", "buton", "btn"],
            "link":      ["link", "bağlantı"],
            "searchbox": ["search", "arama"],
            "textbox":   ["input", "field", "alan"],
        }
        for role, keywords in role_hints.items():
            if any(k in desc_lower for k in keywords):
                try:
                    await page.get_by_role(role).first.click(timeout=5000)
                    return f"Clicked ({role}): '{description}'"
                except Exception:
                    pass

        try:
            await page.get_by_text(description, exact=False).first.click(timeout=5000)
            return f"Clicked (text): '{description}'"
        except Exception:
            pass

        try:
            await page.get_by_placeholder(description, exact=False).first.click(timeout=5000)
            return f"Clicked (placeholder): '{description}'"
        except Exception:
            pass

        return f"Could not find: '{description}'"

    async def _pywinauto_click(self, description: str) -> str:
        """Click using pywinauto on existing Chrome window."""
        try:
            import pywinauto
            import pywinauto.keyboard

            if not self._pywinauto_app:
                return f"Chrome not connected for pywinauto: '{description}'"

            dlg = self._pywinauto_app.window(visible=True)

            # Try to find and click by text
            try:
                elem = dlg.child_window(title_re=f".*{description}.*", control_type="Button")
                elem.click()
                return f"Clicked (pywinauto): '{description}'"
            except Exception:
                pass

            try:
                elem = dlg.child_window(title_re=f".*{description}.*", control_type="Hyperlink")
                elem.click()
                return f"Clicked (pywinauto): '{description}'"
            except Exception:
                pass

            return f"Could not find element: '{description}'"
        except Exception as e:
            return f"pywinauto click failed: {e}"

    async def _pywinauto_open_url(self, url: str) -> str:
        """Open URL in existing Chrome using Ctrl+L address bar + Ctrl+T new tab."""
        try:
            import pywinauto.keyboard

            if not self._pywinauto_app:
                return f"Chrome not connected"

            dlg = self._pywinauto_app.window(visible=True)
            dlg.set_focus()

            # Open new tab with Ctrl+T
            pywinauto.keyboard.send_keys("^t")
            time.sleep(0.3)

            # Focus address bar with Ctrl+L
            pywinauto.keyboard.send_keys("^l")
            time.sleep(0.2)

            # Type URL and press Enter
            pywinauto.keyboard.send_keys(url)
            pywinauto.keyboard.send_keys("{ENTER}")
            time.sleep(1)

            return f"Opened in Chrome: {url}"
        except Exception as e:
            return f"Could not open URL: {e}"

    async def _smart_type(self, description: str, text: str, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)

        for method, locator in [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox")),
        ]:
            try:
                el = locator.first
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue

        return f"Could not find input: '{description}'"

    async def _close_browser(self) -> str:
        """Disconnect from Chrome. Does NOT close Chrome itself — only Playwright's connection."""
        if self._incog_context:
            with contextlib.suppress(Exception):
                await self._incog_context.close()
            self._incog_context = None
            self._incog_page    = None

        if self._context:
            with contextlib.suppress(Exception):
                await self._context.close()
            self._context = None
            self._page    = None

        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.disconnect()
            self._browser = None

        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

        return "Disconnected from Chrome. Chrome itself stays open."


# -- Singleton browser thread -------------------------------------------------

_bt         = _BrowserThread()
_bt_started = False
_bt_lock    = threading.Lock()


def _ensure_started():
    global _bt_started
    with _bt_lock:
        if not _bt_started:
            _bt.start()
            _bt_started = True


# -- Public API ---------------------------------------------------------------

def browser_control(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    """
    Browser controller -- uses system Chrome via channel='chrome'.
    All your existing sessions (YouTube, Gmail, ChatGPT) are available.
    No debug port needed -- just ensure Google Chrome is your default browser.

    parameters:
        action      : go_to | search | click | type | scroll | fill_form |
                      smart_click | smart_type | get_text | press | close
        url         : URL for go_to
        query       : search query
        engine      : google | bing | duckduckgo (default: google)
        selector    : CSS selector for click/type
        text        : text to click or type
        description : element description for smart_click/smart_type
        direction   : up | down for scroll
        amount      : scroll amount in pixels (default: 500)
        key         : key name for press (e.g. Enter, Escape, Tab)
        fields      : {selector: value} dict for fill_form
        clear_first : bool, clear input before typing (default: True)
        incognito   : bool, open in incognito tab in your Chrome (default: False)
    """
    _ensure_started()

    action    = (parameters or {}).get("action", "").lower().strip()
    incognito  = bool(parameters.get("incognito", False))
    result    = "Unknown action."

    try:
        if action == "go_to":
            result = _bt.run(_bt._go_to(parameters.get("url", ""), incognito=incognito))

        elif action == "search":
            result = _bt.run(_bt._search(
                parameters.get("query", ""),
                parameters.get("engine", "google"),
                incognito=incognito
            ))

        elif action == "click":
            result = _bt.run(_bt._click(
                selector=parameters.get("selector"),
                text=parameters.get("text"),
                incognito=incognito
            ))

        elif action == "type":
            result = _bt.run(_bt._type(
                selector=parameters.get("selector"),
                text=parameters.get("text", ""),
                clear_first=parameters.get("clear_first", True),
                incognito=incognito
            ))

        elif action == "scroll":
            result = _bt.run(_bt._scroll(
                direction=parameters.get("direction", "down"),
                amount=parameters.get("amount", 500),
                incognito=incognito
            ))

        elif action == "fill_form":
            result = _bt.run(_bt._fill_form(
                parameters.get("fields", {}),
                incognito=incognito
            ))

        elif action == "smart_click":
            result = _bt.run(_bt._smart_click(
                parameters.get("description", ""),
                incognito=incognito
            ))

        elif action == "smart_type":
            result = _bt.run(_bt._smart_type(
                parameters.get("description", ""),
                parameters.get("text", ""),
                incognito=incognito
            ))

        elif action == "get_text":
            result = _bt.run(_bt._get_text(incognito=incognito))

        elif action == "press":
            result = _bt.run(_bt._press(
                parameters.get("key", "Enter"),
                incognito=incognito
            ))

        elif action == "close":
            result = _bt.run(_bt._close_browser())

        else:
            result = f"Unknown action: {action}"

    except concurrent.futures.TimeoutError:
        logging.getLogger("Browser").warning("Action timed out, resetting connection...")
        _bt._browser = None
        _bt._context = None
        _bt._page = None
        _bt._incog_context = None
        _bt._incog_page = None
        result = "Browser action timed out. Reconnected for next request."
    except Exception as e:
        # Don't spam errors if browser just disconnected
        error_str = str(e)
        if "Target page" in error_str or "closed" in error_str.lower() or "disconnected" in error_str.lower():
            logging.getLogger("Browser").info("Browser disconnected, resetting connection...")
            # Reset browser state for next call
            _bt._browser = None
            _bt._context = None
            _bt._page = None
            _bt._incog_context = None
            _bt._incog_page = None
            result = f"Browser disconnected. Try again."
        else:
            result = f"Browser error: {e}"

    logging.getLogger("Browser").info(f'{result[:80]}')
    if player:
        player.write_log(f"[browser] {result[:60]}")

    return result


