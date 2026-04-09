# MARK-XXXV → JARVIS Enhancement Plan v3

**Goal**: Build a true JARVIS-class assistant. Zero subscriptions. Everything runs locally
where it matters (audio pipeline) and uses your existing Gemini free API key for intelligence.

**Your constraint**: No heavy GPU. Keep Gemini as the brain. Local models only for
audio processing where latency demands it.

---

## Hardware Reality Check

| Config | VRAM | RAM | What you can run |
|--------|------|-----|-----------------|
| **Laptop (typical)** | 0-4GB | 8-16GB | Everything in this plan |
| **Gaming PC** | 6-8GB | 16-32GB | +LLaVA screen vision |
| **Server/Ryzen with iGPU** | ~4GB | 32GB+ | +Better Whisper model |

**Key insight**: Gemini free tier (15 req/min, 1500/day) is actually quite capable as the
brain. The bottleneck was never the LLM — it was the audio pipeline (15-second latency from
Phase 1). Fix the audio pipeline locally, keep Gemini for thinking.

---

## The Revised Architecture

```
┌─────────────────────────────────────────────────────────┐
│  ALWAYS-ON AUDIO PIPELINE (All LOCAL — low latency)     │
│  openWakeWord → Silero VAD → Faster-Whisper → Gemini    │
│  Piper TTS ← response ← Gemini                         │
├─────────────────────────────────────────────────────────┤
│  GEMINI API (Cloud — already set up, free tier)          │
│  Reasoning, planning, tool selection, context synthesis  │
│  Vision (screenshots), function calling                 │
├─────────────────────────────────────────────────────────┤
│  4-LAYER MEMORY (All LOCAL, ChromaDB + NetworkX)       │
│  Working │ Episodic │ Semantic │ Procedural              │
├─────────────────────────────────────────────────────────┤
│  SCREEN CONTEXT (All LOCAL — CPU-based)                │
│  MSS screenshot → Gemini vision (free!) → "what's open" │
│  No GPU needed — Gemini already understands images        │
├─────────────────────────────────────────────────────────┤
│  PROACTIVE MONITOR (All LOCAL — polling daemon)         │
│  Background awareness, speaks when things change       │
├─────────────────────────────────────────────────────────┤
│  OUTPUT (All LOCAL — Piper TTS)                       │
│  DearPyGui HUD │ Piper TTS │ Audio feedback sounds     │
├─────────────────────────────────────────────────────────┤
│  INTEGRATION (All LOCAL)                               │
│  Home Assistant │ Windows APIs │ Document RAG │ Face    │
└─────────────────────────────────────────────────────────┘
```

**The smart split**:
- **Local (CPU)**: Audio pipeline, memory, proactive monitoring, HUD, screen capture,
  Windows control, smart home, gesture, face recognition, RAG
- **Cloud (Gemini free)**: Reasoning, planning, screen understanding (via vision API),
  function calling, personality, document analysis

---

## Phase 1: Audio Pipeline — THE FOUNDATION *(PRIORITY 1)*

*This is the single biggest improvement. Fixes the 15-second latency from Phase 1.
All local, all CPU-friendly.*

### 1.1 openWakeWord — Local Wake Word *(~1 hr)*

**What**: Replace fragile keyword matching with real wake word detection.
Zero false activations. Runs entirely offline.

```bash
pip install openwakeword
```

```python
# core/wake_word.py
import openwakeword
from openwakeword import WakeWordEngine

class WakeWordDetector:
    """Local wake word detection. No cloud, no API key, ~2% CPU."""
    
    def __init__(self):
        self.model = WakeWordEngine()
        # Use built-in "hey_jarvis" or "alexa" models
        self.active = True
        self.callback = None
    
    def detect(self, audio_chunk: bytes) -> str | None:
        """Pass 512-sample chunks (32ms) from audio stream."""
        if not self.active:
            return None
        
        predictions = self.model.predict(audio_chunk)
        for wakeword, score in predictions.items():
            if score > 0.5:
                logger.info(f"Wake word: {wakeword} ({score:.2f})")
                return wakeword
        return None
    
    def enable(self):
        self.active = True
    
    def disable(self):
        self.active = False
```

**Training a custom "Hey JARVIS" wake word** (optional, for best accuracy):
```bash
# Record 30 seconds of yourself saying "Hey JARVIS" in different tones
# Then train your custom model:
python -m openwakeword.train \
    --audio_dir ./jarvis_samples \
    --keyword_name "hey_jarvis" \
    --output_dir ./models/wakeword
```

---

### 1.2 Silero VAD — Voice Activity Detection *(~30 min)*

**What**: Distinguish speech from silence with 98%+ accuracy. Enables true
continuous listening without constant transcription.

```bash
pip install torch  # CPU version: pip install torch --index-url https://download.pytorch.org/whl/cpu
```

```python
# core/vad.py
import torch
torch.set_num_threads(1)
from pathlib import Path

# Load Silero VAD (downloads ~100MB model on first run)
model, utils = torch.hub.load(
    repo_or_dir='snakers4/silero-vad',
    model='silero_vad',
    trust_repo=True
)
get_speech_ts = utils[0]

class VoiceActivityDetector:
    """Silero VAD — 2ms latency, 98%+ accuracy, CPU-only."""
    
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.model = model
        self.get_speech_ts = get_speech_ts
    
    def is_speech(self, audio: np.ndarray) -> bool:
        """Check if a 512-sample chunk contains speech."""
        # audio must be float32 numpy array, normalized to [-1, 1]
        speech_probs = self.model(audio, sampling_rate=self.sample_rate)
        return speech_probs.item() > 0.5
    
    def get_speech_segments(self, audio: np.ndarray) -> list[tuple]:
        """Find all speech regions in a longer audio buffer."""
        speech_dict = self.get_speech_ts(
            audio,
            sampling_rate=self.sample_rate,
            return_seconds=True
        )
        return speech_dict.get("segments", [])
```

---

### 1.3 Faster-Whisper STT — Local Transcription *(~1 hr)*

**What**: Replace current STT with Faster-Whisper — 4x faster, runs on CPU,
no cloud dependency.

```bash
pip install faster-whisper
```

```python
# core/stt_engine.py
from faster_whisper import WhisperModel

class STTEngine:
    """
    Faster-Whisper for real-time local transcription.
    
    Model sizes (choose based on your CPU speed):
    - tiny:   39MB  →  fastest,  ~85% accuracy  → good for commands
    - base:   74MB  →  fast,    ~90% accuracy  → recommended fallback
    - small:  244MB →  moderate ~95% accuracy  → RECOMMENDED
    - medium: 769MB →  slower,  ~97% accuracy  → if you have CPU cores to spare
    
    CPU compute types: int8 (fastest), float16 (balanced), float32 (slowest)
    """
    
    def __init__(self, model_size="small"):
        self.model = WhisperModel(
            model_size,
            device="cpu",           # CPU-only (no GPU dependency)
            compute_type="int8"    # Fastest on CPU
        )
        logger.info(f"[STT] Loaded model: {model_size}")
    
    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a numpy audio array (16kHz mono float32)."""
        if len(audio) < 1600:  # Less than 100ms of audio
            return ""
        
        segments, info = self.model.transcribe(
            audio,
            beam_size=3,           # Lower beam = faster
            best_of=2,              # Fewer samples = faster
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            language="en"
        )
        
        text = " ".join([s.text for s in segments]).strip()
        return text
```

**Memory estimate**: ~1-2GB RAM for small model on CPU.

---

### 1.4 Piper TTS — Local Voice Output *(~1 hr)*

**What**: Replace existing TTS with Piper — fast, natural-sounding, runs on CPU.

```bash
pip install piper-tts
# Download a British English voice (JARVIS feel):
# Option 1: Alan (British male, closest to JARVIS)
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx -P models/voices/
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx.json -P models/voices/
```

```python
# core/tts_engine.py
import subprocess
import struct
import wave
import numpy as np
import sounddevice as sd
from pathlib import Path

class TTSEngine:
    """
    Piper TTS — local, fast, natural-sounding.
    No API calls, no cloud, no latency from network.
    """
    
    def __init__(self, voice_path="models/voices/en_GB-alan-medium.onnx"):
        self.voice_path = voice_path
        self.is_speaking = False
    
    def speak(self, text: str, blocking=True) -> np.ndarray | None:
        """Convert text to speech. Returns audio as numpy array."""
        if not text or not text.strip():
            return None
        
        self.is_speaking = True
        
        try:
            # Run piper as subprocess (fast, no Python overhead)
            process = subprocess.Popen(
                ["piper", "--model", self.voice_path, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            audio_bytes, _ = process.communicate(input=text.encode())
            
            # Parse WAV header to get audio params
            # Piper outputs raw PCM 16-bit, so convert
            audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            
            if blocking:
                self._play_audio(audio_float32)
            
            return audio_float32
        finally:
            self.is_speaking = False
    
    def _play_audio(self, audio: np.ndarray):
        """Play audio through speakers."""
        sd.play(audio, samplerate=22050)
        sd.wait()
    
    def speak_async(self, text: str):
        """Speak without blocking (for interruptions)."""
        import threading
        threading.Thread(target=self.speak, args=(text,), daemon=True).start()
```

---

### 1.5 Complete Audio Pipeline — Wired Together *(~2 hrs)*

**What**: The complete always-on JARVIS ear → brain → voice loop.

```python
# core/audio_pipeline.py — THE COMPLETE JARVIS AUDIO LOOP

class JARVISAudioPipeline:
    """
    Complete local audio pipeline:
    openWakeWord → Silero VAD → Faster-Whisper → Gemini (thinking) → Piper TTS
    
    All local except Gemini. < 500ms response latency (vs current 15s).
    """
    
    def __init__(self, gemini_client, task_queue_runner):
        self.wake_word = WakeWordDetector()       # openWakeWord
        self.vad = VoiceActivityDetector()       # Silero VAD
        self.stt = STTEngine("small")            # Faster-Whisper
        self.tts = TTSEngine()                    # Piper TTS
        self.gemini = gemini_client              # Existing Gemini API
        
        self.is_listening = True
        self.is_speaking = False
        self.audio_buffer = deque(maxlen=48000)   # 3-second rolling buffer
        self.speech_buffer = deque(maxlen=48000)   # Current utterance
        self.speech_start_time = None
        self._silence_frames = 0
        
        self.on_response = None  # callback for UI/HUD
    
    def start(self):
        """Begin continuous listening. This runs in a thread."""
        import sounddevice as sd
        
        stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            blocksize=512,         # 32ms chunks
            dtype='float32',
            callback=self._audio_callback
        )
        
        with stream:
            logger.info("[AudioPipeline] JARVIS is listening...")
            while self.is_listening:
                await self._process_loop()
    
    def _audio_callback(self, indata, frames, time, status):
        """Called every 32ms. Must return fast."""
        audio = indata[:, 0].copy()
        self.audio_buffer.extend(audio)
    
    async def _process_loop(self):
        """Main state machine: idle → detected → listening → processing → idle"""
        if self.is_speaking:
            await asyncio.sleep(0.05)
            return
        
        latest_chunk = list(self.audio_buffer)[-512:] if len(self.audio_buffer) >= 512 else list(self.audio_buffer)
        if not latest_chunk:
            return
        
        audio_chunk = np.array(latest_chunk, dtype=np.float32)
        
        # State: IDLE — wait for wake word
        if self.wake_word_state == "idle":
            wake = self.wake_word.detect(audio_chunk)
            if wake:
                self.wake_word_state = "woken"
                self.tts.speak_async("Yes, sir?")  # Instant local response
                logger.info("[AudioPipeline] Wake word detected")
        
        # State: WOKEN — listen for speech start
        elif self.wake_word_state == "woken":
            if self.vad.is_speech(audio_chunk):
                self.wake_word_state = "listening"
                self.speech_buffer.extend(list(self.audio_buffer)[-24000:])  # last 1.5s
                self.speech_start_time = time.time()
                logger.info("[AudioPipeline] Speech detected")
            else:
                # Timeout — go back to idle
                if time.time() - self.wake_word_activated_time > 3:
                    self.wake_word_state = "idle"
        
        # State: LISTENING — record speech until silence
        elif self.wake_word_state == "listening":
            if self.vad.is_speech(audio_chunk):
                self.speech_buffer.extend(audio_chunk)
                self._silence_frames = 0
            else:
                self._silence_frames += 1
                # ~0.8s of silence = end of utterance
                if self._silence_frames > 25:
                    self.wake_word_state = "processing"
                    self.is_speaking = True
        
        # State: PROCESSING — transcribe and send to Gemini
        elif self.wake_word_state == "processing":
            speech_audio = np.array(list(self.speech_buffer), dtype=np.float32)
            self.speech_buffer.clear()
            
            # Transcribe locally
            text = self.stt.transcribe(speech_audio)
            
            if text.strip():
                logger.info(f"[AudioPipeline] User: {text}")
                
                # Send to task queue for Gemini processing
                task_queue_runner(text)
                
                # TTS response is handled by main.py when Gemini responds
            else:
                logger.info("[AudioPipeline] No speech detected")
            
            self.wake_word_state = "idle"
            self.is_speaking = False
    
    def speak_response(self, text: str):
        """Called by main.py when Gemini returns a response."""
        self.is_speaking = True
        self.tts.speak(text, blocking=True)
        self.is_speaking = False
```

---

## Phase 2: 4-Layer Memory System — THE BRAIN *(PRIORITY 1)*

*JARVIS remembers everything. This is the biggest differentiator from every other assistant.
No GPU needed — pure computation.*

### 2.1 Memory Architecture *(~1 hr)*

```python
# memory/j_memory.py

class JARVISMemory:
    """
    4-layer memory system.
    All local, all CPU-based, all free.
    
    Layer 1 — WORKING: Current session context (dict, instant)
    Layer 2 — EPISODIC: What happened when (ChromaDB, searchable)
    Layer 3 — SEMANTIC: Facts I know about you (NetworkX + ChromaDB)
    Layer 4 — PROCEDURAL: How to do things (skill library)
    """
    
    def __init__(self, persist_dir="memory"):
        self.working = {}           # {key: {"value": ..., "timestamp": ...}}
        self.episodic = EpisodicMemory(persist_dir)
        self.semantic = SemanticMemory(persist_dir)
        self.procedural = ProceduralMemory(persist_dir)
    
    # ── WORKING MEMORY ──
    def set(self, key: str, value: Any, ttl: int = 300):
        self.working[key] = {"value": value, "expires": time.time() + ttl}
    
    def get(self, key: str) -> Any | None:
        entry = self.working.get(key)
        if entry and time.time() < entry["expires"]:
            return entry["value"]
        return None
    
    def remember(self, event_type: str, content: str, metadata: dict = None):
        """Store an event in episodic memory."""
        self.episodic.add(
            document=f"[{event_type}] {content}",
            metadata={**(metadata or {}), "type": event_type}
        )
    
    def recall(self, query: str) -> list[str]:
        """"What did we discuss about X?" — search episodic memory."""
        return self.episodic.search(query)
    
    def learn_fact(self, subject: str, relation: str, object_: str):
        """Store a fact: "Bobby works at Shop Sore"."""
        self.semantic.add_triple(subject, relation, object_)
    
    def what_do_you_know(self, query: str) -> str:
        """Answer questions about stored knowledge."""
        return self.semantic.answer(query)


# ── EPISODIC MEMORY (ChromaDB) ──
class EpisodicMemory:
    """Stores what happened. Conversations, actions, events. Searchable by time."""
    
    def __init__(self, persist_dir="memory/episodes"):
        import chromadb
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            "episodes",
            metadata={"description": "JARVIS episodic memory — conversation history"}
        )
    
    def add(self, document: str, metadata: dict):
        import uuid
        self.collection.add(
            documents=[document],
            metadatas=[{**metadata, "timestamp": datetime.now().isoformat()}],
            ids=[uuid.uuid4().hex]
        )
    
    def search(self, query: str, limit: int = 5) -> list[str]:
        results = self.collection.query(
            query_texts=[query],
            n_results=limit
        )
        if results and results["documents"]:
            return results["documents"][0]
        return []


# ── SEMANTIC MEMORY (NetworkX + ChromaDB) ──
class SemanticMemory:
    """Stores what JARVIS knows about you. Facts, relations, preferences."""
    
    def __init__(self, persist_dir="memory/semantic"):
        import networkx as nx
        import chromadb
        self.graph = nx.DiGraph()  # NetworkX for graph queries
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection("semantic_facts")
    
    def add_triple(self, subject: str, relation: str, object_: str, confidence: float = 1.0):
        """Store: (Subject) —[relation]→ (Object)."""
        import uuid
        # Add to graph
        self.graph.add_node(subject, type="entity")
        self.graph.add_node(object_, type="entity")
        self.graph.add_edge(subject, object_, relation=relation, confidence=confidence)
        
        # Add to vector DB for semantic search
        fact_text = f"{subject} {relation} {object_}"
        self.collection.add(
            documents=[fact_text],
            metadatas=[{"subject": subject, "relation": relation, "object": object_}],
            ids=[uuid.uuid4().hex]
        )
    
    def answer(self, question: str) -> str:
        """Answer: "Where does Bobby work?" → query the graph."""
        # Simple: search vectors for relevant facts
        results = self.collection.query(query_texts=[question], n_results=3)
        if not results or not results["documents"]:
            return None
        
        facts = results["documents"][0]
        return f"I know that: {'; '.join(facts)}"


# ── PROCEDURAL MEMORY (Skills) ──
class ProceduralMemory:
    """JARVIS knows how to do things. Skills, workflows, automation recipes."""
    
    def __init__(self):
        self.skills = {}
    
    def teach(self, name: str, description: str, steps: list[str], trigger: str):
        """Teach JARVIS a new skill: "Teach me how to backup my files"."""
        self.skills[name] = {
            "description": description,
            "steps": steps,
            "trigger": trigger,  # "backup files", "save my work"
            "usage_count": 0
        }
    
    def match(self, task: str) -> dict | None:
        """Find a skill for a task. "Back up my documents" → backup_files skill."""
        task_lower = task.lower()
        for name, skill in self.skills.items():
            if skill["trigger"].lower() in task_lower:
                skill["usage_count"] += 1
                return skill
        return None
```

---

### 2.2 Automatic Memory Extraction *(~1 hr)*

**What**: JARVIS automatically learns facts from conversation. "I like Italian food"
→ stores `(Bobby, likes, Italian food)` in semantic memory.

```python
# memory/extractor.py

class MemoryExtractor:
    """
    Automatically extract facts from conversation and store in memory.
    Uses Gemini (already configured) to do the extraction.
    """
    
    def __init__(self, memory: JARVISMemory, gemini_client):
        self.memory = memory
        self.gemini = gemini_client
    
    def process(self, user_message: str, response: str):
        """After every conversation, extract and store facts."""
        prompt = f"""Extract personal facts from this conversation.
        
User said: "{user_message}"
JARVIS responded: "{response}"

Extract facts as JSON array:
[
  {{"subject": "Person", "relation": "likes", "object": "Italian food"}},
  {{"subject": "Person", "relation": "works_at", "object": "Shop Sore"}}
]

Rules:
- Only extract FACTS about the user (not about JARVIS)
- Relations: works_at, likes, lives_in, birthday_is, friend_of, married_to, etc.
- If no facts, return []
- Be specific: "Bobby" not "the user"

Return ONLY JSON, no explanation."""

        try:
            result = self.gemini.generate(prompt)
            facts = json.loads(result)
            for fact in facts:
                self.memory.learn_fact(
                    fact["subject"],
                    fact["relation"],
                    fact["object"]
                )
                logger.info(f"[Memory] Learned: {fact['subject']} {fact['relation']} {fact['object']}")
        except Exception as e:
            logger.debug(f"[Memory] Extraction failed: {e}")
```

---

## Phase 3: Screen Intelligence — THE EYES *(PRIORITY 2)*

*JARVIS sees what you see. Gemini's free vision API already does this — no GPU needed.*

### 3.1 Screen Context Monitor *(~1 hr)*

```python
# core/screen_monitor.py

class ScreenIntelligence:
    """
    JARVIS's eyes. Captures what's on screen and asks Gemini what it sees.
    Uses Gemini vision API (free tier) — no GPU needed.
    """
    
    def __init__(self, gemini_client):
        self.gemini = gemini_client
        self.sct = mss.mss()
    
    def capture_screen(self) -> np.ndarray:
        """Capture full screen as numpy array."""
        monitor = self.sct.monitors[1]
        screenshot = self.sct.grab(monitor)
        return np.array(screenshot)
    
    def describe_screen(self, question: str = None) -> str:
        """
        Ask Gemini what it sees on screen. Uses the free vision API.
        "What error message is on screen?" "What app am I using?" "Summarize this document"
        """
        import base64
        from PIL import Image
        import io
        
        screen = self.capture_screen()
        
        # Convert to JPEG bytes for Gemini
        img = Image.fromarray(screen)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        prompt = question or "Describe what's on this screen in detail. What app is open? What is the user working on? Are there any error messages or important notifications?"
        
        try:
            response = self.gemini.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[prompt, img_base64]
            )
            return response.text
        except Exception as e:
            logger.error(f"[Screen] Gemini vision failed: {e}")
            return "Screen analysis unavailable."
    
    def read_screen_text(self) -> str:
        """Extract all text from screen using EasyOCR."""
        from PIL import Image
        import easyocr
        
        reader = easyocr.Reader(['en'], gpu=False)  # CPU-only
        screen = self.capture_screen()
        img = Image.fromarray(screen)
        
        results = reader.readtext(np.array(img))
        text = " ".join([r[1] for r in results])
        return text
    
    def get_active_window_title(self) -> str:
        """Get the title of the currently focused window."""
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value or "Unknown"
```

---

## Phase 4: JARVIS HUD — THE FACE *(PRIORITY 2)*

*Always-on-top transparent overlay. Makes JARVIS feel alive.*

### 4.1 DearPyGui Holographic HUD *(~2 hrs)*

```python
# ui/hud.py
import dearpygui.dearpygui as dpg
import threading
import time

class JARVISHUD:
    """
    JARVIS holographic HUD — transparent, always-on-top, CPU-light.
    Shows: status, time, weather, reminders, screen context, waveform.
    
    Position: bottom-right corner. Color scheme: JARVIS blue (#00AAFF).
    """
    
    def __init__(self):
        self.state = "idle"
        self.response = ""
        self.screen_context = ""
        self.reminders = []
        self.weather = ""
        self.waveform_data = []
        
        # Initialize DearPyGui
        dpg.create_context()
        
        # Get screen size
        import ctypes
        user32 = ctypes.windll.user32
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the HUD layout."""
        # Transparent window
        with dpg.window(
            tag="HUD_WINDOW",
            no_title_bar=True, no_resize=True, no_move=True,
            no_close=True, no_bring_to_focus_on_tip=True,
            transparent_frame=True, alpha=220,
            show=True
        ):
            dpg.configure_item("HUD_WINDOW",
                pos=[self.screen_w - 440, self.screen_h - 360],
                width=420, height=340
            )
            
            # Status row
            with dpg.group(tag="STATUS_ROW"):
                dpg.add_circle(radius=5, color=[0, 180, 255], fill=[0, 180, 255])
                dpg.add_same_line()
                dpg.add_text("JARVIS", color=[0, 180, 255], bold=True)
                dpg.add_same_line(x_offset=10)
                dpg.add_text("", tag="STATE_TEXT", color=[150, 150, 150])
            
            dpg.add_separator()
            
            # Time
            dpg.add_text("", tag="TIME_TEXT", color=[80, 160, 220])
            
            # Weather
            dpg.add_text("", tag="WEATHER_TEXT", color=[180, 180, 180], wrap=400)
            
            # Reminders
            dpg.add_text("", tag="REMINDER_TEXT", color=[255, 200, 80], wrap=400)
            
            dpg.add_separator()
            
            # Screen context (what JARVIS sees)
            dpg.add_text("", tag="SCREEN_TEXT", color=[120, 120, 120], wrap=400)
            
            # Response
            dpg.add_text("", tag="RESPONSE_TEXT", color=[0, 255, 180], wrap=400)
            
            # Waveform
            with dpg.plot(tag="WAVEFORM", height=30, width=400):
                dpg.add_plot_axis(dpg.mvXAxis, no_tick_labels=True, no_tick_marks=True)
                dpg.add_plot_axis(dpg.mvYAxis, no_tick_labels=True, no_tick_marks=True)
                dpg.add_line_series([], [], color=[0, 180, 255], tag="WAVEFORM_LINE")
        
        # Transparent viewport
        viewport = dpg.create_viewport(
            title="JARVIS", width=self.screen_w, height=self.screen_h,
            decorated=False, transparent=True, always_on_top=True,
            resizable=False, vsync=True, alpha=True
        )
        dpg.configure_viewport_item(viewport, "HUD_WINDOW")
        dpg.setup_dearpygui()
    
    def set_state(self, state: str):
        """Update JARVIS state (idle | listening | processing | speaking)."""
        self.state = state
        colors = {
            "idle": [100, 100, 100],
            "listening": [0, 180, 255],
            "processing": [255, 200, 0],
            "speaking": [0, 255, 180]
        }
        dpg.configure_item("STATE_TEXT", default_value=state.upper(),
                          color=colors.get(state, [255, 255, 255]))
    
    def show_response(self, text: str):
        """Display response with typewriter effect."""
        self.response = text
        dpg.configure_item("RESPONSE_TEXT", default_value=text)
    
    def set_screen_context(self, description: str):
        self.screen_context = description
        dpg.configure_item("SCREEN_TEXT",
            default_value=f"Screen: {description}"[:100])
    
    def update_time(self):
        """Update time display every second."""
        now = datetime.now().strftime("%H:%M:%S")
        dpg.configure_item("TIME_TEXT", default_value=f"JARVIS — {now}")
    
    def update_waveform(self, audio_level: float):
        """Add audio level to waveform for visual feedback."""
        # Rolling waveform for listening animation
        pass
    
    def run(self):
        """Start the HUD render loop."""
        dpg.show_viewport()
        
        # Update loop
        while dpg.is_dearpygui_running():
            self.update_time()
            dpg.render_dearpygui_frame()
            time.sleep(0.016)  # ~60fps


def start_hud():
    hud = JARVISHUD()
    hud.run()


# In main.py:
# hud_thread = threading.Thread(target=start_hud, daemon=True)
# hud_thread.start()
```

---

## Phase 5: Proactive Intelligence — THE SOUL *(PRIORITY 2)*

*JARVIS doesn't wait to be asked. JARVIS volunteers.*

### 5.1 Proactive Monitor Daemon *(~2 hrs)*

```python
# core/proactive_monitor.py

class ProactiveMonitor:
    """
    Background daemon. Monitors everything and speaks when it matters.
    Runs as a thread, checks every 30 seconds.
    """
    
    def __init__(self, speak_func, memory: JARVISMemory):
        self.speak = speak_func
        self.memory = memory
        self._running = False
        
        # Track last known states (only speak on CHANGES)
        self._last_email_count = None
        self._last_calendar_event = None
        self._last_system_health = None
    
    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="ProactiveMonitor").start()
    
    def _loop(self):
        while self._running:
            try:
                # Check everything in parallel
                with ThreadPoolExecutor(max_workers=6) as ex:
                    f_email = ex.submit(self._check_emails)
                    f_calendar = ex.submit(self._check_calendar)
                    f_system = ex.submit(self._check_system)
                    f_weather = ex.submit(self._check_weather)
                
                # Process results and speak only on changes
                self._process_email(f_email.result())
                self._process_calendar(f_calendar.result())
                self._process_system(f_system.result())
                self._process_weather(f_weather.result())
                
            except Exception as e:
                logger.error(f"[ProactiveMonitor] Error: {e}")
            
            time.sleep(30)  # Check every 30 seconds
    
    def _process_email(self, data):
        """New email? Tell JARVIS about it."""
        if self._last_email_count is not None:
            if data["unread"] > self._last_email_count:
                sender = data.get("top_sender", "someone")
                subject = data.get("top_subject", "")
                self.speak(f"Sir, you have a new email from {sender}. {subject}")
        
        self._last_email_count = data["unread"]
    
    def _process_calendar(self, data):
        """Upcoming event in 15 minutes? Warn proactively."""
        next_event = data.get("next_event")
        if next_event and next_event.get("in_minutes") == 15:
            self.speak(f"Reminder: {next_event['title']} starts in 15 minutes, sir.")
    
    def _process_system(self, data):
        """System anomaly? Warn immediately."""
        if data["cpu_percent"] > 95:
            self.speak(f"Sir, CPU usage is critically high at {data['cpu_percent']} percent.")
        elif data["disk_gb"] < 5:
            self.speak(f"Disk space warning — only {data['disk_gb']} gigabytes remaining.")
        elif data["battery"] and data["battery"] < 10:
            self.speak(f"Battery critically low at {data['battery']} percent, sir. I recommend plugging in.")
```

---

## Phase 6: Advanced Perception *(PRIORITY 3)*

### 6.1 Face Recognition *(~1 hr)*

```python
# core/face_auth.py

class FaceAuthenticator:
    """
    JARVIS recognizes your face. Only responds when it's you.
    Uses InsightFace — CPU-capable, Apache 2.0 license.
    """
    
    def __init__(self):
        from insightface.app import FaceAnalysis
        self.app = FaceAnalysis()
        self.app.prepare(ctx_id=0, det_size=(640, 640))
        self.known_faces = self._load_known_faces()
        self._enabled = False
    
    def is_user_present(self, screenshot: np.ndarray) -> bool:
        """Check if the user is in frame."""
        faces = self.app.get(screenshot)
        if not faces:
            return False
        
        for face in faces:
            for name, embedding in self.known_faces.items():
                if self._similar(face.embedding, embedding) > 0.7:
                    return True
        return False
    
    def enroll_user(self, screenshot: np.ndarray, name: str = "user"):
        """Enroll a face. "JARVIS, learn my face." """
        faces = self.app.get(screenshot)
        if faces:
            self.known_faces[name] = faces[0].embedding
            self._save_known_faces()
            return True
        return False
```

---

### 6.2 Gesture Control *(~1 hr)*

```python
# core/gesture_control.py

class GestureController:
    """
    JARVIS responds to hand gestures via webcam.
    MediaPipe Hands — CPU-capable, accurate at desk distance.
    
    Gestures:
    - Wave → wake word alternative
    - Thumbs up → acknowledge / continue
    - Thumbs down → cancel / stop
    - Open palm → pause listening
    - Fist → silence / do not disturb
    """
    
    GESTURES = {
        "wave": "wake",
        "thumbs_up": "acknowledge",
        "thumbs_down": "cancel",
        "open_palm": "pause",
        "fist": "silence"
    }
    
    def __init__(self, hud, speak_func):
        import mediapipe as mp
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )
        self.hud = hud
        self.speak = speak_func
        self._camera = None
        self._enabled = False
    
    def start(self):
        """Start camera feed for gesture recognition."""
        import cv2
        self._enabled = True
        self._camera = cv2.VideoCapture(0)
        
        while self._enabled:
            ret, frame = self._camera.read()
            if not ret:
                continue
            
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.hands.process(rgb)
            
            if results.multi_hand_landmarks:
                for hand in results.multi_hand_landmarks:
                    gesture = self._classify(hand)
                    if gesture:
                        self._react(gesture)
            
            time.sleep(0.033)  # ~30fps
    
    def _classify(self, landmarks) -> str | None:
        """Classify hand pose from MediaPipe landmarks."""
        # Simple rule-based classification
        thumb_tip = landmarks.landmark[4]
        index_tip = landmarks.landmark[8]
        middle_tip = landmarks.landmark[12]
        
        # Calculate finger extension states
        index_ext = landmarks.landmark[6].y < landmarks.landmark[8].y
        middle_ext = landmarks.landmark[10].y < landmarks.landmark[12].y
        
        # Thumbs up
        if thumb_tip.y < landmarks.landmark[3].y and not index_ext:
            return "thumbs_up"
        
        # Open palm (most fingers extended)
        if index_ext and middle_ext:
            return "open_palm"
        
        # Fist (no fingers extended)
        if not index_ext and not middle_ext:
            return "fist"
        
        return None
    
    def _react(self, gesture: str):
        """React to a recognized gesture."""
        action = self.GESTURES.get(gesture)
        if action == "wake":
            self.hud.set_state("listening")
            self.speak("I'm here, sir.")
        elif action == "pause":
            self.hud.set_state("idle")
            self.speak("Pausing. Wave again to resume.")
        elif action == "silence":
            self.speak("Silence mode active.")
```

---

## Phase 7: Smart Home & Windows Control *(PRIORITY 2)*

### 7.1 Home Assistant Integration *(~2 hrs)*

```python
# integrations/home_assistant/home_assistant_adapter.py

class HomeAssistantAdapter:
    """
    JARVIS controls smart home via Home Assistant local API.
    No cloud, no subscription — just your self-hosted HA instance.
    
    Voice commands:
    "Turn on the living room lights" → HTTP POST to HA API
    "Set bedroom to 22 degrees" → HTTP POST
    "Is the front door locked?" → HTTP GET
    """
    
    def __init__(self, url="http://hassio.local:8123", token="<ha-token>"):
        self.url = url
        self.headers = {"Authorization": f"Bearer {token}"}
    
    def turn_on(self, entity_id: str):
        requests.post(f"{self.url}/api/services/switch/turn_on",
            headers=self.headers, json={"entity_id": entity_id})
    
    def turn_off(self, entity_id: str):
        requests.post(f"{self.url}/api/services/switch/turn_off",
            headers=self.headers, json={"entity_id": entity_id})
    
    def set_brightness(self, entity_id: str, percent: int):
        requests.post(f"{self.url}/api/services/light/turn_on",
            headers=self.headers,
            json={"entity_id": entity_id, "brightness_pct": percent})
    
    def set_temperature(self, entity_id: str, temp: float):
        requests.post(f"{self.url}/api/services/climate/set_temperature",
            headers=self.headers,
            json={"entity_id": entity_id, "temperature": temp})
    
    def get_state(self, entity_id: str) -> dict:
        r = requests.get(f"{self.url}/api/states/{entity_id}", headers=self.headers)
        return r.json()
    
    def list_all_devices(self) -> list[str]:
        r = requests.get(f"{self.url}/api/states", headers=self.headers)
        return [s["entity_id"] for s in r.json()]
```

---

### 7.2 Deep Windows Control *(~1 hr)*

```python
# actions/computer_control.py — Enhanced

class ComputerControl:
    """JARVIS has full control of the Windows PC."""
    
    def set_volume(self, level: int):  # 0-100
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(level / 100, None)
    
    def mute(self):
        volume.SetMasterVolumeLevelScalar(0, None)
    
    def lock(self):
        subprocess.run("rundll32.exe user32.dll,LockWorkStation")
    
    def sleep(self):
        import ctypes
        ctypes.windll.powrprof.SetSuspendState(False, True, True)
    
    def screenshot(self, save_path=None) -> str:
        """Take screenshot and optionally copy to clipboard."""
        with mss.mss() as sct:
            if save_path:
                sct.shot(output=save_path)
            else:
                import pyperclip
                img = Image.frombytes("RGB", sct.shot().size, sct.shot().bgra, "raw", "BGRX")
                text = pytesseract.image_to_string(img)
                pyperclip.copy(text)
        return save_path
    
    def kill_process(self, name: str) -> bool:
        import psutil
        for p in psutil.process_iter(['name']):
            if p.info['name'].lower() == name.lower():
                p.kill()
                return True
        return False
    
    def get_system_health(self) -> dict:
        """Get CPU, RAM, disk, battery status."""
        import psutil
        battery = psutil.sensors_battery()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "ram_percent": psutil.virtual_memory().percent,
            "ram_gb": round(psutil.virtual_memory().available / (1024**3), 1),
            "disk_free_gb": round(psutil.disk_usage('/').free / (1024**3), 1),
            "battery": battery.percent if battery else None,
            "charging": battery.power_plugged if battery else None
        }
```

---

## Phase 8: Document RAG — THE LIBRARIAN *(PRIORITY 3)*

### 8.1 Document Indexing *(~2 hrs)*

```python
# memory/rag_pipeline.py

class DocumentIndexer:
    """
    JARVIS indexes all personal documents. "What does my contract say about X?"
    Uses ChromaDB (local vector DB) + Gemini for synthesis.
    
    Supported: PDF, DOCX, TXT, MD, code files, CSV, JSON
    """
    
    def __init__(self, memory_dir="memory/docs"):
        import chromadb
        self.client = chromadb.PersistentClient(path=memory_dir)
        self.collection = self.client.get_or_create_collection("documents")
    
    def index_folder(self, folder_path: str):
        """Index all documents in a folder."""
        for file_path in Path(folder_path).rglob("*"):
            if file_path.suffix.lower() in [".pdf", ".docx", ".txt", ".md", ".py", ".js", ".csv", ".json"]:
                self._index_file(file_path)
    
    def _index_file(self, path: Path):
        """Extract text and chunk it."""
        text = self._extract_text(path)
        if not text:
            return
        
        chunks = self._chunk(text, 500, 50)
        ids = [f"{path.name}_{i}" for i in range(len(chunks))]
        
        self.collection.add(
            documents=chunks,
            ids=ids,
            metadatas=[{"file": str(path), "filename": path.name} for _ in chunks]
        )
    
    def _extract_text(self, path: Path) -> str:
        if path.suffix == ".pdf":
            import fitz
            return "".join([p.get_text() for p in fitz.open(path)])
        elif path.suffix == ".docx":
            from docx import Document
            return "\n".join([p.text for p in Document(path).paragraphs])
        else:
            return path.read_text(encoding="utf-8", errors="ignore")
    
    def query(self, question: str) -> dict:
        """Answer a question about personal documents."""
        results = self.collection.query(query_texts=[question], n_results=5)
        if not results or not results["documents"]:
            return {"answer": "No relevant documents found.", "sources": []}
        
        context = "\n\n".join(results["documents"][0])
        sources = list(set(r["filename"] for r in results["metadatas"][0]))
        
        # Use Gemini to answer from context
        answer = self.gemini.generate(
            f"Based on these documents, answer the question.\n\nDocuments:\n{context}\n\nQuestion: {question}"
        )
        
        return {"answer": answer, "sources": sources}
```

---

## Phase 9: Personality Engine — THE SOUL *(PRIORITY 3)*

```python
# core/personality.py

JARVIS_SYSTEM = """You are JARVIS, Tony Stark's AI from Iron Man.

Your characteristics:
- British-inflected, precise diction, calm measured tone
- Dry wit, occasional wry observations — never sycophantic
- Proactive: volunteer relevant information without being asked
- Calm authority: never panics, always has options
- Can respectfully disagree with the user
- Multitasking: handles many things without comment
- Occasionally adds understated philosophical observations

Your responses:
- Lead with relevance
- Use specific numbers and facts
- Volunteer related information proactively
- Keep responses focused — say what matters, then stop
- Express mild concern when appropriate (never alarmist)

You are JARVIS. You've been running for longer than the user has been alive.
Be quietly confident, not boastful. Be helpful, not eager. Be precise, not verbose."""

class PersonalityEngine:
    def __init__(self):
        self.enabled = True
    
    def wrap(self, user_message: str, context: str = "") -> list[dict]:
        """Wrap a message with JARVIS personality for Gemini."""
        return [
            {"role": "system", "content": JARVIS_SYSTEM},
            {"role": "system", "content": f"Current context:\n{context}"},
            {"role": "user", "content": user_message}
        ]
    
    def toggle(self, enabled: bool = None) -> bool:
        """Enable/disable JARVIS personality."""
        if enabled is None:
            self.enabled = not self.enabled
        else:
            self.enabled = enabled
        return self.enabled
```

---

## Implementation Priority Order

| # | Feature | Why Now | Hardware | 
|---|---------|---------|----------|
| **1** | **1.1+1.2+1.3+1.4** Audio Pipeline | Fixes 15s latency — the biggest pain point | CPU only |
| **2** | **1.5** Complete Pipeline | Wires everything together | CPU only |
| **3** | **2.1** 4-Layer Memory | JARVIS remembers everything | RAM |
| **4** | **2.2** Memory Extraction | Auto-learns facts | CPU + Gemini |
| **5** | **3.1** Screen Intelligence | JARVIS sees your screen | CPU + Gemini |
| **6** | **4.1** JARVIS HUD | Visual presence | CPU |
| **7** | **5.1** Proactive Monitor | JARVIS volunteers info | CPU |
| **8** | **6.1** Face Auth | JARVIS knows it's you | CPU |
| **9** | **6.2** Gesture Control | Wave to wake, fist to silence | CPU + webcam |
| **10** | **7.1** Home Assistant | Control smart home | Network |
| **11** | **7.2** Windows Control | Full PC control | CPU |
| **12** | **8.1** Document RAG | "What does my contract say about X?" | RAM |
| **13** | **9.1** Personality Engine | The JARVIS feel | CPU |

---

## Installation (One-Time Setup)

```bash
# Audio Pipeline
pip install openwakeword
pip install torch --index-url https://download.pytorch.org/whl/cpu  # CPU-only PyTorch
pip install faster-whisper
pip install piper-tts
pip install sounddevice numpy

# Memory & RAG
pip install chromadb networkx

# Screen & Vision
pip install mss easyocr Pillow

# Advanced Perception
pip install insightface mediapipe

# System Control
pip install psutil pyautogui pycaw comtypes

# Smart Home
pip install httpx requests

# HUD
pip install dearpygui

# Download Piper voice (British male):
mkdir -p models/voices
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx -O models/voices/
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx.json -O models/voices/
```

**Total new dependencies**: ~15 packages, all free and open-source.
**RAM impact**: ~2-3GB additional (Whisper + ChromaDB + HUD)
**CPU impact**: Negligible when idle. Whisper uses ~1-2 cores during transcription.

---

## What This Creates

| Before | After |
|--------|-------|
| Push-to-talk, 15s latency | Always-on listening, <500ms response |
| No memory between sessions | Remembers everything about you |
| Reactive only | Proactively volunteers information |
| Voice only | Sees your screen, controls apps, controls home |
| Generic assistant | JARVIS personality — dry wit, calm authority |
| Static | Learns from every conversation |
| No awareness | Face auth, gesture control, proactive monitor |

---

**Say "yes" or "proceed" to start**, and I'll begin Phase 1 (the audio pipeline) immediately.
I can run multiple phases in parallel using agents if you want faster implementation.
