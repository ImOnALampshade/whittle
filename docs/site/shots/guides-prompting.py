# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for the Prompts and targets guide."""

from tests.docshots.spec import LID, Shot, Snap, Until, done, exec_, popup, render, say, sidebar

# What a self-check looks like from the sidebar: the edit, the numbers, the pictures.
MESH_CHECK = "print(whittle.mesh_report(bpy.data.objects['Crate_Lid']))"


def steering(stage):
    """A turn held on a long step, to steer and to stop."""
    from whittle.addon import operators

    stage.crate()
    script = stage.script("steering", [{"steps": [
        say("Adding the lid, then a handle slot on each side."),
        exec_("add lid", LID),
        say("The lid sits right. Now the handle slots."),
        exec_("carve handle slots", "print('carving')", delay=90),
    ]}])
    stage.submit("Add a lid and carve a handle slot on each side.", script)
    yield Until(lambda: stage.tools("pending"), "a call in flight")
    yield 0.3
    yield Snap("running", "stop-menu")
    stage.props.amend_text = "Make the slots a bit wider."
    yield 0.3
    yield Snap("amend-typed")
    stage.run(operators.amend)
    yield 0.5
    yield Snap("amended")


def self_check(stage):
    """A finished turn: the edit, the mesh check and two renders, folded into one group."""
    stage.crate()
    script = stage.script("self_check", [{"steps": [
        exec_("add lid", LID),
        exec_("check the lid", MESH_CHECK),
        render((1.5, -1.5, 1.2)),
        render((-1.5, -1.5, 1.0)),
        say("Added a lid that overhangs the crate by a centimetre. It is a separate object, "
            "so it can still be lifted off."),
    ], "finish": done("Added a lid.")}])
    yield from stage.turns(["Add a lid to the crate."], script)


SHOTS = [
    Shot("prompt-typed", "The crate targeted and a prompt typed, ready to send.", scenario="prompt_typed"),
    Shot("nothing-selected", "Nothing selected: the target line says Claude adds new objects.", scenario="empty"),
    Shot("manual-targets", "Auto off: two objects picked by hand, a third selected.", scenario="manual_targets"),
    Shot("target-options", "The popover beside the manual targets.", popup(panel="WHITTLE_PT_targets"),
         scenario="manual_targets"),
    Shot("ask-claude", "The Shift+Alt+C popup under the pointer, a draft selected in its field.", scenario="shortcut_popup"),
    Shot("running", "A running turn with a tool call in flight.", sidebar(), setup=steering),
    Shot("stop-menu", "The Stop menu during a turn.", popup(menu="WHITTLE_MT_stop"), setup=steering),
    Shot("amend-typed", "An amendment typed during a turn, with the Amend button.", sidebar(), setup=steering),
    Shot("amended", "The amendment in the conversation.", sidebar(), setup=steering),
    Shot("asking", "A turn paused on a question from Claude, with choices.", scenario="asking"),
    Shot("interrupted", "A turn stopped with its changes kept.", scenario="interrupted"),
    Shot("markdown", "A reply in Markdown.", scenario="markdown"),
    Shot("self-check", "A finished turn: its folded tool calls, the reply and the last render.", sidebar(), setup=self_check),
]
