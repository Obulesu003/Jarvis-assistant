# core/plugin_manager.py
# Auto-discovery plugin system for MARK XXXV.
# Plugins live in actions/plugins/ and export:
#   PLUGIN_NAME        -- unique tool name string
#   PLUGIN_TOOL_DECLARATION -- Gemini function declaration dict
#   PLUGIN_HANDLER     -- callable(params, player, speak) -> str

import logging  # migrated from print()
import importlib.util
import sys
import threading
from collections.abc import Callable
from pathlib import Path

try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


PLUGINS_DIR = get_base_dir() / "actions" / "plugins"


class PluginManager:
    _instance = None
    _lock     = threading.Lock()

    def __init__(self):
        self._plugins:     dict[str, dict] = {}
        self._declarations: list[dict]     = []
        self._discovered   = False

    @classmethod
    def get_instance(cls) -> "PluginManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def discover_plugins(self) -> list[dict]:
        """Scan actions/plugins/ for valid plugin files and load them."""
        if not PLUGINS_DIR.exists():
            PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
            self._write_example_plugin()
            logging.getLogger("PluginManager").info(f"Created plugins directory: {PLUGINS_DIR}")
            return []

        discovered = []
        for py_file in PLUGINS_DIR.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                plugin = self._load_plugin(py_file)
                if plugin:
                    self._plugins[plugin["name"]] = plugin
                    self._declarations.append(plugin["declaration"])
                    discovered.append(plugin["name"])
                    logging.getLogger("PluginManager").info(f"Loaded plugin: {plugin['name']} ({py_file.name})")
            except Exception as e:
                logging.getLogger("PluginManager").info(f"Failed to load {py_file.name}: {e}")
        self._discovered = True
        return discovered

    def _load_plugin(self, path: Path) -> dict | None:
        """Import a plugin file and extract its exports."""
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)

        name        = getattr(module, "PLUGIN_NAME", None)
        declaration = getattr(module, "PLUGIN_TOOL_DECLARATION", None)
        handler     = getattr(module, "PLUGIN_HANDLER", None)

        if not name or not declaration or not handler:
            logging.getLogger("PluginManager").info('{path.name}: missing PLUGIN_NAME, PLUGIN_TOOL_DECLARATION, or PLUGIN_HANDLER')
            return None

        return {
            "name":        name,
            "declaration": declaration,
            "handler":     handler,
            "path":        str(path),
        }

    def get_tool_declarations(self) -> list[dict]:
        """Return all loaded plugin tool declarations."""
        if not self._discovered:
            self.discover_plugins()
        return self._declarations

    def execute_tool(
        self,
        tool_name: str,
        params: dict,
        player=None,
        speak: Callable | None = None,
    ) -> str:
        """Execute a plugin by name."""
        if not self._discovered:
            self.discover_plugins()

        plugin = self._plugins.get(tool_name)
        if plugin is None:
            return f"Unknown plugin: {tool_name}"

        try:
            return plugin["handler"](params, player=player, speak=speak)
        except Exception as e:
            logging.getLogger("PluginManager").info("Plugin '{tool_name}' error: {e}")
            return f"Plugin '{tool_name}' failed: {e}"

    def list_plugins(self) -> list[str]:
        """Return list of loaded plugin names."""
        if not self._discovered:
            self.discover_plugins()
        return list(self._plugins.keys())

    def reload(self):
        """Clear and re-discover all plugins."""
        self._plugins.clear()
        self._declarations.clear()
        self._discovered = False
        return self.discover_plugins()

    def _write_example_plugin(self):
        """Write an example plugin to help developers."""
        example = '''# actions/plugins/example_plugin.py
# Example plugin for MARK XXXV
# Copy this file and customize it to add new capabilities.

PLUGIN_NAME = "example_plugin"
PLUGIN_TOOL_DECLARATION = {
    "name": "example_plugin",
    "description": "An example plugin that demonstrates the plugin system.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action to perform: greet | echo"
            },
            "message": {
                "type": "STRING",
                "description": "Message for the echo action"
            }
        },
        "required": ["action"]
    }
}

def PLUGIN_HANDLER(params: dict, player=None, speak=None) -> str:
    action = params.get("action", "").lower()
    if action == "greet":
        return "Hello from the plugin system, sir!"
    elif action == "echo":
        return f"You said: {params.get('message', '')}"
    else:
        return f"Unknown action '{action}'. Available: greet, echo"
'''
        example_path = PLUGINS_DIR / "example_plugin.py"
        if not example_path.exists():
            example_path.write_text(example, encoding="utf-8")


# Convenience functions for main.py
def get_plugin_manager() -> PluginManager:
    return PluginManager.get_instance()
