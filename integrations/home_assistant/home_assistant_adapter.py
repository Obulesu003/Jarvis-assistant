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
        return ActionResult(success=True, data={"switches": items, "count": len(switches)})

    def _action_list_climates(self, **kwargs) -> ActionResult:
        """List all climate/thermostat entities."""
        states = self._api_get("/states")
        if states is None:
            return ActionResult(success=False, error="Could not reach Home Assistant")
        climates = [s for s in states if s["entity_id"].startswith("climate.")]
        items = [{"entity_id": s["entity_id"], "name": s["attributes"].get("friendly_name", s["entity_id"]), "state": s["state"], "temperature": s["attributes"].get("current_temperature")} for s in climates]
        return ActionResult(success=True, data={"climates": items, "count": len(climates)})

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
