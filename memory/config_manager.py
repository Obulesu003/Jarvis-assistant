import logging  # migrated from print()
import json
import sys
from pathlib import Path

try:
    from core.api_key_manager import (
        get_api_keys,
        get_gemini_key,
        is_configured,
    )
    from core.api_key_manager import (
        save_api_keys as _save_keys,
    )
    _KEY_MANAGER_OK = True
except ImportError:
    _KEY_MANAGER_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    if _KEY_MANAGER_OK:
        return is_configured()
    return CONFIG_FILE.exists()


def save_api_keys(gemini_api_key: str) -> None:
    if _KEY_MANAGER_OK:
        _save_keys({"gemini_api_key": gemini_api_key.strip()})
    else:
        ensure_config_dir()
        data: dict = {}
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data["gemini_api_key"] = gemini_api_key.strip()
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_api_keys() -> dict:
    if _KEY_MANAGER_OK:
        return get_api_keys()
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logging.getLogger(__name__).info(f"Failed to load api_keys.json: {e}")
        return {}


def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")


def is_configured() -> bool:
    if _KEY_MANAGER_OK:
        return is_configured()
    key = get_gemini_key()
    return bool(key and len(key) > 15)
