"""
cinematic_intro.py - JARVIS Cinematic Intro Animation
A stunning, lightweight intro animation that plays on JARVIS startup.
"""

import sys
import math
import time
import threading
from pathlib import Path
from typing import Callable

try:
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    tk = None


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()

# Brand colors
C_BG     = "#0F172A"
C_CYAN   = "#22D3EE"
C_CYAN_D = "#0E7490"
C_WHITE  = "#F0F9FF"
C_GLOW   = "#67E8F9"


class CinematicIntro:
    """
    Plays a stunning cinematic intro animation overlay.
    Call .play() to start, .close() to dismiss.
    """

    def __init__(self, on_complete: Callable | None = None):
        self.on_complete = on_complete
        self._root = None
        self._canvas = None
        self._running = False
        self._phase = 0
        self._start_time = 0
        self._labels = []
        self._logo_tk = None

        # Phase durations (seconds)
        self.DARK      = 0.8   # Black screen, silence
        self.PARTICLE  = 1.5   # Particles converge to center
        self.LOGO_EMERGE = 1.2  # Logo fades/scales in
        self.GLOW_PULSE = 0.8   # Glow pulse
        self.TEXT_REVEAL = 1.5  # "JARVIS" text reveals
        self.HOLD      = 2.0   # Hold the full logo
        self.FADE_OUT  = 1.0   # Fade to transparent

        self.TOTAL = (self.DARK + self.PARTICLE + self.LOGO_EMERGE +
                       self.GLOW_PULSE + self.TEXT_REVEAL + self.HOLD + self.FADE_OUT)

        self._particle_data = self._generate_particles(120)

    def _generate_particles(self, count: int) -> list[dict]:
        """Generate random particle data for the convergence animation."""
        import random
        particles = []
        sw = 900
        sh = 600
        cx, cy = sw // 2, sh // 2
        for i in range(count):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(150, 380)
            particles.append({
                "x": cx + math.cos(angle) * dist,
                "y": cy + math.sin(angle) * dist,
                "target_x": cx,
                "target_y": cy,
                "speed": random.uniform(0.04, 0.12),
                "size": random.uniform(1.5, 4.0),
                "alpha": random.uniform(0.3, 1.0),
                "phase": random.uniform(0, math.pi * 2),
            })
        return particles

    def _lerp(self, a: float, b: float, t: float) -> float:
        return a + (b - a) * max(0.0, min(1.0, t))

    def _phase_time(self, elapsed: float) -> tuple[str, float]:
        """Returns (current_phase, progress_in_phase)."""
        t = elapsed
        phases = [
            ("dark",     self.DARK),
            ("particle", self.PARTICLE),
            ("logo",     self.LOGO_EMERGE),
            ("glow",     self.GLOW_PULSE),
            ("text",     self.TEXT_REVEAL),
            ("hold",     self.HOLD),
            ("fade",     self.FADE_OUT),
        ]
        for name, dur in phases:
            if t < dur:
                return name, t / dur
            t -= dur
        return "done", 1.0

    def _ease_out(self, t: float) -> float:
        return 1 - (1 - t) ** 3

    def _ease_in_out(self, t: float) -> float:
        return t * t * (3 - 2 * t)

    def _ease_elastic(self, t: float) -> float:
        if t == 0 or t == 1:
            return t
        p = 0.4
        return math.pow(2, -10 * t) * math.sin((t - p / 4) * (2 * math.pi) / p) + 1

    def _draw_frame(self, canvas: tk.Canvas, elapsed: float):
        """Draw one frame of the intro animation."""
        canvas.delete("all")
        W, H = 900, 600
        cx, cy = W // 2, H // 2

        phase, prog = self._phase_time(elapsed)

        # ── DARK PHASE ─────────────────────────────────────────────────────
        if phase == "dark":
            canvas.create_rectangle(0, 0, W, H, fill=C_BG, outline="")
            return

        # ── PARTICLE CONVERGENCE PHASE ────────────────────────────────────
        if phase == "particle":
            canvas.create_rectangle(0, 0, W, H, fill=C_BG, outline="")

            t = self._ease_in_out(prog)
            for p in self._particle_data:
                px = self._lerp(p["x"], p["target_x"], t)
                py = self._lerp(p["y"], p["target_y"], t)
                size = p["size"] * (1 - t * 0.5)
                alpha = p["alpha"] * (0.3 + t * 0.7)
                col = self._rgba_str(34, 211, 238, alpha)
                canvas.create_oval(
                    px - size, py - size, px + size, py + size,
                    fill=col, outline=""
                )
            return

        # ── LOGO EMERGE PHASE ─────────────────────────────────────────────
        if phase == "logo":
            canvas.create_rectangle(0, 0, W, H, fill=C_BG, outline="")

            t = self._ease_elastic(min(prog, 1.0))
            scale = 0.3 + t * 0.7
            alpha = min(prog * 2, 1.0)

            # Draw logo
            logo = self._get_logo()
            if logo:
                lw, lh = logo.width, logo.height
                scaled = logo.resize((int(lw * scale), int(lh * scale)), Image.LANCZOS)
                tk_logo = ImageTk.PhotoImage(scaled)
                self._logo_tk = tk_logo  # Keep reference

                lx = cx - scaled.width // 2
                ly = cy - scaled.height // 2
                canvas.create_image(lx + scaled.width // 2, ly + scaled.height // 2,
                                   image=tk_logo)

            # Central glow
            glow_r = int(200 * t)
            for r in range(glow_r, 0, -15):
                frac = (glow_r - r) / glow_r
                a = int(30 * alpha * (1 - frac))
                col = self._rgba_str(34, 211, 238, a)
                canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    outline=col, width=1
                )
            return

        # ── GLOW PULSE PHASE ──────────────────────────────────────────────
        if phase == "glow":
            canvas.create_rectangle(0, 0, W, H, fill=C_BG, outline="")

            pulse = 0.7 + 0.3 * math.sin(prog * math.pi * 4)

            # Radial rings
            for i in range(8):
                r = 80 + i * 25 + int(30 * pulse)
                a = int(60 * pulse * (1 - i / 10))
                col = self._rgba_str(34, 211, 238, max(0, a))
                canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 outline=col, width=1)

            # Logo at center
            logo = self._get_logo()
            if logo:
                lw, lh = logo.width, logo.height
                tk_logo = ImageTk.PhotoImage(logo)
                self._logo_tk = tk_logo
                canvas.create_image(cx - lw // 2, cy - lh // 2, image=tk_logo, anchor="nw")

            # Top + bottom lines
            line_alpha = int(100 * pulse)
            canvas.create_line(0, 30, W, 30, fill=self._rgba_str(34, 211, 238, line_alpha), width=1)
            canvas.create_line(0, H - 30, W, H - 30, fill=self._rgba_str(34, 211, 238, line_alpha), width=1)
            return

        # ── TEXT REVEAL PHASE ──────────────────────────────────────────────
        if phase == "text":
            canvas.create_rectangle(0, 0, W, H, fill=C_BG, outline="")

            # Logo still there
            logo = self._get_logo()
            if logo:
                lw, lh = logo.width, logo.height
                tk_logo = ImageTk.PhotoImage(logo)
                self._logo_tk = tk_logo
                canvas.create_image(cx - lw // 2, cy - lh // 2, image=tk_logo, anchor="nw")

            # "JARVIS" text reveal
            text_t = self._ease_out(prog)
            text_alpha = int(255 * text_t)

            # Glow behind text
            glow_x = cx
            glow_y = cy + 120
            for gr in range(60, 0, -8):
                ga = int(text_alpha * 0.03 * (60 - gr) / 60)
                canvas.create_oval(
                    glow_x - gr, glow_y - gr, glow_x + gr, glow_y + gr,
                    fill=self._rgba_str(34, 211, 238, ga), outline=""
                )

            # Main text
            canvas.create_text(
                cx, cy + 120,
                text="JARVIS",
                fill=self._rgba_hex(C_CYAN, text_alpha),
                font=("Segoe UI", 28, "bold"),
                anchor="center"
            )

            # Subtitle
            sub_alpha = int(text_alpha * 0.7)
            canvas.create_text(
                cx, cy + 155,
                text="JUST A RATHER VERY INTELLIGENT SYSTEM",
                fill=self._rgba_hex(C_CYAN_D, sub_alpha),
                font=("Consolas", 8),
                anchor="center"
            )

            # Decorative lines
            line_a = int(80 * text_alpha / 255)
            canvas.create_line(cx - 180, cy + 120, cx - 70, cy + 120,
                              fill=self._rgba_str(34, 211, 238, line_a), width=1)
            canvas.create_line(cx + 70, cy + 120, cx + 180, cy + 120,
                              fill=self._rgba_str(34, 211, 238, line_a), width=1)
            return

        # ── HOLD PHASE ─────────────────────────────────────────────────────
        if phase == "hold":
            canvas.create_rectangle(0, 0, W, H, fill=C_BG, outline="")

            logo = self._get_logo()
            if logo:
                lw, lh = logo.width, logo.height
                tk_logo = ImageTk.PhotoImage(logo)
                self._logo_tk = tk_logo
                canvas.create_image(cx - lw // 2, cy - lh // 2, image=tk_logo, anchor="nw")

            # Animated rings
            t_anim = elapsed * 1.5
            for i in range(6):
                r = 80 + i * 28
                a = int(40 * (1 - i / 8))
                rot = t_anim + i * 0.5
                col = self._rgba_str(34, 211, 238, max(0, a))
                canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 outline=col, width=1)

            # Text
            canvas.create_text(cx, cy + 120, text="JARVIS",
                              fill=C_CYAN, font=("Segoe UI", 28, "bold"), anchor="center")
            canvas.create_text(cx, cy + 155,
                              text="JUST A RATHER VERY INTELLIGENT SYSTEM",
                              fill=C_CYAN_D, font=("Consolas", 8), anchor="center")
            return

        # ── FADE OUT PHASE ─────────────────────────────────────────────────
        if phase == "fade":
            t = self._ease_in_out(prog)
            alpha = int(255 * (1 - t))

            canvas.create_rectangle(0, 0, W, H, fill=C_BG, outline="")

            logo = self._get_logo()
            if logo:
                lw, lh = logo.width, logo.height
                # Apply fade to logo
                faded = logo.copy()
                alpha_layer = Image.new("RGBA", logo.size, (15, 23, 42, alpha))
                faded = Image.alpha_composite(faded, alpha_layer)
                tk_logo = ImageTk.PhotoImage(faded)
                self._logo_tk = tk_logo
                canvas.create_image(cx - lw // 2, cy - lh // 2, image=tk_logo, anchor="nw")

            # Faded text
            canvas.create_text(cx, cy + 120, text="JARVIS",
                              fill=self._rgba_hex(C_CYAN, alpha),
                              font=("Segoe UI", 28, "bold"), anchor="center")
            canvas.create_text(cx, cy + 155,
                              text="JUST A RATHER VERY INTELLIGENT SYSTEM",
                              fill=self._rgba_hex(C_CYAN_D, int(alpha * 0.7)),
                              font=("Consolas", 8), anchor="center")
            return

    def _rgba_str(self, r: int, g: int, b: int, a: int) -> str:
        """Convert RGBA to Tkinter color (uses 6-char hex, alpha ignored)."""
        return f"#{r:02x}{g:02x}{b:02x}"

    def _rgba_hex(self, hex_color: str, alpha: int) -> str:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        return self._rgba_str(r, g, b, alpha)

    def _get_logo(self):
        """Get the JARVIS logo image."""
        try:
            from core.branding import generate_icon
            return generate_icon(200, style="default")
        except Exception:
            return None

    def _animation_loop(self):
        """Run the animation loop."""
        self._start_time = time.time()
        self._running = True
        self._window_ready = False

        def tick():
            if not self._running:
                return

            elapsed = time.time() - self._start_time
            phase, prog = self._phase_time(elapsed)

            self._draw_frame(self._canvas, elapsed)
            self._window_ready = True  # Mark window as ready after first frame

            if phase == "done":
                self.close()
                return

            # Frame timing: faster during particle phase, slower during hold
            delay = 16 if phase in ("particle", "glow") else 25
            self._root.after(delay, tick)

        # Start animation loop after window is fully visible (one frame delay)
        self._root.after(50, tick)

    def play(self, parent_root=None):
        """Start the cinematic intro."""
        if tk is None:
            if self.on_complete:
                self.on_complete()
            return

        # Create own window (not Tk() because parent_root may not be ready yet)
        self._root = tk.Toplevel(parent_root) if parent_root else tk.Tk()
        self._root.withdraw()
        self._root.configure(bg=C_BG)
        self._root.overrideredirect(True)

        # Center on screen
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        W, H = 900, 600
        x = (sw - W) // 2
        y = (sh - H) // 2
        self._root.geometry(f"{W}x{H}+{x}+{y}")

        # Make window appear above others
        self._root.attributes("-topmost", True)
        self._root.deiconify()

        self._canvas = tk.Canvas(self._root, width=W, height=H,
                                 bg=C_BG, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        # Close on click
        self._canvas.bind("<Button-1>", lambda e: self.close())

        self._animation_loop()

    def close(self):
        """Close the intro and trigger completion."""
        self._running = False
        if self._root:
            try:
                self._root.destroy()
            except Exception:
                pass
            self._root = None
        if self.on_complete:
            try:
                self.on_complete()
            except Exception:
                pass


# ── Quick play function ──────────────────────────────────────────────────────

_intro_instance = None


def play_intro(parent_root=None, on_complete=None):
    """Play the cinematic JARVIS intro."""
    global _intro_instance
    _intro_instance = CinematicIntro(on_complete=on_complete)
    _intro_instance.play(parent_root=parent_root)


def close_intro():
    """Programmatically close the intro."""
    global _intro_instance
    if _intro_instance:
        _intro_instance.close()
        _intro_instance = None
