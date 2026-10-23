# SPDX-License-Identifier: GPL-3.0-or-later
"""The live transcript: a list of entries for the sidebar (assistant text,
tool calls merged with their results, notes) and a transcript.jsonl file per
turn."""

import json
import textwrap
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .. import protocol
from ..protocol import Event

MAX_ENTRIES = 200
LINE_CHARS = 160
RESULT_LINES = 12
# Rough width of an average sidebar character at UI scale 1.
CHAR_PX = 7.0


@dataclass
class Entry:
    id: int
    # text | thinking | tool | turn | note | warning | error | answer | amend | submit | stopping
    kind: str
    turn_id: str | None
    text: str           # the display text, in full
    tool: str | None = None
    tool_use_id: str | None = None
    input: dict | None = None
    status: str = ""    # tool: pending | ok | error; turn: done | failed | interrupted
    result: str = ""    # the tool result's summary; a failed turn's reason
    images: list[str] = field(default_factory=list)
    # A finished turn's step count and cost.
    steps: int | None = None
    cost: float | None = None


def tool_title(entry: Entry) -> str:
    """'exec · add lid', 'render · overlay v1', 'ask · Bevel the lid?'."""
    inp = entry.input or {}
    tool = entry.tool or "tool"
    if tool == "exec":
        detail = inp.get("label") or _first_line(inp.get("code", ""))
    elif tool == "inspect":
        detail = " ".join(str(v) for v in (inp.get("query"), inp.get("name")) if v)
    elif tool == "render":
        source = f"v{inp['view']}" if inp.get("view") is not None else ("camera" if inp.get("camera") else "")
        detail = " ".join(v for v in (inp.get("mode", ""), source) if v)
    elif tool == "ask":
        detail = inp.get("question", "")
    elif tool == "request":
        detail = f"amendment {inp['amend']}" if inp.get("amend") is not None else "bundle"
    else:
        detail = inp.get("label") or ""
    return f"{tool} · {detail}" if detail else tool


def tool_detail(entry: Entry, max_lines: int = 40) -> list[str]:
    """The call's code (or input JSON), then its result lines."""
    inp = entry.input or {}
    if entry.tool == "exec" and isinstance(inp.get("code"), str):
        lines = inp["code"].splitlines()
    else:
        lines = json.dumps(inp, indent=1, ensure_ascii=False).splitlines() if inp else []
    if entry.status != "pending":
        result = entry.result.splitlines()[:RESULT_LINES] or ["(no output)"]
        lines += [f"→ {entry.status}:"] + [f"  {line}" for line in result]
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [f"… {len(lines) - max_lines + 1} more lines"]
    return lines


def wrap(text: str, width_px: int, scale: float = 1.0) -> list[str]:
    """Splits text into lines that fit a sidebar this many pixels wide."""
    chars = max(12, int(width_px / (CHAR_PX * max(scale, 0.1))))
    out = []
    for paragraph in text.splitlines() or [""]:
        out += textwrap.wrap(paragraph, chars, break_long_words=True, break_on_hyphens=False) or [""]
    return out


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


class Stream:
    def __init__(self, maxlen: int = MAX_ENTRIES):
        self._entries: deque[Entry] = deque()
        self._maxlen = maxlen
        self._tools: dict[str, Entry] = {}
        self._next_id = 1

    def _add(self, kind: str, text: str, turn_id: str | None, **fields) -> Entry:
        entry = Entry(id=self._next_id, kind=kind, turn_id=turn_id, text=text, **fields)
        self._next_id += 1
        self._entries.append(entry)
        while len(self._entries) > self._maxlen:
            old = self._entries.popleft()
            if old.tool_use_id:
                self._tools.pop(old.tool_use_id, None)
        return entry

    def append(self, name: str, data: dict) -> Entry | None:
        """Adds the entry for one agent event, or None for events the sidebar
        skips. A tool result completes its tool call's entry."""
        turn = data.get("turn_id")
        if name == Event.TEXT:
            return self._add("text", data.get("text", ""), turn)
        if name == Event.THINKING:
            return self._add("thinking", data.get("text", ""), turn)
        if name == Event.TOOL_USE:
            entry = self._add("tool", "", turn, tool=data.get("tool"), tool_use_id=data.get("tool_use_id"),
                              input=data.get("input") or {}, status="pending")
            entry.text = tool_title(entry)
            if entry.tool_use_id:
                self._tools[entry.tool_use_id] = entry
            return entry
        if name == Event.TOOL_RESULT:
            entry = self._tools.get(data.get("tool_use_id"))
            if entry is None:
                entry = self._add("tool", "tool result", turn, tool_use_id=data.get("tool_use_id"))
            entry.status = "error" if data.get("is_error") else "ok"
            entry.result = data.get("summary") or ""
            entry.images = list(data.get("images") or [])
            return entry
        if name == Event.TURN_FINISHED:
            status = turn_status(data)
            cost = data.get("cost_usd")
            cost = float(cost) if isinstance(cost, (int, float)) else None
            cost_text = f", ${cost:.4f}" if cost is not None else ""
            return self._add("turn", f"Turn {status} ({data.get('num_turns')} steps{cost_text})", turn,
                             status=status, steps=data.get("num_turns"), cost=cost,
                             result=failure_reason(data) if status == "failed" else "")
        if name == Event.ERROR:
            return self._add("error", f"Error {data.get('code')}: {data.get('message')}", turn)
        if name == Event.AMEND_DELIVERED:
            via = "with a tool result" if data.get("via") == "tool_result" else "as a follow-up message"
            return self._add("note", f"Amendment {data.get('amend')} delivered {via}", turn)
        if name == Event.LOG and data.get("level") in ("warning", "error"):
            return self._add("warning" if data["level"] == "warning" else "error",
                             f"[{data['level']}] {data.get('message')}", turn)
        return None

    def note(self, text: str, kind: str = "note", turn_id: str | None = None) -> Entry:
        return self._add(kind, text, turn_id)

    def entries(self, last: int | None = None) -> list[Entry]:
        items = list(self._entries)
        return items[-last:] if last else items

    def lines(self, last: int = 15) -> list[str]:
        out = []
        for entry in self.entries(last):
            text = _first_line(entry.text)
            if entry.kind == "tool":
                text = f"> {text}" + (f" [{entry.status}]" if entry.status != "ok" else "")
            out.append(text[:LINE_CHARS])
        return out

    def images(self) -> list[str]:
        return [path for entry in self._entries for path in entry.images]


def turn_status(data: dict) -> str:
    if data.get("interrupted"):
        return "interrupted"
    return "failed" if data.get("is_error") else "done"


FAILURES = {
    "error_max_turns": "Claude ran out of steps",
    "error_max_budget_usd": "the turn reached its budget",
    "error_during_execution": "Claude stopped with an error",
    "session_ended": "the session ended",
}
REASON_CHARS = 120


def failure_reason(data: dict) -> str:
    """Why a turn failed, in a few words: its first error line, else what
    its subtype means."""
    errors = [e for e in data.get("errors") or [] if isinstance(e, str) and e.strip()]
    if errors:
        reason = _first_line(errors[0])
        return reason if len(reason) <= REASON_CHARS else reason[:REASON_CHARS - 1] + "…"
    subtype = data.get("subtype") or ""
    return FAILURES.get(subtype, subtype.replace("_", " ") or "unknown error")


def local_entry(stream: "Stream", name: str, data: dict, turn_id: str | None) -> Entry | None:
    """The entry for something recorded on Blender's side of a turn (an
    amendment, an answer, an interrupt), or None for records the
    conversation does not show."""
    if name == "amend":
        strokes = data.get("strokes") or 0
        text = (data.get("text") or "").strip()
        if strokes:
            drawn = f"{strokes} new stroke{'s' if strokes != 1 else ''}"
            text = f"{text} (+ {drawn})" if text else drawn
        return stream.note(text or "(new strokes only)", kind="amend", turn_id=turn_id)
    if name == "answer":
        return stream.note(data.get("answer") or "", kind="answer", turn_id=turn_id)
    if name == "interrupt":
        how = "the turn start will be restored" if data.get("mode") == "restore" else "keeping the changes"
        # Its own kind: the running turn's phase line and the stopped turn's
        # end line say the same, so the sidebar leaves it out.
        return stream.note(f"Stopping: {how}", kind="stopping", turn_id=turn_id)
    if name == "amend_returned":
        return stream.note(f"Amendment {data.get('amend')} did not reach Claude ({data.get('reason')})",
                           turn_id=turn_id)
    return None


def entries_from_records(records: list[dict], turn_id: str | None = None) -> list[Entry]:
    """A finished turn's entries, replayed from its transcript.jsonl records
    the way the live stream built them."""
    stream = Stream(maxlen=10_000)
    for record in records:
        data = record.get("data") or {}
        if record.get("type") == "event":
            stream.append(record.get("name", ""), {**data, "turn_id": data.get("turn_id") or turn_id})
        elif record.get("type") == "local":
            local_entry(stream, record.get("name", ""), data, turn_id)
    return stream.entries()


class TranscriptWriter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, msg: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n")

    def write_local(self, name: str, data: dict) -> None:
        """A record of something that happened on Blender's side (an amendment,
        an answer, an interrupt), beside the agent's events."""
        self.write({"v": protocol.VERSION, "type": "local", "name": name, "data": data})
