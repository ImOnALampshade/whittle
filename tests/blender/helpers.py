# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers for Blender-side tests. Timers never fire under
`blender -b --python`, so tests drive the bridge themselves with pump()."""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
CRATE_BUNDLE = FIXTURES / "crate" / "request"
FAKE_SCRIPTS = FIXTURES / "fake"
VENV_PYTHON = REPO / ".venv" / "bin" / "python"


def agent_python() -> Path:
    return Path(os.environ.get("WHITTLE_AGENT_PYTHON") or VENV_PYTHON)


def pump(controller_or_bridge, until, timeout: float = 10.0, what: str = "condition"):
    """Ticks the bridge until `until()` is true; fails the test on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        if until():
            return
        bridge = getattr(controller_or_bridge, "bridge", controller_or_bridge)
        if bridge is not None:
            bridge.tick()
        if until():
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout:g} s waiting for {what}")
        time.sleep(0.01)


class TempUserDir:
    """Points WHITTLE_USER_DIR at a fresh temp folder for one test."""

    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix="whittle-test-"))
        self._old = os.environ.get("WHITTLE_USER_DIR")
        os.environ["WHITTLE_USER_DIR"] = str(self.path)
        return self.path

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("WHITTLE_USER_DIR", None)
        else:
            os.environ["WHITTLE_USER_DIR"] = self._old
        shutil.rmtree(self.path, ignore_errors=True)


class AgentTestCase(unittest.TestCase):
    """Gives each test a temp user dir and session folder, and makes sure any
    agent process it started is gone afterwards."""

    def setUp(self):
        self._user = TempUserDir()
        self.user_dir = self._user.__enter__()
        self.session_dir = self.user_dir / "session"
        self.controllers = []

    def tearDown(self):
        for ctl in self.controllers:
            proc = ctl.process
            if proc.popen is not None and proc.popen.poll() is None:
                proc.popen.kill()
                proc.popen.wait(timeout=5)
            if proc.bridge is not None:
                proc.bridge.close()
        from whittle.addon import chats

        # The chats of one test's file are not the next one's, nor its id.
        chats.reset()
        import bpy

        holder = bpy.data.texts.get(chats.HOLDER)
        if holder is not None:
            bpy.data.texts.remove(holder)
        self._user.__exit__(None, None, None)

    def make_controller(self, script: str | Path | None = "ping.json", **kwargs):
        from whittle.addon.turn import TurnController

        fake = None
        if script is not None:
            fake = Path(script) if Path(script).is_absolute() else FAKE_SCRIPTS / script
        kwargs.setdefault("python", agent_python())
        ctl = TurnController(self.session_dir, fake_script=fake, use_timer=False, **kwargs)
        self.controllers.append(ctl)
        return ctl

    def start_ready(self, ctl, timeout: float = 15.0):
        from whittle.addon.process import AgentState

        ctl.start()
        pump(ctl, lambda: ctl.process.state != AgentState.STARTING, timeout, "the handshake")
        self.assertEqual(ctl.process.state, AgentState.READY, ctl.process.reason)
