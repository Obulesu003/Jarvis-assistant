# ui.py -- J.A.R.V.I.S MARK XXXV  |  Cinematic HUD Interface v2
# Dark slate + electric cyan branding with ambient glow effects

import logging  # migrated from print()
import contextlib
import io
import sys

for _s in (sys.stdout, sys.stderr):
    if isinstance(_s, io.TextIOWrapper):
        with contextlib.suppress(Exception): _s.reconfigure(encoding="utf-8", errors="replace")
import contextlib
import json
import math
import os
import random
import sys
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

try:
    from core.api_key_manager import is_configured as _is_configured
    from core.api_key_manager import save_api_keys
    _KEY_MANAGER_OK = True
except ImportError:
    _KEY_MANAGER_OK = False
    def _is_configured():
        return False


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "MARK XXXV"

# ── Cinematic Dark + Cyan Colour Palette ──────────────────────────────────────
C_BG      = "#0F172A"   # Deep slate - premium dark background
C_PANEL   = "#111827"   # Slightly lighter panel backgrounds
C_BORDER  = "#1E3A5F"   # Subtle border - slate blue
C_PRI     = "#22D3EE"   # Electric cyan - signature accent
C_PRI_D   = "#0E7490"   # Dimmed cyan
C_ACC     = "#F59E0B"   # Amber alert
C_ACC2    = "#FBBF24"   # Gold highlight
C_TEXT    = "#E0F2FE"   # Near-white text
C_TEXT_D  = "#7DD3FC"   # Dimmed text - sky blue
C_GREEN   = "#34D399"   # Active / listening
C_RED     = "#F87171"   # Error / muted
C_HOLO_A  = "#22D3EE22" # Holo fill (transparent cyan)


class JarvisUI:
    def __init__(self, face_path, size=None):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S -- MARK XXXV")
        self.root.resizable(False, False)
        self.root.configure(bg=C_BG)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 1100)
        H  = min(sh, 800)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.W = W
        self.H = H

        # Face / display centre
        self.FACE_SZ = min(int(H * 0.52), 420)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.38)

        # State
        self.speaking     = False
        self.muted        = False
        self._auto_permission = True   # Auto-accept tools by default
        self.scale        = 1.0
        self.target_scale = 1.0
        self.glow_a       = 80.0
        self.target_glow  = 80.0
        self.last_t       = time.time()
        self.tick         = 0
        self.radar_angle  = 0.0
        self.rings        = [0.0, 0.0, 0.0]
        self.scan_pos     = 0.0
        self._jarvis_state = "INITIALISING"
        self.status_blink  = True
        self.data_count    = 0

        self.typing_queue = deque()
        self.is_typing    = False
        self.on_text_command = None
        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._toplevels = {}  # Track open toplevel windows to prevent duplicates
        self._tray_icon = None  # System tray icon
        self._is_minimized_to_tray = False  # Track minimized state
        self._load_face(face_path)

        # Setup system tray if available
        self._setup_tray()

        # Check for --start-minimized flag
        if "--start-minimized" in sys.argv or "-m" in sys.argv:
            self.root.after(500, self._minimize_to_tray)

        # Main canvas -- the entire HUD
        self.c = tk.Canvas(self.root, width=W, height=H,
                           bg=C_BG, highlightthickness=0)
        self.c.pack(fill="both", expand=True)

        # Build UI layers (bottom to top)
        self._build_top_bar()     # title + time
        self._build_side_panels() # left stats + right actions
        self._build_input_bar()    # bottom command bar
        self._build_bottom_bar()   # footer
        self._build_overlay()      # HUD brackets + scan lines (on top)

        # API key check
        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        # Load auto_permission from settings
        try:
            cfg = BASE_DIR / "config" / "settings.json"
            if cfg.exists():
                data = json.loads(cfg.read_text(encoding="utf-8"))
                self._auto_permission = data.get("auto_permission", True)
        except Exception:
            self._auto_permission = True

        # Play cinematic intro on startup (unless minimized)
        self._play_cinematic_intro()

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

    # -- System Tray Support --------------------------------------------------

    def _setup_tray(self):
        """Setup system tray icon for persistent running."""
        try:
            # Try pystray for cross-platform tray
            from pystray import MenuItem as MenuItem, Icon as TrayIcon
            from PIL import Image
            import io

            # Create branded tray icon using JARVIS monogram
            try:
                from core.branding import generate_tray_icon
                img = generate_tray_icon(64)
            except Exception:
                # Fallback: create a simple branded icon
                img = Image.new("RGBA", (64, 64), (15, 23, 42, 255))
                draw = ImageDraw.Draw(img)
                # Draw a simple J shape
                draw.rectangle([22, 8, 38, 48], fill=(34, 211, 238, 255))  # stem
                draw.ellipse([22, 38, 50, 60], fill=(34, 211, 238, 255))     # hook

            # Create menu items
            def show_window(icon=None, item=None, evalue=None):
                self._restore_from_tray()

            def exit_app(icon=None, item=None, evalue=None):
                self.write_log("SYS: JARVIS shutting down...")
                os._exit(0)

            menu = (
                MenuItem("Show JARVIS", show_window),
                MenuItem("Exit", exit_app),
            )

            self._tray_icon = TrayIcon("JARVIS", img, "J.A.R.V.I.S", menu)
            self._tray_icon.run_detached()
            logging.getLogger("Tray").debug('System tray icon created')
            self.write_log("SYS: Running in system tray.")

        except ImportError:
            logging.getLogger("Tray").info('INFO: pystray not installed. Tray support disabled.')
            logging.getLogger("Tray").info('INFO: Install with: pip install pystray Pillow')
        except Exception as e:
            logging.getLogger("Tray").info(f"WARN: Could not setup tray: {e}")

    def _play_cinematic_intro(self):
        """Play the cinematic intro animation on startup."""
        if "--start-minimized" in sys.argv or "-m" in sys.argv:
            return  # Skip intro if starting minimized

        def on_intro_complete():
            self.write_log("SYS: JARVIS online. All systems operational.")

        try:
            from core.cinematic_intro import CinematicIntro

            def run_intro():
                intro = CinematicIntro(on_complete=on_intro_complete)
                intro.play(parent_root=self.root)

            # Schedule intro on main thread's event loop (Tkinter requires main thread)
            self.root.after(500, run_intro)
            logging.getLogger("Intro").debug('Cinematic intro playing')
        except Exception as e:
            logging.getLogger("Intro").warning(f"Intro skipped: {e}")
            on_intro_complete()

    def _minimize_to_tray(self):
        """Hide window and show only in tray."""
        if self._tray_icon:
            self.root.withdraw()
            self._is_minimized_to_tray = True
            self.write_log("SYS: Minimized to system tray. Double-click tray to restore.")

    def _restore_from_tray(self):
        """Show window from tray."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._is_minimized_to_tray = False
        self.write_log("SYS: JARVIS restored.")

    def _exit_from_tray(self):
        """Exit application from tray."""
        if self._tray_icon:
            self._tray_icon.stop()
        os._exit(0)

    # -- Top bar ---------------------------------------------------------------

    def _build_top_bar(self):
        c = self.c
        W, _H = self.W, self.H
        BAR_H = 48

        # Bar background with bottom glow line
        c.create_rectangle(0, 0, W, BAR_H, fill="#020810", outline="")
        c.create_line(0, BAR_H, W, BAR_H, fill=C_PRI_D, width=1)

        # Left: system badge
        c.create_rectangle(14, 8, 14 + 90, 40, outline=C_PRI_D, fill="", width=1)
        c.create_text(59, 24, text=MODEL_BADGE,
                      fill=C_PRI_D, font=("Consolas", 10, "bold"))

        # Centre: JARVIS title with glow
        c.create_text(W // 2, 14, text=SYSTEM_NAME,
                      fill=C_PRI, font=("Consolas", 20, "bold"))
        c.create_text(W // 2, 34, text="JUST A RATHER VERY INTELLIGENT SYSTEM",
                      fill=C_TEXT_D, font=("Consolas", 8))

        # Right: clock
        self._clock_id = c.create_text(W - 20, 24,
                      text=time.strftime("%H:%M:%S"),
                      fill=C_PRI, font=("Consolas", 14, "bold"), anchor="e")

    # -- Side panels ------------------------------------------------------------

    def _build_side_panels(self):
        c = self.c
        W, H = self.W, self.H
        PX  = 14      # panel left x
        PY  = 60      # panel top y
        PW  = 140     # panel width
        PH  = H - 180 # panel height

        # Left: System Stats panel
        self._lp_bg = c.create_rectangle(PX, PY, PX+PW, PY+PH,
                         fill=C_PANEL, outline=C_BORDER, width=1)
        c.create_text(PX + PW//2, PY + 18,
                      text="SYSTEM STATUS", fill=C_PRI,
                      font=("Consolas", 8, "bold"), anchor="center")

        # Stats lines
        self._stat_lines = {}
        stats = [
            ("CORE", "ONLINE"),
            ("VOICE", "STANDBY"),
            ("MEMORY", "ACTIVE"),
            ("NETWORK", "CONNECTED"),
            ("CAMERA", "READY"),
            ("SCHEDULER", "IDLE"),
            ("MONITOR", "OFF"),
        ]
        sy = PY + 46
        for key, val in stats:
            c.create_text(PX + 8, sy, text=key, fill=C_TEXT_D,
                          font=("Consolas", 7), anchor="w")
            tid = c.create_text(PX + PW - 8, sy, text=val, fill=C_GREEN,
                                font=("Consolas", 7, "bold"), anchor="e")
            self._stat_lines[key] = tid
            sy += 22

        # Progress bar simulation
        sy += 8
        c.create_text(PX + 8, sy, text="LOAD", fill=C_TEXT_D,
                      font=("Consolas", 7), anchor="w")
        self._load_bg = c.create_rectangle(PX+8, sy+4, PX+PW-8, sy+12,
                          fill=C_BORDER, outline="")
        self._load_bar = c.create_rectangle(PX+8, sy+4, PX+40, sy+12,
                          fill=C_PRI, outline="")
        sy += 22
        c.create_text(PX + 8, sy, text="UPTIME", fill=C_TEXT_D,
                      font=("Consolas", 7), anchor="w")
        self._uptime_id = c.create_text(PX+PW-8, sy, text="00:00:00",
                          fill=C_PRI, font=("Consolas", 7), anchor="e")

        # Right: Actions / Tools panel
        RX = W - PX - PW
        self._rp_bg = c.create_rectangle(RX, PY, RX+PW, PY+PH,
                         fill=C_PANEL, outline=C_BORDER, width=1)
        c.create_text(RX + PW//2, PY + 18,
                      text="AVAILABLE TOOLS", fill=C_PRI,
                      font=("Consolas", 8, "bold"), anchor="center")

        tools = [
            "WEB SEARCH", "WEATHER", "YOUTUBE",
            "CALENDAR", "EMAIL", "GITHUB",
            "FILES", "CODE", "SETTINGS",
        ]
        ty = PY + 46
        for tool in tools:
            # small dot + text
            tid = c.create_oval(RX + 14, ty - 4, RX + 18, ty,
                                fill=C_PRI_D, outline="")
            c.create_text(RX + 26, ty, text=tool, fill=C_TEXT,
                          font=("Consolas", 7), anchor="w")
            ty += 20

        # Buttons in right panel - use tags
        BY = PY + PH - 36
        c.create_rectangle(RX + 8, BY, RX + 68, BY + 24,
                           fill=C_BG, outline=C_PRI_D, width=1, tags="mute_btn")
        c.create_text(RX + 38, BY + 12, text="[MIC]",
                      fill=C_PRI, font=("Consolas", 8, "bold"), anchor="center", tags="mute_btn")
        c.create_rectangle(RX + 72, BY, RX + PW - 8, BY + 24,
                           fill=C_BG, outline=C_PRI_D, width=1, tags="set_btn")
        c.create_text(RX + PW - 38, BY + 12, text="[CFG]",
                      fill=C_PRI_D, font=("Consolas", 8, "bold"), anchor="center", tags="set_btn")
        HY = BY + 30
        c.create_rectangle(RX + 8, HY, RX + PW - 8, HY + 22,
                           fill=C_BG, outline=C_BORDER, width=1, tags="hist_btn")
        c.create_text(RX + PW // 2, HY + 11, text="HISTORY",
                      fill=C_TEXT_D, font=("Consolas", 8), anchor="center", tags="hist_btn")



    # -- Input bar
    def _build_input_bar(self):
        W, H = self.W, self.H
        LX   = 14 + 140 + 12   # after left panel
        RX   = W - 14 - 140 - 12
        BW   = 64
        IH   = 34
        IY   = H - 80
        IW   = RX - LX - BW - 6

        self._input_var = tk.StringVar()
        self._entry = tk.Entry(
            self.root,
            textvariable=self._input_var,
            fg=C_TEXT, bg="#030d18",
            insertbackground=C_PRI,
            borderwidth=0,
            font=("Consolas", 11),
            highlightthickness=1,
            highlightbackground=C_PRI_D,
            highlightcolor=C_PRI,
        )
        self._entry.place(x=LX, y=IY, width=IW, height=IH)
        self._entry.bind("<Return>", self._on_input_submit)
        self._entry.bind("<KP_Enter>", self._on_input_submit)

        self._send_btn = tk.Button(
            self.root,
            text="SEND",
            command=self._on_input_submit,
            fg=C_PRI, bg="#030d18",
            activeforeground=C_BG, activebackground=C_PRI,
            font=("Consolas", 10, "bold"),
            borderwidth=1,
            relief="flat",
            cursor="hand2",
            highlightbackground=C_PRI_D,
        )
        self._send_btn.place(x=RX - BW, y=IY, width=BW, height=IH)

    # -- Bottom bar -------------------------------------------------------------

    def _build_bottom_bar(self):
        c = self.c
        W, H = self.W, self.H
        BY = H - 36
        c.create_rectangle(0, BY, W, H, fill="#020810", outline="")
        c.create_line(0, BY, W, BY, fill=C_PRI_D, width=1)
        c.create_text(W // 2, BY + 18,
                      text="J.A.R.V.I.S  |  MARK XXXV  |  v3.5",
                      fill=C_TEXT_D, font=("Consolas", 7), anchor="center")
        self._status_id = c.create_text(20, BY + 18,
                         text="READY", fill=C_GREEN,
                         font=("Consolas", 8, "bold"), anchor="w")
        self._hint_id = c.create_text(W - 20, BY + 18,
                         text="[F4] MUTE  |  TYPE TO COMMAND",
                         fill=C_TEXT_D, font=("Consolas", 7), anchor="e")

    # -- HUD overlay (on top of everything) -------------------------------------

    def _build_overlay(self):
        c = self.c
        _W, _H = self.W, self.H
        FCX, FCY = self.FCX, self.FCY
        SZ = self.FACE_SZ

        # Store HUD item IDs for animation
        self._hud_ids = []

        # -- Corner brackets around the face area ----------------------------
        bracket_color = C_PRI
        blen = 32
        gap  = 8
        corners = [
            (FCX - SZ//2 - gap, FCY - SZ//2 - gap),   # top-left
            (FCX + SZ//2 + gap, FCY - SZ//2 - gap),   # top-right
            (FCX - SZ//2 - gap, FCY + SZ//2 + gap),   # bottom-left
            (FCX + SZ//2 + gap, FCY + SZ//2 + gap),   # bottom-right
        ]
        for cx, cy in corners:
            sx = 1 if cx < FCX else -1
            sy = 1 if cy < FCY else -1
            # Horizontal arm
            self._hud_ids.append(c.create_line(
                cx, cy, cx + sx * blen, cy, fill=bracket_color, width=2))
            # Vertical arm
            self._hud_ids.append(c.create_line(
                cx, cy, cx, cy + sy * blen, fill=bracket_color, width=2))
            # Small inner tick
            self._hud_ids.append(c.create_line(
                cx + sx * 6, cy + sy * 6, cx + sx * blen, cy,
                fill=bracket_color, width=1))

        # -- Top + bottom accent lines --------------------------------------
        # Top line across face area
        ty1 = FCY - SZ//2 - gap - 4
        self._hud_ids.append(c.create_line(
            FCX - SZ//2 - gap, ty1, FCX + SZ//2 + gap, ty1,
            fill=C_PRI_D, width=1))
        # Bottom line
        ty2 = FCY + SZ//2 + gap + 4
        self._hud_ids.append(c.create_line(
            FCX - SZ//2 - gap, ty2, FCX + SZ//2 + gap, ty2,
            fill=C_PRI_D, width=1))

        # -- Radial tick marks around outer ring ----------------------------
        outer_r = int(SZ * 0.58)
        inner_r = int(SZ * 0.55)
        for deg in range(0, 360, 15):
            rad = math.radians(deg)
            x1 = FCX + int(inner_r * math.cos(rad))
            y1 = FCY - int(inner_r * math.sin(rad))
            x2 = FCX + int(outer_r * math.cos(rad))
            y2 = FCY - int(outer_r * math.sin(rad))
            col = C_PRI if deg % 45 == 0 else C_PRI_D
            self._hud_ids.append(c.create_line(
                x1, y1, x2, y2, fill=col, width=1))

    # -- Face loader -------------------------------------------------------------

    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    # -- Animation loop ----------------------------------------------------------

    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        # Glow + scale breathing
        if now - self.last_t > (0.10 if self.speaking else 0.5):
            if self.muted:
                self.target_scale = 1.0
                self.target_glow  = random.uniform(30, 50)
            elif self.speaking:
                self.target_scale = random.uniform(1.06, 1.14)
                self.target_glow  = random.uniform(140, 200)
            else:
                self.target_scale = random.uniform(1.01, 1.06)
                self.target_glow  = random.uniform(80, 120)
            self.last_t = now

        sp = 0.3 if self.speaking else 0.12
        self.scale   += (self.target_scale - self.scale) * sp
        self.glow_a  += (self.target_glow  - self.glow_a)  * sp

        # Radar sweep
        self.radar_angle = (self.radar_angle + (3.5 if self.speaking else 1.2)) % 360

        # Ring spins
        for i, spd in enumerate([1.0, -0.7, 1.6] if self.speaking else [0.4, -0.25, 0.7]):
            self.rings[i] = (self.rings[i] + spd) % 360

        # Scan line position
        self.scan_pos = (self.scan_pos + 2.5) % self.FACE_SZ

        # Blink
        if t % 30 == 0:
            self.status_blink = not self.status_blink

        # Data counter
        self.data_count = (self.data_count + 1) % 1000

        self._draw()
        self.root.after(16, self._animate)

    # -- Main draw ---------------------------------------------------------------

    def _draw(self):
        c = self.c
        W, H = self.W, self.H
        t    = self.tick
        FCX, FCY = self.FCX, self.FCY
        SZ  = self.FACE_SZ
        c.delete("all")

        # -- Background grid -------------------------------------------------
        for x in range(0, W, 40):
            for y in range(0, H, 40):
                c.create_rectangle(x, y, x+1, y+1,
                                    fill="#0a1826", outline="")

        # -- Subtle vignette at edges ----------------------------------------
        for r in range(80, 0, -5):
            a = max(0, int(8 * (1 - r / 80)))
            col = f"#{a:02x}{a:02x}{a:02x}"
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r, fill="", outline=col, width=6)

        # -- Outer halo rings -------------------------------------------------
        ga = int(self.glow_a)
        for r_off in range(0, int(SZ * 0.35), 18):
            r    = int(SZ * 0.54 + r_off)
            frac = 1.0 - r_off / (SZ * 0.35)
            a    = max(0, min(255, int(ga * 0.07 * frac)))
            col = f"#{a // 2:02x}00{a // 3:02x}" if self.muted else f"#{a // 4:02x}{a:02x}{a:02x}"
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                          outline=col, width=1)

        # -- Rotating arc segments --------------------------------------------
        for idx, (r_frac, arc_l, gap) in enumerate([
                (0.46, 90, 70), (0.38, 60, 55), (0.30, 40, 40)]):
            ring_r = int(SZ * r_frac)
            base   = self.rings[idx]
            a_val  = max(0, min(255, int(ga * (1.0 - idx * 0.2))))
            col    = self._mcolor(255, 30, 80, a_val) if self.muted \
                     else self._mcolor(0, 212, 255, a_val)
            for s in range(360 // (arc_l + gap)):
                start = (base + s * (arc_l + gap)) % 360
                c.create_arc(FCX-ring_r, FCY-ring_r, FCX+ring_r, FCY+ring_r,
                             start=int(start), extent=arc_l,
                             outline=col, width=2 - idx, style="arc")

        # -- Radar sweep ------------------------------------------------------
        sr = int(SZ * 0.55)
        sweep_a = int(ga * 1.2)
        sweep_col = self._mcolor(0, 212, 255, sweep_a)
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=int(self.radar_angle - 25),
                     extent=25, outline=sweep_col, width=2, style="arc")
        # Fade trail
        for i in range(1, 5):
            trail_start = (self.radar_angle - 25 - i * 12) % 360
            trail_a = int(sweep_a * (1 - i * 0.2))
            c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                         start=int(trail_start), extent=10,
                         outline=self._mcolor(0, 180, 255, trail_a),
                         width=1, style="arc")

        # -- Crosshair --------------------------------------------------------
        ch_r  = int(SZ * 0.50)
        ch_gap = int(SZ * 0.14)
        ch_a  = int(ga * 0.5)
        ch_col = self._mcolor(0, 212, 255, ch_a)
        for x1, y1, x2, y2 in [
                (FCX - ch_r, FCY, FCX - ch_gap, FCY),
                (FCX + ch_gap, FCY, FCX + ch_r, FCY),
                (FCX, FCY - ch_r, FCX, FCY - ch_gap),
                (FCX, FCY + ch_gap, FCX, FCY + ch_r)]:
            c.create_line(x1, y1, x2, y2, fill=ch_col, width=1)

        # -- Glowing face / orb -----------------------------------------------
        if self._has_face:
            fw = int(SZ * self.scale)
            if (self._face_scale_cache is None or
                    abs(self._face_scale_cache[0] - self.scale) > 0.005):
                scaled  = self._face_pil.resize((fw, fw), Image.BILINEAR)
                tk_img  = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, tk_img)
            c.create_image(FCX, FCY, image=self._face_scale_cache[1])
        else:
            # Animated orb fallback
            orb_r = int(SZ * 0.25 * self.scale)
            orb_cols = [(255, 30, 80), (255, 60, 100), (180, 20, 60)] if self.muted \
                       else [(0, 180, 255), (0, 120, 220), (0, 80, 180)]
            for i in range(7, 0, -1):
                r2   = int(orb_r * i / 7)
                frac = i / 7
                ga2  = max(0, min(255, int(self.glow_a * frac)))
                c.create_oval(FCX-r2, FCY-r2, FCX+r2, FCY+r2,
                              fill=self._mcolor(orb_cols[2][0] * frac + orb_cols[0][0] * (1-frac),
                                                orb_cols[2][1] * frac + orb_cols[0][1] * (1-frac),
                                                orb_cols[2][2] * frac + orb_cols[0][2] * (1-frac),
                                                ga2),
                              outline="")
            c.create_text(FCX, FCY, text=SYSTEM_NAME,
                          fill=self._mcolor(0, 212, 255, min(255, int(self.glow_a * 1.5))),
                          font=("Consolas", 12, "bold"))

        # -- Corner brackets (HUD style) -------------------------------------
        bracket_color = C_PRI
        blen = 35
        gap  = 10
        corners = [
            (FCX - SZ//2 - gap, FCY - SZ//2 - gap,  1,  1),
            (FCX + SZ//2 + gap, FCY - SZ//2 - gap, -1,  1),
            (FCX - SZ//2 - gap, FCY + SZ//2 + gap,  1, -1),
            (FCX + SZ//2 + gap, FCY + SZ//2 + gap, -1, -1),
        ]
        for bx, by, sx, sy in corners:
            c.create_line(bx, by, bx + sx * blen, by,            fill=bracket_color, width=2)
            c.create_line(bx, by, bx,               by + sy * blen, fill=bracket_color, width=2)
            c.create_line(bx + sx * 6, by + sy * 6, bx + sx * blen, by,
                          fill=bracket_color, width=1)

        # -- Top + bottom face-area lines ------------------------------------
        ty1 = FCY - SZ//2 - gap - 6
        ty2 = FCY + SZ//2 + gap + 6
        c.create_line(FCX - SZ//2 - gap, ty1, FCX + SZ//2 + gap, ty1,
                      fill=C_PRI_D, width=1)
        c.create_line(FCX - SZ//2 - gap, ty2, FCX + SZ//2 + gap, ty2,
                      fill=C_PRI_D, width=1)

        # -- Radial ticks ----------------------------------------------------
        outer_r = int(SZ * 0.57)
        inner_r = int(SZ * 0.54)
        for deg in range(0, 360, 15):
            rad = math.radians(deg)
            x1 = FCX + int(inner_r * math.cos(rad))
            y1 = FCY - int(inner_r * math.sin(rad))
            x2 = FCX + int(outer_r * math.cos(rad))
            y2 = FCY - int(outer_r * math.sin(rad))
            col = C_PRI if deg % 45 == 0 else C_PRI_D
            c.create_line(x1, y1, x2, y2, fill=col, width=1)

        # -- Status text below face -------------------------------------------
        sy = FCY + SZ//2 + gap + 30
        if self.muted:
            sym, stat, sc = "X", "MUTED", C_RED
        elif self.speaking:
            sym, stat, sc = "*", "SPEAKING", C_ACC
        elif self._jarvis_state == "THINKING":
            sym = ">" if self.status_blink else " "
            stat, sc = "THINKING", C_ACC2
        elif self._jarvis_state == "PROCESSING":
            sym = "..." if self.status_blink else "   "
            stat, sc = "PROCESSING", C_ACC2
        else:  # LISTENING
            sym = "O" if self.status_blink else " "
            stat, sc = "LISTENING", C_GREEN
        c.create_text(W // 2, sy, text=f"[{sym}] {stat}",
                      fill=sc, font=("Consolas", 12, "bold"))

        # -- Audio waveform ---------------------------------------------------
        wy  = sy + 28
        N   = 36
        BH  = 16
        bw  = 7
        total = N * bw
        wx0 = (W - total) // 2
        for i in range(N):
            if self.muted:
                hb  = 2
                col = C_RED
            elif self.speaking:
                hb  = random.randint(3, BH)
                col = C_PRI if hb > BH * 0.6 else C_PRI_D
            else:
                hb  = max(2, int(2 + 3 * math.sin(t * 0.06 + i * 0.5)))
                col = C_PRI_D
            bx = wx0 + i * bw
            c.create_rectangle(bx, wy + BH - hb, bx + bw - 1, wy + BH,
                               fill=col, outline="")

        # -- HUD: Left stat panel ---------------------------------------------
        PX, PY, PW = 14, 60, 140
        c.create_rectangle(PX, PY, PX+PW, PY + self.H - 180,
                           fill="#030a12", outline=C_PRI_D, width=1)

        # Panel title
        c.create_text(PX + PW//2, PY + 14, text="SYSTEM STATUS",
                      fill=C_PRI, font=("Consolas", 8, "bold"))

        # Live data readouts
        stats = [
            ("CORE",      "ONLINE" if not self.muted else "OFFLINE",  C_GREEN if not self.muted else C_RED),
            ("VOICE",     "ACTIVE"  if self.speaking  else "STANDBY",  C_PRI    if self.speaking  else C_TEXT_D),
            ("MEMORY",    "ACTIVE",  C_GREEN),
            ("NETWORK",   "LIVE",    C_GREEN),
            ("CAMERA",    "READY",   C_TEXT_D),
            ("SCHEDULER", "IDLE",    C_TEXT_D),
            ("MONITOR",   "OFF" if not self._get_monitor_state() else "ACTIVE", C_TEXT_D if not self._get_monitor_state() else C_ACC),
        ]
        sy = PY + 38
        for key, val, col in stats:
            c.create_text(PX + 10, sy, text=key,
                          fill=C_TEXT_D, font=("Consolas", 7), anchor="w")
            c.create_text(PX + PW - 10, sy, text=val,
                          fill=col, font=("Consolas", 7, "bold"), anchor="e")
            sy += 20

        # Load bar
        sy += 6
        c.create_text(PX + 10, sy, text="LOAD", fill=C_TEXT_D,
                      font=("Consolas", 7), anchor="w")
        load = random.randint(18, 55) if not self.speaking else random.randint(40, 80)
        c.create_rectangle(PX+10, sy+4, PX+PW-10, sy+12, fill=C_BORDER, outline="")
        c.create_rectangle(PX+10, sy+4, PX+10+int((PW-20)*load/100), sy+12,
                           fill=C_PRI, outline="")

        # Uptime
        sy += 24
        c.create_text(PX + 10, sy, text="UPTIME", fill=C_TEXT_D,
                      font=("Consolas", 7), anchor="w")
        uptime_s = int(time.time() - getattr(self, "_start_time", time.time()))
        hh, ss = divmod(uptime_s, 3600)
        mm, ss = divmod(ss, 60)
        c.create_text(PX+PW-10, sy, text=f"{hh:02d}:{mm:02d}:{ss:02d}",
                      fill=C_PRI, font=("Consolas", 7, "bold"), anchor="e")

        # Data counter
        sy += 22
        c.create_text(PX + 10, sy, text="DATA IDX", fill=C_TEXT_D,
                      font=("Consolas", 7), anchor="w")
        c.create_text(PX+PW-10, sy, text=f"{self.data_count:04d}",
                      fill=C_PRI, font=("Consolas", 7), anchor="e")

        # Mute / cfg buttons
        BY = PY + self.H - 180 - 90
        c.create_rectangle(PX + 6, BY, PX + 68, BY + 24,
                           fill="#030d18", outline=C_PRI_D, width=1)
        txt = "[MIC OFF]" if self.muted else "[MIC ON]"
        col = C_RED if self.muted else C_PRI
        c.create_text(PX + 37, BY + 12, text=txt, tags="mute_btn",
                      fill=col, font=("Consolas", 8, "bold"), anchor="center")
        c.create_rectangle(PX + 72, BY, PX + PW - 6, BY + 24,
                           fill="#030d18", outline=C_BORDER, width=1)
        c.create_text(PX + PW - 38, BY + 12, text="[CFG]",
                      fill=C_TEXT_D, font=("Consolas", 8), anchor="center")

        # History button
        HY = BY + 30
        c.create_rectangle(PX + 6, HY, PX + PW - 6, HY + 20,
                           fill="#030d18", outline=C_BORDER, width=1)
        c.create_text(PX + PW // 2, HY + 10, text="HISTORY",
                      fill=C_TEXT_D, font=("Consolas", 7), anchor="center")

        # -- HUD: Right tools panel -------------------------------------------
        RX = W - PX - PW
        c.create_rectangle(RX, PY, RX+PW, PY + self.H - 180,
                           fill="#030a12", outline=C_PRI_D, width=1)
        c.create_text(RX + PW//2, PY + 14, text="AVAILABLE TOOLS",
                      fill=C_PRI, font=("Consolas", 8, "bold"))

        tools = [
            ("WEB SEARCH", C_TEXT),
            ("WEATHER",     C_TEXT),
            ("YOUTUBE",     C_TEXT),
            ("CALENDAR",    C_TEXT),
            ("EMAIL",       C_TEXT),
            ("GITHUB",      C_TEXT),
            ("FILES",       C_TEXT),
            ("CODE HELPER", C_TEXT),
            ("SETTINGS",    C_TEXT),
        ]
        ty = PY + 38
        for tool, col in tools:
            c.create_oval(RX + 12, ty - 4, RX + 16, ty,
                          fill=C_PRI_D, outline="")
            c.create_text(RX + 24, ty, text=tool,
                          fill=col, font=("Consolas", 7), anchor="w")
            ty += 19

        # Buttons in right panel
        BY = PY + self.H - 180 - 90
        c.create_rectangle(RX + 6, BY, RX + 68, BY + 24,
                           fill="#030d18", outline=C_PRI_D, width=1)
        c.create_text(RX + 37, BY + 12, text="[MIC]",
                      fill=C_PRI, font=("Consolas", 8, "bold"), anchor="center")
        c.create_rectangle(RX + 72, BY, RX + PW - 6, BY + 24,
                           fill="#030d18", outline=C_BORDER, width=1)
        c.create_text(RX + PW - 38, BY + 12, text="[CFG]",
                      fill=C_TEXT_D, font=("Consolas", 8), anchor="center")

        HY = BY + 30
        c.create_rectangle(RX + 6, HY, RX + PW - 6, HY + 20,
                           fill="#030d18", outline=C_BORDER, width=1)
        c.create_text(RX + PW // 2, HY + 10, text="HISTORY",
                      fill=C_TEXT_D, font=("Consolas", 7), anchor="center")

        # -- Top bar --------------------------------------------------------
        BAR_H = 48
        c.create_rectangle(0, 0, W, BAR_H, fill="#020810", outline="")
        c.create_line(0, BAR_H, W, BAR_H, fill=C_PRI_D, width=1)
        c.create_rectangle(14, 8, 14 + 90, 40, outline=C_PRI_D, fill="", width=1)
        c.create_text(59, 24, text=MODEL_BADGE,
                      fill=C_PRI_D, font=("Consolas", 10, "bold"))
        c.create_text(W // 2, 14, text=SYSTEM_NAME,
                      fill=C_PRI, font=("Consolas", 20, "bold"))
        c.create_text(W // 2, 34, text="JUST A RATHER VERY INTELLIGENT SYSTEM",
                      fill=C_TEXT_D, font=("Consolas", 8))
        with contextlib.suppress(Exception):
            c.delete(self._clock_id)
        self._clock_id = c.create_text(W - 20, 24,
                      text=time.strftime("%H:%M:%S"),
                      fill=C_PRI, font=("Consolas", 14, "bold"), anchor="e")

        # -- Bottom bar ----------------------------------------------------
        BY2 = H - 36
        c.create_rectangle(0, BY2, W, H, fill="#020810", outline="")
        c.create_line(0, BY2, W, BY2, fill=C_PRI_D, width=1)
        c.create_text(W // 2, BY2 + 18,
                      text="J.A.R.V.I.S  |  MARK XXXV  |  v3.5",
                      fill=C_TEXT_D, font=("Consolas", 7), anchor="center")

        # Status indicator
        stat_col = C_RED if self.muted else (C_ACC if self.speaking else C_GREEN)
        stat_txt = "MUTED" if self.muted else ("SPEAKING" if self.speaking else "READY")
        c.create_text(20, BY2 + 18, text=stat_txt,
                      fill=stat_col, font=("Consolas", 8, "bold"), anchor="w")
        c.create_text(W - 20, BY2 + 18, text="[F4] MUTE  |  TYPE TO COMMAND",
                      fill=C_TEXT_D, font=("Consolas", 7), anchor="e")

        # -- Bind tags to click handlers -------------------------------------
        c.tag_bind("mute_btn", "<Button-1>", lambda e: self._toggle_mute())
        c.tag_bind("set_btn",  "<Button-1>", lambda e: self._show_settings())
        c.tag_bind("hist_btn", "<Button-1>", lambda e: self._show_history())

    def _get_monitor_state(self) -> bool:
        try:
            from core.screen_monitor import get_screen_monitor
            return get_screen_monitor().is_enabled()
        except Exception:
            return False

    @staticmethod
    def _mcolor(r, g, b, a) -> str:
        f = max(0, min(255, a)) / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    # -- Mute -------------------------------------------------------------------

    def _toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self.set_state("MUTED")
            self.write_log("SYS: Microphone muted.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: Microphone active.")

    # -- State management --------------------------------------------------------

    def set_state(self, state: str):
        self._jarvis_state = state
        if state == "MUTED":
            self.status_text = "MUTED"
            self.speaking    = False
        elif state == "SPEAKING":
            self.status_text = "SPEAKING"
            self.speaking    = True
        elif state == "THINKING":
            self.status_text = "THINKING"
            self.speaking    = False
        elif state == "PROCESSING":
            self.status_text = "PROCESSING"
            self.speaking    = False
        else:
            self.status_text = "LISTENING"
            self.speaking    = False

    # -- Input -----------------------------------------------------------------

    def _on_input_submit(self, event=None):
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")
        self.write_log(f"You: {text}")
        if self.on_text_command:
            threading.Thread(
                target=self.on_text_command,
                args=(text,),
                daemon=True
            ).start()

    # -- Log --------------------------------------------------------------------

    def write_log(self, text: str):
        self.typing_queue.append(text)
        tl = text.lower()
        if tl.startswith("you:"):
            self.set_state("PROCESSING")
        elif tl.startswith(("jarvis:", "ai:")):
            self.set_state("SPEAKING")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        self.is_typing = True
        self._process_queue()

    def _process_queue(self):
        if not self.typing_queue:
            self.is_typing = False
            return
        # We read from the HUD log display - handled via canvas text
        self.typing_queue.popleft()
        self.root.after(30, self._process_queue)

    # -- API key setup ----------------------------------------------------------

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _api_keys_exist(self) -> bool:
        return _KEY_MANAGER_OK and _is_configured()

    def _show_setup_ui(self):
        frame = tk.Frame(self.root, bg="#020810",
                         highlightbackground=C_PRI_D, highlightthickness=2)
        frame.place(relx=0.5, rely=0.5, anchor="center", width=460, height=220)

        tk.Label(frame, text="INITIALIZATION REQUIRED",
                 fg=C_PRI, bg="#020810",
                 font=("Consolas", 14, "bold")).pack(pady=(22, 4))
        tk.Label(frame, text="Enter your Gemini API key to boot J.A.R.V.I.S",
                 fg=C_TEXT_D, bg="#020810",
                 font=("Consolas", 9)).pack(pady=(0, 14))

        tk.Label(frame, text="GEMINI API KEY",
                 fg=C_TEXT_D, bg="#020810",
                 font=("Consolas", 8)).pack(pady=(0, 4))
        entry = tk.Entry(frame, width=44, fg=C_TEXT, bg="#030d18",
                         insertbackground=C_PRI,
                         borderwidth=0, font=("Consolas", 10), show="*")
        entry.pack(pady=(0, 14))

        btn = tk.Button(frame, text="INITIALIZE",
                        command=lambda: self._save_api_keys_from(entry),
                        fg=C_PRI, bg="#030d18",
                        activebackground=C_PRI_D,
                        font=("Consolas", 11, "bold"),
                        borderwidth=1, relief="flat", cursor="hand2",
                        pady=8)
        btn.pack(pady=(0, 16))

    def _save_api_keys_from(self, entry):
        key = entry.get().strip()
        if not key:
            return
        if _KEY_MANAGER_OK:
            save_api_keys({"gemini_api_key": key})
        else:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(API_FILE, "w") as f:
                json.dump({"gemini_api_key": key}, f)
        self._api_key_ready = True
        # Remove setup overlay
        for w in self.root.winfo_children():
            if isinstance(w, tk.Frame):
                w.destroy()

    # -- Settings ---------------------------------------------------------------

    def _show_settings(self):
        # Prevent duplicate settings windows
        if "settings" in self._toplevels and self._toplevels["settings"].winfo_exists():
            self._toplevels["settings"].lift()
            self._toplevels["settings"].focus()
            return

        win = tk.Toplevel(self.root)
        self._toplevels["settings"] = win
        win.title("J.A.R.V.I.S -- Configuration")
        win.configure(bg="#020810")
        ww, wh = 500, 400
        win.geometry(f"{ww}x{wh}+{(self.W-ww)//2}+{(self.H-wh)//2}")
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="[ J.A.R.V.I.S CONFIGURATION ]",
                 fg=C_PRI, bg="#020810", font=("Consolas", 13, "bold")
                 ).pack(pady=(18, 4))
        tk.Label(win, text="Configure system behaviour",
                 fg=C_TEXT_D, bg="#020810", font=("Consolas", 9)
                 ).pack(pady=(0, 14))

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        for tab_bg, label, content_fn in [
            ("#030a12", "General",  self._build_general_tab),
            ("#030a12", "Voice",     self._build_voice_tab),
            ("#030a12", "Monitor",   self._build_monitor_tab),
        ]:
            tab = tk.Frame(nb, bg=tab_bg)
            nb.add(tab, text=f"  {label}  ")
            content_fn(tab)

        tk.Button(win, text="CLOSE", command=win.destroy,
                  fg=C_PRI, bg="#030d18", activebackground=C_PRI_D,
                  font=("Consolas", 10, "bold"), borderwidth=1,
                  relief="flat", cursor="hand2", pady=5
                  ).pack(pady=(0, 12))

        # Clean up toplevel reference when window is closed
        def on_settings_close():
            self._toplevels.pop("settings", None)
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_settings_close)

    def _build_general_tab(self, parent):
        tk.Label(parent, text="Task Settings",
                 fg=C_PRI, bg="#030a12", font=("Consolas", 9, "bold")
                 ).pack(anchor="w", padx=14, pady=(12, 4))

        row = tk.Frame(parent, bg="#030a12")
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="Max concurrent tasks:",
                 fg=C_TEXT, bg="#030a12", font=("Consolas", 8)
                 ).pack(side="left")
        self._set_max_concurrent = tk.IntVar(value=3)
        tk.Spinbox(row, from_=1, to=5, width=4,
                   textvariable=self._set_max_concurrent,
                   fg=C_TEXT, bg="#030d18", font=("Consolas", 8),
                   buttonbackground=C_BORDER, highlightthickness=0
                   ).pack(side="right")

        row2 = tk.Frame(parent, bg="#030a12")
        row2.pack(fill="x", padx=14, pady=4)
        tk.Label(row2, text="Planner max steps:",
                 fg=C_TEXT, bg="#030a12", font=("Consolas", 8)
                 ).pack(side="left")
        self._set_max_steps = tk.IntVar(value=12)
        tk.Spinbox(row2, from_=5, to=20, width=4,
                   textvariable=self._set_max_steps,
                   fg=C_TEXT, bg="#030d18", font=("Consolas", 8),
                   buttonbackground=C_BORDER, highlightthickness=0
                   ).pack(side="right")

        # Auto permission accept
        tk.Label(parent, text="Permissions",
                 fg=C_PRI, bg="#030a12", font=("Consolas", 9, "bold")
                 ).pack(anchor="w", padx=14, pady=(14, 4))
        self._set_auto_permission = tk.BooleanVar(value=True)
        cb = tk.Checkbutton(parent, text="Auto-accept all tool executions (no confirmation popups)",
                           variable=self._set_auto_permission,
                           fg=C_TEXT, bg="#030a12", activeforeground=C_PRI,
                           activebackground="#030a12", selectcolor="#030d18",
                           anchor="w", justify="left",
                           font=("Consolas", 8))
        cb.pack(anchor="w", padx=14, pady=(0, 4))
        tk.Label(parent,
                 text="When ON, tools execute immediately. When OFF, each tool asks for confirmation.",
                 fg=C_TEXT_D, bg="#030a12", font=("Consolas", 7)
                 ).pack(anchor="w", padx=14, pady=(0, 8))

        tk.Button(parent, text="Apply General Settings",
                  command=self._apply_general_settings,
                  fg=C_PRI, bg="#030d18", activebackground=C_PRI_D,
                  font=("Consolas", 8, "bold"), borderwidth=1,
                  relief="flat", cursor="hand2", pady=4
                  ).pack(pady=(4, 4))

        tk.Label(parent, text="API Key",
                 fg=C_PRI, bg="#030a12", font=("Consolas", 9, "bold")
                 ).pack(anchor="w", padx=14, pady=(10, 4))
        tk.Label(parent,
                 text="API key is stored encrypted. Change via setup screen.",
                 fg=C_TEXT_D, bg="#030a12", font=("Consolas", 7)
                 ).pack(anchor="w", padx=14, pady=(0, 6))
        tk.Button(parent, text="Open Setup Screen",
                  command=lambda: (self.root.withdraw(), self._show_setup_ui()),
                  fg=C_ACC2, bg="#030d18", activebackground=C_BORDER,
                  font=("Consolas", 8), borderwidth=1, relief="flat", cursor="hand2"
                  ).pack(anchor="w", padx=14)

    def _build_voice_tab(self, parent):
        tk.Label(parent, text="Voice",
                 fg=C_PRI, bg="#030a12", font=("Consolas", 9, "bold")
                 ).pack(anchor="w", padx=14, pady=(12, 4))

        row = tk.Frame(parent, bg="#030a12")
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="Voice name:",
                 fg=C_TEXT, bg="#030a12", font=("Consolas", 8)
                 ).pack(side="left")

        voices = ["Charon", "Fenrir", "Kora", "Puck", "Leda", "Aoede", "Zephyr"]
        self._set_voice_name = tk.StringVar(value="Charon")
        try:
            cfg = BASE_DIR / "config" / "settings.json"
            if cfg.exists():
                self._set_voice_name.set(
                    json.loads(cfg.read_text(encoding="utf-8")).get("voice_name", "Charon")
                )
        except Exception:
            pass
        ttk.Combobox(row, textvariable=self._set_voice_name,
                     values=voices, state="readonly", width=12,
                     font=("Consolas", 8)).pack(side="right")

        row2 = tk.Frame(parent, bg="#030a12")
        row2.pack(fill="x", padx=14, pady=4)
        tk.Label(row2, text="Speed:",
                 fg=C_TEXT, bg="#030a12", font=("Consolas", 8)
                 ).pack(side="left")
        self._set_voice_speed = tk.DoubleVar(value=1.0)
        try:
            cfg = BASE_DIR / "config" / "settings.json"
            if cfg.exists():
                self._set_voice_speed.set(
                    float(json.loads(cfg.read_text(encoding="utf-8")).get("voice_speed", 1.0))
                )
        except Exception:
            pass
        tk.Scale(row2, from_=0.8, to=1.2, resolution=0.1,
                  variable=self._set_voice_speed,
                  fg=C_PRI, bg="#030a12", troughcolor=C_BORDER,
                  highlightthickness=0, length=130,
                  ).pack(side="right")

        tk.Button(parent, text="Apply Voice Settings",
                  command=self._apply_voice_settings,
                  fg=C_PRI, bg="#030d18", activebackground=C_PRI_D,
                  font=("Consolas", 8, "bold"), borderwidth=1,
                  relief="flat", cursor="hand2", pady=4
                  ).pack(pady=(10, 4))

        tk.Label(parent, text="Restart session to hear the new voice.",
                 fg=C_TEXT_D, bg="#030a12", font=("Consolas", 7)
                 ).pack()

    def _apply_general_settings(self):
        cfg = BASE_DIR / "config" / "settings.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if cfg.exists():
            with contextlib.suppress(Exception):
                data = json.loads(cfg.read_text(encoding="utf-8"))
        data["auto_permission"]     = bool(self._set_auto_permission.get())
        data["max_concurrent"]       = int(self._set_max_concurrent.get())
        data["max_steps"]            = int(self._set_max_steps.get())
        cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.write_log("SYS: General settings applied.")
        self._auto_permission = bool(self._set_auto_permission.get())

    def _apply_voice_settings(self):
        cfg = BASE_DIR / "config" / "settings.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if cfg.exists():
            with contextlib.suppress(Exception):
                data = json.loads(cfg.read_text(encoding="utf-8"))
        data["voice_name"]  = self._set_voice_name.get()
        data["voice_speed"] = float(self._set_voice_speed.get())
        cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.write_log("SYS: Voice settings saved. Restart session to apply.")

    def _build_monitor_tab(self, parent):
        tk.Label(parent, text="Screen Monitor",
                 fg=C_PRI, bg="#030a12", font=("Consolas", 9, "bold")
                 ).pack(anchor="w", padx=14, pady=(12, 4))
        tk.Label(parent,
                 text="Periodically checks screen for actionable content.",
                 fg=C_TEXT_D, bg="#030a12", font=("Consolas", 7)
                 ).pack(anchor="w", padx=14)

        self._set_monitor_enabled = tk.BooleanVar(value=False)
        try:
            from core.screen_monitor import get_screen_monitor
            self._set_monitor_enabled.set(get_screen_monitor().is_enabled())
        except Exception:
            pass
        tk.Checkbutton(parent, text="Enable screen monitoring",
                       variable=self._set_monitor_enabled,
                       fg=C_TEXT, bg="#030a12", selectcolor=C_BORDER,
                       activebackground="#030a12", activeforeground=C_TEXT,
                       font=("Consolas", 8)
                       ).pack(anchor="w", padx=14, pady=(10, 4))

        row = tk.Frame(parent, bg="#030a12")
        row.pack(fill="x", padx=14, pady=4)
        tk.Label(row, text="Check interval (seconds):",
                 fg=C_TEXT, bg="#030a12", font=("Consolas", 8)
                 ).pack(side="left")
        self._set_monitor_interval = tk.IntVar(value=60)
        tk.Spinbox(row, from_=15, to=3600, width=6,
                   textvariable=self._set_monitor_interval,
                   fg=C_TEXT, bg="#030d18", font=("Consolas", 8),
                   buttonbackground=C_BORDER, highlightthickness=0
                   ).pack(side="right")

        tk.Button(parent, text="Apply Monitor Settings",
                  command=self._apply_monitor_settings,
                  fg=C_PRI, bg="#030d18", activebackground=C_PRI_D,
                  font=("Consolas", 8, "bold"), borderwidth=1,
                  relief="flat", cursor="hand2", pady=4
                  ).pack(pady=(10, 4))

        tk.Label(parent, text="Active Schedules",
                 fg=C_PRI, bg="#030a12", font=("Consolas", 9, "bold")
                 ).pack(anchor="w", padx=14, pady=(14, 4))
        try:
            from core.scheduler import get_scheduler
            scheds = get_scheduler().list_schedules()
            if scheds:
                for s in scheds[:6]:
                    tk.Label(parent,
                             text=f"  {s['goal'][:50]} -- {s['schedule']}",
                             fg=C_TEXT, bg="#030a12", font=("Consolas", 7)
                             ).pack(anchor="w", padx=14)
            else:
                tk.Label(parent, text="  No active schedules.",
                         fg=C_TEXT_D, bg="#030a12", font=("Consolas", 7)
                         ).pack(anchor="w", padx=14)
        except Exception:
            tk.Label(parent, text="  Scheduler unavailable.",
                     fg=C_TEXT_D, bg="#030a12", font=("Consolas", 7)
                     ).pack(anchor="w", padx=14)

    def _apply_monitor_settings(self):
        try:
            from core.screen_monitor import get_screen_monitor
            mon = get_screen_monitor()
            if self._set_monitor_enabled.get():
                mon.set_interval(self._set_monitor_interval.get())
                mon.enable()
            else:
                mon.disable()
            self.write_log("SYS: Monitor settings applied.")
        except Exception as e:
            self.write_log(f"SYS: Monitor error -- {e}")

    # -- History ----------------------------------------------------------------

    def _show_history(self):
        # Prevent duplicate history windows
        if "history" in self._toplevels and self._toplevels["history"].winfo_exists():
            self._toplevels["history"].lift()
            self._toplevels["history"].focus()
            return

        win = tk.Toplevel(self.root)
        self._toplevels["history"] = win
        win.title("J.A.R.V.I.S -- Conversation History")
        win.configure(bg="#020810")
        ww, wh = 600, 500
        win.geometry(f"{ww}x{wh}+{(self.W-ww)//2}+{(self.H-wh)//2}")
        win.grab_set()

        hdr = tk.Frame(win, bg="#020810")
        hdr.place(x=0, y=0, relwidth=1.0, height=40)
        tk.Label(hdr, text="[ CONVERSATION HISTORY ]",
                 fg=C_PRI, bg="#020810", font=("Consolas", 11, "bold")
                 ).pack(side="left", padx=14, pady=6)
        tk.Button(hdr, text="Refresh",
                  command=lambda: self._refresh_history(self._hist_listbox, left),
                  fg=C_TEXT_D, bg="#030d18", activebackground=C_BORDER,
                  font=("Consolas", 7), borderwidth=1, relief="flat", cursor="hand2"
                  ).pack(side="right", padx=14, pady=6)

        left = tk.Frame(win, bg="#030a12")
        scroll_y = tk.Scrollbar(left)
        scroll_y.pack(side="right", fill="y")
        self._hist_listbox = tk.Listbox(
            left, fg=C_TEXT, bg="#030a12",
            selectbackground=C_BORDER, selectforeground=C_PRI,
            borderwidth=0, font=("Consolas", 8),
            yscrollcommand=scroll_y.set
        )
        self._hist_listbox.pack(side="left", fill="both", expand=True)
        scroll_y.config(command=self._hist_listbox.yview)
        self._hist_listbox.bind("<<ListboxSelect>>",
                                 lambda e: self._show_session_detail())

        right = tk.Frame(win, bg="#030a12")
        self._hist_detail = tk.Text(
            right, fg=C_TEXT, bg="#030a12",
            insertbackground=C_PRI, borderwidth=0,
            wrap="word", font=("Consolas", 8),
            state="disabled"
        )
        self._hist_detail.pack(fill="both", expand=True, padx=8, pady=8)

        split = tk.PanedWindow(win, bg="#020810", sashrelief="flat",
                                sashwidth=2)
        split.place(x=0, y=40, relwidth=1.0, relheight=1.0)
        split.add(left, width=200)
        split.add(right, width=380)

        self._hist_sessions = []
        self._refresh_history(self._hist_listbox, left)

        # Clean up toplevel reference when window is closed
        def on_history_close():
            self._toplevels.pop("history", None)
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_history_close)

    def _refresh_history(self, listbox, left_frame=None):
        import os
        try:
            conv_dir = BASE_DIR / "memory" / "conversations"
            files = sorted(conv_dir.glob("session_*.json"), key=os.path.getmtime, reverse=True)
        except Exception:
            files = []
        self._hist_sessions = files[:30]
        listbox.delete(0, tk.END)
        for f in self._hist_sessions:
            ts = f.stem.replace("session_", "").replace("_", " ")
            listbox.insert(tk.END, ts)
        if self._hist_sessions:
            listbox.select_set(0)
            listbox.event_generate("<<ListboxSelect>>")

    def _show_session_detail(self):
        sel = self._hist_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._hist_sessions):
            return
        f = self._hist_sessions[idx]
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            summary = data.get("summary", "(no summary)")
            turns = data.get("turns", [])
            lines = [f"[SUMMARY]\n{summary}\n\n[CONVERSATION -- {len(turns)} turns]\n"]
            for t in turns:
                role   = t.get("role", "?")
                content = t.get("content", "")
                tool    = t.get("tool", "")
                if role == "user":
                    lines.append(f"USER: {content[:300]}")
                elif role == "jarvis":
                    lines.append(f"JARVIS: {content[:300]}")
                elif role == "tool":
                    lines.append(f"[{tool}]: {content[:200]}")
                lines.append("")
            text = "\n".join(lines)
        except Exception as e:
            text = f"Could not load session: {e}"

        self._hist_detail.config(state="normal")
        self._hist_detail.delete("1.0", tk.END)
        self._hist_detail.insert("1.0", text)
        self._hist_detail.config(state="disabled")
