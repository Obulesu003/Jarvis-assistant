"""
Scheduler integration adapter for MARK-XXXV.

Bridges the TaskScheduler from core/scheduler.py into the LLM orchestrator,
enabling natural language scheduling: "remind me every morning at 8am to check emails".
"""
from typing import Any

from integrations.base.adapter import ActionResult, BaseIntegrationAdapter


class SchedulerAdapter(BaseIntegrationAdapter):
    """Adapter for scheduling recurring and one-time tasks."""

    SERVICE_NAME = "scheduler"

    def __init__(self):
        # Scheduler is a singleton — no browser/session needed
        super().__init__()
        self._scheduler = self._get_scheduler()

    def _get_scheduler(self) -> Any:
        from core.scheduler import get_scheduler
        return get_scheduler()

    # ------------------------------------------------------------------ #
    # Capabilities                                                         #
    # ------------------------------------------------------------------ //

    def get_capabilities(self) -> list[str]:
        return [
            "scheduler.add_schedule",
            "scheduler.list_schedules",
            "scheduler.remove_schedule",
            "scheduler.enable_schedule",
            "scheduler.disable_schedule",
        ]

    # ------------------------------------------------------------------ #
    # Actions                                                             #
    # ------------------------------------------------------------------ //

    def _execute_action(self, action: str, **kwargs) -> ActionResult:
        method_name = f"_action_{action}"
        method = getattr(self, method_name, None)
        if method is None:
            return ActionResult(success=False, error=f"Unknown action: {action}")
        return method(**kwargs)

    def _action_add_schedule(
        self,
        goal: str = "",
        schedule: str = "daily",
        time: str = "",
        days: str = "",
        interval: int = 0,
        ambient: bool = False,
        **kwargs,
    ) -> ActionResult:
        """Add a new scheduled task."""
        if not goal:
            return ActionResult(success=False, error="Please specify a goal for the scheduled task.")

        # Normalize schedule format
        if schedule == "interval" and interval > 0:
            schedule = f"interval:{interval}"

        sched_id = self._scheduler.add_schedule(goal, schedule, time, days, ambient)
        sched = next((s for s in self._scheduler.list_schedules() if s["id"] == sched_id), None)
        next_run = sched["next_run"] if sched else "scheduled"

        return ActionResult(
            success=True,
            data={
                "id": sched_id,
                "goal": goal,
                "schedule": schedule,
                "next_run": next_run,
            },
        )

    def _action_list_schedules(
        self,
        include_disabled: bool = False,
        **kwargs,
    ) -> ActionResult:
        """List all scheduled tasks."""
        schedules = self._scheduler.list_schedules()
        if not include_disabled:
            schedules = [s for s in schedules if s.get("enabled", True)]
        return ActionResult(success=True, data={"schedules": schedules, "count": len(schedules)})

    def _action_remove_schedule(
        self,
        schedule_id: str = "",
        goal: str = "",
        **kwargs,
    ) -> ActionResult:
        """Remove a scheduled task by ID or by goal keyword."""
        if schedule_id:
            removed = self._scheduler.remove_schedule(schedule_id)
            if removed:
                return ActionResult(success=True, data={"removed": schedule_id})
            return ActionResult(success=False, error=f"Schedule not found: {schedule_id}")

        # Fallback: match by goal keyword
        schedules = self._scheduler.list_schedules()
        matched = [s for s in schedules if goal.lower() in s.get("goal", "").lower()]
        if not matched:
            return ActionResult(success=False, error=f"No schedule found matching: {goal}")
        # Remove all matching
        for s in matched:
            self._scheduler.remove_schedule(s["id"])
        return ActionResult(success=True, data={"removed": [s["id"] for s in matched], "count": len(matched)})

    def _action_enable_schedule(
        self,
        schedule_id: str = "",
        **kwargs,
    ) -> ActionResult:
        """Enable a disabled schedule."""
        with self._scheduler._lock:
            if schedule_id not in self._scheduler._schedules:
                return ActionResult(success=False, error=f"Schedule not found: {schedule_id}")
            sched = self._scheduler._schedules[schedule_id]
            sched.enabled = True
            self._scheduler._compute_next_run(sched)
        self._scheduler.save_schedules()
        return ActionResult(success=True, data={"id": schedule_id, "enabled": True, "next_run": sched.next_run})

    def _action_disable_schedule(
        self,
        schedule_id: str = "",
        goal: str = "",
        **kwargs,
    ) -> ActionResult:
        """Disable a schedule (keeps it saved, stops firing)."""
        if schedule_id:
            with self._scheduler._lock:
                if schedule_id not in self._scheduler._schedules:
                    return ActionResult(success=False, error=f"Schedule not found: {schedule_id}")
                sched = self._scheduler._schedules[schedule_id]
                sched.enabled = False
            self._scheduler.save_schedules()
            return ActionResult(success=True, data={"id": schedule_id, "enabled": False})

        # Fallback: match by goal keyword
        schedules = self._scheduler.list_schedules()
        matched = [s for s in schedules if goal.lower() in s.get("goal", "").lower()]
        if not matched:
            return ActionResult(success=False, error=f"No schedule found matching: {goal}")
        for s in matched:
            with self._scheduler._lock:
                if s["id"] in self._scheduler._schedules:
                    self._scheduler._schedules[s["id"]].enabled = False
        self._scheduler.save_schedules()
        return ActionResult(success=True, data={"disabled": [s["id"] for s in matched], "count": len(matched)})

    def _is_session_active(self) -> bool:
        """Scheduler is always available."""
        return True
