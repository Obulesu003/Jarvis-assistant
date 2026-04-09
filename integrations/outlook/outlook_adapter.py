"""
Outlook adapter using Playwright browser automation.
Controls Outlook web (outlook.live.com) for email and calendar.
"""

import asyncio
import logging
from dataclasses import dataclass

from integrations.base.adapter import ActionResult, BaseIntegrationAdapter
from integrations.base.exceptions import (
    ServiceError,
)

logger = logging.getLogger(__name__)


@dataclass
class Email:
    """Email message representation."""
    id: str
    subject: str
    sender: str
    recipients: str
    preview: str
    date: str
    is_read: bool
    has_attachments: bool
    folder: str = "INBOX"


@dataclass
class CalendarEvent:
    """Calendar event representation."""
    id: str
    title: str
    start: str
    end: str
    location: str
    attendees: list
    organizer: str
    is_all_day: bool
    recurring: bool


class OutlookAdapter(BaseIntegrationAdapter):
    """
    Outlook web adapter for email and calendar automation.

    URL: https://outlook.live.com (default)
    Features:
    - Email: list, search, read, send, reply, forward
    - Calendar: list, create, update, delete events
    """

    SERVICE_NAME = "outlook"
    DEFAULT_TIMEOUT = 30
    DEFAULT_CACHE_TTL = 120  # 2 minutes

    # Outlook URLs - uses settings.json config
    OUTLOOK_URL = "https://outlook.cloud.microsoft/mail"
    CALENDAR_URL = "https://outlook.cloud.microsoft/calendar"

    # CSS selectors for email
    EMAIL_SELECTORS = {
        "email_list_item": '[data-conversation-id]',
        "email_subject": '[aria-label*="Subject"]',
        "email_sender": '[data-sgar*="sender"]',
        "email_body": '[role="main"] [aria-label*="body"]',
        "compose_button": 'button[aria-label*="New mail"]',
        "to_field": 'input[aria-label*="To"]',
        "subject_field": 'input[name="subject"]',
        "body_field": 'div[aria-label*="message body"]',
        "send_button": 'button[aria-label*="Send"]',
        "search_box": 'input[aria-label*="Search"]',
        "attachment_button": 'button[aria-label*="Attach"]',
        "reply_button": 'button[aria-label*="Reply"]',
        "forward_button": 'button[aria-label*="Forward"]',
        "close_button": 'button[aria-label*="Close"]',
        "loading": '[role="progressbar"]',
        "inbox_folder": '[aria-label="Inbox"]',
        "sent_folder": '[aria-label="Sent"]',
    }

    # CSS selectors for calendar
    CALENDAR_SELECTORS = {
        "new_event_button": 'button[aria-label*="New event"]',
        "event_title": 'input[aria-label*="Title"]',
        "event_start": 'input[aria-label*="Start"]',
        "event_end": 'input[aria-label*="End"]',
        "event_location": 'input[aria-label*="Location"]',
        "event_attendees": 'input[aria-label*="optional"]',
        "event_save": 'button[aria-label*="Save"]',
        "event_delete": 'button[aria-label*="Delete"]',
        "event_item": '[data-item-id]',
        "day_view": '[aria-label*="day"]',
        "month_view": '[aria-label*="month"]',
        "today_button": 'button[aria-label*="Today"]',
    }

    def __init__(self, url: str | None = None, session_dir: str = "config/sessions/outlook"):
        super().__init__(session_dir)
        self._url = url or self.OUTLOOK_URL
        self._calendar_url = url.replace("/mail/", "/calendar/") if url else self.CALENDAR_URL
        self._page = None
        self._logged_in = False
        logger.info(f"[Outlook] Adapter initialized for {self._url}")

    def get_capabilities(self) -> list[str]:
        """Return list of supported operations."""
        return [
            "list_emails",
            "search_emails",
            "read_email",
            "send_email",
            "reply_email",
            "forward_email",
            "list_events",
            "create_event",
            "update_event",
            "delete_event",
            "find_meeting_time",
        ]

    def _get_page_sync(self):
        """Synchronous page getter."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self._get_page())

    async def _get_page(self):
        """Get Outlook page, restoring session if needed."""
        if self._page is None:
            self._page = await self._pw.get_page(self.SERVICE_NAME, self.OUTLOOK_URL)
        return self._page

    async def _ensure_logged_in(self) -> bool:
        """Ensure user is logged into Outlook."""
        page = await self._get_page()

        try:
            # Already on Outlook?
            if "outlook.live.com" in page.url or "outlook.office.com" in page.url:
                if "login" not in page.url.lower() and "signin" not in page.url.lower():
                    self._logged_in = True
                    return True

            # Navigate to Outlook
            await page.goto(self.OUTLOOK_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # Check if login is required
            if "login" in page.url.lower() or "signin" in page.url.lower():
                logger.warning("[Outlook] Login required — please log in manually in the browser window")
                self._logged_in = False
                return False

            # Check for login button or profile
            try:
                profile = page.locator('[aria-label*="profile"], [data-testid="surface"]').first
                await profile.wait_for(timeout=5000)
                self._logged_in = True
                logger.info("[Outlook] Logged in")
                # Save session so next time we don't need to log in
                await self._pw.save_session(self.SERVICE_NAME)
                return True
            except Exception:
                try:
                    await page.locator('button[aria-label*="account"], [data-testid="shellNav"]').first.wait_for(
                        timeout=3000
                    )
                    self._logged_in = True
                    await self._pw.save_session(self.SERVICE_NAME)
                    return True
                except Exception:
                    self._logged_in = False
                    return False

        except Exception as e:
            logger.error(f"[Outlook] Error checking login: {e}")
            self._logged_in = False
            return False

    def _is_session_active(self) -> bool:
        """Check if Outlook session is active."""
        try:
            return self._get_page_sync() is not None and self._logged_in
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

    def _action_list_emails(self, folder: str = "INBOX", max_results: int = 20, **kwargs) -> ActionResult:
        """List emails in a folder."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            emails = loop.run_until_complete(self._list_emails_async(folder, max_results))
            return ActionResult(success=True, data=emails)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _list_emails_async(self, folder: str, max_results: int) -> list[dict]:
        """Async implementation of list emails."""
        page = await self._get_page()

        # Navigate to correct folder
        if folder.upper() != "INBOX":
            folder_map = {"SENT": "sent", "DRAFT": "drafts", "SPAM": "junk", "TRASH": "deleted"}
            folder_id = folder_map.get(folder.upper(), folder.lower())
            await page.goto(f"https://outlook.live.com/mail/0/{folder_id}", wait_until="domcontentloaded")
        else:
            await page.goto(self.OUTLOOK_URL, wait_until="domcontentloaded")

        # Wait for emails to load
        await asyncio.sleep(2)
        await self._wait_for_loading(page)

        # Get email list
        emails = []
        email_items = page.locator('[data-conversation-id]')
        count = min(await email_items.count(), max_results)

        for i in range(count):
            try:
                item = email_items.nth(i)
                await item.click()
                await asyncio.sleep(1)

                # Read email details from the reading pane
                try:
                    subject = page.locator('[aria-label*="Subject"]').first.inner_text(timeout=3000)
                except Exception:
                    subject = "No Subject"

                try:
                    sender = page.locator('[aria-label*="From"]').first.inner_text(timeout=2000)
                    sender = sender.replace("From: ", "").strip()
                except Exception:
                    sender = "Unknown"

                try:
                    preview = page.locator('[aria-label*="Preview"]').first.inner_text(timeout=2000)
                except Exception:
                    preview = ""

                # Get message ID from URL or element
                msg_id = str(i + 1)

                emails.append(
                    {
                        "id": msg_id,
                        "subject": subject,
                        "sender": sender,
                        "preview": preview[:100],
                        "folder": folder,
                    }
                )

                # Go back to list
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"[Outlook] Error reading email {i}: {e}")
                continue

        return emails

    def _action_search_emails(self, query: str, max_results: int = 20, **kwargs) -> ActionResult:
        """Search emails."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(self._search_emails_async(query, max_results))
            return ActionResult(success=True, data=results)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _search_emails_async(self, query: str, max_results: int) -> list[dict]:
        """Async implementation of search emails."""
        page = await self._get_page()

        # Click search box and type query
        search_box = page.locator('input[aria-label*="Search"]').first
        await search_box.click()
        await asyncio.sleep(0.5)

        # Clear and enter new query
        await search_box.fill("")
        await search_box.type(query, delay=50)
        await page.keyboard.press("Enter")

        await asyncio.sleep(2)
        await self._wait_for_loading(page)

        # Get results (similar to list emails)
        results = []
        email_items = page.locator('[data-conversation-id]')
        count = min(await email_items.count(), max_results)

        for i in range(count):
            try:
                item = email_items.nth(i)
                subject_el = item.locator('[aria-label*="Subject"]').first
                subject = await subject_el.inner_text() if await subject_el.count() > 0 else "No Subject"

                results.append(
                    {
                        "id": str(i + 1),
                        "subject": subject,
                        "query": query,
                    }
                )
            except Exception:
                continue

        return results

    def _action_read_email(self, email_id: str | None = None, **kwargs) -> ActionResult:
        """Read full email content."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            email = loop.run_until_complete(self._read_email_async(email_id))
            return ActionResult(success=True, data=email)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _read_email_async(self, email_id: str) -> dict:
        """Async implementation of read email."""
        page = await self._get_page()

        # If no email_id provided, assume we're already viewing an email
        # Try to get the currently open email

        try:
            subject_el = page.locator('[aria-label*="Subject:"]').first
            subject = await subject_el.inner_text(timeout=3000)
            subject = subject.replace("Subject: ", "").strip()
        except Exception:
            subject = "No Subject"

        try:
            from_el = page.locator('[aria-label*="From:"]').first
            sender = await from_el.inner_text(timeout=2000)
            sender = sender.replace("From: ", "").strip()
        except Exception:
            sender = "Unknown"

        try:
            # Try to get body
            body_el = page.locator('[aria-label*="body"], [role="article"]').first
            body = await body_el.inner_text(timeout=3000)
        except Exception:
            # Try alternative approach
            try:
                all_text = await page.locator('[role="main"]').first.inner_text()
                body = all_text
            except Exception:
                body = ""

        return {
            "id": email_id or "current",
            "subject": subject,
            "sender": sender,
            "body": body,
            "url": page.url,
        }

    def _action_send_email(
        self, to: str, subject: str, body: str, cc: str | None = None, attachments: list | None = None, **kwargs
    ) -> ActionResult:
        """Send an email."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._send_email_async(to, subject, body, cc, attachments))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _send_email_async(
        self, to: str, subject: str, body: str, cc: str | None = None, attachments: list | None = None
    ) -> ActionResult:
        """Async implementation of send email."""
        page = await self._get_page()

        # Click compose button
        try:
            compose_btn = page.locator('button[aria-label*="New mail"], button[aria-label*="New message"]').first
            await compose_btn.click()
            await asyncio.sleep(1)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not open compose: {e}")

        # Fill in recipient
        try:
            to_field = page.locator('div[aria-label*="To"] input, input[aria-label*="To"]').first
            await to_field.click()
            await to_field.fill(to)
            await asyncio.sleep(0.5)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not fill recipient: {e}")

        # Fill subject
        try:
            subject_field = page.locator('input[name="subject"], input[aria-label*="Subject"]').first
            await subject_field.fill(subject)
        except Exception as e:
            logger.warning(f"[Outlook] Subject field issue: {e}")

        # Fill body
        try:
            body_field = page.locator('div[aria-label*="body"], [role="textbox"]').first
            await body_field.click()
            await body_field.fill(body)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not fill body: {e}")

        # CC if provided
        if cc:
            try:
                # Open CC field
                await page.locator('button[aria-label*="Cc"]').click()
                await asyncio.sleep(0.5)
                cc_field = page.locator('input[aria-label*="Cc"]').first
                await cc_field.fill(cc)
            except Exception as e:
                logger.warning(f"[Outlook] CC field issue: {e}")

        # Click send
        try:
            send_btn = page.locator('button[aria-label*="Send"]').first
            await send_btn.click()
            await asyncio.sleep(2)
            self.invalidate_cache()  # Clear cache since we sent an email
            return ActionResult(success=True, data={"sent": True, "to": to, "subject": subject})
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not send email: {e}")

    def _action_reply_email(self, email_id: str | None = None, body: str = "", attachments: list | None = None, **kwargs) -> ActionResult:
        """Reply to an email."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._reply_email_async(body, attachments))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _reply_email_async(self, body: str, attachments: list | None = None) -> ActionResult:
        """Async implementation of reply email."""
        page = await self._get_page()

        # Click reply button
        try:
            reply_btn = page.locator('button[aria-label*="Reply"]').first
            await reply_btn.click()
            await asyncio.sleep(1)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not click reply: {e}")

        # Fill body
        try:
            body_field = page.locator('div[aria-label*="body"], [role="textbox"]').first
            await body_field.fill(body)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not fill body: {e}")

        # Send
        try:
            send_btn = page.locator('button[aria-label*="Send"]').first
            await send_btn.click()
            await asyncio.sleep(2)
            self.invalidate_cache()
            return ActionResult(success=True, data={"replied": True})
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not send reply: {e}")

    def _action_forward_email(self, email_id: str | None = None, to: str = "", body: str = "", **kwargs) -> ActionResult:
        """Forward an email."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._forward_email_async(to, body))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _forward_email_async(self, to: str, body: str) -> ActionResult:
        """Async implementation of forward email."""
        page = await self._get_page()

        try:
            forward_btn = page.locator('button[aria-label*="Forward"]').first
            await forward_btn.click()
            await asyncio.sleep(1)

            # Fill recipient
            to_field = page.locator('div[aria-label*="To"] input, input[aria-label*="To"]').first
            await to_field.fill(to)

            # Fill body
            if body:
                body_field = page.locator('div[aria-label*="body"], [role="textbox"]').first
                await body_field.fill(body)

            # Send
            send_btn = page.locator('button[aria-label*="Send"]').first
            await send_btn.click()
            await asyncio.sleep(2)
            self.invalidate_cache()
            return ActionResult(success=True, data={"forwarded": True, "to": to})

        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not forward email: {e}")

    # Calendar actions
    def _action_list_events(self, date: str | None = None, max_results: int = 20, **kwargs) -> ActionResult:
        """List calendar events."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            events = loop.run_until_complete(self._list_events_async(date, max_results))
            return ActionResult(success=True, data=events)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _list_events_async(self, date: str, max_results: int) -> list[dict]:
        """Async implementation of list events."""
        page = await self._get_page()

        # Navigate to calendar
        await page.goto(self.CALENDAR_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        await self._wait_for_loading(page)

        events = []
        event_items = page.locator('[data-item-id]')
        count = min(await event_items.count(), max_results)

        for i in range(count):
            try:
                item = event_items.nth(i)
                title_el = item.locator('[aria-label*="title"], [role="heading"]').first
                title = await title_el.inner_text() if await title_el.count() > 0 else "Untitled"

                events.append(
                    {
                        "id": str(i + 1),
                        "title": title,
                    }
                )
            except Exception:
                continue

        return events

    def _action_create_event(
        self,
        title: str,
        start: str,
        end: str | None = None,
        description: str = "",
        location: str = "",
        attendees: list | None = None,
        **kwargs,
    ) -> ActionResult:
        """Create a calendar event."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self._create_event_async(title, start, end, description, location, attendees))
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _create_event_async(
        self, title: str, start: str, end: str, description: str, location: str, attendees: list
    ) -> ActionResult:
        """Async implementation of create event."""
        page = await self._get_page()

        # Navigate to calendar
        await page.goto(self.CALENDAR_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Click new event button
        try:
            new_btn = page.locator('button[aria-label*="New event"], button[aria-label*="New"]').first
            await new_btn.click()
            await asyncio.sleep(1)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not create new event: {e}")

        # Fill title
        try:
            title_field = page.locator('input[aria-label*="Title"], input[name="subject"]').first
            await title_field.fill(title)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not set title: {e}")

        # Fill start time
        if start:
            try:
                start_field = page.locator('input[aria-label*="Start"]').first
                await start_field.fill(start)
            except Exception as e:
                logger.warning(f"[Outlook] Start time issue: {e}")

        # Fill end time
        if end:
            try:
                end_field = page.locator('input[aria-label*="End"]').first
                await end_field.fill(end)
            except Exception as e:
                logger.warning(f"[Outlook] End time issue: {e}")

        # Fill location
        if location:
            try:
                loc_field = page.locator('input[aria-label*="Location"]').first
                await loc_field.fill(location)
            except Exception as e:
                logger.warning(f"[Outlook] Location issue: {e}")

        # Save event
        try:
            save_btn = page.locator('button[aria-label*="Save"], button[aria-label*="done"]').first
            await save_btn.click()
            await asyncio.sleep(2)
            self.invalidate_cache()
            return ActionResult(success=True, data={"created": True, "title": title, "start": start})
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Could not save event: {e}")

    def _action_update_event(self, event_id: str, updates: dict, **kwargs) -> ActionResult:
        """Update a calendar event."""
        return ActionResult(success=False, error="Update event not yet implemented")

    def _action_delete_event(self, event_id: str, **kwargs) -> ActionResult:
        """Delete a calendar event."""
        return ActionResult(success=False, error="Delete event not yet implemented")

    def _action_find_meeting_time(self, attendees: list | None = None, duration: int = 60, **kwargs) -> ActionResult:
        """Find available meeting times."""
        return ActionResult(success=False, error="Find meeting time not yet implemented")

    async def _wait_for_loading(self, page, timeout: int = 10):
        """Wait for loading indicators to disappear."""
        try:
            loading = page.locator('[role="progressbar"], [aria-busy="true"]')
            if await loading.count() > 0:
                await loading.first.wait_for(state="hidden", timeout=timeout * 1000)
        except Exception:
            pass
        await asyncio.sleep(0.5)

    def save_session(self) -> bool:
        """Save current session."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return self._pw.save_session(self.SERVICE_NAME)
        except Exception as e:
            logger.error(f"[Outlook] Failed to save session: {e}")
            return False

    def restore_session(self) -> bool:
        """Restore saved session."""
        return self._pw.restore_session(self.SERVICE_NAME)

    def requires_approval(self, action: str, params: dict) -> tuple[bool, str]:
        """Check if action requires approval."""
        write_actions = {"send_email", "reply_email", "forward_email", "create_event", "update_event", "delete_event"}
        if action in write_actions:
            summary = f"{action.replace('_', ' ')}"
            if "to" in params:
                summary += f" to {params['to']}"
            if "subject" in params:
                summary += f" (subject: {params['subject']})"
            if "title" in params:
                summary += f": {params['title']}"
            return True, summary.capitalize()
        return False, ""
