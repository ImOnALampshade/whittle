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

The file id is stored in the .blend, so the cache follows the file through
renames and moves. A copy opened while the original's cache is in use, or
whose cache records another file that still exists, gets an id of its own.
"""

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
from . import formats, tree as trees

log = logging.getLogger("whittle")

CACHE_FORMAT = "whittle.cache"
RECORD_NAME = "cache.json"
LOCK_NAME = "in-use.json"
# A cache not used for this long is deleted (never the one in use).
MAX_AGE = 30 * 86400
_FILE_ID = re.compile(r"^f[0-9a-f]{16}$")
_REPLACED_TIME = re.compile(r"\d{8}-\d{6}")


def new_file_id() -> str:
    """f + 16 hex digits."""
    return "f" + secrets.token_hex(8)


def is_file_id(text) -> bool:
    return isinstance(text, str) and bool(_FILE_ID.match(text))


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

def _host() -> str:
    return socket.gethostname()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OverflowError, ValueError):
        return False
    return True


def _lock(root: Path) -> dict | None:
    try:
        found = formats.read_json(root / LOCK_NAME)
    except formats.FormatError:
        return None
    pid = found.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    return found


def in_use_elsewhere(root, *, here_only: bool = False) -> bool:
    """Whether another Blender has the cache open: a live process on this
    machine, or any on another one (whose processes cannot be checked;
    here_only leaves those out)."""
    found = _lock(Path(root))
    if found is None:
        return False
    if found.get("host") != _host():
        return not here_only
    return found["pid"] != os.getpid() and _alive(found["pid"])


def take(root) -> None:
    """This Blender has the cache open."""
    formats.write_json_atomic(Path(root) / LOCK_NAME, {"pid": os.getpid(), "host": _host()})


def release(root) -> None:
    """This Blender let go of the cache; another's claim stays."""
    root = Path(root)
    found = _lock(root)
    if found is not None and found["pid"] == os.getpid() and found.get("host") == _host():
        (root / LOCK_NAME).unlink(missing_ok=True)


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

def cleanup(cache_dir, keep=(), *, now: float | None = None, max_age: float = MAX_AGE,
            config=None) -> list[str]:
    """Deletes the caches not used for max_age, with the CLI's transcripts
    of their chats' folders; never one in keep or open in a live Blender on
    this machine. Returns the ids deleted."""
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return []
    now = time.time() if now is None else now
    kept = {Path(k).resolve() for k in keep if k is not None}
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


def cleanup_old_layout(user_dir, *, now: float | None = None, max_age: float = MAX_AGE) -> list[Path]:
    """The caches of earlier versions in the user folder (dev-sessions/<time>
    for unsaved files, caches/<sha1> for files beside an unwritable folder)
    go by the same age, from their modification time."""
    now = time.time() if now is None else now
    gone = []
    for name in ("dev-sessions", "caches"):
        parent = Path(user_dir) / name
        if not parent.is_dir() or parent.is_symlink():
            continue
        for folder in parent.iterdir():
            try:
                old = folder.is_dir() and not folder.is_symlink() and now - folder.stat().st_mtime >= max_age
            except OSError:
                continue
            if old:
                shutil.rmtree(folder, ignore_errors=True)
                gone.append(folder)
        try:
            parent.rmdir()
        except OSError:
            pass
    return gone


# -- the old layout: <name>.whittle beside the .blend ------------------------------

def _format_of(path: Path) -> str | None:
    try:
        return formats.read_json(path).get("format")
    except formats.FormatError:
        return None


def is_cache_root(folder) -> bool:
    """A cache root Whittle made: its chat index, or the single-session
    layout's session.json, says so."""
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        return False
    return (_format_of(folder / store.INDEX_NAME) == store.INDEX_FORMAT
            or _format_of(folder / "session.json") == trees.SESSION_FORMAT)


def _only_chats(folder: Path) -> bool:
    """A folder of chats moved aside: chats/<chat id>/ and nothing else."""
    try:
        entries = list(folder.iterdir())
        chats = folder / "chats"
        return ([e.name for e in entries] == ["chats"] and chats.is_dir() and not chats.is_symlink()
                and all(store.is_chat_id(c.name) and c.is_dir() for c in chats.iterdir()))
    except OSError:
        return False


def sidecar(blend) -> Path | None:
    """The <name>.whittle folder an earlier version kept beside the .blend,
    if Whittle's own."""
    blend = Path(blend)
    found = blend.with_name(f"{blend.stem}.whittle")
    return found if is_cache_root(found) else None


def replaced(blend) -> list[Path]:
    """The <name>.whittle.replaced-<time> folders an earlier version moved a
    cache's differing copies to, if Whittle's own."""
    blend = Path(blend)
    prefix = f"{blend.stem}.whittle.replaced-"
    out = []
    try:
        entries = list(blend.parent.iterdir())
    except OSError:
        return []
    for path in entries:
        name = path.name
        if not name.startswith(prefix) or not _REPLACED_TIME.fullmatch(name[len(prefix):]):
            continue
        if path.is_dir() and not path.is_symlink() and (is_cache_root(path) or _only_chats(path)):
            out.append(path)
    return sorted(out)


def has_chats(root) -> bool:
    root = Path(root)
    chats = root / "chats"
    return (root / store.INDEX_NAME).is_file() or (chats.is_dir() and any(chats.iterdir()))


def migrate_sidecar(old, root, config=None) -> bool:
    """Moves an earlier version's cache root into root, once, when root
    has no chats yet: a single-session layout first becomes a chat in place
    (its CLI transcripts are found by its old path), then the index, the
    chats and their packed copies move. Returns whether they moved."""
    old, root = Path(old), Path(root)
    if has_chats(root):
        return False
    found = store.Chats(old)
    found.load()
    found.migrate(config)
    root.mkdir(parents=True, exist_ok=True)
    for name in (store.INDEX_NAME, "chats", "packed"):
        src = old / name
        if not src.exists() or src.is_symlink():
            continue
        dest = root / name
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        shutil.move(src, dest)
    log.info("moved the chats in %s to %s", old, root)
    return True


def remove(folders) -> None:
    for folder in folders:
        shutil.rmtree(folder, ignore_errors=True)
