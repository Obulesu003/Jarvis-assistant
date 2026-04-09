"""
branding.py - JARVIS Cinematic Branding System
Generates the monogram logo, brand assets, and visual identity for JARVIS v2.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pathlib import Path
import tempfile
import math
import logging
import os

logger = logging.getLogger(__name__)

# ── Brand Colors ──────────────────────────────────────────────────────────────
BRAND_BG       = "#0F172A"   # Deep slate - premium dark
BRAND_CYAN     = "#22D3EE"   # Electric cyan - signature accent
BRAND_CYAN_DIM = "#0E7490"   # Dimmed cyan
BRAND_WHITE    = "#F0F9FF"   # Near-white
BRAND_GLOW     = "#67E8F9"   # Glow cyan
BRAND_GOLD     = "#FBBF24"   # Gold accent for special moments

# ── Monogram Generator ────────────────────────────────────────────────────────

def _get_temp_dir() -> Path:
    return Path(tempfile.gettempdir())


def _draw_j_monogram(size: int, style: str = "default") -> Image.Image:
    """
    Draw a stylized "J" monogram.

    style options:
      - "default"   : Clean modern J with glow
      - "bold"      : Thick, commanding J
      - "minimal"   : Thin, elegant J
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    r_outer = size * 0.42

    if style == "bold":
        # Thick bold J
        stem_w = size * 0.18
        stem_x = cx + size * 0.08
        # Vertical stem
        draw.rectangle(
            [stem_x - stem_w/2, cy - size * 0.25,
             stem_x + stem_w/2, cy + size * 0.25],
            fill=BRAND_CYAN
        )
        # Bottom curve (thick arc)
        draw.ellipse(
            [stem_x - stem_w/2, cy + size * 0.08,
             stem_x + stem_w/2 + size * 0.20, cy + size * 0.45],
            fill=BRAND_CYAN
        )
        # Top bar
        draw.rectangle(
            [cx - size * 0.30, cy - size * 0.30,
             stem_x + stem_w/2, cy - size * 0.20],
            fill=BRAND_CYAN
        )

    elif style == "minimal":
        # Thin elegant J
        stem_w = size * 0.08
        stem_x = cx + size * 0.10
        draw.rectangle(
            [stem_x - stem_w/2, cy - size * 0.32,
             stem_x + stem_w/2, cy + size * 0.22],
            fill=BRAND_CYAN
        )
        # Arc at bottom
        draw.arc(
            [stem_x - size * 0.15, cy + size * 0.10,
             stem_x + size * 0.25, cy + size * 0.38],
            start=0, end=180,
            fill=BRAND_CYAN, width=max(2, size // 60)
        )

    else:
        # Default: Modern J with clean strokes
        stem_w = size * 0.13
        stem_x = cx + size * 0.06

        # Top horizontal bar
        bar_top = cy - size * 0.30
        bar_bottom = cy - size * 0.18
        draw.rectangle(
            [cx - size * 0.28, bar_top, stem_x + stem_w/2, bar_bottom],
            fill=BRAND_CYAN
        )

        # Vertical stem
        draw.rectangle(
            [stem_x - stem_w/2, cy - size * 0.22,
             stem_x + stem_w/2, cy + size * 0.18],
            fill=BRAND_CYAN
        )

        # Bottom hook - clean arc
        hook_left = stem_x - size * 0.14
        hook_right = stem_x + size * 0.22
        hook_top = cy + size * 0.10
        hook_bottom = cy + size * 0.38
        draw.ellipse(
            [hook_left, hook_top, hook_right, hook_bottom],
            fill=BRAND_CYAN
        )
        # Cut off the top of the hook
        draw.rectangle(
            [hook_left, hook_top, hook_right, cy + size * 0.16],
            fill=(15, 23, 42, 255)
        )

    return img


def _glow_image(img: Image.Image, glow_color: str = BRAND_CYAN,
                blur_radius: int = 20, opacity: float = 0.6) -> Image.Image:
    """Add a soft glow effect around the monogram."""
    # Parse color
    r = int(glow_color[1:3], 16)
    g = int(glow_color[3:5], 16)
    b = int(glow_color[5:7], 16)

    # Create glow layer
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)

    # Find bounding box of non-transparent pixels
    bbox = img.getbbox()
    if bbox:
        # Expand bbox for glow spread
        pad = blur_radius * 2
        x1, y1, x2, y2 = bbox
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(img.width, x2 + pad)
        y2 = min(img.height, y2 + pad)

        # Draw glowing background
        glow_draw.ellipse(
            [x1, y1, x2, y2],
            fill=(r, g, b, int(255 * opacity))
        )

    # Blur the glow
    glow = glow.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    # Composite
    result = Image.alpha_composite(glow, img)
    return result


def _add_radial_rays(img: Image.Image, ray_color: str = BRAND_CYAN,
                      num_rays: int = 8, ray_length: float = 0.15,
                      ray_alpha: float = 0.15) -> Image.Image:
    """Add subtle radial light rays behind the monogram."""
    w, h = img.size
    cx, cy = w // 2, h // 2
    r_outer = max(w, h) // 2
    r_inner = int(r_outer * (1 - ray_length))

    result = img.copy()
    ray_draw = ImageDraw.Draw(result)

    r = int(ray_color[1:3], 16)
    g = int(ray_color[3:5], 16)
    b = int(ray_color[5:7], 16)

    for i in range(num_rays):
        angle = (2 * math.pi * i / num_rays) - math.pi / 2
        x1 = cx + int(r_inner * math.cos(angle))
        y1 = cy + int(r_inner * math.sin(angle))
        x2 = cx + int(r_outer * math.cos(angle))
        y2 = cy + int(r_outer * math.sin(angle))
        ray_draw.line(
            [(x1, y1), (x2, y2)],
            fill=(r, g, b, int(255 * ray_alpha)),
            width=max(1, w // 120)
        )

    return result


def _add_orbital_ring(img: Image.Image, ring_color: str = BRAND_CYAN,
                       ring_radius: float = 0.48, ring_width: float = 0.015,
                       ring_alpha: float = 0.4) -> Image.Image:
    """Add an orbital ring behind the monogram."""
    w, h = img.size
    cx, cy = w // 2, h // 2
    r = int(w * ring_radius)
    rw = max(1, int(w * ring_width))

    result = img.copy()
    draw = ImageDraw.Draw(result)

    pr = int(ring_color[1:3], 16)
    pg = int(ring_color[3:5], 16)
    pb = int(ring_color[5:7], 16)

    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        outline=(pr, pg, pb, int(255 * ring_alpha)),
        width=rw
    )

    return result


# ── High-Level Logo Generators ───────────────────────────────────────────────

def generate_icon(size: int = 256, style: str = "default") -> Image.Image:
    """
    Generate the complete JARVIS monogram icon.
    Returns a PIL Image with the stylized "J" and glow effects.
    """
    # Base monogram
    img = _draw_j_monogram(size, style)

    # Add glow
    img = _glow_image(img, glow_color=BRAND_CYAN, blur_radius=size//12, opacity=0.5)

    # Add subtle orbital ring
    img = _add_orbital_ring(img, ring_color=BRAND_CYAN, ring_alpha=0.25)

    # Add radial rays
    img = _add_radial_rays(img, ray_color=BRAND_CYAN, num_rays=12, ray_alpha=0.08)

    return img


def generate_full_logo(height: int = 120, include_text: bool = True) -> Image.Image:
    """
    Generate the full JARVIS logo with the monogram and text.
    """
    icon_size = int(height * 0.9)
    monogram = generate_icon(icon_size)

    if not include_text:
        return monogram

    # Create full logo: monogram + text
    # Text dimensions
    try:
        font_large = ImageFont.truetype("arial.ttf", int(height * 0.5))
        font_small = ImageFont.truetype("arial.ttf", int(height * 0.16))
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Measure text
    jbbox = ImageDraw.Draw(monogram).textbbox((0, 0), "J", font=font_large)
    jw = jbbox[2] - jbbox[0]

    text = "JARVIS"
    tbbox = ImageDraw.Draw(monogram).textbbox((0, 0), text, font=font_large)
    tw = tbbox[2] - tbbox[0]
    th = tbbox[3] - tbbox[1]

    # Total width
    gap = int(height * 0.15)
    total_w = icon_size + gap + tw + gap
    total_h = max(icon_size, th)

    # Create canvas
    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(canvas)

    # Draw monogram on left
    my = (total_h - icon_size) // 2
    canvas.paste(monogram, (0, my), monogram)

    # Draw "JARVIS" text
    tx = icon_size + gap
    ty = (total_h - th) // 2 + (th - font_large.size) // 4

    # Text glow
    glow_img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_img)
    gd.text((tx, ty), text, font=font_large, fill=(34, 211, 238, 80))
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius=6))
    canvas = Image.alpha_composite(glow_img, canvas)

    cd.text((tx, ty), text, font=font_large, fill=BRAND_CYAN)

    return canvas


def save_logo(path: Path | str, size: int = 512, style: str = "default") -> Path:
    """Generate and save the JARVIS monogram to a PNG file."""
    img = generate_icon(size, style)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), "PNG")
    logger.info(f"[Branding] Logo saved: {path}")
    return path


def get_logo_path() -> Path:
    """Get or generate the JARVIS logo PNG."""
    logo_path = _get_temp_dir() / "jarvis_logo.png"
    if not logo_path.exists():
        save_logo(logo_path, size=512, style="default")
    return logo_path


def generate_tray_icon(size: int = 64) -> Image.Image:
    """Generate a smaller tray-friendly icon."""
    img = generate_icon(size, style="bold")
    # Enhance contrast for small sizes
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.2)
    return img


# ── Brand Color Palette ──────────────────────────────────────────────────────

def get_brand_colors() -> dict:
    """Return the brand color palette as CSS hex values."""
    return {
        "bg":         BRAND_BG,
        "cyan":       BRAND_CYAN,
        "cyan_dim":   BRAND_CYAN_DIM,
        "white":      BRAND_WHITE,
        "glow":       BRAND_GLOW,
        "gold":       BRAND_GOLD,
        # UI convenience
        "panel":      "#111827",
        "panel_dim":  "#1F2937",
        "border":     "#374151",
        "text":       "#E0F2FE",
        "text_dim":   "#7DD3FC",
        "green":      "#34D399",
        "red":        "#F87171",
        "amber":      "#FCD34D",
    }


# ── Pre-generate assets ───────────────────────────────────────────────────────

_assets_ready = False


def preload_assets() -> None:
    """Pre-generate all brand assets in background."""
    global _assets_ready
    if _assets_ready:
        return

    import threading

    def _gen():
        try:
            get_logo_path()
            logger.info("[Branding] Assets preloaded")
        except Exception as e:
            logger.warning(f"[Branding] Preload failed: {e}")
        finally:
            global _assets_ready
            _assets_ready = True

    t = threading.Thread(target=_gen, daemon=True, name="BrandingPreload")
    t.start()
