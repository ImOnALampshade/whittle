# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender end of the bridge: a non-blocking socket drained from a timer, and a
queue that runs the agent's calls on the main thread."""

import hmac
import logging
import socket
import time
import traceback
from collections import deque
from collections.abc import Callable

import bpy

from .. import protocol
from ..protocol import ErrorCode, Method

log = logging.getLogger("whittle")

TICK_BUDGET = 0.030
RECV_SIZE = 65536

# Renders take long enough that one per tick keeps the UI responsive.
SLOW_METHODS = frozenset({Method.RENDER})
# Calls that change the scene (a render swaps the camera and what renders,
# a checkpoint writes the objects out): they wait while the user is in the
# middle of a modal operation, at most this long.
SCENE_METHODS = frozenset({Method.EXEC, Method.RESTORE_CHECKPOINT, Method.RENDER, Method.CHECKPOINT})
MODAL_WAIT = 10.0


class BridgeError(Exception):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.message = message
        self.detail = detail


class Deferred:
    """Returned by a handler whose answer comes later through Bridge.resolve()."""


Handler = Callable[[dict], "dict | Deferred"]
ResultCallback = Callable[[bool, dict], None]


class Bridge:
    def __init__(self, process, listener: socket.socket, token: str,
                 handlers: dict[str, Handler], on_event: Callable[[dict], None]):
        self.process = process
        self.listener = listener
        self.token = token
        self.handlers = handlers
        self.on_event = on_event
        self.sock: socket.socket | None = None
        self.handshaken = False
        self.queue: deque[tuple[str, str, dict]] = deque()
        self.pending: dict[str, ResultCallback | None] = {}
        self.deferred: dict[str, str] = {}
        self.interrupted = False
        # When the call at the head of the queue began waiting for the
        # user's modal operation to end.
        self._modal_since: float | None = None
        self.closed = False
        self.ticks = 0
        self._decoder = protocol.LineDecoder()
        self._outbox = bytearray()
        self._ids = protocol.IdCounter("b")

    # -- public API -----------------------------------------------------------

    def call(self, method: str, params: dict, on_result: ResultCallback | None = None) -> str:
        call_id = self._ids.next()
        self.pending[call_id] = on_result
        self._send(protocol.call(call_id, method, params))
        return call_id

    def resolve(self, call_id: str, data: dict) -> bool:
        if self.deferred.pop(call_id, None) is None:
            return False
        self._reply(call_id, data)
        return True

    def fail_deferred(self, code: str, message: str) -> None:
        for call_id in list(self.deferred):
            del self.deferred[call_id]
            self._send(protocol.err(call_id, code, message))

    def set_interrupted(self, value: bool) -> None:
        """While set, queued agent calls are refused instead of run."""
        self.interrupted = value

    def tick(self) -> float | None:
        if self.closed:
            return None
        self.ticks += 1
        if not self.handshaken:
            self._accept()
        if self.sock is not None:
            self._read()
        self.process.poll()
        if self.closed:
            return None
        self._run_queue()
        self.flush()
        return self._interval()

    def flush(self) -> None:
        while self._outbox and self.sock is not None:
            try:
                sent = self.sock.send(self._outbox)
            except BlockingIOError:
                return
            except OSError as exc:
                self._outbox.clear()
                self._lost(f"send failed: {exc}")
                return
            del self._outbox[:sent]

    def fail_pending(self, code: str, message: str) -> None:
        pending, self.pending = self.pending, {}
        for on_result in pending.values():
            if on_result is not None:
                on_result(False, protocol.error_body(code, message))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.queue.clear()
        self.deferred.clear()
        for s in (self.sock, self.listener):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self.sock = None
        self.listener = None

    @property
    def busy(self) -> bool:
        return bool(self.queue or self._outbox)

    # -- handshake and reading ----------------------------------------------

    def _accept(self) -> None:
        if self.sock is None and self.listener is not None:
            try:
                sock, _addr = self.listener.accept()
            except BlockingIOError:
                return
            sock.setblocking(False)
            self.sock = sock

    def _read(self) -> None:
        while self.sock is not None:
            try:
                chunk = self.sock.recv(RECV_SIZE)
            except BlockingIOError:
                return
            except OSError as exc:
                self._lost(f"receive failed: {exc}")
                return
            if not chunk:
                self._lost("the agent closed the connection")
                return
            try:
                messages = self._decoder.feed(chunk)
            except protocol.ProtocolError as exc:
                self.process.fail(f"protocol error: {exc}")
                return
            for msg in messages:
                if self.closed:
                    return
                self._dispatch(msg)

    def _dispatch(self, msg: dict) -> None:
        if not self.handshaken:
            self._handshake(msg)
            return
        kind = msg["type"]
        if kind == "result":
            if msg.get("id") not in self.pending:
                log.warning("result for unknown call %r dropped", msg.get("id"))
                return
            on_result = self.pending.pop(msg["id"])
            if on_result is not None:
                ok = bool(msg.get("ok"))
                _guarded(on_result, ok, (msg.get("data") or {}) if ok else (msg.get("error") or {}))
                redraw_view3d()
        elif kind == "event":
            _guarded(self.on_event, msg)
            redraw_view3d()
        elif kind == "call":
            params = msg.get("params")
            self.queue.append((msg.get("id", ""), msg.get("method", ""),
                               params if isinstance(params, dict) else None))
        else:
            log.warning("unexpected %s message ignored", kind)

    def _handshake(self, msg: dict) -> None:
        token = msg.get("token")
        if msg.get("type") != "hello":
            self.process.fail(f"expected hello, got {msg.get('type')}")
        elif not isinstance(token, str) or not hmac.compare_digest(token, self.token):
            self.process.fail("the agent sent a wrong token")
        elif msg.get("protocol") != protocol.VERSION:
            self.process.fail(f"protocol {msg.get('protocol')} is not {protocol.VERSION}")
        else:
            self.handshaken = True
            self.listener.close()
            self.listener = None
            self._send(protocol.welcome())
            self.process.on_handshake(msg)

    def _lost(self, reason: str) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self.process.on_disconnect(reason)

    # -- the main-thread queue ----------------------------------------------

    def _run_queue(self) -> None:
        start = time.perf_counter()
        ran = 0
        while self.queue and not self.closed:
            if ran and time.perf_counter() - start >= TICK_BUDGET:
                break
            if self._wait_for_modal(self.queue[0][1]):
                break
            call_id, method, params = self.queue.popleft()
            ran += 1
            self._run_call(call_id, method, params)
            if method in SLOW_METHODS:
                break
        if ran:
            # A call can change what the sidebar shows (a question to answer,
            # a warning), and timers do not redraw regions by themselves.
            redraw_view3d()

    def _wait_for_modal(self, method: str) -> bool:
        """Whether a call that changes the scene waits: the user is in the
        middle of a modal operation (a transform, a stroke, the knife), and
        changing or freeing data under it can crash Blender. Some add-ons
        keep a modal running all the time, so a call waits MODAL_WAIT at
        most. Calls that only read go at once."""
        if method not in SCENE_METHODS or self.interrupted or not modal_running():
            self._modal_since = None
            return False
        now = time.monotonic()
        if self._modal_since is None:
            self._modal_since = now
        if now - self._modal_since < MODAL_WAIT:
            return True
        self._modal_since = None
        return False

    def _run_call(self, call_id: str, method: str, params: dict | None) -> None:
        if self.interrupted:
            self._send(protocol.err(call_id, ErrorCode.INTERRUPTED,
                                     "the user stopped this turn; make no more changes"))
            return
        if params is None:
            self._send(protocol.err(call_id, ErrorCode.BAD_REQUEST, "params must be an object"))
            return
        handler = self.handlers.get(method)
        if handler is None:
            self._send(protocol.err(call_id, ErrorCode.UNKNOWN_METHOD, f"unknown method {method!r}"))
            return
        try:
            result = handler(params)
        except BridgeError as exc:
            self._send(protocol.err(call_id, exc.code, exc.message, exc.detail))
            return
        except Exception as exc:
            log.exception("handler for %s failed", method)
            self._send(protocol.err(call_id, ErrorCode.INTERNAL, str(exc), traceback.format_exc()))
            return
        if isinstance(result, Deferred):
            self.deferred[call_id] = method
        else:
            self._reply(call_id, result)

    # -- helpers --------------------------------------------------------------

    def _send(self, msg: dict) -> None:
        if not self.closed:
            self._outbox.extend(protocol.encode(msg))

    def _reply(self, call_id: str, data: dict) -> None:
        """Sends a result, or an internal error when the result cannot be encoded,
        so a bad handler return can never leave the agent waiting."""
        try:
            line = protocol.encode(protocol.ok(call_id, data))
        except (TypeError, ValueError) as exc:
            log.exception("result for %s cannot be encoded", call_id)
            line = protocol.encode(protocol.err(call_id, ErrorCode.INTERNAL,
                                                f"the result cannot be encoded: {exc}"))
        if not self.closed:
            self._outbox.extend(line)

    def _interval(self) -> float:
        if self.busy:
            return 0.01
        return self.process.tick_interval()


def _guarded(callback, *args) -> None:
    # A failing UI callback (say, a transcript write) must not stop the bridge
    # from draining the socket.
    try:
        callback(*args)
    except Exception:
        log.exception("bridge callback %r failed", callback)


def modal_running() -> bool:
    """Whether some window runs a modal operator (a transform, a stroke...)."""
    wm = bpy.context.window_manager
    if wm is None:
        return False
    try:
        return any(window.modal_operators for window in wm.windows)
    except (AttributeError, ReferenceError):
        return False


def redraw_view3d() -> None:
    """Tags the 3D Viewports, where the sidebar lives, for redraw."""
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# -- timer --------------------------------------------------------------------

_timer: Callable[[], float | None] | None = None


def start_timer(bridge: Bridge) -> None:
    global _timer
    stop_timer()

    def tick() -> float | None:
        global _timer
        try:
            interval = bridge.tick()
        except Exception as exc:
            # Blender drops a timer that raises, which would leave the agent
            # running with nobody reading its socket; end it visibly instead.
            log.exception("bridge tick failed")
            try:
                bridge.process.crash(f"internal error in the bridge: {exc}")
            except Exception:
                log.exception("cannot stop the agent after a bridge failure")
            interval = None
        if interval is None and _timer is tick:
            _timer = None
        return interval

    _timer = tick
    bpy.app.timers.register(tick, first_interval=0.01, persistent=True)


def stop_timer() -> None:
    global _timer
    if _timer is not None and bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    _timer = None


def timer_registered() -> bool:
    return _timer is not None and bpy.app.timers.is_registered(_timer)
