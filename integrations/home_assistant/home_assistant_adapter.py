"""
home_assistant_adapter.py - JARVIS controls smart home via Home Assistant local API.
No cloud, no subscription — just your self-hosted HA instance.
Voice commands: "Turn on the lights", "Set bedroom to 22 degrees", "Is the door locked?"
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class HomeAssistantAdapter:
    """
    JARVIS controls smart home via Home Assistant local API.
    No cloud, no subscription. Works with any HA installation.
    """

    def __init__(self, url: str = "http://hassio.local:8123", token: str = ""):
        self.url = url.rstrip("/")
        self.token = token
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._session = None

    def _session(self):
        """Get or create requests session."""
        if self._session is None:
            import requests
            self._session = requests.Session()
            self._session.headers.update(self._headers)
        return self._session

    def turn_on(self, entity_id: str) -> dict[str, Any]:
        """Turn on a device."""
        try:
            import requests
            r = requests.post(
                f"{self.url}/api/services/switch/turn_on",
                headers=self._headers,
                json={"entity_id": entity_id},
                timeout=5,
            )
            return r.json() if r.ok else {"error": r.text}
        except Exception as e:
            logger.error(f"[HA] turn_on failed: {e}")
            return {"error": str(e)}

    def turn_off(self, entity_id: str) -> dict[str, Any]:
        """Turn off a device."""
        try:
            import requests
            r = requests.post(
                f"{self.url}/api/services/switch/turn_off",
                headers=self._headers,
                json={"entity_id": entity_id},
                timeout=5,
            )
            return r.json() if r.ok else {"error": r.text}
        except Exception as e:
            logger.error(f"[HA] turn_off failed: {e}")
            return {"error": str(e)}

    def set_brightness(self, entity_id: str, percent: int) -> dict[str, Any]:
        """Set light brightness (0-100)."""
        try:
            import requests
            r = requests.post(
                f"{self.url}/api/services/light/turn_on",
                headers=self._headers,
                json={"entity_id": entity_id, "brightness_pct": max(0, min(100, percent))},
                timeout=5,
            )
            return r.json() if r.ok else {"error": r.text}
        except Exception as e:
            logger.error(f"[HA] set_brightness failed: {e}")
            return {"error": str(e)}

    def set_temperature(self, entity_id: str, temp: float) -> dict[str, Any]:
        """Set climate temperature."""
        try:
            import requests
            r = requests.post(
                f"{self.url}/api/services/climate/set_temperature",
                headers=self._headers,
                json={"entity_id": entity_id, "temperature": temp},
                timeout=5,
            )
            return r.json() if r.ok else {"error": r.text}
        except Exception as e:
            logger.error(f"[HA] set_temperature failed: {e}")
            return {"error": str(e)}

    def get_state(self, entity_id: str) -> dict[str, Any] | None:
        """Get the state of a device."""
        try:
            import requests
            r = requests.get(
                f"{self.url}/api/states/{entity_id}",
                headers=self._headers,
                timeout=5,
            )
            return r.json() if r.ok else None
        except Exception as e:
            logger.debug(f"[HA] get_state failed: {e}")
            return None

    def list_all_devices(self) -> list[str]:
        """List all device entity IDs."""
        try:
            import requests
            r = requests.get(f"{self.url}/api/states", headers=self._headers, timeout=10)
            if r.ok:
                return [s["entity_id"] for s in r.json()]
        except Exception as e:
            logger.error(f"[HA] list_devices failed: {e}")
        return []

    def list_lights(self) -> list[str]:
        """List all light entities."""
        return [e for e in self.list_all_devices() if e.startswith("light.")]

    def list_switches(self) -> list[str]:
        """List all switch entities."""
        return [e for e in self.list_all_devices() if e.startswith("switch.")]

    def list_climates(self) -> list[str]:
        """List all climate entities."""
        return [e for e in self.list_all_devices() if e.startswith("climate.")]
