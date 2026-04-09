"""
Native Windows Outlook integration via COM (pywin32).
Uses the actual installed Outlook application with all existing sessions and emails.
No browser needed - direct Outlook COM API.
"""

import logging
from datetime import datetime, timedelta

from ..base.adapter import ActionResult, BaseIntegrationAdapter

logger = logging.getLogger(__name__)


class OutlookNativeAdapter(BaseIntegrationAdapter):
    """
    Native Outlook integration using Windows COM API.

    Uses the installed Outlook application directly:
    - Full access to all folders, emails, calendar
    - Uses existing Outlook session (already logged in)
    - No browser or web login needed
    - Much faster than web automation

    Requires: pip install pywin32
    """

    SERVICE_NAME = "outlook_native"
    DEFAULT_TIMEOUT = 30
    DEFAULT_CACHE_TTL = 60  # Cache for 1 minute

    def __init__(self):
        super().__init__()
        self._outlook = None
        self._namespace = None
        self._connected = False
        logger.info("[Outlook Native] Adapter initialized")

    def _connect(self) -> bool:
        """Connect to running Outlook instance via COM."""
        if self._connected and self._outlook:
            try:
                # Test connection by accessing namespace
                _ = self._namespace
                return True
            except Exception:
                self._connected = False

        try:
            import win32com.client
            self._outlook = win32com.client.Dispatch("Outlook.Application")
            self._namespace = self._outlook.GetNamespace("MAPI")
            self._connected = True
            logger.info("[Outlook Native] Connected to Outlook")
            return True
        except ImportError:
            logger.error("[Outlook Native] pywin32 not installed. Run: pip install pywin32")
            return False
        except Exception as e:
            logger.error(f"[Outlook Native] Failed to connect: {e}")
            self._connected = False
            return False

    def get_capabilities(self) -> list[str]:
        return [
            "get_inbox_count",
            "get_unread_count",
            "list_emails",
            "search_emails",
            "read_email",
            "send_email",
            "reply_email",
            "forward_email",
            "delete_email",
            "list_calendar_events",
            "create_calendar_event",
        ]

    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        method_name = f"_action_{action}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            try:
                return method(**kwargs)
            except Exception as e:
                logger.exception(f"[Outlook Native] {action} failed: {e}")
                return ActionResult(success=False, error=str(e))
        return ActionResult(success=False, error=f"Unknown action: {action}")

    # ------------------------------------------------------------------ #
    # Counts                                                              #
    # ------------------------------------------------------------------ #

    def _action_get_unread_count(self, folder: str = "Inbox", **kwargs) -> ActionResult:
        """Get unread email count for a folder."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        try:
            inbox = self._namespace.Folders[self._get_inbox_name()].Folders[folder]
            count = inbox.UnReadItemCount
            return ActionResult(success=True, data={"folder": folder, "unread": count})
        except Exception as e:
            # Try default inbox
            try:
                inbox = self._namespace.GetDefaultFolder(6)  # 6 = olFolderInbox
                count = inbox.UnReadItemCount
                return ActionResult(success=True, data={"folder": "Inbox", "unread": count})
            except Exception:
                return ActionResult(success=False, error=str(e))

    def _action_get_inbox_count(self, folder: str = "Inbox", **kwargs) -> ActionResult:
        """Get total email count for a folder."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        try:
            inbox = self._namespace.Folders[self._get_inbox_name()].Folders[folder]
            total = inbox.Items.Count
            unread = inbox.UnReadItemCount
            return ActionResult(success=True, data={"folder": folder, "total": total, "unread": unread})
        except Exception as e:
            try:
                inbox = self._namespace.GetDefaultFolder(6)
                return ActionResult(
                    success=True,
                    data={"folder": "Inbox", "total": inbox.Items.Count, "unread": inbox.UnReadItemCount},
                )
            except Exception:
                return ActionResult(success=False, error=str(e))

    def _get_inbox_name(self) -> str:
        """Get the default inbox folder name (handles non-English Outlook)."""
        try:
            inbox = self._namespace.GetDefaultFolder(6)
            return inbox.Name
        except Exception:
            return "Inbox"

    # ------------------------------------------------------------------ #
    # Email listing & search                                              #
    # ------------------------------------------------------------------ #

    def _action_list_emails(self, folder: str = "Inbox", max_results: int = 20, unread_only: bool = False, **kwargs) -> ActionResult:
        """List emails in a folder."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        try:
            # Get the default inbox folder
            inbox = self._namespace.GetDefaultFolder(6)
            # If a subfolder is specified, navigate to it
            if folder.lower() != "inbox":
                try:
                    inbox = inbox.Folders[folder]
                except Exception:
                    return ActionResult(success=False, error=f"Subfolder '{folder}' not found")
        except Exception as e:
            return ActionResult(success=False, error=f"Could not access folder '{folder}': {e}")

        try:
            items = inbox.Items
            items.Sort("[ReceivedTime]", True)  # Newest first

            emails = []
            count = 0
            for item in items:
                try:
                    if unread_only and not item.UnRead:
                        continue

                    emails.append({
                        "id": str(item.EntryID),
                        "subject": getattr(item, "Subject", "(no subject)"),
                        "sender": str(getattr(item, "SenderName", getattr(item, "SenderEmailAddress", "?"))),
                        "received": str(item.ReceivedTime) if hasattr(item, "ReceivedTime") else "",
                        "unread": getattr(item, "UnRead", False),
                        "has_attachments": getattr(item, "Attachments", None) is not None and item.Attachments.Count > 0,
                        "preview": getattr(item, "Body", "")[:150].replace("\r\n", " ").strip() if hasattr(item, "Body") else "",
                    })
                    count += 1
                    if count >= max_results:
                        break
                except Exception:
                    continue

            return ActionResult(success=True, data={"folder": folder, "emails": emails, "count": len(emails)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_search_emails(self, query: str = "", max_results: int = 20, folder: str = "Inbox", **kwargs) -> ActionResult:
        """Search emails by subject, sender, or content."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not query:
            return ActionResult(success=False, error="Specify a search query")

        try:
            # Get the default inbox folder
            inbox = self._namespace.GetDefaultFolder(6)
            # If a subfolder is specified, navigate to it
            if folder.lower() != "inbox":
                try:
                    inbox = inbox.Folders[folder]
                except Exception:
                    return ActionResult(success=False, error=f"Subfolder '{folder}' not found")
            items = inbox.Items
            items.Sort("[ReceivedTime]", True)

            # Simple substring search across subject and sender
            query_lower = query.lower()
            results = []

            for item in items:
                try:
                    subject = getattr(item, "Subject", "").lower()
                    sender = str(getattr(item, "SenderName", "")).lower()
                    body = getattr(item, "Body", "").lower()

                    if query_lower in subject or query_lower in sender or query_lower in body:
                        results.append({
                            "id": str(item.EntryID),
                            "subject": getattr(item, "Subject", "(no subject)"),
                            "sender": str(getattr(item, "SenderName", "?")),
                            "received": str(item.ReceivedTime) if hasattr(item, "ReceivedTime") else "",
                            "unread": getattr(item, "UnRead", False),
                            "preview": getattr(item, "Body", "")[:150].replace("\r\n", " ").strip() if hasattr(item, "Body") else "",
                        })
                        if len(results) >= max_results:
                            break
                except Exception:
                    continue

            return ActionResult(success=True, data={"query": query, "results": results, "count": len(results)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_read_email(self, email_id: str = "", mark_read: bool = True, **kwargs) -> ActionResult:
        """Read a specific email by entry ID."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not email_id:
            return ActionResult(success=False, error="Specify email_id to read")

        try:
            item = self._namespace.GetItemFromID(email_id)
            if item is None:
                return ActionResult(success=False, error="Email not found")

            # Mark as read
            if mark_read and item.UnRead:
                item.UnRead = False
                item.Save()

            body = getattr(item, "Body", "") or ""
            getattr(item, "HTMLBody", "") or ""

            # Get attachments
            attachments = []
            try:
                for att in item.Attachments:
                    attachments.append({"name": att.FileName, "size": att.Size})
            except Exception:
                pass

            # Get recipients
            to_recipients = []
            cc_recipients = []
            try:
                for r in item.Recipients:
                    if r.Type == 1:  # olTo
                        to_recipients.append(r.Name)
                    elif r.Type == 2:  # olCC
                        cc_recipients.append(r.Name)
            except Exception:
                pass

            email_data = {
                "id": str(item.EntryID),
                "subject": getattr(item, "Subject", "(no subject)"),
                "sender": str(getattr(item, "SenderName", "?")),
                "sender_email": getattr(item, "SenderEmailAddress", ""),
                "to": ", ".join(to_recipients),
                "cc": ", ".join(cc_recipients),
                "received": str(item.ReceivedTime) if hasattr(item, "ReceivedTime") else "",
                "sent": str(item.SentOn) if hasattr(item, "SentOn") else "",
                "unread": getattr(item, "UnRead", False),
                "importance": str(getattr(item, "Importance", 1)),  # 0=Low, 1=Normal, 2=High
                "body": body,
                "body_preview": body[:500].replace("\r\n", " ").strip(),
                "attachments": attachments,
            }
            return ActionResult(success=True, data=email_data)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Sending                                                             #
    # ------------------------------------------------------------------ #

    def _action_send_email(
        self,
        to: str = "",
        subject: str = "",
        body: str = "",
        cc: str = "",
        bcc: str = "",
        attachments: list | None = None,
        **kwargs,
    ) -> ActionResult:
        """Send a new email."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not to or not subject:
            return ActionResult(success=False, error="Specify 'to' and 'subject'")

        try:
            mail = self._outlook.CreateItem(0)  # 0 = olMailItem

            mail.To = to
            mail.Subject = subject
            mail.Body = body
            if cc:
                mail.CC = cc
            if bcc:
                mail.BCC = bcc

            # Add attachments
            if attachments:
                for path in attachments:
                    try:
                        mail.Attachments.Add(path)
                    except Exception as e:
                        logger.warning(f"[Outlook Native] Attachment failed: {e}")

            mail.Send()
            self.invalidate_cache()
            logger.info(f"[Outlook Native] Email sent to {to}")
            return ActionResult(success=True, data={"sent": True, "to": to, "subject": subject})
        except Exception as e:
            return ActionResult(success=False, error=f"Failed to send email: {e}")

    def _action_reply_email(self, email_id: str = "", body: str = "", reply_all: bool = False, **kwargs) -> ActionResult:
        """Reply to an email."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not email_id:
            return ActionResult(success=False, error="Specify email_id to reply to")

        try:
            original = self._namespace.GetItemFromID(email_id)
            if original is None:
                return ActionResult(success=False, error="Original email not found")

            reply = original.ReplyAll() if reply_all else original.Reply()
            reply.Body = (body or "") + ("\n\n" if body else "") + "---"
            reply.Display()  # Show the reply window (user can review and send)
            return ActionResult(success=True, data={"replied": True, "subject": getattr(original, "Subject", "")})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_forward_email(self, email_id: str = "", to: str = "", body: str = "", **kwargs) -> ActionResult:
        """Forward an email."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not email_id or not to:
            return ActionResult(success=False, error="Specify email_id and 'to'")

        try:
            original = self._namespace.GetItemFromID(email_id)
            if original is None:
                return ActionResult(success=False, error="Original email not found")

            forward = original.Forward()
            forward.To = to
            forward.Body = (body or "") + "\n\n--- Original ---\n" + getattr(original, "Body", "")[:500]
            forward.Display()
            return ActionResult(success=True, data={"forwarded": True, "to": to})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_delete_email(self, email_id: str = "", **kwargs) -> ActionResult:
        """Move an email to Deleted Items."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not email_id:
            return ActionResult(success=False, error="Specify email_id to delete")

        try:
            item = self._namespace.GetItemFromID(email_id)
            if item is None:
                return ActionResult(success=False, error="Email not found")

            item.Delete()
            self.invalidate_cache()
            return ActionResult(success=True, data={"deleted": True})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    # ------------------------------------------------------------------ #
    # Calendar                                                            #
    # ------------------------------------------------------------------ #

    def _action_list_calendar_events(
        self,
        start_date: str = "",
        end_date: str = "",
        max_results: int = 20,
        **kwargs,
    ) -> ActionResult:
        """List calendar events."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        try:
            calendar = self._namespace.GetDefaultFolder(9)  # 9 = olFolderCalendar
            items = calendar.Items
            items.Sort("[Start]")
            items.IncludeRecurrences = True

            # Default: next 7 days
            start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now()

            end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else start + timedelta(days=7)

            items = items.Restrict(f"[Start] >= '{start.strftime('%m/%d/%Y')}' AND [Start] <= '{end.strftime('%m/%d/%Y 11:59 PM')}'")

            events = []
            for item in items:
                try:
                    events.append({
                        "id": str(item.EntryID),
                        "title": getattr(item, "Subject", "No title"),
                        "start": str(item.Start) if hasattr(item, "Start") else "",
                        "end": str(item.End) if hasattr(item, "End") else "",
                        "location": getattr(item, "Location", ""),
                        "body": getattr(item, "Body", "")[:200] if hasattr(item, "Body") else "",
                        "all_day": getattr(item, "AllDayEvent", False),
                        "busy": getattr(item, "BusyStatus", 0) == 2,
                    })
                    if len(events) >= max_results:
                        break
                except Exception:
                    continue

            return ActionResult(success=True, data={"events": events, "count": len(events)})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_create_calendar_event(
        self,
        title: str = "",
        start: str = "",
        end: str = "",
        location: str = "",
        body: str = "",
        all_day: bool = False,
        reminder: int = 15,
        **kwargs,
    ) -> ActionResult:
        """Create a calendar event."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not title or not start:
            return ActionResult(success=False, error="Specify 'title' and 'start'")

        try:
            appt = self._outlook.CreateItem(1)  # 1 = olAppointmentItem
            appt.Subject = title
            appt.Start = start
            if end:
                appt.End = end
            appt.Location = location
            appt.Body = body
            appt.AllDayEvent = all_day
            if reminder > 0:
                appt.ReminderMinutesBeforeStart = reminder
            appt.Save()
            self.invalidate_cache()
            return ActionResult(success=True, data={"created": True, "title": title, "start": start})
        except Exception as e:
            return ActionResult(success=False, error=str(e))
