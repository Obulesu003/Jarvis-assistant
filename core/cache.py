# core/cache.py
# TTL-based tool result cache to reduce redundant API calls.

import json
import threading
import time


# Per-tool TTLs in seconds
TOOL_TTLS: dict[str, int] = {
    "web_search":       300,   # 5 minutes
    "cmd_control":      60,   # 1 minute
    "file_controller":  120,   # 2 minutes
    "weather_report":   900,   # 15 minutes
    "flight_finder":    300,   # 5 minutes
}
DEFAULT_TTL = 30  # 30 seconds for unknown tools


def _get_tool_ttl(tool: str) -> int:
    """Get TTL for a specific tool."""
    return TOOL_TTLS.get(tool, DEFAULT_TTL)


# Simple in-memory cache: key = "tool:params_json"
_TOOL_CACHE: dict[str, tuple[str, float]] = {}  # key -> (result, timestamp)
_CACHE_LOCK = threading.Lock()
_CACHE_HITS = 0
_CACHE_MISSES = 0


def _make_cache_key(tool: str, params: dict) -> str:
    """Create a simple cache key from tool and sorted params."""
    canonical = json.dumps(params, sort_keys=True, default=str)
    return f"{tool}:{canonical}"


def get_cached_result(tool: str, params: dict) -> str | None:
    """
    Returns cached result if present and not expired, else None.
    Thread-safe.
    """
    global _CACHE_HITS, _CACHE_MISSES
    key = _make_cache_key(tool, params)
    ttl = _get_tool_ttl(tool)

    with _CACHE_LOCK:
        entry = _TOOL_CACHE.get(key)
        if entry is None:
            _CACHE_MISSES += 1
            return None

        result, timestamp = entry
        if time.time() - timestamp > ttl:
            # Expired
            del _TOOL_CACHE[key]
            _CACHE_MISSES += 1
            return None

        _CACHE_HITS += 1
        return result


def set_cached_result(tool: str, params: dict, result: str) -> None:
    """Stores a result in the cache with tool-specific TTL. Thread-safe."""
    key = _make_cache_key(tool, params)
    with _CACHE_LOCK:
        _TOOL_CACHE[key] = (result, time.time())


def invalidate_cache(tool: str | None = None, params: dict | None = None) -> None:
    """Invalidate specific entry, all entries for a tool, or all entries."""
    with _CACHE_LOCK:
        if tool is None and params is None:
            _TOOL_CACHE.clear()
        elif params is None:
            prefix = f"{tool}:"
            keys_to_delete = [k for k in _TOOL_CACHE if k.startswith(prefix)]
            for k in keys_to_delete:
                del _TOOL_CACHE[k]
        else:
            key = _make_cache_key(tool, params)
            _TOOL_CACHE.pop(key, None)


def cache_stats() -> dict:
    """Returns cache statistics."""
    with _CACHE_LOCK:
        total = _CACHE_HITS + _CACHE_MISSES
        hit_rate = (_CACHE_HITS / total * 100) if total > 0 else 0.0
        return {
            "hits":     _CACHE_HITS,
            "misses":   _CACHE_MISSES,
            "entries":  len(_TOOL_CACHE),
            "hit_rate": round(hit_rate, 1),
        }


def prune_expired_cache() -> int:
    """Removes all expired entries. Returns count of removed entries."""
    now = time.time()
    count = 0
    with _CACHE_LOCK:
        expired = []
        for key, (_, timestamp) in _TOOL_CACHE.items():
            ttl = _get_tool_ttl(key.split(":")[0])
            if now - timestamp > ttl:
                expired.append(key)
        for k in expired:
            del _TOOL_CACHE[k]
            count += 1
    return count


# Backward-compatible ToolCache class (still available for existing code)
class ToolCache:
    """
    Thread-safe in-memory TTL cache for tool results.
    Caches results by tool name + serialized parameters.
    Uses per-tool TTLs when available.
    """

    def __init__(self, ttl_seconds: int = 300):
        self._default_ttl = ttl_seconds
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _make_key(self, tool: str, params: dict) -> str:
        """Create a stable cache key from tool name and params."""
        return _make_cache_key(tool, params)

    def get(self, tool: str, params: dict) -> str | None:
        """Returns cached result if present and not expired, else None."""
        return get_cached_result(tool, params)

    def set(self, tool: str, params: dict, result: str) -> None:
        """Stores a result in the cache. Thread-safe."""
        set_cached_result(tool, params, result)

    def invalidate(self, tool: str | None = None, params: dict | None = None) -> None:
        """Invalidate specific entry or all entries for a tool."""
        invalidate_cache(tool, params)

    def stats(self) -> dict:
        """Returns cache statistics."""
        return cache_stats()

    def prune_expired(self) -> int:
        """Removes all expired entries. Returns count of removed entries."""
        return prune_expired_cache()


# Singleton instance
_cache: ToolCache | None = None
_init_lock = threading.Lock()


def get_cache() -> ToolCache:
    global _cache
    if _cache is None:
        with _init_lock:
            if _cache is None:
                _cache = ToolCache(ttl_seconds=300)
    return _cache
