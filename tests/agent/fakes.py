# SPDX-License-Identifier: GPL-3.0-or-later
"""Test doubles for the agent side: a fake Blender end of the bridge and a fake
ClaudeSDKClient that plays scripted SDK messages."""

import asyncio
import json

from whittle import protocol


class FakeBlender:
    """An in-process asyncio server speaking the bridge protocol.

    `responses` maps a method to a dict (sent as ok data), a callable
    (params -> dict, may raise FakeError), or a FakeError.
    """

    def __init__(self, token="secret", responses=None, welcome=None):
        self.token = token
        self.responses = dict(responses or {})
        self.welcome = welcome if welcome is not None else protocol.welcome()
        self.calls: list[tuple[str, dict]] = []
        self.events: list[dict] = []
        self.hello: dict | None = None
        self.connected = asyncio.Event()
        self.handshaken = asyncio.Event()
        self.disconnected = asyncio.Event()
        self._event_added = asyncio.Condition()
        self._ids = protocol.IdCounter("b")
        self._pending: dict[str, asyncio.Future] = {}
        self._writer = None
        self._server = None
        self._hold: dict[str, asyncio.Future] = {}

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            self._writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def hold(self, method: str) -> asyncio.Future:
        """Delays the next reply to `method` until the returned future is set."""
        fut = asyncio.get_running_loop().create_future()
        self._hold[method] = fut
        return fut

    async def call(self, method: str, params: dict | None = None, timeout: float = 5.0):
        call_id = self._ids.next()
        fut = asyncio.get_running_loop().create_future()
        self._pending[call_id] = fut
        self._send(protocol.call(call_id, method, params or {}))
        return await asyncio.wait_for(fut, timeout)

    async def wait_event(self, name: str, timeout: float = 5.0, where=None) -> dict:
        def find():
            for ev in self.events:
                if ev["name"] == name and (where is None or where(ev["data"])):
                    return ev
            return None

        async def wait():
            async with self._event_added:
                await self._event_added.wait_for(lambda: find() is not None)
            return find()

        return await asyncio.wait_for(wait(), timeout)

    def event_names(self) -> list[str]:
        return [e["name"] for e in self.events]

    def _send(self, msg: dict) -> None:
        self._writer.write(protocol.encode(msg))

    async def _serve(self, reader, writer):
        self._writer = writer
        decoder = protocol.LineDecoder()
        self.connected.set()
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                for msg in decoder.feed(chunk):
                    await self._handle(msg)
        finally:
            self.disconnected.set()

    async def _handle(self, msg: dict) -> None:
        kind = msg["type"]
        if kind == "hello":
            self.hello = msg
            if msg.get("token") == self.token:
                self._send(self.welcome)
                self.handshaken.set()
            else:
                self._writer.close()
        elif kind == "call":
            self.calls.append((msg["method"], msg["params"]))
            asyncio.create_task(self._reply(msg))
        elif kind == "result":
            fut = self._pending.pop(msg["id"], None)
            if fut and not fut.done():
                fut.set_result((msg["ok"], msg.get("data") if msg["ok"] else msg.get("error")))
        elif kind == "event":
            async with self._event_added:
                self.events.append(msg)
                self._event_added.notify_all()

    async def _reply(self, msg: dict) -> None:
        method = msg["method"]
        held = self._hold.pop(method, None)
        if held is not None:
            await held
        response = self.responses.get(method)
        try:
            if response is None:
                raise FakeError("unknown_method", f"fake Blender has no {method}")
            if isinstance(response, FakeError):
                raise response
            data = response(msg["params"]) if callable(response) else response
            self._send(protocol.ok(msg["id"], data))
        except FakeError as exc:
            self._send(protocol.err(msg["id"], exc.code, exc.message))


class FakeError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message


class StubConnection:
    """Records calls and events for tool handler tests without any socket."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, dict, float | None]] = []
        self.events: list[tuple[str, dict]] = []

    async def call(self, method, params, timeout=300.0):
        self.calls.append((method, params, timeout))
        response = self.responses[method]
        if isinstance(response, Exception):
            raise response
        return response(params) if callable(response) else response

    async def send_event(self, name, data):
        self.events.append((name, data))


class FakeSdkClient:
    """Stands in for ClaudeSDKClient. `script` is a list of turns; each turn is a
    list of SDK message objects, or ("tool", name, input, tool_use_id) tuples that
    run the registered tool handler and yield the assistant tool-use message and
    the user tool-result message, as the CLI would. ("wait", name) pauses the
    turn until the test sets gates[name]. server_info is what
    get_server_info returns (the CLI's initialize response); set_model and
    query calls are logged in order in `log`."""

    instances: list["FakeSdkClient"] = []
    # The initialize response every new client reports; a test sets it.
    server_info: dict | None = None

    def __init__(self, options=None, script=None):
        self.options = options
        self.script = list(script or [])
        self.queries: list[str] = []
        self.log: list[tuple[str, str | None]] = []
        self.interrupts = 0
        self.connected = False
        self.disconnected = False
        self.owner_task = None
        self.task_violations = []
        self.connect_error = None
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._interrupt = asyncio.Event()
        self._bridges = {}
        self._rpc_id = 0
        self.tool_results: list[dict] = []
        self.gates: dict[str, asyncio.Event] = {}
        FakeSdkClient.instances.append(self)

    def gate(self, name: str) -> asyncio.Event:
        return self.gates.setdefault(name, asyncio.Event())

    def _check_task(self, what):
        task = asyncio.current_task()
        if self.owner_task is None:
            self.owner_task = task
        elif task is not self.owner_task and what in ("connect", "disconnect"):
            self.task_violations.append(what)

    async def connect(self, prompt=None):
        from claude_agent_sdk._internal.sdk_mcp_bridge import SdkMcpBridge

        self._check_task("connect")
        if self.connect_error:
            raise self.connect_error
        for key, config in self.options.mcp_servers.items():
            bridge = SdkMcpBridge(key, config["instance"])
            await bridge.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "fake-cli", "version": "0"}}})
            await bridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self._bridges[key] = bridge
        self.connected = True

    async def disconnect(self):
        self._check_task("disconnect")
        self.disconnected = True
        for bridge in self._bridges.values():
            await bridge.aclose()
        self._inbox.put_nowait(None)

    async def query(self, prompt, session_id="default"):
        self.queries.append(prompt)
        self.log.append(("query", prompt))
        turn = self.script.pop(0) if self.script else []
        asyncio.get_running_loop().create_task(self._play(turn))

    async def set_model(self, model=None):
        self.log.append(("set_model", model))

    async def get_server_info(self):
        return FakeSdkClient.server_info

    async def interrupt(self):
        self.interrupts += 1
        self._interrupt.set()

    async def receive_messages(self):
        while True:
            msg = await self._inbox.get()
            if msg is None:
                return
            yield msg

    async def call_tool(self, full_name: str, args: dict) -> dict:
        """Calls a tool through the SDK's own MCP bridge, as the CLI would."""
        _, server, name = full_name.split("__", 2)
        self._rpc_id += 1
        reply = await self._bridges[server].handle({
            "jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/call",
            "params": {"name": name, "arguments": args}})
        return reply["result"]

    async def _play(self, turn):
        from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

        for item in turn:
            if self._interrupt.is_set():
                self._interrupt.clear()
                await self._inbox.put(result_message(terminal_reason="aborted_streaming",
                                                     subtype="error_during_execution"))
                return
            if isinstance(item, tuple) and item[0] == "tool":
                _, name, args, tool_use_id = item
                await self._inbox.put(AssistantMessage(
                    content=[ToolUseBlock(id=tool_use_id, name=name, input=args)], model="fake"))
                result = await self.call_tool(name, args)
                self.tool_results.append(result)
                await self._inbox.put(UserMessage(content=[ToolResultBlock(
                    tool_use_id=tool_use_id, content=result["content"],
                    is_error=result.get("isError"))]))
            elif isinstance(item, tuple) and item[0] == "wait":
                await asyncio.wait_for(self.gate(item[1]).wait(), 5.0)
            elif isinstance(item, tuple) and item[0] == "wait_interrupt":
                await asyncio.wait_for(self._interrupt.wait(), 5.0)
            else:
                await self._inbox.put(item)
            await asyncio.sleep(0)


def result_message(**overrides):
    from claude_agent_sdk import ResultMessage

    fields = dict(subtype="success", duration_ms=12, duration_api_ms=10, is_error=False,
                  num_turns=2, session_id="sess-1", total_cost_usd=0.0123, result="done",
                  terminal_reason="completed")
    fields.update(overrides)
    return ResultMessage(**fields)


def init_message(session_id="sess-1", skills=None):
    from claude_agent_sdk import SystemMessage

    return SystemMessage(subtype="init", data={
        "session_id": session_id, "model": "fake-model", "tools": [],
        "skills": skills if skills is not None else ["whittle:boolean-carve"]})


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True)
