# SPDX-License-Identifier: GPL-3.0-or-later
"""The Undo page's shots: real Ctrl+Z and Ctrl+Shift+Z, between turns and during one."""

from tests.docshots.spec import (LID, ROPE_HANDLES, Popup, Shot, Snap, Until, done, exec_, popup, say, sidebar)


def after_turns(stage):
    """Two finished turns, one Ctrl+Z, then redo and Blender's own list of steps."""
    stage.crate()
    script = stage.script("two-turns", [
        {"steps": [say("Adding a lid."), exec_("add lid", LID)], "finish": done("Added a lid.")},
        {"steps": [say("Adding rope handles."), exec_("add rope handles", ROPE_HANDLES)],
         "finish": done("Added rope handles on both sides.")}])
    yield from stage.turns(["Add a lid to the crate.", "Add rope handles on both sides."], script)
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    yield 0.5
    yield Snap("after-undo")
    yield from stage.press("Z", ctrl=True, shift=True)
    yield from stage.settle()
    yield 0.5
    yield Snap("undo-history", popup=Popup("operator", "wm.call_menu", {"name": "TOPBAR_MT_undo_history"}))


def during_turn(stage):
    """Ctrl+Z pressed with the turn still running, its second call in flight."""
    stage.crate()
    script = stage.script("mid-turn", [{"steps": [
        say("Adding the lid, then rope handles."),
        exec_("add lid", LID),
        say("Now the handles."),
        exec_("add rope handles", ROPE_HANDLES, delay=90)]}])
    stage.submit("Add a lid and rope handles.", script)
    yield Until(lambda: stage.tools("ok") and stage.tools("pending"), "the second call in flight")
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    yield 0.5
    yield Snap("during-turn")


SHOTS = [
    Shot("after-undo", "Ctrl+Z after the second turn: the first is current and the second waits as a later turn.",
         sidebar(), setup=after_turns),
    Shot("undo-history", "Edit > Undo History after two turns.", popup(), setup=after_turns),
    Shot("during-turn", "Ctrl+Z during a turn: the warning in the conversation.", sidebar(), setup=during_turn),
]
