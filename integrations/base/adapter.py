"""
Base integration adapter abstract class.
All service adapters inherit from this, providing a consistent interface.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .cache import IntegrationCache
from .exceptions import IntegrationError, ServiceError
from .playwright_manager import PlaywrightManager

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health status for an integration."""

    healthy: bool = False
    last_check: datetime | None = None
    error: str | None = None
    session_active: bool = False
    consecutive_failures: int = 0


@dataclass
class ActionResult:
    """Result of an action execution."""

    success: bool
    data: Any = None
    error: str | None = None
    requires_approval: bool = False
    approval_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "requires_approval": self.requires_approval,
            "approval_summary": self.approval_summary,
        }


class BaseIntegrationAdapter(ABC):
    """
    Abstract base class for all service integrations.

    Provides:
    - Shared Playwright browser instance
    - Response caching
    - Health status tracking
    - Approval workflow hooks
    - Consistent error handling
    """

    SERVICE_NAME: str = "base"
    DEFAULT_TIMEOUT: int = 30
    DEFAULT_CACHE_TTL: int = 300  # 5 minutes

    def __init__(self, session_dir: str = "config/sessions"):
        self._pw = PlaywrightManager.get_instance()
        self._cache = IntegrationCache(self.SERVICE_NAME, self.DEFAULT_CACHE_TTL)
        self._health = HealthStatus()
        self._session_dir = session_dir
        self._page = None

        logger.info(f"[{self.SERVICE_NAME}] Adapter initialized")

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """Return list of supported operations."""

    @abstractmethod
    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        """
        Execute an action. Override in subclasses.
        Must return ActionResult with success=True/False.
        """

    def execute(self, action: str, **kwargs) -> ActionResult:
        """
        Public execution method with caching and error handling.
        Checks cache first for read operations.
        """
        # Check if this action supports caching
        cache_key = self._make_cache_key(action, kwargs)
        if self._is_read_action(action) and cache_key:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[{self.SERVICE_NAME}] Cache hit for {action}")
                return ActionResult(success=True, data=cached)

        # Execute action
        try:
            result = self._execute_action(action, **kwargs)

            # Cache successful read operations
            if result.success and self._is_read_action(action) and cache_key:
                self._cache.set(cache_key, result.data)

            # Update health on success
            if result.success:
                self._health.consecutive_failures = 0

            return result

        except IntegrationError as e:
            logger.error(f"[{self.SERVICE_NAME}] {e}")
            self._health.consecutive_failures += 1
            return ActionResult(success=False, error=str(e))

        except Exception as e:
            logger.exception(f"[{self.SERVICE_NAME}] Unexpected error: {e}")
            self._health.consecutive_failures += 1
            return ActionResult(success=False, error=str(e))

    def execute_action(self, action: str, **kwargs):
        """
        High-level action dispatcher. Maps action name to _action_* method.
        Returns a human-readable result string for main.py.
        """
        method_name = f"_action_{action}"
        method = getattr(self, method_name, None)
        if method is None:
            return f"Unknown action: {action}"

        result = method(**kwargs)

        if isinstance(result, ActionResult):
            if result.success:
                if result.data:
                    if isinstance(result.data, dict):
                        if "error" in result.data:
                            return f"Error: {result.data['error']}"
                        parts = [f"{k}={v}" for k, v in result.data.items() if k not in ("success",)]
                        return ", ".join(parts) if parts else "Done."
                    return str(result.data)
                return "Done."
            return f"Failed: {result.error}" if result.error else "Operation failed."
        return str(result)

    def get_health(self) -> HealthStatus:
        """Return current health status."""
        return self._health

    def check_health(self) -> bool:
        """Check if the service is accessible."""
        try:
            healthy = self._is_session_active()
            self._health.healthy = healthy
            self._health.last_check = datetime.now()
            self._health.error = None if healthy else "Session not active"
            return healthy
        except Exception as e:
            self._health.healthy = False
            self._health.last_check = datetime.now()
            self._health.error = str(e)
            return False

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Clear cache entries."""
        if pattern:
            self._cache.invalidate_pattern(pattern)
        else:
            self._cache.clear()

    def requires_approval(self, action: str, params: dict) -> tuple[bool, str]:
        """
        Check if action requires user approval.
        Override in subclasses for service-specific rules.

        Returns: (requires_approval, summary_text)
        """
        write_actions = {
            "send", "create", "update", "delete", "reply", "forward",
            "send_message", "create_event", "update_event", "delete_event"
        }
        action_lower = action.lower()
        if any(action_lower.startswith(w) for w in write_actions):
            summary = f"{action}"
            if "to" in params:
                summary += f" to {params['to']}"
            if "subject" in params:
                summary += f" (subject: {params['subject']})"
            if "receiver" in params:
                summary += f" to {params['receiver']}"
            return True, summary
        return False, ""

    def save_session(self) -> bool:
        """Save current session state. Override in subclasses."""
        return False

    def restore_session(self) -> bool:
        """Restore session from saved state. Override in subclasses."""
        return False

    def _is_session_active(self) -> bool:
        """Check if session is active. Override in subclasses."""
        return False

    def _is_read_action(self, action: str) -> bool:
        """Check if action is a read-only operation."""
        read_actions = {"list", "get", "search", "read", "find"}
        action_lower = action.lower()
        return any(action_lower.startswith(r) for r in read_actions)

    def _make_cache_key(self, action: str, params: dict) -> str | None:
        """Create a cache key from action and parameters."""
        if not params:
            return action
        # Only cache read operations with simple params
        if self._is_read_action(action) and len(params) <= 3:
            parts = [action]
            for k, v in sorted(params.items()):
                if v is not None and k not in ("timeout", "wait"):
                    parts.append(f"{k}={v}")
            return ":".join(parts)
        return None

    def _get_page(self, service: str) -> Any:
        """Get or create a browser page for the service."""
        return self._pw.get_page(service)

    def _wait_for_element(
        self, page: Any, selector: str, timeout: int = 10, state: str = "visible"
    ) -> Any:
        """Wait for element helper."""
        try:
            return page.locator(selector).wait_for(state=state, timeout=timeout * 1000)
        except Exception as e:
            raise ServiceError(self.SERVICE_NAME, f"Element not found: {selector} ({e})")

    def _click_element(self, page: Any, selector: str, timeout: int = 10) -> None:
        """Click element helper."""
        element = self._wait_for_element(page, selector, timeout)
        element.click()

    def _fill_element(self, page: Any, selector: str, value: str, timeout: int = 10) -> None:
        """Fill input element helper."""
        element = self._wait_for_element(page, selector, timeout)
        element.fill(value)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} service={self.SERVICE_NAME}>"
