"""
install_features.py - Install all new JARVIS features.
Run this ONCE after pulling the latest changes.

Usage:
    python install_features.py

This installs the optional packages for the new features.
The core JARVIS functionality works without these — these just enable extra features.
"""
import logging  # migrated from print()
import subprocess
import sys


def run(cmd: str, desc: str):
    logging.getLogger(__name__).info("\\n{'='*60}")
    logging.getLogger(__name__).info(f'Installing: {desc}')
    logging.getLogger(__name__).info(f'Command: {cmd}')
    logger.debug('='*60)
    result = subprocess.run(cmd, shell=True)
    if result.returncode == 0:
        logging.getLogger("OK").info(f'{desc} installed')
    else:
        logging.getLogger(__name__).info(f'[!] {desc} failed — feature will be unavailable')


def main():
    logging.getLogger(__name__).info('JARVIS Feature Installer')
    logging.getLogger(__name__).info('=')
    logging.getLogger(__name__).info('Installing optional packages for new JARVIS features.')
    logging.getLogger(__name__).info('These are NOT required — JARVIS works without them.')
    logging.getLogger(__name__).info('=')

    # Wake word detection
    run(
        "pip install openwakeword",
        "Wake Word Detection (openWakeWord) — say 'Hey JARVIS' instead of push-to-talk"
    )

    # Speech models (CPU)
    run(
        "pip install torch --index-url https://download.pytorch.org/whl/cpu",
        "PyTorch CPU — required for Silero VAD and Faster-Whisper"
    )
    run(
        "pip install faster-whisper",
        "Local Transcription (Faster-Whisper) — transcribes your voice locally"
    )
    run(
        "pip install silero-vad",
        "Voice Activity Detection (Silero VAD) — detects when you're speaking"
    )

    # Piper TTS (best quality local voice)
    run(
        "pip install piper-tts",
        "Piper TTS — high-quality local voice (British male)"
    )

    # Vision & HUD extras
    run(
        "pip install dearpygui",
        "DearPyGui HUD — cinematic JARVIS holographic display"
    )
    run(
        "pip install insightface",
        "InsightFace — face recognition for JARVIS greeting"
    )
    run(
        "pip install mediapipe",
        "MediaPipe — gesture control (wave to wake, fist to silence)"
    )
    run(
        "pip install pystray",
        "System Tray — JARVIS icon in Windows notification area"
    )

    # Optional: Download Piper voice
    import os
    voices_dir = "models/voices"
    if not os.path.exists(voices_dir):
        os.makedirs(voices_dir)

    voice_file = f"{voices_dir}/en_GB-alan-medium.onnx"
    if not os.path.exists(voice_file):
        logging.getLogger(__name__).info('\\n')
        logging.getLogger(__name__).info('Downloading JARVIS voice (Alan — British male)...')
        logging.getLogger(__name__).info('This is 47MB and may take a moment.')
        logging.getLogger(__name__).info('=')
        run(
            f'curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/5512791644e2148e4be301d4c7fc2a4bf51a5057/en/en_GB/alan/medium/en_GB-alan-medium.onnx" -o "{voice_file}"',
            "JARVIS voice (Alan British)"
        )

    logging.getLogger(__name__).info('\\n')
    logging.getLogger(__name__).info('INSTALLATION COMPLETE')
    logging.getLogger(__name__).info('=')
    logging.getLogger(__name__).info('Restart JARVIS to use the new features:')
    logging.getLogger(__name__).info('python main.py')
    logger.debug()
    logging.getLogger(__name__).info('New features available:')
    logging.getLogger(__name__).info("1. Wake Word — say 'Hey JARVIS' to activate (requires openwakeword)")
    logging.getLogger(__name__).info('2. Local TTS — fast voice responses (requires piper-tts + voice)')
    logging.getLogger(__name__).info('3. System HUD — always-on-top stats panel (no extra deps)')
    logging.getLogger(__name__).info('4. Screen Watchdog — JARVIS watches your screen (no extra deps)')
    logging.getLogger(__name__).info('5. Shutdown Sound — farewell music when JARVIS exits (no extra deps)')
    logger.debug()
    logging.getLogger(__name__).info('Install just the audio pipeline (skipes slow PyTorch download):')
    logging.getLogger(__name__).info('pip install openwakeword sounddevice numpy piper-tts')


if __name__ == "__main__":
    main()
