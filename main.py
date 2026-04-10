import logging  # migrated from print()
import asyncio
import collections
import contextlib
import hashlib
import io
import sys
import threading
import time as time_module
import traceback
from pathlib import Path

# ── Unicode safety: prevent crashes on Windows cp1252 console ──────────────────
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        with contextlib.suppress(Exception):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import sounddevice as sd
from google import genai
from google.genai import types

from actions.browser_control import browser_control
from actions.audio_action import audio_action
from actions.memory_action import memory_action
from actions.screen_action import screen_action
from actions.proactive_action import proactive_action
from actions.home_action import home_action
from actions.calendar_tool import calendar_tool
from actions.cmd_control import cmd_control
from actions.code_helper import code_helper
from actions.computer_control import computer_control
from actions.computer_settings import computer_settings
from actions.desktop import desktop_control
from actions.dev_agent import dev_agent
from actions.email_tool import email_tool
from actions.file_controller import file_controller
from actions.flight_finder import flight_finder
from actions.game_updater import game_updater
from actions.github_tool import github_tool
from actions.open_app import open_app
from actions.rag_action import rag_action
from actions.reminder import reminder
from actions.screen_processor import screen_process
from actions.send_message import send_message
from actions.weather_report import weather_action
from actions.web_search import web_search as web_search_action
from actions.youtube_video import youtube_video
from core.api_key_manager import get_gemini_key
from core.cache import get_cache
from core.conversation_manager import get_conversation_manager
from core.scheduler import get_scheduler
from core.screen_monitor import get_screen_monitor
from core.screen_watchdog import get_screen_watchdog
from core.welcome_briefing import get_briefing
from core.lock_monitor import get_lock_monitor
from core.face_auth import FaceAuthenticator
from core.gesture_control import GestureController
from core.intro_music import preload_music
from core.system_hud import get_system_hud
from core.system_tray import get_system_tray
from core.hud import get_hud as get_cinematic_hud
from integrations.approval.workflow import ApprovalWorkflow
from integrations.contacts.contacts_adapter import ContactsAdapter

# Integration adapters
from integrations.outlook.outlook_adapter import OutlookAdapter
from integrations.whatsapp.whatsapp_adapter import WhatsAppAdapter
from memory.memory_manager import (
    extract_memory,
    format_memory_for_prompt,
    load_memory,
    should_extract_memory,
    update_memory,
)
from ui import JarvisUI
from memory.session_metadata import SessionMetadataManager
from core.pattern_learner import InteractionPatternLearner

# Global adapter instances
_approval_workflow = None
_outlook_adapter = None
_outlook_native_adapter = None
_whatsapp_adapter = None
_contacts_adapter = None
_orchestrator = None
_llm_orchestrator = None


def get_approval_workflow():
    global _approval_workflow
    if _approval_workflow is None:
        import json
        from pathlib import Path
        cfg_path = Path("config/settings.json")
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            _approval_workflow = ApprovalWorkflow(cfg.get("approval"))
        except Exception:
            _approval_workflow = ApprovalWorkflow()
    return _approval_workflow


def get_outlook_adapter():
    global _outlook_adapter
    if _outlook_adapter is None:
        _outlook_adapter = OutlookAdapter()
    return _outlook_adapter


def get_outlook_native_adapter():
    global _outlook_native_adapter
    if _outlook_native_adapter is None:
        from integrations.outlook.outlook_native_adapter import OutlookNativeAdapter
        _outlook_native_adapter = OutlookNativeAdapter()
    return _outlook_native_adapter


def get_whatsapp_adapter():
    global _whatsapp_adapter
    if _whatsapp_adapter is None:
        _whatsapp_adapter = WhatsAppAdapter()
    return _whatsapp_adapter


def get_contacts_adapter():
    global _contacts_adapter
    if _contacts_adapter is None:
        _contacts_adapter = ContactsAdapter()
    return _contacts_adapter


# ── Local TTS (SAPI + Piper fallback) ────────────────────────────────────────
_local_tts_instance = None


def _get_local_tts():
    """
    Get the best available local TTS engine.
    Priority: Piper (best quality) > SAPI (built-in Windows) > Silent fallback.
    """
    global _local_tts_instance
    if _local_tts_instance is not None:
        return _local_tts_instance

    # Try Piper first (higher quality British voice)
    from core.tts_engine import TTSEngine
    piper = TTSEngine()
    if piper.is_ready:
        _local_tts_instance = piper
        logging.getLogger("TTS").info('Using Piper local TTS (best quality)')
    else:
        # Fall back to Windows SAPI (always available on Windows)
        try:
            from core.sapi_tts import get_sapi_tts
            sapi = get_sapi_tts()
            if sapi.is_ready:
                _local_tts_instance = sapi
                logging.getLogger("TTS").info('Using Windows SAPI TTS (built-in)')
            else:
                _local_tts_instance = None
                logging.getLogger("TTS").info('No local TTS available')
        except Exception as e:
            logging.getLogger("TTS").info(f"SAPI unavailable: {e}")
            _local_tts_instance = None

    return _local_tts_instance



def get_orchestrator(ui=None):
    global _orchestrator
    if _orchestrator is None:
        from integrations.core.universal_orchestrator import UniversalOrchestrator

        _orchestrator = UniversalOrchestrator(ui=ui)

        # Register all adapter singletons at startup
        _orchestrator.register_adapter("outlook", get_outlook_adapter())
        _orchestrator.register_adapter("outlook_native", get_outlook_native_adapter())
        _orchestrator.register_adapter("whatsapp", get_whatsapp_adapter())
        _orchestrator.register_adapter("contacts", get_contacts_adapter())
        # system and windows_app are instantiated on demand via lazy loading
        _orchestrator.register_adapter(
            "system",
            __import__("integrations.system.system_adapter", fromlist=["SystemAutomationAdapter"]).SystemAutomationAdapter(),
        )
        _orchestrator.register_adapter(
            "windows_app",
            __import__("integrations.system.windows_app_adapter", fromlist=["WindowsAppAdapter"]).WindowsAppAdapter(),
        )
    return _orchestrator


def get_llm_orchestrator(ui=None):
    """Get the LLM-powered orchestrator (wraps UniversalOrchestrator with Gemini)."""
    global _llm_orchestrator
    if _llm_orchestrator is None:
        from integrations.core.llm_orchestrator import LLMOrchestrator

        _llm_orchestrator = LLMOrchestrator(
            universal_orchestrator=get_orchestrator(ui=ui),
            gemini_key=get_gemini_key(),
        )
    return _llm_orchestrator


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024


def _get_api_key() -> str:
    return get_gemini_key()


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results -- always call the appropriate tool."
        )


# -- Hafıza --------------------------------------------------------------------
_last_memory_input = ""


def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input

    user_text   = (user_text   or "").strip()
    jarvis_text = (jarvis_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, jarvis_text, api_key):
            return
        data = extract_memory(user_text, jarvis_text, api_key)
        if data:
            update_memory(data)
            logging.getLogger("Memory").info(f'OK {list(data.keys())}')
    except Exception as e:
        if "429" not in str(e):
            logging.getLogger("Memory").info(f'WARN {e}')


def _summarize_conversation() -> None:
    """Background thread to summarize the conversation buffer."""
    try:
        conv_mgr = get_conversation_manager()
        summary = conv_mgr.summarize()
        if summary:
            logging.getLogger("Conversation").info(f'NOTE Summarized: {summary[:120]}')
    except Exception as e:
        logging.getLogger("Conversation").info(f'WARN Summarization failed: {e}')


# -- Tool declarations ---------------------------------------------------------
TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the Windows computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool -- never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT -- the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "cmd_control",
        "description": (
            "Runs CMD/terminal commands via natural language: disk space, processes, "
            "system info, network, find files, or anything in the command line."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":    {"type": "STRING", "description": "Natural language description of what to do"},
                "visible": {"type": "BOOLEAN", "description": "Open visible CMD window. Default: true"},
                "command": {"type": "STRING", "description": "Optional: exact command if already known"},
            },
            "required": ["task"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic -- use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving -- just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity -- name, age, birthday, city, job, language, nationality | "
                        "preferences -- favorite food/color/music/film/game/sport, hobbies | "
                        "projects -- active projects, goals, things being built | "
                        "relationships -- friends, family, partner, colleagues | "
                        "wishes -- future plans, things to buy, travel dreams | "
                        "notes -- habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "schedule_task",
        "description": (
            "Schedules a recurring or one-time task. Use this for reminders, "
            "periodic check-ins, ambient monitoring, or scheduled automation. "
            "Sir: 'Remind me to check email every morning at 8am' -> schedule_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":      {"type": "STRING", "description": "What the scheduled task should do (natural language goal)"},
                "schedule":  {"type": "STRING", "description": "daily | weekly | interval:N | one_time | ambient (default: daily)"},
                "time":      {"type": "STRING", "description": "Time in HH:MM format (for daily/weekly)"},
                "days":      {"type": "STRING", "description": "Comma-separated days: Mon,Tue,Wed (for weekly)"},
                "interval":  {"type": "INTEGER", "description": "Minutes between runs (for interval schedule)"},
                "ambient":   {"type": "BOOLEAN", "description": "Run silently/autonomously without interrupting (default: false)"},
            },
            "required": ["goal", "schedule"]
        }
    },
    {
        "name": "screen_monitor",
        "description": (
            "Controls ambient screen monitoring -- detects actionable content like "
            "error dialogs, notifications, meeting reminders on screen. "
            "Enable for proactive awareness. Sir: 'Watch my screen for errors'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "enable | disable | check | status | set_interval (default: enable)"},
                "interval":  {"type": "INTEGER", "description": "Seconds between checks (15-3600, default: 60)"},
            },
            "required": []
        }
    },
    {
        "name": "voice_settings",
        "description": (
            "Get or change J.A.R.V.I.S's voice and speech settings. Use 'get' to "
            "check current settings, 'set' to change them. Sir: 'Change your voice to Fenrir' "
            "or 'Set your speaking speed to 1.1x'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "get | set"},
                "voice_name":  {"type": "STRING", "description": "Prebuilt voice name: Charon (default), Fenrir, Kora, Puck, Leda, Aoede, etc."},
                "voice_speed": {"type": "NUMBER", "description": "Speaking speed multiplier: 0.8 to 1.2 (default: 1.0). Higher = faster."},
            },
            "required": ["action"]
        }
    },
    {
        "name": "github_tool",
        "description": (
            "Manage GitHub repositories -- list repos, create issues, view issues, "
            "view commits, and get repo statistics. Requires a GitHub personal access "
            "token in config/api_keys.json as 'github_token'. "
            "Sir: 'List my GitHub repos' -> github_tool(list_repos). "
            "'Create an issue on FatihMakes/Mark-XXXV about a bug' -> github_tool(create_issue)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Action to perform: list_repos | create_issue | list_issues | get_commits | repo_stats"
                },
                "repo":    {"type": "STRING", "description": "Repository in owner/repo format (e.g. 'FatihMakes/Mark-XXXV')"},
                "title":   {"type": "STRING", "description": "Issue title (for create_issue)"},
                "body":    {"type": "STRING", "description": "Issue body/description (for create_issue)"},
                "labels":  {"type": "ARRAY",  "description": "List of label names (for create_issue)", "items": {"type": "STRING"}},
                "state":   {"type": "STRING", "description": "Issue state: open | closed (for list_issues, default: open)"},
                "count":   {"type": "INTEGER","description": "Number of results (default: 10, max: 30)"},
                "branch":  {"type": "STRING", "description": "Branch name (for get_commits, default: main)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "calendar_tool",
        "description": (
            "Manage calendar events. Can list upcoming events, create events with details, "
            "or parse natural language to create a quick event. "
            "Sir: 'What's on my calendar this week?' -> calendar_tool(list_events). "
            "'Schedule a meeting with John tomorrow at 3pm' -> calendar_tool(create_event)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list_events | create_event | quick_event"},
                "title":       {"type": "STRING", "description": "Event title (for create_event)"},
                "start":       {"type": "STRING", "description": "Start datetime: YYYY-MM-DD HH:MM or natural ('tomorrow 3pm') (for create_event)"},
                "end":         {"type": "STRING", "description": "End datetime (optional, defaults to start + 1 hour)"},
                "description": {"type": "STRING", "description": "Event description (for create_event)"},
                "location":    {"type": "STRING", "description": "Event location (for create_event)"},
                "all_day":     {"type": "BOOLEAN","description": "All-day event (for create_event)"},
                "text":        {"type": "STRING", "description": "Natural language description (for quick_event)"},
                "days":        {"type": "INTEGER","description": "Days ahead to list (for list_events, default: 7)"},
                "count":       {"type": "INTEGER","description": "Max events to list (for list_events, default: 10)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "email_tool",
        "description": (
            "Send emails or open your email inbox. Configure SMTP in config/api_keys.json "
            "(smtp_host, smtp_port, smtp_user, smtp_password, email_address, email_provider). "
            "Without SMTP configured, opens a mailto: link in your default mail client. "
            "Sir: 'Send an email to John' -> email_tool(send)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "send | read | compose"},
                "to":      {"type": "STRING", "description": "Recipient email address (for send/compose)"},
                "subject": {"type": "STRING", "description": "Email subject (for send/compose)"},
                "body":    {"type": "STRING", "description": "Email body (for send/compose)"},
                "cc":      {"type": "STRING", "description": "CC recipient (optional, for send/compose)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "outlook_tool",
        "description": (
            "Full Outlook email and calendar access via browser automation. "
            "Reads and sends emails, manages calendar events, and searches across Outlook. "
            "Sir: 'List my unread emails' -> outlook_tool(list_emails). "
            "'Send an email to John about the project' -> outlook_tool(send_email). "
            "'What's on my calendar tomorrow' -> outlook_tool(list_events). "
            "'Schedule a meeting with Sarah Friday at 2pm' -> outlook_tool(create_event)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING", "description": "list_emails | search_emails | read_email | send_email | reply_email | forward_email | list_events | create_event | update_event | delete_event | find_meeting_time"},
                "folder":       {"type": "STRING", "description": "Email folder: Inbox, Sent, Drafts, etc. (for list_emails, default: Inbox)"},
                "query":        {"type": "STRING", "description": "Search query (for search_emails)"},
                "email_id":     {"type": "STRING", "description": "Email ID (for read_email, reply_email, forward_email)"},
                "to":           {"type": "STRING", "description": "Recipient email (for send_email, reply_email, forward_email)"},
                "subject":      {"type": "STRING", "description": "Email subject (for send_email, reply_email, forward_email)"},
                "body":         {"type": "STRING", "description": "Email body (for send_email, reply_email, forward_email)"},
                "cc":           {"type": "STRING", "description": "CC recipient (optional)"},
                "attachments":  {"type": "ARRAY",  "description": "List of file paths to attach (optional)", "items": {"type": "STRING"}},
                "title":        {"type": "STRING", "description": "Event title (for create_event, update_event)"},
                "start":        {"type": "STRING", "description": "Start datetime: YYYY-MM-DD HH:MM (for create_event, update_event)"},
                "end":          {"type": "STRING", "description": "End datetime (for create_event, update_event)"},
                "attendees":    {"type": "ARRAY",  "description": "List of email addresses (for create_event, find_meeting_time)", "items": {"type": "STRING"}},
                "location":     {"type": "STRING", "description": "Event location (for create_event, update_event)"},
                "description":  {"type": "STRING", "description": "Event description (for create_event, update_event)"},
                "all_day":      {"type": "BOOLEAN","description": "All-day event (for create_event)"},
                "event_id":     {"type": "STRING", "description": "Event ID (for update_event, delete_event)"},
                "date":         {"type": "STRING", "description": "Date for list_events: YYYY-MM-DD (default: today)"},
                "days":         {"type": "INTEGER","description": "Days ahead to list events (for list_events, default: 7)"},
                "count":        {"type": "INTEGER","description": "Max results (default: 10)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "outlook_native_tool",
        "description": (
            "Native Outlook app automation via Windows COM API. "
            "Uses the installed Outlook application directly -- all emails, calendar, "
            "and contacts are available without any browser or login. "
            "SIR: 'How many unread emails do I have' -> outlook_native_tool(get_unread_count). "
            "'Read my latest emails' -> outlook_native_tool(list_emails). "
            "'Show me emails from John' -> outlook_native_tool(search_emails). "
            "'Send email to Mike' -> outlook_native_tool(send_email). "
            "'Create a meeting tomorrow at 3pm' -> outlook_native_tool(create_calendar_event)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":        {"type": "STRING", "description": "get_unread_count | get_inbox_count | list_emails | search_emails | read_email | send_email | reply_email | forward_email | delete_email | list_calendar_events | create_calendar_event"},
                "folder":        {"type": "STRING", "description": "Email folder (for list_emails, search_emails; default: Inbox)"},
                "email_id":      {"type": "STRING", "description": "Email entry ID (for read_email, reply_email, forward_email, delete_email)"},
                "to":            {"type": "STRING", "description": "Recipient email (for send_email, forward_email)"},
                "subject":       {"type": "STRING", "description": "Email subject (for send_email)"},
                "body":          {"type": "STRING", "description": "Email body (for send_email, reply_email, forward_email)"},
                "cc":            {"type": "STRING", "description": "CC recipient (for send_email)"},
                "attachments":   {"type": "ARRAY",  "description": "File paths to attach", "items": {"type": "STRING"}},
                "query":         {"type": "STRING", "description": "Search query (for search_emails)"},
                "max_results":   {"type": "INTEGER","description": "Max emails to return (default: 20)"},
                "unread_only":   {"type": "BOOLEAN","description": "Only show unread emails (for list_emails)"},
                "mark_read":     {"type": "BOOLEAN","description": "Mark email as read after reading (default: true)"},
                "reply_all":     {"type": "BOOLEAN","description": "Reply to all instead of just sender (for reply_email)"},
                "title":         {"type": "STRING", "description": "Event title (for create_calendar_event)"},
                "start":         {"type": "STRING", "description": "Start datetime (YYYY-MM-DD HH:MM)"},
                "end":           {"type": "STRING", "description": "End datetime (YYYY-MM-DD HH:MM)"},
                "location":      {"type": "STRING", "description": "Meeting location (for create_calendar_event)"},
                "all_day":       {"type": "BOOLEAN","description": "All-day event (for create_calendar_event)"},
                "reminder":      {"type": "INTEGER","description": "Reminder minutes before (default: 15)"},
                "start_date":    {"type": "STRING", "description": "Calendar start date YYYY-MM-DD"},
                "end_date":      {"type": "STRING", "description": "Calendar end date YYYY-MM-DD"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "whatsapp_tool",
        "description": (
            "WhatsApp messaging via web.whatsapp.com browser automation. "
            "Send messages, images, search chats, and read conversation history. "
            "Sir: 'Send a message to Mom' -> whatsapp_tool(send_message). "
            "'Get recent messages from John' -> whatsapp_tool(get_chat_history). "
            "'Search for the chat with Sarah' -> whatsapp_tool(search_chat)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "send_message | send_image | search_chat | get_chat_history | mark_read | get_status"},
                "receiver":    {"type": "STRING", "description": "Contact name or phone number (for send_message, send_image, mark_read, get_chat_history)"},
                "message":     {"type": "STRING", "description": "Message text (for send_message)"},
                "image_path":  {"type": "STRING", "description": "Path to image file (for send_image)"},
                "caption":     {"type": "STRING", "description": "Image caption (for send_image, optional)"},
                "chat_name":   {"type": "STRING", "description": "Chat name (for get_chat_history, mark_read)"},
                "limit":       {"type": "INTEGER","description": "Number of messages to retrieve (for get_chat_history, default: 20)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "contacts_tool",
        "description": (
            "Windows Contacts lookup via browser automation and native integration. "
            "Search contacts, get details, and view interaction history. "
            "Sir: 'Find John Smith' -> contacts_tool(search_contacts). "
            "'Get details of Sarah' -> contacts_tool(get_contact). "
            "'Show my recent contacts' -> contacts_tool(list_contacts)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":       {"type": "STRING", "description": "get_contact | search_contacts | list_contacts | get_relationship_context | refresh"},
                "name":         {"type": "STRING", "description": "Contact name (for get_contact, get_relationship_context)"},
                "query":        {"type": "STRING", "description": "Search query (for search_contacts)"},
                "limit":        {"type": "INTEGER","description": "Max contacts to list (for list_contacts, default: 20)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "system_tool",
        "description": (
            "Native Windows system control -- open/close applications, install apps, "
            "run commands, and get system info. Uses the system's installed applications "
            "directly without any browser automation. "
            "Sir: 'Open WhatsApp' -> system_tool(open_application). "
            "'Install VS Code' -> system_tool(install_app). "
            "'Show running apps' -> system_tool(list_running_apps). "
            "'Close Discord' -> system_tool(close_application). "
            "'Run ipconfig' -> system_tool(run_command)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":         {"type": "STRING", "description": "open_application | install_app | list_running_apps | close_application | run_command | get_system_info"},
                "name":           {"type": "STRING", "description": "App name to open/close/install (for open_application, close_application, install_app)"},
                "url":            {"type": "STRING", "description": "URL or download link (for open_application, install_app)"},
                "command":        {"type": "STRING", "description": "Shell command to execute (for run_command)"},
                "package_manager": {"type": "STRING", "description": "winget | choco (for install_app, default: winget)"},
                "force":          {"type": "BOOLEAN","description": "Force kill (for close_application, default: false)"},
                "wait":           {"type": "BOOLEAN","description": "Wait for command completion (for run_command, default: true)"},
                "timeout":        {"type": "INTEGER","description": "Timeout in seconds (for run_command, default: 60)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "windows_app_tool",
        "description": (
            "Control any running Windows desktop application via UI automation. "
            "Can click buttons, type text, read content, and read window text. "
            "IMPORTANT: This tool is for controlling ALREADY OPEN applications. "
            "Use open_app to launch apps first, then use windows_app_tool to control them. "
            "SIR: 'Show me what windows are open' -> windows_app_tool(list_open_windows). "
            "'Click the Send button in Notepad' -> windows_app_tool(click_button, app_name: notepad, button_text: Send). "
            "'Type hello in the search box' -> windows_app_tool(type_text, app_name: teams, field_text: search, text: hello). "
            "'Read the content of Notepad' -> windows_app_tool(notepad_read). "
            "'Navigate File Explorer to Documents' -> windows_app_tool(explorer_navigate, path: C:\\Users\\bobul\\Documents). "
            "'Open Notepad, type hello, and save' -> open_app first, then windows_app_tool."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":        {"type": "STRING", "description": "list_open_windows | connect_app | launch_app | click_button | type_text | read_text | read_window_content | teams_send_message | teams_join_meeting | notepad_read | notepad_write | explorer_navigate"},
                "app_name":      {"type": "STRING", "description": "App name: teams, excel, word, notepad, calculator, file explorer"},
                "window_title":  {"type": "STRING", "description": "Window title to connect to (alternative to app_name)"},
                "button_text":   {"type": "STRING", "description": "Button text to click (for click_button)"},
                "text":          {"type": "STRING", "description": "Text to type (for type_text, notepad_write, teams_send_message)"},
                "field_text":    {"type": "STRING", "description": "Field label to find (for type_text)"},
                "element_text":  {"type": "STRING", "description": "Element text to find (for read_text)"},
                "recipient":     {"type": "STRING", "description": "Teams recipient name (for teams_send_message)"},
                "message":       {"type": "STRING", "description": "Teams message text (for teams_send_message)"},
                "meeting_link":  {"type": "STRING", "description": "Teams meeting URL (for teams_join_meeting)"},
                "path":          {"type": "STRING", "description": "File path (for explorer_navigate)"},
                "clear_first":   {"type": "BOOLEAN","description": "Clear field before typing (for type_text, default: true)"},
                "append":        {"type": "BOOLEAN","description": "Append instead of overwrite (for notepad_write)"},
                "max_length":    {"type": "INTEGER","description": "Max text length to read (default: 5000)"},
                "index":         {"type": "INTEGER","description": "Element index for click (default: 0)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "assistant",
        "description": (
            "Universal assistant — handles ANY request in natural language. "
            "No predefined actions needed. Just say what you want and it figures out how to do it. "
            "Sir: 'How many unread emails do I have?' -> assistant. "
            "'Read my latest emails and summarize' -> assistant. "
            "'Send a WhatsApp message to Mom' -> assistant. "
            "'Create a meeting with John tomorrow at 3pm' -> assistant. "
            "'Open VS Code and check what's running' -> assistant. "
            "'Search for the best restaurants in Istanbul' -> assistant."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "request": {"type": "STRING", "description": "What you want to do in plain English — any task, no limits"},
            },
            "required": ["request"]
        }
    },
    {
        "name": "document_search",
        "description": (
            "Search and query personal documents using RAG (Retrieval-Augmented Generation). "
            "Index folders of documents, then ask questions about their contents. "
            "Sir: 'Index my Documents folder' -> document_search(index, folder: Documents). "
            "'What does my contract say about termination?' -> document_search(query, question: ...). "
            "'How many documents are indexed?' -> document_search(stats)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command":  {"type": "STRING", "description": "index | query | stats (default: query)"},
                "folder":   {"type": "STRING", "description": "Folder path to index (for index command)"},
                "question": {"type": "STRING", "description": "Question about document contents (for query command)"},
            },
            "required": []
        }
    },
    {
        "name": "audio_pipeline",
        "description": (
            "Controls the local audio pipeline -- always-on wake word listening, "
            "local transcription, and local TTS. "
            "Sir: 'Start listening for wake word' -> audio_pipeline(start). "
            "'Stop listening' -> audio_pipeline(stop). "
            "'Check audio status' -> audio_pipeline(status). "
            "'Speak this' -> audio_pipeline(speak, text: ...)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "start | stop | status | speak | speak_async"},
                "text":    {"type": "STRING", "description": "Text to speak (for speak commands)"},
            },
            "required": []
        }
    },
    {
        "name": "jarvis_memory",
        "description": (
            "JARVIS's 4-layer memory system. Remembers everything about you, "
            "your preferences, your projects, and past conversations. "
            "Sir: 'What do you remember about me?' -> jarvis_memory(recall, query: me). "
            "'Remember that I work at Shop Sore' -> jarvis_memory(learn, subject: Bobby, relation: works_at, object: Shop Sore). "
            "'What did we discuss last time?' -> jarvis_memory(recent). "
            "'Teach me a new skill' -> jarvis_memory(teach)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command":    {"type": "STRING", "description": "remember | recall | learn | what_do_you_know | teach | find_skill | context | knowledge_graph | recent | status"},
                "type":       {"type": "STRING", "description": "Event type (for remember): conversation | action | error | notification"},
                "content":    {"type": "STRING", "description": "Content to remember (for remember)"},
                "query":      {"type": "STRING", "description": "Search query (for recall, what_do_you_know)"},
                "subject":    {"type": "STRING", "description": "Subject (for learn)"},
                "relation":   {"type": "STRING", "description": "Relation (for learn)"},
                "object":     {"type": "STRING", "description": "Object (for learn)"},
                "name":       {"type": "STRING", "description": "Skill name (for teach)"},
                "steps":      {"type": "ARRAY",  "description": "Skill steps (for teach)", "items": {"type": "STRING"}},
                "trigger":    {"type": "STRING", "description": "Skill trigger phrase (for teach, find_skill)"},
                "task":       {"type": "STRING", "description": "Task description (for find_skill)"},
                "user_message": {"type": "STRING", "description": "User message (for context)"},
                "hours":      {"type": "INTEGER","description": "Hours back (for recent, default: 24)"},
                "limit":      {"type": "INTEGER","description": "Result limit (for recall, recent)"},
            },
            "required": []
        }
    },
    {
        "name": "screen_intelligence",
        "description": (
            "JARVIS sees what you see. Captures screen, reads text, analyzes content. "
            "Sir: 'What app am I using?' -> screen_intelligence(describe). "
            "'Read the text on screen' -> screen_intelligence(text). "
            "'Take a screenshot' -> screen_intelligence(capture). "
            "'Analyze what's on screen' -> screen_intelligence(analyze)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command":  {"type": "STRING", "description": "capture | describe | text | window | analyze (default: describe)"},
                "question": {"type": "STRING", "description": "Question about the screen (for describe/analyze)"},
                "path":     {"type": "STRING", "description": "Save path for screenshots (for capture)"},
            },
            "required": []
        }
    },
    {
        "name": "proactive_monitor",
        "description": (
            "Controls JARVIS's proactive monitoring daemon -- speaks when it matters. "
            "Sir: 'Start watching for me' -> proactive_monitor(start). "
            "'Stop proactive monitoring' -> proactive_monitor(stop). "
            "'Status of proactive monitoring' -> proactive_monitor(status)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "start | stop | status | speak"},
                "text":    {"type": "STRING", "description": "Text to speak (for speak command)"},
            },
            "required": []
        }
    },
    {
        "name": "smart_home",
        "description": (
            "Control smart home devices via Home Assistant. "
            "Sir: 'Turn on living room lights' -> smart_home(turn_on, entity: light.living_room). "
            "'Set bedroom to 22 degrees' -> smart_home(temperature, entity: climate.bedroom, temp: 22). "
            "'What's the state of the front door?' -> smart_home(state, entity: lock.front_door). "
            "'List all my devices' -> smart_home(list)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING",  "description": "turn_on | turn_off | brightness | temperature | state | list | lights"},
                "entity":  {"type": "STRING",  "description": "Home Assistant entity ID"},
                "percent": {"type": "INTEGER", "description": "Brightness 0-100 (for brightness)"},
                "temp":    {"type": "NUMBER",  "description": "Temperature in degrees (for temperature)"},
            },
            "required": []
        }
    },
]


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.ui.on_text_command = self._on_text_command
        self._speech_cooldown = False  # Prevent re-triggering during speech
        self._cooldown_lock = threading.Lock()

        # Local TTS fallback — used when Gemini live session is down
        self._local_tts = _get_local_tts()

        # Phase 4: Voice Robustness -- Echo detection with auto-expiring set
        self._recent_commands: collections.OrderedDict[str, float] = collections.OrderedDict()
        self._echo_window_seconds = 10.0

        # Phase 4: Dynamic cooldown -- adjusts based on command length
        self._speech_cooldown_duration = 1.0  # default 1.0s
        self._last_command_word_count  = 0

        # Phase 4: Audio buffer -- holds last 3 seconds at 16kHz
        self._audio_buffer    = collections.deque(maxlen=SEND_SAMPLE_RATE * 3)
        self._buffer_lock    = threading.Lock()

        # Phase 6: ConversationContextEngine -- tracks turns across the session
        from core.conversation_context import ConversationContextEngine
        self._ctx = ConversationContextEngine()
        self._last_tools_used = []  # Track tools per turn

        # Phase 7: Turn-based interruption model
        self._turn_state = "listening"  # listening | jarvis_speaking | interrupted
        self._current_speech_text = ""  # What JARVIS is currently saying

        # Task 22: Interruption guard — require sustained audio before interrupting
        # Counts consecutive audio frames above noise floor while JARVIS is speaking.
        # Only triggers interruption after MIN_INTERRUPTION_FRAMES sustained frames.
        self._interruption_frames = 0
        self._min_interruption_frames = 5  # ~160ms of sustained speech to confirm real user voice

        # Phase 6: MemoryBridge -- initialized lazily on shutdown
        self._memory_bridge = None

        # Phase 6: VisualPresenceEngine -- connects HUD animations to JARVIS state
        from core.visual_presence import VisualPresenceEngine
        hud = get_cinematic_hud()
        self._vpe = VisualPresenceEngine(hud) if hud else None

        # Task 17: Session metadata tracking for cross-session continuity
        self._session_mgr = SessionMetadataManager()
        self._session_mgr.start_session()

        # Task 16: Interaction pattern learning
        self._pattern_learner = InteractionPatternLearner()

    def _get_memory_bridge(self) -> "MemoryBridge | None":
        """Lazily initialize MemoryBridge."""
        if self._memory_bridge is None:
            try:
                from memory.j_memory import JARVISMemory
                from core.memory_bridge import MemoryBridge
                memory = JARVISMemory()
                memory.initialize()
                self._memory_bridge = MemoryBridge(memory)
            except Exception as e:
                logging.getLogger("JARVIS").warning(f"[JarvisLive] MemoryBridge unavailable: {e}")
                self._memory_bridge = None
        return self._memory_bridge

    def stop(self) -> None:
        """Stop the live session and run session review."""
        # Phase 6: Session review on shutdown
        bridge = self._get_memory_bridge()
        if bridge:
            bridge.on_session_end()
        # Task 17: End session and save metadata for cross-session continuity
        self._session_mgr.end_session()
        self._running = False
        logging.getLogger("JARVIS").info("[JarvisLive] Session stopped")

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def _on_emotion(self, emotion_tone):
        """Called when voice emotion is detected during speech."""
        from core.tts_engine import TTSEngine
        try:
            tts = TTSEngine()
            if tts.is_ready:
                tts.set_emotion(emotion_tone)
                # Reset after a delay so emotion doesn't persist
                def _reset():
                    import time
                    time.sleep(2.0)
                    tts.reset_emotion()
                threading.Thread(target=_reset, daemon=True).start()
        except Exception:
            pass

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            with self._cooldown_lock:
                self._speech_cooldown = True  # Block mic input while speaking
            self.ui.set_state("SPEAKING")
            # Phase 7: Track turn state — JARVIS is speaking
            if self._turn_state != "interrupted":
                self._turn_state = "jarvis_speaking"
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")
            # Release cooldown after a brief pause (so user can interject)
            def release_cooldown():
                time_module.sleep(self._cooldown_duration())
                with self._cooldown_lock:
                    self._speech_cooldown = False
            threading.Thread(target=release_cooldown, daemon=True).start()

    def speak(self, text: str):
        """Speak via Gemini live session. Falls back to local SAPI/Piper TTS if offline."""
        if not self._loop or not self.session:
            # Fall back to local TTS — no live session needed
            self._local_tts.speak_async(text)
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} -- {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    # Phase 7: Turn-based interruption model

    def _handle_interruption(self, jarvis_in_progress: str = ""):
        """User spoke while JARVIS was mid-sentence."""
        # 1. Stop JARVIS's speech immediately
        if self._local_tts:
            self._local_tts.stop_async()

        # 2. Record what JARVIS was saying
        self._current_speech_text = jarvis_in_progress
        if hasattr(self, '_ctx'):
            self._ctx.on_interruption(jarvis_in_progress)

        # 3. Set turn state
        self._turn_state = "interrupted"
        # Task 22: Reset interruption guard
        self._interruption_frames = 0

        logging.getLogger("JARVIS").info("[TurnModel] User interrupted JARVIS mid-sentence")

    def _offer_resume(self, interrupted_text: str):
        """After handling interruption, offer to continue."""
        if len(interrupted_text) < 20:
            return  # Too short to resume meaningfully
        resume_prompt = "Shall I continue where I left off?"
        if hasattr(self, '_ctx'):
            self._ctx.current_goal = f"resuming: {interrupted_text[:50]}"
            self._ctx.pending_confirmation.append(("resume", resume_prompt))

    def _on_turn_complete(self, user_text: str, jarvis_text: str) -> None:
        """Called when a conversation turn completes."""
        if hasattr(self, '_ctx'):
            if self._ctx.interrupted:
                interrupted = self._ctx.get_interrupted_text()
                self._ctx.clear_interrupted()
                self._offer_resume(interrupted)
            else:
                tools = getattr(self, '_last_tools_used', [])
                self._ctx.on_user_turn(user_text)
                self._ctx.on_jarvis_turn(jarvis_text, tools)

                # Task 17: Update session metadata
                topic = getattr(self._ctx, 'last_topic', '') or ''
                self._session_mgr.update_topic(topic)
                lang = getattr(self._ctx, '_user_language', 'en')
                self._session_mgr.update_language(lang)
                self._session_mgr.record_tool_chain(tools)

                # Task 16: Record turn completion for pattern learning
                if hasattr(self, '_pattern_learner'):
                    self._pattern_learner.on_turn_complete(helpful=None)

        self._turn_state = "listening"
        # Task 22: Reset interruption guard on turn complete
        self._interruption_frames = 0

    def _load_voice_settings(self) -> dict:
        """Load voice settings from config/settings.json."""
        import json
        settings_path = BASE_DIR / "config" / "settings.json"
        defaults = {"voice_name": "Charon", "voice_speed": 1.0}
        if not settings_path.exists():
            return defaults
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            return {
                "voice_name": data.get("voice_name", defaults["voice_name"]),
                "voice_speed": float(data.get("voice_speed", defaults["voice_speed"])),
            }
        except Exception:
            return defaults

    def _is_echo(self, input_text: str, jarvis_output: str) -> bool:
        """Detect if input is JARVIS's own speech being echoed back."""
        if not jarvis_output:
            return False
        # Convert to lowercase for comparison
        inp = input_text.lower()
        out = jarvis_output.lower()
        # If most of the input matches JARVIS's output, it's likely echo
        words_in = set(inp.split())
        words_out = set(out.split())
        if not words_out:
            return False
        # Check overlap - if >50% of output words appear in input
        overlap = words_in & words_out
        if len(words_out) > 0 and len(overlap) / len(words_out) > 0.5:
            return True
        # Also check if input starts with same phrase as output
        if inp.startswith(out[:30]) if len(out) >= 30 else inp.startswith(out):
            return True
        return False

    # ── Phase 4: Improved Echo Detection ──────────────────────────────────────
    # Uses a hash-based set with auto-expiring entries to catch duplicate commands
    # within the echo window (10 seconds), preventing reprocessing.

    def _clean_expired_commands(self) -> None:
        """Remove command hashes older than the echo window."""
        now = time_module.time()
        expired = [h for h, ts in self._recent_commands.items() if now - ts > self._echo_window_seconds]
        for h in expired:
            del self._recent_commands[h]

    def _is_duplicate_command(self, text: str) -> bool:
        """
        Check if text is a duplicate command within the echo window.
        Uses a hash of the normalized text so similar commands still count.
        Returns True if this exact command was seen recently; adds it to the set.
        """
        normalized = text.lower().strip()
        cmd_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]

        self._clean_expired_commands()

        if cmd_hash in self._recent_commands:
            return True

        # Record this command with its timestamp
        self._recent_commands[cmd_hash] = time_module.time()

        # Keep the dict bounded -- prune again just in case
        if len(self._recent_commands) > 200:
            self._clean_expired_commands()

        return False

    # ── Phase 4: Dynamic Cooldown ───────────────────────────────────────────────
    # Adjusts the cooldown duration based on the length of the last command so
    # that short commands can be followed more quickly while long commands get
    # more breathing room.

    def _update_dynamic_cooldown(self, text: str) -> None:
        """Update the cooldown duration based on word count of the last command."""
        word_count = len(text.split())
        self._last_command_word_count = word_count

        if word_count < 5:
            self._speech_cooldown_duration = 0.5
        elif word_count <= 15:
            self._speech_cooldown_duration = 1.0
        else:
            self._speech_cooldown_duration = 2.0

    def _cooldown_duration(self) -> float:
        """Return the current dynamic cooldown duration."""
        return self._speech_cooldown_duration

    # ── Phase 4: Wake Word Handling ─────────────────────────────────────────────
    # Accepts "mark", "jarvis", "hey mark", "hey jarvis" with case-insensitive
    # matching and strips the detected phrase before processing.

    _WAKE_PHRASES = frozenset({"mark", "jarvis", "hey mark", "hey jarvis"})

    def _strip_wake_word(self, text: str) -> str:
        """Remove wake word from the beginning of the text if present."""
        stripped = text.lower().strip()
        for phrase in self._WAKE_PHRASES:
            if stripped.startswith(phrase):
                remainder = stripped[len(phrase):].strip()
                # If the phrase is the whole text, return empty
                if not remainder and len(phrase) >= len(text):
                    return ""
                # Return the text as-is but preserve original casing for the rest
                if remainder:
                    # Find original position and return rest of original string
                    orig_lower = text.strip()
                    idx = orig_lower.lower().find(phrase)
                    if idx == 0:
                        rest = text.strip()[len(phrase):].strip()
                        return rest
                return ""
        return text

    def _contains_wake_word(self, text: str) -> bool:
        """Return True if text starts with a known wake word phrase."""
        lowered = text.lower().strip()
        for phrase in self._WAKE_PHRASES:
            if lowered.startswith(phrase):
                return True
        return False

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y -- %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        # Inject conversation context
        conv_ctx = get_conversation_manager().get_context_for_prompt()
        if conv_ctx:
            parts.insert(1, conv_ctx)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._load_voice_settings()["voice_name"]
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        # Phase 6: Track tools used for ConversationContextEngine
        self._last_tools_used.append(name)
        # Task 16: Record tool usage for pattern learning
        if hasattr(self, '_pattern_learner'):
            self._pattern_learner.on_tool_used(name)

        # Phase 6: Track tool start for VisualPresenceEngine
        if hasattr(self, '_vpe') and self._vpe:
            self._vpe.on_tool_start(name)

        logging.getLogger("JARVIS").info(f'>> {name}  {args}')
        self.ui.set_state("THINKING")

        # -- Tool result cache (per-tool TTLs from core/cache.py) -------------
        # TTLs: web_search=300s, weather_report=900s, flight_finder=300s,
        #        cmd_control=60s, file_controller=120s, others=30s
        cacheable = {"web_search", "weather_report", "flight_finder", "cmd_control", "file_controller"}
        if name in cacheable:
            cache = get_cache()
            cached = cache.get(name, args)
            if cached:
                logging.getLogger("JARVIS").info(f'Cache hit for {name}')
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": cached}
                )

        # -- save_memory: sessiz, hızlı, Gemini'ye bildirim yok ---------------
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                logging.getLogger("Memory").info(f'save_memory: {category}/{key} = {value}')
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated. Stay completely silent -- vision module will speak directly."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "cmd_control":
                r = await loop.run_in_executor(None, lambda: cmd_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import TaskPriority, get_queue
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                if task_id == "duplicate":
                    result = "Task already in progress or recently completed, sir."
                else:
                    result = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "schedule_task":
                scheduler = get_scheduler()
                goal     = args.get("goal", "")
                schedule = args.get("schedule", "daily")
                time_str = args.get("time", "")
                days     = args.get("days", "")
                interval = args.get("interval", 0)
                ambient  = args.get("ambient", False)
                if not goal:
                    result = "Please specify a goal for the scheduled task, sir."
                else:
                    if schedule == "interval" and interval > 0:
                        schedule = f"interval:{interval}"
                    sched_id = scheduler.add_schedule(goal, schedule, time_str, days, ambient)
                    sched = next((s for s in scheduler.list_schedules() if s["id"] == sched_id), None)
                    next_run = sched["next_run"] if sched else "scheduled"
                    result = f"Task scheduled, sir. ID: {sched_id}. Next run: {next_run}."

            elif name == "screen_monitor":
                monitor = get_screen_monitor()
                action  = args.get("action", "enable").lower()
                if action == "enable":
                    if args.get("interval"):
                        monitor.set_interval(int(args.get("interval", 60)))
                    monitor.set_speak(self.speak)
                    monitor.enable()
                    result = "Screen monitoring enabled, sir. I'll watch for errors and important notifications."
                elif action == "disable":
                    monitor.disable()
                    result = "Screen monitoring disabled, sir."
                elif action == "check":
                    monitor.set_speak(self.speak)
                    finding = monitor.force_check()
                    result = finding if finding else "Nothing actionable detected on screen, sir."
                elif action == "status":
                    enabled = monitor.is_enabled()
                    result = f"Screen monitoring is {'enabled' if enabled else 'disabled'}, sir."
                elif action == "set_interval":
                    if args.get("interval"):
                        monitor.set_interval(int(args["interval"]))
                        result = f"Screen monitor interval set to {args['interval']} seconds, sir."
                    else:
                        result = "Please specify an interval in seconds, sir."
                else:
                    result = f"Unknown screen_monitor action: '{action}'. Available: enable, disable, check, status, set_interval."

            elif name == "github_tool":
                result = github_tool(args, player=self.ui)

            elif name == "voice_settings":
                import json
                action     = args.get("action", "get").lower()
                cfg_path   = BASE_DIR / "config" / "settings.json"
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if cfg_path.exists():
                        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    else:
                        cfg = {"voice_name": "Charon", "voice_speed": 1.0}
                except Exception:
                    cfg = {"voice_name": "Charon", "voice_speed": 1.0}

                if action == "get":
                    result = (
                        f"Current voice: {cfg.get('voice_name', 'Charon')}, "
                        f"speed: {cfg.get('voice_speed', 1.0):.1f}x, sir."
                    )
                elif action == "set":
                    if "voice_name" in args:
                        cfg["voice_name"] = args["voice_name"]
                    if "voice_speed" in args:
                        speed = float(args["voice_speed"])
                        cfg["voice_speed"] = max(0.8, min(1.2, speed))
                    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
                    vn  = cfg["voice_name"]
                    spd = cfg["voice_speed"]
                    result = (
                        f"Voice settings updated, sir. "
                        f"Voice: {vn}, speed: {spd:.1f}x. "
                        f"Restart the session to hear the new voice."
                    )
                else:
                    result = "Unknown action. Use 'get' or 'set', sir."

            elif name == "calendar_tool":
                result = calendar_tool(args, player=self.ui)

            elif name == "email_tool":
                result = email_tool(args, player=self.ui)

            elif name == "outlook_tool":
                action = args.pop("action", "")
                workflow = get_approval_workflow()
                approved, summary = workflow.check_approval(action, args)
                if not approved:
                    result = f"Approval denied for outlook.{action}: {summary}"
                else:
                    adapter = get_outlook_adapter()
                    r = await loop.run_in_executor(None, lambda ad=adapter, ac=action: ad.execute_action(ac, **args))
                    result = r if r else "Outlook operation complete."

            elif name == "outlook_native_tool":
                action = args.pop("action", "")
                workflow = get_approval_workflow()
                approved, summary = workflow.check_approval(action, args)
                if not approved:
                    result = f"Outlook native blocked: {summary}"
                else:
                    adapter = get_outlook_native_adapter()
                    r = await loop.run_in_executor(None, lambda ad=adapter, ac=action: ad.execute_action(ac, **args))
                    result = r if r else "Outlook native operation complete."

            elif name == "whatsapp_tool":
                action = args.pop("action", "")
                workflow = get_approval_workflow()
                approved, summary = workflow.check_approval(action, args)
                if not approved:
                    result = f"Approval denied for whatsapp.{action}: {summary}"
                else:
                    adapter = get_whatsapp_adapter()
                    r = await loop.run_in_executor(None, lambda ad=adapter, ac=action: ad.execute_action(ac, **args))
                    result = r if r else "WhatsApp operation complete."

            elif name == "contacts_tool":
                action = args.pop("action", "")
                workflow = get_approval_workflow()
                approved, summary = workflow.check_approval(action, args)
                if not approved:
                    result = f"Contacts operation blocked: {summary}"
                else:
                    adapter = get_contacts_adapter()
                    r = await loop.run_in_executor(None, lambda ad=adapter, ac=action: ad.execute_action(ac, **args))
                    result = r if r else "Contacts operation complete."

            elif name == "system_tool":
                from integrations.system.system_adapter import SystemAutomationAdapter
                adapter = SystemAutomationAdapter()
                action = args.pop("action", "")
                r = await loop.run_in_executor(None, lambda ad=adapter, ac=action: ad.execute_action(ac, **args))
                result = r if r else "System operation complete."

            elif name == "windows_app_tool":
                from integrations.system.windows_app_adapter import WindowsAppAdapter
                adapter = WindowsAppAdapter()
                action = args.pop("action", "")
                app_name = args.get("app_name", "")
                try:
                    r = await loop.run_in_executor(None, lambda ad=adapter, ac=action: ad.execute_action(ac, **args))
                    if r and hasattr(r, 'success') and not r.success:
                        result = f"App control failed, sir: {r.error}"
                    elif r and hasattr(r, 'data'):
                        result = f"Done. {r.data}"
                    elif r:
                        result = str(r)
                    else:
                        result = "App operation completed, sir."
                except Exception as e:
                    # Fallback to computer_control if windows_app_tool fails
                    result = f"App control error: {e}. Trying alternative method."
                    # Try using computer_control as fallback
                    try:
                        if action == "type_text":
                            text = args.get("text", "")
                            from actions.computer_control import computer_control as cc_func
                            r = await loop.run_in_executor(None, lambda: cc_func(
                                parameters={"action": "type", "text": text}, player=self.ui
                            ))
                            if r and "error" not in str(r).lower():
                                result = f"Typed '{text}' in {app_name or 'app'}, sir."
                    except Exception:
                        pass

            elif name == "assistant":
                # LLM-powered universal assistant — handles ANY natural language request
                request = args.get("request", "")
                if not request:
                    result = "Please tell me what you'd like me to do, sir."
                else:
                    orchestrator = get_llm_orchestrator(ui=self.ui)
                    context = {
                        "last_email_id": getattr(self, "_last_email_id", None),
                        "recent_steps": getattr(self, "_recent_steps", [])[-5:],
                    }
                    r = await loop.run_in_executor(None, lambda: orchestrator.execute(request, context))
                    # Track recent steps for context
                    if not hasattr(self, "_recent_steps"):
                        self._recent_steps = []
                    self._recent_steps.append({"description": request[:50]})
                    result = r if r else "Done."

            elif name == "claude_tool":
                from actions.claude_tool import claude_tool
                r = await loop.run_in_executor(None, lambda: claude_tool(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "claude_session":
                from actions.claude_tool import claude_session
                r = await loop.run_in_executor(None, lambda: claude_session(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "document_search":
                r = await loop.run_in_executor(None, lambda: rag_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "audio_pipeline":
                r = await loop.run_in_executor(None, lambda: audio_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "jarvis_memory":
                r = await loop.run_in_executor(None, lambda: memory_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "screen_intelligence":
                r = await loop.run_in_executor(None, lambda: screen_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "proactive_monitor":
                r = await loop.run_in_executor(None, lambda: proactive_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "smart_home":
                r = await loop.run_in_executor(None, lambda: home_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shell_start":
                from actions.claude_shell import shell_start
                r = await loop.run_in_executor(None, lambda: shell_start(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shell_send":
                from actions.claude_shell import shell_send
                r = await loop.run_in_executor(None, lambda: shell_send(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shell_status":
                from actions.claude_shell import shell_status
                r = await loop.run_in_executor(None, lambda: shell_status(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shell_interrupt":
                from actions.claude_shell import shell_interrupt
                r = await loop.run_in_executor(None, lambda: shell_interrupt(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shell_end":
                from actions.claude_shell import shell_end
                r = await loop.run_in_executor(None, lambda: shell_end(parameters=args, player=self.ui))
                result = r or "Done."

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        logging.getLogger("JARVIS").info(f'OUT {name} -> {str(result)[:80]}')

        # -- Cache the result --------------------------------------------------
        if name in cacheable and isinstance(result, str) and result and not result.startswith("Tool '"):
            with contextlib.suppress(Exception):
                get_cache().set(name, args, result)

        # -- Result: tek cümle söyle, dur --------------------------------------
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            try:
                msg = await self.out_queue.get()
                await self.session.send_realtime_input(media=msg)
            except Exception:
                # WebSocket disconnected -- stop sending
                break

    async def _listen_audio(self):
        logging.getLogger("JARVIS").info('MIC Mic started')
        loop = asyncio.get_event_loop()
        stop_event = asyncio.Event()

        def callback(indata, frames, time_info, status):
            import numpy as np

            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            with self._cooldown_lock:
                on_cooldown = self._speech_cooldown
            # Don't send audio if JARVIS is speaking OR on cooldown after speaking
            if jarvis_speaking:
                # Task 22: Require sustained audio before interruption
                # Measure RMS energy to distinguish real speech from ambient noise/spikes
                audio_chunk = indata[:, 0].astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(audio_chunk**2)))
                if rms > 0.01:  # Real audio above typical ambient noise
                    self._interruption_frames += 1
                    if self._interruption_frames >= self._min_interruption_frames:
                        # Sustained user speech confirmed — trigger interruption
                        self._handle_interruption(self._current_speech_text)
                        self._interruption_frames = 0
                else:
                    # Below threshold — reset the counter so pops/snaps don't trigger
                    self._interruption_frames = 0
                return
            else:
                # Reset counter when JARVIS is not speaking
                self._interruption_frames = 0
            if not on_cooldown and not self.ui.muted:
                data = indata.tobytes()
                # Phase 4: Audio buffer -- keep last 3 seconds in memory
                with self._buffer_lock:
                    self._audio_buffer.append(data)
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

        def _get_buffered_audio(self_ref):
            """Return buffered audio bytes, or empty bytes if buffer is sparse."""
            with self_ref._buffer_lock:
                if len(self_ref._audio_buffer) == 0:
                    return b""
                return b"".join(self_ref._audio_buffer)

        self._get_buffered_audio = lambda: _get_buffered_audio(self)

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                logging.getLogger("JARVIS").info('MIC Mic stream open')
                await stop_event.wait()
        except Exception as e:
            logging.getLogger("JARVIS").info(f'ERROR Mic: {e}')
            raise

    async def _receive_audio(self):
        logging.getLogger("JARVIS").info('RECV Recv started')
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        with contextlib.suppress(Exception):
                            self.audio_in_queue.put_nowait(response.data)
                        # Start speaking immediately when first audio arrives
                        if not self._is_speaking:
                            self.set_speaking(True)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text.strip()
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text.strip()
                            if txt:
                                in_buf.append(txt)

                        # Handle turn completion
                        if sc.turn_complete:
                            self.set_speaking(False)

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                            out_buf = []

                            # Skip processing if input is too short or looks like echo
                            if not full_in or len(full_in) < 5:
                                continue

                            # Phase 4: Improved echo detection -- command hash deduplication
                            if self._is_duplicate_command(full_in):
                                logging.getLogger("JARVIS").info('Duplicate command detected, ignoring')
                                continue

                            # Phase 4: Also use the original word-overlap echo check
                            if full_out and self._is_echo(full_in, full_out):
                                logging.getLogger("JARVIS").info('Echo detected (word overlap), ignoring')
                                continue

                            # Phase 4: Wake word handling -- strip "mark", "jarvis", etc.
                            if self._contains_wake_word(full_in):
                                stripped = self._strip_wake_word(full_in)
                                if stripped:
                                    full_in = stripped
                                    self.ui.write_log(f"You (wake stripped): {full_in}")
                                else:
                                    logging.getLogger("JARVIS").info('Wake word only, no command')
                                    continue

                            # Phase 4: Dynamic cooldown -- update based on command length
                            self._update_dynamic_cooldown(full_in)

                            if full_in and len(full_in) > 5:
                                # Phase 6: Reset tools used tracker for this new turn
                                self._last_tools_used = []

                                # Update conversation buffer
                                conv_mgr = get_conversation_manager()
                                conv_mgr.add_user_turn(full_in)
                                conv_mgr.add_jarvis_turn(full_out)

                                # Phase 6/7: Track conversation turn via _on_turn_complete
                                if hasattr(self, '_ctx'):
                                    try:
                                        self._on_turn_complete(full_in, full_out)
                                    except Exception as e:
                                        logging.getLogger("JARVIS").warning(f"Turn tracking failed: {e}")

                                # Check if summarization is needed
                                if conv_mgr.should_summarize():
                                    threading.Thread(
                                        target=_summarize_conversation,
                                        daemon=True
                                    ).start()

                                # Extract memory in background
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            logging.getLogger("JARVIS").info(f'CALL {fc.name}')
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
                        # -- Boş turn YOK -- bu "Anladım." sorununu yaratıyordu --

        except Exception as e:
            logging.getLogger("JARVIS").info(f'ERROR Recv: {e}')
            traceback.print_exc()
            raise

    async def _play_audio(self):
        logging.getLogger("JARVIS").info('PLAY Play started')
        asyncio.get_event_loop()

        # Sürekli açık output stream -- PyAudio'daki stream.write() davranışıyla aynı
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            logging.getLogger("JARVIS").info(f'ERROR Play: {e}')
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                logging.getLogger("JARVIS").info('CONN Connecting...')
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=50)

                    logging.getLogger("JARVIS").info('OK Connected.')
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                logging.getLogger("JARVIS").info(f'[!] {e}')
                traceback.print_exc()

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            logging.getLogger("JARVIS").info('RETRY Reconnecting in 3s...')
            await asyncio.sleep(3)


def main():
    # Check startup arguments
    start_minimized = "--start-minimized" in sys.argv or "-m" in sys.argv

    # Pre-generate and cache intro music files in background (no delay on first play)
    preload_music()

    # Start the task scheduler (background proactive task runner)
    scheduler = get_scheduler()
    scheduler.start()

    # Start the proactive monitor (JARVIS watches and speaks when it matters)
    # Use a SpeakRef that gets populated once JarvisLive is created
    from core.proactive_monitor import SpeakRef
    jarvis_speak_ref = SpeakRef()
    try:
        from actions.proactive_action import get_monitor
        proactive = get_monitor()
        proactive._speak_ref = jarvis_speak_ref
        proactive.start()
        logging.getLogger("JARVIS").info('PROACTIVE Proactive monitor started')
    except Exception as e:
        logging.getLogger("JARVIS").info(f'PROACTIVE Monitor failed to start: {e}')

    # Initialize JARVIS memory (4-layer system)
    try:
        from memory.j_memory import get_memory as get_j_memory
        j_memory = get_j_memory()
        logging.getLogger("JARVIS").info('MEMORY Memory system ready')
    except Exception as e:
        logging.getLogger("JARVIS").info(f'MEMORY Failed to initialize: {e}')

    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()

        # Setup lock monitor for unlock events
        lock_monitor = get_lock_monitor()
        briefing = get_briefing()

        # Register unlock callback to run briefing
        def on_unlock():
            ui.write_log("SYS: Session unlocked - running briefing...")
            briefing.set_speak(jarvis_speak_ref)
            # Run briefing in background thread
            threading.Thread(
                target=lambda: asyncio.run(briefing.run_full_briefing(ui=ui)),
                daemon=True
            ).start()

        lock_monitor.register_callback("unlock", on_unlock)
        lock_monitor.start()

        # Start the System HUD overlay (JARVIS-blue stats panel)
        hud = get_system_hud()
        hud.start()

        # Start the Cinematic HUD (DearPyGui holographic overlay)
        try:
            cinematic = get_cinematic_hud()
            if cinematic._dpg is not None:
                cinematic.run_threaded()
                ui.write_log("SYS: Cinematic HUD active.")
                logging.getLogger("JARVIS").info('HUD: Cinematic JARVIS display started')

                # Task 15: Start the Ambient Awareness Dashboard
                from core.system_snapshot import SystemSnapshot
                system_snapshot = SystemSnapshot()
                cinematic.show_ambient_dashboard(True, system_snapshot)
                logging.getLogger("JARVIS").info('HUD: Ambient Awareness Dashboard started')
        except Exception as e:
            logging.getLogger("JARVIS").info(f'HUD: Cinematic HUD failed to start: {e}')

        # Start the System Tray icon (JARVIS presence in notification area)
        tray = get_system_tray()
        tray.start()
        ui.write_log("SYS: System tray active.")

        # Face Recognition greeting — check who's at the desk
        def _do_face_greeting():
            """Quick face check: greet by name if recognized. Waits for JarvisLive to be ready."""
            try:
                import cv2, numpy as np

                # Wait up to 5s for JarvisLive to wire the speak ref
                for _ in range(50):
                    if jarvis_speak_ref._func is not None:
                        break
                    time_module.sleep(0.1)
                else:
                    return  # Timed out

                auth = FaceAuthenticator()
                auth.initialize()
                if not auth.is_enabled:
                    return  # No camera or no faces enrolled

                cam = cv2.VideoCapture(0)
                if not cam.isOpened():
                    return

                ret, frame = cam.read()
                cam.release()
                if not ret:
                    return

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                name = auth.is_user_present(rgb)
                if name:
                    greeting = f"Good to see you, {name}."
                else:
                    greeting = "Good evening, sir."
                jarvis_speak_ref(greeting)
            except Exception:
                pass  # Silent fail — face auth is optional

        threading.Thread(target=_do_face_greeting, daemon=True, name="FaceGreeting").start()

        # Start Gesture Control (wave to wake, thumbs up to acknowledge, fist to silence)
        try:
            cinematic = get_cinematic_hud()
        except Exception:
            cinematic = None

        def _gesture_speak(text: str):
            jarvis_speak_ref(text)

        _gesture = GestureController(speak_func=_gesture_speak, hud=cinematic)
        _gesture.initialize()
        if _gesture._hands:
            _gesture.start()
            ui.write_log("SYS: Gesture control active.")
            logging.getLogger("JARVIS").info('GESTURE: Camera gesture control started')
        else:
            logging.getLogger("JARVIS").info('GESTURE: Gesture control unavailable (mediapipe or camera missing)')

        # Start the Audio Pipeline (wake word detection — say "Hey JARVIS" to activate)
        try:
            from actions.audio_action import get_pipeline
            pipeline = get_pipeline()
            # Wire pipeline responses to jarvis
            pipeline.on_response = jarvis_speak_ref
            pipeline.start()
            ui.write_log("SYS: Wake word listening active.")
            logging.getLogger("JARVIS").info("AUDIO Pipeline started — say 'Hey JARVIS' to activate")
        except Exception as e:
            logging.getLogger("JARVIS").info(f'AUDIO Pipeline failed to start: {e}')

        # Start the Screen Watchdog (JARVIS's proactive eyes)
        watchdog = get_screen_watchdog()
        watchdog.set_speak(jarvis_speak_ref)
        watchdog.start()

        # Also register screen watchdog with proactive monitor
        try:
            proactive.register_monitor(
                check_func=lambda: {"screen": watchdog.get_last_description()},
                on_change_func=lambda result: logger.debug(f"[Proactive] Screen: {result.get('screen', '')[:80]}")
            )
        except Exception as e:
            logging.getLogger("JARVIS").info(f'PROACTIVE Watchdog registration failed: {e}')

        jarvis = JarvisLive(ui)
        jarvis_speak_ref.set(jarvis.speak)  # Wire proactive monitor + briefing to jarvis's speak

        # Task 18: Wire GestureController into ConversationContextEngine
        _gesture.set_conversation_context(jarvis._ctx)
        proactive.set_dnd_check(_gesture.is_do_not_disturb)

        # Wire emotion detection callback from audio pipeline to TTS
        try:
            pipeline = get_pipeline()
            pipeline.on_emotion = jarvis._on_emotion
        except Exception:
            pass

        # Task 17: Get resumption greeting from previous session
        greeting = jarvis._session_mgr.get_resumption_greeting()
        if greeting:
            jarvis.speak(greeting)

        # Phase 6: Wire CCE and MemoryBridge into proactive monitor
        proactive.set_context_engine(jarvis._ctx)
        # Task 16: Wire pattern learner into proactive monitor if supported
        if hasattr(proactive, 'set_pattern_learner'):
            proactive.set_pattern_learner(jarvis._pattern_learner)

        # Wire cinematic HUD to JarvisLive state changes
        def _sync_hud_state(state_name: str):
            try:
                cinematic = get_cinematic_hud()
                cinematic.set_state(state_name.lower())
            except Exception:
                pass

        # Patch ui.set_state to also update the cinematic HUD
        _orig_set_state = ui.set_state
        def _set_state_with_hud(state_name: str):
            _orig_set_state(state_name)
            _sync_hud_state(state_name)
        ui.set_state = _set_state_with_hud

        # Wire proactive monitor alerts to the cinematic HUD response display
        def _hud_alert(msg: str):
            try:
                cinematic = get_cinematic_hud()
                cinematic.show_response(msg)
            except Exception:
                pass
        proactive._on_alert = _hud_alert

        # Run initial briefing on startup
        if not start_minimized:
            briefing.set_speak(jarvis.speak)
            ui.write_log("SYS: Running welcome briefing...")
            threading.Thread(
                target=lambda: asyncio.run(briefing.run_full_briefing(ui=ui)),
                daemon=True
            ).start()

        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            logging.getLogger(__name__).info('\\n[X] Shutting down...')
            # Phase 6: Run session review and stop JarvisLive
            try:
                jarvis.stop()
            except Exception:
                pass
            # Play JARVIS shutdown farewell
            try:
                from core.intro_music import play_shutdown_scene
                play_shutdown_scene()
            except Exception:
                pass
            # Speak a farewell using local TTS
            try:
                tts = _get_local_tts()
                if tts:
                    tts.speak("Shutting down, sir. Good night.", blocking=False)
            except Exception:
                pass
            scheduler.stop()
            lock_monitor.stop()
            # Stop the system HUD, screen watchdog, and audio pipeline
            try:
                get_system_hud().stop()
            except Exception:
                pass
            try:
                get_cinematic_hud().stop()
            except Exception:
                pass
            try:
                get_system_tray().stop()
            except Exception:
                pass
            try:
                get_screen_watchdog().stop()
            except Exception:
                pass
            try:
                from actions.audio_action import get_pipeline
                p = get_pipeline()
                p.stop()
            except Exception:
                pass
            try:
                _gesture.stop()
            except (NameError, AttributeError):
                pass
            except Exception:
                pass

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
