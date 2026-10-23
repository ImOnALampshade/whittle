# SPDX-License-Identifier: GPL-3.0-or-later
"""The conversation the sidebar shows: the turns on the path from the history's
start to its current node, then a failed turn that folded away (while it is
the latest thing that happened) and the running turn.

A running turn comes from the live stream; finished ones are replayed from
their transcript.jsonl, read once and cached, so a reopened file shows the
same conversation as the session that made it."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .. import formats, tree as trees
from .stream import Entry, entries_from_records

log = logging.getLogger("whittle")


@dataclass
class Request:
    """What a turn's request carried besides its prompt."""
    strokes: int = 0
    views: int = 0
    refs: int = 0

    def summary(self) -> str:
        parts = []
        for count, word in ((self.strokes, "stroke"), (self.views, "view"), (self.refs, "ref")):
            if count:
                parts.append(f"{count} {word}{'' if count == 1 else 's'}")
        return " · ".join(parts)


@dataclass
class Turn:
    node: str | None
    prompt: str
    entries: list[Entry] = field(default_factory=list)
    # complete | interrupted | failed | running
    status: str = "complete"
    # An interrupted turn whose changes were undone.
    restored: bool = False
    folded: bool = False
    running: bool = False
    request: Request = field(default_factory=Request)
    thumb: Path | None = None

    @property
    def end(self) -> Entry | None:
        return next((e for e in reversed(self.entries) if e.kind == "turn"), None)

    @property
    def failure(self) -> str:
        end = self.end
        return end.result if end is not None and end.result else "the turn did not finish"

    @property
    def renders(self) -> list[str]:
        return [path for e in self.entries if e.kind == "tool" for path in e.images]

    @property
    def picture(self) -> str | None:
        """The turn's last render, else the node's thumbnail."""
        renders = self.renders
        if renders:
            return renders[-1]
        return str(self.thumb) if self.thumb is not None else None


@dataclass
class Conversation:
    # The start line: node 0's id and label, or None before there is a history.
    root: tuple[str, str] | None = None
    current: str | None = None
    turns: list[Turn] = field(default_factory=list)
    # The nodes after the current one down to the newest leaf, when the
    # current node is not at the end of its branch.
    later: list[str] = field(default_factory=list)
    # Things that happened outside any turn (a run that never started).
    notes: list[Entry] = field(default_factory=list)

    @property
    def path_turns(self) -> list[Turn]:
        return [t for t in self.turns if not t.folded and not t.running]


# -- reading finished turns -----------------------------------------------------

_entries: dict[Path, tuple[tuple, list[Entry]]] = {}
_requests: dict[Path, tuple[tuple, Request]] = {}
_starts: dict[Path, tuple[tuple, str]] = {}


def _stamp(path: Path) -> tuple | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def transcript_entries(session: formats.SessionDir, node: str) -> list[Entry]:
    """A finished turn's entries from its transcript.jsonl."""
    path = session.transcript_path(node)
    stamp = _stamp(path)
    if stamp is None:
        return []
    cached = _entries.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        log.warning("cannot read %s: %s", path, exc)
    entries = entries_from_records(records, node)
    _entries[path] = (stamp, entries)
    return entries


def request_info(session: formats.SessionDir, node: str) -> Request:
    path = session.request_dir(node) / "request.json"
    stamp = _stamp(path)
    if stamp is None:
        return Request()
    cached = _requests.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    info = Request()
    try:
        request = formats.read_json(path)
        info.views = len(request.get("views") or [])
        info.refs = len(request.get("refs") or [])
        strokes = path.with_name("strokes.json")
        if strokes.is_file():
            info.strokes = len(formats.read_json(strokes).get("strokes") or [])
    except (formats.FormatError, OSError) as exc:
        log.warning("cannot read the request of %s: %s", node, exc)
    _requests[path] = (stamp, info)
    return info


def start_label(session: formats.SessionDir, node) -> str:
    """What the start line names: a start point's own label, or for a
    plain start the objects node 0 recorded ('Crate', 'Crate + 2 more')."""
    if node.label != trees.ROOT_LABEL:
        return node.label
    path = session.target_blend(node.id).with_suffix(".json")
    stamp = _stamp(path)
    if stamp is None:
        return "the scene as it was"
    cached = _starts.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        names = [o["name"] for o in formats.read_target_manifest(path)["objects"]]
    except (formats.FormatError, OSError, KeyError, TypeError):
        names = []
    if not names:
        label = "new objects"
    elif len(names) <= 2:
        label = ", ".join(names)
    else:
        label = f"{names[0]} + {len(names) - 1} more"
    _starts[path] = (stamp, label)
    return label


def clear_cache() -> None:
    _entries.clear()
    _requests.clear()
    _starts.clear()


# -- building -------------------------------------------------------------------

def _thumb(session: formats.SessionDir, node: str) -> Path | None:
    path = session.thumb_path(node)
    return path if path.is_file() else None


def _node_turn(hist, node_id: str) -> Turn:
    node = hist.tree.node(node_id)
    return Turn(node=node_id, prompt=node.prompt, entries=transcript_entries(hist.session, node_id),
                status=node.status, restored=node.restored, folded=node.folded,
                request=request_info(hist.session, node_id), thumb=_thumb(hist.session, node_id))


def _live_entries(ctl, node: str | None) -> list[Entry]:
    if node is None:
        return []
    return [e for e in ctl.stream.entries() if e.turn_id == node and e.kind != "submit"]


def _busy(ctl) -> bool:
    return ctl is not None and bool(getattr(ctl, "busy", getattr(ctl, "running", False)))


def build(hist, ctl) -> Conversation:
    """The conversation for this history and controller (either may be None)."""
    conv = Conversation()
    active = getattr(ctl, "active_turn", None) if ctl is not None else None
    running_node = active[0] if active else None
    tree = hist.tree if hist is not None else None
    if tree is not None:
        root = tree.node(tree.root)
        conv.root = (root.id, start_label(hist.session, root))
        conv.current = tree.current
        for node_id in tree.path(tree.current)[1:]:
            conv.turns.append(_node_turn(hist, node_id))
        later = [c for c in tree.visible_children(tree.current) if c != running_node]
        if later:
            leaf = max((tree.newest_leaf(c) for c in later), key=formats.node_number)
            path = tree.path(leaf)
            conv.later = path[path.index(tree.current) + 1:]
        folded = getattr(ctl, "last_folded", None) if ctl is not None else None
        if (folded and not _busy(ctl) and folded in tree.nodes and tree.node(folded).folded
                and tree.node(folded).parent == tree.current):
            conv.turns.append(_node_turn(hist, folded))
    if active is not None:
        node, prompt = active
        request = request_info(hist.session, node) if hist is not None and node else Request()
        conv.turns.append(Turn(node=node, prompt=prompt, entries=_live_entries(ctl, node),
                               status="running", running=True, request=request))
    if ctl is not None:
        entries = ctl.stream.entries()
        last_turn = max((i for i, e in enumerate(entries) if e.turn_id is not None), default=-1)
        conv.notes = [e for e in entries[last_turn + 1:]
                      if e.turn_id is None and e.kind in ("note", "warning", "error")]
    return conv
