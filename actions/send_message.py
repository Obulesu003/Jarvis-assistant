# actions/send_message.py
# Universal messaging via Playwright -- reliable browser automation instead of
# fragile PyAutoGUI mouse coordinates.

import logging  # migrated from print()
import asyncio
import contextlib
import sys
from pathlib import Path

try:
    from playwright.async_api import TimeoutError as PWTimeout
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


# -- Browser singleton ---------------------------------------------------------

_playwright = None
_browser    = None
_context    = None


async def _get_page():
    """Get or create a browser page for messaging."""
    global _playwright, _browser, _context
    if _playwright is None:
        _playwright = await async_playwright().start()
    if _browser is None or not _browser.is_connected():
        _browser = await _playwright.chromium.launch(headless=False)
    if _context is None:
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )
    return await _context.new_page()


async def _close_messaging():
    """Close browser resources."""
    global _playwright, _browser, _context
    try:
        if _context:
            await _context.close()
            _context = None
        if _browser:
            await _browser.close()
            _browser = None
        if _playwright:
            await _playwright.stop()
            _playwright = None
    except Exception:
        pass


# -- Platform handlers ----------------------------------------------------------

async def _send_whatsapp_web(receiver: str, message: str, player) -> str:
    """
    Sends a WhatsApp message via web.whatsapp.com using Playwright.
    Steps: Navigate to web -> Search contact -> Click contact -> Type message -> Send
    """
    try:
        page = await _get_page()
        await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=30000)

        if player:
            player.write_log("[msg] Waiting for WhatsApp Web to load...")

        # Wait for the search box to appear (QR scan or already logged in)
        try:
            await page.locator('div[data-tab="3"]').wait_for(timeout=15000)
        except PWTimeout:
            # Try alternate selector for search
            try:
                await page.locator("#side").wait_for(timeout=10000)
            except PWTimeout:
                await _close_messaging()
                return (
                    "WhatsApp Web didn't load in time. "
                    "Please scan the QR code or check your internet connection, sir."
                )

        await page.wait_for_timeout(2000)

        # Search for contact
        search_selectors = [
            'div[data-tab="3"]',
            'div[title="Search"]',
            'div[title="Search input search placeholder"]',
            '#side div[contenteditable="true"]',
            'div[contenteditable="true"][data-lexical-editor="true"]',
        ]
        search_box = None
        for sel in search_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    search_box = el
                    break
            except Exception:
                continue

        if search_box is None:
            await _close_messaging()
            return "Could not find the search box on WhatsApp Web, sir."

        await search_box.click()
        await page.wait_for_timeout(500)
        await search_box.fill(receiver)
        await page.wait_for_timeout(1500)

        # Click the first contact result
        contact_selectors = [
            'span[title*="' + receiver + '"]',
            'div[data-testid="chat-list"] span[title]',
            'div[role="listitem"] span[title]',
            'span[title]',
        ]
        clicked = False
        for sel in contact_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    title = await el.get_attribute("title")
                    if title and receiver.lower() in title.lower():
                        await el.click()
                        clicked = True
                        break
            except Exception:
                continue

        if not clicked:
            # Click first visible contact as fallback
            with contextlib.suppress(Exception):
                await page.locator('div[role="listitem"]').first.click(timeout=3000)

        await page.wait_for_timeout(1000)

        # Type the message
        msg_selectors = [
            'div[data-tab="6"]',
            'footer div[contenteditable="true"]',
            'div[title="Type a message"]',
            'div[contenteditable="true"][data-lexical-editor="true"]',
            'p[spellcheck="true"]',
        ]
        msg_box = None
        for sel in msg_selectors:
            try:
                el = page.locator(sel).last
                if await el.count() > 0:
                    msg_box = el
                    break
            except Exception:
                continue

        if msg_box:
            await msg_box.click()
            await msg_box.fill(message)
            await page.wait_for_timeout(500)
            # Send via Enter or button
            with contextlib.suppress(Exception):
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(500)

        await _close_messaging()
        return f"Message sent to {receiver} via WhatsApp Web."

    except PWTimeout:
        await _close_messaging()
        return "WhatsApp timed out, sir. Please check your internet connection."
    except Exception as e:
        await _close_messaging()
        return f"WhatsApp Web error: {e}"


async def _send_telegram_web(receiver: str, message: str, player) -> str:
    """
    Sends a Telegram message via web.telegram.org using Playwright.
    """
    try:
        page = await _get_page()
        await page.goto("https://web.telegram.org/k", wait_until="domcontentloaded", timeout=30000)

        if player:
            player.write_log("[msg] Waiting for Telegram Web to load...")

        # Wait for the chat list to load
        try:
            await page.locator("#left-sidebar").wait_for(timeout=15000)
        except PWTimeout:
            await _close_messaging()
            return "Telegram Web didn't load in time, sir."

        await page.wait_for_timeout(2000)

        # Click search icon or search input
        search_selectors = [
            'input[type="search"]',
            '#left-column input[placeholder*="earch"]',
            'input[placeholder*="ontact"]',
            'div[contenteditable="true"]',
        ]
        search_box = None
        for sel in search_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    search_box = el
                    break
            except Exception:
                continue

        if search_box:
            await search_box.click()
            await page.wait_for_timeout(300)
            await search_box.fill(receiver)
            await page.wait_for_timeout(1500)

            # Click first contact
            with contextlib.suppress(Exception):
                await page.locator('.chat-item').first.click(timeout=3000)
        else:
            # Try clicking search icon then typing
            try:
                await page.locator('button[title*="earch" i], a[title*="earch" i]').first.click(timeout=3000)
                await page.wait_for_timeout(500)
                await page.keyboard.type(receiver, delay=50)
                await page.wait_for_timeout(1000)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1000)
            except Exception:
                pass

        # Type message in the input box
        msg_selectors = [
            'div[contenteditable="true"]',
            'textarea[placeholder*="ype" i]',
            'input[type="text"]',
            'div[role="textbox"]',
        ]
        for sel in msg_selectors:
            try:
                el = page.locator(sel).last
                if await el.count() > 0:
                    await el.click()
                    await el.fill(message)
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
                    break
            except Exception:
                continue

        await _close_messaging()
        return f"Message sent to {receiver} via Telegram Web."

    except Exception as e:
        await _close_messaging()
        return f"Telegram Web error: {e}"


async def _send_instagram_dm(receiver: str, message: str, player) -> str:
    """
    Sends an Instagram DM via the web interface using Playwright.
    """
    try:
        page = await _get_page()
        await page.goto("https://www.instagram.com/direct/new/", wait_until="domcontentloaded", timeout=30000)

        if player:
            player.write_log("[msg] Waiting for Instagram to load...")

        # Wait for the DM new message dialog
        try:
            await page.locator("h1").wait_for(timeout=15000)
        except PWTimeout:
            await _close_messaging()
            return "Instagram didn't load in time, sir. Please check if you're logged in."

        await page.wait_for_timeout(2000)

        # Search for the user
        search_selectors = [
            'input[placeholder*="Search"]',
            'input[placeholder*="earch"]',
            'div[contenteditable="true"]',
        ]
        for sel in search_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await el.fill(receiver)
                    await page.wait_for_timeout(1500)

                    # Click first result
                    with contextlib.suppress(Exception):
                        await page.locator('div[role="button"]').first.click(timeout=3000)
                    await page.wait_for_timeout(500)
                    break
            except Exception:
                continue

        # Navigate to the conversation
        next_selectors = [
            'button:has-text("Next")',
            'button:has-text("Next")',
            'button[tabindex="0"]',
            'div[role="button"]:has-text("Next")',
        ]
        for sel in next_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                continue

        # Type and send message
        msg_selectors = [
            'div[contenteditable="true"]',
            'textarea[placeholder*="essage"]',
        ]
        for sel in msg_selectors:
            try:
                el = page.locator(sel).last
                if await el.count() > 0:
                    await el.click()
                    await el.fill(message)
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
                    break
            except Exception:
                continue

        await _close_messaging()
        return f"Message sent to {receiver} via Instagram."

    except Exception as e:
        await _close_messaging()
        return f"Instagram DM error: {e}"


# -- PyAutoGUI fallback (desktop app) -----------------------------------------

def _send_via_desktop_app(app_name: str, receiver: str, message: str, player) -> str:
    """Fallback: uses PyAutoGUI to control the desktop app."""
    import time as t

    try:
        import pyautogui as _pyautogui
        _pyautogui.FAILSAFE = True
        _pyautogui.PAUSE = 0.08

        def _open_app(name: str) -> bool:
            try:
                _pyautogui.press("win")
                t.sleep(0.4)
                _pyautogui.write(name, interval=0.04)
                t.sleep(0.5)
                _pyautogui.press("enter")
                t.sleep(2.0)
                return True
            except Exception as e:
                logging.getLogger("msg").info(f"Could not open {name}: {e}")
                return False

        if not _open_app(app_name):
            return f"Could not open {app_name}, sir."

        t.sleep(1.5)
        _pyautogui.hotkey("ctrl", "f")
        t.sleep(0.4)
        _pyautogui.hotkey("ctrl", "a")
        _pyautogui.write(receiver, interval=0.04)
        t.sleep(1.0)
        _pyautogui.press("enter")
        t.sleep(0.8)
        _pyautogui.write(message, interval=0.03)
        t.sleep(0.2)
        _pyautogui.press("enter")

        return f"Message sent to {receiver} via {app_name} desktop app."

    except Exception as e:
        return f"{app_name} error: {e}"


# -- Main entry point -----------------------------------------------------------

def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    """
    Universal messaging via Playwright (web) with PyAutoGUI desktop fallback.

    parameters:
        receiver     : Contact name to send to
        message_text : The message content
        platform     : whatsapp | telegram | instagram | <any app name>
                       Default: whatsapp
    """
    params       = parameters or {}
    receiver     = params.get("receiver", "").strip()
    message_text = params.get("message_text", "").strip()
    platform     = params.get("platform", "whatsapp").strip().lower()

    if not receiver:
        return "Please specify who to send the message to, sir."
    if not message_text:
        return "Please specify what message to send, sir."

    logging.getLogger("SendMessage").info('📨 {platform} -> {receiver}: {message_text[:40]}')
    if player:
        player.write_log(f"[msg] Sending to {receiver} via {platform}...")

    # Use Playwright for web-based platforms
    if _PLAYWRIGHT_OK and platform in ("whatsapp", "wp", "wapp"):
        try:
            result = asyncio.run(_send_whatsapp_web(receiver, message_text, player))
            logging.getLogger("SendMessage").debug('{result}')
            if player:
                player.write_log(f"[msg] {result}")
            return result
        except Exception as e:
            logging.getLogger("SendMessage").warning('️ WhatsApp Web failed: {e}, trying desktop...')
            return _send_via_desktop_app("WhatsApp", receiver, message_text, player)

    elif _PLAYWRIGHT_OK and platform in ("telegram", "tg"):
        try:
            result = asyncio.run(_send_telegram_web(receiver, message_text, player))
            logging.getLogger("SendMessage").debug('{result}')
            if player:
                player.write_log(f"[msg] {result}")
            return result
        except Exception as e:
            logging.getLogger("SendMessage").warning('️ Telegram Web failed: {e}, trying desktop...')
            return _send_via_desktop_app("Telegram", receiver, message_text, player)

    elif _PLAYWRIGHT_OK and platform in ("instagram", "ig", "insta"):
        try:
            result = asyncio.run(_send_instagram_dm(receiver, message_text, player))
            logging.getLogger("SendMessage").debug('{result}')
            if player:
                player.write_log(f"[msg] {result}")
            return result
        except Exception as e:
            logging.getLogger("SendMessage").warning('️ Instagram DM failed: {e}')
            return f"Instagram DM error: {e}"

    # Fallback: PyAutoGUI desktop app
    app_map = {
        "whatsapp": "WhatsApp",
        "telegram": "Telegram",
        "instagram": "Instagram",
        "messenger": "Messenger",
        "discord": "Discord",
        "signal": "Signal",
    }
    app_name = app_map.get(platform, platform.title())
    result = _send_via_desktop_app(app_name, receiver, message_text, player)
    logging.getLogger("SendMessage").debug('{result}')
    if player:
        player.write_log(f"[msg] {result}")
    return result
