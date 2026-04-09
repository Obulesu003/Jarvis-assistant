"""
UI integration for approval workflow.
Provides hooks for displaying approval requests in the Jarvis UI.
"""

import logging
from typing import TYPE_CHECKING

from .tier_classifier import ActionTier

if TYPE_CHECKING:
    from .workflow import ApprovalRequest

logger = logging.getLogger(__name__)


class ApprovalUI:
    """
    UI integration for approval workflow.

    This class provides methods to integrate with the existing
    JarvisUI (ui.py) for displaying approval requests.
    """

    def __init__(self, jarvis_ui=None):
        """
        Initialize UI integration.

        Args:
            jarvis_ui: Reference to JarvisUI instance
        """
        self._ui = jarvis_ui
        self._pending_approval_ids = []

    def set_ui(self, jarvis_ui) -> None:
        """Set the JarvisUI reference."""
        self._ui = jarvis_ui

    def show_approval_request(self, request: "ApprovalRequest") -> None:
        """
        Display approval request in UI.

        Args:
            request: ApprovalRequest to display
        """
        self._pending_approval_ids.append(request.id)

        if self._ui is None:
            logger.warning("[ApprovalUI] No UI attached, skipping display")
            return

        try:
            tier_emoji = {
                ActionTier.TIER_0_SILENT: "",
                ActionTier.TIER_1_INFO: "info",
                ActionTier.TIER_2_CONFIRM: "confirm",
                ActionTier.TIER_3_BLOCK: "block",
            }

            tier_name = tier_emoji.get(request.tier, "info")

            # Write to log
            self._ui.write_log(f"[{tier_name.upper()}] {request.summary}")

            # For TIER_2, wait for confirmation
            if request.tier == ActionTier.TIER_2_CONFIRM:
                self._ui.write_log(f"[CONFIRM] Waiting for your response... (timeout: {request.timeout_seconds}s)")

        except Exception as e:
            logger.error(f"[ApprovalUI] Failed to show request: {e}")

    def show_info_notification(self, summary: str) -> None:
        """
        Show an info notification (TIER 1 actions).

        Args:
            summary: What will happen
        """
        if self._ui is None:
            return

        try:
            self._ui.write_log(f"[INFO] {summary}")
            self._ui.write_log("[INFO] Proceeding automatically...")
        except Exception as e:
            logger.debug(f"[ApprovalUI] Info notification failed: {e}")

    def on_approval_response(self, request_id: str, approved: bool) -> None:
        """
        Called when user responds to an approval request.

        Args:
            request_id: The request ID
            approved: True if approved, False if denied
        """
        if request_id in self._pending_approval_ids:
            self._pending_approval_ids.remove(request_id)

        if self._ui is None:
            return

        try:
            status = "APPROVED" if approved else "DENIED"
            self._ui.write_log(f"[{status}] {'Proceeding with action.' if approved else 'Action cancelled.'}")
        except Exception as e:
            logger.debug(f"[ApprovalUI] Response notification failed: {e}")

    def hide_approval_request(self, request_id: str) -> None:
        """
        Hide/remove approval request from UI.

        Args:
            request_id: The request ID to hide
        """
        if request_id in self._pending_approval_ids:
            self._pending_approval_ids.remove(request_id)

    def get_pending_count(self) -> int:
        """Get number of pending approval requests."""
        return len(self._pending_approval_ids)

    def has_pending(self) -> bool:
        """Check if there are pending approval requests."""
        return len(self._pending_approval_ids) > 0


class TkinterApprovalDialog:
    """
    Tkinter-specific approval dialog implementation.
    Can be used as an alternative to in-line approval.
    """

    @staticmethod
    def show_confirm_dialog(title: str, message: str, timeout: int = 30) -> bool:
        """
        Show a blocking confirmation dialog.

        Args:
            title: Dialog title
            message: Dialog message
            timeout: Timeout in seconds

        Returns:
            True if approved, False if denied or timeout
        """
        try:
            from tkinter import messagebox

            return messagebox.askyesno(title, message)
        except Exception as e:
            logger.error(f"[ApprovalUI] Dialog failed: {e}")
            return False

    @staticmethod
    def show_info_toast(title: str, message: str, duration: int = 3) -> None:
        """
        Show a toast/info notification.

        Args:
            title: Toast title
            message: Toast message
            duration: Duration in seconds
        """
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()  # Hide main window

            # Create toast window
            toast = tk.Toplevel(root)
            toast.wm_overrideredirect(True)
            toast.wm_geometry("+100+100")

            # Position at bottom right
            screen_w = toast.winfo_screenwidth()
            screen_h = toast.winfo_screenheight()
            toast.wm_geometry(f"+{screen_w - 350}+{screen_h - 100}")

            tk.Label(
                toast,
                text=f"{title}\n{message}",
                bg="#333",
                fg="white",
                padx=15,
                pady=10,
                font=("Arial", 10),
            ).pack()

            # Auto-close after duration
            toast.after(duration * 1000, toast.destroy)
            toast.after((duration + 0.5) * 1000, root.destroy)

            root.mainloop()

        except Exception as e:
            logger.debug(f"[ApprovalUI] Toast failed: {e}")
