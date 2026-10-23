# SPDX-License-Identifier: GPL-3.0-or-later
"""Setting up the agent's private venv from Blender: where it goes, the
checks before anything is downloaded, the timer that drives the install,
and the operators behind the preferences' buttons.

An install only ever starts from the confirmation dialog of
whittle.venv_install, never on its own and never during a turn, so the
agent's exec cannot trigger one."""

import importlib.util
import logging
import platform
import sys
import time
from pathlib import Path

import bpy
from bpy.props import BoolProperty

from .. import venv
from ..venv import VenvSetup, VenvStatus
from . import paths, prefs, turn
from .process import AgentState

log = logging.getLogger("whittle")

UNREGISTER_WAIT = 2.0

_current: VenvSetup | None = None


def venv_dir() -> Path:
    folder = prefs.get().venv_dir
    if folder:
        return Path(bpy.path.abspath(folder)).resolve()
    return paths.user_dir() / "venv"


def lock_path() -> Path:
    return Path(__file__).resolve().parent.parent / venv.LOCK_NAME


def base_python() -> Path:
    return Path(sys.executable)


def current() -> VenvSetup | None:
    return _current


def _turn_busy() -> bool:
    return turn.busy(turn.current())


def begin(*, reinstall: bool = False, dry_run: bool = False) -> VenvSetup:
    """Starts setting up the venv; RuntimeError carries the user-facing
    reason when it cannot. A dry run only logs the commands."""
    global _current
    if _current is not None and _current.running:
        raise RuntimeError("The agent environment is already being set up")
    if _turn_busy():
        raise RuntimeError("Wait for the turn to finish before setting up the agent environment")
    reason = venv.compatible(sys.version_info, platform.machine(), sys.platform)
    if reason:
        raise RuntimeError(reason[0].upper() + reason[1:])
    if importlib.util.find_spec("ensurepip") is None:
        raise RuntimeError("Blender's Python has no ensurepip, so it cannot make a venv")
    folder, lock = venv_dir(), lock_path()
    state = venv.status(folder, lock)
    if state == VenvStatus.FOREIGN:
        raise RuntimeError(f"{folder} exists and was not made by Whittle: remove it or choose "
                           "another folder")
    if state == VenvStatus.READY and not reinstall:
        raise RuntimeError("The agent environment is already set up; use Reinstall to rebuild it")
    if not dry_run:
        if not bpy.app.online_access:
            raise RuntimeError("Allow Online Access in Preferences > System to download the agent "
                               "environment")
        if bpy.app.background:
            raise RuntimeError("The agent environment can only be installed from Blender's interface")
    # A stale or broken venv is Whittle's own, so it is rebuilt from scratch.
    clear = reinstall or state in (VenvStatus.STALE, VenvStatus.BROKEN)
    steps = venv.plan(base_python(), folder, lock, reinstall=clear)
    log_path = paths.logs_dir() / f"venv-{time.strftime('%Y%m%d-%H%M%S')}.log"
    setup = VenvSetup(steps, venv=folder, lock=lock, log_path=log_path, dry_run=dry_run,
                      base_python=base_python(), on_finish=_finished)
    _current = setup
    setup.start()
    if setup.running:
        _start_timer()
    return setup


def _finished(setup: VenvSetup) -> None:
    if setup.state == "done" and not setup.dry_run:
        log.info("agent environment ready: %s", setup.venv)
        ctl = turn.current()
        if ctl is not None and ctl.process.state == AgentState.NEEDS_SETUP:
            ctl.process.clear_setup()
    elif setup.state in ("failed", "cancelled"):
        log.warning("agent environment setup %s: %s (log: %s)", setup.state, setup.reason,
                    setup.log_path)
    _redraw()


def cancel(wait: float = 0.0) -> None:
    if _current is not None:
        _current.cancel(wait=wait)
    _stop_timer()


def shutdown() -> None:
    """Unregistering must not leave pip running or a timer pointing at
    code that is gone."""
    cancel(wait=UNREGISTER_WAIT)


def _timer() -> float | None:
    if _current is None:
        return None
    try:
        delay = _current.tick()
    except Exception:
        log.exception("agent environment setup failed")
        _current.cancel()
        return None
    _redraw()
    return delay


def _start_timer() -> None:
    if not bpy.app.timers.is_registered(_timer):
        # Persistent, so opening a file mid-install does not orphan pip.
        bpy.app.timers.register(_timer, first_interval=0.1, persistent=True)


def _stop_timer() -> None:
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)


def timer_registered() -> bool:
    return bpy.app.timers.is_registered(_timer)


def _redraw() -> None:
    wm = bpy.context.window_manager
    for window in (wm.windows if wm is not None else ()):
        for area in window.screen.areas:
            area.tag_redraw()


STATUS_TEXT = {
    VenvStatus.MISSING: ("Not set up yet", "ERROR"),
    VenvStatus.READY: ("Ready", "CHECKMARK"),
    VenvStatus.STALE: ("Set up for an earlier version of Whittle: reinstall", "ERROR"),
    VenvStatus.BROKEN: ("Incomplete or its Python is gone: reinstall", "ERROR"),
    VenvStatus.FOREIGN: ("The folder holds something Whittle did not make", "ERROR"),
}


def describe() -> tuple[str, str]:
    """(status text, icon) for the preferences and the sidebar."""
    running = _current
    if running is not None and running.running:
        return f"Setting up: {running.describe_progress()}…", "SORTTIME"
    if running is not None and running.state in ("failed", "cancelled") and not running.dry_run:
        return f"Setup {running.state}: {running.reason}", "CANCEL"
    folder = venv_dir()
    state = venv.status(folder, lock_path())
    text, icon = STATUS_TEXT[state]
    if state == VenvStatus.READY:
        marker = venv.read_marker(folder) or {}
        text = f"Ready: {venv.SDK} {marker.get('sdk')}"
    override = paths.agent_python()
    if override is not None and state != VenvStatus.READY:
        text += f" (the agent uses {override})"
    return text, icon


def install_summary() -> str:
    pins = venv.read_pins(lock_path())
    return (f"Download {len(pins)} pinned packages incl. {venv.SDK} {pins.get(venv.SDK)} "
            f"from PyPI into {venv_dir()}")


class WHITTLE_OT_venv_install(bpy.types.Operator):
    bl_idname = "whittle.venv_install"
    bl_label = "Set Up Agent Environment"
    bl_description = ("Make the agent's private Python environment and install its exactly pinned, "
                      "hash-checked packages from PyPI")

    reinstall: BoolProperty(name="Reinstall", default=False, options={"SKIP_SAVE"},
                            description="Rebuild the environment from scratch")
    dry_run: BoolProperty(name="Dry Run", default=False, options={"HIDDEN", "SKIP_SAVE"},
                          description="Only log the commands")

    @classmethod
    def description(cls, context, properties):
        if properties.reinstall:
            return "Rebuild the agent's environment from scratch from the pinned lock"
        return cls.bl_description

    @classmethod
    def poll(cls, context):
        # Properties cannot be read here; begin() refuses a real install in
        # background Blender.
        return not _turn_busy() and not (_current is not None and _current.running)

    def invoke(self, context, event):
        if self.dry_run:
            return self.execute(context)
        title = "Reinstall Agent Environment" if self.reinstall else "Set Up Agent Environment"
        return context.window_manager.invoke_confirm(
            self, event, title=title, message=install_summary(),
            confirm_text="Download and Install", icon="WARNING")

    def execute(self, context):
        try:
            setup = begin(reinstall=self.reinstall, dry_run=self.dry_run)
        except (RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if setup.state == "failed":
            self.report({"ERROR"}, setup.reason or "setup failed")
            return {"CANCELLED"}
        self.report({"INFO"}, "Dry run logged to " + str(setup.log_path) if setup.dry_run
                    else "Setting up the agent environment")
        return {"FINISHED"}


class WHITTLE_OT_venv_cancel(bpy.types.Operator):
    bl_idname = "whittle.venv_cancel"
    bl_label = "Cancel Setup"
    bl_description = "Stop setting up the agent environment"

    @classmethod
    def poll(cls, context):
        return _current is not None and _current.running

    def execute(self, context):
        cancel()
        return {"FINISHED"}


CLASSES = (WHITTLE_OT_venv_install, WHITTLE_OT_venv_cancel)
