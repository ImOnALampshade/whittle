# SPDX-License-Identifier: GPL-3.0-or-later
"""The screenshots of the Privacy and safety guide."""

from tests.docshots.spec import Shot, preferences, sidebar


class FirstCallOpen:
    """A layout whose tool groups start open, as they are once clicked, with
    only the first call open: the render call's result names this machine's
    folders."""

    def __init__(self, layout):
        self.layout = layout

    def __getattr__(self, name):
        return getattr(self.layout, name)

    def panel(self, idname, default_closed=False):
        closed = idname.startswith("whittle_call_") and not idname.endswith("_0_0")
        header, body = self.layout.panel(idname, default_closed=closed)
        return header, FirstCallOpen(body) if body is not None else None


def tool_code(stage):
    """A finished turn with its first call open. Blender has no Python API
    for a layout panel's state and simulated clicks do not reach it, so the
    panels start open, in this Blender only, before they first draw."""
    from whittle.addon import ui

    draw = ui.draw_tool_group
    ui.draw_tool_group = lambda layout, *args, **kwargs: draw(FirstCallOpen(layout), *args, **kwargs)
    stage.crate()
    yield from stage.turns(["Add a lid to the crate."], stage.fake("stream.json"))
    yield 0.3


SHOTS = [
    Shot("usage-data", "The Claude box of the Preferences, usage data off.", preferences(crop=(170, 272, 665, 205))),
    Shot("save-chats", "The Files box of the Preferences, with Save Chats in the .blend on.",
         preferences(full=True, crop=(8, 696, 664, 68))),
    Shot("tool-code", "A finished turn with a tool call open on the code Claude ran.", sidebar(), setup=tool_code),
    Shot("continue-chat", "A chat made on another machine, asking to be continued.", sidebar(),
         scenario="continue_chat"),
    Shot("guide-gate", "A file naming a guide this computer has not approved, asking first.", sidebar(), scenario="guide_gate"),
]
