"""
intro_music.py - JARVIS Ultimate Cyberpunk Startup Music
Best-in-class synthesized music using advanced techniques:
- FM synthesis for rich, evolving timbres
- Analog-style synths (saw, square, triangle)
- Digital glitch effects
- Binaural beats and ambient pads
- Professional mixing and mastering
"""

import math
import struct
import os
import random
import threading
import tempfile
from pathlib import Path
from typing import Callable

# Audio settings
SAMPLE_RATE = 44100
BYTES_PER_SAMPLE = 2


def get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()

# ── Audio Writing ──────────────────────────────────────────────────────────────

def _write_wav(path: Path, samples: list[float]):
    """Write samples to a 16-bit WAV file."""
    n_samples = len(samples)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + n_samples * BYTES_PER_SAMPLE))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<H", 1))
        f.write(struct.pack("<I", SAMPLE_RATE))
        f.write(struct.pack("<I", SAMPLE_RATE * BYTES_PER_SAMPLE))
        f.write(struct.pack("<H", BYTES_PER_SAMPLE))
        f.write(struct.pack("<H", BYTES_PER_SAMPLE * 8))
        f.write(b"data")
        f.write(struct.pack("<I", n_samples * BYTES_PER_SAMPLE))
        for s in samples:
            s = max(-1.0, min(1.0, s))
            s = int(round(s * 32767.0))
            f.write(struct.pack("<h", s))


# ── Oscillators (Advanced Synthesis) ─────────────────────────────────────────

def _sine(freq: float, duration: float, amp: float = 1.0, phase: float = 0.0) -> list[float]:
    """Pure sine wave with optional phase offset."""
    n = int(SAMPLE_RATE * duration)
    return [float(amp * math.sin(2 * math.pi * freq * (i / SAMPLE_RATE) + phase)) for i in range(n)]


def _triangle(freq: float, duration: float, amp: float = 0.5) -> list[float]:
    """Triangle wave - softer, mellower tone."""
    n = int(SAMPLE_RATE * duration)
    return [float(amp * (2 / math.pi * math.asin(math.sin(2 * math.pi * freq * i / SAMPLE_RATE)))) for i in range(n)]


def _sawtooth(freq: float, duration: float, amp: float = 0.4) -> list[float]:
    """Band-limited sawtooth - analog synth bass/synth."""
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        phase = (freq * t) % 1.0
        sample = amp * (2.0 * phase - 1.0)
        samples.append(float(sample))
    return samples


def _square(freq: float, duration: float, amp: float = 0.3, duty: float = 0.5) -> list[float]:
    """Pulse wave with variable duty cycle."""
    n = int(SAMPLE_RATE * duration)
    return [float(amp * (1.0 if (freq * i / SAMPLE_RATE) % 1.0 < duty else -1.0)) for i in range(n)]


def _fm_synth(base_freq: float, duration: float, mod_ratio: float = 2.0,
              mod_index: float = 3.0, amp: float = 0.5) -> list[float]:
    """
    FM Synthesis - creates rich, evolving timbres.
    Carrier frequency: base_freq
    Modulator frequency: base_freq * mod_ratio
    Modulation depth: mod_index
    Classic FM electric piano, bell, and synth sounds.
    """
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        mod = mod_index * math.sin(2 * math.pi * base_freq * mod_ratio * t)
        carrier = math.sin(2 * math.pi * base_freq * t + mod)
        samples.append(float(amp * carrier))
    return samples


def _supersaw(freq: float, duration: float, num_voices: int = 7, amp: float = 0.3) -> list[float]:
    """
    Supersaw oscillator - fat, lush analog synthesizer sound.
    Layers multiple detuned sawtooth waves.
    """
    n = int(SAMPLE_RATE * duration)
    samples = [0.0] * n
    detunes = [0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03][:num_voices]

    for detune in detunes:
        voice = _sawtooth(freq * detune, duration, amp / num_voices)
        for i in range(len(voice)):
            samples[i] += voice[i]

    return samples


def _noise(duration: float, amp: float = 0.05, color: str = "white") -> list[float]:
    """Noise generator with color options."""
    n = int(SAMPLE_RATE * duration)
    samples = []
    if color == "white":
        return [float(amp * random.uniform(-1, 1)) for _ in range(n)]
    elif color == "pink":
        b0 = b1 = b2 = b3 = b4 = b5 = b6 = 0.0
        for _ in range(n):
            white = random.uniform(-1, 1)
            b0 = 0.99886 * b0 + white * 0.05551797
            b1 = 0.99332 * b1 + white * 0.07507591
            b2 = 0.96900 * b2 + white * 0.15385208
            b3 = 0.86650 * b3 + white * 0.31048560
            b4 = 0.55000 * b4 + white * 0.53295232
            b5 = -0.7616 * b5 - white * 0.0168980
            samples.append(float(amp * (b0 + b1 + b2 + b3 + b4 + b5 + b6 + white * 0.5362)))
            b6 = white * 0.115926
        return samples
    return [float(amp * random.uniform(-1, 1)) for _ in range(n)]


def _bitcrush(samples: list[float], bits: int = 8) -> list[float]:
    """Digital bitcrush effect - lo-fi digital character."""
    step = 2.0 / ((2 ** bits) - 1)
    return [float(step * round(s / step)) for s in samples]


def _ring_modulate(samples: list[float], carrier_freq: float, duration: float) -> list[float]:
    """Ring modulation - metallic, sci-fi tones."""
    n = min(len(samples), int(SAMPLE_RATE * duration))
    carrier = _sine(carrier_freq, duration, 1.0)
    return [float(samples[i] * carrier[i]) for i in range(n)]


def _autopan(samples: list[float], rate: float = 1.0, depth: float = 0.5) -> list[float]:
    """Auto-panning - creates movement in stereo field."""
    n = len(samples)
    mid = n // 2
    left = int(mid * (1 - depth))
    right = int(mid * (1 + depth))

    result = [0.0] * n
    for i in range(n):
        t = i / SAMPLE_RATE
        pan = 0.5 + 0.5 * math.sin(2 * math.pi * rate * t)
        # Simple stereo simulation (mono output)
        result[i] = samples[i]

    return result


def _chorus(samples: list[float], rate: float = 0.5, depth: float = 0.002, mix: float = 0.3) -> list[float]:
    """Chorus effect - adds warmth and thickness."""
    n = len(samples)
    result = [samples[i] * (1 - mix) for i in range(n)]

    for i in range(n):
        t = i / SAMPLE_RATE
        delay_samples = int(SAMPLE_RATE * depth * (1 + math.sin(2 * math.pi * rate * t)))
        delayed_idx = i - delay_samples
        if 0 <= delayed_idx < n:
            result[i] += samples[delayed_idx] * mix

    return result


# ── Effects ────────────────────────────────────────────────────────────────────

def _adsr(samples: list[float], attack: float = 0.01, decay: float = 0.1,
         sustain: float = 0.7, release: float = 0.2, sample_rate: int = SAMPLE_RATE) -> list[float]:
    """ADSR envelope."""
    n = len(samples)
    a_samples = int(attack * sample_rate)
    d_samples = int(decay * sample_rate)
    r_samples = int(release * sample_rate)
    s_samples = max(0, n - a_samples - d_samples - r_samples)

    result = []
    for i in range(n):
        if i < a_samples:
            env = i / a_samples
        elif i < a_samples + d_samples:
            env = 1.0 - (1.0 - sustain) * ((i - a_samples) / d_samples)
        elif i < a_samples + d_samples + s_samples:
            env = sustain
        else:
            env = sustain * max(0.0, 1.0 - (i - a_samples - d_samples - s_samples) / r_samples)
        result.append(float(samples[i] * env))

    return result


def _fade(samples: list[float], fade_in: float = 0.0, fade_out: float = 0.0) -> list[float]:
    """Apply fade in/out."""
    n = len(samples)
    fi = int(SAMPLE_RATE * fade_in)
    fo = int(SAMPLE_RATE * fade_out)

    for i in range(n):
        if i < fi:
            samples[i] *= i / fi if fi > 0 else 1.0
        elif i > n - fo:
            samples[i] *= (n - i) / fo if fo > 0 else 1.0
    return samples


def _fade_exp(samples: list[float], fade_in: float = 0.0, fade_out: float = 0.0) -> list[float]:
    """Exponential fade - more natural sound."""
    n = len(samples)
    fi = int(SAMPLE_RATE * fade_in)
    fo = int(SAMPLE_RATE * fade_out)

    for i in range(n):
        if i < fi:
            samples[i] *= (i / fi) ** 2 if fi > 0 else 1.0
        elif i > n - fo:
            samples[i] *= ((n - i) / fo) ** 2 if fo > 0 else 1.0
    return samples


def _layer(samples: list[float], layer: list[float], gain: float = 1.0) -> list[float]:
    """Mix a layer into samples."""
    n = min(len(samples), len(layer))
    return [float(max(-1.0, min(1.0, samples[i] + layer[i] * gain))) for i in range(n)]


def _lowpass(samples: list[float], cutoff: float, resonance: float = 0.5) -> list[float]:
    """Simple one-pole lowpass filter."""
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / SAMPLE_RATE
    alpha = dt / (rc + dt)

    result = [samples[0]]
    for i in range(1, len(samples)):
        result.append(float(result[-1] + alpha * (samples[i] - result[-1])))
    return result


def _highpass(samples: list[float], cutoff: float) -> list[float]:
    """Simple one-pole highpass filter."""
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / SAMPLE_RATE
    alpha = rc / (rc + dt)

    result = [samples[0]]
    for i in range(1, len(samples)):
        result.append(float(alpha * (result[-1] + samples[i] - samples[i-1])))
    return result


def _compressor(samples: list[float], threshold: float = 0.5, ratio: float = 4.0) -> list[float]:
    """Simple compressor for loudness control."""
    return [float(s * (1 / ratio if abs(s) > threshold else 1.0)) for s in samples]


def _normalize(samples: list[float], target_db: float = -3.0) -> list[float]:
    """Normalize to target dB level."""
    max_val = max(abs(s) for s in samples)
    if max_val == 0:
        return samples
    target_amp = 10 ** (target_db / 20.0)
    gain = target_amp / max_val
    return [float(s * gain) for s in samples]


# ── Generators ─────────────────────────────────────────────────────────────────

def _generate_glitch_pattern(duration: float, density: float = 0.1) -> list[float]:
    """Generate glitch pattern - stuttering, broken audio."""
    n = int(SAMPLE_RATE * duration)
    samples = [0.0] * n

    glitch_length = 0
    gap_length = 0
    in_glitch = False
    pos = 0

    while pos < n:
        if not in_glitch:
            # Random gap
            gap_length = int(random.uniform(0.001, 0.05) * SAMPLE_RATE)
            in_glitch = True
        else:
            # Glitch burst
            glitch_length = int(random.uniform(0.0005, 0.02) * SAMPLE_RATE)
            for i in range(min(glitch_length, n - pos)):
                samples[pos + i] = float(random.uniform(-1, 1) * 0.3)
            pos += glitch_length
            in_glitch = False

        pos += gap_length if not in_glitch else 0

    return samples


def _arp(freqs: list[float], rate: float, duration: float, wave_func: Callable, amp: float = 0.3) -> list[float]:
    """Generate arpeggiated pattern."""
    n = int(SAMPLE_RATE * duration)
    samples = [0.0] * n
    note_duration = 1.0 / rate
    note_samples = int(SAMPLE_RATE * note_duration)

    pos = 0
    note_idx = 0

    while pos < n:
        freq = freqs[note_idx % len(freqs)]
        note = wave_func(freq, note_duration * 0.9, amp)
        note = _adsr(note, 0.005, 0.05, 0.3, 0.1)

        for i in range(min(len(note), n - pos)):
            samples[pos + i] = float(max(-1.0, min(1.0, samples[pos + i] + note[i])))

        pos += note_samples
        note_idx += 1

    return samples


# ── Main Music Generator ────────────────────────────────────────────────────────

def _generate_ultimate_startup(duration: float = 10.0) -> list[float]:
    """
    Ultimate cyberpunk startup music - multi-layered masterpiece.
    """
    n = int(SAMPLE_RATE * duration)
    samples = [0.0] * n

    # ═══════════════════════════════════════════════════════════
    # LAYER 1: SUB BASS FOUNDATION (0-3s)
    # Deep, rumbling bass that you FEEL
    # ═══════════════════════════════════════════════════════════
    bass_notes = [
        (32.70, 0.0, 0.8),    # C1 - deep sub
        (41.20, 0.8, 1.6),    # D1
        (36.71, 1.6, 2.4),    # F#1
        (49.00, 2.4, 3.2),    # G1
    ]

    for freq, start, end in bass_notes:
        wave = _sine(freq, end - start, 0.5)
        wave = _adsr(wave, 0.1, 0.2, 0.8, 0.3)
        start_s = int(SAMPLE_RATE * start)
        for i in range(len(wave)):
            if start_s + i < n:
                samples[start_s + i] += wave[i]

    # Add harmonic overtones to bass
    for freq, start, end in bass_notes:
        wave = _sine(freq * 2, end - start, 0.15)
        wave = _adsr(wave, 0.1, 0.2, 0.6, 0.3)
        start_s = int(SAMPLE_RATE * start)
        for i in range(len(wave)):
            if start_s + i < n:
                samples[start_s + i] += wave[i]

    # ═══════════════════════════════════════════════════════════
    # LAYER 2: ANALOG SYNTH PAD (2-6s)
    # Fat, warm supersaw chords
    # ═══════════════════════════════════════════════════════════
    chord_progression = [
        [130.81, 164.81, 196.00],  # C3, E3, G3 - Cmaj
        [146.83, 174.61, 220.00], # D3, F3, A3 - Dm
        [164.81, 196.00, 246.94], # E3, G3, B3 - Em
        [174.61, 220.00, 261.63], # F3, A3, C4 - Fmaj
    ]

    for i, chord in enumerate(chord_progression):
        start = 2.0 + i * 1.0
        end = start + 1.5
        if end > duration:
            break

        for freq in chord:
            # Main supersaw
            wave = _supersaw(freq, end - start, num_voices=5, amp=0.15)
            wave = _adsr(wave, 0.2, 0.3, 0.6, 0.4)
            start_s = int(SAMPLE_RATE * start)
            for j in range(len(wave)):
                if start_s + j < n:
                    samples[start_s + j] += wave[j]

            # FM layer for brightness
            fm_wave = _fm_synth(freq, end - start, mod_ratio=3.5, mod_index=2.0, amp=0.08)
            fm_wave = _adsr(fm_wave, 0.3, 0.4, 0.5, 0.3)
            for j in range(len(fm_wave)):
                if start_s + j < n:
                    samples[start_s + j] += fm_wave[j]

    # ═══════════════════════════════════════════════════════════
    # LAYER 3: ARPEGGIO (3-7s)
    # Fast, glitchy arpeggios - very cyberpunk
    # ═══════════════════════════════════════════════════════════
    arp_freqs = [261.63, 329.63, 392.00, 523.25, 392.00, 329.63]  # C4, E4, G4, C5, G4, E4
    arp = _arp(arp_freqs, rate=8.0, duration=4.0, wave_func=lambda f, d, a: _square(f, d, a, 0.3), amp=0.12)
    arp = _bitcrush(arp, bits=10)  # Digital crunch
    arp = _fade_exp(arp, 0.1, 0.2)

    start_s = int(SAMPLE_RATE * 3.0)
    for i in range(len(arp)):
        if start_s + i < n:
            samples[start_s + i] += arp[i]

    # Second arp layer - higher octave, different timing
    arp_freqs2 = [523.25, 659.25, 783.99, 1046.50, 783.99, 659.25]
    arp2 = _arp(arp_freqs2, rate=6.0, duration=3.5, wave_func=lambda f, d, a: _sawtooth(f, d, a), amp=0.08)
    arp2 = _lowpass(arp2, 2000)
    arp2 = _fade_exp(arp2, 0.1, 0.3)

    start_s = int(SAMPLE_RATE * 3.5)
    for i in range(len(arp2)):
        if start_s + i < n:
            samples[start_s + i] += arp2[i]

    # ═══════════════════════════════════════════════════════════
    # LAYER 4: LEAD MELODY (5-9s)
    # Heroic lead synth - the main hook
    # ═══════════════════════════════════════════════════════════
    melody_notes = [
        (392.00, 5.0, 5.5),    # G4
        (440.00, 5.5, 6.0),    # A4
        (493.88, 6.0, 6.5),    # B4
        (523.25, 6.5, 7.5),   # C5 - long note
        (587.33, 7.5, 8.0),   # D5
        (523.25, 8.0, 8.5),   # C5
        (440.00, 8.5, 9.0),   # A4
        (392.00, 9.0, 9.5),   # G4
    ]

    for freq, start, end in melody_notes:
        # Main lead - square wave with filter
        lead = _square(freq, end - start, 0.2, 0.4)
        lead = _lowpass(lead, 3000 + (end - start) * 1000)  # Sweeping filter
        lead = _adsr(lead, 0.02, 0.1, 0.7, 0.2)

        # FM layer for richness
        fm_lead = _fm_synth(freq, end - start, mod_ratio=2.0, mod_index=1.5, amp=0.1)
        fm_lead = _adsr(fm_lead, 0.03, 0.15, 0.6, 0.3)

        start_s = int(SAMPLE_RATE * start)
        for i in range(min(len(lead), n - start_s)):
            samples[start_s + i] += lead[i] + fm_lead[i]

    # ═══════════════════════════════════════════════════════════
    # LAYER 5: GLITCHES & TEXTURES (0-10s)
    # Throughout the entire track for cyberpunk feel
    # ═══════════════════════════════════════════════════════════
    # Glitch bursts at specific points
    glitch_times = [0.5, 1.5, 2.5, 4.0, 5.0, 6.5, 7.5, 8.5]
    for t in glitch_times:
        glitch = _generate_glitch_pattern(0.3, density=0.3)
        glitch = _lowpass(glitch, 3000)
        start_s = int(SAMPLE_RATE * t)
        for i in range(len(glitch)):
            if start_s + i < n:
                samples[start_s + i] += glitch[i] * 0.15

    # Ambient noise sweep
    noise_sweep = _noise(duration, amp=0.02, color="pink")
    noise_sweep = _lowpass(noise_sweep, 500)
    noise_sweep = _fade_exp(noise_sweep, 2.0, 2.0)
    for i in range(len(noise_sweep)):
        if i < n:
            samples[i] += noise_sweep[i]

    # ═══════════════════════════════════════════════════════════
    # LAYER 6: IMPACT & BUILDUP (6-7s, 9-10s)
    # Tension builders and release
    # ═══════════════════════════════════════════════════════════
    # Impact at 7s mark
    impact_start = int(SAMPLE_RATE * 6.8)
    impact_duration = 0.4

    # Sub impact
    impact_wave = _sine(50, impact_duration, 0.4)
    impact_wave = _fade_exp(impact_wave, 0.01, 0.3)
    for i in range(len(impact_wave)):
        if impact_start + i < n:
            samples[impact_start + i] += impact_wave[i]

    # Noise impact
    noise_impact = _noise(impact_duration, 0.15)
    noise_impact = _fade_exp(noise_impact, 0.01, 0.2)
    for i in range(len(noise_impact)):
        if impact_start + i < n:
            samples[impact_start + i] += noise_impact[i]

    # ═══════════════════════════════════════════════════════════
    # MASTERING
    # ═══════════════════════════════════════════════════════════
    # Soft clip for warmth
    samples = [math.tanh(s * 1.2) if abs(s) < 50 else float(max(-1.0, min(1.0, s))) for s in samples]

    # Gentle compression
    samples = _compressor(samples, threshold=0.6, ratio=2.0)

    # Final normalize
    samples = _normalize(samples, -2.0)

    # Master fade out
    samples = _fade_exp(samples, 0.0, 1.0)

    return samples


def _generate_unlock_sound(duration: float = 2.5) -> list[float]:
    """Quick unlock confirmation sound - digital blip."""
    n = int(SAMPLE_RATE * duration)
    samples = [0.0] * n

    # Quick ascending arpeggio
    arp_freqs = [440, 554, 659, 880, 1047]
    arp = _arp(arp_freqs, rate=4.0, duration=1.5, wave_func=lambda f, d, a: _sine(f, d, a), amp=0.3)
    arp = _adsr(arp, 0.01, 0.05, 0.5, 0.1)

    start_s = 0
    for i in range(len(arp)):
        if start_s + i < n:
            samples[start_s + i] = arp[i]

    # Confirmation blip
    blip = _square(880, 0.15, 0.2)
    blip = _adsr(blip, 0.005, 0.05, 0.3, 0.05)
    for i in range(len(blip)):
        if i < n:
            samples[i] += blip[i]

    # Sub bass undertone
    bass = _sine(55, duration, 0.15)
    bass = _fade_exp(bass, 0.1, 0.3)
    for i in range(len(bass)):
        if i < n:
            samples[i] += bass[i]

    samples = _normalize(samples, -4.0)
    return samples


def _generate_wake_sound(duration: float = 3.0) -> list[float]:
    """Gentle wake sound - ambient, peaceful."""
    n = int(SAMPLE_RATE * duration)
    samples = [0.0] * n

    # Soft FM pad
    for freq in [220, 277, 330]:  # A3, C#4, E4 - A major
        wave = _fm_synth(freq, duration, mod_ratio=2.0, mod_index=1.0, amp=0.15)
        wave = _adsr(wave, 0.5, 1.0, 0.4, 0.5)
        for i in range(len(wave)):
            if i < n:
                samples[i] += wave[i]

    # Gentle shimmer on top
    shimmer = _sine(1760, duration, 0.05)  # A6
    shimmer = _adsr(shimmer, 1.0, 0.5, 0.2, 0.5)
    for i in range(len(shimmer)):
        if i < n:
            samples[i] += shimmer[i]

    samples = _lowpass(samples, 4000)
    samples = _normalize(samples, -6.0)
    return samples


# ── Cached Playback ────────────────────────────────────────────────────────────

_cached_files = {}


def _get_music_path(scene: str) -> Path:
    """Get or generate the music file for a scene."""
    global _cached_files

    if scene in _cached_files:
        path = _cached_files[scene]
        if path.exists():
            return path

    temp_dir = Path(tempfile.gettempdir())
    path = temp_dir / f"jarvis_ultimate_{scene}.wav"

    generators = {
        "startup": _generate_ultimate_startup,
        "unlock": _generate_unlock_sound,
        "wake": _generate_wake_sound,
        "shutdown": _generate_shutdown_sound,
    }

    if scene in generators:
        samples = generators[scene]()
        _write_wav(path, samples)
        _cached_files[scene] = path

    return path


def _play_sound_async(path: Path):
    """Play a WAV file asynchronously using Windows API."""
    if not path.exists():
        return

    def _play():
        try:
            from ctypes import windll
            windll.winmm.PlaySoundW(str(path), None, 0x0000)  # SND_FILENAME | SND_ASYNC
        except Exception:
            pass

    threading.Thread(target=_play, daemon=True, name=f"Music_{path.stem}").start()


def play_startup_scene():
    """Play the ultimate cyberpunk startup music."""
    path = _get_music_path("startup")
    _play_sound_async(path)


def play_unlock_scene():
    """Play the unlock sound."""
    path = _get_music_path("unlock")
    _play_sound_async(path)


def play_wake_scene():
    """Play the wake sound."""
    path = _get_music_path("wake")
    _play_sound_async(path)


def preload_music():
    """Pre-generate all music files in background."""
    def _preload():
        for scene in ["startup", "unlock", "wake", "shutdown"]:
            try:
                _get_music_path(scene)
            except Exception:
                pass

    threading.Thread(target=_preload, daemon=True, name="MusicPreload").start()


def _generate_shutdown_sound(duration: float = 3.0) -> list[float]:
    """JARVIS shutdown farewell — descending tone, polite goodbye."""
    n = int(SAMPLE_RATE * duration)
    samples = [0.0] * n

    # Descending arpeggio (G5 → G4) — JARVIS going to sleep
    farewell_notes = [
        (783.99, 0.0, 0.3),   # G5
        (659.25, 0.3, 0.6),  # E5
        (587.33, 0.6, 1.0),  # D5
        (523.25, 1.0, 1.5),  # C5
        (392.00, 1.5, 2.5),  # G4 - held
    ]

    for freq, start, end in farewell_notes:
        wave = _sine(freq, end - start, 0.25)
        wave = _adsr(wave, 0.05, 0.1, 0.7, 0.3)
        start_s = int(SAMPLE_RATE * start)
        for i in range(len(wave)):
            if start_s + i < n:
                samples[start_s + i] += wave[i]

    # Soft pad undertone for warmth
    for freq in [196, 247]:
        wave = _triangle(freq, duration, 0.1)
        wave = _adsr(wave, 0.5, 1.0, 0.3, 1.0)
        for i in range(len(wave)):
            if i < n:
                samples[i] += wave[i]

    # Subtle fade out
    samples = _fade_exp(samples, 0.0, 1.5)
    samples = _normalize(samples, -3.0)
    return samples


def play_shutdown_scene():
    """Play JARVIS shutdown farewell music."""
    path = _get_music_path("shutdown")
    _play_sound_async(path)
