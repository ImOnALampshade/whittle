# SPDX-License-Identifier: GPL-3.0-or-later
"""The Claude Agent SDK runner. The only module that imports claude_agent_sdk."""

import asyncio
import json
import logging
import os
import time
import urllib.parse
import urllib.request

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .. import __version__, formats, models
from ..protocol import SESSION_ENDED, ErrorCode, Event
from . import prompt
from .connection import BridgeCallError
from .store import FolderSessionStore
from .tools import TOOL_NAMES, ToolContext, build_servers, follow_up_text, image_paths, short_name

log = logging.getLogger("whittle.agent")

INTERRUPTED_REASONS = {"aborted_streaming", "aborted_tools"}
STOP_TIMEOUT = 10.0
# ask waits on a person, so the CLI must not time the tool call out.
MCP_TOOL_TIMEOUT_MS = "86400000"
API_URL = "https://api.anthropic.com"
MODELS_TIMEOUT = 10.0
MODELS_PAGES = 5


def inline_skills_from_env() -> bool:
    return os.environ.get("WHITTLE_INLINE_SKILLS", "") not in ("", "0")


def build_options(params: dict, servers: dict, *, inline_skills: bool) -> ClaudeAgentOptions:
    settings = params.get("settings") or {}
    kwargs = dict(
        system_prompt=prompt.build(settings, inline_skills=inline_skills),
        model=params.get("model"),
        tools=[] if inline_skills else ["Skill"],
        allowed_tools=list(TOOL_NAMES),
        permission_mode="dontAsk",
        mcp_servers=servers,
        strict_mcp_config=True,
        setting_sources=[],
        resume=params.get("resume"),
        fork_session=bool(params.get("fork")),
        # Where a branch cuts the resumed conversation: the last message of
        # the history node it starts from.
        resume_session_at=params.get("resume_at"),
        cwd=params["session_dir"],
        env={"MCP_TOOL_TIMEOUT": MCP_TOOL_TIMEOUT_MS,
             "CLAUDE_AGENT_SDK_CLIENT_APP": f"whittle/{__version__}"},
        stderr=lambda line: log.debug("cli: %s", line.rstrip()),
        max_turns=settings.get("max_turns"),
        max_budget_usd=settings.get("max_budget_usd"),
        # The chat's own transcript store: the SDK mirrors every transcript
        # line into it and resumes from it, so the chat carries its
        # conversation wherever its file goes. (File checkpointing must stay
        # off with a store.)
        session_store=FolderSessionStore(params["store_dir"]) if params.get("store_dir") else None,
    )
    if not inline_skills:
        kwargs["plugins"] = [{"type": "local", "path": str(prompt.PLUGIN_DIR)}]
        kwargs["skills"] = [f"{prompt.PLUGIN_NAME}:{name}" for name in prompt.SKILLS]
    return ClaudeAgentOptions(**kwargs)


NO_SKETCH = ("This request has no sketch: no strokes and no sketch views, so there are no "
             "overlay images. Work from the prompt, and self-check with mcp__blender__render "
             "from cameras you place (camera={location, look_at}), not view ids or overlay mode.")


def sketch_size(bundle_dir: str) -> tuple[int, int] | None:
    """(strokes, views) in the request, or None when it cannot be read; the
    request tool reports any problem with the bundle itself."""
    try:
        request = formats.read_json(os.path.join(bundle_dir, "request.json"))
        strokes = formats.read_json(os.path.join(bundle_dir, "strokes.json"))
        return len(strokes["strokes"]), len(request["views"])
    except (formats.FormatError, KeyError, TypeError):
        return None


def submit_text(user_prompt: str, bundle_dir: str, context=(), sketch: tuple[int, int] | None = None) -> str:
    """The turn's first message. `sketch` is (strokes, views) when known: a
    request without views says so, so the agent does not look for overlays
    that were never made."""
    unsketched = sketch is not None and not any(sketch)
    if user_prompt.strip():
        head = user_prompt.strip()
    else:
        head = "(No prompt: work from the reference images.)" if unsketched else "(No prompt: interpret the sketch.)"
    text = f"{head}\n\nRequest bundle: {bundle_dir}\n"
    if unsketched:
        text += NO_SKETCH + "\nCall mcp__whittle__request first to read the request, then follow the turn shape."
    else:
        text += "Call mcp__whittle__request first to read the sketch, then follow the turn shape."
    if context:
        lines = "\n".join(f"- {line}" for line in context)
        text = f"<whittle_context>\n{lines}\n</whittle_context>\n\n{text}"
    return text


def list_api_models(api_key: str, base_url: str | None = None) -> list[dict]:
    """The Models API's pages (GET /v1/models) for an API key. Plain urllib:
    the anthropic package is not in the agent's lock, and this one listing
    is all Whittle asks of the API itself. It uses no tokens, and is made
    once per agent process."""
    base = (base_url or API_URL).rstrip("/")
    pages, after = [], None
    for _ in range(MODELS_PAGES):
        query = {"limit": "1000", **({"after_id": after} if after else {})}
        request = urllib.request.Request(f"{base}/v1/models?{urllib.parse.urlencode(query)}", headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01",
            "user-agent": f"whittle/{__version__}"})
        with urllib.request.urlopen(request, timeout=MODELS_TIMEOUT) as response:
            page = json.loads(response.read().decode("utf-8"))
        pages.append(page)
        after = page.get("last_id")
        if not page.get("has_more") or not after:
            break
    return pages


def turn_cost(results: list, session_total_before: float) -> float | None:
    """The cost of one turn. ResultMessage.total_cost_usd is a running total
    for the SDK session (the SDK resets it only with the conversation), so a
    turn that took several queries costs its last total less the total the
    session had reached before the turn."""
    totals = [r.total_cost_usd for r in results if r.total_cost_usd is not None]
    if not totals:
        return None
    return max(0.0, totals[-1] - session_total_before)


def _tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def map_message(msg, turn_id: str | None) -> list[tuple[str, dict]]:
    """Translates one SDK message into bridge events. ResultMessages are left to
    the runner, which needs them for turn accounting."""
    base = {"turn_id": turn_id}
    if isinstance(msg, SystemMessage):
        if msg.subtype == "init":
            return [(Event.STATUS, {**base, "state": "running", "detail": msg.data.get("model")})]
        return [(Event.LOG, {**base, "level": "debug", "message": f"system {msg.subtype}"})]
    if isinstance(msg, AssistantMessage):
        events = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                events.append((Event.TEXT, {**base, "text": block.text}))
            elif isinstance(block, ThinkingBlock):
                events.append((Event.THINKING, {**base, "text": block.thinking}))
            elif isinstance(block, ToolUseBlock):
                events.append((Event.TOOL_USE, {**base, "tool_use_id": block.id,
                                                "tool": short_name(block.name), "input": block.input}))
        if msg.error:
            events.append((Event.ERROR, {**base, "code": "assistant_error", "message": str(msg.error)}))
        return events
    if isinstance(msg, UserMessage):
        events = []
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    text = _tool_result_text(block.content)
                    events.append((Event.TOOL_RESULT, {
                        **base, "tool_use_id": block.tool_use_id, "is_error": bool(block.is_error),
                        "summary": text[:500], "images": image_paths(text)}))
        return events
    if isinstance(msg, ResultMessage):
        return []
    return [(Event.LOG, {**base, "level": "debug", "message": type(msg).__name__})]


class SdkRunner:
    """Runs one ClaudeSDKClient per session inside a dedicated task, because the
    client must stay in the task group it connected in. Public methods only
    enqueue commands for that task."""

    def __init__(self, connection, client_factory=None, *, inline_skills: bool | None = None,
                 list_models=None):
        self.conn = connection
        self.client_factory = client_factory or ClaudeSDKClient
        # Reads the Models API for an API key (list_api_models in the real
        # agent, see __main__); None reads nothing, so tests never call it.
        self.list_models = list_models
        # The model the live session runs on: a submit for another one
        # switches it before its query.
        self.model: str | None = None
        # The models are reported once per agent process.
        self._models_task: asyncio.Task | None = None
        self.inline_skills = inline_skills_from_env() if inline_skills is None else inline_skills
        self.ctx = ToolContext(connection)
        self.session_id: str | None = None
        self.init_data: dict | None = None
        self.turn_id: str | None = None
        self._task: asyncio.Task | None = None
        self._commands: asyncio.Queue | None = None
        # Cleared the moment the SDK stream ends, before the session task has
        # finished disconnecting, so no submit can land on a dead session.
        self._alive = False
        self._queries = 0
        self._results = 0
        self._interrupt_requested = False
        self._turn_start = 0.0
        # Every ResultMessage of the running turn: an amendment that arrives
        # after the model has finished adds a follow-up query, and its result.
        self._turn_results: list[ResultMessage] = []
        self._session_cost = 0.0
        # The last transcript message of the running turn, which a later
        # branch from this turn's history node resumes at.
        self._last_uuid: str | None = None

    # -- Runner API -----------------------------------------------------------

    async def start_session(self, params: dict) -> None:
        await self._stop_session("session restarted")
        options = build_options(params, build_servers(self.ctx), inline_skills=self.inline_skills)
        self.session_id = params.get("resume")
        self.model = params.get("model")
        self.init_data = None
        self._session_cost = 0.0
        self._commands = asyncio.Queue()
        self._alive = True
        ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._session(options, self._commands, ready))
        await self._event(Event.STATUS, {"state": "connecting", "detail": params.get("model")})
        try:
            await ready
        except Exception as exc:
            await self._event(Event.ERROR, {"code": "connect_failed", "message": str(exc)})
            raise BridgeCallError(ErrorCode.INTERNAL, f"SDK connect failed: {exc}") from None
        await self._event(Event.STATUS, {"state": "idle", "detail": None})

    async def submit(self, turn_id: str, bundle_dir: str, prompt_text: str, context=(),
                     model: str | None = None) -> None:
        if not self._session_open():
            raise BridgeCallError(ErrorCode.NO_SESSION, "start_session first")
        if self.turn_id is not None:
            raise BridgeCallError(ErrorCode.BUSY, f"turn {self.turn_id} is running")
        self.turn_id = turn_id
        self.ctx.turn_id = turn_id
        self.ctx.bundle_dir = bundle_dir
        self._queries, self._results = 1, 0
        self._interrupt_requested = False
        self._turn_results = []
        self._last_uuid = None
        self.ctx.amends.clear()
        self._turn_start = time.monotonic()
        await self._event(Event.TURN_STARTED, {})
        await self._event(Event.STATUS, {"state": "running", "detail": None})
        # The stream may have ended during the awaits above; the reader has then
        # already failed this turn, and the query would go nowhere.
        if self._session_open() and self.turn_id == turn_id:
            text = submit_text(prompt_text, bundle_dir, context, sketch_size(bundle_dir))
            # A chat whose model changed since the session started switches
            # the live session, which keeps its conversation, before this query.
            self._commands.put_nowait(("query", (text, model if model != self.model else None)))

    async def amend(self, turn_id: str, text: str, bundle_dir: str | None,
                    number: int | None = None) -> None:
        if not self._session_open():
            raise BridgeCallError(ErrorCode.NO_SESSION, "start_session first")
        if self.turn_id is None or turn_id != self.turn_id:
            raise BridgeCallError(ErrorCode.NOT_FOUND, f"turn {turn_id} is not running")
        self.ctx.queue_amend(number, text, bundle_dir)

    async def interrupt(self, turn_id: str) -> None:
        if self.turn_id != turn_id or not self._session_open():
            return
        self._interrupt_requested = True
        await self._event(Event.STATUS, {"state": "interrupting", "detail": None})
        self._commands.put_nowait(("interrupt", None))

    async def close(self) -> None:
        await self._stop_session("agent shutting down")
        if self._models_task is not None and not self._models_task.done():
            self._models_task.cancel()

    def _session_open(self) -> bool:
        return self._alive and self._task is not None and not self._task.done()

    # -- session task ---------------------------------------------------------

    async def _session(self, options, commands: asyncio.Queue, ready: asyncio.Future) -> None:
        client = self.client_factory(options=options)
        try:
            await client.connect()
        except Exception as exc:
            log.exception("SDK connect failed")
            ready.set_exception(exc)
            try:
                await client.disconnect()
            except Exception:
                pass
            return
        ready.set_result(None)
        if self._models_task is None:
            self._models_task = asyncio.create_task(self._report_models(client))
        try:
            reader = asyncio.create_task(self._read(client, commands))
            try:
                await self._control(client, commands)
            finally:
                reader.cancel()
                try:
                    await reader
                except asyncio.CancelledError:
                    pass
        finally:
            try:
                await client.disconnect()
            except Exception:
                log.exception("SDK disconnect failed")

    async def _control(self, client, commands: asyncio.Queue) -> None:
        while True:
            kind, payload = await commands.get()
            if kind == "stop":
                await self._drop_queued(commands)
                return
            try:
                if kind == "query":
                    text, model = payload
                    if model:
                        await client.set_model(model)
                        self.model = model
                        await self._event(Event.LOG, {"level": "info", "message": f"switched to model {model}"})
                    await client.query(text)
                elif kind == "interrupt":
                    await client.interrupt()
            except Exception as exc:
                log.exception("SDK %s failed", kind)
                await self._event(Event.ERROR, {"code": f"{kind}_failed", "message": str(exc)})
                if kind == "query":
                    await self._finish_turn(error=str(exc))

    async def _drop_queued(self, commands: asyncio.Queue) -> None:
        # A query queued behind the stop will never run; its turn must still end.
        while not commands.empty():
            kind, _ = commands.get_nowait()
            if kind == "query":
                await self._finish_turn(error="the agent session ended before the prompt was sent")

    async def _read(self, client, commands: asyncio.Queue) -> None:
        failure = None
        try:
            async for msg in client.receive_messages():
                await self._handle(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("SDK message stream failed")
            failure = exc
        if commands is self._commands:
            self._alive = False
        if failure is not None:
            await self._event(Event.ERROR, {"code": "stream_failed", "message": str(failure)})
        # The stream ending means the CLI is gone; nothing more can run in this session.
        if self.turn_id is not None:
            await self._finish_turn(error="the agent CLI stopped")
        # Blender has to start a new session before its next submit.
        await self._event(Event.STATUS, {"state": SESSION_ENDED, "detail": "the agent CLI stopped"})
        commands.put_nowait(("stop", None))

    async def _handle(self, msg) -> None:
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            self.init_data = msg.data
            self.session_id = msg.data.get("session_id", self.session_id)
            skills = msg.data.get("skills") or []
            await self._event(Event.LOG, {
                "level": "info",
                "message": f"session {self.session_id}: model {msg.data.get('model')}, "
                           f"tools {msg.data.get('tools')}, skills {skills}"})
            loaded = [s for s in skills if str(s).startswith(f"{prompt.PLUGIN_NAME}:")]
            if not self.inline_skills and not loaded:
                await self._event(Event.LOG, {
                    "level": "warning",
                    "message": "no whittle: skills in the session; set WHITTLE_INLINE_SKILLS=1 "
                               f"to put the recipes in the system prompt (skills: {skills})"})
        if self.turn_id is not None and isinstance(msg, (AssistantMessage, UserMessage)) and msg.uuid:
            self._last_uuid = msg.uuid
        for name, data in map_message(msg, self.turn_id):
            await self.conn.send_event(name, data)
        if isinstance(msg, ResultMessage):
            self.session_id = msg.session_id or self.session_id
            if self.turn_id is None:
                await self._event(Event.LOG, {"level": "debug", "message": "result outside a turn"})
                return
            self._results += 1
            self._turn_results.append(msg)
            await self._event(Event.LOG, {
                "level": "debug",
                "message": f"result {self._results}/{self._queries}: total_cost_usd={msg.total_cost_usd} "
                           f"num_turns={msg.num_turns}"})
            if self._results < self._queries:
                return
            if self.ctx.amends and not self._interrupt_requested and not msg.is_error:
                await self._follow_up()
            else:
                await self._finish_turn()

    async def _follow_up(self) -> None:
        """The model finished before an amendment could ride on a tool result,
        so it goes as one more query and the Blender turn continues."""
        notes = self.ctx.take_amend_notes()
        self._queries += 1
        self._commands.put_nowait(("query", (follow_up_text([note for _n, note in notes]), None)))
        for number, _note in notes:
            await self._event(Event.AMEND_DELIVERED, {"amend": number, "via": "query"})

    async def _finish_turn(self, error: str | None = None) -> None:
        if self.turn_id is None:
            return
        results = self._turn_results
        r = results[-1] if results else None
        errors = [e for res in results for e in (res.errors or [])]
        if error:
            errors.append(error)
        interrupted = self._interrupt_requested or bool(r and r.terminal_reason in INTERRUPTED_REASONS)
        cost = turn_cost(results, self._session_cost)
        if r is not None and r.total_cost_usd is not None:
            self._session_cost = r.total_cost_usd
        undelivered = [a.number for a in self.ctx.amends]
        self.ctx.amends.clear()
        # The turn is over before its end is announced, so an amendment that
        # arrives meanwhile is refused rather than lost.
        turn_id, self.turn_id = self.turn_id, None
        self.ctx.turn_id = None
        await self.conn.send_event(Event.TURN_FINISHED, {
            "turn_id": turn_id,
            "session_id": (r.session_id if r else None) or self.session_id,
            "subtype": r.subtype if r else "error_during_execution",
            "is_error": bool(error) or bool(r and r.is_error),
            "interrupted": interrupted,
            "cost_usd": cost,
            "session_cost_usd": r.total_cost_usd if r else None,
            "num_turns": sum(res.num_turns for res in results),
            "duration_ms": (sum(res.duration_ms for res in results) if results
                            else int((time.monotonic() - self._turn_start) * 1000)),
            "result_text": (r.result or "") if r else "",
            "errors": errors,
            "amends_undelivered": undelivered,
            "message_uuid": self._last_uuid,
        })
        await self._event(Event.STATUS, {"state": "idle", "detail": None})

    async def _stop_session(self, reason: str) -> None:
        task, commands = self._task, self._commands
        self._task = None
        self._alive = False
        if task is None:
            return
        if self.turn_id is not None:
            await self._finish_turn(error=reason)
        if not task.done():
            commands.put_nowait(("stop", None))
            try:
                await asyncio.wait_for(asyncio.shield(task), STOP_TIMEOUT)
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            except Exception:
                log.exception("session task failed")

    async def _report_models(self, client) -> None:
        """Tells Blender which models the API key can use: the Models API's
        list, older versions included, else (when that fails) the CLI's own
        from its initialize response, the newest of each family. Nothing is
        sent when neither has any; a failure only costs the menu its
        freshness."""
        ids, source = [], "api"
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key and self.list_models is not None:
            try:
                pages = await asyncio.to_thread(self.list_models, key, os.environ.get("ANTHROPIC_BASE_URL"))
                ids = models.ids_from_models_api(pages)
            except Exception as exc:
                log.warning("no model list from the Models API: %s", exc)
        if not ids:
            source = "cli"
            try:
                info = getattr(client, "get_server_info", None)
                ids = models.ids_from_server_info(await info()) if info is not None else []
            except Exception as exc:
                log.warning("no model list from the CLI: %s", exc)
        if ids:
            await self.conn.send_event(Event.MODELS, {"turn_id": None, "models": ids, "source": source})

    async def _event(self, name: str, data: dict) -> None:
        await self.conn.send_event(name, {"turn_id": self.turn_id, **data})
