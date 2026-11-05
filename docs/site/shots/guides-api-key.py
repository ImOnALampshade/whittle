# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for the API key and cost guide. Every key here is fake."""

from tests.docshots.spec import LID, Shot, done, exec_, preferences, render, say, sidebar


# Keeps the Claude box's key rows: where the Preferences show them on opening.
KEY_ROWS = (170, 245, 665, 145)
# An example, for the picture: a fake turn costs what its finish step says.
COST = 0.124


def key_typed(stage):
    """A key in the preference: the field shows dots."""
    stage.preferences.api_key = "sk-ant-api-not-a-real-key"
    yield 0.2


def key_inherited(stage):
    """The preference empty, a key in Blender's environment."""
    import os

    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-api-not-a-real-key"
    yield 0.2


class OpenGroup:
    """A layout whose panel starts open. Blender has no Python API for a
    layout panel's state, and a simulated click on one does not land."""

    def __init__(self, layout):
        self.layout = layout

    def panel(self, idname, default_closed=False):
        return self.layout.panel(idname + "_open", default_closed=False)


def turn_cost(stage):
    from whittle.addon import ui

    draw = ui.draw_tool_group
    ui.draw_tool_group = lambda layout, *args, **kwargs: draw(OpenGroup(layout), *args, **kwargs)
    stage.crate()
    script = stage.script("cost", [{"steps": [say("Adding a lid."), exec_("add lid", LID),
                                              render((1.5, -1.5, 1.2))],
                                    "finish": {**done("Added a lid."), "cost": COST}}])
    yield from stage.turns(["Add a lid to the crate."], script)
    yield 0.5


SHOTS = [
    Shot("key-needed", "No key: Send started nothing and the sidebar asks for one.", scenario="key_needed"),
    Shot("prefs-typed", "The Claude box with a key in the preference.", preferences(crop=KEY_ROWS), setup=key_typed),
    Shot("prefs-environment", "The Claude box using the environment's key.", preferences(crop=KEY_ROWS), setup=key_inherited),
    Shot("turn-cost", "A finished turn with its tool group open, the cost at its end.", sidebar(), setup=turn_cost),
]
