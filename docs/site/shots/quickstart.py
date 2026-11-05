# SPDX-License-Identifier: GPL-3.0-or-later
"""The Quickstart's shots: the Preferences a first install goes through, then
one short session on Blender's default cube, from the first look at the
sidebar to the turn undone."""

from tests.docshots.spec import Shot, Snap, Until, done, exec_, preferences, render, say, sidebar, window

PROMPT = "Bevel the edges of the cube."
BEVEL = """cube = bpy.data.objects['Cube']
bevel = cube.modifiers.new('Bevel', 'BEVEL')
bevel.width = 0.25
bevel.segments = 4
print(whittle.mesh_report(cube))"""


def first_turn(stage):
    """The default cube, as a new file opens: a prompt, a turn, Ctrl+Z."""
    stage.orbit((1.0, -1.2, 0.8), 9.0, (0.0, 0.0, 0.0))
    yield 0.3
    yield Snap("first-look")
    stage.props.prompt = PROMPT
    yield 0.2
    yield Snap("prompt")
    script = stage.script("bevel", [{"steps": [
        say("Adding a bevel to the cube's edges."),
        exec_("bevel the edges", BEVEL),
        render((5.0, -6.0, 4.0), look_at=(0.0, 0.0, 0.0)),
        say("The cube's edges are bevelled, with four segments so they read as rounded."),
    ], "finish": done("Bevelled the cube.")}])
    stage.props.prompt = ""
    yield from stage.turns([PROMPT], script)
    yield 0.3
    yield Snap("finished")
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    yield 0.3
    yield Snap("undone")


# The arrow to the right of Repositories and the menu's Install from Disk, from
# the Preferences window's top left.
ARROW = (821, 17)
ITEM = (716, 135)


def extension_menu(stage):
    """Get Extensions, with the menu open as a click on its arrow opens it."""
    import bpy

    from tests.gui import checks

    area = stage.override()["area"]
    region = next(r for r in area.regions if r.type == "UI")
    with bpy.context.temp_override(window=stage.window, screen=stage.window.screen, area=area, region=region):
        bpy.ops.screen.userpref_show("INVOKE_DEFAULT", section="EXTENSIONS")
    yield Until(lambda: checks.preferences_window() is not None, "the Preferences window")
    bpy.context.preferences.active_section = "EXTENSIONS"
    checks.redraw_all()
    yield 1.0
    # Whittle is already installed here; the crop leaves the Installed list out.
    win = checks.preferences_window()
    x, y = ARROW[0], win.height - ARROW[1]
    win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    yield 0.3
    win.event_simulate(type="LEFTMOUSE", value="PRESS", x=x, y=y)
    win.event_simulate(type="LEFTMOUSE", value="RELEASE", x=x, y=y)
    yield 0.5
    win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=ITEM[0], y=win.height - ITEM[1])
    yield 0.5


# The viewport's middle and the sidebar: the cube and the reply at a size
# that reads on the page.
CLOSE = (380, 80, 930, 550)

SHOTS = [
    Shot("install-menu", "The arrow right of Repositories, its menu open on Install from Disk.",
         window(of="PREFERENCES", crop=(160, 0, 680, 180)), setup=extension_menu),
    Shot("online-access", "Allow Online Access in the System section.",
         preferences("SYSTEM", crop=(0, 0, 840, 412))),
    Shot("environment", "The Agent Environment box before setup.",
         preferences(full=True, crop=(0, 480, 680, 118))),
    Shot("api-key", "The API key field, empty.", preferences(full=True, crop=(0, 275, 680, 118))),
    Shot("first-look", "The default cube selected and the Whittle tab open.", window(crop=CLOSE), setup=first_turn),
    Shot("prompt", "A prompt typed, ready to send.", sidebar(), setup=first_turn),
    Shot("finished", "The first turn finished: the bevelled cube and the reply.", window(crop=CLOSE),
         setup=first_turn),
    Shot("undone", "Ctrl+Z pressed: the cube is square again.", window(crop=CLOSE), setup=first_turn),
]
