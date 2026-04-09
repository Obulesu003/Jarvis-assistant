# Audio Pipeline Setup

This directory contains the local audio pipeline for MARK-XXXV JARVIS.

## Quick Start

Install dependencies:
```bash
pip install openwakeword torch --index-url https://download.pytorch.org/whl/cpu faster-whisper sounddevice numpy
```

Download the British voice model:
```bash
mkdir -p models/voices
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx -P models/voices/
wget https://github.com/rhasspy/piper/releases/download/2024.11.0/en_GB-alan-medium.onnx.json -P models/voices/
```

Install Piper CLI (required for TTS):
- Download from: https://github.com/rhasspy/piper/releases
- Or: npm install -g piper-tts

## Components

- `core/wake_word.py` — openWakeWord wake word detection
- `core/vad.py` — Silero VAD voice activity detection
- `core/stt_engine.py` — Faster-Whisper transcription
- `core/tts_engine.py` — Piper TTS voice output
- `core/audio_pipeline.py` — Complete wired pipeline
- `actions/audio_action.py` — Action interface for main.py

## Testing

```python
from core.audio_pipeline import JARVISAudioPipeline

pipeline = JARVISAudioPipeline()
pipeline.initialize()
pipeline.start()
```