# actions/email_tool.py
# Email management via SMTP or web-based approach.
# Requires: smtplib (built-in) + config/api_keys.json with smtp_* fields
# Or: use mailto: links to open the user's default mail client.

import logging  # migrated from print()
import json
import smtplib
import sys
import webbrowser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _get_email_config() -> dict:
    """Get email/SMTP config from api_keys.json."""
    try:
        from core.api_key_manager import get_api_keys
        keys = get_api_keys()
        return {
            "smtp_host":     keys.get("smtp_host", ""),
            "smtp_port":     keys.get("smtp_port", 587),
            "smtp_user":     keys.get("smtp_user", ""),
            "smtp_password": keys.get("smtp_password", ""),
            "from_address":  keys.get("email_address", ""),
            "provider":       keys.get("email_provider", ""),  # gmail | outlook | other
        }
    except Exception:
        pass
    try:
        cfg = BASE_DIR / "config" / "api_keys.json"
        if cfg.exists():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return {
                "smtp_host":     data.get("smtp_host", ""),
                "smtp_port":     data.get("smtp_port", 587),
                "smtp_user":     data.get("smtp_user", ""),
                "smtp_password": data.get("smtp_password", ""),
                "from_address":  data.get("email_address", ""),
                "provider":       data.get("email_provider", ""),
            }
    except Exception:
        pass
    return {"smtp_host": "", "smtp_port": 587, "smtp_user": "",
            "smtp_password": "", "from_address": "", "provider": ""}


def _is_configured() -> bool:
    cfg = _get_email_config()
    return bool(cfg.get("smtp_host") and cfg.get("smtp_user") and cfg.get("smtp_password"))


def _build_mailto(to: str, subject: str = "", body: str = "", cc: str = "") -> str:
    """Build a mailto: URL."""
    parts = []
    if to:
        parts.append(f"mailto:{to}")
    else:
        parts.append("mailto:")
    query = []
    if subject:
        query.append(f"subject={webbrowser.quote(subject)}")
    if body:
        query.append(f"body={webbrowser.quote(body)}")
    if cc:
        query.append(f"cc={webbrowser.quote(cc)}")
    if query:
        parts.append("?" + "&".join(query))
    return "".join(parts)


def _handle_send_email(params: dict, player) -> str:
    """Send an email via SMTP or mailto fallback."""
    to      = params.get("to", "").strip()
    subject = params.get("subject", "").strip()
    body    = params.get("body", "").strip()
    cc      = params.get("cc", "").strip()

    if not to:
        return "Please specify a 'to' address, sir."

    cfg = _get_email_config()

    if _is_configured():
        try:
            msg = MIMEMultipart()
            msg["From"] = cfg["from_address"]
            msg["To"]   = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc
            msg.attach(MIMEText(body, "plain"))

            port = int(cfg.get("smtp_port", 587))
            with smtplib.SMTP(cfg["smtp_host"], port, timeout=30) as server:
                server.ehlo()
                if port == 587:
                    server.starttls()
                    server.ehlo()
                server.login(cfg["smtp_user"], cfg["smtp_password"])
                recipients = [to] + ([cc] if cc else [])
                server.sendmail(cfg["from_address"], recipients, msg.as_string())
            return f"Email sent to {to}, sir."
        except Exception as e:
            return f"SMTP send failed: {e}. Falling back to mailto link..."

    # Fallback: open mailto link in default mail client
    url = _build_mailto(to, subject, body, cc)
    webbrowser.open(url)
    return (
        f"Opened your email client to send to {to}, sir. "
        f"Subject: '{subject}'. "
        f"Please review and send."
    )


def _handle_read_email(params: dict, player) -> str:
    """Simulate reading emails -- opens inbox in browser."""
    provider = _get_email_config().get("provider", "").lower()

    if not provider:
        # Try to detect from SMTP host
        cfg = _get_email_config()
        host = cfg.get("smtp_host", "").lower()
        if "gmail" in host or "google" in host:
            provider = "gmail"
        elif "outlook" in host or "hotmail" in host or "live" in host:
            provider = "outlook"
        elif "yahoo" in host:
            provider = "yahoo"

    inbox_urls = {
        "gmail":   "https://mail.google.com",
        "outlook": "https://outlook.live.com",
        "yahoo":   "https://mail.yahoo.com",
    }

    url = inbox_urls.get(provider, "https://mail.google.com")
    webbrowser.open(url)
    return f"Opened your email inbox, sir ({url})."


_EMAIL_ACTIONS = {
    "send":    _handle_send_email,
    "read":    _handle_read_email,
    "compose": _handle_send_email,  # alias
}


def email_tool(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Send or read emails.

    parameters:
        action   : send | read | compose
        to       : Recipient email address (for send/compose)
        subject  : Email subject (for send/compose)
        body     : Email body (for send/compose)
        cc       : CC recipient (optional, for send/compose)
    """
    params = parameters or {}
    action = params.get("action", "send").lower().strip()

    if player:
        player.write_log(f"[Email] Action: {action}")

    logging.getLogger("Email").info(f"Action: {action}  Params: {params}")

    handler = _EMAIL_ACTIONS.get(action)
    if handler is None:
        return f"Unknown email action: '{action}'. Available: send, read, compose."

    try:
        return handler(params, player)
    except Exception as e:
        logging.getLogger("Email").info(f"Error in {action}: {e}")
        return f"Email {action} failed, sir: {e}"
