# SPDX-License-Identifier: GPL-3.0-or-later
"""The GUI checks' phases (tests/gui/catalog.py describes each check).

A phase is a generator over a GuiStage, stepped by tests/gui/harness.py in a
real GUI Blender started with --enable-event-simulate. It reaches its state
through the add-on's controller and operators, as the screenshot scenarios
do, but sends the input under test (a key, a drag of the draw tool, a
right-click) as simulated events through Blender's own event handling, and
asserts what came of it with expect(). Phases of one check share the work
folder: what one saves, the next opens, and state.json carries small values
between them."""

import json
import math
import os
import time
from pathlib import Path

import bpy
from bpy_extras import view3d_utils
from mathutils import Euler, Vector

from tests.screens.scenarios import LID, Stage, done, exec_, say
from whittle.addon import chats, history, operators, turn

# Returned by a phase to end its Blender with a kill -9 instead of a quit.
KILL = object()


class Until:
    """Waits for check() to be true, at most timeout seconds."""

    def __init__(self, check, what: str, timeout: float = 20.0):
        self.check = check
        self.what = what
        self.timeout = timeout
        self.deadline = None

    @classmethod
    def of(cls, step) -> "Until":
        """This kind of wait for a screenshot scenario's (the stage's
        finished() gives one)."""
        return step if isinstance(step, cls) else cls(step.check, step.what)

    def start(self) -> "Until":
        self.deadline = time.monotonic() + self.timeout
        return self

    def expired(self) -> bool:
        return time.monotonic() > self.deadline


def expect(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_equal(actual, wanted, what: str) -> None:
    if actual != wanted:
        raise AssertionError(f"{what}: got {actual!r}, wanted {wanted!r}")


# -- the stage ----------------------------------------------------------------

class GuiStage(Stage):
    """The screenshot scenarios' stage, plus simulated input, the work
    folder's state, saving and opening files the way the File menu does,
    and what the fake agent was told."""

    STEP = 0.05

    # state carried from phase to phase

    @property
    def state_path(self) -> Path:
        return self.work / "state.json"

    def recall(self, key: str):
        try:
            return json.loads(self.state_path.read_text())[key]
        except (OSError, ValueError, KeyError) as exc:
            raise AssertionError(f"an earlier phase did not remember {key!r}") from exc

    def remember(self, **values) -> None:
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            state = {}
        state.update(values)
        self.state_path.write_text(json.dumps(state, indent=1) + "\n")

    # the window and the viewport

    @property
    def window(self):
        return bpy.context.window_manager.windows[0]

    def view3d(self):
        """The largest 3D viewport's area, main region and its RegionView3D."""
        o = self.override()
        return o["area"], o["region"], o["area"].spaces.active.region_3d

    def to_window(self, co) -> tuple[int, int]:
        """Where the world point co shows, in window pixels."""
        _area, region, rv3d = self.view3d()
        xy = view3d_utils.location_3d_to_region_2d(region, rv3d, Vector(co))
        expect(xy is not None, f"{tuple(co)} is behind the viewport")
        return round(region.x + xy.x), round(region.y + xy.y)

    def viewport_centre(self) -> tuple[int, int]:
        _area, region, _rv3d = self.view3d()
        return region.x + region.width // 2, region.y + region.height // 2

    def look(self, rotation_euler, distance: float = 6.0, location=(0.0, 0.0, 0.5)) -> None:
        """Sets the viewport's view as orbiting would."""
        _area, _region, rv3d = self.view3d()
        rv3d.view_perspective = "PERSP"
        rv3d.view_rotation = Euler(rotation_euler).to_quaternion()
        rv3d.view_distance = distance
        rv3d.view_location = location

    # simulated input: each helper is a generator, used with `yield from`

    def simulate(self, kind: str, value: str, x: int, y: int, **mods):
        self.window.event_simulate(type=kind, value=value, x=x, y=y, **mods)
        yield self.STEP

    def move(self, x: int, y: int):
        self._pointer = (x, y)
        yield from self.simulate("MOUSEMOVE", "NOTHING", x, y)

    def press(self, key: str, at=None, **mods):
        """A key pressed and released with the pointer at `at` (window
        pixels), so the editor under it gets it."""
        x, y = at or self.viewport_centre()
        yield from self.move(x, y)
        yield from self.simulate(key, "PRESS", x, y, **mods)
        yield from self.simulate(key, "RELEASE", x, y, **mods)

    def key(self, key: str, **mods):
        """A key pressed and released where the pointer is, without moving
        it (inside a menu, a move highlights the item under the pointer)."""
        x, y = getattr(self, "_pointer", (0, 0))
        yield from self.simulate(key, "PRESS", x, y, **mods)
        yield from self.simulate(key, "RELEASE", x, y, **mods)

    DIGITS = ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")
    SIGNS = {" ": "SPACE", ".": "PERIOD", ",": "COMMA", "-": "MINUS"}

    def type_text(self, text: str):
        """Types text where the pointer is, a key per character, as the
        keyboard would (the text field in edit mode takes it)."""
        x, y = getattr(self, "_pointer", (0, 0))
        for ch in text:
            if ch.isalpha():
                kind, shift = ch.upper(), ch.isupper()
            elif ch.isdigit():
                kind, shift = self.DIGITS[int(ch)], False
            else:
                kind, shift = self.SIGNS[ch], False
            self.window.event_simulate(type=kind, value="PRESS", x=x, y=y, shift=shift, unicode=ch)
            yield self.STEP
            self.window.event_simulate(type=kind, value="RELEASE", x=x, y=y, shift=shift)
            yield self.STEP

    def click(self, x: int, y: int, button: str = "LEFTMOUSE", **mods):
        yield from self.move(x, y)
        yield from self.simulate(button, "PRESS", x, y, **mods)
        yield from self.simulate(button, "RELEASE", x, y, **mods)

    def drag(self, points, button: str = "LEFTMOUSE", steps: int = 4):
        """Presses at the first point, moves through the rest (with steps
        moves in between each pair) and releases at the last."""
        (x, y), rest = points[0], points[1:]
        yield from self.move(x, y)
        yield from self.simulate(button, "PRESS", x, y)
        for nx, ny in rest:
            for k in range(1, steps + 1):
                yield from self.simulate("MOUSEMOVE", "NOTHING", round(x + (nx - x) * k / steps),
                                         round(y + (ny - y) * k / steps))
            x, y = nx, ny
        yield from self.simulate(button, "RELEASE", x, y)

    # the sidebar's buttons

    def button(self, idname: str, **props):
        """Runs an operator as a button in the 3D viewport's sidebar does:
        invoked in that region, with an undo step. (Blender has no Python
        API for where a button is drawn, so it is not clicked.)"""
        module, name = idname.split(".")
        area = self.override()["area"]
        region = next(r for r in area.regions if r.type == "UI")
        with bpy.context.temp_override(window=self.window, screen=self.window.screen, area=area, region=region):
            return getattr(getattr(bpy.ops, module), name)("INVOKE_DEFAULT", True, **props)

    # files, as the File menu does them

    def window_override(self) -> dict:
        win = self.window
        return {"window": win, "screen": win.screen}

    def save_as(self, path: Path) -> None:
        with bpy.context.temp_override(**self.window_override()):
            result = bpy.ops.wm.save_as_mainfile(filepath=str(path))
        expect_equal(result, {"FINISHED"}, f"saving {path.name}")

    def settle(self):
        """A few passes of the event loop. Blender marks a saved file
        unmodified when it handles the save's notifier, after the save
        returns, so bpy.data.is_dirty (the title bar's '*') is read after."""
        for _ in range(4):
            yield self.STEP

    def open(self, path: Path) -> None:
        with bpy.context.temp_override(**self.window_override()):
            result = bpy.ops.wm.open_mainfile(filepath=str(path))
        expect_equal(result, {"FINISHED"}, f"opening {path.name}")

    # the agent

    def logs(self, node: str | None = None) -> list[str]:
        """The fake agent's log lines this session, for one turn or all."""
        ctl = self.ctl
        return [e["data"]["message"] for e in (ctl.events if ctl else ())
                if e["name"] == "log" and (node is None or e["data"].get("turn_id") == node)]

    def context_lines(self, node: str) -> list[str]:
        return [m[len("context: "):] for m in self.logs(node) if m.startswith("context: ")]

    def entries(self, kind: str, node: str | None = None) -> list[str]:
        """The texts of this session's stream entries of a kind (note,
        warning, error, ...), for one turn or all."""
        ctl = self.ctl
        return [e.text for e in (ctl.stream.entries() if ctl else ())
                if e.kind == kind and (node is None or e.turn_id == node)]

    def conversation(self):
        """What the sidebar's conversation shows."""
        from whittle.addon import conversation

        return conversation.build(history.active(), self.ctl)

    def history(self):
        found = history.active()
        expect(found is not None and found.tree is not None, "there is no history")
        return found


# -- phases -------------------------------------------------------------------

PHASES = {}


def phase(check: str):
    """Adds fn as the next phase of check."""
    def add(fn):
        PHASES.setdefault(check, []).append(fn)
        return fn
    return add


def nudge_script(stage: GuiStage, name: str, count: int) -> Path:
    return stage.script(name, [
        {"steps": [say(f"Nudging the crate ({k})."),
                   exec_(f"nudge {k}", "bpy.data.objects['Crate'].location.x += 0.1"),
                   say(f"Nudged ({k}).")], "finish": done(f"Nudged {k}.")}
        for k in range(1, count + 1)])


# restart and resume ----------------------------------------------------------

@phase("restart_resume")
def restart_first(stage: GuiStage):
    stage.crate()
    nodes = yield from stage.turns(["Add a lid.", "Nudge it."], nudge_script(stage, "first", 2))
    found = stage.history()
    stage.remember(nodes=nodes, session=found.tree.nodes[nodes[-1]].agent_session_id,
                   chat=found.chat, x=bpy.data.objects["Crate"].location.x)
    stage.save_as(stage.work / "scene.blend")
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "the title bar shows '*' after saving")


@phase("restart_resume")
def restart_reopen(stage: GuiStage):
    # Opened like File > Open from a fresh Blender: load_pre and load_post run.
    stage.open(stage.work / "scene.blend")
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "the title bar shows '*' after opening")
    nodes, session = stage.recall("nodes"), stage.recall("session")
    found = stage.history()
    expect_equal(found.chat, stage.recall("chat"), "the current chat")
    expect_equal(found.tree.current, nodes[-1], "the current node")
    expect(set(nodes) <= set(found.tree.nodes), f"the history lost turns: {sorted(found.tree.nodes)}")
    expect(abs(bpy.data.objects["Crate"].location.x - stage.recall("x")) < 1e-6, "the crate moved")
    shown = [t.node for t in stage.conversation().path_turns]
    expect(nodes[-1] in shown, f"the conversation does not show {nodes[-1]}: {shown}")
    node = stage.submit("Nudge it again.", nudge_script(stage, "second", 1))
    yield stage.finished(node)
    starts = stage.ctl.session_starts
    expect_equal(len(starts), 1, "agent sessions started")
    expect_equal(starts[0].get("resume"), session, "the session the turn resumed")
    expect(not starts[0].get("fork"), "the turn forked instead of resuming")
    expect_equal(stage.context_lines(node), [], "the context the turn was sent (a note means context was lost)")
    expect_equal(stage.history().tree.nodes[node].agent_session_id, session, "the turn's session")


# the dirty flag --------------------------------------------------------------

def expect_no_payload(what: str) -> None:
    holder = bpy.data.texts.get(chats.HOLDER)
    expect(holder is not None, f"{what}: the file has no chats holder")
    expect(chats.PAYLOAD_PROP not in holder and chats.INDEX_PROP not in holder,
           f"{what}: the chats stayed in the open file's data")


@phase("dirty_flag")
def dirty_save(stage: GuiStage):
    stage.crate()
    script = nudge_script(stage, "dirty", 2)
    yield from stage.turns(["Nudge it."], script)
    first = chats.get().current
    stage.run(operators.new_chat)
    yield from stage.turns(["Nudge it again."], script)
    stage.remember(other=chats.get().current)
    stage.run(operators.switch_chat, first)
    expect(bpy.data.is_dirty, "the turns did not mark the file modified")
    stage.save_as(stage.work / "scene.blend")
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "saving (the chats packed into the file) left the title bar's '*'")
    expect_no_payload("after saving")
    # Ctrl+S with nothing changed packs again from the cache.
    yield from stage.press("S", ctrl=True)
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "Ctrl+S left the title bar's '*'")


@phase("dirty_flag")
def dirty_open(stage: GuiStage):
    stage.open(stage.work / "scene.blend")
    yield from stage.settle()
    expect_no_payload("after opening")
    expect(not bpy.data.is_dirty, "opening (the chats taken out of the file) set the title bar's '*'")
    # The other chat is only packed until it is switched to: switching
    # unpacks it, and changes nothing in the scene.
    stage.run(operators.switch_chat, stage.recall("other"))
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "switching to a packed chat set the title bar's '*'")
    stage.run(operators.new_chat)
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "New Chat set the title bar's '*'")


# crashes and Blender's recovery files ----------------------------------------

def saved_then_unsaved(stage: GuiStage, name: str):
    """The crate, a turn, a save, then a turn that is not saved. Remembers
    both nodes, the chat, the file's id and the unsaved turn's session."""
    stage.crate()
    script = nudge_script(stage, name, 2)
    (saved,) = yield from stage.turns(["Nudge it."], script)
    stage.save_as(stage.work / "scene.blend")
    yield from stage.settle()
    (unsaved,) = yield from stage.turns(["Nudge it again."], script)
    found = stage.history()
    stage.remember(saved=saved, unsaved=unsaved, chat=found.chat, file_id=chats.file_id(),
                   session=found.tree.nodes[unsaved].agent_session_id,
                   x=bpy.data.objects["Crate"].location.x)


def expect_unsaved_turn(stage: GuiStage):
    """The chats are the original's, with the turn made after its save."""
    found = stage.history()
    expect_equal(chats.file_id(), stage.recall("file_id"), "the file's id (so its cache)")
    expect_equal(found.chat, stage.recall("chat"), "the current chat")
    unsaved = stage.recall("unsaved")
    expect(unsaved in found.tree.nodes, f"the unsaved turn {unsaved} is gone: {sorted(found.tree.nodes)}")
    shown = [t.node for t in stage.conversation().path_turns]
    expect_equal(shown[-1:], [unsaved], "the conversation's last turn")


def expect_resumes(stage: GuiStage, name: str):
    node = stage.submit("And once more.", nudge_script(stage, name, 1))
    yield stage.finished(node)
    starts = stage.ctl.session_starts
    expect_equal([s.get("resume") for s in starts], [stage.recall("session")], "the sessions resumed")
    expect_equal(stage.context_lines(node), [], "the context the turn was sent")


def record(stage: GuiStage) -> dict:
    from whittle import caches

    return caches.read_record(chats.root())


@phase("crash_keeps_chats")
def crash_turn(stage: GuiStage):
    yield from saved_then_unsaved(stage, "crash")
    return KILL


@phase("crash_keeps_chats")
def crash_reopen(stage: GuiStage):
    # Started with the file, as after a crash: Blender enables the installed
    # add-on, then opens the file, and load_post finds its chats. The cache's
    # newer work stays, so the unsaved turn is still in the history; the
    # crash lost its scene, so the conversation follows the file's, the
    # saved turn, and the next turn branches from there, the agent told.
    yield from stage.settle()
    found = stage.history()
    saved, unsaved = stage.recall("saved"), stage.recall("unsaved")
    expect_equal(chats.file_id(), stage.recall("file_id"), "the file's id (so its cache)")
    expect_equal(found.chat, stage.recall("chat"), "the current chat")
    expect(unsaved in found.tree.nodes, f"the unsaved turn {unsaved} is gone: {sorted(found.tree.nodes)}")
    expect_equal(found.tree.current, saved, "the current node (the file's scene)")
    shown = [t.node for t in stage.conversation().path_turns]
    expect_equal(shown[-1:], [saved], "the conversation's last turn")
    node = stage.submit("And once more.", nudge_script(stage, "crash-after", 1))
    yield stage.finished(node)
    expect_equal(stage.history().tree.nodes[node].parent, saved, "the turn after the crash's parent")
    starts = stage.ctl.session_starts
    expect_equal([(s.get("resume"), s.get("fork")) for s in starts], [(stage.recall("session"), True)],
                 "the session the turn forked")
    expect(any(saved in line for line in stage.context_lines(node)),
           f"the agent was not told where the turn continues from: {stage.context_lines(node)}")


def tmp_files(stage: GuiStage, pattern: str) -> list[Path]:
    return sorted((stage.work / "tmp").glob(pattern), key=lambda p: p.stat().st_mtime)


@phase("recover_last_session")
def quit_unsaved(stage: GuiStage):
    yield from saved_then_unsaved(stage, "quit")
    # The harness quits Blender, which writes quit.blend.


@phase("recover_last_session")
def recover_last(stage: GuiStage):
    expect(tmp_files(stage, "quit.blend"), "quitting wrote no quit.blend")
    with bpy.context.temp_override(**stage.window_override()):
        result = bpy.ops.wm.recover_last_session()
    expect_equal(result, {"FINISHED"}, "File > Recover > Last Session")
    yield from stage.settle()
    print(f"gui: recovered {bpy.data.filepath!r}", flush=True)
    expect_unsaved_turn(stage)
    expect_equal(Path(record(stage)["path"]), stage.work / "scene.blend", "the path the cache records")
    expect(abs(bpy.data.objects["Crate"].location.x - stage.recall("x")) < 1e-6,
           "the recovered scene is not the last session's")
    yield from expect_resumes(stage, "quit-after")


@phase("recover_autosave")
def autosave_unsaved(stage: GuiStage):
    yield from saved_then_unsaved(stage, "autosave")
    # Blender's own autosave timer, at its shortest (a minute).
    bpy.context.preferences.filepaths.use_auto_save_temporary_files = True
    bpy.context.preferences.filepaths.auto_save_time = 1
    yield Until(lambda: tmp_files(stage, "*_autosave.blend"), "Blender's autosave", timeout=100)
    return KILL


@phase("recover_autosave")
def recover_autosave(stage: GuiStage):
    (autosave,) = tmp_files(stage, "*_autosave.blend")
    with bpy.context.temp_override(**stage.window_override()):
        result = bpy.ops.wm.recover_auto_save(filepath=str(autosave))
    expect_equal(result, {"FINISHED"}, "File > Recover > Auto Save")
    yield from stage.settle()
    print(f"gui: recovered {bpy.data.filepath!r}", flush=True)
    expect_unsaved_turn(stage)
    expect_equal(Path(record(stage)["path"]), stage.work / "scene.blend", "the path the cache records")
    expect(abs(bpy.data.objects["Crate"].location.x - stage.recall("x")) < 1e-6,
           "the recovered scene is not the autosaved one")
    yield from expect_resumes(stage, "autosave-after")


# Save As ----------------------------------------------------------------------

def file_browser():
    """The window and area of an open file browser, or (None, None)."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "FILE_BROWSER":
                return win, area
    return None, None


def confirm(stage: GuiStage, win, area):
    """Return over the file browser's file list. The press runs the
    operator and closes the browser's window; a release sent to a closed
    window would crash Blender, so it goes only to one still open."""
    region = next(r for r in area.regions if r.type == "WINDOW")
    x, y = region.x + region.width // 2, region.y + region.height // 2
    win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    yield stage.STEP
    win.event_simulate(type="RET", value="PRESS", x=x, y=y)
    yield stage.STEP
    if any(w == win for w in bpy.context.window_manager.windows):
        win.event_simulate(type="RET", value="RELEASE", x=x, y=y)
        yield stage.STEP


@phase("save_as")
def save_as(stage: GuiStage):
    stage.crate()
    script = stage.script("save_as", [
        {"steps": [say("First."), exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1")],
         "finish": done("Nudged.")},
        {"steps": [say("Second, slowly."), exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1"),
                   {"sleep": 3}, exec_("nudge again", "bpy.data.objects['Crate'].location.y += 0.1"),
                   say("Done.")],
         "finish": done("Nudged twice.")}])
    (first,) = yield from stage.turns(["Nudge it."], script)
    stage.save_as(stage.work / "scene.blend")
    yield from stage.settle()
    file_id, root = chats.file_id(), chats.root()
    second = stage.submit("Nudge it twice.", script)
    yield Until(lambda: stage.entries("text", second), "the second turn to start")

    # File > Save As (Shift+Ctrl+S) over the viewport opens the file
    # browser; a name typed into it and Return save.
    yield from stage.press("S", ctrl=True, shift=True)
    yield Until(lambda: file_browser()[0] is not None, "the Save As file browser")
    win, area = file_browser()
    params = area.spaces.active.params
    params.filename = "moved.blend"
    yield from confirm(stage, win, area)
    moved = stage.work / "moved.blend"
    yield Until(lambda: moved.is_file() and Path(bpy.data.filepath) == moved, "the file saved as moved.blend")
    expect(stage.ctl.running, "the turn did not run on through Save As")
    yield stage.finished(second)
    found = stage.history()
    expect(not found.tree.nodes[second].folded, "the turn through Save As did not finish")
    expect_equal((chats.file_id(), chats.root()), (file_id, root), "the cache after Save As")
    expect_equal(Path(record(stage)["path"]), moved, "the path the cache records")

    # Ctrl+S over the viewport saves moved.blend again, and leaves no '*'.
    yield from stage.press("S", ctrl=True)
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "the title bar shows '*' after Ctrl+S")
    expect_equal(Path(record(stage)["path"]), moved, "the path the cache records")

    # The file left behind stores the same id, but that cache is
    # moved.blend's now: it gets its own, filled from its own chats.
    stage.open(stage.work / "scene.blend")
    yield from stage.settle()
    expect(chats.file_id() not in (None, file_id), f"scene.blend took {chats.file_id()}, moved.blend's cache")
    nodes = stage.history().tree.nodes
    expect(first in nodes and second not in nodes, f"scene.blend's chats are not what it stores: {sorted(nodes)}")
    stage.open(moved)
    yield from stage.settle()
    expect_equal(chats.file_id(), file_id, "moved.blend's cache")
    expect(second in stage.history().tree.nodes, "moved.blend lost the turn made through Save As")


# undo -------------------------------------------------------------------------

def crate_x() -> float:
    return round(bpy.data.objects["Crate"].location.x, 6)


def crate_y() -> float:
    return round(bpy.data.objects["Crate"].location.y, 6)


@phase("undo_turn")
def undo_turn(stage: GuiStage):
    script = stage.script("undo_turn", [{"steps": [
        say("Moving the crate."),
        exec_("move", "bpy.data.objects['Crate'].location.x += 0.5"),
        {"sleep": 4},
        exec_("look", "print(round(bpy.data.objects['Crate'].location.x, 3))"),
        say("Done.")], "finish": done("Moved.")}])
    yield from select_crate(stage)
    # A change after the user's last undo step that has none of its own (a
    # script's, say): only the turn's own step holds it.
    bpy.data.objects["Crate"].location.y = 0.2
    start = (crate_x(), crate_y())
    node = stage.submit("Move the crate.", script)
    yield Until(lambda: stage.tools("ok"), "the agent's first call")
    moved = (round(start[0] + 0.5, 6), start[1])
    expect_equal((crate_x(), crate_y()), moved, "the crate after the agent's call")
    # Ctrl+Z with the pointer over the viewport, while the turn runs.
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    expect_equal((crate_x(), crate_y()), start, "the crate after Ctrl+Z (exactly the turn's start)")
    # Redo brings the agent's edit back, and Ctrl+Z takes it away again.
    yield from stage.press("Z", ctrl=True, shift=True)
    yield from stage.settle()
    expect_equal((crate_x(), crate_y()), moved, "the crate after Ctrl+Shift+Z")
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    expect_equal((crate_x(), crate_y()), start, "the crate after Ctrl+Z again")
    expect(any("Undo during a turn" in t for t in stage.entries("warning", node)),
           f"the conversation does not say the turn was undone: {stage.entries('warning', node)}")
    yield stage.finished(node)
    results = [e["data"] for e in stage.ctl.events if e["name"] == "tool_result"]
    expect_equal(len(results), 2, "the agent's call results")
    expect(turn.UNDO_NOTE[:60] not in results[0]["summary"], "the note came before the undo")
    expect(turn.UNDO_NOTE[:60] in results[1]["summary"],
           f"the agent was not told of the undo: {results[1]['summary']!r}")
    found = stage.history()
    expect_equal(found.tree.current, node, "the current node after the turn")
    expect(not found.tree.nodes[node].folded, "the turn was not recorded")
    expect_equal(bpy.context.scene.whittle.history_node, node, "the node the scene shows")


def select_crate(stage: GuiStage):
    """The crate scene, the crate selected by a click in the viewport: the
    user's last undo step, as it would be before a turn."""
    stage.crate(pick=False)
    bpy.context.view_layer.objects.active = None
    yield from stage.settle()
    yield from stage.click(*stage.to_window((0.0, -0.3, 0.3)))
    yield from stage.settle()
    crate = bpy.data.objects["Crate"]
    expect(crate.select_get(), "clicking the crate did not select it")
    from whittle.addon import targets

    yield Until(lambda: targets.resolve(bpy.context.scene) == [crate], "Auto to target the crate")


@phase("undo_compare")
def undo_compare(stage: GuiStage):
    from whittle.addon import compare

    stage.crate()
    first, second = yield from stage.turns(["Nudge it.", "Nudge it again."], nudge_script(stage, "compare", 2))
    after_second = crate_x()
    stage.run(operators.compare_node, first)
    yield from stage.settle()
    comparison = compare.active()
    expect(comparison is not None, "the comparison did not start")
    after_first = crate_x()
    expect(after_first != after_second, "the comparison does not show the earlier turn")
    live = comparison.live_blend
    expect(live.is_file(), "the comparison has no live snapshot")
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    expect(compare.active() is None, "Ctrl+Z did not end the comparison")
    expect(not live.is_file(), "the comparison's live snapshot was left behind")
    # The undo put back the scene of the step before the second turn's end:
    # the first turn's. The comparison leaves it as it is, and the history
    # follows it.
    expect_equal(crate_x(), after_first, "the crate after Ctrl+Z")
    expect_equal(stage.history().tree.current, first, "the current node after Ctrl+Z")
    expect_equal(bpy.context.scene.whittle.history_node, first, "the node the scene shows")
    # Redo goes forward to the second turn, with no comparison to undo.
    yield from stage.press("Z", ctrl=True, shift=True)
    yield from stage.settle()
    expect_equal(crate_x(), after_second, "the crate after Ctrl+Shift+Z")
    expect_equal(stage.history().tree.current, second, "the current node after Ctrl+Shift+Z")


# a real transform --------------------------------------------------------------

def modal_running() -> bool:
    return any(w.modal_operators for w in bpy.context.window_manager.windows)


@phase("modal_wait")
def modal_wait(stage: GuiStage):
    stage.crate()
    script = stage.script("modal_wait", [{"steps": [
        say("Looking first."),
        exec_("look", "print('look')"),
        {"sleep": 1},
        exec_("scale", "import time\nbpy.data.objects['Crate'].scale.z = 2.0\n"
                       "bpy.app.driver_namespace['gui_ran'] = time.monotonic()"),
        exec_("after", "bpy.app.driver_namespace['gui_after'] = time.monotonic()"),
        say("Done.")], "finish": done("Scaled.")}])
    bpy.app.driver_namespace.pop("gui_ran", None)
    node = stage.submit("Make it taller.", script)
    yield Until(lambda: stage.tools("ok"), "the agent's first call")
    # G with the pointer over the viewport, the crate selected, then a move.
    x, y = stage.to_window((0.0, 0.0, 0.3))
    yield from stage.press("G", at=(x, y))
    yield Until(modal_running, "the transform to start")
    yield from stage.move(x + 60, y)
    yield from stage.move(x + 120, y)
    # The agent's scene call is now waiting for the transform.
    yield Until(lambda: len(stage.tools("pending")) == 1, "the agent's next call")
    yield 1.5
    expect(modal_running(), "the transform ended by itself")
    expect("gui_ran" not in bpy.app.driver_namespace, "the agent's code ran during the transform")
    expect_equal(round(bpy.data.objects["Crate"].scale.z, 3), 1.0, "the crate's height during the transform")
    moved = bpy.data.objects["Crate"].location.x
    expect(moved > 0.05, f"the transform did not move the crate (x = {moved})")
    confirmed = time.monotonic()
    yield from stage.simulate("LEFTMOUSE", "PRESS", x + 120, y)
    yield from stage.simulate("LEFTMOUSE", "RELEASE", x + 120, y)
    yield stage.finished(node)
    ran, after = bpy.app.driver_namespace.get("gui_ran"), bpy.app.driver_namespace.get("gui_after")
    expect(ran is not None and ran >= confirmed, "the agent's call did not run after the transform")
    expect(after is not None and after >= ran, "the calls behind it ran out of order")
    crate = bpy.data.objects["Crate"]
    expect_equal(round(crate.scale.z, 3), 2.0, "the crate's height after the turn")
    expect(abs(crate.location.x - moved) < 1e-4, "the user's move was lost")
    expect_equal(stage.ctl.last_finished.get("errors") or [], [], "the turn's errors")


# references -------------------------------------------------------------------

def sidebar(stage: GuiStage):
    area, _region, _rv3d = stage.view3d()
    return area, next(r for r in area.regions if r.type == "UI")


def ref_objects() -> list:
    from whittle.addon import targets

    return [o for o in bpy.data.objects if targets.REFERENCE_PROP in o]


@phase("references_view")
def references_view(stage: GuiStage):
    stage.crate()
    ref = stage.props.refs.add()
    ref.path = str(stage.write_image("front", (0.8, 0.5, 0.2)))
    area, _ui = sidebar(stage)
    area.spaces.active.show_region_ui = True
    stage.look((math.radians(70), 0.0, math.radians(35)), distance=5.0, location=(0.2, 0.1, 0.4))
    _area, _region, rv3d = stage.view3d()
    yield from stage.settle()
    placed = {}
    # Each of the reference chip's menu entries, run as the menu runs them:
    # in the sidebar's region of the orbited viewport.
    for align in ("VIEW", "FRONT", "RIGHT", "TOP"):
        before = set(ref_objects())
        expect_equal(stage.button("whittle.ref_place", index=0, align=align), {"FINISHED"}, f"placing {align}")
        (obj,) = set(ref_objects()) - before
        placed[align] = obj
        yield stage.STEP
    view = placed["VIEW"]
    facing = view.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))
    towards_eye = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
    expect(facing.dot(towards_eye) > 0.999, f"Place Facing the View does not face the view: {tuple(facing)}")
    centre = view.matrix_world.translation
    expect((centre - rv3d.view_location).length < 1e-4, "Place Facing the View is not at the view's centre")
    cursor = bpy.context.scene.cursor.location
    for align, normal, where in (("FRONT", (0, -1, 0), (0, 1, 0)), ("RIGHT", (1, 0, 0), (-1, 0, 0)),
                                 ("TOP", (0, 0, 1), (0, 0, -0.01))):
        obj = placed[align]
        got = obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))
        expect(got.dot(Vector(normal)) > 0.999, f"{align} faces {tuple(got)}, not {normal}")
        offset = obj.matrix_world.translation - cursor
        expect(offset.normalized().dot(Vector(where).normalized()) > 0.999,
               f"{align} is not behind the model from that side: {tuple(offset)}")


# start points and real strokes -------------------------------------------------

def sketch_object():
    from whittle.addon import sketch

    obj = sketch.find_sketch_object()
    expect(obj is not None, "there is no sketch object")
    return obj


def strokes() -> list:
    from whittle.addon import sketch

    return list(sketch.iter_strokes(sketch_object()))


def draw(stage: GuiStage, world_points, steps: int = 6):
    """Drags the draw tool through where these world points show."""
    count = len(strokes())
    yield from stage.drag([stage.to_window(p) for p in world_points], steps=steps)
    yield Until(lambda: len(strokes()) > count, "the stroke to be drawn")
    yield Until(lambda: all(s.view for s in strokes()), "the stroke to be tagged with its view")
    return strokes()[-1]


def start_sketching(stage: GuiStage):
    from whittle.addon import sketch

    result = stage.button("whittle.sketch")
    expect_equal(result, {"FINISHED"}, "Sketch")
    yield Until(lambda: sketch.current_session() is not None, "sketch mode")
    expect_equal(bpy.context.object.mode, "PAINT_GREASE_PENCIL", "the mode while sketching")


def surface_distance(obj, point) -> float:
    """How far point lies from obj's surface."""
    local = obj.matrix_world.inverted() @ Vector(point)
    ok, closest, _normal, _index = obj.closest_point_on_mesh(local)
    expect(ok, f"no closest point on {obj.name}")
    return (obj.matrix_world @ closest - Vector(point)).length


def sent(stroke) -> "formats.Stroke":
    """The stroke as a request bundle would send it: its points' on-surface
    flags and the objects hit, judged along its view's lines of sight."""
    from whittle.addon import bundle, views

    obj = sketch_object()
    found = {v.id: v for v in views.load_views(obj.data)}
    for s in bundle.gather_strokes(bpy.context.scene, bpy.context.evaluated_depsgraph_get(), obj, found, None):
        if s.points == [[bundle._r(c, 5) for c in p] for p in stroke.points]:
            return s
    raise AssertionError("the stroke is not in the bundle")


def expect_on_surface(obj, stroke, what: str) -> None:
    """Every point on obj as the agent is told, and on its surface within
    the depth precision the draw tool places points with."""
    from whittle.addon import bundle

    expect(len(stroke.points) >= 3, f"{what} has {len(stroke.points)} points")
    s = sent(stroke)
    distances = [round(surface_distance(obj, p), 4) for p in stroke.points]
    print(f"gui: {what}: {len(distances)} points, off the surface by {distances}", flush=True)
    expect(all(s.on_surface) and set(s.hit_object) == {obj.name},
           f"{what} is not sent as on {obj.name}: {list(zip(s.on_surface, s.hit_object))}")
    eye = _eye()
    abs_tol, rel_tol = bundle.SURFACE_TOLERANCE
    for p, distance in zip(stroke.points, distances):
        expect(distance <= abs_tol + rel_tol * (Vector(p) - eye).length,
               f"{what} has a point {distance:.4f} m off {obj.name}'s surface")


def _eye() -> Vector:
    area = max((a for a in bpy.context.window_manager.windows[0].screen.areas if a.type == "VIEW_3D"),
               key=lambda a: a.width * a.height)
    return area.spaces.active.region_3d.view_matrix.inverted().translation


@phase("blank_sketch")
def blank_sketch(stage: GuiStage):
    from whittle.addon import targets

    scene = bpy.context.scene
    cube = bpy.data.objects["Cube"]
    expect(cube.select_get(), "the default cube is not selected to begin with")
    objects, matrix = set(bpy.data.objects), cube.matrix_world.copy()
    result = stage.button("whittle.start_blank")
    expect_equal(result, {"FINISHED"}, "Start Blank")
    yield from stage.settle()
    expect_equal(set(bpy.data.objects), objects, "the objects after Start Blank")
    expect(not cube.select_get() and bpy.context.view_layer.objects.active is None, "the cube is still selected")
    expect(cube.matrix_world == matrix, "Start Blank moved the cube")
    expect_equal(targets.resolve(scene), [], "the targets after Start Blank")
    expect("new objects" in targets.describe(scene).lower(),
           f"the target line does not say Claude makes new objects: {targets.describe(scene)!r}")

    scene.cursor.location = (0.0, 0.0, 0.0)
    stage.look((math.radians(60), 0.0, math.radians(30)), distance=7.0, location=(0.0, 0.0, 0.0))
    yield from stage.settle()
    yield from start_sketching(stage)
    on = yield from draw(stage, [(-0.6, -0.5, 1.0), (0.0, 0.0, 1.0), (0.6, 0.5, 1.0)])
    expect_on_surface(cube, on, "the stroke drawn over the cube")
    # Off every surface: the view plane through the 3D cursor.
    _area, _region, rv3d = stage.view3d()
    towards_eye = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
    side = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    off = yield from draw(stage, [-2.6 * side + Vector((0, 0, 1.2)), -2.6 * side, -2.6 * side - Vector((0, 0, 1.2))])
    for p in off.points:
        depth = (Vector(p) - scene.cursor.location).dot(towards_eye)
        expect(abs(depth) < 1e-3, f"a stroke off the surfaces is {depth:.4f} m off the view plane at the cursor")
    expect(min(surface_distance(cube, p) for p in off.points) > 0.5, "the stroke off the cube touched it")

    # The first turn makes a new object, which becomes the target.
    script = stage.script("blank", [{"steps": [
        say("Making a box."),
        exec_("box", "mesh = bpy.data.meshes.new('Box')\nbox = bpy.data.objects.new('Box', mesh)\n"
                     "bpy.context.scene.collection.objects.link(box)"),
    ], "finish": done("Made a box.")}])
    yield from stage.turns(["Make a box where I drew."], script)
    expect_equal([o.name for o in targets.resolve(scene)], ["Box"], "the targets after the first turn")
    expect(cube.matrix_world == matrix, "the turn moved the cube")


@phase("primitive_sketch")
def primitive_sketch(stage: GuiStage):
    from whittle.addon import targets

    scene = bpy.context.scene
    scene.cursor.location = (1.5, -0.5, 0.4)
    result = stage.button("whittle.start_primitive", kind="CYLINDER")
    expect_equal(result, {"FINISHED"}, "Start From Primitive")
    yield from stage.settle()
    found = targets.resolve(scene)
    expect_equal(len(found), 1, "the targets after Start From Primitive")
    (cylinder,) = found
    expect(cylinder.name.startswith("Cylinder"), f"the target is {cylinder.name}")
    expect((cylinder.location.xy - scene.cursor.location.xy).length < 1e-6, "the cylinder is not at the cursor")
    lowest = min((cylinder.matrix_world @ Vector(c)).z for c in cylinder.bound_box)
    expect(abs(lowest) < 1e-4, f"the cylinder does not stand on z = 0 (its base is at {lowest})")
    expect(cylinder.select_get() and bpy.context.view_layer.objects.active == cylinder,
           "the cylinder is not selected and active")
    expect(stage.props.target_auto, "Auto is off")
    # Auto follows the selection, which is the cylinder: it stays the target.
    yield 0.5
    expect_equal(targets.resolve(scene), [cylinder], "the targets once Auto has looked")

    stage.look((math.radians(65), 0.0, math.radians(20)), distance=6.0, location=cylinder.location)
    yield from stage.settle()
    yield from start_sketching(stage)
    top = max((cylinder.matrix_world @ Vector(c)).z for c in cylinder.bound_box)
    c = cylinder.location
    stroke = yield from draw(stage, [(c.x - 0.2, c.y - 0.1, top), (c.x, c.y, top), (c.x + 0.2, c.y + 0.1, top)])
    expect_on_surface(cylinder, stroke, "the stroke drawn over the cylinder")
    expect_equal(targets.resolve(scene), [cylinder], "the targets while sketching")


@phase("sketch_undo")
def sketch_undo(stage: GuiStage):
    from whittle.addon import sketch, views

    placement = bpy.context.scene.tool_settings.gpencil_stroke_placement_view3d
    stage.crate()
    stage.look((math.radians(70), 0.0, math.radians(20)), distance=3.0, location=(0.0, 0.0, 0.3))
    yield from stage.settle()
    yield from start_sketching(stage)
    first = yield from draw(stage, [(-0.2, -0.25, 0.4), (0.0, -0.25, 0.3), (0.2, -0.25, 0.2)])
    expect_on_surface(bpy.data.objects["Crate"], first, "the first stroke")
    # Ctrl+Z over the viewport takes the stroke back and stays in Draw Mode.
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    expect_equal(len(strokes()), 0, "the strokes after Ctrl+Z")
    expect(sketch.current_session() is not None, "Ctrl+Z ended sketch mode")
    expect_equal(sketch_object().mode, "PAINT_GREASE_PENCIL", "the mode after Ctrl+Z")
    # A stroke drawn after the undo is still tagged with its view.
    stage.look((math.radians(70), 0.0, math.radians(-40)), distance=3.0, location=(0.0, 0.0, 0.3))
    yield from stage.settle()
    second = yield from draw(stage, [(0.25, -0.1, 0.4), (0.25, 0.0, 0.3), (0.25, 0.1, 0.2)])
    expect_on_surface(bpy.data.objects["Crate"], second, "the stroke drawn after Ctrl+Z")
    expect(second.view > 0, "the stroke after Ctrl+Z has no view")
    # A stroke is tagged with the view it was drawn in before the user can
    # orbit: an orbit right after the release does not change its view.
    eye = _eye()
    count = len(strokes())
    yield from stage.drag([stage.to_window(p) for p in ((0.25, -0.1, 0.15), (0.25, 0.1, 0.1))], steps=6)
    stage.look((math.radians(40), 0.0, math.radians(120)), distance=4.0, location=(0.0, 0.0, 0.3))
    yield Until(lambda: len(strokes()) > count and strokes()[-1].view, "the stroke to be tagged")
    view = {v.id: v for v in views.load_views(sketch_object().data)}[strokes()[-1].view]
    drawn_from = Vector([row[3] for row in view.camera["matrix_world"][:3]])
    expect((drawn_from - eye).length < 1e-3,
           f"the stroke took the view after the orbit: drawn from {tuple(eye)}, tagged {tuple(drawn_from)}")
    # Stop Sketching puts the user's placement and Object Mode back.
    expect_equal(stage.button("whittle.sketch_stop"), {"FINISHED"}, "Stop Sketching")
    yield from stage.settle()
    expect_equal(bpy.context.scene.tool_settings.gpencil_stroke_placement_view3d, placement,
                 "the placement after sketching")
    expect_equal(sketch_object().mode, "OBJECT", "the sketch's mode after sketching")


# the Asset Browser -------------------------------------------------------------

LIBRARY = "GUI Checks"


def make_asset_library(stage: GuiStage) -> Path:
    """A library folder with one file holding an object asset, Barrel."""
    from whittle.addon import start

    folder = stage.work / "assets"
    folder.mkdir(exist_ok=True)
    barrel = bpy.data.objects.new("Barrel", start.primitive_mesh("CYLINDER", 0.8, "Barrel"))
    barrel.asset_mark()
    path = folder / "barrel.blend"
    bpy.data.libraries.write(str(path), {barrel}, fake_user=True)
    mesh = barrel.data
    bpy.data.objects.remove(barrel)
    bpy.data.meshes.remove(mesh)
    library = bpy.context.preferences.filepaths.asset_libraries.new(name=LIBRARY, directory=str(folder))
    expect(library is not None, "the asset library could not be added")
    return path


def selected_assets(win, area, region) -> list[str]:
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        return [a.name for a in (bpy.context.selected_assets or [])]


@phase("asset_browser")
def asset_browser(stage: GuiStage):
    from whittle.addon import targets

    scene = bpy.context.scene
    path = make_asset_library(stage)
    win = stage.window
    # The Properties editor becomes an Asset Browser on the new library.
    area = next(a for a in win.screen.areas if a.type == "PROPERTIES")
    area.ui_type = "ASSETS"
    yield from stage.settle()
    space = area.spaces.active
    space.params.asset_library_reference = LIBRARY
    # The catalog list would take most of the narrow area.
    space.show_region_toolbar = False
    space.show_region_tool_props = False
    region = next(r for r in area.regions if r.type == "WINDOW")
    yield 1.0
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        bpy.ops.file.select_all(action="SELECT")
    expect_equal(selected_assets(win, area, region), ["Barrel"], "the assets the library lists")
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        bpy.ops.file.select_all(action="DESELECT")
    print(f"gui: the Asset Browser's file list is {region.width}x{region.height}", flush=True)
    # Click the first tile: the top-left of the file list.
    size = space.params.display_size
    for dy in range(size // 2, size * 2, max(8, size // 4)):
        x, y = region.x + 12 + size // 2, region.y + region.height - dy
        yield from stage.click(x, y)
        yield 0.2
        if selected_assets(win, area, region) == ["Barrel"]:
            break
    else:
        raise AssertionError("no click on the Asset Browser's first tile selected Barrel")
    scene.cursor.location = (-1.0, 2.0, 0.0)
    objects = set(bpy.data.objects)
    # Right-click on it: the context menu opens with Start Whittle From
    # Asset at its end, which Up then Return run.
    yield from stage.click(x, y, button="RIGHTMOUSE")
    yield 0.4
    yield from stage.press("UP_ARROW", at=(x, y))
    yield from stage.press("RET", at=(x, y))
    yield Until(lambda: set(bpy.data.objects) - objects, "the asset to be appended")
    (barrel,) = set(bpy.data.objects) - objects
    expect(barrel.name.startswith("Barrel"), f"the menu entry appended {barrel.name}")
    expect((barrel.location.xy - scene.cursor.location.xy).length < 1e-6, "the asset is not at the 3D cursor")
    expect_equal(targets.resolve(scene), [barrel], "the targets after Start Whittle From Asset")
    expect_equal(list(bpy.data.libraries), [], "the libraries in the file (Blender File view)")
    expect(not barrel.asset_data, "the appended object is still marked as an asset")
    expect(path.is_file(), "the library file went away")


# the Shift+Alt+Enter key -----------------------------------------------------------

def send_key(stage: GuiStage):
    """Shift+Alt+Enter with the pointer over the viewport."""
    yield from stage.press("RET", shift=True, alt=True)
    yield from stage.settle()


@phase("send_key")
def send_key_check(stage: GuiStage):
    stage.crate()
    script = stage.script("send_key", [
        {"steps": [say("Nudging."), exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1")],
         "finish": done("Nudged.")},
        {"steps": [say("Working on it."), exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1"),
                   {"wait_amend": 15}, exec_("after", "print('after the amendment')")],
         "finish": done("Amended.")}])
    bpy.context.window_manager.whittle_fake_script = str(script)

    # Between turns: nothing to send, nothing sent; a typed prompt is sent.
    yield from send_key(stage)
    expect(stage.ctl is None or stage.ctl.turn_id is None, "the key sent with nothing to send")
    stage.props.prompt = "Nudge it."
    yield from send_key(stage)
    # The fake agent's turn may well be over before the key's event is.
    yield Until(lambda: stage.ctl is not None and (stage.ctl.last_finished or {}).get("turn_id"),
                "the turn the key sent to finish")
    first = stage.ctl.last_finished["turn_id"]
    expect_equal(stage.history().tree.nodes[first].prompt, "Nudge it.", "the prompt the key sent")

    # During a turn: nothing typed, nothing sent; typed text amends the turn.
    second = stage.submit("Nudge it again.", script)
    yield Until(lambda: stage.tools("ok"), "the second turn's first call")
    yield from send_key(stage)
    expect_equal(stage.entries("amend", second), [], "the amendments with nothing typed")
    expect_equal(stage.ctl.turn_id, second, "the running turn")
    stage.props.amend_text = "Make it red"
    yield from send_key(stage)
    yield stage.finished(second)
    delivered = [e for e in stage.ctl.events if e["name"] == "amend_delivered"]
    expect(delivered, "the amendment the key sent was not delivered")
    expect(any("Make it red" in t for t in stage.entries("amend", second)),
           f"the conversation does not show the amendment: {stage.entries('amend', second)}")
    expect_equal(stage.props.amend_text, "", "the amend box after amending")


# the Shift+Alt+C shortcut ----------------------------------------------------------

def shortcut(stage: GuiStage, text: str):
    """Shift+Alt+C over the viewport, the text typed into the field it
    opens, and Enter."""
    yield from stage.press("C", shift=True, alt=True)
    yield 0.3
    yield from stage.type_text(text)
    yield from stage.key("RET")
    yield 0.2


@phase("shortcut")
def shortcut_check(stage: GuiStage):
    from whittle.addon import shortcut as keys

    yield from select_crate(stage)
    area, ui = sidebar(stage)
    area.spaces.active.show_region_ui = False
    script = stage.script("shortcut", [
        {"steps": [say("Nudging."), exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1")],
         "finish": done("Nudged.")},
        {"steps": [say("Working on it."), exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1"),
                   {"wait_amend": 15}, exec_("after", "print('after the amendment')")],
         "finish": done("Amended.")},
        {"steps": [{"ask": "Should the lid overhang or sit flush?", "choices": ["Overhang", "Flush"]},
                   say("Going with that.")], "finish": done("Asked.")}])
    bpy.context.window_manager.whittle_fake_script = str(script)

    # Idle: the field is the prompt, and Enter sends it.
    yield from shortcut(stage, "Nudge it.")
    expect(area.spaces.active.show_region_ui, "the shortcut did not open the sidebar")
    expect_equal(ui.active_panel_category, keys.CATEGORY, "the sidebar's tab")
    yield Until(lambda: stage.ctl is not None and stage.ctl.turn_id is not None, "the shortcut to send")
    first = stage.ctl.turn_id
    yield stage.finished(first)
    expect_equal(stage.history().tree.nodes[first].prompt, "Nudge it.", "the prompt the shortcut sent")
    expect_equal(stage.props.prompt, "", "the prompt box after sending")

    # During a turn: the field is the amendment.
    second = stage.submit("Nudge it again.", script)
    yield Until(lambda: stage.tools("ok"), "the second turn's first call")
    yield from shortcut(stage, "Make it red")
    yield stage.finished(second)
    delivered = [e for e in stage.ctl.events if e["name"] == "amend_delivered"]
    expect(delivered, "the amendment typed into the shortcut's field was not delivered")
    expect(any("Make it red" in t for t in stage.entries("amend", second)),
           f"the conversation does not show the amendment: {stage.entries('amend', second)}")

    # While Claude asks: the field is the answer.
    third = stage.submit("Add a lid.", script)
    yield Until(lambda: stage.ctl.question is not None, "the question")
    yield from shortcut(stage, "Flush")
    yield Until(lambda: stage.ctl.question is None, "the question to be answered")
    yield stage.finished(third)
    results = [e["data"] for e in stage.ctl.events if e["name"] == "tool_result"]
    expect("Flush" in results[-1]["summary"], f"the agent did not get the answer: {results[-1]['summary']!r}")


# Auto targets --------------------------------------------------------------------

def target_names() -> list[str]:
    from whittle.addon import targets

    return [o.name for o in targets.resolve(bpy.context.scene)]


@phase("auto_targets")
def auto_targets(stage: GuiStage):
    yield from select_crate(stage)
    barrel = stage.add_object("Barrel", (1.2, 0.0, 0.3), (0.5, 0.5, 0.6))
    yield from stage.settle()
    expect(stage.props.target_auto, "Auto is off")
    # A click on another object in Object Mode: the target follows.
    yield from stage.click(*stage.to_window((1.2, -0.25, 0.3)))
    yield Until(lambda: target_names() == ["Barrel"], "the target to follow the click")
    # A click on empty space deselects; the active object stays the target.
    yield from stage.click(*stage.to_window((-1.5, 2.5, 0.0)))
    yield from stage.settle()
    expect(not barrel.select_get(), "the click on empty space did not deselect")
    yield 0.3
    expect_equal(target_names(), ["Barrel"], "the target after clicking empty space")
    # Sketching makes the sketch active; the target stays.
    yield from start_sketching(stage)
    yield 0.3
    expect_equal(target_names(), ["Barrel"], "the target while sketching")
    stage.button("whittle.sketch_stop")
    yield from stage.settle()
    # Auto off: a click elsewhere leaves the list alone.
    stage.props.target_auto = False
    yield from stage.click(*stage.to_window((0.0, -0.25, 0.3)))
    yield from stage.settle()
    expect(bpy.data.objects["Crate"].select_get(), "the click did not select the crate")
    yield 0.3
    expect_equal(target_names(), ["Barrel"], "the targets with Auto off")


# branches and undo -------------------------------------------------------------------

@phase("branch_undo")
def branch_undo(stage: GuiStage):
    yield from select_crate(stage)
    script = stage.script("branch", [
        {"steps": [exec_("first", "bpy.data.objects['Crate'].location.x += 0.1")], "finish": done("One.")},
        {"steps": [exec_("second", "bpy.data.objects['Crate'].location.x += 0.1")], "finish": done("Two.")},
        {"steps": [exec_("other", "bpy.data.objects['Crate'].location.y += 0.3")], "finish": done("Other.")}])
    first, second = yield from stage.turns(["Nudge it.", "Nudge it again."], script)
    at_second = (crate_x(), crate_y())
    # Edit & Resend on the second turn, sent as another branch.
    stage.run(operators.branch_node, second)
    yield from stage.settle()
    expect_equal(stage.props.prompt, "Nudge it again.", "the prompt Edit & Resend puts back")
    (other,) = yield from stage.turns(["Move it sideways instead."], script)
    at_other = (crate_x(), crate_y())
    expect_equal(stage.history().tree.nodes[other].parent, first, "the new branch's parent")
    # The switcher's ◂ brings back the first branch's scene...
    stage.run(operators.switch_branch, second)
    yield from stage.settle()
    expect_equal((crate_x(), crate_y()), at_second, "the scene after switching to the first branch")
    expect_equal(stage.history().tree.current, second, "the current node after switching")
    # ... and Ctrl+Z goes back again.
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    expect_equal((crate_x(), crate_y()), at_other, "the scene after Ctrl+Z")
    expect_equal(stage.history().tree.current, other, "the current node after Ctrl+Z")
    shown = [t.node for t in stage.conversation().path_turns]
    expect_equal(shown, [first, other], "the conversation after Ctrl+Z")


# the agent crashing ---------------------------------------------------------------------

@phase("agent_crash")
def agent_crash(stage: GuiStage):
    from whittle.addon import ui

    stage.crate()
    script = stage.script("crash", [{"steps": [
        say("Nudging."), exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1"), {"sleep": 2},
        exec_("more", "print('more')"), say("Done.")], "finish": done("Nudged.")}])
    node = stage.submit("Nudge it.", script)
    yield Until(lambda: stage.tools("ok"), "the agent's first call")
    pid = stage.ctl.process.popen.pid
    stage.ctl.process.popen.kill()
    yield Until(lambda: stage.ctl.process.state == "crashed" and not operators.busy(stage.ctl),
                "the crash to be noticed")
    ctx = ui.Ctx(scene=bpy.context.scene, hist=history.active(), ctl=stage.ctl, comparing=None)
    crashed = ui._crashed_turn(ctx, stage.conversation())
    expect_equal(crashed, node, "the turn the attention box offers to Restart and Retry")
    # Restart and Retry.
    before = set(stage.history().tree.nodes)
    expect_equal(stage.button("whittle.retry", node=crashed), {"FINISHED"}, "Restart and Retry")
    yield Until(lambda: set(stage.history().tree.nodes) - before, "the retried turn")
    (retried,) = set(stage.history().tree.nodes) - before
    yield stage.finished(retried)
    expect(stage.ctl.process.popen.pid != pid, "the agent was not started again")
    found = stage.history()
    expect_equal(found.tree.current, retried, "the current node after the retry")
    expect(not found.tree.nodes[retried].folded, "the retried turn did not complete")


# chats ---------------------------------------------------------------------------------

@phase("chats")
def chats_check(stage: GuiStage):
    stage.crate()
    script = nudge_script(stage, "chats", 3)
    (a_turn,) = yield from stage.turns(["Nudge it."], script)
    a = chats.get().current
    a_session = stage.history().tree.nodes[a_turn].agent_session_id
    stage.save_as(stage.work / "scene.blend")
    expect_equal(stage.button("whittle.chat_new"), {"FINISHED"}, "New Chat")
    yield from stage.settle()
    yield from stage.turns(["Nudge it in another chat."], script)
    b = chats.get().current
    expect(a != b, "New Chat made no chat")
    before = (crate_x(), crate_y())
    # The first chat's title in the menu: its conversation is back, the
    # scene stays as the other chat left it.
    expect_equal(stage.button("whittle.chat_switch", chat=a), {"FINISHED"}, "switching back")
    yield from stage.settle()
    expect_equal([t.node for t in stage.conversation().path_turns], [a_turn], "the conversation after switching")
    expect_equal((crate_x(), crate_y()), before, "the scene after switching")
    node = stage.submit("Once more.", script)
    yield stage.finished(node)
    expect_equal([s.get("resume") for s in stage.ctl.session_starts], [a_session], "the session resumed")
    expect(not any("could not be resumed" in line for line in stage.context_lines(node)),
           "the first chat's conversation was lost")
    yield from stage.press("S", ctrl=True)
    yield from stage.settle()
    expect(not bpy.data.is_dirty, "the title bar shows '*' after Ctrl+S")
    size = (stage.work / "scene.blend").stat().st_size
    # The other chat's 🗑, confirmed with Return.
    stage.button("whittle.chat_delete", chat=b)
    yield 0.3
    yield from stage.press("RET")
    yield Until(lambda: b not in chats.get().index.chats, "the chat to be deleted")
    yield from stage.press("S", ctrl=True)
    yield from stage.settle()
    smaller = (stage.work / "scene.blend").stat().st_size
    expect(smaller < size, f"the file did not shrink after deleting a chat: {size} -> {smaller}")


@phase("file_carries_chats")
def carries_save(stage: GuiStage):
    stage.crate()
    script = nudge_script(stage, "carry", 2)
    (a_turn,) = yield from stage.turns(["Nudge it."], script)
    a = chats.get().current
    stage.run(operators.new_chat)
    (b_turn,) = yield from stage.turns(["Nudge it in another chat."], script)
    found = stage.history()
    stage.remember(a=a, b=chats.get().current, a_turn=a_turn, b_turn=b_turn,
                   b_session=found.tree.nodes[b_turn].agent_session_id, cache=str(chats.root()))
    stage.save_as(stage.work / "scene.blend")
    yield from stage.settle()


@phase("file_carries_chats")
def carries_open(stage: GuiStage):
    import shutil

    cache = Path(stage.recall("cache"))
    expect(cache.is_dir(), "the file's cache is not where it was")
    shutil.rmtree(cache)
    stage.open(stage.work / "scene.blend")
    yield from stage.settle()
    found = chats.get()
    expect_equal(set(found.index.chats), {stage.recall("a"), stage.recall("b")}, "the chats in the menu")
    expect_equal(found.current, stage.recall("b"), "the current chat")
    b_turn = stage.recall("b_turn")
    hist = stage.history()
    expect(b_turn in hist.tree.nodes, "the current chat's turn is missing")
    expect(hist.session.transcript_path(b_turn).is_file(), "the turn's transcript is missing")
    shown = stage.conversation().path_turns
    expect(shown and shown[-1].node == b_turn and shown[-1].picture, "the turn shows no thumbnail or render")
    expect_equal(stage.button("whittle.chat_switch", chat=stage.recall("a")), {"FINISHED"}, "switching")
    yield from stage.settle()
    expect_equal([t.node for t in stage.conversation().path_turns], [stage.recall("a_turn")],
                 "the other chat's conversation")
    expect_equal(stage.button("whittle.chat_switch", chat=stage.recall("b")), {"FINISHED"}, "switching back")
    yield from stage.settle()
    node = stage.submit("Once more.", nudge_script(stage, "carry-after", 1))
    yield stage.finished(node)
    expect_equal([s.get("resume") for s in stage.ctl.session_starts], [stage.recall("b_session")],
                 "the session resumed")
    beside = sorted(p.name for p in stage.work.iterdir() if p.name.startswith("scene"))
    expect(set(beside) <= {"scene.blend", "scene.blend1"}, f"files beside the .blend: {beside}")


# comparing targets -----------------------------------------------------------------------

@phase("compare_targets")
def compare_targets(stage: GuiStage):
    from whittle.addon import compare

    yield from select_crate(stage)
    script = stage.script("compare_targets", [
        {"steps": [exec_("nudge", "bpy.data.objects['Crate'].location.x += 0.1")], "finish": done("Nudged.")},
        {"steps": [exec_("add lid", LID)], "finish": done("Added a lid.")}])
    first, _second = yield from stage.turns(["Nudge it.", "Add a lid."], script)
    expect_equal(sorted(target_names()), ["Crate", "Crate_Lid"], "the targets after the lid")
    stage.run(operators.compare_node, first)
    yield from stage.settle()
    expect("Crate_Lid" not in bpy.data.objects, "the earlier turn shows a lid")
    stage.button("whittle.compare_toggle")
    yield from stage.settle()
    expect("Crate_Lid" in bpy.data.objects, "Swap did not bring the lid back")
    stage.button("whittle.compare_end")
    yield from stage.settle()
    expect(compare.active() is None, "Done did not end the comparison")
    expect_equal(sorted(target_names()), ["Crate", "Crate_Lid"], "the targets after Done")
    yield 0.5
    expect_equal(sorted(target_names()), ["Crate", "Crate_Lid"], "the targets once Auto has looked")
    expect(all(bpy.data.objects[n].select_get() for n in ("Crate", "Crate_Lid")), "the targets are not selected")


# references through the file browser ---------------------------------------------------------

def add_reference(stage: GuiStage, path: Path):
    """📎: the file browser opens, a file is picked and Return adds it."""
    count = len(stage.props.refs)
    stage.button("whittle.ref_add")
    yield Until(lambda: file_browser()[0] is not None, "the reference file browser")
    win, area = file_browser()
    params = area.spaces.active.params
    params.directory = str(path.parent).encode()
    params.filename = path.name
    yield from confirm(stage, win, area)
    yield Until(lambda: len(stage.props.refs) > count, f"{path.name} to be added")
    yield Until(lambda: file_browser()[0] is None, "the file browser to close")


@phase("references_turn")
def references_turn(stage: GuiStage):
    stage.crate()
    front = stage.write_image("front", (0.8, 0.5, 0.2))
    side = stage.write_image("side", (0.3, 0.5, 0.8))
    yield from add_reference(stage, front)
    yield from add_reference(stage, side)
    expect_equal([Path(r.path).name for r in stage.props.refs], ["front.png", "side.png"], "the references")
    expect_equal(stage.button("whittle.ref_pin", index=1), {"FINISHED"}, "pinning")
    yield from stage.turns(["Match the references."], nudge_script(stage, "refs", 1))
    expect_equal([(Path(r.path).name, r.pinned) for r in stage.props.refs], [("side.png", True)],
                 "the references after a turn that succeeded")



# the preferences -------------------------------------------------------------------------------
#
# Whittle runs installed as an extension (tests/gui/run.py), so the Preferences
# window lists it with its own preferences. What a panel or the preferences
# drew is read from a Spy (tests/gui/spy.py) on its draw method, at Blender's
# own redraws. Any API key is a fake one, and Blender runs without online
# access, so nothing can reach the API.

NO_KEY_LINE = "Whittle needs an Anthropic API key to run Claude."
ENVIRONMENT_KEY_LINE = "Using ANTHROPIC_API_KEY from Blender's environment."
TYPED_KEY_LINE = "Usage is billed to the key's Anthropic Console account."
KEY_LINES = (NO_KEY_LINE, ENVIRONMENT_KEY_LINE, TYPED_KEY_LINE)
KEY_BOX_TITLE = "Add an API key to start"
ENVIRONMENT_KEY = "sk-ant-gui-check-environment-not-a-real-key"
TYPED_KEY = "sk-ant-gui-check-typed-not-a-real-key"


def addon_preferences():
    from whittle.addon import prefs

    addon = bpy.context.preferences.addons.get(prefs.PACKAGE)
    expect(addon is not None and addon.preferences is not None,
           f"{prefs.PACKAGE} has no preferences: Whittle is not installed as an extension")
    return addon.preferences


def preferences_window():
    """The Preferences window, once one is open."""
    for win in bpy.context.window_manager.windows:
        if any(a.type == "PREFERENCES" for a in win.screen.areas):
            return win
    return None


def redraw_all() -> None:
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


def drawn(spy, what: str, wanted=None, timeout: float = 10.0):
    """The first draw of the spy's panel from now on that shows what is
    wanted (any, without wanted), redrawing every window until then."""
    count = spy.count

    def check():
        if spy.errors:
            raise AssertionError(f"{what} failed to draw:\n{spy.errors[-1]}")
        if spy.count > count and (wanted is None or wanted(spy.latest)):
            return True
        redraw_all()
        return False

    redraw_all()
    yield Until(check, what, timeout)
    return spy.latest


def shoot(stage: GuiStage, name: str, win) -> None:
    """A screenshot of a window into the work folder, for a person to look at."""
    # The Preferences' screen is a temporary one, which an override cannot
    # name: the window brings its own.
    area = max(win.screen.areas, key=lambda a: a.width * a.height)
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.screen.screenshot(filepath=str(stage.work / f"{name}.png"))


# How far down the Preferences window is scrolled for a screenshot of a box,
# in steps of the mouse wheel: Blender opens it too small to show all of
# Whittle's preferences at once.
SCROLL = {"Claude": 0, "Agent Environment": 6, "Defaults": 60}


def shoot_preferences(stage: GuiStage, name: str, box: str):
    """A screenshot of the Preferences window scrolled to one of Whittle's
    boxes (roughly: Blender's own lines above them vary)."""
    override = preferences_override()
    with bpy.context.temp_override(**override):
        for _ in range(60):
            bpy.ops.view2d.scroll_up()
        for _ in range(SCROLL[box]):
            bpy.ops.view2d.scroll_down()
    override["area"].tag_redraw()
    yield from stage.settle()
    shoot(stage, name, override["window"])


def show_sidebar(stage: GuiStage):
    from whittle.addon import shortcut

    area, ui = sidebar(stage)
    shortcut.show_sidebar(area)
    yield Until(lambda: ui.active_panel_category == shortcut.CATEGORY, "the sidebar's Whittle tab")


def open_preferences(stage: GuiStage, spy):
    """Preferences… as the sidebar's buttons run it: the Preferences window
    opens on the add-ons, with Whittle's preferences. Returns their first
    draw."""
    from whittle.addon import prefs

    expect_equal(stage.button("preferences.addon_show", module=prefs.PACKAGE), {"FINISHED"}, "Preferences…")
    yield Until(lambda: preferences_window() is not None, "the Preferences window")
    expect_equal(bpy.context.preferences.active_section, "ADDONS", "the Preferences' section")
    return (yield from drawn(spy, "Whittle's preferences"))


def preferences_override() -> dict:
    """The Preferences window's main region, where its buttons run."""
    win = preferences_window()
    area = next(a for a in win.screen.areas if a.type == "PREFERENCES")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return {"window": win, "area": area, "region": region}


def in_box(layout, title: str) -> list:
    """The records drawn inside the box whose first label is title, in order."""
    for c in layout.of("box"):
        child = c["child"]
        mine = [r for r in layout.calls if r["layout"] is child]
        if not (mine and mine[0]["kind"] == "label" and mine[0]["text"] == title):
            continue
        start = layout.calls.index(mine[0])
        end = next((i for i in range(start + 1, len(layout.calls)) if layout.calls[i]["depth"] < child.depth),
                   len(layout.calls))
        return layout.calls[start:end]
    raise AssertionError(f"no box titled {title!r} among {layout.labels()}")


def key_line(layout) -> str:
    """The line under the API Key field: where the key comes from."""
    found = [t for t in layout.labels() if t in KEY_LINES]
    expect_equal(len(found), 1, f"the key's source lines among {layout.labels()}")
    return found[0]


# What the Preferences' main region keeps from its width for a line in one
# of Whittle's boxes: the region's margins, the box's border and the icon.
PREFERENCES_LINE_MARGIN = 96


def expect_key_line_whole(layout) -> None:
    """The key's source line has a row of its own (nothing else drawn in its
    layout) and its text fits the Preferences window as Blender opens it,
    so it is never cut off."""
    import blf

    text = key_line(layout)
    (record,) = [r for r in layout.of("label") if r["text"] == text]
    (parent,) = [r for r in layout.calls if r.get("child") is record["layout"]]
    expect(parent["kind"] in ("box", "column"),
           f"the key's source line {text!r} shares a {parent['kind']} with other items")
    region = preferences_override()["region"]
    scale = bpy.context.preferences.system.ui_scale
    blf.size(0, bpy.context.preferences.ui_styles[0].widget.points * scale)
    width = blf.dimensions(0, text)[0]
    room = region.width - PREFERENCES_LINE_MARGIN * scale
    expect(width <= room, f"the key's source line {text!r} is {width:.0f} px, wider than the {room:.0f} px "
                          f"the Preferences window has for it")


@phase("preferences_key")
def preferences_key(stage: GuiStage):
    from tests.gui.spy import Spy
    from whittle.addon import prefs, ui
    from whittle.addon.process import AgentState

    # A fake key could only ever reach the API with online access.
    expect(not bpy.app.online_access, "Blender has online access")
    expect(prefs.ENV_KEY not in os.environ, "the run left ANTHROPIC_API_KEY in Blender's environment")
    p = addon_preferences()
    expect_equal(p.api_key, "", "the API key preference at the start")
    expect_equal(p.bl_rna.properties["api_key"].subtype, "PASSWORD", "the API Key field's kind")
    stage.crate()
    yield from show_sidebar(stage)
    panel = Spy(ui.WHITTLE_PT_main)

    # Send without a key: nothing starts, and the sidebar asks for one.
    bpy.context.window_manager.whittle_fake_script = ""
    stage.props.prompt = "Add a lid."
    try:
        stage.run(operators.submit_sketch)
    except RuntimeError:
        pass
    yield Until(lambda: stage.ctl is not None and stage.ctl.process.state == AgentState.NEEDS_KEY,
                "Send to ask for a key")
    expect_equal(stage.props.prompt, "Add a lid.", "the prompt box after Send without a key")
    side = yield from drawn(panel, "the sidebar's key box", lambda d: KEY_BOX_TITLE in d.labels())
    buttons = [(r["idname"], r.get("text")) for r in in_box(side, KEY_BOX_TITLE) if r["kind"] == "operator"]
    expect_equal(buttons, [("wm.url_open", "Get a Key"), ("preferences.addon_show", "Preferences…")],
                 "the key box's buttons")
    expect_equal([o.url for o in side.operator_props("wm.url_open")], [prefs.KEYS_URL], "where Get a Key goes")
    expect_equal([o.module for o in side.operator_props("preferences.addon_show")], [prefs.PACKAGE],
                 "what Preferences… shows")
    shoot(stage, "sidebar-no-key", stage.window)

    # Preferences…, as the box's button runs it.
    spy = Spy(prefs.WhittlePreferences)
    page = yield from open_preferences(stage, spy)
    # Blender's own lines above the preferences: an installed extension
    # that puts its modules or folders where they do not belong is warned
    # about there.
    import addon_utils

    expect_equal(addon_utils._extensions_warnings_get().get(prefs.PACKAGE, []), [],
                 "the warnings the Preferences show for Whittle")
    claude = in_box(page, "Claude")
    expect_equal([r["prop"] for r in claude if r["kind"] == "prop"], ["api_key", "model", "usage_data"],
                 "the Claude box's fields")
    expect_equal(key_line(page), NO_KEY_LINE, "the key's source line with no key")
    expect_key_line_whole(page)
    links = [(r.get("text"), r["props"].url) for r in claude if r["kind"] == "operator"]
    expect_equal(links, [("Get an API Key", prefs.KEYS_URL)], "the Claude box's link")
    yield from shoot_preferences(stage, "preferences-no-key", "Claude")

    # A key in Blender's environment: the sidebar's box goes.
    os.environ[prefs.ENV_KEY] = ENVIRONMENT_KEY
    page = yield from drawn(spy, "the environment's key line", lambda d: key_line(d) == ENVIRONMENT_KEY_LINE)
    expect_key_line_whole(page)
    expect_equal(prefs.api_key(), (ENVIRONMENT_KEY, "environment"), "the key from the environment")
    yield from drawn(panel, "the sidebar without its key box", lambda d: KEY_BOX_TITLE not in d.labels())
    yield from shoot_preferences(stage, "preferences-environment-key", "Claude")

    # A key typed in the field wins over the environment's, and clears the ask.
    p.api_key = TYPED_KEY
    expect_equal(prefs.api_key(), (TYPED_KEY, "preferences"), "the key with both set")
    expect_equal(stage.ctl.process.state, AgentState.STOPPED, "the agent's state once a key is typed")
    page = yield from drawn(spy, "the typed key's line", lambda d: key_line(d) == TYPED_KEY_LINE)
    expect_key_line_whole(page)
    yield from shoot_preferences(stage, "preferences-typed-key", "Claude")
    del os.environ[prefs.ENV_KEY]
    yield from drawn(spy, "the typed key's line alone", lambda d: key_line(d) == TYPED_KEY_LINE)
    side = yield from drawn(panel, "the sidebar with a typed key")
    expect(KEY_BOX_TITLE not in side.labels(), "the key box stayed once a key was typed")

    # Cleared again: the line says so, and no agent ever ran.
    p.api_key = ""
    yield from drawn(spy, "the no-key line again", lambda d: key_line(d) == NO_KEY_LINE)
    expect(stage.ctl.process.popen is None, "an agent was started with a fake key")


def environment_status_lines(layout) -> list:
    """The Agent Environment box's status: the labels after its folder, in
    the column they share."""
    box = in_box(layout, "Agent Environment")
    index = next(i for i, r in enumerate(box) if r["kind"] == "prop" and r["prop"] == "venv_dir")
    first = next(r for r in box[index + 1:] if r["kind"] == "label")
    return [r for r in box if r["kind"] == "label" and r["layout"] is first["layout"]]


def environment_status(layout) -> tuple[str, str]:
    """The Agent Environment box's status as one line, and its icon. Lines
    wrapped after a path separator join without a space."""
    lines = environment_status_lines(layout)
    text = lines[0]["text"]
    for r in lines[1:]:
        text += r["text"] if text.endswith(("/", "\\")) else " " + r["text"]
    return text, lines[0]["icon"]


def expect_environment_status_whole(layout) -> None:
    """The status has rows of its own (a column holding only its lines, the
    icon on the first) and every line fits the Preferences window as Blender
    opens it, so none is cut off."""
    import blf

    lines = environment_status_lines(layout)
    (parent,) = [r for r in layout.calls if r.get("child") is lines[0]["layout"]]
    expect_equal(parent["kind"], "column", "what holds the environment's status")
    others = [r for r in layout.calls if r["layout"] is lines[0]["layout"] and r not in lines]
    expect_equal(others, [], "what else the environment's status column holds")
    expect_equal([r["icon"] for r in lines[1:]], ["BLANK1"] * (len(lines) - 1),
                 "the icons of the status's continuation lines")
    region = preferences_override()["region"]
    scale = bpy.context.preferences.system.ui_scale
    blf.size(0, bpy.context.preferences.ui_styles[0].widget.points * scale)
    room = region.width - PREFERENCES_LINE_MARGIN * scale
    for r in lines:
        width = blf.dimensions(0, r["text"])[0]
        expect(width <= room, f"the environment's status line {r['text']!r} is {width:.0f} px, wider than "
                              f"the {room:.0f} px the Preferences window has for it")


def environment_buttons(layout) -> list:
    return [(r["idname"], r.get("text"), getattr(r["props"], "reinstall", False))
            for r in in_box(layout, "Agent Environment") if r["kind"] == "operator"]


SET_UP_BUTTONS = [("whittle.venv_install", None, False), ("whittle.venv_install", "Reinstall", True)]


@phase("preferences_environment")
def preferences_environment(stage: GuiStage):
    from tests.gui.spy import Spy
    from whittle import venv
    from whittle.addon import prefs, setup

    expect(not bpy.app.online_access, "Blender has online access")
    p = addon_preferences()
    spy = Spy(prefs.WhittlePreferences)
    yield from open_preferences(stage, spy)
    agent = os.environ["WHITTLE_AGENT_PYTHON"]
    uses = f" (the agent uses {agent})"
    lock = setup.lock_path()
    sdk = venv.read_pins(lock)[venv.SDK]
    folders = stage.work / "venvs"
    other_lock = stage.work / "other.lock"
    other_lock.write_text(f"{venv.SDK}==0.0.1 --hash=sha256:{'0' * 64}\n")

    def made_by_whittle(name: str, marker_lock: Path, complete: bool = True) -> Path:
        """A folder as a setup leaves it, its python linking to the agent's."""
        folder = folders / name
        (folder / "bin").mkdir(parents=True)
        (folder / "bin" / "python").symlink_to(agent)
        venv.write_marker(folder, marker_lock, sdk=sdk, base_python=Path(agent), complete=complete)
        return folder

    foreign = folders / "foreign"
    foreign.mkdir(parents=True)
    (foreign / "notes.txt").write_text("not a venv\n")
    states = [
        ("missing", folders / "missing", ("Not set up yet" + uses, "ERROR")),
        ("foreign", foreign, ("The folder holds something Whittle did not make" + uses, "ERROR")),
        ("unfinished", made_by_whittle("unfinished", lock, complete=False),
         ("Incomplete or its Python is gone: reinstall" + uses, "ERROR")),
        ("other-lock", made_by_whittle("other-lock", other_lock),
         ("Set up for an earlier version of Whittle: reinstall" + uses, "ERROR")),
        # Ready: the agent override is no longer worth a mention.
        ("ready", made_by_whittle("ready", lock), (f"Ready: {venv.SDK} {sdk}", "CHECKMARK")),
    ]
    for name, folder, wanted in states:
        p.venv_dir = str(folder)
        page = yield from drawn(spy, f"the {name} environment's status",
                                lambda d, w=wanted: environment_status(d) == w)
        expect_environment_status_whole(page)
        expect_equal(environment_buttons(page), SET_UP_BUTTONS, f"the {name} environment's buttons")
        yield from shoot_preferences(stage, f"environment-{name}", "Agent Environment")

    # A developer override deep in a long path: the status wraps to the
    # window, breaking the path after a folder, and every line fits.
    deep = stage.work.joinpath("a-developer-checkout-of-whittle-with-a-long-name",
                               *(["nested-folder-for-the-agent-environment"] * 4), "python")
    deep.parent.mkdir(parents=True)
    deep.symlink_to(agent)
    os.environ["WHITTLE_AGENT_PYTHON"] = str(deep)
    try:
        p.venv_dir = str(folders / "missing")
        wanted = (f"Not set up yet (the agent uses {deep})", "ERROR")
        page = yield from drawn(spy, "the status with a long agent path",
                                lambda d: environment_status(d) == wanted)
        lines = environment_status_lines(page)
        expect(len(lines) > 1, f"the status with a long agent path was not wrapped: {lines[0]['text']!r}")
        expect_environment_status_whole(page)
        yield from shoot_preferences(stage, "environment-long-path", "Agent Environment")
    finally:
        os.environ["WHITTLE_AGENT_PYTHON"] = agent

    # A dry run, as Set Up runs with dry_run: the commands are logged under
    # the box; nothing is made and nothing downloaded.
    target = folders / "dry-run"
    p.venv_dir = str(target)
    with bpy.context.temp_override(**preferences_override()):
        result = bpy.ops.whittle.venv_install("INVOKE_DEFAULT", dry_run=True)
    expect_equal(result, {"FINISHED"}, "the dry run")
    dry = setup.current()
    expect(dry.dry_run and dry.state == "done", f"the dry run ended {dry.state}")
    page = yield from drawn(spy, "the dry run's log", lambda d: "dry run: nothing was run" in d.labels())
    expect(any(t.startswith("$ ") for t in page.labels()), f"the dry run's log has no command: {page.labels()}")
    expect_equal(environment_status(page), ("Not set up yet" + uses, "ERROR"), "the status after a dry run")
    expect("--require-hashes" in dry.log_path.read_text(), "the dry run's install is not hash-checked")
    expect(not target.exists(), "the dry run made the environment folder")
    yield from shoot_preferences(stage, "environment-dry-run", "Agent Environment")

    # A setup running: a stand-in whose one step is a sleep, never pip.
    target = folders / "stand-in"
    p.venv_dir = str(target)
    stand_in = venv.VenvSetup([venv.Step("create", [agent, "-c", "import time; time.sleep(60)"], 90.0)],
                              venv=target, lock=lock, log_path=stage.work / "stand-in.log",
                              base_python=Path(agent), on_finish=setup._finished)
    setup._current = stand_in
    stand_in.start()
    setup._start_timer()
    sleeper = stand_in._proc
    page = yield from drawn(spy, "the running setup",
                            lambda d: environment_status(d) == ("Setting up: create…", "SORTTIME"))
    expect_equal(environment_buttons(page), [("whittle.venv_cancel", None, False)], "the running setup's buttons")
    yield from shoot_preferences(stage, "environment-running", "Agent Environment")
    with bpy.context.temp_override(**preferences_override()):
        result = bpy.ops.whittle.venv_cancel()
    expect_equal(result, {"FINISHED"}, "Cancel Setup")
    yield Until(lambda: sleeper.poll() is not None, "the stand-in's step to stop")
    page = yield from drawn(spy, "the cancelled setup",
                            lambda d: environment_status(d) == ("Setup cancelled: cancelled during create", "CANCEL"))
    expect_equal(environment_buttons(page), SET_UP_BUTTONS, "the cancelled setup's buttons")
    expect_equal(venv.status(target, lock), venv.VenvStatus.BROKEN, "the cancelled setup's folder")
    yield from shoot_preferences(stage, "environment-cancelled", "Agent Environment")


def agent_popover(stage: GuiStage, spy):
    """The header's agent popover, opened over the sidebar and closed again.
    Returns what it drew."""
    count = spy.count
    area, ui = sidebar(stage)
    with bpy.context.temp_override(window=stage.window, screen=stage.window.screen, area=area, region=ui):
        bpy.ops.wm.call_panel(name="WHITTLE_PT_agent", keep_open=False)
    yield Until(lambda: spy.count > count, "the agent popover to draw")
    if spy.errors:
        raise AssertionError(f"the agent popover failed to draw:\n{spy.errors[-1]}")
    layout = spy.latest
    yield from stage.key("ESC")
    yield 0.2
    return layout


def file_setting(layout, key: str) -> tuple[str, bool]:
    """For This File's line for a setting: its label, and whether its reset
    button is enabled."""
    from whittle.addon import prefs, ui

    label = prefs.LABELS[key]
    if key in ui.OWN_LINE_SETTINGS:
        texts = [t for t in layout.labels() if t.startswith(label)]
    else:
        texts = [r.get("text") for r in layout.of("prop") if r["prop"] == key]
    expect_equal(len(texts), 1, f"For This File's {label} lines")
    resets = [r for r in layout.operators("whittle.file_setting_reset") if r["props"].key == key]
    expect_equal(len(resets), 1, f"{label}'s reset buttons")
    return texts[0], layout.is_enabled(resets[0])


def agent_environ(stage: GuiStage) -> dict:
    """The environment the running agent's process was started with."""
    raw = Path(f"/proc/{stage.ctl.process.popen.pid}/environ").read_bytes()
    return dict(item.split("=", 1) for item in raw.decode(errors="replace").split("\0") if "=" in item)


def defaults_turn(stage: GuiStage, prompt: str):
    """A turn; returns its session's start and the agent's process id. The
    request the turn sent carries the session's budget and style too."""
    script = stage.script("defaults", [{"steps": [say("Looked.")], "finish": done("Looked.")}] * 8)
    node = stage.submit(prompt, script)
    yield stage.finished(node)
    started = stage.ctl.session_starts[-1]
    request = json.loads((stage.ctl.session.request_dir(node) / "request.json").read_text())
    expect_equal(budget_and_style(request), budget_and_style(started), "the budget and style the request carries")
    return started, stage.ctl.process.popen.pid


def budget_and_style(sent: dict) -> tuple:
    """The triangle budget, palette, bevel style and style notes sent."""
    return tuple(sent["settings"][key] for key in ("poly_budget", "palette", "bevel_style", "style_notes"))


@phase("preferences_defaults")
def preferences_defaults(stage: GuiStage):
    from tests.gui.spy import Spy
    from whittle.addon import models, prefs, ui
    from whittle.addon.process import NONESSENTIAL

    p = addon_preferences()
    stage.crate()
    yield from show_sidebar(stage)
    spy = Spy(prefs.WhittlePreferences)
    page = yield from open_preferences(stage, spy)
    expect_equal([r.get("text") for r in in_box(page, "Claude") if r["kind"] == "prop" and r["prop"] == "model"],
                 ["Model for New Chats"], "the model field's label")
    expect_equal([r["prop"] for r in in_box(page, "Defaults") if r["kind"] == "prop"],
                 ["poly_budget", "self_check_rounds", "render_size", "palette", "bevel_style", "style_notes"],
                 "the Defaults box's fields")
    expect_equal([r["prop"] for r in in_box(page, "Files") if r["kind"] == "prop"], ["store_chats"],
                 "the Files box's fields")
    expect(not p.usage_data, "Send Claude Code usage data is on by default")
    yield from shoot_preferences(stage, "preferences-defaults", "Defaults")
    popover = Spy(ui.WHITTLE_PT_agent)

    # The first turn runs with the preferences as they are.
    started, pid = yield from defaults_turn(stage, "Look at it.")
    first_chat, first_model = chats.get().current, started["model"]
    expect_equal(first_model, p.model, "the first chat's model")
    expect_equal(budget_and_style(started), (p.poly_budget, p.palette, p.bevel_style, p.style_notes),
                 "the first session's budget and style")
    expect_equal(agent_environ(stage).get(NONESSENTIAL), "1", f"{NONESSENTIAL} with usage data off")
    layout = yield from agent_popover(stage, popover)
    expect_equal(file_setting(layout, "poly_budget"), ("Triangle Budget (default)", False), "For This File's budget")
    for key in ("palette", "bevel_style", "style_notes"):
        expect_equal(file_setting(layout, key), (f"{prefs.LABELS[key]} (default)", False), f"For This File's {key}")

    # New defaults: the file shows them, and the next turn restarts the agent with them.
    p.poly_budget, p.palette, p.bevel_style, p.style_notes = 1500, "oak, iron", "chunky", "worn wood"
    layout = yield from agent_popover(stage, popover)
    expect_equal(file_setting(layout, "poly_budget"), ("Triangle Budget (default)", False),
                 "For This File's budget after the preference changed")
    expect_equal((stage.props.poly_budget, stage.props.palette, stage.props.bevel_style, stage.props.style_notes),
                 (1500, "oak, iron", "chunky", "worn wood"),
                 "what For This File's fields show")
    started, pid2 = yield from defaults_turn(stage, "Look again.")
    expect(pid2 != pid, "the agent was not restarted for the new defaults")
    expect_equal(budget_and_style(started), (1500, "oak, iron", "chunky", "worn wood"),
                 "the session's budget and style")

    # Usage data on: the restarted agent's CLI may send it.
    p.usage_data = True
    _started, pid3 = yield from defaults_turn(stage, "And again.")
    expect(pid3 != pid2, "the agent was not restarted when usage data was turned on")
    expect(NONESSENTIAL not in agent_environ(stage), f"{NONESSENTIAL} with usage data on")

    # Model for New Chats: the next new chat starts on it; the first keeps its own.
    offered = prefs._model_search(None, None, "")
    expect(first_model in offered, f"the model field does not offer {first_model}: {offered}")
    other = next((m for m in offered if m != first_model), None)
    expect(other is not None, f"the model field offers nothing else: {offered}")
    p.model = other
    stage.run(operators.new_chat)
    second_chat = chats.get().current
    started, _pid = yield from defaults_turn(stage, "Look from the new chat.")
    expect_equal(started["model"], other, "the new chat's model")
    expect_equal(chats.get().model(second_chat), other, "the model the new chat keeps")
    stage.run(operators.switch_chat, first_chat)
    expect_equal(models.chat_model(), first_model, "the first chat's model after the default changed")

    # This file's own budget wins over the preference.
    stage.props.poly_budget = 800
    layout = yield from agent_popover(stage, popover)
    expect_equal(file_setting(layout, "poly_budget"), ("Triangle Budget", True), "For This File's own budget")
    expect_equal(file_setting(layout, "style_notes"), ("Style Notes (default)", False),
                 "For This File's notes beside the file's own budget")
    started, pid5 = yield from defaults_turn(stage, "Look with the file's budget.")
    expect(pid5 != pid3, "the agent was not restarted for the file's budget")
    expect_equal(budget_and_style(started), (800, "oak, iron", "chunky", "worn wood"),
                 "the session's budget and style")
    stage.save_as(stage.work / "scene.blend")
    yield from stage.settle()


@phase("preferences_defaults")
def preferences_defaults_reopen(stage: GuiStage):
    from tests.gui.spy import Spy
    from whittle.addon import prefs, props, ui

    # A fresh Blender: the preferences are the run's again, since checks never save them.
    p = addon_preferences()
    expect_equal((p.poly_budget, p.style_notes, p.model, p.usage_data),
                 (prefs.DEFAULTS["poly_budget"], "", prefs.DEFAULTS["model"], False),
                 "the preferences in a fresh Blender")
    yield from show_sidebar(stage)
    popover = Spy(ui.WHITTLE_PT_agent)
    expect_equal(props.file_settings(bpy.context.scene), {"poly_budget": 800}, "the reopened file's settings")
    layout = yield from agent_popover(stage, popover)
    expect_equal(file_setting(layout, "poly_budget"), ("Triangle Budget", True), "the reopened file's budget")
    expect_equal(stage.props.poly_budget, 800, "the budget the reopened file shows")

    # Another file shows the preference.
    stage.open(stage.work / "base.blend")
    yield from stage.settle()
    yield from show_sidebar(stage)
    layout = yield from agent_popover(stage, popover)
    expect_equal(file_setting(layout, "poly_budget"), ("Triangle Budget (default)", False), "another file's budget")
    expect_equal(stage.props.poly_budget, p.poly_budget, "the budget another file shows")

    # The reset button gives the file the preference back.
    stage.open(stage.work / "scene.blend")
    yield from stage.settle()
    yield from show_sidebar(stage)
    expect_equal(stage.button("whittle.file_setting_reset", key="poly_budget"), {"FINISHED"}, "the reset button")
    layout = yield from agent_popover(stage, popover)
    expect_equal(file_setting(layout, "poly_budget"), ("Triangle Budget (default)", False),
                 "the budget after its reset")
    expect_equal(props.file_settings(bpy.context.scene), {}, "the file's settings after the reset")
