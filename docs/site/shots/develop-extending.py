# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for Extending Whittle: where each recipe's change shows up."""

from tests.docshots.spec import Shot, preferences, sidebar


class OpenPanels:
    """A layout whose sub-panels start open, as they are once clicked."""

    def __init__(self, layout):
        self.layout = layout

    def __getattr__(self, name):
        return getattr(self.layout, name)

    def panel(self, idname, default_closed=False):
        header, body = self.layout.panel(idname, default_closed=False)
        return header, OpenPanels(body) if body is not None else None


def tool_open(stage):
    """A finished turn with its call opened. Blender has no Python API for a
    layout panel's state, so the tool groups start open in this Blender,
    before they first draw."""
    from whittle.addon import ui

    draw = ui.draw_tool_group
    ui.draw_tool_group = lambda layout, *args, **kwargs: draw(OpenPanels(layout), *args, **kwargs)
    stage.crate()
    yield from stage.turns(["What is in the scene?"], stage.fake("inspect_call.json"))
    yield 0.3


def development_panel(stage):
    """The Development panel after a fake turn, its Fake Script field showing
    a path from the repository instead of this machine's."""
    import bpy

    bpy.context.preferences.view.show_developer_ui = True
    stage.crate()
    yield from stage.turns(["What is in the scene?"], stage.fake("inspect_call.json"))
    bpy.context.window_manager.whittle_fake_script = "tests/fixtures/fake/stream.json"
    yield 0.2


SHOTS = [
    Shot("fake-call", "A fake script's inspect call, opened in the sidebar.", sidebar(), setup=tool_open),
    Shot("development-panel", "Developer Extras on: the Development panel's Fake Script field.", sidebar(),
         setup=development_panel, open_panels=True),
    Shot("asking", "A sidebar state: a turn paused on a question.", scenario="asking"),
    Shot("sketching", "A sidebar state: Sketch pressed, Capture View beside it.",
         scenario="sketching"),
    Shot("preferences-defaults", "The Defaults box of Whittle's preferences.",
         preferences(scroll=6, crop=(176, 364, 652, 94))),
    Shot("agent-popover", "The agent popover's For This File.", scenario="agent_popover"),
]
