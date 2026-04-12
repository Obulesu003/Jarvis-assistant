# core/api_key_manager.py
# Centralized, encrypted API key storage.
# Uses Fernet symmetric encryption derived from a machine-specific key.

import logging  # migrated from print()
import base64
import contextlib
import hashlib
import json
import os
import sys
from getpass import getuser
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
CONFIG_DIR      = BASE_DIR / "config"
API_FILE_PLAIN  = CONFIG_DIR / "api_keys.json"
API_FILE_ENC    = CONFIG_DIR / "api_keys.enc"
KEY_FILE        = CONFIG_DIR / ".key"


def _get_machine_key() -> bytes:
    """
    Derives a consistent machine-specific key from hardware/OS details.
    Falls back to a generated key stored in KEY_FILE if unavailable.
    """
    # Try to get a unique machine identifier
    identifiers = []

    try:
        import uuid
        identifiers.append(str(uuid.getnode()))
    except Exception:
        pass

    with contextlib.suppress(Exception):
        identifiers.append(getuser())

    try:
        identifiers.append(os.environ.get("COMPUTERNAME", ""))
        identifiers.append(os.environ.get("USERDOMAIN", ""))
    except Exception:
        pass

    try:
        import platform
        identifiers.append(platform.node())
        identifiers.append(platform.system())
        identifiers.append(platform.machine())
    except Exception:
        pass

    raw = "|".join(identifiers).encode("utf-8")
    return hashlib.sha256(raw).digest()


def _get_fernet() -> "Fernet":
    """Returns a Fernet instance using the machine-specific key."""
    if not _CRYPTO_OK:
        msg = "cryptography library not installed. Run: pip install cryptography"
        raise RuntimeError(
            msg
        )

    # Generate/store a stable Fernet key derived from machine identity
    machine_key = _get_machine_key()
    # Fernet needs a URL-safe base64-encoded 32-byte key
    fernet_key = base64.urlsafe_b64encode(machine_key)
    return Fernet(fernet_key)


def _migrate_plaintext():
    """Migrate existing plaintext api_keys.json to encrypted format."""
    if API_FILE_PLAIN.exists() and not API_FILE_ENC.exists():
        try:
            with open(API_FILE_PLAIN, encoding="utf-8") as f:
                data = json.load(f)
            save_api_keys(data)
            # Backup plaintext (optional -- comment out to delete)
            backup = API_FILE_PLAIN.with_suffix(".json.bak")
            API_FILE_PLAIN.rename(backup)
            logging.getLogger(__name__).info(f'[API Key Manager] Migrated plaintext keys to encrypted format. Backup: {backup}')
        except Exception as e:
            logging.getLogger(__name__).info(f'[API Key Manager] Migration failed: {e}')


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_api_keys() -> dict:
    """
    Reads and decrypts API keys from the encrypted store.
    Falls back to plaintext file for backwards compatibility.
    """
    _ensure_config_dir()

    # Try encrypted first
    if API_FILE_ENC.exists():
        try:
            fernet = _get_fernet()
            with open(API_FILE_ENC, "rb") as f:
                encrypted = f.read()
            decrypted = fernet.decrypt(encrypted)
            return json.loads(decrypted.decode("utf-8"))
        except Exception as e:
            logging.getLogger(__name__).info(f'[API Key Manager] Decryption failed ({e}), trying plaintext...')

    # Fallback: plaintext (for existing installs)
    if API_FILE_PLAIN.exists():
        try:
            with open(API_FILE_PLAIN, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.getLogger(__name__).info(f'[API Key Manager] Could not read plaintext keys: {e}')

    return {}


def save_api_keys(keys: dict) -> None:
    """Encrypts and saves API keys to the secure store."""
    if not _CRYPTO_OK:
        # Fallback: save as plaintext
        _ensure_config_dir()
        with open(API_FILE_PLAIN, "w", encoding="utf-8") as f:
            json.dump(keys, f, indent=4)
        logging.getLogger(__name__).info('[API Key Manager] Warning: saving keys in plaintext (cryptography not installed)')
        return

    _ensure_config_dir()
    fernet = _get_fernet()
    data   = json.dumps(keys, indent=4).encode("utf-8")
    encrypted = fernet.encrypt(data)
    with open(API_FILE_ENC, "wb") as f:
        f.write(encrypted)

    # Remove plaintext if it exists (after successful encrypted write)
    if API_FILE_PLAIN.exists():
        with contextlib.suppress(Exception):
            API_FILE_PLAIN.unlink()


def get_gemini_key() -> str:
    """Convenience: returns just the Gemini API key."""
    keys = get_api_keys()
    return keys.get("gemini_api_key", "")


def is_configured() -> bool:
    """Returns True if a Gemini API key is present."""
    return bool(get_gemini_key().strip())


# Auto-migrate on first import
_migrate_plaintext()
