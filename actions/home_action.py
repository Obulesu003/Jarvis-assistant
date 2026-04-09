"""
home_action.py - Action function for Home Assistant smart home control.
"""
import logging
import re

logger = logging.getLogger(__name__)

_ha_adapter = None


def get_ha():
    """Get or create the Home Assistant adapter."""
    global _ha_adapter
    if _ha_adapter is None:
        from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
        _ha_adapter = HomeAssistantAdapter()
    return _ha_adapter


def home_action(params: dict, player=None):
    """Action to control smart home via Home Assistant."""
    cmd = params.get("command", "status")
    ha = get_ha()

    if cmd == "turn_on":
        entity = params.get("entity", "")
        result = ha.turn_on(entity)
        return {"status": "on", "entity": entity, "result": result}

    elif cmd == "turn_off":
        entity = params.get("entity", "")
        result = ha.turn_off(entity)
        return {"status": "off", "entity": entity, "result": result}

    elif cmd == "brightness":
        entity = params.get("entity", "")
        percent = params.get("percent", 100)
        result = ha.set_brightness(entity, percent)
        return {"status": "brightness_set", "entity": entity, "percent": percent}

    elif cmd == "temperature":
        entity = params.get("entity", "")
        temp = params.get("temp", 22)
        result = ha.set_temperature(entity, temp)
        return {"status": "temperature_set", "entity": entity, "temp": temp}

    elif cmd == "state":
        entity = params.get("entity", "")
        state = ha.get_state(entity)
        return {"status": "state", "entity": entity, "state": state}

    elif cmd == "list":
        devices = ha.list_all_devices()
        return {"status": "list", "devices": devices, "count": len(devices)}

    elif cmd == "lights":
        lights = ha.list_lights()
        return {"status": "lights", "lights": lights, "count": len(lights)}

    else:
        return {"status": "error", "message": f"Unknown command: {cmd}"}
