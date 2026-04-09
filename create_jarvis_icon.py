"""
create_jarvis_icon.py - Create a JARVIS icon and desktop shortcut
Generates a JARVIS-themed .ico file and places it on the Desktop.
"""
import logging  # migrated from print()
import os
import sys
import struct
import math
from pathlib import Path
from PIL import Image, ImageDraw


def create_jarvis_image(size=64):
    """Create a JARVIS icon image (PIL RGBA)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    blue = (0, 170, 255)
    dark_blue = (0, 50, 120)
    white = (255, 255, 255)
    gold = (255, 200, 0)

    cx = cy = size // 2

    # Outer ring
    r = int(size * 0.44)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dark_blue)

    # Inner ring
    r2 = int(size * 0.36)
    draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=blue, width=max(2, size // 20))

    # Center dot
    r3 = int(size * 0.12)
    draw.ellipse([cx - r3, cy - r3, cx + r3, cy + r3], fill=blue)

    # Arc segments (HUD style)
    for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
        rad = math.radians(angle)
        x1 = cx + int(size * 0.28 * math.cos(rad))
        y1 = cy + int(size * 0.28 * math.sin(rad))
        x2 = cx + int(size * 0.42 * math.cos(rad))
        y2 = cy + int(size * 0.42 * math.sin(rad))
        draw.line([x1, y1, x2, y2], fill=gold, width=max(1, size // 32))

    # "J" letter
    font_size = max(16, size // 3)
    try:
        draw.text((cx - font_size // 3, cy - font_size // 2), "J", fill=white)
    except Exception:
        pass  # Some environments don't support text

    return img


def save_ico(images, path):
    """Save PIL RGBA images as a proper .ico file."""
    if not images:
        return False

    with open(path, 'wb') as f:
        # ICO header
        f.write(struct.pack('<HHI', 0, 1, len(images)))

        # Build image data first so we can compute offsets
        image_data_list = []
        for img in images:
            img = img.convert("RGBA")
            w, h = img.size
            row_bytes = w * 4
            pixel_data = bytearray()
            # BMP rows are bottom-up
            for y in range(h - 1, -1, -1):
                row = bytearray()
                for x in range(w):
                    r, g, b, a = img.getpixel((x, y))
                    row.extend([b, g, r, a])
                # Pad row to 4 bytes
                while len(row) < row_bytes:
                    row.append(0)
                pixel_data.extend(row)

            # AND mask (all 0 = fully opaque)
            and_row_bytes = (w + 31) // 32 * 4
            and_mask = bytes(and_row_bytes * h)

            # BITMAPINFOHEADER (40 bytes)
            header = struct.pack('<IIIHHIIIIII',
                40,       # header size
                w,        # width
                h * 2,    # height (doubled for XOR + AND mask)
                1,        # planes
                32,       # bits per pixel
                0,        # compression (BI_RGB)
                len(pixel_data) + len(and_mask),  # image size
                0, 0, 0, 0  # resolution, colors
            )

            image_data_list.append((header, pixel_data, and_mask))

        # Write directory entries
        data_offset = 6 + 16 * len(images)
        for (header, pixel_data, and_mask), img in zip(image_data_list, images):
            w = img.width
            h = img.height
            entry = struct.pack('<IIBBHII',
                w, h, 0, 0, 1, 32,
                len(header) + len(pixel_data) + len(and_mask)
            )
            f.write(entry)
            f.write(struct.pack('<I', data_offset))
            data_offset += len(header) + len(pixel_data) + len(and_mask)

        # Write image data
        for header, pixel_data, and_mask in image_data_list:
            f.write(header)
            f.write(pixel_data)
            f.write(and_mask)

    return True


def create_shortcut():
    """Create desktop shortcut with JARVIS icon."""
    desktop = Path(os.path.expanduser("~/Desktop"))
    icon_path = desktop / "jarvis.ico"
    shortcut_path = desktop / "JARVIS - MARK XXXV.lnk"
    script_path = Path(__file__).resolve().parent / "main.py"

    # Create icon at multiple sizes
    sizes = [64, 48, 32, 16]
    images = [create_jarvis_image(s) for s in sizes]
    save_ico(images, str(icon_path))
    logging.getLogger("OK").info(f'Icon: {icon_path}')

    # Create shortcut
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(str(shortcut_path))
        sc.TargetPath = str(Path(sys.executable))
        sc.Arguments = f'"{script_path}"'
        sc.WorkingDirectory = str(script_path.parent)
        sc.IconLocation = str(icon_path)
        sc.save()
        logging.getLogger("OK").info(f'Shortcut: {shortcut_path.name}')
    except Exception as e:
        logging.getLogger("WARN").info(f"Shortcut failed: {e} — using batch file")
        bat_path = desktop / "JARVIS - MARK XXXV.bat"
        with open(bat_path, "w") as f:
            f.write(f'@echo off\nstart "" "{script_path}"\n')
        logging.getLogger("OK").info(f'Batch file: {bat_path.name}')


if __name__ == "__main__":
    create_shortcut()