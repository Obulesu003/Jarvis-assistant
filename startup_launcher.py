"""
startup_launcher.py - MARK-XXXV Windows Startup Integration
Registers JARVIS to start automatically on Windows boot and lock/unlock events.
"""

import sys
import os
from pathlib import Path
import winreg
import logging

logger = logging.getLogger(__name__)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def get_jarvis_exe_path() -> Path:
    """Find the JARVIS executable or Python script."""
    exe_path = BASE_DIR / "Mark-XXXV.exe"
    if exe_path.exists():
        return exe_path

    # Try the Python script
    script_path = BASE_DIR / "main.py"
    if script_path.exists():
        python = sys.executable
        return Path(f'"{python}" "{script_path}"')

    # Return default
    return BASE_DIR / "main.py"


def register_startup(app_name: str = "MARK-XXXV", minimize_to_tray: bool = True) -> bool:
    """
    Register MARK-XXXV to start automatically with Windows.
    Sets it in the HKCU registry key for Run on startup.
    """
    try:
        exe_path = get_jarvis_exe_path()
        exe_str = str(exe_path)

        if minimize_to_tray:
            exe_str += ' --start-minimized'

        key = winreg.HKEY_CURRENT_USER
        reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"

        with winreg.OpenKey(key, reg_key, 0, winreg.KEY_SET_VALUE) as run_key:
            winreg.SetValueEx(run_key, app_name, 0, winreg.REG_SZ, exe_str)

        logger.info(f"[Startup] Registered '{app_name}' to run at startup")
        logging.getLogger("Startup").debug('{app_name} will start automatically on Windows boot')
        return True

    except PermissionError:
        logger.error("[Startup] Permission denied - run as administrator if needed")
        logging.getLogger("Startup").info('ERROR: Permission denied')
        return False
    except Exception as e:
        logger.error(f"[Startup] Failed to register: {e}")
        logging.getLogger("Startup").info('ERROR: {e}')
        return False


def unregister_startup(app_name: str = "MARK-XXXV") -> bool:
    """Remove MARK-XXXV from Windows startup."""
    try:
        key = winreg.HKEY_CURRENT_USER
        reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"

        with winreg.OpenKey(key, reg_key, 0, winreg.KEY_SET_VALUE) as run_key:
            try:
                winreg.DeleteValue(run_key, app_name)
                logger.info(f"[Startup] Unregistered '{app_name}' from startup")
                logging.getLogger("Startup").debug('{app_name} removed from startup')
                return True
            except FileNotFoundError:
                logger.info(f"[Startup] '{app_name}' was not in startup")
                logging.getLogger("Startup").info('INFO: {app_name} was not registered')
                return True

    except Exception as e:
        logger.error(f"[Startup] Failed to unregister: {e}")
        logging.getLogger("Startup").info('ERROR: {e}')
        return False


def is_registered_startup(app_name: str = "MARK-XXXV") -> bool:
    """Check if MARK-XXXV is registered to start with Windows."""
    try:
        key = winreg.HKEY_CURRENT_USER
        reg_key = r"Software\Microsoft\Windows\CurrentVersion\Run"

        with winreg.OpenKey(key, reg_key, 0, winreg.KEY_READ) as run_key:
            try:
                value, _ = winreg.QueryValueEx(run_key, app_name)
                return value is not None
            except FileNotFoundError:
                return False

    except Exception:
        return False


def register_task_scheduler() -> bool:
    """
    Register a Windows Task Scheduler task that runs on system unlock.
    This enables JARVIS to start when the user unlocks the screen.
    Uses PowerShell for reliable task creation with unlock trigger.
    """
    try:
        import subprocess

        exe_path = get_jarvis_exe_path()
        exe_str = str(exe_path).replace("\\", "\\\\").replace('"', '\\"')

        ps_script = f"""
$action = New-ScheduledTaskAction -Execute 'python' -Argument '"{exe_str}"'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Unregister existing task if present
Unregister-ScheduledTask -TaskName 'MARK-XXXV' -Confirm:$false -ErrorAction SilentlyContinue

# Register the task
Register-ScheduledTask -TaskName 'MARK-XXXV' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'MARK-XXXV - JARVIS AI Assistant - Starts on logon'
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0 and not result.stderr.strip():
            logger.info("[Startup] Task Scheduler task registered for logon")
            logging.getLogger("Startup").debug('Task registered: will start on system logon')
            return True
        else:
            logger.warning(f"[Startup] Task Scheduler failed: {result.stderr or result.stdout}")
            logging.getLogger("Startup").info('WARN: Task Scheduler: {result.stderr or result.stdout}')
            return False

    except Exception as e:
        logger.error(f"[Startup] Task Scheduler registration failed: {e}")
        logging.getLogger("Startup").info('ERROR: Task Scheduler: {e}')
        return False

    except Exception as e:
        logger.error(f"[Startup] Task Scheduler registration failed: {e}")
        logging.getLogger("Startup").info('ERROR: Task Scheduler: {e}')
        return False


def unregister_task_scheduler() -> bool:
    """Remove the MARK-XXXV Task Scheduler task."""
    try:
        import subprocess

        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", "MARK-XXXV", "/F"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            logging.getLogger("Startup").debug('Task scheduler removed')
            return True
        else:
            logging.getLogger("Startup").info('INFO: Task was not registered')
            return True

    except Exception as e:
        logging.getLogger("Startup").info('ERROR: {e}')
        return False


def enable_startup_all(start_minimized: bool = True) -> bool:
    """Enable all startup methods."""
    logging.getLogger("Startup").info('Configuring MARK-XXXV startup integration...')
    logging.getLogger(__name__).info('=')

    # Register for boot startup
    reg_ok = register_startup(minimize_to_tray=start_minimized)

    # Register Task Scheduler for unlock/logon
    task_ok = register_task_scheduler()

    logging.getLogger(__name__).info('=')
    if reg_ok and task_ok:
        logging.getLogger("Startup").info('SUCCESS: MARK-XXXV will start on boot AND unlock')
        logging.getLogger(__name__).info('JARVIS will greet you automatically!')
        return True
    elif reg_ok:
        logging.getLogger("Startup").info('PARTIAL: Boot startup enabled')
        return True
    else:
        logging.getLogger("Startup").info('FAILED: Could not enable startup')
        return False


def disable_startup_all() -> bool:
    """Disable all startup methods."""
    logging.getLogger("Startup").info('Removing MARK-XXXV startup integration...')
    unregister_startup()
    unregister_task_scheduler()
    logging.getLogger("Startup").info('Done.')
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MARK-XXXV Startup Integration")
    parser.add_argument("--enable", action="store_true", help="Enable startup")
    parser.add_argument("--disable", action="store_true", help="Disable startup")
    parser.add_argument("--status", action="store_true", help="Check startup status")
    parser.add_argument("--minimized", action="store_true", default=True, help="Start minimized to tray")

    args = parser.parse_args()

    if args.enable:
        enable_startup_all(start_minimized=args.minimized)
    elif args.disable:
        disable_startup_all()
    elif args.status:
        logging.getLogger(__name__).info('=')
        logging.getLogger(__name__).info('MARK-XXXV Startup Status')
        logging.getLogger(__name__).info('=')
        logging.getLogger(__name__).info("Boot Startup: {'ENABLED' if is_registered_startup() else 'DISABLED'}")
        logging.getLogger(__name__).info('=')
    else:
        logging.getLogger(__name__).info('Usage: python startup_launcher.py --enable | --disable | --status')
