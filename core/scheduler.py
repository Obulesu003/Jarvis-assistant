# core/scheduler.py
# Background task scheduler for proactive and recurring tasks.
# Supports: one-time, daily, weekly, interval-based schedules.

import logging  # migrated from print()
import contextlib
import io
import sys

for _s in (sys.stdout, sys.stderr):
    if isinstance(_s, io.TextIOWrapper):
        with contextlib.suppress(Exception): _s.reconfigure(encoding="utf-8", errors="replace")
import json
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR       = get_base_dir()
SCHEDULES_FILE = BASE_DIR / "memory" / "schedules.json"


class ScheduleType(Enum):
    ONE_TIME  = "one_time"
    DAILY     = "daily"
    WEEKLY    = "weekly"
    INTERVAL  = "interval"
    AMBIENT   = "ambient"


@dataclass
class Schedule:
    id:          str
    goal:        str
    schedule:    str       # "daily" | "weekly" | "interval:N" | "one_time" | "ambient"
    time_str:    str = ""  # "HH:MM" for daily/weekly
    days:        str = ""  # "Mon,Tue,Wed" for weekly
    interval_m:  int = 0   # minutes for interval
    ambient:     bool = False
    enabled:     bool = True
    last_run:    float = 0
    next_run:    float = 0
    created_at:  float = field(default_factory=time.time)


class TaskScheduler:
    """
    Background scheduler that triggers tasks at specified intervals.
    Runs in a dedicated daemon thread.
    """

    def __init__(self):
        self._schedules:  dict[str, Schedule] = {}
        self._lock:       threading.Lock = threading.Lock()
        self._running:    bool = False
        self._thread:     threading.Thread | None = None
        self._check_interval = 30  # seconds between checks
        self._speak:      Callable | None = None
        self._task_queue_runner: Callable | None = None  # callback to submit to task queue

    def set_speak(self, speak: Callable | None):
        self._speak = speak

    def set_task_queue_runner(self, runner: Callable | None):
        """Set a callback that submits goals to the task queue."""
        self._task_queue_runner = runner

    def load_schedules(self):
        """Load schedules from disk."""
        if not SCHEDULES_FILE.exists():
            return
        try:
            with open(SCHEDULES_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            with self._lock:
                for s in raw.get("schedules", []):
                    sched = Schedule(
                        id=s["id"], goal=s["goal"], schedule=s["schedule"],
                        time_str=s.get("time_str", ""), days=s.get("days", ""),
                        interval_m=s.get("interval_m", 0),
                        ambient=s.get("ambient", False),
                        enabled=s.get("enabled", True),
                        last_run=s.get("last_run", 0),
                        next_run=s.get("next_run", 0),
                        created_at=s.get("created_at", time.time()),
                    )
                    self._schedules[sched.id] = sched
                    self._compute_next_run(sched)
            logging.getLogger("Scheduler").info('Loaded {len(self._schedules)} schedules')
        except Exception as e:
            logging.getLogger("Scheduler").info(f"Failed to load schedules: {e}")

    def save_schedules(self):
        """Persist schedules to disk."""
        try:
            SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    "schedules": [
                        {
                            "id": s.id, "goal": s.goal, "schedule": s.schedule,
                            "time_str": s.time_str, "days": s.days,
                            "interval_m": s.interval_m, "ambient": s.ambient,
                            "enabled": s.enabled, "last_run": s.last_run,
                            "next_run": s.next_run, "created_at": s.created_at,
                        }
                        for s in self._schedules.values()
                    ]
                }
            with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.getLogger("Scheduler").info(f"Failed to save schedules: {e}")

    def add_schedule(
        self,
        goal: str,
        schedule: str,
        time_str: str = "",
        days: str = "",
        ambient: bool = False,
    ) -> str:
        """Add a new schedule. Returns schedule ID."""
        import uuid
        sched = Schedule(
            id=uuid.uuid4().hex[:8],
            goal=goal,
            schedule=schedule,
            time_str=time_str,
            days=days,
            ambient=ambient,
        )

        if schedule.startswith("interval:"):
            try:
                sched.interval_m = int(schedule.split(":")[1])
                sched.schedule = "interval"
            except (ValueError, IndexError):
                sched.schedule = "one_time"

        self._compute_next_run(sched)

        with self._lock:
            self._schedules[sched.id] = sched
        self.save_schedules()
        logging.getLogger("Scheduler").info('Added: {sched.id} -- {goal} (next: {self._fmt_time(sched.next_run)})')
        return sched.id

    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule by ID."""
        with self._lock:
            if schedule_id in self._schedules:
                del self._schedules[schedule_id]
                self.save_schedules()
                return True
        return False

    def list_schedules(self) -> list[dict]:
        """Return all schedules as dicts."""
        with self._lock:
            result = []
            for s in self._schedules.values():
                result.append({
                    "id": s.id, "goal": s.goal, "schedule": s.schedule,
                    "time_str": s.time_str, "days": s.days,
                    "interval_m": s.interval_m, "ambient": s.ambient,
                    "enabled": s.enabled,
                    "next_run": self._fmt_time(s.next_run) if s.next_run else "now",
                    "last_run": self._fmt_time(s.last_run) if s.last_run else "never",
                })
            return result

    def _compute_next_run(self, sched: Schedule):
        """Calculate the next run timestamp."""
        now = time.time()
        sched.next_run = now  # default: run ASAP

        if sched.schedule == "one_time":
            sched.next_run = now + 3600  # 1 hour from now as default
            if sched.time_str:
                try:
                    dt = datetime.strptime(sched.time_str, "%H:%M")
                    today = datetime.now().replace(hour=dt.hour, minute=dt.minute, second=0)
                    sched.next_run = today.timestamp()
                    if sched.next_run <= now:
                        sched.next_run += 86400  # tomorrow
                except ValueError:
                    pass

        elif sched.schedule == "daily":
            if sched.time_str:
                try:
                    dt = datetime.strptime(sched.time_str, "%H:%M")
                    today = datetime.now().replace(hour=dt.hour, minute=dt.minute, second=0)
                    next_t = today.timestamp()
                    if next_t <= now:
                        next_t += 86400
                    sched.next_run = next_t
                except ValueError:
                    sched.next_run = now + 86400
            else:
                sched.next_run = now + 86400

        elif sched.schedule == "interval":
            sched.next_run = now + (sched.interval_m * 60)

        elif sched.schedule == "ambient":
            sched.next_run = now + (sched.interval_m * 60 if sched.interval_m else 300)

    def _fmt_time(self, ts: float) -> str:
        if ts <= 0:
            return "never"
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

    def _should_run(self, sched: Schedule) -> bool:
        if not sched.enabled:
            return False
        if sched.schedule == "one_time" and sched.last_run > 0:
            return False  # already ran
        return time.time() >= sched.next_run

    def start(self):
        """Start the scheduler background thread."""
        if self._running:
            return
        self._running = True
        self.load_schedules()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TaskScheduler")
        self._thread.start()
        logging.getLogger("Scheduler").info('Started')

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logging.getLogger("Scheduler").info('Stopped')

    def _loop(self):
        """Main scheduler loop."""
        while self._running:
            try:
                now = time.time()
                with self._lock:
                    due = [s for s in self._schedules.values() if self._should_run(s)]

                for sched in due:
                    self._run_schedule(sched)

                # Recompute next run for completed one-time schedules
                with self._lock:
                    for s in self._schedules.values():
                        if s.schedule == "one_time" and s.last_run > 0 and s.next_run <= now:
                            s.enabled = False
                            s.next_run = 0

                self.save_schedules()

            except Exception as e:
                logging.getLogger("Scheduler").info(f"Loop error: {e}")

            time.sleep(self._check_interval)

    def _run_schedule(self, sched: Schedule):
        """Execute a due schedule."""
        logging.getLogger("Scheduler").info(f"Running: {sched.goal}")
        sched.last_run = time.time()
        self._compute_next_run(sched)

        if sched.ambient:
            # Ambient tasks run silently
            if self._task_queue_runner:
                try:
                    self._task_queue_runner(sched.goal, priority="normal")
                except Exception as e:
                    logging.getLogger("Scheduler").info(f"Ambient task failed: {e}")
        else:
            # Regular scheduled tasks: speak a notification
            if self._speak:
                self._speak(f"Sir, it's time for: {sched.goal}")
            if self._task_queue_runner:
                try:
                    self._task_queue_runner(sched.goal, priority="normal")
                except Exception as e:
                    logging.getLogger("Scheduler").info(f"Scheduled task failed: {e}")


# Singleton
_scheduler: TaskScheduler | None = None
_sched_lock = threading.Lock()


def get_scheduler() -> TaskScheduler:
    global _scheduler
    if _scheduler is None:
        with _sched_lock:
            if _scheduler is None:
                _scheduler = TaskScheduler()
    return _scheduler
