# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent end of the bridge: an asyncio client speaking the JSON-lines protocol."""

import asyncio
import logging
import os
import traceback
from collections.abc import Awaitable, Callable

from .. import __version__, protocol
from ..protocol import ErrorCode

log = logging.getLogger("whittle.agent")

HANDSHAKE_TIMEOUT = 10.0

Handler = Callable[[str, dict], Awaitable[dict]]


class BridgeCallError(Exception):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code = str(code)
        self.message = message
        self.detail = detail


class HandshakeError(Exception):
    pass


class Connection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._decoder = protocol.LineDecoder()
        self._ids = protocol.IdCounter("a")
        self._pending: dict[str, asyncio.Future] = {}
        self._handler: Handler | None = None
        self._tasks: set[asyncio.Task] = set()
        self._write_lock = asyncio.Lock()
        self._inbox: list[dict] = []
        self.closed = asyncio.Event()

    @classmethod
    async def open(cls, port: int, token: str, mode: str, *, host: str = "127.0.0.1",
                   timeout: float = HANDSHAKE_TIMEOUT) -> "Connection":
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout)
        except (OSError, TimeoutError) as exc:
            raise HandshakeError(f"cannot connect to Blender on port {port}: {exc}") from None
        conn = cls(reader, writer)
        await conn._send(protocol.hello(token, os.getpid(), __version__, mode))
        try:
            reply = await asyncio.wait_for(conn._read_one(), timeout)
        except TimeoutError:
            await conn.close()
            raise HandshakeError("no welcome from Blender") from None
        if reply is None or reply.get("type") != "welcome" or reply.get("protocol") != protocol.VERSION:
            await conn.close()
            raise HandshakeError(f"handshake rejected: {reply!r}")
        return conn

    def set_handler(self, handler: Handler) -> None:
        self._handler = handler

    async def call(self, method: str, params: dict, timeout: float | None = 300.0) -> dict:
        if self.closed.is_set():
            raise BridgeCallError(ErrorCode.AGENT_CRASHED, "Blender connection is closed")
        call_id = self._ids.next()
        fut = asyncio.get_running_loop().create_future()
        self._pending[call_id] = fut
        try:
            await self._send(protocol.call(call_id, method, params))
            if timeout is None:
                return await fut
            try:
                return await asyncio.wait_for(fut, timeout)
            except TimeoutError:
                raise BridgeCallError(ErrorCode.TIMEOUT,
                                      f"{method} got no reply within {timeout:g} s") from None
        finally:
            self._pending.pop(call_id, None)

    async def send_event(self, name: str, data: dict) -> None:
        if self.closed.is_set():
            return
        try:
            await self._send(protocol.event(name, data))
        except ConnectionError:
            log.warning("dropped event %s: connection lost", name)

    async def serve(self) -> None:
        """Reads until EOF, routing results to callers and calls to the handler."""
        try:
            for msg in self._inbox:
                self._dispatch(msg)
            self._inbox.clear()
            while True:
                chunk = await self._reader.read(65536)
                if not chunk:
                    break
                for msg in self._decoder.feed(chunk):
                    self._dispatch(msg)
        except (ConnectionError, protocol.ProtocolError) as exc:
            log.error("bridge read failed: %s", exc)
        finally:
            self._fail_pending()
            self.closed.set()

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._fail_pending()
        self.closed.set()
        if not self._writer.is_closing():
            self._writer.close()
        try:
            await asyncio.wait_for(self._writer.wait_closed(), 2.0)
        except (ConnectionError, TimeoutError):
            pass

    # -- internals ------------------------------------------------------------

    async def _send(self, msg: dict) -> None:
        async with self._write_lock:
            self._writer.write(protocol.encode(msg))
            await self._writer.drain()

    async def _read_one(self) -> dict | None:
        while not self._inbox:
            chunk = await self._reader.read(65536)
            if not chunk:
                return None
            self._inbox.extend(self._decoder.feed(chunk))
        return self._inbox.pop(0)

    def _dispatch(self, msg: dict) -> None:
        kind = msg["type"]
        if kind == "result":
            fut = self._pending.get(msg.get("id"))
            if fut is None or fut.done():
                log.warning("result for unknown call %r dropped", msg.get("id"))
                return
            if msg.get("ok"):
                fut.set_result(msg.get("data") or {})
            else:
                e = msg.get("error") or {}
                fut.set_exception(BridgeCallError(
                    e.get("code", ErrorCode.INTERNAL), e.get("message", ""), e.get("detail")))
        elif kind == "call":
            task = asyncio.create_task(self._serve_call(msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            log.warning("unexpected %s message ignored", kind)

    async def _serve_call(self, msg: dict) -> None:
        call_id = msg.get("id", "")
        method = msg.get("method", "")
        params = msg.get("params")
        if not isinstance(params, dict):
            reply = protocol.err(call_id, ErrorCode.BAD_REQUEST, "params must be an object")
        elif self._handler is None:
            reply = protocol.err(call_id, ErrorCode.UNKNOWN_METHOD, f"no handler for {method}")
        else:
            try:
                reply = protocol.ok(call_id, await self._handler(method, params))
            except BridgeCallError as exc:
                reply = protocol.err(call_id, exc.code, exc.message, exc.detail)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("handler for %s failed", method)
                reply = protocol.err(call_id, ErrorCode.INTERNAL, str(exc), traceback.format_exc())
        try:
            await self._send(reply)
        except ConnectionError:
            log.warning("could not reply to %s: connection lost", method)

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(BridgeCallError(
                    ErrorCode.AGENT_CRASHED, "Blender connection closed"))
