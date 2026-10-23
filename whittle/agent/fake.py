# SPDX-License-Identifier: GPL-3.0-or-later
"""A scripted stand-in for the SDK agent, so the real process, socket and
Blender handlers can be exercised end to end at no cost. Stdlib only.

Script format: {"turns": [{"steps": [...], "finish": {...}}, ...]}, plus an
optional top-level "resume_fails": true that refuses every start_session with
a resume, as the CLI does when it cannot find the session, and an optional
"models": {"models": [ids], "source": "api" | "cli"} reported (as the
models event) when the first session starts, as the real runner reports what
the account offers. Each submit plays
the next turn; a turn with "refuse": "<code>" answers its submit with that
error instead of starting. Steps:
  {"say": text}
  {"call": method, "params": {...}, "expect": "ok" | "error:<code>",
   "delay": seconds}         announce the call, then wait (cut short by an
                             interrupt) before making it, so it shows as in
                             flight the way a slow real tool does
  {"gather": [call steps]}   issued concurrently
  {"ask": question, "choices": [...]}
  {"sleep": seconds}          cut short by an interrupt
  {"wait_amend": seconds}    wait until the user amends the turn
  {"read_amend": n}          read amendment n's bundle and say what it holds
  {"if_views": [steps], "else": [steps]}
                             play the first list when the request has sketch
                             views, the second (default none) when it has
                             none, as a real agent checks against the sketch
                             only when there is one. A call's "view":
                             "first" names the request's lowest view id.
  {"fail": reason}           exit the process with code 3
  {"end_session": reason}    end the session as if the CLI had stopped; the
                             process stays up and the next submit needs a
                             new start_session

A submit whose model differs from the session's switches it, as the real
runner does with set_model, and logs "model: <id>"; start_session logs its
model as "session model: <id>". Effort likewise: "effort: <level>" and
"session effort: <level>".

Session ids are fake-<hex>: a new one for a fresh session or a fork, the
same one for a plain resume. Each turn reports a fake message uuid. With a
store_dir, each turn appends one line to <store_dir>/<session id>.jsonl, as
the SDK mirrors a real transcript, and a resume reports how many lines the
store has for the session it resumes (stored_lines=N).

Amendments ride on the next call's result as note lines. Any still pending
when the steps run out are delivered as if by a follow-up query, and the
turn's "after_amend" steps play (by default one say of the amendment).
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

from .. import formats
from ..protocol import SESSION_ENDED, ErrorCode, Event, Method
from .connection import BridgeCallError
from .tools import amend_note

log = logging.getLogger("whittle.agent")

CRASH_EXIT_CODE = 3


def _store_lines(store: str, session: str) -> int:
    try:
        with open(os.path.join(store, f"{session}.jsonl"), encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:8]


class FakeRunner:
    def __init__(self, connection, script_path, *, exit=os._exit):
        self.conn = connection
        self.script = json.loads(Path(script_path).read_text(encoding="utf-8"))
        self._exit = exit
        self.session: dict | None = None
        self.session_id: str | None = None
        self.sessions_started = 0
        self.turn_id: str | None = None
        self._turn_index = 0
        self._task: asyncio.Task | None = None
        self._interrupted = False
        self._interrupt_event = asyncio.Event()
        self._amends: list[dict] = []
        self._amend_arrived = asyncio.Event()
        self._bundle_dir: str | None = None
        self._tool_ids = 0
        self.model: str | None = None
        self.effort: str | None = None
        self._models_reported = False

    async def start_session(self, params: dict) -> None:
        if self._task is not None and not self._task.done():
            self._interrupt()
            await self._task
        resume, fork, resume_at = params.get("resume"), params.get("fork"), params.get("resume_at")
        described = f"resume={resume} fork={bool(fork)} resume_at={resume_at}"
        store = params.get("store_dir")
        if store:
            # What a real resume would find in the chat's transcript store.
            found = _store_lines(store, resume) if resume else 0
            described += f" store={store} stored_lines={found}"
        if resume and self.script.get("resume_fails"):
            self.session = None
            raise BridgeCallError(ErrorCode.INTERNAL, f"SDK connect failed: no conversation found "
                                                      f"with session id {resume}")
        self.session = params
        self.model = params.get("model")
        self.effort = params.get("effort")
        self.session_id = resume if resume and not fork else _new_id("fake-")
        self.sessions_started += 1
        await self._event(Event.STATUS, {"state": "idle", "detail": f"fake session ({described})"})
        await self._event(Event.LOG, {"level": "info", "message": f"fake session {self.session_id}: "
                                                                  f"{described}"})
        await self._event(Event.LOG, {"level": "info", "message": f"session model: {self.model}"})
        await self._event(Event.LOG, {"level": "info", "message": f"session effort: {self.effort}"})
        if self.script.get("models") and not self._models_reported:
            self._models_reported = True
            await self.conn.send_event(Event.MODELS, {"turn_id": None, **self.script["models"]})

    async def submit(self, turn_id: str, bundle_dir: str, prompt: str, context=(),
                     model: str | None = None, effort: str | None = None) -> None:
        if self.session is None:
            raise BridgeCallError(ErrorCode.NO_SESSION, "start_session first")
        if self.turn_id is not None:
            raise BridgeCallError(ErrorCode.BUSY, f"turn {self.turn_id} is running")
        turns = self.script.get("turns", [])
        turn = turns[self._turn_index] if self._turn_index < len(turns) else None
        self._turn_index += 1
        if turn is not None and turn.get("refuse"):
            raise BridgeCallError(turn["refuse"], "the fake script refuses this submit")
        self.turn_id = turn_id
        self._bundle_dir = bundle_dir
        self._interrupted = False
        self._interrupt_event = asyncio.Event()
        self._amends = []
        self._amend_arrived = asyncio.Event()
        if model and model != self.model:
            self.model = model
            await self._event(Event.LOG, {"level": "info", "message": f"model: {model}"})
        if effort and effort != self.effort:
            self.effort = effort
            await self._event(Event.LOG, {"level": "info", "message": f"effort: {effort}"})
        for line in context:
            await self._event(Event.LOG, {"level": "info", "message": f"context: {line}"})
        self._task = asyncio.create_task(self._play(turn_id, turn))

    async def amend(self, turn_id: str, text: str, bundle_dir: str | None,
                    number: int | None = None) -> None:
        if self.session is None:
            raise BridgeCallError(ErrorCode.NO_SESSION, "start_session first")
        if self.turn_id is None or turn_id != self.turn_id:
            raise BridgeCallError(ErrorCode.NOT_FOUND, f"turn {turn_id} is not running")
        self._amends.append({"number": number, "text": text, "bundle_dir": bundle_dir})
        self._amend_arrived.set()

    async def interrupt(self, turn_id: str) -> None:
        if self.turn_id == turn_id:
            self._interrupt()
            await self._event(Event.STATUS, {"state": "interrupting", "detail": None})

    def _interrupt(self) -> None:
        self._interrupted = True
        self._interrupt_event.set()

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # -- playback -------------------------------------------------------------

    async def _event(self, name: str, data: dict) -> None:
        await self.conn.send_event(name, {"turn_id": self.turn_id, **data})

    async def _play(self, turn_id: str, turn: dict | None) -> None:
        start = time.monotonic()
        errors = []
        await self._event(Event.TURN_STARTED, {})
        await self._event(Event.STATUS, {"state": "running", "detail": None})
        steps = turn.get("steps", []) if turn else []
        if turn is None:
            errors.append("the fake script has no more turns")
        for step in steps:
            if self._interrupted:
                break
            await self._step(step, errors)
        while self._amends and not self._interrupted:
            amends = self._take_amends()
            await self._deliver("query", amends)
            after = (turn or {}).get("after_amend",
                                     [{"say": f"Amendment received: {a['text']}"} for a in amends])
            for step in after:
                if self._interrupted:
                    break
                await self._step(step, errors)
        undelivered = [a["number"] for a in self._amends]
        self._amends = []
        finish = (turn or {}).get("finish", {})
        self._record_in_store(turn_id)
        # The turn is over before its end is announced, so an amendment that
        # arrives meanwhile is refused rather than lost.
        self.turn_id = None
        await self.conn.send_event(Event.TURN_FINISHED, {
            "turn_id": turn_id,
            "session_id": self.session_id,
            "subtype": finish.get("subtype", "success" if turn else "error_during_execution"),
            "is_error": bool(finish.get("is_error", turn is None)),
            "interrupted": self._interrupted,
            "cost_usd": 0.0,
            "num_turns": len(steps),
            "duration_ms": int((time.monotonic() - start) * 1000),
            "result_text": finish.get("result", ""),
            "errors": errors,
            "amends_undelivered": undelivered,
            "message_uuid": _new_id("fake-msg-"),
        })
        await self.conn.send_event(Event.STATUS, {"turn_id": None, "state": "idle", "detail": None})

    async def _step(self, step: dict, errors: list[str]) -> None:
        if "say" in step:
            await self._event(Event.TEXT, {"text": step["say"]})
        elif "call" in step:
            await self._call(step, errors)
        elif "gather" in step:
            await asyncio.gather(*(self._call(s, errors) for s in step["gather"]))
        elif "ask" in step:
            await self._event(Event.STATUS, {"state": "waiting_user", "detail": step["ask"]})
            await self._call({"call": Method.ASK,
                              "params": {"question": step["ask"], "choices": step.get("choices", [])},
                              "expect": step.get("expect")}, errors, timeout=None)
            await self._event(Event.STATUS, {"state": "running", "detail": None})
        elif "sleep" in step:
            await self._wait(self._interrupt_event, float(step["sleep"]))
        elif "wait_amend" in step:
            if not self._amends and not await self._wait(self._amend_arrived, float(step["wait_amend"])):
                if not self._interrupted:
                    errors.append(f"no amendment within {step['wait_amend']} s")
        elif "read_amend" in step:
            await self._read_amend(int(step["read_amend"]), errors)
        elif "if_views" in step:
            for sub in step["if_views"] if self._has_views() else step.get("else", []):
                if self._interrupted:
                    break
                await self._step(sub, errors)
        elif "end_session" in step:
            self.session = None
            await self._event(Event.STATUS, {"state": SESSION_ENDED, "detail": step["end_session"]})
        elif "fail" in step:
            log.error("fake script asked to crash: %s", step["fail"])
            logging.shutdown()
            self._exit(CRASH_EXIT_CODE)
        else:
            errors.append(f"unknown fake step {step!r}")

    def _record_in_store(self, turn_id: str) -> None:
        """One transcript line per turn in the chat's store, as the SDK
        mirrors a real session's, so the store travels with the chat."""
        store = (self.session or {}).get("store_dir")
        if not store or not self.session_id:
            return
        try:
            os.makedirs(store, exist_ok=True)
            with open(os.path.join(store, f"{self.session_id}.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "fake", "turn_id": turn_id, "session_id": self.session_id}) + "\n")
        except OSError as exc:
            log.warning("could not write the fake transcript: %s", exc)

    def _views(self) -> list[int]:
        if not self._bundle_dir:
            return []
        try:
            request = formats.read_json(Path(self._bundle_dir) / "request.json")
        except formats.FormatError:
            return []
        return sorted(request.get("views") or [])

    def _has_views(self) -> bool:
        return bool(self._views())

    async def _wait(self, event: asyncio.Event, seconds: float) -> bool:
        """Waits for the event, an interrupt or the timeout; True when the
        event was set."""
        waiters = [asyncio.create_task(event.wait()), asyncio.create_task(self._interrupt_event.wait())]
        try:
            await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
        return event.is_set()

    def _take_amends(self) -> list[dict]:
        amends, self._amends = self._amends, []
        self._amend_arrived.clear()
        return amends

    async def _deliver(self, via: str, amends: list[dict]) -> None:
        for amend in amends:
            await self._event(Event.AMEND_DELIVERED, {"amend": amend["number"], "via": via})

    async def _read_amend(self, n: int, errors: list[str]) -> None:
        if not self._bundle_dir:
            errors.append("read_amend: there is no request bundle")
            return
        try:
            bundle = formats.read_bundle(Path(self._bundle_dir).parent / f"amend-{n}")
        except formats.FormatError as exc:
            errors.append(f"read_amend: {exc}")
            await self._event(Event.ERROR, {"code": "read_amend_failed", "message": str(exc)})
            return
        await self._event(Event.TEXT, {"text": f"amend {n}: {len(bundle.strokes)} strokes, "
                                               f"views {sorted(bundle.views)}"})

    async def _call(self, step: dict, errors: list[str], timeout: float | None = 300.0) -> None:
        self._tool_ids += 1
        tool_use_id = f"fake-tu-{self._tool_ids}"
        method, params = step["call"], step.get("params", {})
        if params.get("view") == "first":
            params = {**params, "view": (self._views() or [None])[0]}
        await self._event(Event.TOOL_USE, {"tool_use_id": tool_use_id, "tool": method, "input": params})
        if step.get("delay"):
            await self._wait(self._interrupt_event, float(step["delay"]))
        try:
            data = await self.conn.call(method, params, timeout=timeout)
            outcome = "ok"
            images = [p for p in (data.get("path"), data.get("strokes_path")) if p]
            summary = json.dumps(data, ensure_ascii=False)[:500]
            is_error = bool(data.get("error"))
        except BridgeCallError as exc:
            outcome = f"error:{exc.code}"
            images, summary, is_error = [], f"{exc.code}: {exc.message}"[:500], True
        # Amendments ride on the result, as they do on a real tool result.
        amends = self._take_amends()
        notes = [amend_note(a["number"], a["text"], a["bundle_dir"] is not None) for a in amends]
        if notes:
            summary = "\n".join([summary, *notes])
        await self._event(Event.TOOL_RESULT, {
            "tool_use_id": tool_use_id, "is_error": is_error, "summary": summary, "images": images})
        await self._deliver("tool_result", amends)
        expect = step.get("expect")
        if expect and expect != outcome:
            message = f"{method}: expected {expect}, got {outcome}"
            errors.append(message)
            await self._event(Event.ERROR, {"code": "expect_failed", "message": message})
