# SPDX-License-Identifier: GPL-3.0-or-later
"""A file's chats: each one a conversation with its own history tree and SDK
sessions, the index the chat menu draws from, and packing a chat into one
zip for the .blend. Stdlib only, so the agent tests cover it without
Blender; addon/chats.py does the Blender side.

A cache root (<user dir>/cache/<file id>/, caches.py) holds:

    chats.json                 the index
    chats/<chat id>/           one chat: chat.json and a session folder (§8),
                               also the agent's cwd for that chat, with the
                               SDK transcripts in sdk/
    packed/<chat id>.zip       the chat as last written into the .blend
    packed/<chat id>.json      {"digest", "fingerprint", "size"} of that zip
"""

import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import time
import unicodedata
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import formats, platforms, tree as trees

log = logging.getLogger("whittle")

INDEX_FORMAT = "whittle.chats"
CHAT_FORMAT = "whittle.chat"
INDEX_NAME = "chats.json"
CHAT_NAME = "chat.json"
NEW_TITLE = "New chat"
TITLE_CHARS = 40
# Files that are already compressed go into the zip as they are.
STORED_SUFFIXES = (".png", ".blend")
# A .blend is data from whoever made it: a chat that unpacks to more than
# this is refused rather than filling the disk.
MAX_UNPACKED = 4 << 30
_CHAT_ID = re.compile(r"^c[0-9a-f]{8}$")
_SANITIZE = re.compile(r"[^a-zA-Z0-9]")
# The CLI cuts a project folder name here and adds a hash of the path.
MAX_PROJECT_KEY = 200

# How far back "Delete Other Chats" reaches, by its choice.
OLDER_THAN = {"OTHERS": 0, "WEEK": 7 * 86400, "MONTH": 30 * 86400, "QUARTER": 91 * 86400}


# -- names, titles and ages -------------------------------------------------------

def new_chat_id(taken=()) -> str:
    """c + 8 hex digits, never one already taken."""
    while True:
        chat = "c" + secrets.token_hex(4)
        if chat not in taken:
            return chat


def is_chat_id(text: str) -> bool:
    return bool(_CHAT_ID.match(text or ""))


def title_for(prompt: str, target: str | None = None) -> str:
    """A chat's title from its first prompt, as the Claude apps make one: the
    first line without its closing full stop, cut at a word's end. A first turn without a prompt is named
    after what it sketched on."""
    line = next((part.strip() for part in (prompt or "").splitlines() if part.strip()), "")
    line = " ".join(line.split())
    if not line:
        return f"Sketch of {target}" if target else "Sketch"
    if len(line) <= TITLE_CHARS:
        # A title, not a message: one closing full stop goes ("Add a lid").
        return line[:-1] if line.endswith(".") and not line.endswith("..") else line
    cut = line[:TITLE_CHARS - 1]
    if line[TITLE_CHARS - 1] != " " and " " in cut:
        head = cut.rsplit(" ", 1)[0]
        if len(head) >= TITLE_CHARS // 2:
            cut = head
    return cut.rstrip(" ,.;:·-") + "…"


def age_label(seconds: float) -> str:
    """How long ago, in the words the chat menu uses."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        n = int(seconds // 60)
        return f"{n} minute{'' if n == 1 else 's'} ago"
    if seconds < 86400:
        n = int(seconds // 3600)
        return f"{n} hour{'' if n == 1 else 's'} ago"
    days = int(seconds // 86400)
    if days < 2:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        return "over a week ago"
    if days < 365:
        return "over a month ago"
    return "over a year ago"


def size_label(size: int) -> str:
    """Bytes as the chat menu shows them: MB with one decimal, 0.1 MB at least."""
    return f"{max(size / 1e6, 0.1):.1f} MB"


def epoch(stamp: str) -> float:
    """An ISO time (now_iso(), or tree.now_iso() to the second) as seconds
    since the epoch; 0 when it cannot be read."""
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (TypeError, ValueError):
        return 0.0


def iso(seconds: float) -> str:
    """Local time to the millisecond, so two turns ending in one second
    still sort."""
    return datetime.fromtimestamp(seconds).astimezone().isoformat(timespec="milliseconds")


def now_iso() -> str:
    return iso(time.time())


# -- the CLI's own folders ---------------------------------------------------------
# The CLI runs with Whittle's private configuration folder (the add-on's
# paths.claude_config_dir()), which callers pass in as `config`.

def _djb2(text: str) -> str:
    """The CLI's 32-bit string hash in base 36, for long project paths."""
    h = 0
    for ch in text:
        h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
    if h >= 0x80000000:
        h -= 0x100000000
    h = abs(h)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while h:
        h, rest = divmod(h, 36)
        out = digits[rest] + out
    return out or "0"


def project_key(directory) -> str:
    """The name the CLI gives the folder of a cwd's transcripts: the real
    path, NFC, every non-alphanumeric a dash, long ones cut and hashed. A
    port of the SDK's project_key_for_directory."""
    try:
        path = unicodedata.normalize("NFC", os.path.realpath(str(directory)))
    except OSError:
        path = unicodedata.normalize("NFC", str(directory))
    key = _SANITIZE.sub("-", path)
    if len(key) <= MAX_PROJECT_KEY:
        return key
    return f"{key[:MAX_PROJECT_KEY]}-{_djb2(path)}"


def cli_project_dir(cwd, config) -> Path:
    """Where the CLI, run with config as its configuration folder, keeps
    the transcripts of sessions run in cwd."""
    return Path(unicodedata.normalize("NFC", str(config))) / "projects" / project_key(cwd)


# -- packing ------------------------------------------------------------------------

def _skipped(rel: PurePosixPath) -> bool:
    """A comparison's scratch, turn checkpoints (only used during their turn)
    and partial files are not part of a chat."""
    parts = rel.parts
    if parts[0] == "compare":
        return True
    if len(parts) >= 3 and parts[0] == "nodes" and parts[2] == "checkpoints":
        return True
    return any(p.startswith(".") for p in parts) or rel.name.endswith(".tmp")


def _members(folder: Path) -> list[tuple[str, Path]]:
    out = []
    for path in folder.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        rel = PurePosixPath(path.relative_to(folder).as_posix())
        if not _skipped(rel):
            out.append((str(rel), path))
    return sorted(out)


def fingerprint(folder) -> str:
    """A digest of what pack would read: every member's path, size and
    modification time. Cheap to take at every save, and different after any
    write."""
    digest = hashlib.sha256()
    folder = Path(folder)
    if folder.is_dir():
        for rel, path in _members(folder):
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def _read_member(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix == ".jsonl" and data and not data.endswith(b"\n"):
        # Being appended to: up to its last whole line.
        data = data[:data.rfind(b"\n") + 1]
    return data


def pack(folder) -> bytes:
    """The chat folder as one zip: PNG and .blend files stored as they are
    (snapshots are already compressed), the rest deflated."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for rel, path in _members(Path(folder)):
            try:
                data = _read_member(path)
                mtime = path.stat().st_mtime
            except OSError as exc:
                log.warning("leaving %s out of the packed chat: %s", path, exc)
                continue
            info = zipfile.ZipInfo(rel, date_time=time.localtime(max(mtime, 315532800))[:6])
            info.compress_type = zipfile.ZIP_STORED if path.suffix in STORED_SUFFIXES else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return out.getvalue()


def packed_size(folder) -> int:
    """What the chat would add to the .blend now."""
    return len(pack(folder))


def _safe_member(name: str) -> PurePosixPath:
    rel = PurePosixPath(name)
    if (not name or name.startswith("/") or "\\" in name or rel.is_absolute()
            or any(p in ("", "..") or ":" in p for p in rel.parts)):
        raise formats.FormatError(f"unsafe path in a packed chat: {name!r}")
    return rel


def unpack(data: bytes, folder) -> None:
    """Writes a packed chat into folder, which must not exist yet. Every
    member path is checked first, so nothing lands outside it; the folder
    appears whole or not at all."""
    folder = Path(folder)
    if folder.exists():
        raise FileExistsError(f"{folder} already exists")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise formats.FormatError(f"not a packed chat: {exc}") from None
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        names = [_safe_member(i.filename) for i in infos]
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise formats.FormatError("a packed chat that large is refused")
        folder.parent.mkdir(parents=True, exist_ok=True)
        tmp = folder.with_name(f".{folder.name}.unpack-{os.getpid()}")
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            for info, rel in zip(infos, names):
                dest = tmp.joinpath(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(info))
            tmp.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, folder)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    platforms.replace(tmp, path)


# -- the index ----------------------------------------------------------------------

@dataclass
class Entry:
    """One chat as the menu lists it."""
    title: str = NEW_TITLE
    created: str = ""
    # The end of its last turn, else created.
    updated: str = ""
    # Non-folded turns on every branch.
    turns: int = 0
    # Bytes it adds to the saved .blend.
    size: int = 0
    # sha256 of the zip the .blend last got.
    digest: str | None = None
    # The model the chat runs on; None follows the add-on's default until
    # the chat's first turn, which keeps the model it was sent with.
    model: str | None = None
    # The install that made the chat (caches.install_id), and those it was
    # continued on after asking. None: made before chats recorded it, and
    # taken as every install's own.
    origin: str | None = None
    adopted: list[str] = field(default_factory=list)
    # The chat's effort (models.EFFORTS); None runs at the default.
    effort: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


_ENTRY_SPEC = {"title": str, "created": str, "updated": str, "turns": int, "size": int,
               "digest": (str, None)}
# Keys an index from an earlier version may lack.
_ENTRY_OPTIONAL = {"model": (str, None), "effort": (str, None), "origin": (str, None), "adopted": list}


@dataclass
class Index:
    current: str | None = None
    chats: dict[str, Entry] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"format": INDEX_FORMAT, "version": 1, "current": self.current,
                "chats": {chat: entry.to_json() for chat, entry in self.chats.items()}}


def validate_index(obj, where: str = INDEX_NAME) -> None:
    if not isinstance(obj, dict):
        raise formats.FormatError(f"{where}: not a JSON object")
    formats._check_header(obj, where, INDEX_FORMAT)
    formats._check(obj, where, {"current": (str, None), "chats": dict})
    for chat, entry in obj["chats"].items():
        if not is_chat_id(chat):
            raise formats.FormatError(f"{where}: {chat!r} is not a chat id")
        if not isinstance(entry, dict):
            raise formats.FormatError(f"{where}: chats.{chat} must be an object")
        formats._check(entry, f"{where}: chats.{chat}", _ENTRY_SPEC)
        formats._check(entry, f"{where}: chats.{chat}", {k: t for k, t in _ENTRY_OPTIONAL.items() if k in entry})
        if not all(isinstance(i, str) for i in entry.get("adopted", [])):
            raise formats.FormatError(f"{where}: chats.{chat}.adopted must hold strings")
    if obj["current"] is not None and obj["current"] not in obj["chats"]:
        raise formats.FormatError(f"{where}: current {obj['current']!r} is not listed")


def index_from_json(obj, where: str = INDEX_NAME) -> Index:
    validate_index(obj, where)
    return Index(current=obj.get("current"),
                 chats={chat: Entry(**{k: entry[k] for k in (*_ENTRY_SPEC, *_ENTRY_OPTIONAL) if k in entry})
                        for chat, entry in obj["chats"].items()})


def read_index(path) -> Index:
    return index_from_json(formats.read_json(path), str(path))


def write_index(path, index: Index) -> None:
    formats.write_json_atomic(path, index.to_json())


# -- one cache root ----------------------------------------------------------------

class Chats:
    """The chats of one cache root. Every change is written at once. origin
    is this install's id: the chats it makes record it, and a chat made by
    another install is foreign() until adopted here."""

    def __init__(self, root, origin: str | None = None):
        self.root = Path(root)
        self.origin = origin
        self.index = Index()
        # The chat switched to since its last turn: its next turn tells the
        # agent the scene may have changed meanwhile. Runtime only.
        self.switched: str | None = None

    # -- paths --------------------------------------------------------------------

    def index_path(self) -> Path:
        return self.root / INDEX_NAME

    def folder(self, chat: str) -> Path:
        return self.root / "chats" / chat

    def packed_paths(self, chat: str) -> tuple[Path, Path]:
        folder = self.root / "packed"
        return folder / f"{chat}.zip", folder / f"{chat}.json"

    # -- the index ---------------------------------------------------------------

    def load(self) -> None:
        path = self.index_path()
        self.index = Index()
        if path.is_file():
            try:
                self.index = read_index(path)
                return
            except formats.FormatError as exc:
                log.error("cannot read the chat index, rebuilding it: %s", exc)
        self.rebuild()

    def save(self) -> None:
        write_index(self.index_path(), self.index)

    def rebuild(self) -> None:
        """The index from the chat folders, when it is missing or unreadable."""
        found = self.root / "chats"
        current = self.index.current
        self.index = Index()
        if not found.is_dir():
            return
        for folder in sorted(found.iterdir()):
            if folder.is_dir() and is_chat_id(folder.name):
                self.index.chats[folder.name] = self._describe(folder.name)
        if current in self.index.chats:
            self.index.current = current
        elif self.index.chats:
            self.index.current = self.ordered()[0]
        if self.index.chats:
            self.save()

    def __contains__(self, chat) -> bool:
        return chat in self.index.chats

    @property
    def current(self) -> str | None:
        return self.index.current

    def entry(self, chat: str) -> Entry:
        return self.index.chats[chat]

    def ordered(self) -> list[str]:
        """Every chat, most recently active first (times are to the second:
        of two in the same second, the one made later)."""
        return sorted(reversed(list(self.index.chats)), reverse=True,
                      key=lambda c: (epoch(self.index.chats[c].updated), epoch(self.index.chats[c].created)))

    def listed(self) -> list[str]:
        """The chats the menu lists: those with turns, and the current one."""
        return [c for c in self.ordered() if self.index.chats[c].turns or c == self.current]

    def total_size(self) -> int:
        return sum(self.index.chats[c].size for c in self.listed())

    # -- one chat ----------------------------------------------------------------

    def read_chat(self, chat: str) -> dict:
        path = self.folder(chat) / CHAT_NAME
        try:
            found = formats.read_json(path)
        except formats.FormatError:
            return {}
        return found if found.get("format") == CHAT_FORMAT else {}

    def _write_chat(self, chat: str, **values) -> None:
        data = {"format": CHAT_FORMAT, "version": 1, "id": chat, "title": NEW_TITLE,
                "title_custom": False, "created": now_iso(), "model": None, "effort": None,
                "origin": None, "adopted": []}
        data.update({k: v for k, v in self.read_chat(chat).items() if k in data})
        data.update(values)
        formats.write_json_atomic(self.folder(chat) / CHAT_NAME, data)

    def _tree(self, chat: str):
        path = self.folder(chat) / "session.json"
        if not path.is_file():
            return None
        try:
            return trees.read_session(path)[0]
        except formats.FormatError as exc:
            log.warning("cannot read the history of chat %s: %s", chat, exc)
            return None

    @staticmethod
    def _turns(found) -> list:
        """The turns a chat counts: every non-folded node but the start."""
        if found is None:
            return []
        return sorted((n for n in found.nodes.values() if n.parent is not None and not n.folded),
                      key=lambda n: formats.node_number(n.id))

    def _first_turn(self, chat: str):
        turns = self._turns(self._tree(chat))
        return turns[0] if turns else None

    def _describe(self, chat: str) -> Entry:
        """An entry from the chat's folder alone."""
        info = self.read_chat(chat)
        found = self._tree(chat)
        created = info.get("created") or (found.created if found else "") or now_iso()
        model = info.get("model") if isinstance(info.get("model"), str) else None
        effort = info.get("effort") if isinstance(info.get("effort"), str) else None
        origin = info.get("origin") if isinstance(info.get("origin"), str) else None
        adopted = [i for i in info.get("adopted") or [] if isinstance(i, str)] \
            if isinstance(info.get("adopted"), list) else []
        entry = Entry(title=info.get("title") or NEW_TITLE, created=created, updated=created, model=model,
                      effort=effort, origin=origin, adopted=adopted)
        if found is not None:
            turns = self._turns(found)
            entry.turns = len(turns)
            stamps = [n.created for n in turns if n.created]
            if stamps:
                entry.updated = max(stamps, key=epoch)
            if entry.title == NEW_TITLE and turns:
                entry.title = title_for(turns[0].prompt)
            entry.size = packed_size(self.folder(chat))
        return entry

    def new(self, model: str | None = None) -> str:
        """An empty chat, made current. The previous current chat goes if it
        never had a turn, so New Chat repeated leaves nothing behind. Without
        a model it follows the add-on's default."""
        chat = new_chat_id(set(self.index.chats) | self._folders())
        stamp = now_iso()
        self.folder(chat).mkdir(parents=True, exist_ok=True)
        self._write_chat(chat, created=stamp, model=model, origin=self.origin)
        self.index.chats[chat] = Entry(created=stamp, updated=stamp, model=model, origin=self.origin)
        self._become_current(chat)
        self.save()
        return chat

    def _folders(self) -> set[str]:
        found = self.root / "chats"
        return {p.name for p in found.iterdir()} if found.is_dir() else set()

    def ensure_current(self) -> str:
        """The current chat, made when there is none."""
        if self.current is None:
            return self.new()
        self.ensure_unpacked(self.current)
        return self.current

    def switch(self, chat: str) -> None:
        if chat not in self.index.chats:
            raise KeyError(f"no chat {chat!r}")
        self.ensure_unpacked(chat)
        self._become_current(chat)
        # Its next turn says the scene may have moved on: nothing to say for
        # a chat that never had one.
        self.switched = chat if (self.folder(chat) / "session.json").is_file() else None
        self.save()

    def _become_current(self, chat: str) -> None:
        previous = self.index.current
        self.index.current = chat
        if previous and previous != chat and previous in self.index.chats and self._empty(previous):
            self._remove(previous)
        if self.switched != chat:
            self.switched = None

    def _empty(self, chat: str) -> bool:
        # A chat whose only turns failed (folded) or that only took a start
        # point has a history but no turn: the menu does not list it, so it
        # goes too rather than riding along in every save unseen. One whose
        # history cannot be read, or that is still only packed, is never
        # taken for empty: deleting it would lose turns nobody has seen.
        folder = self.folder(chat)
        if not folder.is_dir():
            return not self.packed_paths(chat)[0].is_file()
        if any(folder.glob("session.json.bad-*")):
            return False
        if not (folder / "session.json").is_file():
            return True
        found = self._tree(chat)
        return found is not None and not self._turns(found)

    def ensure_unpacked(self, chat: str) -> None:
        """A chat the .blend brought is unpacked the first time it is used."""
        folder = self.folder(chat)
        if folder.is_dir():
            return
        zip_path, meta_path = self.packed_paths(chat)
        if zip_path.is_file():
            unpack(zip_path.read_bytes(), folder)
            meta = self._meta(chat) or {}
            formats.write_json_atomic(meta_path, {**meta, "fingerprint": fingerprint(folder)})
        else:
            folder.mkdir(parents=True, exist_ok=True)
            entry = self.index.chats.get(chat)
            self._write_chat(chat, title=entry.title if entry else NEW_TITLE,
                             model=entry.model if entry else None,
                             effort=entry.effort if entry else None,
                             origin=entry.origin if entry else self.origin,
                             adopted=list(entry.adopted) if entry else [])

    def rename(self, chat: str, title: str) -> str:
        """A title by hand; an empty one puts back the automatic title."""
        title = " ".join(title.split())
        if title:
            self._write_chat(chat, title=title, title_custom=True)
        else:
            first = self._first_turn(chat)
            title = title_for(first.prompt) if first is not None else NEW_TITLE
            self._write_chat(chat, title=title, title_custom=False)
        self.index.chats[chat].title = title
        self.save()
        return title

    def model(self, chat: str | None) -> str | None:
        """The chat's own model; None when it follows the default."""
        entry = self.index.chats.get(chat) if chat else None
        return entry.model if entry is not None else None

    def set_model(self, chat: str, model: str | None) -> None:
        """The model the chat's next turn runs on."""
        model = (model or "").strip() or None
        self._write_chat(chat, model=model)
        self.index.chats[chat].model = model
        self.save()

    def effort(self, chat: str | None) -> str | None:
        """The chat's own effort; None when it runs at the default."""
        entry = self.index.chats.get(chat) if chat else None
        return entry.effort if entry is not None else None

    def set_effort(self, chat: str, effort: str | None) -> None:
        """The effort the chat's next turn runs at."""
        effort = (effort or "").strip() or None
        self._write_chat(chat, effort=effort)
        self.index.chats[chat].effort = effort
        self.save()

    def foreign(self, chat: str | None) -> bool:
        """Whether the chat was made by another install (someone else's
        file, or this user's other machine) and not continued here yet. A
        chat that records no origin, or Chats without one, is never foreign."""
        entry = self.index.chats.get(chat) if chat else None
        return (entry is not None and self.origin is not None and entry.origin is not None
                and entry.origin != self.origin and self.origin not in entry.adopted)

    def adopt(self, chat: str) -> None:
        """This install continues the chat: it is not asked about again,
        here or in any copy of the file saved from now on."""
        entry = self.index.chats[chat]
        if self.origin is None or not self.foreign(chat):
            return
        entry.adopted = [*entry.adopted, self.origin]
        self.ensure_unpacked(chat)
        self._write_chat(chat, adopted=list(entry.adopted))
        self.save()

    def began(self, chat: str, prompt: str, target: str | None = None, model: str | None = None) -> None:
        """A turn was sent: the first one names the chat, unless it was
        named by hand. A chat that followed the default keeps the model the
        turn went with, so changing the default later leaves it alone."""
        info = self.read_chat(chat)
        entry = self.index.chats[chat]
        if model and entry.model is None:
            self.set_model(chat, model)
        if info.get("title_custom") or entry.turns or entry.title != NEW_TITLE:
            return
        title = title_for(prompt, target)
        self._write_chat(chat, title=title)
        entry.title = title
        self.save()

    def refresh(self, chat: str, *, ended: bool = False) -> None:
        """The entry follows the chat's folder: its turns and size, and with
        ended, the time of its last turn."""
        entry = self.index.chats.get(chat)
        if entry is None:
            return
        entry.turns = len(self._turns(self._tree(chat)))
        entry.size = packed_size(self.folder(chat))
        if ended:
            entry.updated = now_iso()
        self.save()

    def to_delete(self, which: str, now: float | None = None) -> list[str]:
        """The listed chats, other than the current one, that a "Delete Other
        Chats" choice takes."""
        now = time.time() if now is None else now
        age = OLDER_THAN[which]
        return [c for c in self.listed() if c != self.current
                and (not age or now - epoch(self.index.chats[c].updated) >= age)]

    def delete(self, chat: str, config=None) -> str | None:
        """Removes the chat from the cache at once: its folder, its packed
        copy, its entry and, given the CLI's configuration folder, the CLI's
        transcripts for its cwd (which hold only its own). The .blend loses
        it at the next save. Deleting the
        current chat makes the most recent remaining one current, or a new
        empty one. Returns the current chat."""
        if chat not in self.index.chats:
            raise KeyError(f"no chat {chat!r}")
        cli = cli_project_dir(self.folder(chat), config) if config is not None else None
        was_current = chat == self.index.current
        self._remove(chat)
        if cli is not None:
            shutil.rmtree(cli, ignore_errors=True)
        if was_current:
            self.index.current = None
            rest = self.listed() or self.ordered()
            if rest:
                self.switch(rest[0])
            else:
                self.new()
        self.save()
        return self.index.current

    def _remove(self, chat: str) -> None:
        shutil.rmtree(self.folder(chat), ignore_errors=True)
        for path in self.packed_paths(chat):
            path.unlink(missing_ok=True)
        self.index.chats.pop(chat, None)
        if self.switched == chat:
            self.switched = None

    # -- the .blend ---------------------------------------------------------------

    def _meta(self, chat: str) -> dict | None:
        try:
            return formats.read_json(self.packed_paths(chat)[1])
        except formats.FormatError:
            return None

    def pack_all(self) -> dict[str, bytes]:
        """Every chat with a history as a zip for the .blend, packed again
        only when its folder changed since it was last packed. A chat never
        unpacked since the file was opened goes back as it came."""
        out = {}
        for chat, entry in self.index.chats.items():
            folder = self.folder(chat)
            zip_path, meta_path = self.packed_paths(chat)
            if not folder.is_dir():
                if zip_path.is_file():
                    out[chat] = zip_path.read_bytes()
                continue
            if not (folder / "session.json").is_file():
                # Nothing to keep but its entry.
                entry.digest, entry.size = None, 0
                continue
            stamp = fingerprint(folder)
            meta = self._meta(chat)
            if meta and meta.get("fingerprint") == stamp and zip_path.is_file():
                data = zip_path.read_bytes()
            else:
                data = pack(folder)
                _write_bytes_atomic(zip_path, data)
                formats.write_json_atomic(meta_path, {"digest": hashlib.sha256(data).hexdigest(),
                                                      "fingerprint": stamp, "size": len(data)})
            entry.digest, entry.size = hashlib.sha256(data).hexdigest(), len(data)
            out[chat] = data
        self.save()
        return out

    def reconcile(self, index: dict, packed: dict[str, bytes], *, keep_newer: bool = False) -> dict[str, list[str]]:
        """After the .blend was opened: the cache is made to match what the
        file stores, and the file wins. A chat folder that differs, or that
        the file does not have, is deleted. Chats the cache lacks are
        unpacked when first used (the current one at once). With keep_newer
        (the cache was built on exactly this file's chats, then went on
        without a save: a crash) the cache stays as it is. Returns what
        happened, by chat."""
        stored = index_from_json(index, "the .blend's chat index")
        report = {"in_step": [], "written": [], "discarded": [], "kept": []}
        if keep_newer:
            report["kept"] = sorted(self.index.chats)
            if self.current is not None:
                self.ensure_unpacked(self.current)
            return report
        for chat, entry in stored.chats.items():
            folder = self.folder(chat)
            data = packed.get(chat)
            if data is None:
                # An empty chat: its entry is all there is. A folder that has
                # gained a history since differs from the file, so it goes.
                if folder.is_dir() and (folder / "session.json").is_file():
                    shutil.rmtree(folder)
                    report["discarded"].append(chat)
                if not folder.is_dir():
                    folder.mkdir(parents=True, exist_ok=True)
                    self._write_chat(chat, title=entry.title, created=entry.created, model=entry.model,
                                     effort=entry.effort, origin=entry.origin,
                                     adopted=list(entry.adopted))
                report["in_step"].append(chat)
                continue
            digest = hashlib.sha256(data).hexdigest()
            meta = self._meta(chat) or {}
            if (folder.is_dir() and meta.get("digest") == digest
                    and meta.get("fingerprint") == fingerprint(folder)):
                report["in_step"].append(chat)
                continue
            if folder.exists():
                shutil.rmtree(folder)
                report["discarded"].append(chat)
            zip_path, meta_path = self.packed_paths(chat)
            _write_bytes_atomic(zip_path, data)
            formats.write_json_atomic(meta_path, {"digest": digest, "fingerprint": None, "size": len(data)})
            entry.digest, entry.size = digest, len(data)
            report["written"].append(chat)
        for chat in sorted(self._folders() - set(stored.chats)):
            if is_chat_id(chat):
                self._remove(chat)
                report["discarded"].append(chat)
        packed_dir = self.root / "packed"
        if packed_dir.is_dir():
            for path in packed_dir.iterdir():
                if path.suffix in (".zip", ".json") and path.stem not in stored.chats:
                    path.unlink(missing_ok=True)
        self.index = stored
        self.switched = None
        if stored.current is not None:
            self.ensure_unpacked(stored.current)
        self.save()
        if report["discarded"]:
            log.info("chats %s differed from the file; the file's copies replaced them",
                     ", ".join(report["discarded"]))
        return report



def delete_label(count: int, size: int) -> str:
    return f"Deletes {count} chat{'' if count == 1 else 's'}, {size_label(size)}."


def index_json(index: Index) -> str:
    return json.dumps(index.to_json(), ensure_ascii=False)
