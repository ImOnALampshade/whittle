# SPDX-License-Identifier: GPL-3.0-or-later
"""The shots of guides/history: existing scenarios, each showing one state,
and two states of this page's own."""

from tests.docshots.spec import (DARKEN, LID, METAL_BANDS, METAL_HANDLES, ROPE_HANDLES, Shot, done, exec_, popup, say,
                                 viewport)

TALLER = "bpy.data.objects['Crate'].scale.z *= 1.6"


def ghost(stage):
    """The crate made taller, with the turn before it as a ghost."""
    from whittle.addon import operators

    stage.crate()
    script = stage.script("taller", [{"steps": [say("Making the crate taller."), exec_("taller", TALLER)],
                                      "finish": done("Made the crate taller.")}])
    yield from stage.turns(["Make the crate taller."], script)
    stage.run(operators.toggle_ghost)
    stage.orbit((3.0, -4.0, 2.0), 2.6, (0.0, 0.0, 0.4))
    yield 0.5


def tree(stage):
    """A small tree of real prompts: the handles tried two ways, the second take
    current, so its row is the last."""
    from whittle.addon import operators

    stage.crate()
    script = stage.script("tree", [
        {"steps": [exec_("add lid", LID)], "finish": done("Added a lid.")},
        {"steps": [exec_("darken the wood", DARKEN)], "finish": done("Darkened the wood.")},
        {"steps": [exec_("add rope handles", ROPE_HANDLES)], "finish": done("Added rope handles.")},
        {"steps": [exec_("add metal bands", METAL_BANDS)], "finish": done("Added metal bands.")},
        {"steps": [exec_("add metal handles", METAL_HANDLES)], "finish": done("Added metal handles.")},
    ])
    nodes = yield from stage.turns(["Add a lid.", "Make the wood darker.", "Add rope handles on both sides.",
                                    "Add metal bands around the crate."], script)
    stage.run(operators.branch_node, nodes[2])
    yield from stage.turns(["Add metal handles on both sides."], script)


SHOTS = [
    Shot("turn-menu", "The menu of an earlier turn.", scenario="turn_menu"),
    Shot("history-popover", "The history popover over a small tree with two branches.",
         popup(panel="WHITTLE_PT_history"), setup=tree),
    Shot("branch-edit", "After Edit & Resend: back before the turn, its prompt in the box.", scenario="branch_edit"),
    Shot("branched", "Two takes on a turn, the second current.", scenario="branched"),
    Shot("comparing", "Comparing the scene with an earlier turn.", scenario="comparing"),
    Shot("ghost", "The previous turn as a wireframe over the crate.", viewport(crop=(250, 270, 480, 350)), setup=ghost),
    Shot("interrupted", "A turn stopped with its changes kept.", scenario="interrupted"),
    Shot("failed-turn", "A failed turn with Retry beside its reason.", scenario="error_turn"),
    Shot("folded-failure", "A failed turn that changed nothing.", scenario="folded_failure"),
    Shot("crashed", "The agent stopped during a turn.", scenario="crashed"),
]
