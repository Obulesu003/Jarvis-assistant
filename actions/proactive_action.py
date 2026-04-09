"""
proactive_action.py - Action functions to control the proactive monitor.
"""
import logging

logger = logging.getLogger(__name__)

_monitor = None


def get_monitor():
    """Get or create the global proactive monitor instance."""
    global _monitor
    if _monitor is None:
        from core.proactive_monitor import ProactiveMonitor
        try:
            from memory.j_memory import get_memory as _get_mem
            memory = _get_mem()
        except Exception:
            memory = None
        _monitor = ProactiveMonitor(memory=memory)
    return _monitor


def proactive_action(params: dict, player=None):
    """Action to control the proactive monitor."""
    cmd = params.get("command", "status")
    mon = get_monitor()

    if cmd == "start":
        mon.start()
        return {"status": "started", "message": "Proactive monitor active"}
    elif cmd == "stop":
        mon.stop()
        return {"status": "stopped", "message": "Proactive monitor stopped"}
    elif cmd == "status":
        return {"status": "ok", "running": mon._running}
    elif cmd == "speak":
        text = params.get("text", "")
        if mon._speak:
            mon._speak(text)
        return {"status": "spoken"}
    elif cmd == "register":
        # Register custom monitor callback
        # Params: check_func (import path), on_change_func (import path)
        logger.info("[ProactiveAction] Custom monitor registration requires import paths")
        return {"status": "ok"}
    else:
        return {"status": "error", "message": f"Unknown command: {cmd}"}
