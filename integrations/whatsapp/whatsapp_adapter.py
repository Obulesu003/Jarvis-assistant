"""
WhatsApp adapter using Playwright browser automation.
Controls web.whatsapp.com for messaging.
"""

import asyncio
import logging
from pathlib import Path

from integrations.base.adapter import ActionResult, BaseIntegrationAdapter

logger = logging.getLogger(__name__)


class WhatsAppAdapter(BaseIntegrationAdapter):
    """
    WhatsApp Web adapter for messaging automation.

    URL: https://web.whatsapp.com
    Features:
    - Send text messages
    - Send images with captions
    - Search chats
    - Get chat history
    - Mark as read
    """

    SERVICE_NAME = "whatsapp"
    WHATSAPP_URL = "https://web.whatsapp.com"
    DEFAULT_TIMEOUT = 30
    DEFAULT_CACHE_TTL = 60  # 1 minute

    # WhatsApp selectors
    SELECTORS = {
        # Search and chat
        "search_box": '[data-testid="chat-list-search"]',
        "chat_list_item": '[data-testid="chat-list-item"]',
        "chat_title": '[data-testid="chat-title"]',
        "message_input": 'footer [data-testid="conversation-compose-box-input"]',
        "send_button": '[data-testid="send"]',
        # Chat header
        "back_button": '[data-testid="back"]',
        "chat_header": '[data-testid="conversation-panel-header"]',
        # Messages
        "message_bubble": '[data-testid="msg-body"]',
        "message_incoming": '[data-testid="msg-incoming"]',
        "message_outgoing": '[data-testid="msg-outgoing"]',
        # Media
        "attach_button": '[data-testid="attach-clip"]',
        "image_option": '[data-testid="attach-image"]',
        # Status
        "online_indicator": '[data-testid="status-egg"]',
        "typing_indicator": '[data-testid="typing"]',
        # QR Code
        "qr_code": 'canvas[aria-label*="Scan"]',
        "phone_number": '[data-testid="alert-phone"]',
        # Message status
        "delivered": '[data-testid="msg-delivered"]',
        "read": '[data-testid="msg-read"]',
        "sent": '[data-testid="msg-checked"]',
    }

    def __init__(self, session_dir: str = "config/sessions/whatsapp"):
        super().__init__(session_dir)
        self._page = None
        self._logged_in = False
        logger.info("[WhatsApp] Adapter initialized")

    def get_capabilities(self) -> list[str]:
        """Return list of supported operations."""
        return [
            "send_message",
            "send_image",
            "search_chat",
            "get_chat_history",
            "mark_read",
            "get_status",
        ]

    async def _get_page(self):
        """Get WhatsApp page, restoring session if needed."""
        if self._page is None:
            self._page = await self._pw.get_page(self.SERVICE_NAME, self.WHATSAPP_URL)
        return self._page

    def _get_page_sync(self):
        """Synchronous page getter."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self._get_page())

    async def _ensure_connected(self) -> bool:
        """Ensure WhatsApp Web is connected."""
        page = await self._get_page()

        try:
            # Already on WhatsApp?
            if "web.whatsapp.com" in page.url:
                try:
                    search = page.locator(self.SELECTORS["search_box"])
                    if await search.count() > 0:
                        self._logged_in = True
                        return True
                except Exception:
                    pass

            # Navigate to WhatsApp
            await page.goto(self.WHATSAPP_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)  # Wait for QR code / chat list to appear

            # Check for QR code (not logged in)
            try:
                qr = page.locator(self.SELECTORS["qr_code"]).first
                await qr.wait_for(timeout=3000)
                logger.warning("[WhatsApp] QR code visible — scan it in the browser window")
                self._logged_in = False
                return False
            except Exception:
                pass  # No QR code, might be logged in

            # Check for chat list (logged in)
            try:
                search = page.locator(self.SELECTORS["search_box"]).first
                await search.wait_for(timeout=5000)
                self._logged_in = True
                logger.info("[WhatsApp] Connected")
                # Save session
                await self._pw.save_session(self.SERVICE_NAME)
                return True
            except Exception:
                pass

            # Double check by looking for chat list items
            try:
                chat = page.locator(self.SELECTORS["chat_list_item"]).first
                await chat.wait_for(timeout=5000)
                self._logged_in = True
                await self._pw.save_session(self.SERVICE_NAME)
                return True
            except Exception:
                self._logged_in = False
                return False

        except Exception as e:
            logger.error(f"[WhatsApp] Error checking connection: {e}")
            self._logged_in = False
            return False

    def _is_session_active(self) -> bool:
        """Check if WhatsApp session is active."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._is_connected_async())
        except Exception:
            return False

    async def _is_connected_async(self) -> bool:
        """Async check for connection."""
        try:
            page = await self._get_page()
            # Check if URL is correct and we're logged in
            if "web.whatsapp.com" not in page.url:
                return False
            search = page.locator(self.SELECTORS["search_box"])
            return await search.count() > 0
        except Exception:
            return False

    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        """Route action to appropriate method."""
        method_name = f"_action_{action}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            try:
                return method(**kwargs)
            except Exception as e:
                return ActionResult(success=False, error=str(e))
        else:
            return ActionResult(success=False, error=f"Unknown action: {action}")

    def _action_send_message(self, receiver: str, message: str, **kwargs) -> ActionResult:
        """Send a text message to a contact."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._send_message_async(receiver, message))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _send_message_async(self, receiver: str, message: str) -> ActionResult:
        """Async implementation of send message."""
        # Ensure connected
        if not await self._ensure_connected():
            return ActionResult(success=False, error="WhatsApp not connected. Please scan QR code.")

        page = await self._get_page()

        # Search for contact
        try:
            search_box = page.locator(self.SELECTORS["search_box"]).first
            await search_box.click()
            await asyncio.sleep(0.3)
            await search_box.fill(receiver)
            await asyncio.sleep(1)

            # Click on the first chat result
            chat_item = page.locator(self.SELECTORS["chat_list_item"]).first
            await chat_item.click()
            await asyncio.sleep(1)

        except Exception:
            return ActionResult(success=False, error=f"Could not find contact: {receiver}")

        # Type message
        try:
            msg_input = page.locator(self.SELECTORS["message_input"]).first
            await msg_input.click()
            await msg_input.fill(message)
            await asyncio.sleep(0.3)

            # Click send
            send_btn = page.locator(self.SELECTORS["send_button"]).first
            await send_btn.click()
            await asyncio.sleep(1)

            self.invalidate_cache()  # Clear chat history cache
            return ActionResult(success=True, data={"sent": True, "to": receiver, "message": message[:50]})

        except Exception as e:
            return ActionResult(success=False, error=f"Could not send message: {e}")

    def _action_send_image(self, receiver: str, image_path: str, caption: str = "", **kwargs) -> ActionResult:
        """Send an image with caption to a contact."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._send_image_async(receiver, image_path, caption))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _send_image_async(self, receiver: str, image_path: str, caption: str) -> ActionResult:
        """Async implementation of send image."""
        if not await self._ensure_connected():
            return ActionResult(success=False, error="WhatsApp not connected. Please scan QR code.")

        # Check if file exists
        if not Path(image_path).exists():
            return ActionResult(success=False, error=f"Image file not found: {image_path}")

        page = await self._get_page()

        # Search for contact
        try:
            search_box = page.locator(self.SELECTORS["search_box"]).first
            await search_box.click()
            await asyncio.sleep(0.3)
            await search_box.fill(receiver)
            await asyncio.sleep(1)

            chat_item = page.locator(self.SELECTORS["chat_list_item"]).first
            await chat_item.click()
            await asyncio.sleep(1)

        except Exception:
            return ActionResult(success=False, error=f"Could not find contact: {receiver}")

        # Click attach button
        try:
            attach_btn = page.locator(self.SELECTORS["attach_button"]).first
            await attach_btn.click()
            await asyncio.sleep(0.5)

            # Click image option
            image_option = page.locator(self.SELECTORS["image_option"]).first
            await image_option.click()
            await asyncio.sleep(1)

            # Use file chooser to select image
            async with page.expect_file_chooser() as fc_info:
                pass
            file_chooser = await fc_info.value
            await file_chooser.set_files(image_path)
            await asyncio.sleep(2)  # Wait for image to upload

            # Add caption if provided
            if caption:
                msg_input = page.locator(self.SELECTORS["message_input"]).first
                await msg_input.fill(caption)

            # Send
            send_btn = page.locator(self.SELECTORS["send_button"]).first
            await send_btn.click()
            await asyncio.sleep(2)

            self.invalidate_cache()
            return ActionResult(success=True, data={"sent": True, "to": receiver, "image": image_path})

        except Exception as e:
            return ActionResult(success=False, error=f"Could not send image: {e}")

    def _action_search_chat(self, query: str, **kwargs) -> ActionResult:
        """Search for a chat by name."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._search_chat_async(query))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _search_chat_async(self, query: str) -> ActionResult:
        """Async implementation of search chat."""
        if not await self._ensure_connected():
            return ActionResult(success=False, error="WhatsApp not connected.")

        page = await self._get_page()

        try:
            search_box = page.locator(self.SELECTORS["search_box"]).first
            await search_box.click()
            await asyncio.sleep(0.3)
            await search_box.fill(query)
            await asyncio.sleep(1)

            # Get matching chats
            chat_items = page.locator(self.SELECTORS["chat_list_item"])
            count = await chat_items.count()

            results = []
            for i in range(min(count, 10)):
                try:
                    item = chat_items.nth(i)
                    title_el = item.locator(self.SELECTORS["chat_title"]).first
                    title = await title_el.inner_text() if await title_el.count() > 0 else "Unknown"
                    results.append({"name": title, "index": i})
                except Exception:
                    continue

            return ActionResult(success=True, data=results)

        except Exception as e:
            return ActionResult(success=False, error=f"Search error: {e}")

    def _action_get_chat_history(self, chat_name: str, limit: int = 20, **kwargs) -> ActionResult:
        """Get recent messages from a chat."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._get_chat_history_async(chat_name, limit))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _get_chat_history_async(self, chat_name: str, limit: int) -> ActionResult:
        """Async implementation of get chat history."""
        # Check cache first
        cache_key = f"history:{chat_name}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return ActionResult(success=True, data=cached)

        if not await self._ensure_connected():
            return ActionResult(success=False, error="WhatsApp not connected.")

        page = await self._get_page()

        try:
            # Search for and open chat
            search_box = page.locator(self.SELECTORS["search_box"]).first
            await search_box.click()
            await asyncio.sleep(0.3)
            await search_box.fill(chat_name)
            await asyncio.sleep(1)

            chat_item = page.locator(self.SELECTORS["chat_list_item"]).first
            await chat_item.click()
            await asyncio.sleep(2)

            # Scroll up to load more messages
            for _ in range(3):
                await page.keyboard.press("PageUp")
                await asyncio.sleep(0.5)

            # Get messages
            messages = []
            msg_elements = page.locator(self.SELECTORS["message_bubble"])
            count = min(await msg_elements.count(), limit)

            for i in range(count):
                try:
                    msg = msg_elements.nth(i)
                    text = await msg.inner_text()

                    # Determine if incoming or outgoing
                    parent = msg.locator("..")
                    is_outgoing = await parent.count() > 0

                    messages.append(
                        {
                            "index": i,
                            "text": text,
                            "direction": "outgoing" if is_outgoing else "incoming",
                        }
                    )
                except Exception:
                    continue

            # Cache the result
            self._cache.set(cache_key, messages)

            return ActionResult(success=True, data=messages)

        except Exception as e:
            return ActionResult(success=False, error=f"Could not get chat history: {e}")

    def _action_mark_read(self, chat_name: str | None = None, **kwargs) -> ActionResult:
        """Mark a chat as read."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._mark_read_async(chat_name))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _mark_read_async(self, chat_name: str | None = None) -> ActionResult:
        """Async implementation of mark read."""
        if not await self._ensure_connected():
            return ActionResult(success=False, error="WhatsApp not connected.")

        page = await self._get_page()

        try:
            # If chat_name provided, open that chat first
            if chat_name:
                search_box = page.locator(self.SELECTORS["search_box"]).first
                await search_box.click()
                await asyncio.sleep(0.3)
                await search_box.fill(chat_name)
                await asyncio.sleep(1)

                chat_item = page.locator(self.SELECTORS["chat_list_item"]).first
                await chat_item.click()
                await asyncio.sleep(1)

            # Double click on chat to mark as read
            # Or just navigate to it - WhatsApp auto-marks as read when viewed
            return ActionResult(success=True, data={"marked_read": True, "chat": chat_name or "current"})

        except Exception as e:
            return ActionResult(success=False, error=f"Could not mark as read: {e}")

    def _action_get_status(self, **kwargs) -> ActionResult:
        """Get WhatsApp connection status."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            connected = loop.run_until_complete(self._ensure_connected())
            session_saved = loop.run_until_complete(self._pw.save_session(self.SERVICE_NAME))
            return ActionResult(
                success=True,
                data={"connected": connected, "session_saved": session_saved},
            )
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # Override message_input with more reliable fallback selector
    SELECTORS["message_input"] = 'div[contenteditable="true"][data-tab="10"]'

    def save_session(self) -> bool:
        """Save current session."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._pw.save_session(self.SERVICE_NAME))
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to save session: {e}")
            return False

    def restore_session(self) -> bool:
        """Restore saved session."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._pw.restore_session(self.SERVICE_NAME))
        except Exception as e:
            logger.error(f"[WhatsApp] Failed to restore session: {e}")
            return False

    def requires_approval(self, action: str, params: dict) -> tuple[bool, str]:
        """Check if action requires approval."""
        write_actions = {"send_message", "send_image"}
        if action in write_actions:
            summary = f"Send message to {params.get('receiver', params.get('chat_name', 'contact'))}"
            if "message" in params:
                summary += f": {params['message'][:50]}..."
            return True, summary
        return False, ""
