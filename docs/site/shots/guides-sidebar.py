# SPDX-License-Identifier: GPL-3.0-or-later
"""The shots of guides/sidebar: every part of the sidebar and its states,
from the scenarios wherever one shows the thing."""

import json

from tests.docshots.spec import LID, Shot, Until, exec_, popup, say, sidebar, window

# An example, for the picture: a fake turn costs what its finish step says.
TURN_COST = 0.0612


def in_the_window(stage):
    """A finished turn, with the view on the crate, so the sidebar reads
    beside what it talks about."""
    stage.crate()
    yield from stage.turns(["Add a lid to the crate."], stage.fake("stream.json"))
    stage.orbit((3.0, -4.0, 2.5), 2.2)
    yield 0.3


class OpenPanels:
    """A layout whose sub-panels start open, as they are once clicked: all
    but the render call, whose result names this machine's folders."""

    def __init__(self, layout):
        self.layout = layout

    def __getattr__(self, name):
        return getattr(self.layout, name)

    def panel(self, idname, default_closed=False):
        closed = idname.startswith("whittle_call_") and not idname.endswith("_0_0")
        header, body = self.layout.panel(idname, default_closed=closed)
        return header, OpenPanels(body) if body is not None else None


def tools_open(stage):
    """A finished turn with its tool groups open. Blender has no Python API
    for a layout panel's state and simulated clicks did not reach it, so the
    groups are made to start open, in this Blender only, before they first
    draw."""
    from whittle.addon import ui

    draw = ui.draw_tool_group
    ui.draw_tool_group = lambda layout, *args, **kwargs: draw(OpenPanels(layout), *args, **kwargs)
    turns = json.loads(stage.fake("stream.json").read_text())["turns"]
    turns[0]["finish"]["cost"] = TURN_COST
    stage.crate()
    yield from stage.turns(["Add a lid to the crate."], stage.script("tools_open", turns))
    yield 0.3


def answer_typed(stage):
    """A turn paused on a question, with an answer of the user's own typed."""
    stage.crate()
    script = stage.script("answer_typed", [{"steps": [
        say("Adding the lid first."),
        exec_("add lid", LID),
        {"ask": "Should the lid overhang the crate by 1 cm, or sit flush with its sides?",
         "choices": ["Overhang", "Flush"]},
        say("Going with that."),
    ]}])
    stage.submit("Add a lid to the crate.", script)
    yield Until(lambda: stage.ctl.question is not None, "the question")
    stage.props.ask_answer = "Overhang it by 2 cm."
    yield 0.3


SHOTS = [
    Shot("in-the-window", "The sidebar open beside the crate after one turn.", window(), setup=in_the_window),
    Shot("overview", "Three finished turns: the sidebar's parts from top to bottom.", scenario="conversation"),
    Shot("empty", "Nothing selected and nothing sent: the start row.", scenario="empty"),
    Shot("primitive-menu", "The Primitive menu of the start row.", popup(menu="WHITTLE_MT_start_primitive"),
         scenario="empty"),
    Shot("agent-popover", "The agent popover from the header's gear.", scenario="agent_popover"),
    Shot("setup-needed", "The attention box after Send found no agent environment.", scenario="setup_needed"),
    Shot("key-needed", "The attention box with no API key.", scenario="key_needed"),
    Shot("crashed", "The attention box after a crash.", scenario="crashed"),
    Shot("manual-targets", "Auto off: the targets picked by hand.", scenario="manual_targets"),
    Shot("comparing", "The comparison bar.", scenario="comparing"),
    Shot("tools-open", "A finished turn with its tool groups opened.", sidebar(), setup=tools_open),
    Shot("turn-menu", "The ⋮ menu of an earlier turn.", scenario="turn_menu"),
    Shot("long-session", "Thirteen turns folded down to a bounded height.", scenario="long_session"),
    Shot("later-turns", "Off the end of a branch: Return to Latest and Branch.", scenario="branch_edit"),
    Shot("branched", "The branch switcher in a message with siblings.", scenario="branched"),
    Shot("running", "A turn at work: the phase in the conversation, Stop in the composer.", scenario="streaming"),
    Shot("stop-menu", "The Stop menu.", popup(menu="WHITTLE_MT_stop"), scenario="streaming"),
    Shot("asking", "Claude asks a question with choices.", scenario="asking"),
    Shot("answer-typed", "An answer of the user's own typed, with the Answer button.", sidebar(), setup=answer_typed),
    Shot("interrupted", "A stopped turn with its changes kept.", scenario="interrupted"),
    Shot("failed", "A recovered tool error, then a failed turn with Retry.", scenario="error_turn"),
    Shot("sketching", "Sketch mode: the stroke types and the view list.", scenario="sketching"),
    Shot("references", "Reference chips over the prompt, one pinned.", scenario="references"),
    Shot("continue-chat", "A chat from another machine waits for Continue.", scenario="continue_chat"),
    Shot("open-elsewhere", "The line saying the file is open in another Blender.", scenario="open_elsewhere"),
]
