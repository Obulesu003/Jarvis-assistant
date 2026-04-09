import logging  # migrated from print()
import contextlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class TaskPriority(Enum):
    LOW    = 3
    NORMAL = 2
    HIGH   = 1


@dataclass(order=True)
class Task:
    priority:    int
    created_at:  float = field(compare=False)
    task_id:     str   = field(compare=False)
    goal:        str   = field(compare=False)
    status:      TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result:      Any        = field(compare=False, default=None)
    error:       str        = field(compare=False, default="")
    speak:       Any        = field(compare=False, default=None)
    on_complete: Any        = field(compare=False, default=None)
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)


class TaskQueue:
    def __init__(self, max_concurrent: int = 1):  # Changed from 3 to 1 - run one task at a time
        self._queue:        list[Task]       = []
        self._lock:         threading.Lock   = threading.Lock()
        self._condition:    threading.Condition = threading.Condition(self._lock)
        self._tasks:        dict[str, Task]  = {}
        self._running:      bool             = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._active_count   = 0
        self._executor       = None
        self._last_goals:    list[str]        = []  # Track last 5 goals to prevent duplicates
        self._max_goal_history = 5
        self._current_task_id: str | None = None
        self._current_step_info: dict | None = None

    def _get_executor(self):
        if self._executor is None:
            from agent.executor import AgentExecutor
            self._executor = AgentExecutor()
        return self._executor

    def start(self) -> None:
        if self._running:
            return
        self._running      = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AgentTaskQueue"
        )
        self._worker_thread.start()
        logging.getLogger("TaskQueue").debug('Started')

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        logging.getLogger("TaskQueue").info('🔴 Stopped')

    def submit(
        self,
        goal:        str,
        priority:    TaskPriority = TaskPriority.NORMAL,
        speak:       Callable | None = None,
        on_complete: Callable | None = None,
    ) -> str:

        # Check for duplicate goals - skip if same goal ran recently
        goal_lower = goal.lower().strip()
        with self._lock:
            if goal_lower in self._last_goals:
                logging.getLogger("TaskQueue").info(f'Duplicate goal detected: {goal[:50]}')
                return "duplicate"

        task_id = str(uuid.uuid4())[:8]
        task    = Task(
            priority    = priority.value,
            created_at  = time.time(),
            task_id     = task_id,
            goal        = goal,
            speak       = speak,
            on_complete = on_complete,
        )

        with self._condition:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[task_id] = task
            # Track goal for duplicate detection
            self._last_goals.append(goal_lower)
            if len(self._last_goals) > self._max_goal_history:
                self._last_goals.pop(0)
            self._condition.notify()

        logging.getLogger("TaskQueue").info(f'📥 Task queued: [{task_id}] {goal[:60]}')
        return task_id

    def cancel(self, task_id: str) -> bool:

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False

            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            logging.getLogger("TaskQueue").info(f"🚫 Task cancelled: [{task_id}]")
            return True

    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "goal":    task.goal,
                "status":  task.status.value,
                "result":  task.result,
                "error":   task.error,
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "goal":    t.goal[:50],
                    "status":  t.status.value,
                }
                for t in self._tasks.values()
            ]

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._queue if t.status == TaskStatus.PENDING)

    def get_current_task_progress(self) -> dict | None:
        """
        Returns information about the currently running task and step.
        Used by the executor for stuck detection feedback.
        """
        with self._lock:
            if self._current_task_id:
                task = self._tasks.get(self._current_task_id)
                if task and task.status == TaskStatus.RUNNING:
                    return {
                        "task_id": task.task_id,
                        "goal": task.goal[:100],
                        "step_info": self._current_step_info,
                        "status": task.status.value,
                    }
            return None

    def _worker_loop(self) -> None:
        while self._running:
            task = None

            with self._condition:
                # Poll frequently — no artificial delay
                while self._running and not self._next_task():
                    self._condition.wait(timeout=0.05)   # was 1.0s → now 50ms
                task = self._next_task()
                if task:
                    task.status = TaskStatus.RUNNING
                    self._active_count += 1
                    with contextlib.suppress(ValueError):
                        self._queue.remove(task)

            if task:
                t = threading.Thread(
                    target=self._run_task,
                    args=(task,),
                    daemon=True,
                    name=f"AgentTask-{task.task_id}"
                )
                t.start()
                # Decrement counter AFTER the thread is spawned (not when it finishes)
                # This allows the next task to start without waiting for the thread to complete
                with self._lock:
                    self._active_count -= 1
                    self._active_count = max(0, self._active_count)

    def _next_task(self) -> Task | None:
        if self._active_count >= self._max_concurrent:
            return None
        for task in self._queue:
            if task.status == TaskStatus.PENDING and not task.cancel_flag.is_set():
                return task
        return None

    def _run_task(self, task: Task) -> None:
        logging.getLogger("TaskQueue").info(f'️ Running: [{task.task_id}] {task.goal[:60]}')

        # Set current task info for progress tracking
        with self._lock:
            self._current_task_id = task.task_id
            self._current_step_info = {"step": "initializing", "description": task.goal[:50]}

        # Initialize executor's last activity time
        executor = self._get_executor()
        executor._last_activity_time = time.time()
        executor._current_step = None

        try:
            result = executor.execute(
                goal        = task.goal,
                speak       = task.speak,
                cancel_flag = task.cancel_flag,
            )

            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = result

            if task.on_complete and not task.cancel_flag.is_set():
                try:
                    task.on_complete(task.task_id, result)
                except Exception as e:
                    logging.getLogger("TaskQueue").warning(f'️ on_complete callback error: {e}')

            logging.getLogger("TaskQueue").debug(f"Completed: [{task.task_id}]")

        except Exception as e:
            with self._lock:
                task.status = TaskStatus.FAILED
                task.error  = str(e)
            logging.getLogger("TaskQueue").error(f'Failed: [{task.task_id}] {e}')

        # Clear current task info
        with self._lock:
            self._current_task_id = None
            self._current_step_info = None

        with self._condition:
            self._condition.notify()

_queue        = TaskQueue()
_queue_started = False
_queue_lock    = threading.Lock()


def get_queue() -> TaskQueue:
    global _queue_started
    with _queue_lock:
        if not _queue_started:
            _queue.start()
            _queue_started = True
    return _queue
