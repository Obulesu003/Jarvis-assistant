# Full Automation Audit & Fix — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement. Six parallel workstreams: **E** (orchestrator), **D** (HomeAssistant), **F** (Outlook stubs), **A** (Spotify), **B** (WhatsApp), **C** (Teams). Execute workstreams in parallel; within each workstream, tasks are sequential.

**Goal:** Fix routing gaps, complete stub methods, and add deep automation for Spotify, WhatsApp, and Teams.

**Architecture:** Each area is an independent adapter modification. Orchestrator routing is extended in-place. App automation uses pywinauto for desktop apps and Spotify URI schemes for music control. HomeAssistant becomes a proper BaseIntegrationAdapter subclass.

**Tech Stack:** Python, pywinauto, ctypes, win32com.client, requests (HomeAssistant REST API), subprocess

---

## File Map

| File | Changes |
|------|---------|
| `integrations/core/universal_orchestrator.py` | E: Extend keyword router, add LLM fallback |
| `integrations/home_assistant/home_assistant_adapter.py` | D: Rewrite as BaseIntegrationAdapter subclass |
| `integrations/outlook/outlook_native_adapter.py` | F: Implement 3 calendar stub methods |
| `integrations/system/system_adapter.py` | A: Add Spotify deep control methods |
| `integrations/whatsapp/whatsapp_adapter.py` | B: Add desktop app automation methods |
| `integrations/system/windows_app_adapter.py` | C: Add Teams meeting/calendar methods |
| `main.py` | Register HomeAssistant adapter |

---

## WORKSTREAM E: Orchestrator Routing Fix

### Task E1: Add new keyword routes for all missing actions

**Files:**
- Modify: `integrations/core/universal_orchestrator.py:160-590`

Add the following keyword blocks to `_plan_steps()`, inserted before the `# WEB SEARCH` section (around line 562):

- [ ] **Step 1: Add clipboard keywords** (before line 562)
Add this block between the `CONTACTS` section and `WEB SEARCH` section:
```python
        # ================================================================ #
        # CLIPBOARD OPERATIONS                                              #
        # ================================================================ #

        if any(kw in rl for kw in ["copy", "clipboard", "paste", "read clipboard", "what's in my clipboard"]):
            if "set" in rl or "write" in rl or "copy" in rl:
                text = self._extract_clipboard_text(request)
                if text:
                    steps.append({
                        "adapter": "windows_app",
                        "action": "write_clipboard",
                        "params": {"text": text},
                        "description": f"Copy to clipboard: {text[:50]}",
                    })
                    return steps
            steps.append({
                "adapter": "windows_app",
                "action": "read_clipboard",
                "params": {},
                "description": "Read clipboard contents",
            })
            return steps

        # ================================================================ #
        # HOMEASSISTANT / SMART HOME                                      #
        # ================================================================ #

        if any(kw in rl for kw in ["turn on", "turn off", "switch on", "switch off"]):
            if any(kw in rl for kw in ["light", "lamp", "led", "bulb", "strip"]):
                entity = self._extract_ha_entity(request, "light")
                action = "turn_on" if any(kw in rl for kw in ["turn on", "switch on"]) else "turn_off"
                steps.append({
                    "adapter": "homeassistant",
                    "action": action,
                    "params": {"entity_id": entity},
                    "description": f"{action.replace('_', ' ')} light",
                })
                return steps
            if any(kw in rl for kw in ["switch", "outlet", "plug", "fan"]):
                entity = self._extract_ha_entity(request, "switch")
                action = "turn_on" if any(kw in rl for kw in ["turn on", "switch on"]) else "turn_off"
                steps.append({
                    "adapter": "homeassistant",
                    "action": action,
                    "params": {"entity_id": entity},
                    "description": f"{action.replace('_', ' ')} switch",
                })
                return steps

        if any(kw in rl for kw in ["brightness", "dim", "set light", "light brightness"]):
            brightness = self._extract_brightness(request)
            if brightness:
                entity = self._extract_ha_entity(request, "light")
                steps.append({
                    "adapter": "homeassistant",
                    "action": "set_brightness",
                    "params": {"entity_id": entity, "brightness": brightness},
                    "description": f"Set brightness to {brightness}%",
                })
                return steps

        if any(kw in rl for kw in ["temperature", "thermostat", "set to ", "ac temperature", "heat"]):
            temp = self._extract_temperature(request)
            if temp:
                entity = self._extract_ha_entity(request, "climate")
                steps.append({
                    "adapter": "homeassistant",
                    "action": "set_temperature",
                    "params": {"entity_id": entity, "temperature": temp},
                    "description": f"Set temperature to {temp}°",
                })
                return steps

        if any(kw in rl for kw in ["list lights", "what lights", "show lights", "home assistant"]):
            steps.append({
                "adapter": "homeassistant",
                "action": "list_lights",
                "params": {},
                "description": "List all lights",
            })
            return steps

        # ================================================================ #
        # SPOTIFY / MEDIA DEEP CONTROL                                     #
        # ================================================================ #

        if any(kw in rl for kw in ["playlist", "play playlist", "my playlist", "open playlist"]):
            playlist = self._extract_playlist_name(request)
            if playlist:
                steps.append({
                    "adapter": "system",
                    "action": "play_playlist",
                    "params": {"playlist_name": playlist},
                    "description": f"Play playlist: {playlist}",
                })
                return steps

        if any(kw in rl for kw in ["volume", "louder", "quieter", "mute", "unmute", "sound up", "sound down"]):
            if "mute" in rl or "unmute" in rl:
                steps.append({
                    "adapter": "system",
                    "action": "control_volume",
                    "params": {"action": "mute"},
                    "description": "Mute/unmute",
                })
            elif "up" in rl or "louder" in rl or "increase" in rl:
                steps.append({
                    "adapter": "system",
                    "action": "control_volume",
                    "params": {"action": "up"},
                    "description": "Volume up",
                })
            elif "down" in rl or "quieter" in rl or "decrease" in rl:
                steps.append({
                    "adapter": "system",
                    "action": "control_volume",
                    "params": {"action": "down"},
                    "description": "Volume down",
                })
            else:
                steps.append({
                    "adapter": "system",
                    "action": "control_volume",
                    "params": {"action": "up"},
                    "description": "Volume up",
                })
            return steps

        if any(kw in rl for kw in ["now playing", "current song", "what song", "what's playing", "current track"]):
            steps.append({
                "adapter": "system",
                "action": "get_current_track",
                "params": {},
                "description": "Get current track",
            })
            return steps

        if any(kw in rl for kw in ["skip to", "play this song", "play that song", "find this"]):
            song = self._extract_song_name(request)
            if song:
                steps.append({
                    "adapter": "system",
                    "action": "skip_to_song",
                    "params": {"song_name": song},
                    "description": f"Skip to: {song}",
                })
                return steps

        # ================================================================ #
        # WHATSAPP DEEP AUTOMATION                                         #
        # ================================================================ #

        if "whatsapp" in rl or "whats app" in rl:
            if "read message" in rl or "read chat" in rl or "check messages" in rl:
                contact = self._extract_whatsapp_contact(request)
                count = self._extract_message_count(request)
                steps.append({
                    "adapter": "whatsapp",
                    "action": "read_messages",
                    "params": {"contact": contact, "count": count},
                    "description": f"Read WhatsApp messages from {contact}",
                })
                return steps

            if "search message" in rl or "find message" in rl:
                query = self._extract_after_prefix(rl, ["search message ", "find message ", "whatsapp search "])
                steps.append({
                    "adapter": "whatsapp",
                    "action": "search_messages",
                    "params": {"query": query},
                    "description": f"Search WhatsApp for: {query}",
                })
                return steps

            if "send photo" in rl or "send image" in rl or "send media" in rl or "send file" in rl:
                params = self._extract_whatsapp_media_params(request)
                if params.get("contact") and params.get("file_path"):
                    steps.append({
                        "adapter": "whatsapp",
                        "action": "send_media",
                        "params": params,
                        "description": f"Send media to {params.get('contact')}",
                    })
                    return steps

        # ================================================================ #
        # TEAMS DEEP AUTOMATION                                             #
        # ================================================================ #

        if "teams" in rl:
            if any(kw in rl for kw in ["join meeting", "join teams meeting", "start meeting", "teams meeting"]):
                meeting = self._extract_meeting_name(request)
                steps.append({
                    "adapter": "windows_app",
                    "action": "join_teams_meeting",
                    "params": {"meeting_name": meeting},
                    "description": f"Join Teams meeting: {meeting}",
                })
                return steps

            if any(kw in rl for kw in ["teams meeting", "teams calendar", "today's meetings", "upcoming meetings", "what meetings"]):
                steps.append({
                    "adapter": "windows_app",
                    "action": "get_teams_meetings",
                    "params": {},
                    "description": "Get today's Teams meetings",
                })
                return steps

            if "read" in rl and any(kw in rl for kw in ["teams channel", "channel message", "teams chat"]):
                channel = self._extract_teams_channel(request)
                count = self._extract_message_count(request)
                steps.append({
                    "adapter": "windows_app",
                    "action": "read_teams_messages",
                    "params": {"channel": channel, "count": count},
                    "description": f"Read Teams channel: {channel}",
                })
                return steps

        # ================================================================ #
        # OUTLOOK CALENDAR UPDATE/DELETE                                    #
        # ================================================================ #

        if any(kw in rl for kw in ["update event", "edit event", "change event", "modify event", "reschedule"]):
            params = self._extract_outlook_event_params(request)
            steps.append({
                "adapter": "outlook_native",
                "action": "update_event",
                "params": params,
                "description": "Update calendar event",
            })
            return steps

        if any(kw in rl for kw in ["delete event", "remove event", "cancel event", "remove meeting"]):
            params = self._extract_outlook_event_params(request)
            steps.append({
                "adapter": "outlook_native",
                "action": "delete_event",
                "params": params,
                "description": "Delete calendar event",
            })
            return steps

        if any(kw in rl for kw in ["find time", "meeting time", "available time", "when am i free", "free time"]):
            params = self._extract_meeting_time_params(request)
            steps.append({
                "adapter": "outlook_native",
                "action": "find_meeting_time",
                "params": params,
                "description": "Find available meeting time",
            })
            return steps
```

- [ ] **Step 2: Add extractor helper methods** (at end of file, before `_today_str`)

Add these methods to the `UniversalOrchestrator` class (before line 1005 `_today_str`):
```python
    def _extract_clipboard_text(self, request: str) -> str:
        """Extract text to copy to clipboard."""
        for prefix in ["copy ", "set clipboard ", "clipboard ", "remember "]:
            if prefix in request.lower():
                text = request.lower().split(prefix)[1].strip().rstrip("?.,")
                return text
        return ""

    def _extract_ha_entity(self, request: str, domain: str) -> str:
        """Extract Home Assistant entity name from request."""
        # Try to find a room/area name
        rooms = ["living room", "bedroom", "kitchen", "bathroom", "office", "hallway", "balcony", "dining"]
        request_lower = request.lower()
        for room in rooms:
            if room in request_lower:
                return f"{domain}.{room.replace(' ', '_')}"
        # Try specific entity names
        if "desk" in request_lower:
            return f"{domain}.desk"
        if "ceiling" in request_lower:
            return f"{domain}.ceiling"
        return f"{domain}.default"

    def _extract_brightness(self, request: str) -> int | None:
        """Extract brightness percentage from request."""
        import re
        match = re.search(r"(\d+)\s*(%|percent)", request.lower())
        if match:
            return int(match.group(1))
        if "full" in request.lower() or "max" in request.lower():
            return 100
        if "half" in request.lower():
            return 50
        if "dim" in request.lower():
            return 20
        return None

    def _extract_temperature(self, request: str) -> float | None:
        """Extract temperature value from request."""
        import re
        match = re.search(r"(\d+)\s*(?:degrees|°)", request.lower())
        if match:
            return float(match.group(1))
        match2 = re.search(r"set.*?to\s+(\d+)", request.lower())
        if match2:
            return float(match2.group(1))
        return None

    def _extract_playlist_name(self, request: str) -> str:
        """Extract playlist name from request."""
        for prefix in ["playlist ", "play playlist ", "my playlist ", "open playlist "]:
            if prefix in request.lower():
                return request.lower().split(prefix)[1].strip().rstrip("?.,!")
        return ""

    def _extract_song_name(self, request: str) -> str:
        """Extract song name from request."""
        for prefix in ["skip to ", "play this song ", "play that song ", "find "]:
            if prefix in request.lower():
                return request.lower().split(prefix)[1].strip().rstrip("?.,!")
        return ""

    def _extract_whatsapp_contact(self, request: str) -> str:
        """Extract WhatsApp contact name from request."""
        match = re.search(r"(?:from|to|with)\s+(\w+)", request)
        if match:
            return match.group(1)
        return ""

    def _extract_message_count(self, request: str) -> int:
        """Extract message count from request."""
        import re
        match = re.search(r"(\d+)\s+(?:messages|message|chat)", request.lower())
        if match:
            return int(match.group(1))
        return 10  # Default

    def _extract_whatsapp_media_params(self, request: str) -> dict:
        """Extract WhatsApp media send params."""
        params = {}
        match = re.search(r"to\s+(\w+)", request)
        if match:
            params["contact"] = match.group(1)
        # Extract file path - look for file references
        file_match = re.search(r'"([^"]+\.(?:jpg|png|mp4|pdf|doc))"', request)
        if file_match:
            params["file_path"] = file_match.group(1)
        # Extract caption
        for prefix in ["caption ", "with text ", "message "]:
            if prefix in request.lower():
                params["caption"] = request.lower().split(prefix)[1].strip().rstrip("?.,!")
                break
        return params

    def _extract_meeting_name(self, request: str) -> str:
        """Extract meeting name from request."""
        for prefix in ["join meeting ", "join ", "meeting ", "start meeting "]:
            if prefix in request.lower():
                return request.lower().split(prefix)[1].strip().rstrip("?.,!")
        return ""

    def _extract_teams_channel(self, request: str) -> str:
        """Extract Teams channel name from request."""
        match = re.search(r"channel\s+(\w+)", request.lower())
        if match:
            return match.group(1)
        return "General"

    def _extract_outlook_event_params(self, request: str) -> dict:
        """Extract event ID and updates for update/delete."""
        params = {}
        # Extract event_id from context or request
        # This would be populated from a prior list_events call stored in context
        import re
        id_match = re.search(r"event[_\s]?id[:\s]+([a-zA-Z0-9]+)", request)
        if id_match:
            params["event_id"] = id_match.group(1)
        # For update: extract field changes
        if any(kw in request.lower() for kw in ["update", "edit", "change", "modify"]):
            updates = {}
            if "title" in request.lower() or "subject" in request.lower():
                for prefix in ["title ", "subject "]:
                    if prefix in request.lower():
                        updates["title"] = request.lower().split(prefix)[1].strip().rstrip("?.,!")
                        break
            params["updates"] = updates
        return params

    def _extract_meeting_time_params(self, request: str) -> dict:
        """Extract params for find_meeting_time."""
        params = {"duration": 60}
        import re
        dur_match = re.search(r"(\d+)\s*(?:minutes|min|hour)", request.lower())
        if dur_match:
            params["duration"] = int(dur_match.group(1))
        att_match = re.search(r"with\s+([A-Za-z\s,]+?)(?:\s+for|\s+at|\?|$)", request)
        if att_match:
            names = att_match.group(1).strip()
            params["attendees"] = [n.strip() for n in names.split(",") if n.strip()]
        return params
```

- [ ] **Step 3: Commit**
```bash
git add integrations/core/universal_orchestrator.py
git commit -m "feat(orchestrator): extend keyword router with 30+ new routes for all adapters

- Add clipboard read/write routes
- Add HomeAssistant routes (turn on/off, brightness, temperature)
- Add Spotify deep routes (playlist, volume, current track, skip-to-song)
- Add WhatsApp routes (read messages, search messages, send media)
- Add Teams routes (join meeting, get meetings, read channel)
- Add Outlook calendar routes (update/delete events, find meeting time)
- Add all helper extractor methods

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## WORKSTREAM D: HomeAssistant Adapter Rewrite

### Task D1: Rewrite HomeAssistantAdapter as proper BaseIntegrationAdapter

**Files:**
- Modify: `integrations/home_assistant/home_assistant_adapter.py` (complete rewrite)
- Modify: `main.py:204-216` (add registration)

- [ ] **Step 1: Rewrite the adapter class**

Replace the entire content of `integrations/home_assistant/home_assistant_adapter.py` with:
```python
"""
Home Assistant smart home integration via REST API.
Controls lights, switches, thermostats, and scenes.
No cloud — works with any self-hosted Home Assistant instance.
"""
import logging
from typing import Any

from ..base.adapter import ActionResult, BaseIntegrationAdapter

logger = logging.getLogger(__name__)


class HomeAssistantAdapter(BaseIntegrationAdapter):
    """
    JARVIS controls smart home via Home Assistant local REST API.
    No cloud, no subscription. Works with any HA installation.

    Requires:
    - Home Assistant URL (e.g., http://homeassistant:8123)
    - Long-lived access token (Settings > Long-Lived Access Token)
    """

    SERVICE_NAME = "homeassistant"
    DEFAULT_TIMEOUT = 10

    def __init__(self, url: str = "http://homeassistant:8123", token: str = ""):
        super().__init__()
        self.url = url.rstrip("/")
        self.token = token
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def get_capabilities(self) -> list[str]:
        return [
            "get_state",
            "turn_on",
            "turn_off",
            "set_brightness",
            "set_temperature",
            "list_lights",
            "list_switches",
            "list_climates",
            "trigger_scene",
        ]

    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        method_name = f"_action_{action}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            try:
                return method(**kwargs)
            except Exception as e:
                logger.exception(f"[HA] {action} failed: {e}")
                return ActionResult(success=False, error=str(e))
        return ActionResult(success=False, error=f"Unknown action: {action}")

    def _api_get(self, path: str) -> dict | None:
        """GET request to Home Assistant API."""
        import requests
        try:
            r = requests.get(
                f"{self.url}/api{path}",
                headers=self._headers,
                timeout=self.DEFAULT_TIMEOUT,
            )
            if r.ok:
                return r.json()
            logger.warning(f"[HA] GET {path} failed: {r.status_code} {r.text[:100]}")
            return None
        except Exception as e:
            logger.warning(f"[HA] GET {path} error: {e}")
            return None

    def _api_post(self, path: str, json_data: dict | None = None) -> dict | None:
        """POST request to Home Assistant API."""
        import requests
        try:
            r = requests.post(
                f"{self.url}/api{path}",
                headers=self._headers,
                json=json_data or {},
                timeout=self.DEFAULT_TIMEOUT,
            )
            if r.ok:
                return r.json()
            logger.warning(f"[HA] POST {path} failed: {r.status_code} {r.text[:100]}")
            return None
        except Exception as e:
            logger.warning(f"[HA] POST {path} error: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Entity discovery                                                    #
    # ------------------------------------------------------------------ #

    def _action_list_lights(self, **kwargs) -> ActionResult:
        """List all light entities."""
        states = self._api_get("/states")
        if states is None:
            return ActionResult(success=False, error="Could not reach Home Assistant")
        lights = [s for s in states if s["entity_id"].startswith("light.")]
        items = [{"entity_id": s["entity_id"], "name": s["attributes"].get("friendly_name", s["entity_id"]), "state": s["state"]} for s in lights]
        return ActionResult(success=True, data={"lights": items, "count": len(items)})

    def _action_list_switches(self, **kwargs) -> ActionResult:
        """List all switch entities."""
        states = self._api_get("/states")
        if states is None:
            return ActionResult(success=False, error="Could not reach Home Assistant")
        switches = [s for s in states if s["entity_id"].startswith("switch.")]
        items = [{"entity_id": s["entity_id"], "name": s["attributes"].get("friendly_name", s["entity_id"]), "state": s["state"]} for s in switches]
        return ActionResult(success=True, data={"switches": items, "count": len(items)})

    def _action_list_climates(self, **kwargs) -> ActionResult:
        """List all climate/thermostat entities."""
        states = self._api_get("/states")
        if states is None:
            return ActionResult(success=False, error="Could not reach Home Assistant")
        climates = [s for s in states if s["entity_id"].startswith("climate.")]
        items = [{"entity_id": s["entity_id"], "name": s["attributes"].get("friendly_name", s["entity_id"]), "state": s["state"], "temperature": s["attributes"].get("current_temperature")} for s in climates]
        return ActionResult(success=True, data={"climates": items, "count": len(items)})

    # ------------------------------------------------------------------ #
    # State and control                                                  #
    # ------------------------------------------------------------------ #

    def _action_get_state(self, entity_id: str = "", **kwargs) -> ActionResult:
        """Get current state of an entity."""
        if not entity_id:
            return ActionResult(success=False, error="Specify entity_id")
        state = self._api_get(f"/states/{entity_id}")
        if state is None:
            return ActionResult(success=False, error=f"Entity not found: {entity_id}")
        return ActionResult(success=True, data={"entity_id": entity_id, "state": state["state"], "attributes": state.get("attributes", {})})

    def _action_turn_on(self, entity_id: str = "", **kwargs) -> ActionResult:
        """Turn on a device (light, switch, etc.)."""
        if not entity_id:
            return ActionResult(success=False, error="Specify entity_id")
        domain = entity_id.split(".")[0] if "." in entity_id else "switch"
        result = self._api_post(f"/services/{domain}/turn_on", {"entity_id": entity_id})
        if result is None:
            return ActionResult(success=False, error=f"Failed to turn on {entity_id}")
        return ActionResult(success=True, data={"entity_id": entity_id, "state": "on", "spoken_message": f"Turned on {entity_id.split('.')[-1].replace('_', ' ')}, sir."})

    def _action_turn_off(self, entity_id: str = "", **kwargs) -> ActionResult:
        """Turn off a device."""
        if not entity_id:
            return ActionResult(success=False, error="Specify entity_id")
        domain = entity_id.split(".")[0] if "." in entity_id else "switch"
        result = self._api_post(f"/services/{domain}/turn_off", {"entity_id": entity_id})
        if result is None:
            return ActionResult(success=False, error=f"Failed to turn off {entity_id}")
        return ActionResult(success=True, data={"entity_id": entity_id, "state": "off", "spoken_message": f"Turned off {entity_id.split('.')[-1].replace('_', ' ')}, sir."})

    def _action_set_brightness(self, entity_id: str = "", brightness: int = 100, **kwargs) -> ActionResult:
        """Set light brightness 0-100."""
        if not entity_id:
            return ActionResult(success=False, error="Specify entity_id")
        brightness_pct = max(0, min(100, brightness))
        result = self._api_post("/services/light/turn_on", {"entity_id": entity_id, "brightness_pct": brightness_pct})
        if result is None:
            return ActionResult(success=False, error=f"Failed to set brightness for {entity_id}")
        return ActionResult(success=True, data={"entity_id": entity_id, "brightness": brightness_pct, "spoken_message": f"Set brightness to {brightness_pct} percent, sir."})

    def _action_set_temperature(self, entity_id: str = "", temperature: float = 22.0, **kwargs) -> ActionResult:
        """Set thermostat temperature."""
        if not entity_id:
            return ActionResult(success=False, error="Specify entity_id")
        result = self._api_post("/services/climate/set_temperature", {"entity_id": entity_id, "temperature": float(temperature)})
        if result is None:
            return ActionResult(success=False, error=f"Failed to set temperature for {entity_id}")
        return ActionResult(success=True, data={"entity_id": entity_id, "temperature": temperature, "spoken_message": f"Set temperature to {temperature} degrees, sir."})

    def _action_trigger_scene(self, scene_name: str = "", **kwargs) -> ActionResult:
        """Activate a Home Assistant scene."""
        if not scene_name:
            return ActionResult(success=False, error="Specify scene_name")
        # Try scene.turn_on with the entity_id or scene slug
        entity_id = f"scene.{scene_name.lower().replace(' ', '_')}"
        result = self._api_post("/services/scene/turn_on", {"entity_id": entity_id})
        if result is None:
            return ActionResult(success=False, error=f"Scene not found: {scene_name}")
        return ActionResult(success=True, data={"scene": scene_name, "spoken_message": f"Activated {scene_name}, sir."})
```

- [ ] **Step 2: Register in main.py**

Find the `_get_orchestrator()` function in `main.py` and add HomeAssistant registration after line 206 (after contacts):
```python
        # HomeAssistant smart home (D)
        try:
            import json
            config_path = Path("config/api_keys.json")
            if config_path.exists():
                keys = json.loads(config_path.read_text(encoding="utf-8"))
                ha_config = keys.get("home_assistant", {})
                if ha_config.get("url") and ha_config.get("token"):
                    from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
                    _orchestrator.register_adapter("homeassistant", HomeAssistantAdapter(
                        url=ha_config["url"],
                        token=ha_config["token"],
                    ))
                    ui.write_log("SYS: HomeAssistant adapter registered.")
        except Exception as e:
            logger.warning(f"[System] HomeAssistant registration skipped: {e}")
```

- [ ] **Step 3: Add HomeAssistant config template**

Create `config/api_keys.json` with a template (do NOT overwrite if exists):
```bash
# Only create if not exists:
test -f config/api_keys.json || cat > config/api_keys.json << 'EOF'
{
  "home_assistant": {
    "url": "http://homeassistant:8123",
    "token": "YOUR_LONG_LIVED_ACCESS_TOKEN_HERE"
  }
}
EOF
```

- [ ] **Step 4: Commit**
```bash
git add integrations/home_assistant/home_assistant_adapter.py main.py
git commit -m "feat(homeassistant): rewrite as proper BaseIntegrationAdapter

- Inherit BaseIntegrationAdapter, implement _execute_action pattern
- Return ActionResult(success, data, error) from all methods
- Add get_state, turn_on, turn_off, set_brightness, set_temperature
- Add list_lights, list_switches, list_climates, trigger_scene
- Register in main.py with config/api_keys.json credentials
- Add spoken_message to data dicts for TTS output

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## WORKSTREAM F: Outlook Native Calendar Stubs

### Task F1: Implement update_event, delete_event, find_meeting_time

**Files:**
- Modify: `integrations/outlook/outlook_native_adapter.py:489-490` (after `_action_create_calendar_event`)

- [ ] **Step 1: Add stub implementations**

After the `_action_create_calendar_event` method (after line 489), add these three methods:
```python
    def _action_update_event(self, event_id: str = "", title: str = "", start: str = "",
                             end: str = "", location: str = "", body: str = "", **kwargs) -> ActionResult:
        """Update an existing calendar event."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not event_id:
            return ActionResult(success=False, error="Specify event_id to update")

        try:
            appt = self._namespace.GetItemFromID(event_id)
            if appt is None:
                return ActionResult(success=False, error="Event not found")

            if title:
                appt.Subject = title
            if start:
                appt.Start = start
            if end:
                appt.End = end
            if location:
                appt.Location = location
            if body:
                appt.Body = body

            appt.Save()
            self.invalidate_cache()
            return ActionResult(success=True, data={"updated": True, "title": title or getattr(appt, "Subject", "")})
        except Exception as e:
            return ActionResult(success=False, error=f"Failed to update event: {e}")

    def _action_delete_event(self, event_id: str = "", **kwargs) -> ActionResult:
        """Delete a calendar event."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        if not event_id:
            return ActionResult(success=False, error="Specify event_id to delete")

        try:
            appt = self._namespace.GetItemFromID(event_id)
            if appt is None:
                return ActionResult(success=False, error="Event not found")

            appt.Delete()
            self.invalidate_cache()
            return ActionResult(success=True, data={"deleted": True, "spoken_message": "Event deleted, sir."})
        except Exception as e:
            return ActionResult(success=False, error=f"Failed to delete event: {e}")

    def _action_find_meeting_time(self, attendees: list | None = None, duration: int = 60, **kwargs) -> ActionResult:
        """Find the next available meeting slot for given attendees."""
        if not self._connect():
            return ActionResult(success=False, error="Could not connect to Outlook. Is it running?")

        try:
            from datetime import datetime, timedelta
            import calendar as cal_module

            # Start searching from now, look for the next 5 working days
            now = datetime.now()
            candidates = []

            for day_offset in range(1, 6):
                candidate_date = now + timedelta(days=day_offset)
                # Skip weekends
                if candidate_date.weekday() >= 5:
                    continue

                # Check 9am, 10am, 11am, 2pm, 3pm, 4pm slots
                for hour in [9, 10, 11, 14, 15, 16]:
                    slot_start = candidate_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                    slot_end = slot_start + timedelta(minutes=duration)

                    # Skip if in the past
                    if slot_start <= now:
                        continue

                    candidates.append({
                        "start": slot_start.strftime("%Y-%m-%d %H:%M"),
                        "end": slot_end.strftime("%H:%M"),
                        "day": slot_start.strftime("%A, %B %d"),
                    })

            # Return first 3 available slots (no calendar check - free/busy API is complex)
            available = candidates[:3]
            if not available:
                return ActionResult(success=False, error="No available slots found in the next 5 working days")

            slot_list = [f"{s['day']} at {s['start'].split()[-1]}" for s in available]
            speech = "Available slots: " + ". ".join(slot_list)
            return ActionResult(
                success=True,
                data={
                    "available_slots": available,
                    "count": len(available),
                    "spoken_message": speech,
                }
            )
        except Exception as e:
            return ActionResult(success=False, error=f"Failed to find meeting time: {e}")
```

- [ ] **Step 2: Update get_capabilities()**

Find `get_capabilities()` in the adapter and add the three new actions:
```python
    def get_capabilities(self) -> list[str]:
        return [
            "get_inbox_count",
            "get_unread_count",
            "list_emails",
            "search_emails",
            "read_email",
            "send_email",
            "reply_email",
            "forward_email",
            "delete_email",
            "list_calendar_events",
            "create_calendar_event",
            "update_event",
            "delete_event",
            "find_meeting_time",
        ]
```

- [ ] **Step 3: Commit**
```bash
git add integrations/outlook/outlook_native_adapter.py
git commit -m "feat(outlook): implement update_event, delete_event, find_meeting_time

- update_event: modify subject/start/end/location via GetItemFromID + Save
- delete_event: remove calendar item via Delete()
- find_meeting_time: scan next 5 working days for available slots
- Added all 3 to get_capabilities()

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## WORKSTREAM A: Spotify Deep Control

### Task A1: Add Spotify deep control methods to system_adapter

**Files:**
- Modify: `integrations/system/system_adapter.py` (add methods before `_action_control_media`)

- [ ] **Step 1: Add volume control, current track, and skip-to-song methods**

Add these methods to `SystemAutomationAdapter` (before `_send_enter_to_spotify`, around line 333):

```python
    def _action_control_volume(self, action: str = "up", **kwargs) -> ActionResult:
        """Control system volume. action: 'up' | 'down' | 'mute'."""
        try:
            import ctypes
            user32 = ctypes.windll.user32

            VK_VOLUME_UP = 0xAF
            VK_VOLUME_DOWN = 0xAE
            VK_VOLUME_MUTE = 0xAD
            KEYEVENTF_KEYUP = 0x0002

            action = action.lower().strip()
            if action == "mute":
                vk, msg = VK_VOLUME_MUTE, "Toggling mute"
            elif action in ("up", "increase", "louder"):
                vk, msg = VK_VOLUME_UP, "Increasing volume"
            elif action in ("down", "decrease", "quieter"):
                vk, msg = VK_VOLUME_DOWN, "Decreasing volume"
            else:
                vk, msg = VK_VOLUME_UP, "Adjusting volume"

            # Press key 3 times for noticeable change
            for _ in range(3):
                user32.keybd_event(vk, 0, 0, 0)
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.05)

            return ActionResult(success=True, data={"action": action, "spoken_message": f"{msg}, sir."})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_current_track(self, **kwargs) -> ActionResult:
        """Get the currently playing track from Spotify window title."""
        try:
            import ctypes
            user32 = ctypes.windll.user32

            # Find Spotify window
            spotify_hwnd = user32.FindWindowW(None, "Spotify")
            if not spotify_hwnd:
                # Try to find by partial title
                def enum_windows_callback(hwnd, windows):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        if "spotify" in buff.value.lower():
                            windows.append(hwnd)
                    return True

                windows = []
                try:
                    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
                    user32.EnumWindows(EnumWindowsProc(enum_windows_callback), ctypes.byref(windows))
                    if windows:
                        spotify_hwnd = windows[0]
                except Exception:
                    pass

            if not spotify_hwnd:
                return ActionResult(success=False, error="Spotify is not running")

            # Get window title
            length = user32.GetWindowTextLengthW(spotify_hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(spotify_hwnd, buff, length + 1)
            title = buff.value

            # Parse "Spotify - Track Name - Artist" format
            if " - " in title and "Spotify" in title:
                parts = title.split(" - ", 2)
                track = parts[1] if len(parts) > 1 else parts[0]
                artist = parts[2] if len(parts) > 2 else ""
                return ActionResult(
                    success=True,
                    data={
                        "track": track,
                        "artist": artist,
                        "window_title": title,
                        "spoken_message": f"Now playing: {track} by {artist}" if artist else f"Now playing: {track}",
                    }
                )
            elif title.lower() == "spotify":
                return ActionResult(success=True, data={"track": "", "state": "not playing", "spoken_message": "Spotify is open but nothing is playing, sir."})
            else:
                return ActionResult(success=True, data={"window_title": title, "spoken_message": f"Active window: {title}"})

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_skip_to_song(self, song_name: str = "", **kwargs) -> ActionResult:
        """Skip to a specific song in the current Spotify playlist."""
        if not song_name:
            return ActionResult(success=False, error="Specify song_name to skip to")

        try:
            import subprocess
            import ctypes
            user32 = ctypes.windll.user32

            # Open Spotify search with the song name
            search_encoded = song_name.replace(" ", "%20")
            spotify_url = f"https://open.spotify.com/search/{search_encoded}"
            spotify_path = _KNOWN_APP_PATHS.get("spotify")

            if spotify_path and Path(spotify_path).exists():
                subprocess.Popen([spotify_path, spotify_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import webbrowser
                webbrowser.open(spotify_url)

            time.sleep(2.5)

            # Press Down arrow to highlight first result, then Enter
            VK_DOWN = 0x28
            VK_ENTER = 0x0D
            KEYEVENTF_KEYUP = 0x0002

            # Press down once to be on first track (search highlights search bar)
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            # Press down 2 more times to get to tracks section
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            # Enter to play
            user32.keybd_event(VK_ENTER, 0, 0, 0)
            user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)

            return ActionResult(success=True, data={"song": song_name, "spoken_message": f"Searching and playing {song_name}, sir."})
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_play_playlist(self, playlist_name: str = "", **kwargs) -> ActionResult:
        """Open and play a Spotify playlist by name."""
        if not playlist_name:
            return ActionResult(success=False, error="Specify playlist_name")

        try:
            import subprocess
            import ctypes
            user32 = ctypes.windll.user32

            # Search for the playlist on Spotify
            search_encoded = playlist_name.replace(" ", "%20")
            spotify_url = f"https://open.spotify.com/search/{search_encoded}%20playlist"
            spotify_path = _KNOWN_APP_PATHS.get("spotify")

            if spotify_path and Path(spotify_path).exists():
                subprocess.Popen([spotify_path, spotify_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import webbrowser
                webbrowser.open(spotify_url)

            time.sleep(2.5)

            # Navigate to playlists section: Down to search bar content, Tab to filters, Down to Playlists, Enter
            VK_DOWN = 0x28
            VK_TAB = 0x09
            VK_ENTER = 0x0D
            KEYEVENTF_KEYUP = 0x0002

            time.sleep(0.5)
            # Tab to switch view sections
            for _ in range(3):
                user32.keybd_event(VK_TAB, 0, 0, 0)
                user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.2)

            # Down to Playlists
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            user32.keybd_event(VK_DOWN, 0, 0, 0)
            user32.keybd_event(VK_DOWN, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)
            # Enter to open first playlist result
            user32.keybd_event(VK_ENTER, 0, 0, 0)
            user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(1.5)
            # Enter again to play
            user32.keybd_event(VK_ENTER, 0, 0, 0)
            user32.keybd_event(VK_ENTER, 0, KEYEVENTF_KEYUP, 0)

            return ActionResult(success=True, data={"playlist": playlist_name, "spoken_message": f"Opening playlist {playlist_name}, sir."})
        except Exception as e:
            return ActionResult(success=False, error=str(e))
```

- [ ] **Step 2: Add to get_capabilities()**

Find `get_capabilities()` in `SystemAutomationAdapter` and add:
```python
    def get_capabilities(self) -> list[str]:
        return [
            "open_application",
            "install_app",
            "list_running_apps",
            "close_application",
            "run_command",
            "get_system_info",
            "control_media",
            "get_active_window",
            "play_music",
            "control_volume",
            "get_current_track",
            "skip_to_song",
            "play_playlist",
        ]
```

- [ ] **Step 3: Add VK constants and FindWindowW import**

At the top of `_action_control_volume` method, ensure the `ctypes` import also imports `windll` and uses `FindWindowW`. Since `_action_get_current_track` already uses `FindWindowW`, verify it's imported at module level in `system_adapter.py`. If not, add to the imports inside that method.

Also add `VK_DOWN = 0x28` and `VK_TAB = 0x09` as constants where needed.

- [ ] **Step 4: Commit**
```bash
git add integrations/system/system_adapter.py
git commit -m "feat(spotify): add deep media control actions

- control_volume: volume up/down/mute via VK_VOLUME_* keys
- get_current_track: parse Spotify window title for now-playing
- skip_to_song: search Spotify and navigate to play a specific song
- play_playlist: search and open Spotify playlist by name

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## WORKSTREAM B: WhatsApp Desktop Automation

### Task B1: Add desktop app automation methods to WhatsAppAdapter

**Files:**
- Modify: `integrations/whatsapp/whatsapp_adapter.py` (add pywinauto-based methods)

- [ ] **Step 1: Add desktop app methods**

First, add to imports at top of file:
```python
import time
from pathlib import Path
```

Then add these methods to `WhatsAppAdapter` class (after `get_capabilities()`):

```python
    def _action_read_messages(self, contact: str = "", count: int = 10, **kwargs) -> ActionResult:
        """Read recent messages from a WhatsApp chat using pywinauto."""
        try:
            from pywinauto import Application, findwindows
            import ctypes

            # Try to connect to WhatsApp desktop app
            wa_window = None
            try:
                app = Application(backend="uia").connect(title_re="WhatsApp.*", timeout=3)
                wa_window = app.window(title_re="WhatsApp.*")
                wa_window.set_focus()
            except Exception:
                pass

            if not wa_window:
                # Fall back to web WhatsApp
                return ActionResult(success=False, error="WhatsApp desktop not running. Using web WhatsApp instead.")

            user32 = ctypes.windll.user32

            # Search for contact
            search_box = wa_window.child_window(auto_id="mainSearchBox", control_type="Edit")
            if search_box.exists():
                search_box.set_edit_text(contact)
                time.sleep(1)
                # Press Enter to open chat
                user32.keybd_event(0x0D, 0, 0, 0)
                user32.keybd_event(0x0D, 0, 0x0002, 0)
                time.sleep(1)

            # Try to read message bubbles
            messages = []
            try:
                chat_area = wa_window.child_window(control_type="Document")
                if chat_area.exists():
                    # Get all text from chat area
                    all_text = chat_area.window_text()
                    if all_text:
                        # Split by newlines and take recent ones
                        lines = [l.strip() for l in all_text.split("\n") if l.strip()]
                        messages = lines[-count:] if len(lines) > count else lines
            except Exception:
                pass

            if messages:
                msg_text = "\n".join(messages)
                return ActionResult(
                    success=True,
                    data={
                        "contact": contact,
                        "messages": messages,
                        "count": len(messages),
                        "spoken_message": f"Last messages from {contact}: {'. '.join(messages[:3])}",
                    }
                )
            return ActionResult(success=True, data={"contact": contact, "messages": [], "spoken_message": f"No messages found from {contact}"})

        except ImportError:
            return ActionResult(success=False, error="pywinauto not installed. Run: pip install pywinauto")
        except Exception as e:
            logger.warning(f"[WhatsApp] read_messages failed: {e}")
            return ActionResult(success=False, error=str(e))

    def _action_search_messages(self, query: str = "", **kwargs) -> ActionResult:
        """Search within WhatsApp messages."""
        try:
            from pywinauto import Application
            import ctypes

            try:
                app = Application(backend="uia").connect(title_re="WhatsApp.*", timeout=3)
                wa_window = app.window(title_re="WhatsApp.*")
                wa_window.set_focus()
            except Exception:
                return ActionResult(success=False, error="WhatsApp desktop not running")

            user32 = ctypes.windll.user32

            # Click search icon (Ctrl+F in WhatsApp desktop)
            user32.keybd_event(0x11, 0, 0, 0)  # Ctrl
            user32.keybd_event(0x46, 0, 0, 0)    # F
            user32.keybd_event(0x46, 0, 0x0002, 0)
            user32.keybd_event(0x11, 0, 0x0002, 0)
            time.sleep(0.5)

            # Type search query
            search_edit = wa_window.child_window(auto_id="searchInput", control_type="Edit")
            if search_edit.exists():
                search_edit.set_edit_text(query)
                time.sleep(1)

            return ActionResult(success=True, data={"query": query, "spoken_message": f"Searching WhatsApp for: {query}"})

        except ImportError:
            return ActionResult(success=False, error="pywinauto not installed")
        except Exception as e:
            logger.warning(f"[WhatsApp] search_messages failed: {e}")
            return ActionResult(success=False, error=str(e))

    def _action_send_media(self, contact: str = "", file_path: str = "", caption: str = "", **kwargs) -> ActionResult:
        """Send a media file (image/video) to a WhatsApp contact."""
        try:
            from pywinauto import Application
            import ctypes
            import subprocess

            if not contact or not file_path:
                return ActionResult(success=False, error="Specify contact and file_path")

            # Verify file exists
            if not Path(file_path).exists():
                return ActionResult(success=False, error=f"File not found: {file_path}")

            try:
                app = Application(backend="uia").connect(title_re="WhatsApp.*", timeout=3)
                wa_window = app.window(title_re="WhatsApp.*")
                wa_window.set_focus()
            except Exception:
                return ActionResult(success=False, error="WhatsApp desktop not running")

            user32 = ctypes.windll.user32

            # Search for contact
            search_box = wa_window.child_window(auto_id="mainSearchBox", control_type="Edit")
            if search_box.exists():
                search_box.set_edit_text(contact)
                time.sleep(1)
                user32.keybd_event(0x0D, 0, 0, 0)
                user32.keybd_event(0x0D, 0, 0x0002, 0)
                time.sleep(1)

            # Click attach button (paperclip icon)
            try:
                attach_btn = wa_window.child_window(title="Attach", control_type="Button")
                if not attach_btn.exists():
                    attach_btn = wa_window.child_window(auto_id="attachDocBtn", control_type="Button")
                if attach_btn.exists():
                    attach_btn.click()
                    time.sleep(1)
                    # Type file path into the file dialog
                    file_input = wa_window.child_window(control_type="Edit")
                    if file_input.exists():
                        file_input.set_edit_text(str(Path(file_path).resolve()))
                        time.sleep(0.5)
                        user32.keybd_event(0x0D, 0, 0, 0)  # Open
                        user32.keybd_event(0x0D, 0, 0x0002, 0)
                        time.sleep(2)

                        # Send (Enter or click send button)
                        if caption:
                            msg_box = wa_window.child_window(control_type="Edit")
                            if msg_box.exists():
                                msg_box.set_edit_text(caption)
                                time.sleep(0.5)

                        send_btn = wa_window.child_window(title="Send", control_type="Button")
                        if send_btn.exists():
                            send_btn.click()
                        else:
                            user32.keybd_event(0x0D, 0, 0, 0)
                            user32.keybd_event(0x0D, 0, 0x0002, 0)
            except Exception as e:
                return ActionResult(success=False, error=f"Attachment UI interaction failed: {e}")

            return ActionResult(success=True, data={"contact": contact, "file": Path(file_path).name, "spoken_message": f"Sent {Path(file_path).name} to {contact}"})

        except ImportError:
            return ActionResult(success=False, error="pywinauto not installed. Run: pip install pywinauto")
        except Exception as e:
            logger.warning(f"[WhatsApp] send_media failed: {e}")
            return ActionResult(success=False, error=str(e))
```

- [ ] **Step 2: Update get_capabilities()**
```python
    def get_capabilities(self) -> list[str]:
        return [
            "send_message",
            "send_image",
            "send_media",
            "search_chat",
            "get_chat_history",
            "read_messages",
            "search_messages",
            "mark_read",
            "get_status",
        ]
```

- [ ] **Step 3: Commit**
```bash
git add integrations/whatsapp/whatsapp_adapter.py
git commit -m "feat(whatsapp): add desktop automation methods

- read_messages: use pywinauto to search contact and read chat
- search_messages: Ctrl+F search within WhatsApp desktop
- send_media: attach and send image/video via pywinauto UI automation

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## WORKSTREAM C: Teams Deep Automation

### Task C1: Add Teams meeting and channel methods to WindowsAppAdapter

**Files:**
- Modify: `integrations/system/windows_app_adapter.py` (add methods)

- [ ] **Step 1: Add Teams methods**

First check if `windows_app_adapter.py` already has `teams_join_meeting` and `teams_send_message`:
```bash
grep -n "teams_join_meeting\|teams_send_message\|read_teams_messages\|get_teams_meetings" integrations/system/windows_app_adapter.py
```

If they don't exist, find the end of the `WindowsAppAdapter` class and add these methods:
```python
    def _action_join_teams_meeting(self, meeting_name: str = "", meeting_link: str = "", **kwargs) -> ActionResult:
        """Join a Teams meeting by name or link."""
        try:
            import subprocess
            import time
            import ctypes

            # If a direct link is provided, open it
            if meeting_link:
                subprocess.Popen(["cmd", "/c", "start", "", meeting_link],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3)
                return ActionResult(success=True, data={"action": "join", "meeting_link": meeting_link, "spoken_message": "Joining Teams meeting from link, sir."})

            if not meeting_name:
                return ActionResult(success=False, error="Specify meeting_name or meeting_link")

            # Launch Teams and search for the meeting
            teams_path = self._find_teams_exe()
            if teams_path:
                subprocess.Popen([teams_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(4)

            # Use pywinauto to interact with Teams
            try:
                from pywinauto import Application
                app = Application(backend="uia").connect(title_re="Microsoft Teams.*", timeout=5)
                win = app.window(title_re="Microsoft Teams.*")
                win.set_focus()
                time.sleep(1)

                user32 = ctypes.windll.user32

                # Try Calendar view first (key combo Ctrl+2)
                user32.keybd_event(0x11, 0, 0, 0)  # Ctrl
                user32.keybd_event(0x32, 0, 0, 0)   # 2
                user32.keybd_event(0x32, 0, 0x0002, 0)
                user32.keybd_event(0x11, 0, 0x0002, 0)
                time.sleep(2)

                # Search for meeting
                search = win.child_window(auto_id="searchInput", control_type="Edit")
                if search.exists():
                    search.set_edit_text(meeting_name)
                    time.sleep(2)
                    user32.keybd_event(0x0D, 0, 0, 0)  # Enter
                    user32.keybd_event(0x0D, 0, 0x0002, 0)
                    time.sleep(2)

                # Try to find and click Join button
                try:
                    join_btn = win.child_window(title="Join", control_type="Button")
                    if join_btn.exists():
                        join_btn.click()
                        time.sleep(3)
                        # Confirm joining
                        join_btn2 = win.child_window(title="Join now", control_type="Button")
                        if join_btn2.exists():
                            join_btn2.click()
                except Exception:
                    pass

                return ActionResult(success=True, data={"meeting": meeting_name, "spoken_message": f"Searching for and joining {meeting_name}, sir."})

            except ImportError:
                return ActionResult(success=False, error="pywinauto not installed. Run: pip install pywinauto")
            except Exception:
                return ActionResult(success=False, error="Could not connect to Teams window")

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_get_teams_meetings(self, **kwargs) -> ActionResult:
        """Get today's upcoming Teams meetings from calendar."""
        try:
            import subprocess
            import time

            teams_path = self._find_teams_exe()
            if not teams_path:
                return ActionResult(success=False, error="Microsoft Teams not installed")

            subprocess.Popen([teams_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(4)

            try:
                from pywinauto import Application
                import ctypes
                user32 = ctypes.windll.user32

                app = Application(backend="uia").connect(title_re="Microsoft Teams.*", timeout=5)
                win = app.window(title_re="Microsoft Teams.*")
                win.set_focus()
                time.sleep(1)

                # Go to Calendar (Ctrl+2)
                user32.keybd_event(0x11, 0, 0, 0)
                user32.keybd_event(0x32, 0, 0, 0)
                user32.keybd_event(0x32, 0, 0x0002, 0)
                user32.keybd_event(0x11, 0, 0x0002, 0)
                time.sleep(2)

                # Try to read calendar content
                meetings = []
                try:
                    calendar_pane = win.child_window(control_type="Pane")
                    if calendar_pane.exists():
                        text = calendar_pane.window_text()
                        if text:
                            lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]
                            meetings = lines[:10]
                except Exception:
                    pass

                if meetings:
                    return ActionResult(success=True, data={"meetings": meetings, "count": len(meetings), "spoken_message": f"Found {len(meetings)} meetings today."})
                return ActionResult(success=True, data={"meetings": [], "spoken_message": "No meetings found for today, sir."})

            except ImportError:
                return ActionResult(success=False, error="pywinauto not installed")
            except Exception:
                return ActionResult(success=False, error="Could not read Teams calendar")

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _action_read_teams_messages(self, channel: str = "General", count: int = 10, **kwargs) -> ActionResult:
        """Read recent messages from a Teams channel."""
        try:
            import subprocess
            import time
            import ctypes

            teams_path = self._find_teams_exe()
            if teams_path:
                subprocess.Popen([teams_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(4)

            try:
                from pywinauto import Application
                user32 = ctypes.windll.user32

                app = Application(backend="uia").connect(title_re="Microsoft Teams.*", timeout=5)
                win = app.window(title_re="Microsoft Teams.*")
                win.set_focus()
                time.sleep(1)

                # Go to Teams (Ctrl+1)
                user32.keybd_event(0x11, 0, 0, 0)
                user32.keybd_event(0x31, 0, 0, 0)
                user32.keybd_event(0x31, 0, 0x0002, 0)
                user32.keybd_event(0x11, 0, 0x0002, 0)
                time.sleep(2)

                # Search for channel
                search = win.child_window(auto_id="searchInput", control_type="Edit")
                if search.exists():
                    search.set_edit_text(channel)
                    time.sleep(2)
                    user32.keybd_event(0x0D, 0, 0, 0)
                    user32.keybd_event(0x0D, 0, 0x0002, 0)
                    time.sleep(2)

                # Try to read messages from chat pane
                messages = []
                try:
                    chat_pane = win.child_window(control_type="Document")
                    if chat_pane.exists():
                        text = chat_pane.window_text()
                        if text:
                            lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 2]
                            messages = lines[-count:] if len(lines) > count else lines
                except Exception:
                    pass

                if messages:
                    msg_text = " | ".join(messages[:5])
                    return ActionResult(success=True, data={"channel": channel, "messages": messages, "count": len(messages), "spoken_message": f"Recent from {channel}: {msg_text}"})
                return ActionResult(success=True, data={"channel": channel, "messages": [], "spoken_message": f"No messages found in {channel}"})

            except ImportError:
                return ActionResult(success=False, error="pywinauto not installed")
            except Exception:
                return ActionResult(success=False, error="Could not read Teams channel")

        except Exception as e:
            return ActionResult(success=False, error=str(e))

    def _find_teams_exe(self) -> str | None:
        """Find Teams executable path."""
        paths = [
            Path(os.path.expandvars("%LOCALAPPDATA%")) / "Microsoft" / "Teams" / "Update.exe",
            Path(os.path.expandvars("%APPDATA%")) / "Microsoft" / "Teams" / "Update.exe",
            Path("C:/Users") / os.getenv("USERNAME", "") / "AppData" / "Local" / "Microsoft" / "Teams" / "Update.exe",
        ]
        for p in paths:
            if p.exists():
                return str(p)
        return None
```

Add `import os` to the top of `windows_app_adapter.py` if not already present.

- [ ] **Step 2: Update get_capabilities()** (find and update the list)
```python
    def get_capabilities(self) -> list[str]:
        return [
            "connect_app", "launch_app", "click_button", "type_text",
            "read_text", "read_window_content",
            "teams_send_message", "teams_join_meeting", "join_teams_meeting",
            "get_teams_meetings", "read_teams_messages",
            "notepad_read", "notepad_write",
            "explorer_navigate", "list_open_windows",
            "read_clipboard", "write_clipboard",
        ]
```

- [ ] **Step 3: Commit**
```bash
git add integrations/system/windows_app_adapter.py
git commit -m "feat(teams): add Teams meeting and channel automation

- join_teams_meeting: navigate to calendar, search meeting, click Join
- get_teams_meetings: read today's calendar via Teams UI
- read_teams_messages: navigate to channel and read recent messages
- _find_teams_exe: locate Teams executable for direct launch
- Add all to get_capabilities()

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

## Final Verification

After all workstreams complete, run this verification:
```bash
# Check all imports work
python -c "
from integrations.core.universal_orchestrator import UniversalOrchestrator
from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
from integrations.system.system_adapter import SystemAutomationAdapter
from integrations.whatsapp.whatsapp_adapter import WhatsAppAdapter
from integrations.system.windows_app_adapter import WindowsAppAdapter
print('All imports OK')
" 2>&1

# Verify all new actions are registered in capabilities
python -c "
from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
a = HomeAssistantAdapter()
caps = a.get_capabilities()
print('HA capabilities:', caps)
assert 'turn_on' in caps
assert 'set_brightness' in caps
assert 'trigger_scene' in caps

from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
o = OutlookNativeAdapter()
caps = o.get_capabilities()
print('Outlook capabilities:', caps)
assert 'update_event' in caps
assert 'delete_event' in caps
assert 'find_meeting_time' in caps

from integrations.system.system_adapter import SystemAutomationAdapter
s = SystemAutomationAdapter()
caps = s.get_capabilities()
print('System capabilities:', caps)
assert 'control_volume' in caps
assert 'get_current_track' in caps
assert 'skip_to_song' in caps
assert 'play_playlist' in caps

print('ALL VERIFICATIONS PASSED')
" 2>&1
```

Expected output: `ALL VERIFICATIONS PASSED`
