# J.A.R.V.I.S — Cinematic Auto-Start Setup

## What This Does

When configured, MARK-XXXV will:

1. **Start automatically when Windows boots** - JARVIS runs in the background
2. **Start when you unlock your screen** - JARVIS greets you with a welcome briefing
3. **Run in system tray** - JARVIS never closes until you explicitly exit
4. **Give personalized briefings** - Weather, emails, calendar, reminders

## Quick Setup

Run this ONE TIME to configure everything:

```bash
python setup_startup.py
```

Or manually:

```bash
python startup_launcher.py --enable
```

## What Gets Configured

### 1. Windows Registry (Startup)
JARVIS is added to `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`

### 2. Task Scheduler
A task is created to run on:
- System Logon
- System Unlock

## Manual Control

```bash
# Enable auto-start
python startup_launcher.py --enable

# Disable auto-start
python startup_launcher.py --disable

# Check status
python startup_launcher.py --status
```

## First Start Experience

When JARVIS first starts, you'll hear:

"Good morning, Bobby. I hope you slept well. JARVIS is online. Systems operational."

Then it checks:
- Unread emails → tells you how many
- Today's calendar → mentions any events
- Weather in Istanbul
- Active reminders

## Unlock Experience

When you unlock your screen:

"JARVIS online. Welcome back."

Then checks what's new since you locked.

## System Tray

JARVIS minimizes to system tray with an icon.
- Double-click tray icon → Show JARVIS
- Right-click → Menu with Show/Exit

## Troubleshooting

### JARVIS doesn't start on boot
1. Check Task Scheduler (taskschd.msc) for "MARK-XXXV" task
2. Run: `python startup_launcher.py --status`
3. Check Windows Event Viewer → Application logs

### System tray not working
Install pystray:
```bash
pip install pystray Pillow
```

### Lock monitor not detecting unlock
The lock monitor uses input idle time. If you lock for less than 5 minutes, it won't trigger.

## Removing Everything

```bash
python startup_launcher.py --disable
```

This removes:
- Registry entry
- Task Scheduler task
- But NOT the desktop shortcut

---

Ready to have your own JARVIS? Let's go!
