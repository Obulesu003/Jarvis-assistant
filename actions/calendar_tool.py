# actions/calendar_tool.py
# Calendar management via ICS file generation or Google Calendar API.
# Requires: google-api-python-client (pip install google-api-python-client)
#   OR:     free CalDAV approach with webcal URLs.
# ICS files can be imported into any calendar app (Google Calendar, Outlook, etc.)
# Token stored in config/api_keys.json as "google_calendar_token" (OAuth2 JSON).

import logging  # migrated from print()
import json
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

try:
    from google.auth import credentials as google_auth_creds
    from googleapiclient.discovery import build
    _GAPI_OK = True
except ImportError:
    _GAPI_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _get_gcalendar_token() -> dict | None:
    """Get Google Calendar OAuth token from config."""
    try:
        from core.api_key_manager import get_api_keys
        keys = get_api_keys()
        raw = keys.get("google_calendar_token")
        if raw and isinstance(raw, str):
            return json.loads(raw)
        return raw
    except Exception:
        pass
    try:
        cfg = BASE_DIR / "config" / "api_keys.json"
        if cfg.exists():
            raw = json.loads(cfg.read_text(encoding="utf-8")).get("google_calendar_token")
            if raw and isinstance(raw, str):
                return json.loads(raw)
            return raw
    except Exception:
        pass
    return None


def _save_gcalendar_token(token: dict):
    """Save Google Calendar OAuth token to config."""
    try:
        from core.api_key_manager import get_api_keys, save_api_keys
        keys = get_api_keys()
        keys["google_calendar_token"] = json.dumps(token)
        save_api_keys(keys)
        return
    except Exception:
        pass
    cfg = BASE_DIR / "config" / "api_keys.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding="utf-8"))
    data["google_calendar_token"] = json.dumps(token)
    cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_gcalendar_service():
    """Build Google Calendar service with OAuth2."""
    creds = _get_gcalendar_token()
    if not creds:
        return None
    try:
        creds_obj = google_auth_creds.Credentials.from_authorized_user_info(creds)
        if not creds_obj.valid:
            return None
        return build("calendar", "v3", credentials=creds_obj, static_dlls=False)
    except Exception:
        return None


def _build_ics_event(
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
    all_day: bool = False,
) -> str:
    """Build a valid ICS (iCalendar) string."""
    uid = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}@mark-jarvis"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MARK XXXV//J.A.R.V.I.S//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART{'DATE' if all_day else 'TZID'}:{start_iso.replace('-', '').replace(':', '')}",
        f"DTEND{'DATE' if all_day else 'TZID'}:{end_iso.replace('-', '').replace(':', '')}",
        f"SUMMARY:{title}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{description}")
    if location:
        lines.append(f"LOCATION:{location}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def _parse_dt(dt_str: str, days_offset: int = 0) -> datetime:
    """Parse a datetime string to a datetime object. Accepts natural language cues."""
    dt_str = dt_str.strip()
    now = datetime.now()

    # Try natural language shortcuts
    lower = dt_str.lower()
    if "tomorrow" in lower:
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    if "today" in lower:
        return now.replace(hour=9, minute=0, second=0, microsecond=0)
    if "next week" in lower:
        return (now + timedelta(weeks=1)).replace(hour=9, minute=0, second=0, microsecond=0)

    # Try common formats
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"]:
        try:
            d = datetime.strptime(dt_str, fmt)
            if fmt in ["%Y-%m-%d"]:
                d = d.replace(hour=9, minute=0)
            return d
        except ValueError:
            pass

    return now + timedelta(hours=1)


def _handle_list_events(params: dict, player) -> str:
    """List upcoming calendar events using Google Calendar API."""
    service = _get_gcalendar_service()
    if not service:
        return (
            "Google Calendar is not configured. "
            "Add your OAuth2 token to config/api_keys.json as 'google_calendar_token', sir. "
            "Alternatively, say 'Create a calendar event' and I'll generate an ICS file "
            "you can import into your calendar app."
        )

    days = int(params.get("days", 7))
    max_results = min(int(params.get("count", 10)), 50)
    try:
        now = datetime.utcnow().isoformat() + "Z"
        end = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=end,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return f"No events in the next {days} days, sir."
        lines = [f"Upcoming events (next {days} days):"]
        for ev in events:
            start = ev["start"].get("dateTime", ev["start"].get("date"))
            summary = ev.get("summary", "(no title)")
            loc = ev.get("location", "")
            loc_str = f" @ {loc}" if loc else ""
            lines.append(f"  {start}: {summary}{loc_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list events, sir: {e}"


def _handle_create_event(params: dict, player) -> str:
    """Create a calendar event. Tries Google Calendar API, falls back to ICS file."""
    title   = params.get("title", "").strip()
    start_s = params.get("start", "").strip()
    end_s   = params.get("end", "").strip()
    desc    = params.get("description", "").strip()
    loc     = params.get("location", "").strip()
    all_day = params.get("all_day", False)

    if not title:
        return "Please specify a 'title' for the event, sir."

    # Parse dates
    start_dt = _parse_dt(start_s) if start_s else datetime.now() + timedelta(hours=1)
    end_dt = _parse_dt(end_s) if end_s else start_dt + timedelta(hours=1)

    # Try Google Calendar API first
    service = _get_gcalendar_service()
    if service:
        try:
            event = {
                "summary": title,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
                "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "UTC"},
            }
            if desc:
                event["description"] = desc
            if loc:
                event["location"] = loc
            created = service.events().insert(calendarId="primary", body=event).execute()
            link = created.get("htmlLink", "")
            return (
                f"Event created, sir: '{title}' on {start_dt.strftime('%Y-%m-%d %H:%M')}. "
                f"Link: {link}"
            )
        except Exception as e:
            return f"Google Calendar API failed, sir: {e}. Falling back to ICS file..."

    # Fallback: generate ICS file
    start_iso = start_dt.strftime("%Y%m%dT%H%M%S")
    end_iso   = end_dt.strftime("%Y%m%dT%H%M%S")
    ics = _build_ics_event(title, start_iso, end_iso, desc, loc, all_day=bool(all_day))
    ics_path = BASE_DIR / "calendar_event.ics"
    ics_path.write_bytes(ics.encode("utf-8"))
    webbrowser.open(f"file://{ics_path}")
    return (
        f"ICS calendar event created for '{title}' on "
        f"{start_dt.strftime('%Y-%m-%d %H:%M')}, sir. "
        f"Open the file in your calendar app to import it."
    )


def _handle_quick_event(params: dict, player) -> str:
    """Create a quick event from natural language (e.g., 'Meeting tomorrow 3pm for 1 hour')."""
    natural = params.get("text", "").strip()
    if not natural:
        return "Please provide a natural language description, sir."

    # Quick parse: use Gemini to extract structured event data
    try:
        from core.api_key_manager import get_gemini_key as _get_gemini_key
    except ImportError:
        _get_gemini_key = None

    if _get_gemini_key and _get_gemini_key():
        try:
            from google.genai import Client
            from google.genai.types import GenerateContentConfig

            client = Client(api_key=_get_gemini_key())
            prompt = (
                f"Parse this natural language event description and extract: "
                f"title, start_datetime (as YYYY-MM-DD HH:MM), duration_minutes (integer), location (string), description (string). "
                f"Today is {datetime.now().strftime('%Y-%m-%d')}.\n\n"
                f"Description: {natural}\n\n"
                f"Respond ONLY as JSON: {{"
                f'"title":"...","start_datetime":"YYYY-MM-DD HH:MM","duration_minutes":60,'
                f'"location":"...","description":"..."'
                f'}}'
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt
            )
            data = json.loads(resp.text.strip())
            title  = data.get("title", natural)
            start  = data.get("start_datetime", "")
            dur    = int(data.get("duration_minutes", 60))
            loc    = data.get("location", "")
            desc   = data.get("description", "")
            if start:
                start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
                end_dt   = start_dt + timedelta(minutes=dur)
                params |= {"title": title, "start": start, "end": end_dt.strftime("%Y-%m-%d %H:%M"),
                           "location": loc, "description": desc}
            return _handle_create_event(params, player)
        except Exception:
            pass

    # Fallback without AI: create a placeholder ICS for tomorrow 9am
    start_dt = datetime.now() + timedelta(days=1)
    start_dt = start_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    end_dt   = start_dt + timedelta(hours=1)
    start_iso = start_dt.strftime("%Y%m%dT%H%M%S")
    end_iso   = end_dt.strftime("%Y%m%dT%H%M%S")
    ics = _build_ics_event(natural, start_iso, end_iso)
    ics_path = BASE_DIR / "calendar_event.ics"
    ics_path.write_bytes(ics.encode("utf-8"))
    return (
        f"Calendar event created for '{natural}' tomorrow at 9am, sir. "
        f"Import the ICS file into your calendar app."
    )


_CALENDAR_ACTIONS = {
    "list_events":  _handle_list_events,
    "create_event":  _handle_create_event,
    "quick_event":   _handle_quick_event,
}


def calendar_tool(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """
    Manage calendar events.

    parameters:
        action      : list_events | create_event | quick_event
        title       : Event title (for create_event)
        start       : Start datetime -- YYYY-MM-DD HH:MM or natural language (for create_event)
        end         : End datetime (optional, defaults to start + 1 hour)
        description : Event description (for create_event)
        location    : Event location (for create_event)
        all_day     : Boolean, all-day event (for create_event)
        text        : Natural language description (for quick_event)
        days        : How many days ahead to look (for list_events, default: 7)
        count       : Max number of events (for list_events, default: 10)
    """
    params  = parameters or {}
    action  = params.get("action", "list_events").lower().strip()

    if player:
        player.write_log(f"[Calendar] Action: {action}")

    logging.getLogger("Calendar").info(f"Action: {action}  Params: {params}")

    handler = _CALENDAR_ACTIONS.get(action)
    if handler is None:
        return (
            f"Unknown calendar action: '{action}'. "
            "Available: list_events, create_event, quick_event."
        )

    try:
        return handler(params, player)
    except Exception as e:
        logging.getLogger("Calendar").info(f"Error in {action}: {e}")
        return f"Calendar {action} failed, sir: {e}"
