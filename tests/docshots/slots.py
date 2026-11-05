# SPDX-License-Identifier: GPL-3.0-or-later
"""The machine-wide limit on Blenders the docs' screenshot tool runs at once:
flock on slot files, so a process that dies gives its slot back by itself.
Stdlib only."""

import contextlib
import fcntl
import os
import random
import time
from pathlib import Path

# A GUI Blender with a nested compositor keeps a few cores busy.
MAX_DEFAULT = 4
CORES_PER_SLOT = 4
SIZE_VARIABLE = "WHITTLE_DOCSHOTS_SLOTS"
WAIT_VARIABLE = "WHITTLE_DOCSHOTS_SLOT_WAIT"
# How long a Blender waits for a slot: long enough for every page's writer to
# queue behind the others.
DEFAULT_WAIT = 3600.0
POLL = 0.25


class SlotTimeout(TimeoutError):
    """No slot came free before the deadline."""


def default_size(cpus: int | None = None) -> int:
    """A slot per CORES_PER_SLOT cores, at least 1 and at most MAX_DEFAULT."""
    return max(1, min(MAX_DEFAULT, (cpus or os.cpu_count() or 1) // CORES_PER_SLOT))


def size(env=os.environ) -> int:
    """How many Blenders may run at once: the variable, else the default."""
    value = env.get(SIZE_VARIABLE, "").strip()
    if not value:
        return default_size()
    try:
        count = int(value)
    except ValueError:
        count = 0
    if count < 1:
        raise ValueError(f"{SIZE_VARIABLE} must be a whole number of at least 1, not {value!r}")
    return count


def wait_limit(env=os.environ) -> float:
    value = env.get(WAIT_VARIABLE, "").strip()
    return float(value) if value else DEFAULT_WAIT


def try_lock(path: Path) -> int | None:
    """An open file descriptor holding path's lock, or None when it is held.
    The descriptor is not inherited, so no child keeps a slot alive."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _wait_for(attempt, what: str, wait: float, stopped, waiting):
    """Calls attempt until it gives a descriptor, polling with a little
    jitter so waiters do not move in step."""
    started = time.monotonic()
    told = started
    while True:
        fd = attempt()
        if fd is not None:
            return fd
        now = time.monotonic()
        if stopped is not None and stopped():
            raise SlotTimeout(f"stopped while waiting for {what}")
        if now - started >= wait:
            raise SlotTimeout(f"no {what} came free in {wait:g} s")
        if waiting is not None and now >= told:
            waiting(now - started)
            told = now + 60.0
        time.sleep(min(POLL * (0.5 + random.random()), max(0.0, started + wait - now)))


@contextlib.contextmanager
def slot(folder: Path, count: int, wait: float = DEFAULT_WAIT, stopped=None, waiting=None):
    """Holds one of count slots in folder, blocking at most wait seconds
    (SlotTimeout after that). Yields the slot's number. waiting(seconds) is
    called when it has to wait, then once a minute."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    taken = {}

    def attempt():
        # From a random slot, so waiters do not all fight over the first.
        start = random.randrange(count)
        for k in range(count):
            number = (start + k) % count
            fd = try_lock(folder / f"slot-{number}.lock")
            if fd is not None:
                taken["number"] = number
                return fd
        return None

    fd = _wait_for(attempt, "slot", wait, stopped, waiting)
    try:
        yield taken["number"]
    finally:
        os.close(fd)


@contextlib.contextmanager
def exclusive(path: Path, wait: float = DEFAULT_WAIT, stopped=None, waiting=None):
    """Holds the lock file at path, blocking at most wait seconds."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = _wait_for(lambda: try_lock(path), path.name, wait, stopped, waiting)
    try:
        yield
    finally:
        os.close(fd)
