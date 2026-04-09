# JARVIS Enhancement — Integration Guide

This guide explains what was built and how to enable each new feature.

## What Was Built

All 9 phases have been implemented:

| Phase | Feature | Files | Status |
|-------|---------|-------|--------|
| 1 | Audio Pipeline (wake word → STT → TTS) | `core/audio_pipeline.py`, `wake_word.py`, `vad.py`, `stt_engine.py`, `tts_engine.py` | Ready |
| 2 | 4-Layer Memory System | `memory/j_memory.py`, `extractor.py` | Ready |
| 3 | Screen Intelligence | `core/screen_monitor.py` | Ready |
| 4 | JARVIS HUD | `ui/hud.py` | Ready |
| 5 | Proactive Monitor | `core/proactive_monitor.py` | Auto-starts |
| 6 | Advanced Perception | `core/face_auth.py`, `gesture_control.py` | Ready |
| 7 | Smart Home + Windows Control | `integrations/home_assistant/home_assistant_adapter.py` | Ready |
| 8 | Document RAG | `memory/rag_pipeline.py` | Ready |
| 9 | Personality Engine | `core/personality.py` | Ready |

All 6 new tools are wired into `main.py`:
- `audio_pipeline` — controls the local audio pipeline
- `jarvis_memory` — accesses the 4-layer memory
- `screen_intelligence` — JARVIS sees your screen
- `proactive_monitor` — controls proactive monitoring
- `smart_home` — Home Assistant control
- `document_search` — RAG document search (already existed)

---

## Phase 1: Audio Pipeline — Fixes 15-Second Latency

**The biggest improvement.** Replaces slow cloud STT with local models.

### Install Dependencies

```bash
# Core audio models (CPU-only)
pip install openwakeword
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install faster-whisper
pip install sounddevice numpy

# Piper TTS (local voice)
# Option A: npm install -g piper-tts (faster)
# Option B: pip install piper-tts (Python wrapper)

# Download British voice (JARVIS feel)
mkdir -p models/voices
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx -P models/voices/
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx.json -P models/voices/
```

### Test It

```python
from core.audio_pipeline import JARVISAudioPipeline

pipeline = JARVISAudioPipeline()
pipeline.initialize()
pipeline.start()  # JARVIS listens for "Hey JARVIS"
```

### Voice Commands

```
"Say: Start listening for wake word" → audio_pipeline(start)
"Say: Stop listening" → audio_pipeline(stop)
"Say: Check audio status" → audio_pipeline(status)
```

---

## Phase 2: 4-Layer Memory

JARVIS now remembers everything about you across sessions.

### Install Dependencies

```bash
pip install chromadb networkx
```

### Voice Commands

```
"What do you remember about me?" → jarvis_memory(recall, query: me)
"Remember that I work at Shop Sore" → jarvis_memory(learn, subject: Bobby, relation: works_at, object: Shop Sore)
"What did we discuss last time?" → jarvis_memory(recent)
"Teach me a new skill" → jarvis_memory(teach)
"What do you know about my projects?" → jarvis_memory(what_do_you_know, query: projects)
```

### Memory Layers

1. **Working** — session context (5-min TTL)
2. **Episodic** — conversation history (ChromaDB, searchable)
3. **Semantic** — facts about you (NetworkX + ChromaDB graph)
4. **Procedural** — taught skills (JSON file)

---

## Phase 3: Screen Intelligence

JARVIS sees your screen using Gemini Vision (free).

### Install Dependencies

```bash
pip install mss Pillow easyocr
```

### Voice Commands

```
"What's on my screen?" → screen_intelligence(describe)
"Read the text on screen" → screen_intelligence(text)
"Take a screenshot" → screen_intelligence(capture)
"Describe what I'm working on" → screen_intelligence(analyze)
"What's the active window?" → screen_intelligence(window)
```

---

## Phase 4: JARVIS HUD

Transparent always-on-top overlay showing JARVIS status.

### Install Dependencies

```bash
pip install dearpygui
```

### Start the HUD

```python
from ui.hud import start_hud
start_hud()  # Runs in background thread
```

The HUD shows:
- Status indicator (idle/listening/processing/speaking)
- Live clock
- Weather
- Reminders
- Screen context
- Response text
- Audio waveform

---

## Phase 5: Proactive Monitor

JARVIS watches and speaks when things change. **Already auto-started at boot.**

Monitors:
- New unread emails (announces sender + subject)
- Upcoming calendar events (warns 10-20 min before)
- System health (CPU >95%, disk <5GB, battery <10%)
- Custom monitors (via `register_monitor`)

### Voice Commands

```
"Stop watching for me" → proactive_monitor(stop)
"Start watching for me" → proactive_monitor(start)
```

---

## Phase 6: Advanced Perception

### Face Recognition

```bash
pip install insightface
```

```python
from core.face_auth import FaceAuthenticator
auth = FaceAuthenticator()
auth.initialize()
# Take a selfie and enroll:
auth.enroll_user(screenshot_array, "Bobby")
```

Then JARVIS only responds when it sees your face.

### Gesture Control

```bash
pip install mediapipe opencv-python
```

```python
from core.gesture_control import GestureController
gc = GestureController(speak_func=speak, hud=hud)
gc.initialize()
gc.start()  # Camera opens for gesture recognition
```

Gestures:
- Thumbs up → acknowledge
- Thumbs down → cancel
- Open palm → pause
- Fist → silence

---

## Phase 7: Smart Home (Home Assistant)

### Setup

1. Install [Home Assistant](https://www.home-assistant.io/)
2. Create a Long-Lived Access Token in HA
3. Add token to config or environment variable

```python
from integrations.home_assistant.home_assistant_adapter import HomeAssistantAdapter
ha = HomeAssistantAdapter(
    url="http://hassio.local:8123",  # Your HA URL
    token="your-ha-long-lived-token"  # From HA profile
)
```

### Voice Commands

```
"Turn on living room lights" → smart_home(turn_on, entity: light.living_room)
"Set bedroom to 22 degrees" → smart_home(temperature, entity: climate.bedroom, temp: 22)
"What's the front door state?" → smart_home(state, entity: lock.front_door)
"List all my devices" → smart_home(list)
"Turn off all lights" → smart_home(turn_off, entity: group.all_lights)
```

---

## Phase 8: Document RAG

JARVIS indexes your documents and answers questions about them.

### Install Dependencies

```bash
pip install chromadb fitz python-docx pyyaml
```

### Voice Commands

```
"Index my Documents folder" → document_search(index, folder: Documents)
"What does my contract say about X?" → document_search(query, question: ...)
"How many documents are indexed?" → document_search(stats)
```

Supports: PDF, DOCX, TXT, MD, PY, JS, CSV, JSON, YAML

---

## Phase 9: Personality Engine

JARVIS's soul — British-inflected, dry wit, calm authority.

Currently integrated into the LLM orchestrator via `core/personality.py`.
The system prompt in `core/prompt.txt` can be enhanced with the JARVIS character.

---

## Quick Install All

```bash
# Audio Pipeline
pip install openwakeword torch --index-url https://download.pytorch.org/whl/cpu faster-whisper sounddevice numpy

# Memory & RAG
pip install chromadb networkx

# Screen & Vision
pip install mss Pillow easyocr

# Advanced Perception
pip install insightface mediapipe opencv-python

# HUD
pip install dearpygui

# System Control
pip install psutil pyautogui pycaw comtypes

# Download Piper voice
mkdir -p models/voices
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx -P models/voices/
```

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────┐
│  ALWAYS-ON AUDIO PIPELINE (Local CPU)               │
│  openWakeWord → Silero VAD → Faster-Whisper          │
│  Piper TTS ← response ← Gemini Live API              │
├─────────────────────────────────────────────────────┤
│  GEMINI FREE TIER (Cloud)                            │
│  Reasoning, planning, vision, function calling        │
├─────────────────────────────────────────────────────┤
│  4-LAYER MEMORY (Local)                              │
│  Working │ Episodic (ChromaDB) │ Semantic │ Procedural │
├─────────────────────────────────────────────────────┤
│  PROACTIVE MONITOR (Local daemon)                    │
│  Background awareness, change detection, alerts        │
├─────────────────────────────────────────────────────┤
│  SCREEN INTELLIGENCE (Local + Gemini Vision)          │
│  MSS capture → Gemini → screen description           │
├─────────────────────────────────────────────────────┤
│  INTEGRATIONS (Local)                                │
│  Home Assistant │ Face Auth │ Gesture │ Document RAG │
└─────────────────────────────────────────────────────┘
```

**All local except Gemini.** Zero subscriptions. All free open-source software.
