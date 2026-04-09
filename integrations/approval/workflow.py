"""
Approval workflow orchestrator.
Manages the approval process for sensitive actions.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .tier_classifier import ActionTier, TierClassifier

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    """Represents a pending approval request."""
    id: str
    action: str
    params: dict
    tier: ActionTier
    summary: str
    timestamp: float
    timeout_seconds: int
    response: str | None = None  # "approved", "denied", "timeout", None
    response_timestamp: float | None = None
    responded_by: str | None = None  # "user", "auto", "system"

    def is_pending(self) -> bool:
        """Check if request is still pending."""
        return self.response is None

    def is_expired(self) -> bool:
        """Check if request has timed out."""
        if self.response is not None:
            return False
        return time.time() > (self.timestamp + self.timeout_seconds)


@dataclass
class ApprovalConfig:
    """Configuration for approval workflow."""
    tier0_auto_proceed: bool = True
    tier1_timeout: int = 5  # seconds
    tier2_timeout: int = 30  # seconds
    tier3_timeout: int = 0  # immediate block
    allow_blocked: bool = False
    notification_callback: Callable | None = None


class ApprovalWorkflow:
    """
    Manages the approval workflow for sensitive actions.

    Features:
    - Queue-based approval requests
    - Timeout handling with auto-expire
    - Multiple approval modes (silent, info, confirm, block)
    - Thread-safe operation
    - UI integration hooks
    """

    def __init__(self, config: dict | None = None, ui_integration=None):
        """
        Initialize approval workflow.

        Args:
            config: Approval configuration dict
            ui_integration: UI integration for displaying requests
        """
        self._config = ApprovalConfig(
            tier1_timeout=config.get("tier1_timeout_seconds", 5) if config else 5,
            tier2_timeout=config.get("tier2_timeout_seconds", 30) if config else 30,
            allow_blocked=(config or {}).get("allow_blocked_actions", False),
        )
        self._classifier = TierClassifier(config)
        self._ui = ui_integration
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._response_events: dict[str, threading.Event] = {}
        self._approval_callbacks: list[Callable] = []
        self._history: list[ApprovalRequest] = []
        self._max_history = 100

        logger.info("[Approval] Workflow initialized")

    def check_approval(self, action: str, params: dict | None = None) -> tuple[bool, str]:
        """
        Check if action requires approval.

        Returns:
            (approved, summary_or_error)
            - (True, "") if approved to proceed
            - (False, summary) if needs approval (call wait_for_response)
            - (False, error) if blocked
        """
        params = params or {}
        tier, summary = self._classifier.classify(action, params)

        self._classifier.get_tier_config(tier)

        # TIER 0: Silent, auto-proceed
        if tier == ActionTier.TIER_0_SILENT:
            self._log_action(action, params, tier, "auto-approved", "system")
            return True, ""

        # TIER 3: Blocked
        if tier == ActionTier.TIER_3_BLOCK:
            logger.warning(f"[Approval] Action blocked: {action}")
            return False, f"Action '{action}' is blocked for safety. Enable in settings to proceed."

        # TIER 1: Info mode, auto-proceed after timeout
        if tier == ActionTier.TIER_1_INFO:
            self._notify_user(action, params, tier, summary)
            self._log_action(action, params, tier, "auto-proceed", "auto")
            return True, summary

        # TIER 2: Require explicit confirmation
        self._create_request(action, params, tier, summary)
        return False, summary

    def wait_for_response(self, request_id: str, timeout: int | None = None) -> bool:
        """
        Wait for user response to an approval request.

        Returns:
            True if approved, False otherwise (denied or timeout)
        """
        event = self._response_events.get(request_id)
        if not event:
            return False

        with self._lock:
            request = self._pending.get(request_id)
            if not request:
                return False
            if timeout is None:
                timeout = request.timeout_seconds

        approved = event.wait(timeout=timeout)

        with self._lock:
            request = self._pending.get(request_id)
            if request and request.response is None:
                request.response = "timeout" if not approved else "approved"
                request.response_timestamp = time.time()
                request.responded_by = "auto" if not approved else "system"

                if not approved:
                    logger.info(f"[Approval] Request timed out: {request_id}")

        return approved

    def respond(self, request_id: str, approved: bool, by_user: bool = True) -> bool:
        """
        Record user response to an approval request.

        Args:
            request_id: The approval request ID
            approved: True for "yes", False for "no"
            by_user: True if response is from user, False if from system

        Returns:
            True if response was recorded, False if request not found
        """
        with self._lock:
            request = self._pending.get(request_id)
            if not request:
                return False

            request.response = "approved" if approved else "denied"
            request.response_timestamp = time.time()
            request.responded_by = "user" if by_user else "system"

            # Signal waiting thread
            event = self._response_events.get(request_id)
            if event:
                event.set()

        self._log_action(
            request.action,
            request.params,
            request.tier,
            request.response,
            request.responded_by,
        )

        # Notify UI
        if self._ui:
            try:
                self._ui.on_approval_response(request_id, approved)
            except Exception as e:
                logger.error(f"[Approval] UI notification failed: {e}")

        # Cleanup after delay
        threading.Timer(5.0, self._cleanup, args=[request_id]).start()

        return True

    def approve(self, request_id: str) -> bool:
        """Convenience method to approve a request."""
        return self.respond(request_id, True, by_user=True)

    def deny(self, request_id: str) -> bool:
        """Convenience method to deny a request."""
        return self.respond(request_id, False, by_user=True)

    def get_pending(self) -> list[ApprovalRequest]:
        """Get all pending approval requests."""
        with self._lock:
            return [r for r in self._pending.values() if r.is_pending()]

    def get_history(self, limit: int = 20) -> list[ApprovalRequest]:
        """Get approval history."""
        return self._history[-limit:]

    def cancel_all(self) -> int:
        """Cancel all pending requests."""
        count = 0
        with self._lock:
            for request in list(self._pending.values()):
                if request.is_pending():
                    self.respond(request.id, False, by_user=False)
                    count += 1
        return count

    def add_callback(self, callback: Callable) -> None:
        """Add a callback for approval events."""
        self._approval_callbacks.append(callback)

    def set_ui(self, ui_integration) -> None:
        """Set the UI integration."""
        self._ui = ui_integration

    def is_approved(self, action: str, params: dict | None = None) -> bool:
        """
        Convenience method: check and return approval in one call.
        For TIER_1 actions, this returns True (auto-proceed).
        For TIER_2 actions, this returns False (needs explicit confirmation).
        """
        approved, message = self.check_approval(action, params)
        if message and "blocked" in message.lower():
            return False
        return approved

    def _create_request(self, action: str, params: dict, tier: ActionTier, summary: str) -> str:
        """Create a new approval request."""
        request_id = f"{action}_{uuid.uuid4().hex[:8]}"

        # Get timeout from tier config
        tier_config = self._classifier.get_tier_config(tier)
        timeout = tier_config.get("timeout", 30)

        request = ApprovalRequest(
            id=request_id,
            action=action,
            params=params,
            tier=tier,
            summary=summary,
            timestamp=time.time(),
            timeout_seconds=timeout,
        )

        with self._lock:
            self._pending[request_id] = request
            self._response_events[request_id] = threading.Event()

        # Notify UI
        if self._ui:
            try:
                self._ui.show_approval_request(request)
            except Exception as e:
                logger.error(f"[Approval] UI notification failed: {e}")

        self._notify_callbacks(action, params, tier, summary)

        logger.info(f"[Approval] Created request: {request_id} ({action})")
        return request_id

    def _cleanup(self, request_id: str) -> None:
        """Remove processed request from pending."""
        with self._lock:
            request = self._pending.pop(request_id, None)
            self._response_events.pop(request_id, None)

            if request:
                self._history.append(request)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]

    def _notify_user(self, action: str, params: dict, tier: ActionTier, summary: str) -> None:
        """Notify user of action (TIER 1)."""
        if self._ui:
            try:
                self._ui.show_info_notification(summary)
            except Exception as e:
                logger.debug(f"[Approval] UI notification failed: {e}")

    def _notify_callbacks(self, action: str, params: dict, tier: ActionTier, summary: str) -> None:
        """Notify registered callbacks of approval request."""
        for callback in self._approval_callbacks:
            try:
                callback(action, params, tier, summary)
            except Exception as e:
                logger.error(f"[Approval] Callback failed: {e}")

    def _log_action(
        self, action: str, params: dict, tier: ActionTier, response: str, by: str
    ) -> None:
        """Log an action for audit trail."""
        logger.info(f"[Approval] {action} -> {response} (by={by}, tier={tier.display_name})")

    @property
    def classifier(self) -> TierClassifier:
        """Get the tier classifier."""
        return self._classifier
