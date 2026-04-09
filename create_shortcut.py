"""
create_shortcut.py - Create desktop shortcut for MARK-XXXV JARVIS
Creates a desktop icon that launches JARVIS with a single click.
"""
import logging  # migrated from print()
import os
import sys
from pathlib import Path

def create_desktop_shortcut():
    """Create a desktop shortcut for JARVIS."""
    desktop = Path(os.path.expanduser("~/Desktop"))
    shortcut_path = desktop / "JARVIS - MARK XXXV.lnk"

    # Find Python and main script
    python_exe = Path(sys.executable)
    script_path = Path(__file__).resolve().parent / "main.py"

    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.TargetPath = str(python_exe)
        shortcut.Arguments = f'"{script_path}"'
        shortcut.WorkingDirectory = str(script_path.parent)
        # Use the Python icon
        shortcut.IconLocation = f"{python_exe},0"
        shortcut.save()
        logging.getLogger("OK").info(f'Desktop shortcut created: {shortcut_path.name}')
        return True
    except ImportError:
        # Fallback: create a batch file as the shortcut
        batch_path = desktop / "JARVIS - MARK XXXV.bat"
        with open(batch_path, "w") as f:
            f.write(f'@echo off\npython "{script_path}"\npause\n')
        logging.getLogger("OK").info(f'Batch shortcut created: {batch_path.name}')
        logging.getLogger(__name__).info('NOTE: win32com not available. Using batch file instead.')
        logging.getLogger(__name__).info("You can right-click the .bat file -> 'Create shortcut' for a proper icon.")
        return False
    except Exception as e:
        logging.getLogger("ERROR").info(f'Could not create shortcut: {e}')
        return False


if __name__ == "__main__":
    create_desktop_shortcut()