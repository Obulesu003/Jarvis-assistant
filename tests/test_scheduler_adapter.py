"""Tests for integrations.system.scheduler_adapter and scheduler keyword routing."""
import unittest.mock

import pytest


class TestExtractScheduleParams:
    """Test _extract_schedule_params helper (doesn't need adapters)."""

    @pytest.fixture
    def orchestrator(self):
        """Create a minimal orchestrator to test the extractors."""
        from integrations.core.universal_orchestrator import UniversalOrchestrator
        return UniversalOrchestrator(ui=None)

    # ------------------------------------------------------------------ #
    # Goal extraction                                                     #
    # ------------------------------------------------------------------ //

    def test_extract_reminder_goal_delete(self, orchestrator):
        """'delete reminder to X' → X"""
        rl = "delete reminder to check emails"
        goal = orchestrator._extract_reminder_goal("delete reminder to check emails", rl)
        assert goal == "check emails"

    def test_extract_reminder_goal_cancel(self, orchestrator):
        """'cancel schedule for X' → X"""
        goal = orchestrator._extract_reminder_goal("cancel schedule for standup", "cancel schedule for standup")
        assert "standup" in goal

    def test_extract_reminder_goal_remove(self, orchestrator):
        """'remove reminder X' → X"""
        goal = orchestrator._extract_reminder_goal("remove reminder backup files", "remove reminder backup files")
        assert "backup" in goal

    # ------------------------------------------------------------------ #
    # Schedule params — goal                                             #
    # ------------------------------------------------------------------ //

    def test_extract_goal_remind_me(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me to check emails every morning at 8am",
            "remind me to check emails every morning at 8am",
        )
        assert params["goal"] == "check emails"

    def test_extract_goal_reminder_to(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "reminder to stand up every hour",
            "reminder to stand up every hour",
        )
        assert "stand up" in params["goal"]

    def test_extract_goal_schedule_task(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "schedule task to check news every evening",
            "schedule task to check news every evening",
        )
        assert "check news" in params["goal"]

    def test_extract_goal_set_reminder(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "set a reminder to call mom every day at 9pm",
            "set a reminder to call mom every day at 9pm",
        )
        assert "call mom" in params["goal"]

    # ------------------------------------------------------------------ #
    # Schedule params — time                                              #
    # ------------------------------------------------------------------ //

    def test_extract_time_8am(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me to check emails every morning at 8am",
            "remind me to check emails every morning at 8am",
        )
        assert params["time"] == "08:00"

    def test_extract_time_3pm(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me to drink water every day at 3pm",
            "remind me to drink water every day at 3pm",
        )
        assert params["time"] == "15:00"

    def test_extract_time_6am(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me to stretch every day at 6am",
            "remind me to stretch every day at 6am",
        )
        assert params["time"] == "06:00"

    def test_extract_time_12am_midnight(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me at 12am to backup",
            "remind me at 12am to backup",
        )
        assert params["time"] == "00:00"

    def test_extract_time_12pm_noon(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me at 12pm to eat lunch",
            "remind me at 12pm to eat lunch",
        )
        assert params["time"] == "12:00"

    def test_extract_time_830(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me at 8:30 to start standup",
            "remind me at 8:30 to start standup",
        )
        assert params["time"] == "08:30"

    def test_default_time_morning(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me every morning to check emails",
            "remind me every morning to check emails",
        )
        assert params["time"] == "08:00"

    def test_default_time_evening(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me every evening to check for updates",
            "remind me every evening to check for updates",
        )
        assert params["time"] == "20:00"

    def test_default_time_night(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me every night to backup files",
            "remind me every night to backup files",
        )
        assert params["time"] == "20:00"

    # ------------------------------------------------------------------ #
    # Schedule params — type                                              #
    # ------------------------------------------------------------------ //

    def test_schedule_daily(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me every day to drink water",
            "remind me every day to drink water",
        )
        assert params["schedule"] == "daily"

    def test_schedule_weekday(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me every weekday to stand up",
            "remind me every weekday to stand up",
        )
        assert params["schedule"] == "weekly"
        assert params["days"] == "Mon,Tue,Wed,Thu,Fri"

    def test_schedule_hourly(self, orchestrator):
        params = orchestrator._extract_schedule_params(
            "remind me every hour to stretch",
            "remind me every hour to stretch",
        )
        assert params["schedule"] == "interval"
        assert params["interval"] == 60


class TestSchedulerAdapterUnit:
    """Test SchedulerAdapter with full mocking."""

    @pytest.fixture
    def mock_sched(self):
        mock = unittest.mock.MagicMock()
        mock._schedules = {}
        mock._lock = unittest.mock.MagicMock()
        mock._lock.__enter__ = unittest.mock.MagicMock(return_value=None)
        mock._lock.__exit__ = unittest.mock.MagicMock(return_value=None)
        return mock

    @pytest.fixture
    def adapter(self, mock_sched):
        from integrations.system.scheduler_adapter import SchedulerAdapter
        from unittest.mock import patch

        with patch("core.scheduler.get_scheduler", return_value=mock_sched):
            a = SchedulerAdapter()
            a._scheduler = mock_sched
            return a

    # ------------------------------------------------------------------ #
    # Capabilities                                                        #
    # ------------------------------------------------------------------ //

    def test_capabilities(self, adapter):
        caps = adapter.get_capabilities()
        assert "scheduler.add_schedule" in caps
        assert "scheduler.list_schedules" in caps
        assert "scheduler.remove_schedule" in caps
        assert "scheduler.enable_schedule" in caps
        assert "scheduler.disable_schedule" in caps

    # ------------------------------------------------------------------ #
    # Add Schedule                                                        #
    # ------------------------------------------------------------------ //

    def test_add_schedule_daily(self, adapter, mock_sched):
        mock_sched.add_schedule.return_value = "abc123"
        mock_sched.list_schedules.return_value = []

        r = adapter.execute("add_schedule", goal="check emails", schedule="daily", time="08:00")
        assert r.success is True
        assert r.data["goal"] == "check emails"
        assert r.data["id"] == "abc123"
        mock_sched.add_schedule.assert_called_once()

    def test_add_schedule_interval(self, adapter, mock_sched):
        mock_sched.add_schedule.return_value = "xyz"
        mock_sched.list_schedules.return_value = []

        r = adapter.execute("add_schedule", goal="stretch", schedule="interval", interval=60)
        assert r.success is True
        # Called with normalized interval format
        call_args = str(mock_sched.add_schedule.call_args)
        assert "interval:60" in call_args

    def test_add_schedule_no_goal(self, adapter):
        r = adapter.execute("add_schedule", goal="", schedule="daily")
        assert r.success is False

    # ------------------------------------------------------------------ #
    # List Schedules                                                      #
    # ------------------------------------------------------------------ //

    def test_list_schedules_empty(self, adapter, mock_sched):
        mock_sched.list_schedules.return_value = []
        r = adapter.execute("list_schedules")
        assert r.success is True
        assert r.data["count"] == 0

    def test_list_schedules_with_items(self, adapter, mock_sched):
        mock_sched.list_schedules.return_value = [
            {"id": "abc", "goal": "check email", "enabled": True, "schedule": "daily"},
        ]
        r = adapter.execute("list_schedules")
        assert r.success is True
        assert r.data["count"] == 1

    def test_list_schedules_excludes_disabled(self, adapter, mock_sched):
        mock_sched.list_schedules.return_value = [
            {"id": "abc", "goal": "check email", "enabled": True},
            {"id": "def", "goal": "stand up", "enabled": False},
        ]
        r = adapter.execute("list_schedules")
        assert r.success is True
        assert r.data["count"] == 1

    # ------------------------------------------------------------------ #
    # Remove Schedule                                                      #
    # ------------------------------------------------------------------ //

    def test_remove_by_id(self, adapter, mock_sched):
        mock_sched.remove_schedule.return_value = True
        r = adapter.execute("remove_schedule", schedule_id="abc123")
        assert r.success is True
        assert r.data["removed"] == "abc123"

    def test_remove_by_goal(self, adapter, mock_sched):
        mock_sched.list_schedules.return_value = [{"id": "abc", "goal": "check emails"}]
        mock_sched.remove_schedule.return_value = True
        r = adapter.execute("remove_schedule", goal="check emails")
        assert r.success is True
        assert r.data["count"] == 1

    def test_remove_nonexistent(self, adapter, mock_sched):
        mock_sched.remove_schedule.return_value = False
        r = adapter.execute("remove_schedule", schedule_id="nonexistent")
        assert r.success is False

    # ------------------------------------------------------------------ #
    # Enable / Disable                                                    #
    # ------------------------------------------------------------------ //

    def test_disable(self, adapter, mock_sched):
        mock_obj = unittest.mock.MagicMock()
        mock_obj.enabled = True
        mock_sched._schedules = {"abc": mock_obj}

        r = adapter.execute("disable_schedule", schedule_id="abc")
        assert r.success is True
        assert mock_obj.enabled is False
        mock_sched.save_schedules.assert_called()

    def test_enable(self, adapter, mock_sched):
        mock_obj = unittest.mock.MagicMock()
        mock_obj.enabled = False
        mock_sched._schedules = {"abc": mock_obj}

        r = adapter.execute("enable_schedule", schedule_id="abc")
        assert r.success is True
        assert mock_obj.enabled is True
        mock_sched.save_schedules.assert_called()

    def test_disable_nonexistent(self, adapter, mock_sched):
        mock_sched._schedules = {}
        r = adapter.execute("disable_schedule", schedule_id="xyz")
        assert r.success is False

    def test_session_always_active(self, adapter):
        assert adapter.check_health() is True


class TestSchedulerKeywordRouting:
    """Test scheduler keyword routing via the orchestrator's _plan_steps."""

    @pytest.fixture
    def orchestrator(self):
        from integrations.core.universal_orchestrator import UniversalOrchestrator
        from integrations.system.scheduler_adapter import SchedulerAdapter
        import unittest.mock

        orch = UniversalOrchestrator(ui=None)

        mock_sched = unittest.mock.MagicMock()
        mock_sched._schedules = {}
        mock_sched._lock = unittest.mock.MagicMock()
        mock_sched._lock.__enter__ = unittest.mock.MagicMock(return_value=None)
        mock_sched._lock.__exit__ = unittest.mock.MagicMock(return_value=None)

        with unittest.mock.patch("core.scheduler.get_scheduler", return_value=mock_sched):
            adapter = SchedulerAdapter()
            adapter._scheduler = mock_sched
            orch.register_adapter("scheduler", adapter)

        return orch

    def test_list_reminders_keyword(self, orchestrator):
        for kw in ["what schedules", "list reminders", "my reminders", "show schedules", "what reminders"]:
            steps = orchestrator._plan_steps(kw, kw.lower(), {})
            assert len(steps) == 1, f"Failed for: {kw}"
            assert steps[0]["adapter"] == "scheduler"
            assert steps[0]["action"] == "list_schedules"

    def test_remind_me_routes_to_scheduler(self, orchestrator):
        req = "remind me to check emails every morning at 8am"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["adapter"] == "scheduler"
        assert steps[0]["action"] == "add_schedule"
        assert steps[0]["params"]["goal"] == "check emails"
        assert steps[0]["params"]["time"] == "08:00"
        assert steps[0]["params"]["schedule"] == "daily"

    def test_remind_every_morning_defaults(self, orchestrator):
        req = "remind me every morning to check emails"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["time"] == "08:00"
        assert steps[0]["params"]["schedule"] == "daily"

    def test_remind_every_night_defaults(self, orchestrator):
        req = "remind me every night to check for updates"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["time"] == "20:00"

    def test_remind_every_weekday(self, orchestrator):
        req = "remind me every weekday to stand up"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["schedule"] == "weekly"
        assert steps[0]["params"]["days"] == "Mon,Tue,Wed,Thu,Fri"

    def test_remind_every_hour_interval(self, orchestrator):
        req = "remind me every hour to stretch"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["schedule"] == "interval"
        assert steps[0]["params"]["interval"] == 60

    def test_delete_reminder_routes_to_remove(self, orchestrator):
        req = "delete reminder to check emails"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["adapter"] == "scheduler"
        assert steps[0]["action"] == "remove_schedule"
        assert steps[0]["params"]["goal"] == "check emails"

    def test_cancel_schedule_routes_to_remove(self, orchestrator):
        req = "cancel schedule for standup"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["action"] == "remove_schedule"
        assert "standup" in steps[0]["params"]["goal"]

    def test_schedule_task_routes_to_add(self, orchestrator):
        req = "schedule task to check news every evening"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["action"] == "add_schedule"
        assert "check news" in steps[0]["params"]["goal"]
        assert steps[0]["params"]["time"] == "20:00"

    def test_pm_time_extraction(self, orchestrator):
        req = "remind me to drink water every day at 3pm"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["time"] == "15:00"

    def test_am_time_extraction(self, orchestrator):
        req = "remind me to stretch every day at 6am"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["time"] == "06:00"

    def test_12am_midnight(self, orchestrator):
        req = "remind me at 12am to backup"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["time"] == "00:00"

    def test_12pm_noon(self, orchestrator):
        req = "remind me at 12pm to eat lunch"
        steps = orchestrator._plan_steps(req, req.lower(), {})
        assert steps[0]["params"]["time"] == "12:00"


# Need pytest for fixtures
import pytest
