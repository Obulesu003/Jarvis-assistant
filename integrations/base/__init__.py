"""Base integration module."""
from .adapter import BaseIntegrationAdapter
from .cache import IntegrationCache
from .exceptions import (
    ElementNotFoundError,
    IntegrationError,
    RateLimitError,
    ServiceError,
    SessionExpiredError,
)
from .playwright_manager import PlaywrightManager

__all__ = [
    "BaseIntegrationAdapter",
    "ElementNotFoundError",
    "IntegrationCache",
    "IntegrationError",
    "PlaywrightManager",
    "RateLimitError",
    "ServiceError",
    "SessionExpiredError",
]
