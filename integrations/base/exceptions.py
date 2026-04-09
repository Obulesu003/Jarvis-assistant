"""
Integration exception hierarchy.
Provides consistent error handling across all service integrations.
"""


class IntegrationError(Exception):
    """Base exception for all integration errors."""

    def __init__(self, service: str, message: str, recoverable: bool = True):
        self.service = service
        self.recoverable = recoverable
        super().__init__(f"[{service}] {message}")

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/display."""
        return {
            "service": self.service,
            "message": str(self),
            "recoverable": self.recoverable,
            "type": self.__class__.__name__,
        }


class ServiceError(IntegrationError):
    """General service error (page not loading, element not found, etc.)."""

    def __init__(self, service: str, message: str):
        super().__init__(service, message, recoverable=True)


class SessionExpiredError(IntegrationError):
    """Session expired, user needs to log in again."""

    def __init__(self, service: str, message: str = "Session expired. Please log in again."):
        super().__init__(service, message, recoverable=True)


class ElementNotFoundError(ServiceError):
    """UI element not found on page."""

    def __init__(self, service: str, selector: str, timeout: float | None = None):
        msg = f"Element not found: {selector}"
        if timeout:
            msg += f" (timeout: {timeout}s)"
        super().__init__(service, msg)


class RateLimitError(IntegrationError):
    """Rate limited by service."""

    def __init__(self, service: str, message: str = "Rate limited. Please wait."):
        super().__init__(service, message, recoverable=True)


class ActionCancelledError(IntegrationError):
    """User cancelled the action."""

    def __init__(self, service: str, message: str = "Action cancelled by user."):
        super().__init__(service, message, recoverable=True)


class BrowserError(IntegrationError):
    """Browser automation error."""

    def __init__(self, service: str, message: str):
        super().__init__(service, message, recoverable=True)


class ContactNotFoundError(ServiceError):
    """Contact not found."""

    def __init__(self, service: str, identifier: str):
        super().__init__(service, f"Contact not found: {identifier}")


class EmailNotFoundError(ServiceError):
    """Email not found."""

    def __init__(self, service: str, email_id: str):
        super().__init__(service, f"Email not found: {email_id}")


class CalendarEventNotFoundError(ServiceError):
    """Calendar event not found."""

    def __init__(self, service: str, event_id: str):
        super().__init__(service, f"Calendar event not found: {event_id}")
