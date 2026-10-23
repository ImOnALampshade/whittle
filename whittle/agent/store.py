# SPDX-License-Identifier: GPL-3.0-or-later
"""A chat's SDK transcripts in its own folder: an SDK SessionStore, so the
transcripts travel with the chat (into the .blend and back) and a chat
resumes on another machine or after its file moved. Stdlib only; the SDK
finds the methods by name, so nothing here imports it.

Layout: <folder>/<session id>.jsonl for a session's transcript and
<folder>/<session id>/<subpath>.jsonl for its subagents'. One store serves
one chat, so the SDK's project key is ignored. Nothing is ever deleted here:
deleting a chat removes its folder."""

import json
import logging
import os
import re
from pathlib import Path, PurePosixPath

log = logging.getLogger("whittle.agent")

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FolderSessionStore:
    def __init__(self, folder):
        self.folder = Path(folder)

    def path(self, key: dict) -> Path:
        """The file of a session key; a session id or subpath that could
        reach outside the folder is refused."""
        session = key.get("session_id") or ""
        if not _NAME.match(session):
            raise ValueError(f"not a session id: {session!r}")
        subpath = key.get("subpath")
        if not subpath:
            return self.folder / f"{session}.jsonl"
        parts = PurePosixPath(subpath).parts
        if subpath.startswith("/") or not parts or not all(_NAME.match(p) for p in parts):
            raise ValueError(f"not a transcript subpath: {subpath!r}")
        return self.folder.joinpath(session, *parts[:-1], f"{parts[-1]}.jsonl")

    async def append(self, key: dict, entries: list) -> None:
        if not entries:
            return
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in entries)
        # One write per batch, so a reader never sees half of one.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, text.encode("utf-8"))
        finally:
            os.close(fd)

    async def load(self, key: dict) -> list | None:
        path = self.path(key)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        entries = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                # A line cut short when the folder was copied mid-write.
                log.warning("skipping a damaged line in %s", path)
        return entries

    async def list_subkeys(self, key: dict) -> list[str]:
        base = self.path({"session_id": key.get("session_id")}).with_suffix("")
        if not base.is_dir():
            return []
        return sorted(p.relative_to(base).with_suffix("").as_posix() for p in base.rglob("*.jsonl"))
