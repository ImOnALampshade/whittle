# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent's private Python environment: the commands that build it from
the pinned lock, and a small state machine that runs them as subprocesses.

Stdlib only, so the add-on and the agent-side tests share it. Nothing here
runs on import, and nothing ever upgrades: a venv made from another lock is
reported as stale and only rebuilt when the user asks.
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from . import platforms

LOCK_NAME = "requirements.lock"
# Written last, after the install was verified; its absence means the
# folder is not (or not yet) a working Whittle venv.
MARKER = "whittle-venv.json"
MARKER_FORMAT = "whittle.venv"
SDK = "claude-agent-sdk"
# Hard caps per step. The install is mostly downloading (the SDK wheel alone
# is over 100 MB), so its cap is generous and it is really bounded by STALL:
# a slow link that keeps making progress is never cut off, a dead one is.
STEP_TIMEOUTS = {"create": 120.0, "install": 3 * 3600.0, "verify": 60.0}
STALL_TIMEOUTS = {"install": 300.0}
PROGRESS_PREFIX = "Progress "
TAIL_BYTES = 64 * 1024
KILL_AFTER = 2.0
TICK = 0.25
# Settings that could point pip at another index or change which Python
# and site-packages the steps use. Everything else (PATH, HOME, proxies,
# SSL_CERT_*) is kept so downloads work behind a proxy.
DROPPED_ENV_PREFIXES = ("PIP_", "PYTHON", "UV_", "VIRTUAL_ENV", "CONDA_")
VERIFY_PREFIX = "whittle-verify:"
# Imports the SDK (and so its whole dependency tree) and checks that the
# wheel brought its bundled Claude Code CLI along, under the name the SDK
# looks for (bundled_cli_name).
VERIFY_SCRIPT = (
    "import importlib.metadata, json, pathlib, sys, claude_agent_sdk; "
    "cli = pathlib.Path(claude_agent_sdk.__file__).parent / '_bundled' / "
    "('claude.exe' if sys.platform == 'win32' else 'claude'); "
    f"print({VERIFY_PREFIX!r} + json.dumps({{'sdk': importlib.metadata.version({SDK!r}), "
    "'cli': cli.is_file()}), flush=True)"
)

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")
_HASH = re.compile(r"--hash=(sha256:[0-9a-f]{64})")


class VenvStatus(StrEnum):
    MISSING = "missing"    # no folder, or an empty one
    READY = "ready"        # verified install from this exact lock
    STALE = "stale"        # installed from another lock; reinstall, never automatic
    BROKEN = "broken"      # ours, but unfinished or its Python is gone
    FOREIGN = "foreign"    # a folder Whittle did not make


@dataclass(frozen=True)
class Step:
    name: str
    argv: list[str]
    timeout: float
    # Seconds the step may go without writing to the log before it counts
    # as stuck; None means only the hard timeout applies.
    stall: float | None = None


# -- the lock -------------------------------------------------------------------

def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(lock: Path) -> dict[str, str]:
    """Package name -> pinned version, in lock order."""
    pins = {}
    for line in Path(lock).read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line)
        if match:
            pins[_normalise(match.group(1))] = match.group(2)
    return pins


def lock_hashes(lock: Path) -> dict[str, list[str]]:
    """Package name -> the hashes its pin allows."""
    hashes: dict[str, list[str]] = {}
    current = None
    for line in Path(lock).read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line)
        if match:
            current = _normalise(match.group(1))
            hashes[current] = []
        elif line.lstrip().startswith("#") or not line.strip():
            continue
        if current is not None:
            hashes[current] += _HASH.findall(line)
    return hashes


def lock_digest(lock: Path) -> str:
    return hashlib.sha256(Path(lock).read_bytes()).hexdigest()


# (OS, machine) pairs the lock has a wheel of every pin for, by the names
# sys.platform and platform.machine() use. The lock was compiled on Linux,
# but its hashes cover every file of each pin, so Windows x64 and Apple
# silicon install from it too. Intel Macs are left out: cryptography 50 has
# no x86_64 macOS wheel (and Blender 5.2 no Intel build). Windows on Arm is
# left out: the SDK has no win_arm64 wheel.
SUPPORTED = {"linux": ("x86_64", "amd64"), "win32": ("amd64", "x86_64"), "darwin": ("arm64", "aarch64")}
SUPPORTED_TEXT = "Linux x64, Windows x64 and macOS on Apple silicon"
_OS_NAMES = {"linux": "Linux", "win32": "Windows", "darwin": "macOS"}


def compatible(version_info, machine: str, platform: str) -> str | None:
    """Why this interpreter cannot use the lock, or None. The lock holds
    CPython 3.14 wheels for the platforms in SUPPORTED."""
    if tuple(version_info[:2]) != (3, 14):
        return f"the agent environment needs Python 3.14, but Blender runs {version_info[0]}.{version_info[1]}"
    system = "linux" if platform.startswith("linux") else platform
    if system not in SUPPORTED:
        return f"the agent environment is available on {SUPPORTED_TEXT}, not {platform}"
    if machine.lower() in SUPPORTED[system]:
        return None
    if system == "darwin":
        return (f"the agent environment needs a Mac with Apple silicon, not {machine}: one of its "
                "packages (cryptography) has no Intel Mac build")
    return (f"the agent environment is available on {SUPPORTED_TEXT}, not {_OS_NAMES[system]} "
            f"on {machine}")


def bundled_cli_name(platform: str = sys.platform) -> str:
    """The Claude Code CLI's file name in the SDK's _bundled folder."""
    return "claude.exe" if platforms.is_windows(platform) else "claude"


# -- commands -------------------------------------------------------------------

def venv_python(venv: Path, platform: str = sys.platform) -> Path:
    venv = Path(venv)
    if platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def create_command(base_python: Path, venv: Path, *, clear: bool = False) -> list[str]:
    argv = [str(base_python), "-I", "-m", "venv"]
    if clear:
        argv.append("--clear")
    return [*argv, str(venv)]


def install_command(python: Path, lock: Path) -> list[str]:
    # --no-deps with --require-hashes means exactly the lock's pins are
    # installed, from wheels only, so no package's build code ever runs.
    # -u and a raw progress bar make pip report each downloaded chunk to the
    # log as it arrives, which is what the stall check watches.
    return [str(python), "-I", "-u", "-m", "pip", "install", "--isolated", "--disable-pip-version-check",
            "--no-input", "--progress-bar", "raw", "--require-hashes", "--only-binary", ":all:",
            "--no-deps", "-r", str(lock)]


def verify_command(python: Path) -> list[str]:
    return [str(python), "-I", "-c", VERIFY_SCRIPT]


def subprocess_env(environ) -> dict[str, str]:
    return {key: value for key, value in environ.items()
            if not key.upper().startswith(DROPPED_ENV_PREFIXES)}


def plan(base_python: Path, venv: Path, lock: Path, *, reinstall: bool = False) -> list[Step]:
    python = venv_python(venv)
    return [Step("create", create_command(base_python, venv, clear=reinstall), STEP_TIMEOUTS["create"]),
            Step("install", install_command(python, lock), STEP_TIMEOUTS["install"],
                 STALL_TIMEOUTS["install"]),
            Step("verify", verify_command(python), STEP_TIMEOUTS["verify"])]


# -- the marker -----------------------------------------------------------------

def read_marker(venv: Path) -> dict | None:
    try:
        data = json.loads((Path(venv) / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def base_home(venv: Path) -> Path | None:
    """The folder of the Python the venv was made from, as its pyvenv.cfg
    records it; None when it records none."""
    try:
        text = (Path(venv) / "pyvenv.cfg").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "home" and value.strip():
            return Path(value.strip())
    return None


def status(venv: Path, lock: Path, platform: str = sys.platform) -> VenvStatus:
    venv = Path(venv)
    if not venv.is_dir() or not any(venv.iterdir()):
        return VenvStatus.MISSING
    if not (venv / MARKER).exists():
        return VenvStatus.FOREIGN
    marker = read_marker(venv)
    if marker is None or marker.get("format") != MARKER_FORMAT or not marker.get("complete"):
        return VenvStatus.BROKEN
    python = venv_python(venv, platform)
    # A venv's python is a symlink to the interpreter it was made from; if
    # that Python was removed or upgraded away, the link dangles.
    if not python.is_file() or not os.access(python, os.X_OK):
        return VenvStatus.BROKEN
    # On Windows it is a copied launcher that stays behind, so the base
    # Python's folder recorded in pyvenv.cfg is what tells.
    if platforms.is_windows(platform):
        home = base_home(venv)
        if home is not None and not home.is_dir():
            return VenvStatus.BROKEN
    if marker.get("lock_sha256") != lock_digest(lock):
        return VenvStatus.STALE
    return VenvStatus.READY


def write_marker(venv: Path, lock: Path, *, sdk: str | None, base_python: Path,
                 complete: bool = True) -> None:
    """Atomically. complete=False claims a folder whose setup has started, so
    a cancelled or failed setup is BROKEN (ours to rebuild), not FOREIGN."""
    venv = Path(venv)
    data = {"format": MARKER_FORMAT, "version": 1, "complete": complete,
            "lock_sha256": lock_digest(lock), "sdk": sdk, "base_python": str(base_python),
            "written": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    tmp = venv / f".{MARKER}.tmp"
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    platforms.replace(tmp, venv / MARKER)


# -- running the steps ------------------------------------------------------------

class VenvSetup:
    """Runs the steps one after another as subprocesses, polled by tick()
    (a Blender timer in the GUI, the tests by hand). Output goes to a log
    file, never a pipe, so a chatty pip can never block on a full buffer."""

    def __init__(self, steps: list[Step], *, venv: Path, lock: Path, log_path: Path,
                 dry_run: bool = False, popen=subprocess.Popen, clock=time.monotonic,
                 env=None, base_python: Path | None = None, on_finish=None,
                 platform: str = sys.platform):
        self.steps = list(steps)
        self.venv = Path(venv)
        self.lock = Path(lock)
        self.log_path = Path(log_path)
        self.dry_run = dry_run
        self.base_python = Path(base_python) if base_python else Path(sys.executable)
        self.on_finish = on_finish
        self._popen = popen
        self._clock = clock
        self._env = subprocess_env(os.environ if env is None else env)
        self._platform = platform
        self.state = "idle"
        self.step: str | None = None
        self.reason: str | None = None
        self.sdk: str | None = None
        self._index = -1
        self._proc = None
        self._log = None
        self._deadline = 0.0
        self._log_size = 0
        self._last_output = 0.0
        self._terminated_at: float | None = None
        self._timeout_reason = ""

    @property
    def running(self) -> bool:
        return self.state == "running"

    def start(self) -> None:
        if self.state != "idle":
            raise RuntimeError(f"setup already {self.state}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "ab")
        self._write(f"Whittle agent environment: {self.venv}\nlock: {self.lock} "
                    f"(sha256 {lock_digest(self.lock)})\n")
        if self.dry_run:
            for step in self.steps:
                self._write(f"$ {shlex.join(step.argv)}\n")
            self._write("dry run: nothing was run\n")
            self._end("done")
            return
        self.state = "running"
        if not self.venv.exists():
            # venv accepts a folder that exists; claiming it first means a
            # setup cancelled during create leaves a folder Whittle owns.
            self.venv.mkdir(parents=True)
            self._claim()
        self._next()

    def tick(self) -> float | None:
        if self.state != "running" or self._proc is None:
            return None
        code = self._proc.poll()
        now = self._clock()
        if code is None:
            if self._terminated_at is None:
                why = self._overdue(now)
                if why is not None:
                    self._write(f"{why}\n")
                    self._timeout_reason = why
                    self._proc.terminate()
                    self._terminated_at = now
            elif now >= self._terminated_at + KILL_AFTER:
                self._proc.kill()
                self._fail(self._timeout_reason)
                return None
            return TICK
        if self._terminated_at is not None:
            self._fail(self._timeout_reason)
            return None
        if code != 0:
            tail = " | ".join(self.log_tail(5))
            self._fail(f"{self.step} failed with exit code {code}: {tail}")
            return None
        if self.step == "verify" and not self._verified():
            return None
        if self.step == "create":
            self._claim()
        if self._index + 1 < len(self.steps):
            self._next()
            return TICK
        write_marker(self.venv, self.lock, sdk=self.sdk, base_python=self.base_python)
        self._write("done\n")
        self._end("done")
        return None

    def cancel(self, wait: float = 0.0) -> None:
        """Stops the running step. With wait, gives it that long to exit
        before killing it (unregistering cannot leave pip running)."""
        if self.state != "running":
            return
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            if wait > 0:
                try:
                    proc.wait(timeout=wait)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._write(f"cancelled during {self.step}\n")
        self._claim()
        self.reason = f"cancelled during {self.step}"
        self._end("cancelled")

    def log_tail(self, n: int = 20) -> list[str]:
        """The last n log lines, without pip's per-chunk progress lines
        (progress() summarises those)."""
        lines = [line for line in self._tail_lines() if not line.startswith(PROGRESS_PREFIX)]
        return lines[-n:]

    def progress(self) -> tuple[str, int, int] | None:
        """(file, bytes so far, total bytes) of the download in progress
        during install, or None."""
        if self.step != "install":
            return None
        last = None
        for line in reversed(self._tail_lines()):
            if line.startswith(PROGRESS_PREFIX):
                if last is None:
                    last = line.split()
                continue
            # The first other line above the progress lines says what is
            # downloading; anything else means the last download finished.
            if last is None or not line.lstrip().startswith("Downloading "):
                return None
            # "Progress <done> of <total>"
            if len(last) != 4 or not (last[1].isdigit() and last[3].isdigit()):
                return None
            return line.split()[1], int(last[1]), int(last[3])
        return None

    def describe_progress(self) -> str:
        """A short status for the UI, e.g. "install: claude_agent_sdk…whl 43.1 / 114.1 MB"."""
        found = self.progress()
        if found is None:
            return self.step or ""
        name, done, total = found
        return f"{self.step}: {name} {done / 1e6:.1f} / {total / 1e6:.1f} MB"

    # -- internals ----------------------------------------------------------------

    def _tail_lines(self) -> list[str]:
        # Only the end of the log: pip's progress lines make it long.
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - TAIL_BYTES))
                data = f.read()
        except OSError:
            return []
        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[1:] if size > TAIL_BYTES else lines

    def _overdue(self, now: float) -> str | None:
        step = self.steps[self._index]
        if now >= self._deadline:
            return f"{step.name} timed out after {step.timeout:g} s"
        if step.stall is None:
            return None
        try:
            size = os.fstat(self._log.fileno()).st_size
        except (OSError, AttributeError, ValueError):
            return None
        if size != self._log_size:
            self._log_size, self._last_output = size, now
            return None
        if now >= self._last_output + step.stall:
            return f"{step.name} stalled: no progress for {step.stall:g} s"
        return None

    def _next(self) -> None:
        self._index += 1
        step = self.steps[self._index]
        self.step = step.name
        self._terminated_at = None
        self._timeout_reason = f"timed out in {step.name}"
        self._write(f"$ {shlex.join(step.argv)}\n")
        try:
            # Each step is a single process (pip downloads in-process), so
            # terminate() and kill() reach all of it on every platform.
            self._proc = self._popen(step.argv, stdin=subprocess.DEVNULL, stdout=self._log,
                                     stderr=subprocess.STDOUT, env=self._env,
                                     **platforms.hidden_window(self._platform))
        except OSError as exc:
            self._proc = None
            self._fail(f"cannot run {step.name}: {exc}")
            return
        self._deadline = self._clock() + step.timeout
        self._last_output = self._clock()
        try:
            self._log_size = os.fstat(self._log.fileno()).st_size
        except (OSError, AttributeError, ValueError):
            self._log_size = 0

    def _verified(self) -> bool:
        found = None
        for line in self.log_tail(50):
            if line.startswith(VERIFY_PREFIX):
                try:
                    found = json.loads(line[len(VERIFY_PREFIX):])
                except ValueError:
                    found = None
        expected = read_pins(self.lock).get(SDK)
        if not isinstance(found, dict):
            self._fail("verify printed no result")
            return False
        if found.get("sdk") != expected:
            self._fail(f"verify found {SDK} {found.get('sdk')}, expected {expected}")
            return False
        if found.get("cli") is not True:
            self._fail(f"{SDK} is installed without its bundled Claude Code CLI")
            return False
        self.sdk = found["sdk"]
        return True

    def _claim(self) -> None:
        # Marks a folder this setup made or rebuilt as ours, unfinished.
        if self.dry_run or not self.venv.is_dir():
            return
        marker = read_marker(self.venv)
        if marker is not None and marker.get("complete") is False:
            return
        try:
            write_marker(self.venv, self.lock, sdk=None, base_python=self.base_python, complete=False)
        except OSError as exc:
            self._write(f"could not mark {self.venv}: {exc}\n")

    def _fail(self, reason: str) -> None:
        self.reason = reason
        self._write(f"failed: {reason}\n")
        self._claim()
        self._end("failed")

    def _end(self, state: str) -> None:
        self.state = state
        self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None
        if self.on_finish is not None:
            self.on_finish(self)

    def _write(self, text: str) -> None:
        if self._log is not None:
            self._log.write(text.encode("utf-8"))
            self._log.flush()
