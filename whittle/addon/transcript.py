# SPDX-License-Identifier: GPL-3.0-or-later
"""The full transcript of a session as readable text, for a Text datablock."""

import json
import logging

from .. import formats
from ..protocol import Event
from .stream import turn_status

log = logging.getLogger("whittle")

TEXT_NAME = "Whittle Transcript"
RESULT_LINES = 30


def _indent(text: str, prefix: str = "    ") -> list[str]:
    return [prefix + line for line in (text.splitlines() or [""])]


def _event_lines(name: str, data: dict) -> list[str]:
    if name == Event.TURN_STARTED:
        return []
    if name == Event.TEXT:
        return ["", *data.get("text", "").splitlines()]
    if name == Event.THINKING:
        return ["", "(thinking)", *_indent(data.get("text", ""))]
    if name == Event.TOOL_USE:
        inp = data.get("input") or {}
        lines = ["", f"> {data.get('tool')}" + (f" ({inp['label']})" if inp.get("label") else "")]
        if isinstance(inp.get("code"), str):
            lines += _indent(inp["code"])
        elif inp:
            lines += _indent(json.dumps(inp, indent=1, ensure_ascii=False))
        return lines
    if name == Event.TOOL_RESULT:
        flag = "error" if data.get("is_error") else "ok"
        summary = (data.get("summary") or "").splitlines()[:RESULT_LINES]
        lines = [f"  < {flag}:"] + [f"    {line}" for line in summary]
        lines += [f"    image: {path}" for path in data.get("images") or []]
        return lines
    if name == Event.TURN_FINISHED:
        cost = data.get("cost_usd")
        cost_text = f", ${cost:.4f}" if isinstance(cost, (int, float)) else ""
        lines = ["", f"Turn {turn_status(data)}: {data.get('num_turns')} steps{cost_text}"]
        lines += [f"  error: {e}" for e in data.get("errors") or []]
        return lines
    if name == Event.ERROR:
        return [f"! error {data.get('code')}: {data.get('message')}"]
    if name == Event.AMEND_DELIVERED:
        return [f"  (amendment {data.get('amend')} delivered via {data.get('via')})"]
    return []


def _local_lines(name: str, data: dict) -> list[str]:
    if name == "submit":
        return []
    if name == "amend":
        strokes = f", strokes in {data['bundle_dir']}" if data.get("bundle_dir") else ""
        return ["", f">> Amendment {data.get('amend')}: {data.get('text') or '(new strokes only)'}{strokes}"]
    if name == "answer":
        return [f">> Question: {data.get('question')}", f">> Answer: {data.get('answer')}"]
    if name == "interrupt":
        mode = "restore the turn start" if data.get("mode") == "restore" else "keep the partial edit"
        return ["", f">> Interrupted ({mode})"]
    if name == "restored":
        return [f">> Restored the turn start: {', '.join(data.get('objects') or []) or 'nothing'}"]
    if name == "target_edited":
        edits = ", ".join(f"{e['name']} ({e['kind']})" for e in data.get("edits") or [])
        return [f">> You edited the target: {edits}"]
    if name == "amend_returned":
        return [f">> Amendment {data.get('amend')} was not delivered: {data.get('reason')}"]
    return [f">> {name}: {json.dumps(data, ensure_ascii=False)}"]


def format_transcript(records: list[dict]) -> str:
    """The records of one or more transcript.jsonl files as plain text: turn
    headers with their prompt, the agent's text, tool calls in full with their
    results, and what the user did during each turn."""
    lines = []
    for record in records:
        data = record.get("data") or {}
        if record.get("type") == "local" and record.get("name") == "submit":
            if lines:
                lines.append("")
            heading = f"Turn {data.get('node')}"
            lines += ["=" * 60, heading, "=" * 60]
            lines += [f"Prompt: {data.get('prompt') or '(sketch only)'}"]
            if data.get("targets"):
                lines.append(f"Target: {', '.join(data['targets'])}")
            continue
        if record.get("type") == "local":
            lines += _local_lines(record.get("name", ""), data)
        elif record.get("type") == "event":
            lines += _event_lines(record.get("name", ""), data)
    return "\n".join(lines).strip() + "\n"


def session_records(session: formats.SessionDir) -> list[dict]:
    """Every node's transcript.jsonl, in node order."""
    records = []
    for node in session.node_ids():
        path = session.transcript_path(node)
        if not path.is_file():
            continue
        has_header = False
        node_records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipped a bad line in %s", path)
                continue
            has_header = has_header or (record.get("type") == "local" and record.get("name") == "submit")
            node_records.append(record)
        if not has_header:
            node_records.insert(0, {"type": "local", "name": "submit", "data": {"node": node}})
        records += node_records
    return records


def open_transcript(session: formats.SessionDir, context=None):
    """Writes the session's transcript into the Whittle Transcript text and
    shows it in a Text Editor when there is a window for one."""
    import bpy

    from . import editors

    text = bpy.data.texts.get(TEXT_NAME) or bpy.data.texts.new(TEXT_NAME)
    text.clear()
    text.write(format_transcript(session_records(session)))
    editors.show_text(context or bpy.context, text)
    return text
