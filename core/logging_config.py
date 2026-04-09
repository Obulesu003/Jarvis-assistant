# core/logging_config.py
# MARK XXV — Centralized structured logging.
# Replaces print() statements. Provides levels, structured output, file rotation.

import logging
import logging.handlers
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR      = get_base_dir()
LOG_DIR       = BASE_DIR / "logs"
LOG_FILE      = LOG_DIR / "jarvis.log"
LOG_MAX_BYTES = 5 * 1024 * 1024   # 5 MB per file
LOG_BACKUP_COUNT = 5
LOG_FORMAT    = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATEFMT   = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", to_file: bool = True, to_console: bool = True):
    """
    Configure root logger with file + console handlers.

    Args:
        level: DEBUG | INFO | WARNING | ERROR | CRITICAL
        to_file: write logs to logs/jarvis.log with rotation
        to_console: write logs to stderr (captured by IDE/debug tools)
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Prevent duplicate handlers on re-initialization
    if root.hasHandlers():
        root.handlers.clear()

    fmt = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    if to_file:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    if to_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger for the given module name.
    Usage: logger = get_logger(__name__)
           logger.info("User logged in", extra={"user_id": 42})
    """
    return logging.getLogger(name)


# Convenience shorthand
def getLogger(name: str) -> logging.Logger:
    """Alias for get_logger (PEP8 lowercase)."""
    return get_logger(name)


# ── Auto-init on import ────────────────────────────────────────────────────────

try:
    setup_logging(level="INFO", to_file=True, to_console=True)
except Exception:
    # Fallback: basic config if logs dir not writable
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATEFMT,
    )


# ── Drop-in print() replacement ─────────────────────────────────────────────
# Use log_print() instead of print() for structured output.
# Supports all print() args (sep, end, file, flush) for easy migration.

def log_print(*args, level: str = "INFO", **kwargs) -> None:
    """
    Structured print() replacement. Routes through logging.

    Usage:
        log_print("User logged in", extra={"user_id": 42})
        log_print("Download started", level="DEBUG")
        log_print("[Browser] [OK] Connected")  # strips [tag] prefix automatically

    In existing code, replace: print(f"[Browser] [OK] Connected")
    With: log_print("[Browser] [OK] Connected", tag="Browser", status="OK")
    """
    if not args:
        return

    # Auto-detect tagged print: log_print("[Browser] [OK] Connected")
    # Strip the [TAG] [STATUS] prefix and use it for structured context
    first_arg = str(args[0])
    context = {}

    import re
    tag_match = re.match(r"^\[([A-Za-z]+)\]\s*", first_arg)
    if tag_match:
        context["tag"] = tag_match.group(1)
        args = (first_arg[tag_match.end():],) + args[1:]

    status_match = re.match(r"^\[([A-Za-z]+)\]\s*", str(args[0]))
    if tag_match and status_match:
        context["status"] = status_match.group(1)
        args = (args[0][status_match.end():],) + args[1:]

    # Build message from remaining args
    sep = kwargs.pop("sep", " ")
    end = kwargs.pop("end", "\n")
    flush = kwargs.pop("flush", False)
    message = sep.join(str(a) for a in args) + end

    message = message.rstrip("\n")

    if not message:
        return

    logger = logging.getLogger(context.get("tag", "jarvis"))
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.log(log_level, message)

    if flush:
        for h in logger.handlers:
            h.flush()


# ── Backward-compatible print alias (for easy search-replace) ─────────────────

# In files using print(), add this import:
#   from core.logging_config import print as log_print, get_logger
# Then find-replace: print(f"[Foo] → log_print(f"[Foo]

