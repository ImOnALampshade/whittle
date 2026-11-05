# SPDX-License-Identifier: GPL-3.0-or-later
"""Wire protocol shared by the Blender bridge and the agent process.

JSON lines over a local TCP socket. Stdlib only: both Blender's Python and the
agent venv import this module.
"""

import json
from enum import StrEnum

VERSION = 1
MAX_LINE = 16 * 1024 * 1024


class ProtocolError(Exception):
    """A message that breaks the wire format, such as bad JSON or an oversized line."""
    pass


class ErrorCode(StrEnum):
    """The codes a failed call's result can carry."""
    BAD_REQUEST = "bad_request"
    UNKNOWN_METHOD = "unknown_method"
    NOT_FOUND = "not_found"
    BUSY = "busy"
    INTERRUPTED = "interrupted"
    NO_SESSION = "no_session"
    AGENT_CRASHED = "agent_crashed"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


class Method:
    """Names of the calls each side can make of the other."""
    # Blender -> agent
    START_SESSION = "start_session"
    SUBMIT = "submit"
    AMEND = "amend"
    INTERRUPT = "interrupt"
    PING = "ping"
    SHUTDOWN = "shutdown"
    # agent -> Blender
    EXEC = "exec"
    INSPECT = "inspect"
    RENDER = "render"
    CHECKPOINT = "checkpoint"
    RESTORE_CHECKPOINT = "restore_checkpoint"
    ASK = "ask"


class Event:
    """Names of the events the agent sends Blender; none gets a reply."""
    STATUS = "status"
    TURN_STARTED = "turn_started"
    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    TURN_FINISHED = "turn_finished"
    AMEND_DELIVERED = "amend_delivered"
    ERROR = "error"
    LOG = "log"
    MODELS = "models"


# Status state the agent reports when its SDK session stops on its own while
# the process lives on.
SESSION_ENDED = "session_ended"

MESSAGE_TYPES = frozenset({"hello", "welcome", "call", "result", "event"})


def encode(msg: dict) -> bytes:
    """One message as a line of UTF-8 JSON, newline included."""
    # Lone surrogates (say, from os.fsdecode of a non-UTF-8 filename) cannot be
    # UTF-8 encoded; backslashreplace turns them into JSON \uXXXX escapes, which
    # every JSON decoder reads back.
    text = json.dumps(msg, separators=(",", ":"), ensure_ascii=False) + "\n"
    return text.encode("utf-8", "backslashreplace")


class LineDecoder:
    """Splits a byte stream into decoded messages, keeping any partial tail."""

    def __init__(self, max_line: int = MAX_LINE):
        self.max_line = max_line
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        """Takes more bytes and returns the messages they complete, skipping blank
        lines. Raises ProtocolError on a bad or oversized line."""
        self._buf.extend(data)
        messages = []
        while True:
            end = self._buf.find(b"\n")
            if end < 0:
                break
            if end > self.max_line:
                raise ProtocolError(f"line of {end} bytes exceeds {self.max_line}")
            line = bytes(self._buf[:end])
            del self._buf[: end + 1]
            if line.strip():
                messages.append(decode_line(line))
        if len(self._buf) > self.max_line:
            raise ProtocolError(f"unterminated line exceeds {self.max_line} bytes")
        return messages


def decode_line(line: bytes) -> dict:
    """Parses one line, raising ProtocolError unless it is a JSON object with this
    protocol's version and a known type."""
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON line: {exc}") from None
    if not isinstance(msg, dict):
        raise ProtocolError("message is not a JSON object")
    if msg.get("v") != VERSION:
        raise ProtocolError(f"unsupported message version {msg.get('v')!r}")
    if msg.get("type") not in MESSAGE_TYPES:
        raise ProtocolError(f"unknown message type {msg.get('type')!r}")
    return msg


def hello(token: str, pid: int, agent_version: str, mode: str) -> dict:
    """The agent's first message; Blender accepts it only with the right token and
    protocol version."""
    return {"v": VERSION, "type": "hello", "token": token, "protocol": VERSION,
            "pid": pid, "agent_version": agent_version, "mode": mode}


def welcome() -> dict:
    """Blender's reply to an accepted hello."""
    return {"v": VERSION, "type": "welcome", "protocol": VERSION}


def call(id: str, method: str, params: dict) -> dict:
    """A request from either side, answered by a result with the same id."""
    return {"v": VERSION, "type": "call", "id": id, "method": method, "params": params}


def ok(id: str, data: dict) -> dict:
    """The result of a call that succeeded."""
    return {"v": VERSION, "type": "result", "id": id, "ok": True, "data": data}


def err(id: str, code: str, message: str, detail: str | None = None) -> dict:
    """The result of a call that failed."""
    return {"v": VERSION, "type": "result", "id": id, "ok": False,
            "error": error_body(code, message, detail)}


def error_body(code: str, message: str, detail: str | None = None) -> dict:
    """The error of a failed result. The bridge also hands one to callbacks whose
    call will never get a result."""
    return {"code": str(code), "message": message, "detail": detail}


def event(name: str, data: dict) -> dict:
    """A one-way message from the agent to Blender."""
    return {"v": VERSION, "type": "event", "name": name, "data": data}


class IdCounter:
    """Makes call ids: each side's own prefix, then a running number."""

    def __init__(self, prefix: str):
        self.prefix = prefix
        self._n = 0

    def next(self) -> str:
        """Returns an id not used before."""
        self._n += 1
        return f"{self.prefix}{self._n}"
