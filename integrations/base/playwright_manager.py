"""
Playwright browser manager for all integrations.

Supports two connection modes:
1. channel='chrome' — uses system Chrome, inherits all existing sessions.
   Simple, no setup needed. Opens a Chrome window if none is running.
2. connect_over_cdp() — connects to Chrome with --remote-debugging-port.
   Reuses existing Chrome window exactly as-is. Run start_chrome_debug.ps1 first.

Default: channel='chrome' (simpler, more reliable).
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DEBUG_PORT = 9222


class PlaywrightManager:
    """
    Singleton browser manager.

    Connects to the user's existing Chrome browser via CDP debug port.
    All existing sessions are automatically available.
    """

    _instance: Optional["PlaywrightManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, debug_port: int = DEFAULT_DEBUG_PORT, use_cdp: bool = True):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._debug_port = debug_port
        self._use_cdp = use_cdp
        self._playwright = None
        self._browser = None
        self._contexts: dict[str, any] = {}  # service -> context
        self._initialized = True

        mode = f"CDP port {debug_port}" if use_cdp else "channel='chrome'"
        logger.info(f"[Playwright] Manager initialized ({mode})")

    @classmethod
    def get_instance(cls, debug_port: int = DEFAULT_DEBUG_PORT, use_cdp: bool = True) -> "PlaywrightManager":
        if cls._instance is None:
            cls._instance = cls(debug_port=debug_port, use_cdp=use_cdp)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton — call this to reconnect on a new port."""
        if cls._instance is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(cls._instance.close())
                else:
                    loop.run_until_complete(cls._instance.close())
            except Exception:
                pass
            cls._instance = None

    async def _get_playwright(self):
        if self._playwright is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
        return self._playwright

    async def _ensure_browser(self):
        """Connect to Chrome. Mode depends on _use_cdp flag."""
        if self._browser is not None:
            try:
                _ = self._browser.contexts
                return True
            except Exception:
                self._browser = None

        pw = await self._get_playwright()

        if self._use_cdp:
            # CDP mode: connect to Chrome with debug port (must run start_chrome_debug.ps1 first)
            try:
                cdp_url = f"http://localhost:{self._debug_port}"
                self._browser = await pw.chromium.connect_over_cdp(cdp_url)
                logger.info(f"[Playwright] Connected via CDP port {self._debug_port}")
                return True
            except Exception as e:
                logger.warning(f"[Playwright] CDP connection failed: {e}")
                logger.info("[Playwright] Falling back to channel='chrome' mode...")

        # Fallback: channel='chrome' mode - uses system Chrome, inherits all sessions
        try:
            self._browser = await pw.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--start-maximized"],
            )
            logger.info("[Playwright] Connected to system Chrome via channel='chrome'")
            return True
        except Exception as e:
            logger.error(f"[Playwright] channel='chrome' failed: {e}")
            return False

    async def get_context(self, service: str) -> any:
        """Get or create a browser context for a service."""
        await self._ensure_browser()

        if service in self._contexts:
            try:
                _ = self._contexts[service].browser
                return self._contexts[service]
            except Exception:
                del self._contexts[service]

        context = await self._browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        self._contexts[service] = context
        logger.info(f"[Playwright] Context ready for: {service}")
        return context

    async def new_tab(self, url: str | None = None, service: str = "default") -> any:
        """
        Open a NEW TAB in the existing Chrome browser.
        This is the key method — it adds a tab to the Chrome window
        the user already has open, not a new browser.
        """
        await self._ensure_browser()
        if self._browser is None:
            msg = "Cannot connect to Chrome. Is start_chrome_debug.ps1 running?"
            raise RuntimeError(msg)

        # Create a new page (tab) in the existing browser
        page = await self._browser.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            logger.info(f"[Playwright] Opened new tab: {url[:60]}")
        else:
            logger.info("[Playwright] Opened new blank tab")

        return page

    async def get_or_create_page(self, service: str, url: str | None = None) -> any:
        """
        Get or create a page for a service.
        Reuses existing context if available.
        """
        await self._ensure_browser()
        if self._browser is None:
            msg = "Cannot connect to Chrome. Is start_chrome_debug.ps1 running?"
            raise RuntimeError(msg)

        if service not in self._contexts:
            self._contexts[service] = await self._browser.new_context(
                viewport={"width": 1400, "height": 900},
            )

        context = self._contexts[service]
        page = await context.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            logger.info(f"[Playwright] {service}: {url[:60]}")

        return page

    async def get_page(self, service: str, url: str | None = None) -> any:
        """Get a page in the service context, navigating to URL if provided."""
        return await self.get_or_create_page(service, url)

    async def save_session(self, service: str):
        """Save session cookies and storage state to disk."""
        if service not in self._contexts:
            return

        try:
            context = self._contexts[service]
            session_path = Path("config/sessions") / service
            session_path.mkdir(parents=True, exist_ok=True)

            storage_state = await context.storage_state()
            import json
            (session_path / "storage.json").write_text(
                json.dumps(storage_state, ensure_ascii=False)
            )
            logger.info(f"[Playwright] Session saved for: {service}")
        except Exception as e:
            logger.warning(f"[Playwright] Session save failed for {service}: {e}")

    async def save_all_sessions(self):
        for service in list(self._contexts.keys()):
            await self.save_session(service)

    async def bring_to_front(self, service: str) -> bool:
        if service not in self._contexts:
            return False
        try:
            pages = self._contexts[service].pages
            if pages:
                await pages[0].bring_to_front()
                return True
        except Exception:
            pass
        return False

    async def list_tabs(self) -> list[dict]:
        """List all browser tabs."""
        tabs = []
        if self._browser is None:
            return tabs
        try:
            for ctx in self._browser.contexts:
                for pg in ctx.pages:
                    with contextlib.suppress(Exception):
                        tabs.append({"url": pg.url, "title": await pg.title()})
        except Exception:
            pass
        return tabs

    async def close(self):
        """Close browser cleanly."""
        await self.save_all_sessions()

        for service, context in self._contexts.items():
            with contextlib.suppress(Exception):
                await context.close()
        self._contexts.clear()

        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None

        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

        logger.info("[Playwright] Browser closed")

    def is_connected(self) -> bool:
        if self._browser is None:
            return False
        try:
            _ = self._browser.contexts
            return True
        except Exception:
            return False

    def __del__(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.close())
            else:
                loop.run_until_complete(self.close())
        except Exception:
            pass
