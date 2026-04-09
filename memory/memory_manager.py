"""
memory_manager.py -- MARK XXV Hafıza Sistemi
============================================
Düzeltmeler:
  - _MEMORY_EVERY_N_TURNS: 3 -> 1 (her turda kontrol)
  - Stage 1 YES/NO check daha geniş kriterlere sahip
  - Extraction prompt daha kapsamlı ve agresif
  - Projeleri, favori şeyleri, arkadaşları daha iyi yakalar
"""

import logging  # migrated from print()
import json
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 400


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":    {},
        "projects":       {},
        "relationships":  {},
        "wishes":         {},
        "notes":          {},
        "habits":         {},  # recurring behaviours: sleep schedule, work hours, routines
        "routines":       {},  # multi-step sequences: morning routine, commute steps, etc.
        "context":         {},  # current situation: current project, ongoing issue, recent events
        "learned_fixes":   {},  # solutions to recurring problems: known bugs, workaround recipes
    }


def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        logging.getLogger("Memory").info('INFO No memory file found, starting fresh')
        return _empty_memory()

    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                # Count non-empty memory entries for debug
                non_empty = sum(1 for v in data.values() if isinstance(v, dict) and len(v) > 0)
                logging.getLogger("Memory").info('INFO Loaded {non_empty} categories from {MEMORY_PATH}')
                return data
            logging.getLogger("Memory").info('WARN Memory file corrupted (not a dict), starting fresh')
            return _empty_memory()
        except Exception as e:
            logging.getLogger("Memory").info('WARN Load error: {e}, starting fresh')
            return _empty_memory()


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "..."
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            if isinstance(value, dict) and "value" in value:
                new_val = _truncate_value(str(value["value"]))
            else:
                new_val = _truncate_value(str(value))

            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        logging.getLogger("Memory").info('Saved: {list(memory_update.keys())}')
    return memory


def should_extract_memory(user_text: str, jarvis_text: str, api_key: str) -> bool:
    """
    Fast heuristic check -- no API call needed. ONLY triggers on explicit personal info keywords.
    This reduces unnecessary LLM calls by skipping extraction when no personal data is mentioned.
    """
    text = user_text.lower()
    # Explicit personal info keywords - only these trigger extraction
    indicators = [
        "i am ", "i'm ", "my name is", "i live", "i work", "i'm from",
        "my birthday", "years old", "i like", "i love", "i hate", "i want",
        "i need", "i'm building", "i'm working on", "my project", "my friend",
        "my boss", "my wife", "my husband", "my brother", "my sister",
        "my dad", "my mom", "my colleague", "favourite", "favorite",
        "hobby", "hobbies", "dream", "goal", "plan to", "going to buy",
        "want to buy", "next week", "tomorrow", "monday", "tuesday",
        "wednesday", "thursday", "friday", "saturday", "sunday",
        "my girlfriend", "my boyfriend", "my kids", "my son", "my daughter",
        "my family", "my home", "i study", "i study at", "i graduated",
        "call me", "you can call me", "my nickname", "i'm from",
        "i prefer", "i usually", "i always", "i never", "i sometimes",
        "my schedule", "my routine", "i wake up", "i go to sleep",
    ]
    return any(kw in text for kw in indicators)


def extract_memory(user_text: str, jarvis_text: str, api_key: str) -> dict:
    """
    Stage 2: Detaylı çıkarım. Her iki tarafı da analiz eder.
    """
    try:
        from google.genai import Client
        client = Client(api_key=api_key)

        combined = f"User: {user_text[:500]}\nJarvis: {jarvis_text[:300]}"

        prompt = (
            f"Extract ALL memorable personal facts from this conversation. Any language.\n"
            f"Return ONLY valid JSON. Use {{}} if truly nothing is worth saving.\n\n"
            f"Category guide:\n"
            f"  identity      -> name, age, birthday, city, country, job, school, nationality, language\n"
            f"  preferences   -> ANY favorite or preferred thing:\n"
            f"                  favorite_food, favorite_color, favorite_music, favorite_film,\n"
            f"                  favorite_game, favorite_sport, favorite_book, favorite_artist,\n"
            f"                  favorite_country, hobbies, interests, dislikes, etc.\n"
            f"  projects      -> projects being built, ongoing work, goals, ideas in progress\n"
            f"                  (e.g. mark_xxv: 'Building a JARVIS-like AI assistant')\n"
            f"  relationships -> people mentioned: friends, family, partner, colleagues\n"
            f"                  (e.g. best_friend_ali: 'Best friend, met in university')\n"
            f"  wishes         -> future plans, things to buy, travel plans, dreams\n"
            f"  notes          -> anything else worth remembering\n"
            f"  habits         -> recurring behaviours: sleep hours, work schedule, when active, coffee breaks, exercise times\n"
            f"  routines       -> multi-step sequences: morning routine, how they start the day, commute steps, shutdown routine\n"
            f"  context        -> current situation: what project they're working on, what's the current blocker, what's ongoing\n"
            f"  learned_fixes   -> solutions to recurring problems: known bugs they've encountered, workaround recipes they've used\n\n"
            f"IMPORTANT:\n"
            f"- Be LIBERAL: if something MIGHT be worth remembering, include it.\n"
            f"- Extract from BOTH user and Jarvis turns.\n"
            f"- Skip: weather, reminders, search results, one-time commands.\n"
            f"- Use concise English values regardless of conversation language.\n\n"
            f"Format:\n"
            f'{{"identity":{{"name":{{"value":"Ali"}}}},\n'
            f' "preferences":{{"favorite_color":{{"value":"blue"}}, "hobby":{{"value":"gaming"}}}},\n'
            f' "projects":{{"mark_xxv":{{"value":"JARVIS-like AI assistant on Windows"}}}},\n'
            f' "relationships":{{"friend_yusuf":{{"value":"close friend"}}}},\n'
            f' "wishes":{{"buy_guitar":{{"value":"wants an acoustic guitar"}}}},\n'
            f' "notes":{{"reminder_tone":{{"value":"likes formal tone"}}}},\n'
            f' "habits":{{"late_nighter":{{"value":"most productive after 10pm"}}}},\n'
            f' "routines":{{"morning":{{"value":"coffee then email then code"}}}},\n'
            f' "context":{{"current_project":{{"value":"building MARK XXXV voice assistant"}}}},\n'
            f' "learned_fixes":{{"pyautogui_broken":{{"value":"use playwright instead for WhatsApp"}}}}}}\n\n'
            f"Conversation:\n{combined}\n\nJSON:"
        )
        raw = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt
        ).text.strip()

        import re
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        if not raw or raw == "{}":
            return {}

        return json.loads(raw)

    except json.JSONDecodeError:
        return {}
    except Exception as e:
        if "429" not in str(e):
            logging.getLogger("Memory").info('WARN Extract failed: {e}')
        return {}


def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:10]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    habits = memory.get("habits", {})
    if habits:
        lines.append("")
        lines.append("Habits & schedule:")
        for key, entry in list(habits.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    routines = memory.get("routines", {})
    if routines:
        lines.append("")
        lines.append("Routines:")
        for key, entry in list(routines.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    context = memory.get("context", {})
    if context:
        lines.append("")
        lines.append("Current context:")
        for key, entry in list(context.items())[:6]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    learned_fixes = memory.get("learned_fixes", {})
    if learned_fixes:
        lines.append("")
        lines.append("Learned fixes & workarounds:")
        for key, entry in list(learned_fixes.items())[:8]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON -- use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "..."

    return result + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes",
             "notes", "habits", "routines", "context", "learned_fixes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"

# Alias -- eski import'larla uyumluluk için
forget_memory = forget
