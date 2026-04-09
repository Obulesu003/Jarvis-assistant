"""
setup_startup.py - Easy setup for MARK-XXXV startup integration
Run this once to enable auto-start on Windows boot and unlock.
"""

import logging  # migrated from print()
import sys
import os
from pathlib import Path

# Add project directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    logging.getLogger(__name__).info('=')
    logging.getLogger(__name__).info('MARK-XXXV STARTUP SETUP')
    logging.getLogger(__name__).info('JARVIS Auto-Start Configuration')
    logging.getLogger(__name__).info('=')
    logger.debug()
    logging.getLogger(__name__).info('This will configure MARK-XXXV to:')
    logging.getLogger(__name__).info('1. Start automatically when Windows boots')
    logging.getLogger(__name__).info('2. Start when you unlock your screen')
    logging.getLogger(__name__).info('3. Show a welcome briefing on startup')
    logging.getLogger(__name__).info('4. Run in system tray (never closes accidentally)')
    logger.debug()
    logging.getLogger(__name__).info('=')

    confirm = input("Proceed with setup? (y/n): ").strip().lower()
    if confirm != 'y':
        logging.getLogger(__name__).info('Setup cancelled.')
        return

    logger.debug()
    logging.getLogger(__name__).info('[1/3] Configuring startup registry...')
    try:
        from startup_launcher import enable_startup_all
        enable_startup_all(start_minimized=True)
    except Exception as e:
        logging.getLogger(__name__).info(f"ERROR: {e}")

    logger.debug()
    logging.getLogger(__name__).info('[2/3] Checking dependencies...')
    deps_ok = True

    # Check pystray
    try:
        import pystray
        logging.getLogger(__name__).info('pystray: OK')
    except ImportError:
        logging.getLogger(__name__).info('pystray: MISSING - tray support will be limited')
        logging.getLogger(__name__).info('Install: pip install pystray Pillow')
        deps_ok = False

    logger.debug()
    logging.getLogger(__name__).info('[3/3] Creating desktop shortcut...')
    try:
        create_shortcut()
    except Exception as e:
        logging.getLogger(__name__).info(f"Shortcut creation failed: {e}")
        logging.getLogger(__name__).info('You can create a shortcut manually.')

    logger.debug()
    logging.getLogger(__name__).info('=')
    logging.getLogger(__name__).info('SETUP COMPLETE!')
    logger.debug()
    logging.getLogger(__name__).info("What's next:")
    logging.getLogger(__name__).info('- Restart your computer to test auto-start')
    logging.getLogger(__name__).info('- JARVIS will start minimized to system tray')
    logging.getLogger(__name__).info('- Double-click the tray icon to show JARVIS')
    logging.getLogger(__name__).info('- On unlock, JARVIS will greet you with a briefing')
    logger.debug()
    logging.getLogger(__name__).info('To uninstall startup integration, run:')
    logging.getLogger(__name__).info('python startup_launcher.py --disable')
    logging.getLogger(__name__).info('=')


def create_shortcut():
    """Create a desktop shortcut."""
    try:
        import win32com.client
        from pathlib import Path

        desktop = Path(os.path.expanduser("~/Desktop"))
        shortcut_path = desktop / "JARVIS - MARK XXXV.lnk"

        # Get the script path
        script_path = Path(__file__).resolve().parent / "main.py"
        python_path = sys.executable

        # Create shortcut via Windows COM
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = python_path
        shortcut.Arguments = f'"{script_path}"'
        shortcut.WorkingDirectory = str(script_path.parent)
        shortcut.IconLocation = str(script_path)
        shortcut.save()

        logging.getLogger(__name__).info('Shortcut created: {shortcut_path.name}')
        return True
    except ImportError:
        logging.getLogger(__name__).info('win32com not available - skipping shortcut')
        return False
    except Exception as e:
        logging.getLogger(__name__).info('Could not create shortcut: {e}')
        return False


if __name__ == "__main__":
    main()
