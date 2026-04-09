"""
audio_action.py - Action function to manage the audio pipeline.
Provides a clean interface for main.py to interact with the pipeline.
"""
import logging

logger = logging.getLogger(__name__)

_pipeline = None


def get_pipeline():
    """Get or create the global audio pipeline instance."""
    global _pipeline
    if _pipeline is None:
        from core.audio_pipeline import JARVISAudioPipeline
        _pipeline = JARVISAudioPipeline()
        _pipeline.initialize()
    return _pipeline


def audio_action(params: dict, player=None):
    """Action to manage audio pipeline."""
    global _pipeline
    cmd = params.get("command", "status")

    if cmd == "start":
        p = get_pipeline()
        p.start()
        return {"status": "listening", "message": "JARVIS is now listening for wake word"}
    elif cmd == "stop":
        if _pipeline:
            _pipeline.stop()
        return {"status": "stopped", "message": "Audio pipeline stopped"}
    elif cmd == "status":
        p = get_pipeline()
        ready = p.is_ready
        components = {
            "wake_word": p._wake_word.is_ready if p._wake_word else False,
            "vad": p._vad.is_ready if p._vad else False,
            "stt": p._stt.is_ready if p._stt else False,
            "tts": p._tts.is_ready if p._tts else False,
        }
        return {"ready": ready, "components": components}
    elif cmd == "speak":
        text = params.get("text", "")
        p = get_pipeline()
        p.speak_response(text)
        return {"status": "spoken", "text": text}
    elif cmd == "speak_async":
        text = params.get("text", "")
        p = get_pipeline()
        p.speak_async(text)
        return {"status": "speaking_async"}
    else:
        return {"status": "error", "message": f"Unknown command: {cmd}"}