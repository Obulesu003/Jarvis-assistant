# actions/youtube_video.py
# YouTube control via Playwright -- reliable browser automation instead of
# fragile CV2 thumbnail detection.

import logging  # migrated from print()
import asyncio
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pyautogui

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False

try:
    from playwright.async_api import TimeoutError as PWTimeout
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


try:
    from core.api_key_manager import get_gemini_key as _get_gemini_key
except ImportError:
    _get_gemini_key = None

BASE_DIR = get_base_dir()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _get_api_key() -> str:
    if _get_gemini_key is not None:
        return _get_gemini_key()
    with open(BASE_DIR / "config" / "api_keys.json", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


# -- Playwright browser instance (singleton) ------------------------------------

_playwright = None
_browser    = None
_context    = None


async def _get_browser_context(incognito: bool = False):
    """Returns a page using system Chrome via channel='chrome' — inherits all sessions."""
    global _playwright, _browser, _context

    if _playwright is None:
        _playwright = await async_playwright().start()

    if _browser is None or not _browser.is_connected():
        try:
            _browser = await _playwright.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--start-maximized"],
            )
            logging.getLogger("YouTube").debug("Connected to system Chrome via channel='chrome")
        except Exception as e:
            logging.getLogger("YouTube").error("channel='chrome' failed: {e}")
            logging.getLogger("YouTube").info('Ensure Google Chrome is your default browser.')
            raise

    # Fresh context for YouTube (keeps your existing sessions separate)
    if _context is None or incognito:
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
        )

    return await _context.new_page()


async def _close_browser():
    """Cleanly close browser resources."""
    global _playwright, _browser, _context
    try:
        if _context:
            await _context.close()
            _context = None
        if _browser:
            await _browser.close()
            _browser = None
        if _playwright:
            await _playwright.stop()
            _playwright = None
    except Exception:
        pass


# -- Helpers --------------------------------------------------------------------

def _get_default_browser_display_name() -> str:
    """Returns the display name of the default browser."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
        )
        prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
        winreg.CloseKey(key)
        mapping = {
            "chrome": "Google Chrome", "firefox": "Firefox",
            "opera": "Opera", "brave": "Brave",
            "vivaldi": "Vivaldi", "msedge": "Microsoft Edge",
        }
        for k, name in mapping.items():
            if k in prog_id:
                return name
    except Exception:
        pass
    return "Google Chrome"


def _extract_video_id(url: str) -> str | None:
    patterns = [r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})"]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def _ask_for_url(prompt_text: str = "YouTube video URL:") -> str | None:
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
        url = simpledialog.askstring("J.A.R.V.I.S", prompt_text, parent=root)
        return url.strip() if url else None
    except Exception:
        return None


def _get_transcript(video_id: str) -> str | None:
    if not _TRANSCRIPT_OK:
        return None
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        for langs in [
            ["en", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"],
        ]:
            try:
                transcript = transcript_list.find_manually_created_transcript(langs)
                break
            except Exception:
                pass
        if transcript is None:
            for langs in [
                ["en", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"],
            ]:
                try:
                    transcript = transcript_list.find_generated_transcript(langs)
                    break
                except Exception:
                    pass
        if transcript is None:
            for t in transcript_list:
                transcript = t
                break
        if transcript is None:
            return None
        fetched = transcript.fetch()
        return " ".join(entry["text"] for entry in fetched)
    except Exception as e:
        logging.getLogger("YouTube").info(f"Transcript fetch failed: {e}")
        return None


def _summarize_with_gemini(transcript: str, video_url: str) -> str:
    from google.genai import Client
    from google.genai.types import GenerateContentConfig

    client = Client(api_key=_get_api_key())
    max_chars = 80000
    truncated = transcript[:max_chars] + ("..." if len(transcript) > max_chars else "")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Please summarize this YouTube video transcript:\n\n{truncated}",
        config=GenerateContentConfig(
            system_instruction=(
                "You are JARVIS, Tony Stark's AI assistant. "
                "Summarize YouTube video transcripts clearly and concisely. "
                "Structure: 1-sentence overview, then 3-5 key points. "
                "Be direct. Address the user as 'sir'. "
                "Match the language of the transcript."
            )
        )
    )
    return response.text.strip()


def _save_to_notepad(content: str, video_url: str) -> str:
    from datetime import datetime
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"youtube_summary_{ts}.txt"
    desktop  = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / filename
    header = (
        f"JARVIS -- YouTube Summary\n"
        f"{'-' * 50}\n"
        f"URL    : {video_url}\n"
        f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'-' * 50}\n\n"
    )
    filepath.write_text(header + content, encoding="utf-8")
    system = sys.platform
    if system == "win32":
        subprocess.Popen(["notepad.exe", str(filepath)])
    elif system == "darwin":
        subprocess.Popen(["open", "-t", str(filepath)])
    else:
        subprocess.Popen(["xdg-open", str(filepath)])
    return str(filepath)


def _scrape_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        info = {}
        if m := re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', html):
            info["title"]   = m.group(1)
        if m := re.search(r'"ownerChannelName":"([^"]+)"', html):
            info["channel"] = m.group(1)
        if m := re.search(r'"viewCount":"(\d+)"', html):
            info["views"]   = f"{int(m.group(1)):,}"
        if m := re.search(r'"lengthSeconds":"(\d+)"', html):
            secs = int(m.group(1))
            info["duration"] = f"{secs // 60}:{secs % 60:02d}"
        if m := re.search(r'"label":"([0-9,]+ likes)"', html):
            info["likes"] = m.group(1)
        return info
    except Exception as e:
        logging.getLogger("YouTube").info('Info scrape failed: {e}')
        return {}


def _scrape_trending(region: str = "TR", max_results: int = 8) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        titles   = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        channels = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)
        results, seen = [], set()
        for i, title in enumerate(titles):
            if title in seen or len(title) < 5:
                continue
            seen.add(title)
            ch = channels[i] if i < len(channels) else "Unknown"
            results.append({"rank": len(results) + 1, "title": title, "channel": ch})
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        logging.getLogger("YouTube").info('Trending scrape failed: {e}')
        return []


# -- Action handlers -------------------------------------------------------------

def _handle_play(parameters: dict, player) -> str:
    """Play a YouTube video using Playwright -- no more CV2 thumbnail detection."""
    if not _PLAYWRIGHT_OK:
        # Fallback to old PyAutoGUI method
        return _handle_play_pyautogui(parameters, player)

    query = parameters.get("query", "").strip()
    if not query:
        return "Please tell me what you'd like to watch, sir."

    if player:
        player.write_log(f"[YouTube] Playing via Playwright: {query}")

    try:
        return asyncio.run(_play_youtube(query))
    except Exception as e:
        logging.getLogger("YouTube").info('Playwright failed, falling back: {e}')
        with contextlib.suppress(Exception):
            asyncio.run(_close_browser())
        return _handle_play_pyautogui(parameters, player)


async def _play_youtube(query: str) -> str:
    """Uses Playwright to navigate YouTube and click the first video."""
    page = await _get_browser_context()

    search_url = (
        f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
    )
    await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
    await page.wait_for_timeout(2000)

    # Wait for video links to appear
    try:
        # YouTube search results: first video is usually the first 'ytd-video-renderer'
        # Try multiple selectors for reliability
        selectors = [
            "ytd-video-renderer a#video-title",
            "ytd-video-renderer a#thumbnail",
            "ytd-rich-item-renderer a#thumbnail",
            "a.ytd-video-renderer",
            "ytd-video-renderer .yt-simple-endpoint",
        ]
        video_link = None
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    video_link = el
                    break
            except Exception:
                continue

        if video_link:
            href = await video_link.get_attribute("href")
            if href:
                video_url = f"https://www.youtube.com{href}"
                await page.goto(video_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                # Click to remove overlay if needed
                with contextlib.suppress(Exception):
                    await page.locator("button.ytp-play-button").click(timeout=3000)
                # Leave browser open -- user watches from here
                return f"Playing YouTube video: {query}"
        # If no video link found, just navigate to search and let user click
        return f"Opened YouTube search for: {query}. Please click a video to watch."

    except PWTimeout:
        await _close_browser()
        return f"Timed out loading YouTube for: {query}, sir."


def _handle_play_pyautogui(parameters: dict, player) -> str:
    """Fallback: old PyAutoGUI-based playback."""
    import time as t
    query = parameters.get("query", "").strip()
    if not query:
        return "Please tell me what you'd like to watch, sir."

    if player:
        player.write_log(f"[YouTube] Playing via fallback: {query}")

    browser_name = _get_default_browser_display_name()
    pyautogui.press("win")
    t.sleep(0.5)
    pyautogui.write(browser_name, interval=0.04)
    t.sleep(0.7)
    pyautogui.press("enter")
    t.sleep(2.5)

    search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
    pyautogui.hotkey("ctrl", "l")
    t.sleep(0.3)
    pyautogui.write(search_url, interval=0.02)
    pyautogui.press("enter")
    t.sleep(4.0)

    screen_w, screen_h = pyautogui.size()
    # Click approximate position of first YouTube search result
    pyautogui.click(screen_w // 2, int(screen_h * 0.40))
    return f"Attempted to play YouTube video for: {query}"


def _handle_summarize(parameters: dict, player, speak) -> str:
    if not _TRANSCRIPT_OK:
        return "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"

    url = _ask_for_url("Please paste the YouTube video URL:")
    if not url:
        return "No URL provided, sir. Summary cancelled."
    if not _is_valid_youtube_url(url):
        return "That doesn't appear to be a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, sir."

    if player:
        player.write_log(f"[YouTube] Summarizing: {url}")
    if speak:
        speak("Fetching the transcript now, sir. One moment.")

    transcript = _get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, sir."

    if speak:
        speak("Transcript retrieved. Generating summary now.")

    try:
        summary = _summarize_with_gemini(transcript, url)
    except Exception as e:
        return f"Summary generation failed, sir: {e}"

    if speak:
        speak(summary)

    if parameters.get("save", False):
        saved_path = _save_to_notepad(summary, url)
        return f"Summary complete and saved to Desktop: {saved_path}"

    return summary


def _handle_get_info(parameters: dict, player, speak) -> str:
    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url or not _is_valid_youtube_url(url):
        return "Please provide a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID, sir."

    if player:
        player.write_log(f"[YouTube] Getting info: {url}")

    info = _scrape_video_info(video_id)
    if not info:
        return "Could not retrieve video information, sir."

    lines = []
    for key in ("title", "channel", "views", "duration", "likes"):
        if key in info:
            lines.append(f"{key.capitalize()}: {info[key]}")

    result = "\n".join(lines)
    if speak:
        speak(f"Here's the video info, sir. {result.replace(chr(10), '. ')}")
    return result


def _handle_trending(parameters: dict, player, speak) -> str:
    region = parameters.get("region", "TR").upper()
    if player:
        player.write_log(f"[YouTube] Trending: {region}")

    trending = _scrape_trending(region=region, max_results=8)
    if not trending:
        return f"Could not fetch trending videos for region {region}, sir."

    lines = [f"Top trending videos in {region}:"]
    for item in trending:
        lines.append(f"{item['rank']}. {item['title']} -- {item['channel']}")

    result = "\n".join(lines)
    if speak:
        top3 = trending[:3]
        spoken = "Here are the top trending videos, sir. " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)
    return result


_ACTION_MAP = {
    "play":      _handle_play,
    "summarize": _handle_summarize,
    "get_info":  _handle_get_info,
    "trending":  _handle_trending,
}


def youtube_video(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    params  = parameters or {}
    action  = params.get("action", "play").lower().strip()

    if player:
        player.write_log(f"[YouTube] Action: {action}")

    logging.getLogger("YouTube").info('Action: {action}  Params: {params}')

    handler = _ACTION_MAP.get(action)
    if handler is None:
        return f"Unknown YouTube action: '{action}'. Available: play, summarize, get_info, trending."

    try:
        if action == "play":
            return handler(params, player) or "Done."
        return handler(params, player, speak) or "Done."
    except Exception as e:
        logging.getLogger("YouTube").error('Error in {action}: {e}')
        return f"YouTube {action} failed, sir: {e}"
