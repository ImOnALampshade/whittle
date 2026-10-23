# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent process: spawn, handshake, crash detection and shutdown."""

import logging
import os
import secrets
import signal
import socket
import subprocess
import time
from collections import deque
from enum import StrEnum
from pathlib import Path

import bpy

from ..protocol import ErrorCode, Method
from . import paths, prefs
from .bridge import Bridge, start_timer, stop_timer

log = logging.getLogger("whittle")

HANDSHAKE_TIMEOUT = 30.0
# After shutdown the agent closes its SDK session, which can take a while
# (agent/__main__.py gives it 15 s): it is terminated only after that, and
# killed after another grace. A terminate makes it close the same way.
TERMINATE_AFTER = 20.0
# Quitting or loading a file waits here, blocking Blender: a shorter wait.
WAIT_TERMINATE_AFTER = 10.0
KILL_AFTER = 5.0
EXIT_GRACE = 1.0
KEEP_LOGS = 10
NO_KEY = "Add an Anthropic API key in Preferences to run Claude"

# Every other way the bundled CLI could sign in (a claude.ai subscription
# token, a bearer token, a cloud provider, a key helper) is cut off: Whittle
# runs Claude on the user's API key only, which is what Anthropic's terms ask
# of a product built on the Agent SDK. So the agent's environment keeps no
# variable of these prefixes but the ones in KEPT (a gateway's address, and
# the user's opt-out of the CLI's non-essential traffic), and
# CLAUDE_CONFIG_DIR points at Whittle's own folder, where the CLI finds no
# login, settings, hooks or MCP servers of the user's. The CLI's own usage
# telemetry and error reports are off unless the user turns them on
# (the "Send Claude Code usage data" preference).
STRIPPED_PREFIXES = ("ANTHROPIC_", "CLAUDE")
NONESSENTIAL = "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
KEPT = {"ANTHROPIC_BASE_URL", NONESSENTIAL}


class AgentState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    STOPPING = "stopping"
    CRASHED = "crashed"
    FAILED = "failed"
    NEEDS_SETUP = "needs_setup"
    NEEDS_KEY = "needs_key"


LIVE_STATES = (AgentState.STARTING, AgentState.READY, AgentState.BUSY, AgentState.STOPPING)


class AgentProcess:
    def __init__(self, *, handlers: dict, on_event, fake_script: Path | None = None,
                 python: Path | None = None, agent_token: str | None = None,
                 use_timer: bool = True):
        self.handlers = handlers
        self.on_event = on_event
        self.fake_script = Path(fake_script) if fake_script else None
        self.python = Path(python) if python else None
        # Lets tests hand the agent a token that differs from the one Blender expects.
        self._agent_token = agent_token
        self.use_timer = use_timer
        self.state = AgentState.STOPPED
        self.reason: str | None = None
        self.bridge: Bridge | None = None
        self.popen: subprocess.Popen | None = None
        self.log_path: Path | None = None
        self.hello: dict | None = None
        self.exit_code: int | None = None
        self.state_listeners: list = []
        self._deadline = 0.0
        self._stop_started = 0.0
        self._terminated = False
        self._log_file = None

    @property
    def is_fake(self) -> bool:
        return self.fake_script is not None

    @property
    def alive(self) -> bool:
        return self.state in LIVE_STATES

    # -- lifecycle ------------------------------------------------------------

    def start(self, session_dir: Path) -> None:
        if self.alive:
            raise RuntimeError(f"agent is already {self.state}")
        self.reason = None
        self.hello = None
        self.exit_code = None
        python = self.python or paths.agent_python()
        if python is None:
            self._set_state(AgentState.NEEDS_SETUP, paths.agent_python_problem()
                            or "The agent environment is not set up yet")
            return
        api_key, _source = prefs.api_key()
        if not self.is_fake and not api_key:
            self._set_state(AgentState.NEEDS_KEY, NO_KEY)
            return
        if not self.is_fake and not bpy.app.online_access:
            self._set_state(AgentState.FAILED,
                            "Allow Online Access in Preferences > System to run the agent")
            return

        session_dir = Path(session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        listener = socket.create_server(("127.0.0.1", 0), backlog=1)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        token = secrets.token_hex(32)

        env = agent_environment(os.environ, api_key=api_key, config_dir=paths.claude_config_dir(),
                                usage_data=prefs.get().usage_data)
        env["PYTHONPATH"] = str(paths.package_parent())
        env["WHITTLE_TOKEN"] = self._agent_token or token
        argv = [str(python), "-s", "-P", "-m", paths.agent_module(), "--port", str(port)]
        if self.fake_script:
            argv += ["--fake", str(self.fake_script)]

        self.log_path = paths.logs_dir() / f"agent-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{port}.log"
        _prune_logs(self.log_path.parent)
        self._log_file = open(self.log_path, "ab")
        try:
            # Its own process group, so terminating or killing it reaches the
            # Claude Code CLI it runs too.
            self.popen = subprocess.Popen(argv, cwd=session_dir, env=env, stdin=subprocess.DEVNULL,
                                          stdout=self._log_file, stderr=subprocess.STDOUT,
                                          start_new_session=True)
        except OSError as exc:
            listener.close()
            self._close_log()
            self._set_state(AgentState.FAILED, f"cannot start the agent: {exc}")
            return
        self.bridge = Bridge(self, listener, token, self.handlers, self.on_event)
        self._deadline = time.monotonic() + HANDSHAKE_TIMEOUT
        self._terminated = False
        self._set_state(AgentState.STARTING)
        if self.use_timer:
            start_timer(self.bridge)

    def clear_key(self) -> None:
        """A key was just added: the next start can use it."""
        if self.state == AgentState.NEEDS_KEY:
            self.reason = None
            self._set_state(AgentState.STOPPED)

    def clear_setup(self) -> None:
        """The agent environment was just set up: the next start can find it."""
        if self.state == AgentState.NEEDS_SETUP:
            self.reason = None
            self._set_state(AgentState.STOPPED)

    def stop(self, *, wait: bool = False) -> None:
        """Asks the agent to exit; ticks escalate to terminate and kill. With
        wait=True (quit, file load, unregister) the escalation runs here, since
        no more ticks will come."""
        if self.popen is None:
            self._finish(AgentState.STOPPED)
            return
        if self.state != AgentState.STOPPING:
            if self.bridge is not None and self.bridge.handshaken and self.bridge.sock is not None:
                self.bridge.call(Method.SHUTDOWN, {})
                self.bridge.flush()
            self._stop_started = time.monotonic()
            self._set_state(AgentState.STOPPING)
        if wait:
            self._wait_exit()

    def poll(self) -> None:
        """Called from every bridge tick."""
        if self.popen is None:
            return
        code = self.popen.poll()
        now = time.monotonic()
        if self.state == AgentState.STOPPING:
            if code is not None:
                self.exit_code = code
                self._finish(AgentState.STOPPED)
            elif not self._terminated and now - self._stop_started > TERMINATE_AFTER:
                self._signal(signal.SIGTERM)
                self._terminated = True
            elif now - self._stop_started > TERMINATE_AFTER + KILL_AFTER:
                self._signal(signal.SIGKILL)
            return
        if code is not None and self.alive:
            self.exit_code = code
            if self.state == AgentState.STARTING:
                self.fail(f"the agent exited with code {code} before the handshake")
            else:
                self.crash(f"the agent exited with code {code}")
            return
        if self.state == AgentState.STARTING and now > self._deadline:
            self.fail("the agent did not complete the handshake in time")

    def tick_interval(self) -> float | None:
        return {
            AgentState.STARTING: 0.05,
            AgentState.READY: 0.2,
            AgentState.BUSY: 0.05,
            AgentState.STOPPING: 0.1,
        }.get(self.state)

    # -- bridge callbacks -----------------------------------------------------

    def on_handshake(self, hello: dict) -> None:
        self.hello = hello
        if self.state == AgentState.STOPPING:
            # stop() came before the agent said hello, so the shutdown it would
            # have sent goes out now.
            self.bridge.call(Method.SHUTDOWN, {})
            self.bridge.flush()
            return
        self._set_state(AgentState.READY)

    def on_disconnect(self, reason: str) -> None:
        if self.state == AgentState.STOPPING:
            return
        # EOF usually means the process is exiting; its exit code says more.
        if self.popen is not None:
            try:
                self.exit_code = self.popen.wait(timeout=EXIT_GRACE)
                reason = f"the agent exited with code {self.exit_code}"
            except subprocess.TimeoutExpired:
                pass
        if self.state == AgentState.STARTING:
            self.fail(f"handshake failed: {reason}")
        elif self.alive:
            self.crash(reason)

    def set_busy(self, busy: bool) -> None:
        if self.state in (AgentState.READY, AgentState.BUSY):
            self._set_state(AgentState.BUSY if busy else AgentState.READY)

    def fail(self, reason: str) -> None:
        self._kill()
        self._finish(AgentState.FAILED, reason)

    def crash(self, reason: str) -> None:
        self._kill()
        self._finish(AgentState.CRASHED, reason)

    def log_tail(self, n: int = 20) -> list[str]:
        if self.log_path is None or not self.log_path.is_file():
            return []
        with open(self.log_path, encoding="utf-8", errors="replace") as f:
            return [line.rstrip("\n") for line in deque(f, maxlen=n)]

    # -- internals ------------------------------------------------------------

    def _wait_exit(self) -> None:
        deadline = time.monotonic() + WAIT_TERMINATE_AFTER
        while self.popen is not None and time.monotonic() < deadline:
            if self.bridge is not None and not self.bridge.closed:
                self.bridge.flush()
            try:
                self.exit_code = self.popen.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                pass
        if self.popen is not None and self.popen.poll() is None:
            self._signal(signal.SIGTERM)
            try:
                self.exit_code = self.popen.wait(timeout=KILL_AFTER)
            except subprocess.TimeoutExpired:
                self._signal(signal.SIGKILL)
                self.exit_code = self.popen.wait(timeout=KILL_AFTER)
        self._finish(AgentState.STOPPED)

    def _signal(self, sig) -> None:
        """Signals the agent's whole process group: the CLI it runs, which
        may be in the middle of an API request, goes with it."""
        try:
            os.killpg(self.popen.pid, sig)
        except (AttributeError, ProcessLookupError, PermissionError):
            self.popen.send_signal(sig)

    def _kill(self) -> None:
        if self.popen is not None and self.popen.poll() is None:
            self._signal(signal.SIGKILL)
            try:
                self.exit_code = self.popen.wait(timeout=KILL_AFTER)
            except subprocess.TimeoutExpired:
                log.error("agent process %d did not die", self.popen.pid)

    def _finish(self, state: AgentState, reason: str | None = None) -> None:
        bridge = self.bridge
        if bridge is not None:
            bridge.fail_pending(ErrorCode.AGENT_CRASHED, reason or f"the agent is {state}")
            bridge.close()
            if self.use_timer:
                stop_timer()
        self.bridge = None
        if self.popen is not None and self.popen.poll() is not None:
            self.exit_code = self.popen.returncode
            self.popen = None
        self._close_log()
        self._set_state(state, reason)

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def _set_state(self, state: AgentState, reason: str | None = None) -> None:
        self.state = state
        if reason is not None:
            self.reason = reason
            log.info("agent %s: %s", state, reason)
        for listener in list(self.state_listeners):
            listener(state, reason)


def agent_environment(base, *, api_key: str, config_dir: Path, usage_data: bool = False) -> dict:
    """The agent's environment: Blender's, without any Anthropic or Claude
    variable (see STRIPPED_PREFIXES), plus the API key and Whittle's private
    CLI configuration folder. Without usage_data the CLI sends nothing but
    the turns (no telemetry or error reports); with it, Blender's own
    setting, if any, stands. The fake agent gets the same, key or not."""
    env = {k: v for k, v in base.items() if k in KEPT or not k.upper().startswith(STRIPPED_PREFIXES)}
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    if not usage_data:
        env[NONESSENTIAL] = "1"
    return env


def _prune_logs(folder: Path) -> None:
    logs = sorted(folder.glob("agent-*.log"), key=lambda p: p.stat().st_mtime)
    for old in logs[:-(KEEP_LOGS - 1)]:
        try:
            old.unlink()
        except OSError:
            pass
