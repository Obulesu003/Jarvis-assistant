"""
fix_shortcut.py - Ensure JARVIS desktop icon is visible with JARVIS branding.
Creates a proper .lnk with the JARVIS icon embedded.
"""
import logging  # migrated from print()
import os
import sys
import struct
import math
from pathlib import Path
from PIL import Image, ImageDraw
import win32com.client
import pythoncom

def create_jarvis_image(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2

    # HUD-style rings
    draw.ellipse([cx - int(size*0.44), cy - int(size*0.44), cx + int(size*0.44), cy + int(size*0.44)], fill=(0, 50, 120))
    draw.ellipse([cx - int(size*0.36), cy - int(size*0.36), cx + int(size*0.36), cy + int(size*0.36)], outline=(0, 170, 255), width=3)
    draw.ellipse([cx - int(size*0.12), cy - int(size*0.12), cx + int(size*0.12), cy + int(size*0.12)], fill=(0, 170, 255))
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1 = cx + int(size * 0.28 * math.cos(rad))
        y1 = cy + int(size * 0.28 * math.sin(rad))
        x2 = cx + int(size * 0.42 * math.cos(rad))
        y2 = cy + int(size * 0.42 * math.sin(rad))
        draw.line([x1, y1, x2, y2], fill=(255, 200, 0), width=2)

    return img


def save_ico(images, path):
    with open(path, 'wb') as f:
        f.write(struct.pack('<HHI', 0, 1, len(images)))
        image_data_list = []
        for img in images:
            img = img.convert("RGBA")
            w, h = img.size
            row_bytes = w * 4
            pixel_data = bytearray()
            for y in range(h - 1, -1, -1):
                row = bytearray()
                for x in range(w):
                    r, g, b, a = img.getpixel((x, y))
                    row.extend([b, g, r, a])
                while len(row) < row_bytes:
                    row.append(0)
                pixel_data.extend(row)
            and_row = ((w + 31) // 32) * 4
            and_mask = bytes(and_row * h)
            header = struct.pack('<IIIHHIIIIII', 40, w, h*2, 1, 32, 0,
                                len(pixel_data)+len(and_mask), 0, 0, 0, 0)
            image_data_list.append((header, pixel_data, and_mask))
        data_offset = 6 + 16 * len(images)
        for (header, pixel_data, and_mask), img in zip(image_data_list, images):
            entry = struct.pack('<IIBBHII', img.width, img.height, 0, 0, 1, 32,
                               len(header)+len(pixel_data)+len(and_mask))
            f.write(entry)
            f.write(struct.pack('<I', data_offset))
            data_offset += len(header)+len(pixel_data)+len(and_mask)
        for header, pixel_data, and_mask in image_data_list:
            f.write(header)
            f.write(pixel_data)
            f.write(and_mask)
    return True


def fix_jarvis_desktop():
    desktop = Path(os.path.expanduser("~/Desktop"))
    jarvis_dir = Path(__file__).resolve().parent

    # Create JARVIS icon
    icon_path = desktop / "jarvis.ico"
    sizes = [64, 48, 32, 16]
    images = [create_jarvis_image(s) for s in sizes]
    save_ico(images, str(icon_path))
    logging.getLogger("OK").info('Created JARVIS icon: {icon_path.name} ({icon_path.stat().st_size} bytes)')

    # Create proper Windows shortcut using Shell
    pythoncom.CoInitialize()
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut_path = str(desktop / "JARVIS - MARK XXXV.lnk")
        sc = shell.CreateShortCut(shortcut_path)
        sc.TargetPath = str(Path(sys.executable))
        sc.Arguments = f'"{jarvis_dir / "main.py"}"'
        sc.WorkingDirectory = str(jarvis_dir)
        sc.IconLocation = str(icon_path)
        sc.Description = "JARVIS - MARK XXXV AI Assistant"
        sc.save()
        logging.getLogger("OK").info('Created desktop shortcut with JARVIS icon')
    except Exception as e:
        logging.getLogger("WARN").info(f'Shortcut: {e}')
    finally:
        pythoncom.CoUninitialize()

    logging.getLogger(__name__).info('\\nDesktop files now available:')
    for f in sorted(desktop.iterdir()):
        if "jarvis" in f.name.lower() or "mark" in f.name.lower():
            logging.getLogger(__name__).info(f"{f.name} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    fix_jarvis_desktop()