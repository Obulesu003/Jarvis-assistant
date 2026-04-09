# actions/web_search.py
# MARK XXV -- Web Search
# Primary: Gemini google_search (yeni google.genai SDK)
# Fallback: DuckDuckGo (ddgs)

import logging  # migrated from print()
import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None

def _get_api_key() -> str:
    if _get_gemini_key is not None:
        return _get_gemini_key()
    BASE_DIR = get_base_dir()
    API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
    with open(API_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _gemini_search(query: str) -> str:
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=query,
        config={"tools": [{"google_search": {}}]}
    )
    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text
    if not text.strip():
        msg = "Empty response"
        raise ValueError(msg)
    return text.strip()



def _ddg_search(query: str, max_results: int = 6) -> list:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title", ""),
                "snippet": r.get("body", ""),
                "url":     r.get("href", ""),
            })
    return results

def _format_ddg(query: str, results: list) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list, aspect: str) -> str:
    query = f"Compare {', '.join(items)} in terms of {aspect}. Give specific facts and data."
    try:
        return _gemini_search(query)
    except Exception as e:
        logging.getLogger("WebSearch").warning(f"Gemini compare failed: {e}")
        all_results = {}
        for item in items:
            try:
                all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
            except Exception:
                all_results[item] = []
        lines = [f"Comparison -- {aspect.upper()}\n{'-'*40}"]
        for item in items:
            lines.append(f"\n> {item}")
            for r in all_results.get(item, [])[:2]:
                if r.get("snippet"):
                    lines.append(f"  * {r['snippet']}")
        return "\n".join(lines)


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode", "search").lower()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general")

    if not query and not items:
        return "Please provide a search query, sir."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    logging.getLogger("WebSearch").info('Query: {query!r}  Mode: {mode}')

    try:
        if mode == "compare" and items:
            logging.getLogger("WebSearch").info('Comparing: {items}')
            result = _compare(items, aspect)
            logging.getLogger("WebSearch").debug('Compare done.')
            return result

        logging.getLogger("WebSearch").info('Gemini search...')
        try:
            result = _gemini_search(query)
            logging.getLogger("WebSearch").debug('Gemini OK.')
            return result
        except Exception as e:
            logging.getLogger("WebSearch").warning('Gemini failed ({e}), trying DDG...')
            results = _ddg_search(query)
            result  = _format_ddg(query, results)
            logging.getLogger("WebSearch").debug('DDG: {len(results)} results.')
            return result

    except Exception as e:
        logging.getLogger("WebSearch").error('Failed: {e}')
        return f"Search failed, sir: {e}"
