# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs turns: owns the agent process, the command context and the stream,
and drives start_session -> submit -> turn_finished."""

import hashlib
import logging
import re
import shutil
from pathlib import Path

import bpy

from .. import formats, protocol
from ..protocol import SESSION_ENDED, ErrorCode, Event, Method
from ..tree import SessionPlan, session_plan
from . import (bundle, chats, commands, compare, execution, history, models, paths, prefs, sketch, snapshot,
               targets, views)
from . import refs as references
from .bridge import modal_running, redraw_view3d
from .process import AgentProcess, AgentState
from .stream import Stream, TranscriptWriter, local_entry

log = logging.getLogger("whittle")

# What the CLI says when the API key is refused (or, should it ever run
# without one, that it has no credentials at all).
_KEY_REFUSED = re.compile(r"not logged in|invalid.{0,12}api.?key|x-api-key|authentication_error"
                          r"|\b401\b|unauthori[sz]ed", re.IGNORECASE)
KEY_REFUSED = "The API key was refused"


UNDO_NOTE = ("The user pressed undo during this turn: the scene went back to how it was when the "
             "turn began, or earlier, so your edits so far may be gone and objects you hold in "
             "variables may no longer exist. Inspect the target before you go on.")


def key_problem(text: str) -> str | None:
    """What an error message says about the API key, if it is about that."""
    if not text or not _KEY_REFUSED.search(text):
        return None
    return KEY_REFUSED


node_number = formats.node_number


def latest_node_number(session: formats.SessionDir) -> int:
    """The highest node in the session folder, or 0 when there is none."""
    return max(map(node_number, session.node_ids()), default=0)


def next_node_number(session: formats.SessionDir) -> int:
    """One past the highest node already in the session folder, so a new
    controller on an existing session never reuses an earlier turn's node."""
    return latest_node_number(session) + 1


class TurnController:
    def __init__(self, session_root: Path, *, fake_script: Path | None = None,
                 python: Path | None = None, agent_token: str | None = None,
                 use_timer: bool = True, model: str | None = None,
                 settings: dict | None = None):
        self.session = formats.SessionDir(session_root)
        self.stream = Stream()
        # A model for every turn, over the chat's own (tests use it).
        self.model = model
        # Extra session settings on top of the preferences (max_turns, max_budget_usd).
        self.settings_overrides = dict(settings or {})
        self.bundle: formats.Bundle | None = None
        self.turn_id: str | None = None
        self.last_finished: dict | None = None
        self.question: dict | None = None
        self.session_ready = False
        self.events: list[dict] = []
        self.errors: list[str] = []
        self._next_node = next_node_number(self.session)
        # (bundle_dir, prompt, reserved node or None, written from the live sketch)
        self._pending_run: tuple[Path, str | None, str | None, bool] | None = None
        self._submitted: tuple[Path, str | None, str | None, bool] | None = None
        # Whether the submitted node's folder was made for this run (and so
        # goes again if the agent refuses it).
        self._owns_node_dir = False
        # (prompt, targets, model) of the submitted turn, for its chat once
        # the agent accepts it.
        self._began: tuple[str, list, str] | None = None
        # Whether the running turn's bundle was written from the live sketch.
        self._from_sketch = False
        # The reference images the waiting or running sketch run sent.
        self._sent_refs: list[Path] = []
        # Whether the agent accepted the running turn's submit.
        self._accepted = False
        # A run is resubmitted at most once after a no_session answer.
        self._retried = False
        self._transcript: TranscriptWriter | None = None
        self.history = history.get(self.session.root, reload=True)
        # The history node the live SDK client last finished on; a submit from
        # any other node starts (resumes or forks) another session first.
        self.live_node: str | None = None
        # The params of every start_session sent.
        self.session_starts: list[dict] = []
        self._plan: SessionPlan | None = None
        self._plan_node: str | None = None
        self._session_starting = False
        # Context lines for the agent on the next submit.
        self._context: list[str] = []
        # Set when resuming the SDK session failed: the next start is fresh.
        self._resume_failed: str | None = None
        self._resumed = False
        self._session_turns = 0
        # What the sidebar shows: idle | starting | running | waiting_user | interrupting.
        self.status: dict = {"phase": "idle", "detail": None}
        # The running turn's amendments: number -> {text, bundle_dir, delivered, returned}.
        self.amends: dict[int, dict] = {}
        # Amendments made after Submit but before the agent took the turn:
        # (text, scene), sent in order once it does.
        self.queued_amends: list[tuple[str, object]] = []
        # The prompt box's text, taken by Send: (scene, text). It goes back if
        # the run never starts or its turn folds away.
        self._sent_prompt: tuple[object, str] | None = None
        # The latest turn of this Blender session if it failed without
        # changing anything: not in the tree, but shown once with Retry.
        self.last_folded: str | None = None
        # Set when a turn or start failed because the API key was refused;
        # cleared by the next turn that completes.
        self.key_problem: str | None = None
        self._start: snapshot.Snapshot | None = None
        self._restore_on_finish = False
        self._started = False
        self._scene = None
        # What the running agent process was started with (launch_settings()).
        self._launched: dict | None = None
        # Session uids of the objects that existed when the running turn began.
        self._preexisting: set[int] = set()
        self.commands = commands.CommandContext(
            session=self.session, turn_id=lambda: self.turn_id, bundle=lambda: self.bundle,
            settings=prefs.session_settings(), on_ask=self._on_ask,
            amend_bundles=self._amend_bundles, turn_number=self._turn_number,
            turn_objects=self._turn_objects, on_restored=self._on_checkpoint_restored)
        self.process = AgentProcess(handlers=commands.build_handlers(self.commands),
                                    on_event=self.on_event, fake_script=fake_script, python=python,
                                    agent_token=agent_token, use_timer=use_timer)
        self.process.state_listeners.append(self._on_state)
        # A crash or exit is noticed by polling, not by an agent message, so it
        # tags the sidebar for redraw itself.
        self.process.state_listeners.append(lambda _state, _reason: redraw_view3d())

    @property
    def bridge(self):
        return self.process.bridge

    @property
    def running(self) -> bool:
        return self.turn_id is not None

    @property
    def busy(self) -> bool:
        """A turn is running or a run is waiting for the agent."""
        return self.running or self._pending_run is not None

    @property
    def active_turn(self) -> tuple[str | None, str] | None:
        """(node, prompt) of the running turn, or of the run waiting for the
        agent or its session to start; None when idle. A bundle run has no
        node until it is submitted."""
        if self.turn_id is not None:
            node = self.history.tree.nodes.get(self.turn_id) if self.history.tree is not None else None
            prompt = node.prompt if node is not None else (self.bundle.request.prompt if self.bundle else "")
            return self.turn_id, prompt
        if self._pending_run is not None:
            bundle_dir, prompt, node, _from_sketch = self._pending_run
            if prompt is None:
                try:
                    prompt = formats.read_json(Path(bundle_dir) / "request.json").get("prompt", "")
                except (formats.FormatError, OSError):
                    prompt = ""
            return node, prompt
        return None

    def hold_prompt(self, scene, text: str) -> None:
        """Send took the prompt box's text; it comes back if the run never
        starts, or if its turn fails without changing anything."""
        self._sent_prompt = (scene, text) if text.strip() else None

    def _give_back_prompt(self, *, only_if_empty: bool) -> None:
        held, self._sent_prompt = self._sent_prompt, None
        if held is None:
            return
        scene, text = held
        try:
            props = scene.whittle
            if not props.prompt.strip():
                props.prompt = text
            elif not only_if_empty and text.strip() not in props.prompt:
                props.prompt = f"{text} {props.prompt}"
        except (ReferenceError, AttributeError):
            pass

    @property
    def interrupting(self) -> bool:
        return self.running and self.bridge is not None and self.bridge.interrupted

    def _turn_number(self) -> int | None:
        if self.turn_id is None or not self._from_sketch:
            return None
        return node_number(self.turn_id)

    def _amend_bundles(self) -> list[formats.Bundle]:
        return [a["bundle"] for a in self.amends.values() if a.get("bundle") and not a.get("returned")]

    # -- commands from the UI ------------------------------------------------

    def start(self) -> None:
        if not self.process.alive:
            self.session_ready = False
            launched = self.launch_settings()
            self.process.start(self.session.root)
            self._launched = launched if self.process.alive else None

    def launch_settings(self) -> dict:
        """What an agent started now would run with: the process's Python,
        fake script, API key and usage-data choice, and the settings its
        sessions get. The key
        is kept only as a digest. The model is not among them: each submit
        names the chat's, and the agent switches its session to it."""
        key, _source = prefs.api_key()
        python = self.process.python or paths.agent_python()
        return {"python": str(python) if python else None,
                "fake_script": str(self.process.fake_script) if self.process.fake_script else None,
                "api_key": hashlib.sha256(key.encode()).hexdigest() if key else None,
                "usage_data": bool(prefs.get().usage_data),
                "settings": {**prefs.session_settings(), **self.settings_overrides}}

    def chat_model(self) -> str:
        """The model this chat's next turn runs on: the controller's own,
        else the chat's, else the add-on's default."""
        return self.model or chats.model_for(self.session.root) or models.default_model()

    @property
    def launch_changed(self) -> bool:
        """The running agent was started with settings that no longer hold."""
        return self.process.alive and self._launched is not None and self._launched != self.launch_settings()

    def stop(self, *, wait: bool = False) -> None:
        self.process.stop(wait=wait)

    def close(self) -> None:
        """Stops the agent, waiting for it to exit."""
        if self.process.alive:
            self.stop(wait=True)

    def run_bundle(self, bundle_dir: Path, prompt: str | None = None) -> None:
        """Starts the agent and a session if needed, then submits the bundle."""
        if self.running:
            raise RuntimeError("a turn is already running")
        if self._pending_run is not None:
            raise RuntimeError("a run is already waiting for the agent")
        _refuse_while_comparing()
        self._resume_failed = None
        self.last_folded = None
        bundle = formats.read_bundle(bundle_dir)
        missing = [t["name"] for t in bundle.request.target if t["name"] not in bpy.data.objects]
        if missing:
            raise ValueError(f"target objects not in this file: {', '.join(missing)}")
        self._ensure_started()
        compare.clear_ghost()
        self.history.ensure_root([bpy.data.objects[t["name"]] for t in bundle.request.target],
                                 bpy.context.scene)
        self._pending_run = (Path(bundle_dir), prompt, None, False)
        self._retried = False
        self._advance()

    def run_sketch(self, prompt: str, *, targets, refs=(), scene=None) -> str:
        """Writes a bundle from the live sketch into the next node's request
        folder and runs it; returns the node id.

        The agent is started (or checked) first, so nothing is written for a
        run that cannot happen. The bundle is written now rather than when the
        agent is ready, so strokes drawn while it starts stay pending."""
        if self.running:
            raise RuntimeError("a turn is already running")
        if self._pending_run is not None:
            raise RuntimeError("a run is already waiting for the agent")
        _refuse_while_comparing()
        refs = [Path(r) for r in refs]
        if not prompt.strip() and not refs and not sketch.pending_count(sketch.find_sketch_object()):
            raise ValueError("nothing to send: type a prompt or draw on the sketch")
        self._resume_failed = None
        self.last_folded = None
        scene = scene or bpy.context.scene
        self._ensure_started()
        compare.clear_ghost()
        number = self._next_node
        node = formats.node_id(number)
        node_dir = self.session.node_dir(node)
        if node_dir.exists():
            raise FileExistsError(f"node {node} already exists in {self.session.root}")
        obj = sketch.find_sketch_object()
        if obj is not None:
            sketch.ensure_region_fills(obj)
        settings = {**prefs.session_settings(), **self.settings_overrides}
        dest = self.session.request_dir(node)
        # The scene reflects the current history node, so the turn grows from it.
        parent = self.history.current or history.ROOT
        targets = list(targets)
        collection = scene.whittle.target_collection if hasattr(scene, "whittle") else None
        try:
            bundle.write_bundle(dest, scene=scene, sketch_obj=obj, node=node, parent=parent,
                                prompt=prompt, targets=targets, refs=refs, settings=settings,
                                render_size=int(settings.get("render_size") or 512),
                                target_collection=collection.name if collection is not None else None)
            # Node 0 is the target before any turn, written once the run is
            # sure to go ahead.
            self.history.ensure_root(targets, scene)
        except BaseException:
            # The node folder did not exist before this run, so whatever the
            # failed write left there goes, and the number stays free.
            shutil.rmtree(node_dir, ignore_errors=True)
            raise
        self._next_node = number + 1
        self._sent_refs = refs
        if obj is not None:
            sketch.stamp_strokes(obj, number)
        self._pending_run = (dest, prompt, node, True)
        self._retried = False
        self._advance()
        return node

    def _ensure_started(self) -> None:
        if not self.process.alive:
            self.start()
            if not self.process.alive:
                self._pending_run = None
                raise RuntimeError(self.process.reason or f"the agent is {self.process.state}")

    def start_session(self, plan: SessionPlan | None = None) -> None:
        """Starts an SDK session: fresh, or resuming (and maybe forking) the
        conversation the plan names."""
        plan = plan or SessionPlan(restart=True)
        settings = {**prefs.session_settings(), **self.settings_overrides}
        self.commands.settings = settings
        # The chat's SDK transcripts live in its folder (agent/store.py).
        params = {"session_dir": str(self.session.root), "store_dir": str(self.session.root / "sdk"),
                  "model": self.chat_model(),
                  "resume": plan.resume, "fork": plan.fork, "resume_at": plan.resume_at,
                  "settings": settings}
        self.session_starts.append(params)
        self._session_starting = True
        self._resumed = plan.resume is not None
        self._session_turns = 0
        self.bridge.call(Method.START_SESSION, params,
                         lambda ok, data: self._on_session_started(ok, data, params))

    def submit(self, bundle_dir: Path, prompt: str | None = None, node: str | None = None, *,
               from_sketch: bool = False) -> str:
        """Submits a bundle under the given node, or the next free one. A bundle
        already in the node's request folder (written from the sketch, or a
        retry) is used in place."""
        if node is None:
            node = formats.node_id(self._next_node)
            self._next_node += 1
        else:
            self._next_node = max(self._next_node, node_number(node) + 1)
        dest = self.session.request_dir(node)
        copied = Path(bundle_dir).resolve() != dest.resolve()
        if copied:
            if self.session.node_dir(node).exists():
                raise FileExistsError(f"node {node} already exists in {self.session.root}")
            try:
                shutil.copytree(bundle_dir, dest)
                self.bundle = formats.read_bundle(dest)
            except BaseException:
                shutil.rmtree(self.session.node_dir(node), ignore_errors=True)
                raise
        else:
            self.bundle = formats.read_bundle(dest)
        self._submitted = (dest, prompt, node, from_sketch)
        self._owns_node_dir = copied or from_sketch
        if not from_sketch and copied:
            # A bundle from disk brings its own strokes for the overlay renders.
            # A sketch bundle's strokes are already there, with any pending
            # ones drawn since.
            sketch.load_strokes(bpy.context.scene, self.bundle.strokes)
        self._from_sketch = from_sketch
        self.turn_id = node
        self._accepted = False
        self._started = False
        self.last_finished = None
        self._scene = bpy.context.scene
        began = False
        try:
            self._transcript = TranscriptWriter(self.session.transcript_path(node))
            text = self.bundle.request.prompt if prompt is None else prompt
            turn_targets = self.commands.targets()
            if self.history.tree is None:
                self.history.ensure_root(turn_targets, self._scene)
            self.history.begin(node, text, continued_session=self._continued_session())
            began = True
            # A chat's first turn names it and keeps its model once the agent
            # takes it; one switched back to tells the agent.
            model = self.chat_model()
            self._began = (text, turn_targets, model)
            self._begin_turn(node, turn_targets)
            context = [*(self._plan.notes if self._plan else ()), *self._context,
                       *chats.switch_note(self.session.root)]
            self._transcript.write_local("submit", {"node": node, "prompt": text, "bundle_dir": str(dest),
                                                    "targets": [o.name for o in turn_targets],
                                                    "parent": self.history.node(node).parent,
                                                    "context": context})
        except Exception:
            # Nothing reached the agent: the turn is undone, so the controller
            # is not left running a turn that never started.
            self._abandon_submit(node, began=began)
            raise
        self.stream.note(f"Turn {node}: {text or '(sketch only)'}", kind="submit", turn_id=node)
        self.bridge.call(Method.SUBMIT, {"turn_id": node, "bundle_dir": str(dest), "prompt": text,
                                         "context": context, "model": model},
                         self._on_submit_result)
        self.process.set_busy(True)
        self._set_phase("starting")
        return node

    def _abandon_submit(self, node: str, *, began: bool) -> None:
        """A submit that failed before it was sent, or that the agent refused:
        its node goes from the history and, when made for it, from disk, and
        the prompt and queued amendments go back to the user."""
        submitted, self._submitted = self._submitted, None
        from_sketch = bool(submitted and submitted[3])
        self.turn_id = None
        self._transcript = None
        self._from_sketch = False
        self._began = None
        if began:
            try:
                self.history.discard(node)
            except Exception:
                log.exception("could not drop node %s from the history", node)
        if self._owns_node_dir:
            self._free_node(node, unstamp=from_sketch)
        self._owns_node_dir = False
        self._give_back_prompt(only_if_empty=False)
        self._return_queued_amends("the turn was not sent")

    def _free_node(self, node: str, *, unstamp: bool) -> None:
        """A node no turn ran in: its folder goes and, when it was the newest,
        its number is free again. Its strokes lose the stamp: one left on a
        stroke hidden from the next run would see it removed when that run
        succeeds, unsent."""
        shutil.rmtree(self.session.node_dir(node), ignore_errors=True)
        if unstamp:
            obj = sketch.find_sketch_object()
            if obj is not None:
                try:
                    sketch.unstamp_strokes(obj, node_number(node))
                except (ReferenceError, RuntimeError) as exc:
                    log.warning("could not unstamp the strokes of %s: %s", node, exc)
        # The next run takes the freed number, so node ids stay contiguous.
        if self._next_node == node_number(node) + 1:
            self._next_node = node_number(node)

    def _continued_session(self) -> str | None:
        """The SDK session a submit now carries on: the one the session just
        started resumed, or the live one. A fork or a fresh session has no id
        until its turn reports one."""
        if self._plan is not None:
            return self._plan.resume if not self._plan.fork else None
        nodes = self.history.tree.nodes if self.history.tree is not None else {}
        if self.session_ready and self.live_node in nodes:
            return nodes[self.live_node].agent_session_id
        return None

    def _begin_turn(self, node: str, turn_targets: list) -> None:
        """Turn-start state: the snapshot an interrupt can restore."""
        self.commands.reset_turn()
        self.amends = {}
        self._restore_on_finish = False
        self._start = None
        # Exec diffs compare names, so an object the agent merely renamed shows
        # up as added; identity tells the agent's new objects from the user's.
        self._preexisting = {o.session_uid for o in bpy.data.objects}
        # In Edit Mode the target's live mesh is not in its data yet.
        snapshot.leave_edit_mode(turn_targets)
        # An undo during the turn goes back to here, not past the user's
        # last change. Not in the middle of a modal operation.
        if not modal_running():
            history.undo_push(f"{history.UNDO_PREFIX}: before {node}")
        blend, _manifest = self.session.checkpoint_paths(node, "start")
        try:
            self._start = snapshot.write(blend, turn_targets)
        except Exception as exc:
            log.exception("turn-start snapshot failed")
            self.stream.note(f"No turn-start snapshot, so this turn cannot be restored: {exc}",
                             kind="warning", turn_id=node)

    def interrupt(self, *, restore: bool = False) -> None:
        """Stops the turn after the call that is running. With restore, the
        target goes back to how it was at the turn's start once the turn has
        ended; otherwise the partial edit stays."""
        if not self.running or self.bridge is None:
            return
        self._restore_on_finish = restore
        self._local("interrupt", {"mode": "restore" if restore else "keep"})
        local_entry(self.stream, "interrupt", {"mode": "restore" if restore else "keep"}, self.turn_id)
        if self.bridge.interrupted:
            return
        self.bridge.set_interrupted(True)
        # The interrupt goes out before the refused question, so the agent
        # knows why the question failed when it sees the failure.
        self.bridge.call(Method.INTERRUPT, {"turn_id": self.turn_id})
        self.bridge.fail_deferred(ErrorCode.INTERRUPTED, "the user stopped this turn; make no more changes")
        self.question = None
        self._set_phase("interrupting")

    def answer(self, text: str) -> bool:
        if self.bridge is None or self.question is None:
            return False
        question = self.question
        call_ids = [cid for cid, method in self.bridge.deferred.items() if method == Method.ASK]
        self.question = None
        notes = self.commands.take_notes()
        answered = any([self.bridge.resolve(cid, {"answer": text, "notes": notes}) for cid in call_ids])
        if not answered:
            self.commands.notes[:0] = notes
        if answered:
            self._local("answer", {"question": question["question"], "answer": text})
            local_entry(self.stream, "answer", {"answer": text}, self.turn_id)
            self._set_phase("running")
        return answered

    @property
    def can_amend(self) -> bool:
        """From Submit until the turn ends, unless it is being interrupted."""
        return self.busy and not self.interrupting

    def amend(self, text: str, *, scene=None) -> int:
        """Sends a message, and the strokes drawn since the submit, into the
        running turn; returns the amendment number. Between Submit and the
        agent taking the turn (the agent or its session still starting) the
        amendment is queued and goes in as soon as the turn is accepted."""
        if not self.busy:
            raise RuntimeError("there is no running turn to amend")
        if self.interrupting:
            raise RuntimeError("the turn is being interrupted")
        scene = scene or bpy.context.scene
        if not self.running or not (self._accepted or self._started) or self.bridge is None:
            return self._queue_amend(text, scene)
        node = self.turn_id
        number = len(self.amends) + 1
        obj = sketch.find_sketch_object() if self._from_sketch else None
        pending = sketch.pending_count(obj)
        if not text.strip() and not pending:
            raise ValueError("nothing to amend: type a message or draw new strokes")
        amend = {"text": text, "bundle_dir": None, "bundle": None, "delivered": False,
                 "returned": False, "scene": scene}
        if pending:
            dest = self.session.amend_dir(node, number)
            settings = {**prefs.session_settings(), **self.settings_overrides}
            sketch.ensure_region_fills(obj)
            written = bundle.write_bundle(
                dest, scene=scene, sketch_obj=obj, node=node, parent=self.bundle.request.parent,
                prompt=text, targets=self.commands.targets(), settings=settings,
                render_size=int(settings.get("render_size") or 512), amend=number,
                stroke_filter=lambda turn, _amend: turn == 0)
            sketch.stamp_pending(obj, node_number(node), number)
            amend.update(bundle_dir=str(dest), bundle=written)
        self.amends[number] = amend
        self._local("amend", {"amend": number, "text": text, "bundle_dir": amend["bundle_dir"],
                              "strokes": pending})
        local_entry(self.stream, "amend", {"text": text, "strokes": pending}, node)
        self.bridge.call(Method.AMEND, {"turn_id": node, "amend": number, "text": text,
                                        "bundle_dir": amend["bundle_dir"]},
                         lambda ok, data: self._on_amend_result(number, ok, data))
        return number

    def _queue_amend(self, text: str, scene) -> int:
        run = self._submitted if self.running else self._pending_run
        from_sketch = bool(run and run[3])
        pending = sketch.pending_count(sketch.find_sketch_object()) if from_sketch else 0
        if not text.strip() and not pending:
            raise ValueError("nothing to amend: type a message or draw new strokes")
        self.queued_amends.append((text, scene))
        number = len(self.queued_amends)
        self.stream.note(f"Amendment {number} waits for the turn to start: {text or '(new strokes only)'}",
                         turn_id=self.turn_id or (run[2] if run else None))
        return number

    def _send_queued_amends(self) -> None:
        """The turn was accepted: amendments made while it was starting go in,
        each with the strokes drawn by then."""
        queued, self.queued_amends = self.queued_amends, []
        for text, scene in queued:
            try:
                self.amend(text, scene=scene)
            except (RuntimeError, ValueError, OSError, bundle.BundleError) as exc:
                self._return_text(text, scene, f"could not be sent: {exc}")

    def _return_queued_amends(self, reason: str) -> None:
        queued, self.queued_amends = self.queued_amends, []
        for text, scene in queued:
            self._return_text(text, scene, reason)

    def _return_text(self, text: str, scene, reason: str) -> None:
        """An amendment that never reached a turn: its text goes back to the
        prompt, and strokes drawn for it simply stay pending."""
        moved = _append_to_prompt(scene, text)
        self.stream.note(f"An amendment did not reach the agent ({reason})."
                         + (" Its text is back in the prompt." if moved else ""), kind="warning")

    def _on_amend_result(self, number: int, ok: bool, data: dict) -> None:
        if not ok:
            self._return_amend(number, data.get("message") or data.get("code") or "refused")

    def _return_amend(self, number: int, reason: str) -> None:
        """Hands an amendment the agent never received back to the user: its
        strokes are pending again and its text goes back to the prompt."""
        amend = self.amends.get(number)
        if amend is None or amend["returned"] or amend["delivered"]:
            return
        amend["returned"] = True
        node = self._amend_node(number)
        obj = sketch.find_sketch_object()
        if obj is not None and node is not None:
            try:
                sketch.unstamp_amend(obj, node_number(node), number)
            except (ReferenceError, RuntimeError) as exc:
                log.warning("could not unstamp amendment %d: %s", number, exc)
        if amend["bundle_dir"]:
            shutil.rmtree(amend["bundle_dir"], ignore_errors=True)
        moved = _append_to_prompt(amend.get("scene"), amend["text"])
        self._local("amend_returned", {"amend": number, "reason": reason})
        self.stream.note(f"Amendment {number} did not reach the agent ({reason})."
                         + (" Its text is back in the prompt." if moved else "")
                         + (" Its strokes are pending again." if amend["bundle_dir"] else ""),
                         kind="warning", turn_id=node)

    def _amend_node(self, number: int) -> str | None:
        amend = self.amends.get(number)
        if amend and amend["bundle_dir"]:
            return Path(amend["bundle_dir"]).parent.name
        return self.turn_id

    def _local(self, name: str, data: dict) -> None:
        if self._transcript is not None:
            try:
                self._transcript.write_local(name, data)
            except OSError as exc:
                log.warning("could not write the transcript: %s", exc)

    def _set_phase(self, phase: str, detail: str | None = None) -> None:
        self.status = {"phase": phase, "detail": detail}

    # -- callbacks -----------------------------------------------------------

    def on_event(self, msg: dict) -> None:
        name, data = msg.get("name", ""), msg.get("data") or {}
        self.events.append(msg)
        self.stream.append(name, data)
        if self._transcript is not None and data.get("turn_id") == self.turn_id:
            self._transcript.write(msg)
        current = data.get("turn_id") == self.turn_id and self.running
        if name == Event.MODELS:
            models.received(data)
        elif name == Event.TURN_FINISHED and current:
            self._finish(data)
        elif name == Event.TURN_STARTED and current:
            self._started = True
            self._set_phase("running")
        elif name == Event.AMEND_DELIVERED and current:
            amend = self.amends.get(data.get("amend"))
            if amend is not None and not amend["returned"]:
                amend["delivered"] = True
        elif name == Event.STATUS and current and data.get("state") in ("running", "waiting_user"):
            if not self.interrupting:
                self._set_phase(data["state"], data.get("detail"))
        elif name == Event.STATUS and data.get("state") == SESSION_ENDED:
            # The agent's SDK session is gone though the process lives on; the
            # next run has to start a new one.
            self.session_ready = False
            self.live_node = None
            if self._resumed and self._session_turns == 0:
                # A resumed conversation that ends before taking a turn could
                # not really be resumed; the next start is fresh.
                self._resume_failed = data.get("detail") or "the session ended at once"
            # An accepted turn the end is not tagged with will get no
            # turn_finished. One still being submitted waits for its answer.
            if self.running and self._accepted and data.get("turn_id") != self.turn_id:
                self._finish(self._failed_turn("session_ended", data.get("detail")
                                               or "the agent session ended"))

    def after_undo(self) -> None:
        """The user pressed undo while a turn runs: the scene went back to
        before the turn, or earlier, under the agent's feet. It hears so with
        its next call's result."""
        if not self.running:
            return
        self.commands.notes.append(UNDO_NOTE)
        self._local("undo", {})
        self.stream.note("Undo during a turn takes back what Claude did so far; Claude is told.",
                         kind="warning", turn_id=self.turn_id)

    def _on_ask(self, question: str, choices: list) -> None:
        self.question = {"question": question, "choices": choices}
        self._set_phase("waiting_user", question)

    def _on_state(self, state: AgentState, reason: str | None) -> None:
        if state == AgentState.READY:
            self._advance()
            return
        if state in (AgentState.STARTING, AgentState.BUSY):
            return
        # A start_session still on its way gets no answer from a bridge that
        # is going; the next agent starts its own.
        self._session_starting = False
        self._plan = None
        # The agent is going or gone: a run waiting for it must not fire on
        # some later, unrelated start.
        if self._pending_run is not None:
            self._drop_pending_run()
            if state != AgentState.STOPPING:
                self._error(f"the bundle was not run: the agent {state}"
                            + (f" ({reason})" if reason else ""))
        if state in (AgentState.CRASHED, AgentState.FAILED, AgentState.STOPPED,
                     AgentState.NEEDS_SETUP, AgentState.NEEDS_KEY):
            self.session_ready = False
            self.question = None
            if reason:
                self.stream.note(f"Agent {state}: {reason}")
            if self.running:
                self._finish(self._failed_turn("agent_" + state, reason or f"the agent {state}"))

    def _on_session_started(self, ok: bool, data: dict, params: dict | None = None) -> None:
        self._session_starting = False
        if ok:
            self.session_ready = True
            self.live_node = self._plan_node
            self.commands.namespace = execution.ExecNamespace(self.commands.targets)
            self._advance()
            return
        message = data.get("message") or data.get("code") or "failed"
        self.key_problem = key_problem(message) or self.key_problem
        # A crash fails every pending call: that says nothing about resuming.
        crashed = data.get("code") == ErrorCode.AGENT_CRASHED or self.bridge is None or self.bridge.closed
        if (params and params.get("resume") and self._resume_failed is None and self._pending_run
                and not crashed):
            # The conversation could not be resumed (the session folder moved,
            # say): carry on in a fresh one, with a note in its place.
            self._resume_failed = message
            self.stream.note(f"Could not resume the agent's earlier conversation ({message}); "
                             "starting a new one.", kind="warning")
            self._advance()
            return
        self._drop_pending_run()
        self._error(f"start_session failed: {message}")

    def _on_submit_result(self, ok: bool, data: dict) -> None:
        if ok:
            self._accepted = True
            self._owns_node_dir = False
            began, self._began = self._began, None
            if began is not None:
                chats.turn_began(self.session.root, *began)
            self._session_turns += 1
            self._plan = None
            self._context = []
            self._resume_failed = None
            self._send_queued_amends()
            return
        submitted = self._submitted
        self.process.set_busy(False)
        self._set_phase("idle")
        if data.get("code") == ErrorCode.NO_SESSION and submitted and not self._retried:
            # The session ended while this submit was on its way; start a new
            # one and send the same bundle again, under the same node.
            self._submitted = None
            self.turn_id = None
            self._transcript = None
            self._began = None
            self._retried = True
            self.session_ready = False
            self.live_node = None
            # The refused turn never ran in that session.
            self.history.forget_session(submitted[2])
            if self._resumed and self._session_turns == 0 and self._resume_failed is None:
                self._resume_failed = data.get("message") or "the resumed session ended at once"
            self._pending_run = submitted
            self.stream.note("The agent session had ended; starting a new one.")
            self._advance()
            return
        # The refused turn never ran: its node, and the folder made for it, go.
        if self.turn_id is not None:
            self._abandon_submit(self.turn_id, began=True)
        self.key_problem = key_problem(data.get("message") or "") or self.key_problem
        self._error(f"submit failed: {data.get('message')}")

    def plan_session(self) -> SessionPlan:
        """Which conversation the next submit continues, given the node the
        scene reflects and the live client."""
        current = self.history.current
        live = self.live_node if self.session_ready else None
        if current is None:
            plan = SessionPlan(restart=not self.session_ready)
        else:
            plan = session_plan(self.history.tree, current, live)
        if plan.restart and plan.resume is not None and self._resume_failed is not None:
            note = (f"The earlier conversation could not be resumed ({self._resume_failed}); "
                    "inspect the target before editing.")
            plan = SessionPlan(restart=True, notes=(note,))
        return plan

    def _advance(self) -> None:
        if self._pending_run is None or self.process.state != AgentState.READY:
            return
        if self._session_starting or (not self.session_ready and self.bridge.pending):
            return
        plan = self.plan_session()
        if plan.restart:
            self.session_ready = False
            self._plan, self._plan_node = plan, self.history.current
            self.start_session(plan)
            return
        bundle_dir, prompt, node, from_sketch = self._pending_run
        self._pending_run = None
        try:
            self.submit(bundle_dir, prompt, node, from_sketch=from_sketch)
        except Exception as exc:
            # This runs from a timer or a state callback: nothing above it
            # would report the failure.
            log.exception("submit failed")
            self._error(f"cannot submit the bundle: {exc}")

    def _drop_pending_run(self) -> None:
        """Forgets a run that never reached the agent. A sketch bundle written
        for it is removed: its strokes stay on the sketch for the next run."""
        run, self._pending_run = self._pending_run, None
        if run is None:
            return
        self._give_back_prompt(only_if_empty=False)
        self._return_queued_amends("the turn never started")
        _bundle_dir, _prompt, node, from_sketch = run
        if from_sketch and node is not None and not self.session.transcript_path(node).exists():
            self._free_node(node, unstamp=True)

    def _failed_turn(self, subtype: str, error: str) -> dict:
        return {"turn_id": self.turn_id, "session_id": None, "subtype": subtype,
                "is_error": True, "interrupted": False, "cost_usd": None,
                "num_turns": 0, "duration_ms": None, "result_text": "", "errors": [error],
                "synthetic": True}

    def _finish(self, data: dict) -> None:
        node, from_sketch = self.turn_id, self._from_sketch
        if data.pop("synthetic", False):
            # The agent never sent turn_finished (it crashed, or its session
            # ended): the stream and the transcript still record how the
            # turn ended, so the conversation can say why it failed.
            self.stream.append(Event.TURN_FINISHED, data)
            if self._transcript is not None:
                try:
                    self._transcript.write({"v": protocol.VERSION, "type": "event",
                                            "name": Event.TURN_FINISHED, "data": data})
                except OSError as exc:
                    log.warning("could not write the transcript: %s", exc)
        turn_bundle = self.bundle
        # Undelivered amendments go back first: their strokes carry the turn's
        # stamp and would otherwise be cleared with the turn's own.
        undelivered = set(data.get("amends_undelivered") or [])
        undelivered |= {n for n, a in self.amends.items() if not a["delivered"]}
        for number in sorted(undelivered):
            self._return_amend(number, "the turn ended first")
        self._return_queued_amends("the turn ended first")
        restored = None
        if self._restore_on_finish:
            restored = self._restore_turn_start(node)
        completed = not data.get("is_error") and not data.get("interrupted") and restored is None
        if restored is None and (completed or data.get("interrupted")):
            self._adopt_created_objects()
        result = dict(data)
        if restored is not None:
            result.update(interrupted=True, restored=restored)
        # A failed turn that never touched the scene leaves nothing to restore
        # or compare, so it folds into its parent instead of cluttering the tree.
        folded = (bool(data.get("is_error")) and not data.get("interrupted") and restored is None
                  and self.commands.edits == 0 and not self._created_objects())
        if completed:
            self.key_problem = None
        elif data.get("is_error"):
            self.key_problem = key_problem(" ".join(
                [*(e for e in data.get("errors") or [] if isinstance(e, str)),
                 str(data.get("result_text") or "")])) or self.key_problem
        if folded:
            # The prompt stays out of the prompt box: the folded turn shows
            # it, and Retry or Edit & Resend bring it back.
            self._fold_node(node, result)
            self._sent_prompt = None
        else:
            self._record_node(node, result, turn_bundle, restored is not None)
            self._sent_prompt = None
        self.last_finished = result
        self.turn_id = None
        self._from_sketch = False
        if from_sketch and node is not None and completed:
            self._clear_sent_strokes(node)
            self._clear_sent_refs()
        self._sent_refs = []
        self._accepted = False
        self._started = False
        self._restore_on_finish = False
        self._transcript = None
        self.question = None
        if self.bridge is not None:
            self.bridge.set_interrupted(False)
        self.process.set_busy(False)
        self._set_phase("idle")
        chats.turn_ended(self.session.root)
        if folded:
            return
        label = self.history.node(node).label if self.history.tree and node in self.history.tree.nodes else ""
        history.undo_push(f"{history.UNDO_PREFIX}: {node} {label}".rstrip())

    def _fold_node(self, node: str | None, result: dict) -> None:
        if node is None or self.history.tree is None or node not in self.history.tree.nodes:
            return
        try:
            self.history.fold(node, result)
        except Exception as exc:
            log.exception("folding history node %s failed", node)
            self.stream.note(f"Could not record {node} in the history: {exc}", kind="error", turn_id=node)
        # The live conversation went past the parent with the failed exchange;
        # the next submit forks it at the parent instead.
        self.live_node = None
        self.last_folded = node
        self.stream.note(f"Nothing changed, so {node} is not kept in the history; the next submit "
                         f"starts again from {self.history.current}.", turn_id=node)

    def _record_node(self, node: str | None, result: dict, turn_bundle, restored: bool) -> None:
        """The turn's history node: the target as the turn left it, and the
        conversation it belongs to."""
        if node is None or self.history.tree is None or node not in self.history.tree.nodes:
            return
        created = [] if restored else self._created_objects()
        view = None
        if turn_bundle is not None and turn_bundle.views:
            view = turn_bundle.views[min(turn_bundle.views)]
        try:
            self.history.finish(node, self._turn_objects(), result, scene=self._scene or bpy.context.scene,
                                created=created, restored=restored,
                                kept_partial=bool(result.get("interrupted")) and not restored, view=view)
        except Exception as exc:
            log.exception("recording history node %s failed", node)
            self.stream.note(f"Could not record {node} in the history: {exc}", kind="error", turn_id=node)
        self.live_node = node if result.get("session_id") and self.session_ready else None
        if restored:
            self._context.append(f"Your previous turn ({node}) was interrupted and the target was put "
                                 "back as it was before it.")

    def _turn_objects(self) -> list:
        """The turn's targets and the objects its agent made that still exist."""
        found = {}
        for obj in self.commands.targets() + self._created_objects():
            found.setdefault(obj.as_pointer(), obj)
        return list(found.values())

    def _on_checkpoint_restored(self, objects: list, replaced: dict) -> None:
        """A checkpoint restore replaced objects with appended copies, which
        have new session uids: those that existed before the turn still did."""
        for obj in objects:
            old = replaced.get(obj.get(bundle.UID_PROP))
            if old is not None and old in self._preexisting:
                self._preexisting.add(obj.session_uid)

    def _restore_turn_start(self, node: str | None) -> list[str] | None:
        if self._start is None:
            self.stream.note("The turn start cannot be restored: there is no snapshot.",
                             kind="warning", turn_id=node)
            return None
        try:
            names = snapshot.restore(self._start, remove=[o.name for o in self._created_objects()])
        except Exception as exc:
            log.exception("restoring the turn start failed")
            self.stream.note(f"Restoring the turn start failed: {exc}", kind="error", turn_id=node)
            return None
        self._local("restored", {"objects": names})
        self.stream.note(f"Restored the turn start: {', '.join(names) or 'nothing to restore'}",
                         turn_id=node)
        return names

    def _adopt_created_objects(self) -> None:
        """Objects the agent made this turn become targets, so a follow-up can
        edit them."""
        scene = self._scene
        if scene is None or not hasattr(scene, "whittle"):
            return
        try:
            targets.add(scene, self._created_objects())
            targets.select_list(scene)
        except (ReferenceError, AttributeError) as exc:
            log.warning("could not add the new objects to the targets: %s", exc)

    def _created_objects(self) -> list:
        """Objects this turn's exec calls created: named in an exec diff and
        absent when the turn began."""
        added = set(self.commands.added)
        return [o for o in bpy.data.objects
                if o.name in added and o.session_uid not in self._preexisting]

    def _clear_sent_strokes(self, node: str) -> None:
        """A finished sketch turn's strokes have done their job. Strokes drawn
        during the turn stay for the next one, with the views they use."""
        obj = sketch.find_sketch_object()
        if obj is None:
            return
        try:
            sketch.remove_turn_strokes(obj, node_number(node))
            views.prune_views(obj.data, sketch.used_views(obj))
        except (ReferenceError, RuntimeError) as exc:
            log.warning("could not clear the sent strokes: %s", exc)

    def _clear_sent_refs(self) -> None:
        """Like its strokes, a finished turn's references are done with,
        unless pinned to the session."""
        scene = self._scene
        if not self._sent_refs or scene is None or not hasattr(scene, "whittle"):
            return
        try:
            references.clear_sent(scene, self._sent_refs)
        except (ReferenceError, AttributeError) as exc:
            log.warning("could not clear the sent references: %s", exc)

    def _error(self, message: str) -> None:
        log.error("%s", message)
        self.errors.append(message)
        self.stream.note(message)


def _append_to_prompt(scene, text: str) -> bool:
    """Puts text that never reached the agent at the end of the prompt box;
    returns whether it went there."""
    text = text.strip()
    if not text or scene is None or not hasattr(scene, "whittle"):
        return False
    try:
        props = scene.whittle
        props.prompt = f"{props.prompt} {text}".strip() if props.prompt else text
    except ReferenceError:
        return False
    return True


def _refuse_while_comparing() -> None:
    if compare.active() is not None:
        raise RuntimeError("end the comparison before submitting")


# -- the controller the UI talks to -------------------------------------------

_current: TurnController | None = None


def current() -> TurnController | None:
    return _current


def busy(ctl) -> bool:
    """A turn is running or a run is waiting for the agent (for the real
    controller and the stand-ins tests draw the panel with)."""
    if ctl is None:
        return False
    return bool(getattr(ctl, "busy", getattr(ctl, "running", False)))


def set_current(controller: TurnController | None) -> None:
    global _current
    _current = controller


def shutdown_current() -> None:
    global _current
    if _current is not None:
        _current.close()
        _current = None
