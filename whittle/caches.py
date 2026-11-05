# SPDX-License-Identifier: GPL-3.0-or-later
"""Each file's hidden cache of its chats: <user dir>/cache/<file id>/, the
working copy of what the .blend stores (architecture §14). Nothing is ever
written beside a .blend. Stdlib only, so the agent tests cover it;
addon/chats.py does the Blender side.

A cache root holds what chats.py describes, plus:

    cache.json     {"format": "whittle.cache", "version": 1, "id", "path",
                    "used", "base"}: the file it belongs to, when it was last
                    used, and the stamp of the .blend state it was last in
                    step with
    in-use.json    {"pid", "host"}: the Blender that has it open

Beside the caches, open-<key>.json, one per running Blender, holds {"pid",
"host", "path"}: the saved file it has open, with or without a cache, so two
Blenders on one file see each other even when it has no chats yet.

The file id is stored in the .blend, so the cache follows the file through
renames and moves. A copy opened while the original's cache is in use, or
whose cache records another file that still exists, gets an id of its own.

The user folder also holds install.json, {"format": "whittle.install",
"version": 1, "id"}: a random id for this Whittle install, which each chat
records as its origin (chats.py), so a chat that came in a file from
elsewhere can be told apart.
"""

import functools
import hashlib
import logging
import os
import re
import secrets
import shutil
import socket
import time
from pathlib import Path

from . import chats as store
from . import formats, platforms

log = logging.getLogger("whittle")

CACHE_FORMAT = "whittle.cache"
RECORD_NAME = "cache.json"
LOCK_NAME = "in-use.json"
OPEN_MARKS = "open-*.json"
INSTALL_FORMAT = "whittle.install"
INSTALL_NAME = "install.json"
# A cache not used for this long is deleted (never the one in use).
MAX_AGE = 30 * 86400
_FILE_ID = re.compile(r"^f[0-9a-f]{16}$")
_INSTALL_ID = re.compile(r"^i[0-9a-f]{16}$")


def new_file_id() -> str:
    """f + 16 hex digits."""
    return "f" + secrets.token_hex(8)


def is_file_id(text) -> bool:
    return isinstance(text, str) and bool(_FILE_ID.match(text))


def install_id(user_dir) -> str:
    """This install's id, made the first time it is asked for. It names no
    machine or user: it only tells this install's chats from others'."""
    path = Path(user_dir) / INSTALL_NAME
    try:
        found = formats.read_json(path)
    except formats.FormatError:
        found = {}
    if found.get("format") == INSTALL_FORMAT and isinstance(found.get("id"), str) \
            and _INSTALL_ID.match(found["id"]):
        return found["id"]
    made = "i" + secrets.token_hex(8)
    formats.write_json_atomic(path, {"format": INSTALL_FORMAT, "version": 1, "id": made})
    return made


def state_stamp(index_json: str, packed: dict[str, bytes]) -> str:
    """What a .blend stores, in one digest: its chat index as written and
    the digest of every chat's zip."""
    digest = hashlib.sha256(index_json.encode())
    for chat in sorted(packed):
        digest.update(f"\0{chat}\0{hashlib.sha256(packed[chat]).hexdigest()}".encode())
    return digest.hexdigest()


# -- the record -----------------------------------------------------------------

def read_record(root) -> dict:
    """The cache's cache.json; empty when it has none or it cannot be read."""
    try:
        found = formats.read_json(Path(root) / RECORD_NAME)
    except formats.FormatError:
        return {}
    return found if found.get("format") == CACHE_FORMAT else {}


def update_record(root, **values) -> dict:
    """Sets values in the cache's cache.json, making it if needed."""
    root = Path(root)
    record = {"format": CACHE_FORMAT, "version": 1, "id": root.name, "path": None,
              "used": time.time(), "base": None}
    record.update({k: v for k, v in read_record(root).items() if k in record})
    record.update(values)
    record["id"] = root.name
    formats.write_json_atomic(root / RECORD_NAME, record)
    return record


def _used(root: Path) -> float:
    used = read_record(root).get("used")
    if isinstance(used, (int, float)) and not isinstance(used, bool):
        return float(used)
    try:
        return root.stat().st_mtime
    except OSError:
        return 0.0


# -- in use -----------------------------------------------------------------------

@functools.cache
def _host() -> str:
    """This machine's name, read once: macOS renames the machine as networks
    change, and a Blender must go on knowing its own claims and marks."""
    return socket.gethostname()


def _alive(pid: int) -> bool:
    return platforms.pid_alive(pid)


def _claim(path: Path) -> dict | None:
    try:
        found = formats.read_json(path)
    except formats.FormatError:
        return None
    pid = found.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    return found


def _held_elsewhere(found: dict, *, here_only: bool = False) -> bool:
    """Whether a claim is another Blender's: a live process on this machine,
    or any on another one (whose processes cannot be checked; here_only
    leaves those out)."""
    if found.get("host") != _host():
        return not here_only
    return found["pid"] != os.getpid() and _alive(found["pid"])


def in_use_elsewhere(root, *, here_only: bool = False) -> bool:
    """Whether another Blender has the cache open."""
    found = _claim(Path(root) / LOCK_NAME)
    return found is not None and _held_elsewhere(found, here_only=here_only)


def take(root) -> None:
    """This Blender has the cache open."""
    formats.write_json_atomic(Path(root) / LOCK_NAME, {"pid": os.getpid(), "host": _host()})


def release(root) -> None:
    """This Blender let go of the cache; another's claim stays."""
    root = Path(root)
    found = _claim(root / LOCK_NAME)
    if found is not None and found["pid"] == os.getpid() and found.get("host") == _host():
        (root / LOCK_NAME).unlink(missing_ok=True)


def _open_mark(cache_dir) -> Path:
    key = hashlib.sha256(f"{_host()}\0{os.getpid()}".encode()).hexdigest()[:16]
    return Path(cache_dir) / OPEN_MARKS.replace("*", key)


def mark_open(cache_dir, blend) -> None:
    """This Blender has the saved file blend open, and none if it is None. A
    file that never had chats has no cache to claim, and a Blender on it
    would otherwise go unseen."""
    if blend is None:
        unmark_open(cache_dir)
    else:
        formats.write_json_atomic(_open_mark(cache_dir),
                                  {"pid": os.getpid(), "host": _host(), "path": str(blend)})


def unmark_open(cache_dir) -> None:
    """This Blender closed its file."""
    _open_mark(cache_dir).unlink(missing_ok=True)


def open_elsewhere(cache_dir, blend, skip=None) -> bool:
    """Whether another Blender has the same file open: it marked the file
    open, or a cache other than skip (this Blender's) records the file and
    is claimed by a live Blender, which may be on a recovered copy of it.
    Each of the two works on a cache of its own, so their chats do not
    merge."""
    cache_dir = Path(cache_dir)
    if blend is None or not cache_dir.is_dir():
        return False
    for mark in cache_dir.glob(OPEN_MARKS):
        found = _claim(mark)
        recorded = found.get("path") if found is not None else None
        if isinstance(recorded, str) and same_file(recorded, blend) and _held_elsewhere(found):
            return True
    for folder in cache_dir.iterdir():
        if folder.name == skip or not is_file_id(folder.name) or folder.is_symlink() \
                or not (folder / LOCK_NAME).is_file():
            continue
        recorded = read_record(folder).get("path")
        if isinstance(recorded, str) and recorded and same_file(recorded, blend) \
                and in_use_elsewhere(folder):
            return True
    return False


# -- which cache a file uses -----------------------------------------------------

def same_file(a, b) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


def belongs_elsewhere(root, blend) -> bool:
    """Whether the cache is another file's: open in another Blender, or
    recording a different file that still exists."""
    if in_use_elsewhere(root):
        return True
    recorded = read_record(root).get("path")
    if not isinstance(recorded, str) or not recorded or blend is None:
        return False
    return not same_file(recorded, blend) and Path(recorded).exists()


def find(cache_dir, file_id, blend) -> tuple[str | None, bool]:
    """The cache id of an opened file and whether it differs from the id
    the file stores: that id, unless its cache is another file's
    (copy-on-conflict); then, as for a file without an id, the most
    recently used cache that records its path and is not in use, so a copy
    keeps the id it got until it is saved (and a crash before that save
    keeps its work); else a fresh id. (None, False) when a file without an
    id has no cache."""
    cache_dir = Path(cache_dir)
    if is_file_id(file_id):
        if not belongs_elsewhere(cache_dir / file_id, blend):
            return file_id, False
        return _by_path(cache_dir, blend, skip=file_id) or new_file_id(), True
    return _by_path(cache_dir, blend), False


def _by_path(cache_dir: Path, blend, skip: str | None = None) -> str | None:
    """The most recently used cache that records the file and is not in use."""
    if blend is None or not cache_dir.is_dir():
        return None
    found = []
    for folder in cache_dir.iterdir():
        if folder.name == skip or not is_file_id(folder.name) or not folder.is_dir() \
                or folder.is_symlink():
            continue
        recorded = read_record(folder).get("path")
        if isinstance(recorded, str) and recorded and same_file(recorded, blend) \
                and not in_use_elsewhere(folder):
            found.append((_used(folder), folder.name))
    return max(found)[1] if found else None


# -- cleanup ------------------------------------------------------------------------

def _stale_mark(mark: Path, now: float, max_age: float) -> bool:
    """Whether an open mark's Blender is gone; one on another machine cannot
    be checked, so it lasts as long as an unused cache."""
    found = _claim(mark)
    if found is None:
        return True
    if found.get("host") != _host():
        return now - mark.stat().st_mtime >= max_age
    return not _alive(found["pid"])


def cleanup(cache_dir, keep=(), *, now: float | None = None, max_age: float = MAX_AGE,
            config=None) -> list[str]:
    """Deletes the caches not used for max_age, with the CLI's transcripts
    of their chats' folders; never one in keep or open in a live Blender on
    this machine. Marks a crashed Blender left go too. Returns the ids
    deleted."""
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return []
    now = time.time() if now is None else now
    kept = {Path(k).resolve() for k in keep if k is not None}
    for mark in cache_dir.glob(OPEN_MARKS):
        if _stale_mark(mark, now, max_age):
            mark.unlink(missing_ok=True)
    gone = []
    for folder in sorted(cache_dir.iterdir()):
        if not is_file_id(folder.name) or not folder.is_dir() or folder.is_symlink():
            continue
        if folder.resolve() in kept or in_use_elsewhere(folder, here_only=True):
            continue
        if now - _used(folder) < max_age:
            continue
        chats = folder / "chats"
        if chats.is_dir():
            for chat in chats.iterdir():
                if config is not None and store.is_chat_id(chat.name):
                    shutil.rmtree(store.cli_project_dir(chat, config), ignore_errors=True)
        shutil.rmtree(folder, ignore_errors=True)
        gone.append(folder.name)
    if gone:
        log.info("deleted %d chat caches not used for %d days", len(gone), max_age // 86400)
    return gone
