# Full Automation Audit & Fix — Design Spec
**Date:** 2026-04-12
**Status:** Approved
**Scope:** 6 areas — E (orchestrator routing), D (HomeAssistant), F (Outlook stubs), A (Spotify), B (WhatsApp), C (Teams)

---

## Overview

Mark-XXXV has 8 integration adapters, but many actions inside them are unreachable via voice because the orchestrator's keyword router only covers a curated subset. Additionally, several adapters have stub methods or broken implementations. This spec covers fixing all 6 deficient areas.

---

## E — Orchestrator Routing Fix

### Problem
The `UniversalOrchestrator` uses a hardcoded keyword → action mapping. Many adapter actions (e.g., `read_clipboard`, `get_active_window`, `notepad_read`) exist but are never triggered because no keyword routes to them.

### Solution
1. **Auto-generate capability coverage** — inspect `adapter.get_capabilities()` at startup to build a complete action map
2. **Extend keyword router** — add keyword triggers for every `_action_*` method
3. **LLM fallback** — if no keyword matches, use Gemini to route to the best action

### Implementation
- `universal_orchestrator.py`: Add `build_capability_map()` that reads all `_action_*` methods
- Add keywords for: clipboard, window, active, notepad, teams_chat, get_running_apps
- LLM fallback via existing `orchestrate()` method when keyword routing yields no steps

### Files
- `integrations/core/universal_orchestrator.py`

---

## D — HomeAssistant Adapter

### Problem
`HomeAssistantAdapter` does not inherit `BaseIntegrationAdapter`, returns raw Python dicts instead of `ActionResult`, and is not registered in the orchestrator.

### Solution
Rewrite as a proper `BaseIntegrationAdapter` subclass with full `_execute_action` pattern.

### Capabilities
| Action | Description |
|--------|-------------|
| `get_state` | Get current state of any entity |
| `turn_on` | Turn on a device (light, switch, etc.) |
| `turn_off` | Turn off a device |
| `set_brightness` | Set light brightness 0-100 |
| `set_temperature` | Set thermostat temperature |
| `list_lights` | List all light entities |
| `list_switches` | List all switch entities |
| `list_climates` | List all climate/thermostat entities |
| `trigger_scene` | Activate a Home Assistant scene |

### Requirements
- `home_assistant.url` — Home Assistant server URL (e.g., `http://homeassistant:8123`)
- `home_assistant.token` — Long-lived access token
- Stored in `config/api_keys.json` or environment variables

### Implementation
- Rewrite class to inherit `BaseIntegrationAdapter`
- Implement `_execute_action` with HTTP REST calls to HA API
- Add `_action_*` methods for each capability
- Register in `main.py` `_get_orchestrator()`

### Files
- `integrations/home_assistant/home_assistant_adapter.py`
- `main.py` (register adapter)

---

## F — Outlook Native Stubs

### Problem
Three methods in `OutlookNativeAdapter` return "not yet implemented":
- `update_event`
- `delete_event`
- `find_meeting_time`

### Solution
Implement all three using Outlook COM API.

#### `update_event(event_id, updates)`
- Find the appointment by entry ID using `namespace.GetItemFromID()`
- Update fields: `Subject`, `Start`, `End`, `Location`, `Body`
- Call `.Save()` to persist changes

#### `delete_event(event_id)`
- Find appointment by entry ID
- Call `.Delete()` to remove from calendar

#### `find_meeting_time(attendees, duration)`
- Use `namespace.GetSharedDefaultFolder()` or Outlook's free/busy API
- Parse each attendee's calendar for the next available slot
- Return the first available time slot that fits `duration` minutes

### Files
- `integrations/outlook/outlook_native_adapter.py`

---

## A — Spotify / Media Deep Control

### Problem
We can search and play songs, but playlist control, queue management, volume, and now-playing info are missing.

### Solution
Use Spotify's deep-link URIs + pywinauto keyboard navigation for in-app control.

### New Capabilities
| Action | Description |
|--------|-------------|
| `play_playlist` | Open and play a Spotify playlist by name |
| `control_volume` | Volume up / down / mute via Spotify window |
| `skip_to_song` | Navigate to a song in current playlist and play it |
| `get_current_track` | Read now-playing from Spotify window title |

### Implementation
- Spotify URI scheme: `spotify:search:`, `spotify:playlist:`, `spotify:track:`
- For playlist control: open playlist via URI, then use pywinauto to navigate to first track
- Volume: use `VK_VOLUME_UP` (0xAF), `VK_VOLUME_DOWN` (0xAE), `VK_VOLUME_MUTE` (0xAD)
- Current track: parse `Spotify - Track Name` from window title via `GetWindowTextW`
- For skip-to-song: search within Spotify, arrow down to correct result, press Enter

### Files
- `integrations/system/system_adapter.py`

---

## B — WhatsApp Deep Automation

### Problem
Current WhatsApp adapter only supports basic text send. No group support, media, or chat reading.

### Solution
Use pywinauto to automate the WhatsApp desktop app (Windows Store version or EXE).

### New Capabilities
| Action | Description |
|--------|-------------|
| `send_message` | Send text to contact or group |
| `send_media` | Send image/video file to contact |
| `read_messages` | Read last N messages from a chat |
| `search_messages` | Search within WhatsApp |
| `mark_read` | Mark a chat as read |

### Implementation
1. **Search chat**: `pywinauto` — click search icon, type contact name, press Enter
2. **Send message**: click message input, type text, press Enter
3. **Send media**: click attach button, navigate file dialog, select file, send
4. **Read messages**: scroll up in chat, read message elements via UI inspection
5. **Mark read**: double-click chat or click read receipt icon

### Desktop App Detection
- Check for WhatsApp in Start Menu or `AppData\Local\Programs\WhatsApp`
- Fall back to WhatsApp Web if desktop not installed

### Files
- `integrations/whatsapp/whatsapp_adapter.py`

---

## C — Teams Deep Automation

### Problem
Current Teams support only sends basic messages. No meeting joining or channel reading.

### Solution
Use pywinauto to automate the Microsoft Teams desktop app.

### New Capabilities
| Action | Description |
|--------|-------------|
| `send_message` | Send message to Teams channel or DM |
| `join_meeting` | Find meeting by name/description and join |
| `read_messages` | Read recent messages from a channel |
| `get_meetings` | List today's upcoming Teams meetings |

### Implementation
1. **Join meeting**: Calendar view → search meeting name → click Join button
2. **Send channel message**: Navigate to channel → click compose → type → send
3. **Read messages**: Navigate to channel → scroll → read message bubbles
4. **Get meetings**: Calendar view → extract today's meeting cards

### Teams Window Detection
- Window title contains "Microsoft Teams"
- Use `pywinauto.Application(backend="uia")` for better element detection
- Fallback: Teams web app via browser

### Files
- `integrations/system/windows_app_adapter.py`

---

## Error Handling (All Areas)

### Standard Error Contract
Every `_action_*` method returns `ActionResult(success=bool, data=..., error=...)`:
- `success=True` with `data` on success
- `success=False` with `error=str(exc)` on any failure
- **No silent failures** — exceptions are caught, logged, and returned as errors

### Fallback Strategy
1. Try primary method (COM API, pywinauto, HTTP)
2. If it fails, try keyboard simulation (VK_MEDIA keys)
3. If all fail, return `ActionResult(success=False, error="...")` with a human-readable message

### Files
- All adapter files in `integrations/`

---

## Registration (All New Adapters)

Add to `main.py` `_get_orchestrator()`:
```python
# HomeAssistant (D)
if home_assistant_config:
    _orchestrator.register_adapter("homeassistant", HomeAssistantAdapter(
        url=home_assistant_config["url"],
        token=home_assistant_config["token"]
    ))
```

---

## Orchestrator Routes (New Keywords)

Add to `universal_orchestrator.py` keyword map:

| Keyword Pattern | Adapter | Action |
|---|---|---|
| `clipboard`, `copy`, `paste` | windows_app | read_clipboard / write_clipboard |
| `active window`, `what's open` | system | get_active_window |
| `notepad`, `open notepad` | windows_app | notepad_read |
| `light`, `turn on light`, `lights` | homeassistant | turn_on / turn_off |
| `temperature`, `thermostat`, `ac` | homeassistant | set_temperature |
| `playlist`, `play playlist` | system | play_playlist |
| `volume`, `louder`, `quieter` | system | control_volume |
| `whatsapp`, `send whatsapp` | whatsapp | send_message |
| `teams`, `teams message`, `teams channel` | windows_app | teams_send_message |
| `join meeting`, `teams meeting` | windows_app | teams_join_meeting |

---

## Dependencies

New Python packages may be needed:
- `pywinauto` — already used by WindowsAppAdapter
- `requests` — for HomeAssistant HTTP API (likely already installed)

Existing dependencies used:
- `win32com.client` — Outlook COM
- `psutil` — process listing
- `ctypes` — keyboard simulation
- `subprocess` — launching apps
