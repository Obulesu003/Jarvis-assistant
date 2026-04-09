"""
Integration response cache.
Extends the core ToolCache with service-specific features.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class IntegrationCache:
    """
    Thread-safe TTL cache for integration responses.
    Extends the existing core ToolCache patterns.
    """

    def __init__(self, service_name: str, default_ttl: int = 300):
        self._service = service_name
        self._default_ttl = default_ttl
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        """Get cached value if not expired."""
        with self._lock:
            if key not in self._cache:
                return None

            value, expiry = self._cache[key]
            if datetime.now() > expiry:
                # Expired
                del self._cache[key]
                logger.debug(f"[{self._service}] Cache expired: {key}")
                return None

            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set cached value with TTL."""
        if ttl is None:
            ttl = self._default_ttl

        expiry = datetime.now() + timedelta(seconds=ttl)
        with self._lock:
            self._cache[key] = (value, expiry)
        logger.debug(f"[{self._service}] Cache set: {key} (TTL: {ttl}s)")

    def invalidate(self, key: str) -> None:
        """Remove a specific key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"[{self._service}] Cache invalidated: {key}")

    def invalidate_pattern(self, pattern: str) -> None:
        """Remove all keys matching pattern."""
        with self._lock:
            to_remove = [k for k in self._cache if pattern in k]
            for key in to_remove:
                del self._cache[key]
            if to_remove:
                logger.debug(f"[{self._service}] Cache invalidated {len(to_remove)} keys matching: {pattern}")

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.debug(f"[{self._service}] Cache cleared ({count} entries)")

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            now = datetime.now()
            active = sum(1 for _, exp in self._cache.values() if now <= exp)
            expired = len(self._cache) - active
            return {
                "service": self._service,
                "total_entries": len(self._cache),
                "active_entries": active,
                "expired_entries": expired,
            }
