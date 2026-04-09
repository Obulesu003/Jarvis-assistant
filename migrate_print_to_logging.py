"""
migrate_print_to_logging.py
One-time migration: replace print() calls with structured logging.

Usage:
    python migrate_print_to_logging.py --dry-run
    python migrate_print_to_logging.py --apply

For files not modified by this script (custom integrations, etc.):
1. Add import at top of file:
       from core.logging_config import log_print as print, get_logger
   or:
       from core.logging_config import get_logger
       logger = get_logger(__name__)

2. Replace tagged print calls:
       logging.getLogger("Browser").debug("Connected")
       logging.getLogger("Error").info(f"Failed: {e}")
       logging.getLogger("WARN").info("Rate limited")

3. Remove print() calls that are just noise (progress indicators, etc.)
"""

import logging
import re
import sys
from pathlib import Path


DRY_RUN = "--dry-run" in sys.argv


def _log(*args, **kwargs):
    """Internal print replacement — uses stderr so stdout stays clean."""
    sep = kwargs.pop("sep", " ")
    end = kwargs.pop("end", "\n")
    kwargs.pop("file", None)
    kwargs.pop("flush", None)
    print(*args, sep=sep, end=end, file=sys.stderr)


def extract_tag(msg: str) -> tuple[str, str, str]:
    """Parse [TAG] [STATUS] pattern and return (tag, status, rest)."""
    tag = status = rest = ""
    m = re.match(r"^\[([A-Za-z]+)\]\s*", msg)
    if m:
        tag = m.group(1)
        rest = msg[m.end():]
        m2 = re.match(r"^\[([A-Za-z]+)\]\s*", rest)
        if m2:
            status = m2.group(1)
            rest = rest[m2.end():]
    else:
        rest = msg
    return tag, status, rest


def migrate_print_line(line: str) -> str:
    """
    Convert a single print() call to logger call.
    Handles: print("..."), print(f"..."), print(... + ...), print("[Tag] [Status] message")
    """
    # Match print( ...) with various args
    m = re.match(r'(\s*)print\((.*)\)$', line)
    if not m:
        return line

    indent = m.group(1)
    args_str = m.group(2)

    # Extract the format string (first positional arg, possibly f-string or string concat)
    first_str_match = re.search(r'(f?"[^"]*")', args_str)
    if not first_str_match:
        # Dynamic print — can't safely convert, use debug
        inner = args_str.rstrip(', ').rstrip(')')
        return f"{indent}logging.getLogger(__name__).debug({inner})"

    format_str = first_str_match.group(1)

    # Parse tag/status prefix from format string
    raw_msg = format_str.strip('f"\'`')
    tag, status, rest = extract_tag(raw_msg)

    # Determine log level from status
    level_map = {
        "FAIL": "error",
        "ERROR": "error",
        "WARN": "warning",
        "WARNING": "warning",
        "OK": "debug",
        "INFO": "info",
        "DEBUG": "debug",
    }
    level = level_map.get(status.upper(), "info")

    # Build new line
    logger_name = f'"{tag}"' if tag else "__name__"
    if rest.strip():
        return f"{indent}logging.getLogger({logger_name}).{level}({repr(rest.strip())})"
    else:
        return f"{indent}logging.getLogger({logger_name}).{level}({format_str})"


def migrate_file(filepath: Path) -> int:
    """Migrate print() calls in a single file. Returns count of changes."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        _log(f"[SKIP] {filepath}: {e}")
        return 0

    lines = content.split('\n')
    changed = []
    change_count = 0

    # Add import if not present
    needs_import = (
        "from core.logging_config import" not in content
        and "import logging" not in content
    )
    if needs_import:
        import_line = "import logging  # migrated from print()"
        # Find first import line
        for i, line in enumerate(lines):
            if line.startswith("import ") or line.startswith("from "):
                lines.insert(i, import_line)
                changed.append(i)
                break
        else:
            lines.insert(0, import_line)
            changed.append(0)

    for i, line in enumerate(lines):
        if re.match(r'\s*print\(', line):
            new_line = migrate_print_line(line)
            if new_line != line:
                changed.append(i)
                change_count += 1
                lines[i] = new_line

    if not change_count:
        return 0

    new_content = '\n'.join(lines)

    if DRY_RUN:
        _log(f"[DRYRUN] {filepath}: {change_count} migrations")
        if len(changed) > 5:
            _log(f"  ... and {len(changed) - 5} more changes")
    else:
        filepath.write_text(new_content, encoding="utf-8")
        _log(f"[MIGRATED] {filepath}: {change_count} migrations")

    return change_count


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate print() to logging")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", default=".", help="Root path to scan")
    parser.add_argument("--ext", default="*.py", help="File pattern")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    files = list(root.rglob(args.ext))
    # Exclude __pycache__ and hidden dirs
    files = [f for f in files if "__pycache__" not in str(f) and not any(p.startswith(".") for p in f.parts)]

    total = 0
    for f in files:
        total += migrate_file(f)

    _log(f"\nTotal: {total} print() calls in {len(files)} files")
    if DRY_RUN:
        _log("Run without --dry-run to apply changes")


if __name__ == "__main__":
    main()
