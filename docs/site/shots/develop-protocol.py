# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for Protocol and file formats. One run makes both shots and
every example on the page: a sketched turn, a second turn, a branch and a save."""

from tests.docshots.spec import DARKEN, LID, Popup, Shot, Snap, done, exec_, popup, region, render, say

LIGHTEN = "bpy.data.materials['Wood'].diffuse_color = (0.62, 0.45, 0.28, 1)"
PROMPT = "Add a lid that overhangs the crate slightly."
TURNS = [
    {"steps": [say("I'll add a lid that overhangs the crate by a couple of centimetres."),
               exec_("add lid", LID),
               {"call": "render", "params": {"view": "first", "mode": "overlay", "size": 256}, "expect": "ok"},
               render((1.5, -1.5, 1.2)),
               say("The lid sits where you drew it.")],
     "finish": done("Added a lid.")},
    {"steps": [say("Darkening the wood."), exec_("darken", DARKEN)], "finish": done("Darkened the wood.")},
    {"steps": [say("Lightening the wood."), exec_("lighten", LIGHTEN)], "finish": done("Lightened the wood.")},
]


def sketched_turn(stage):
    """The crate with the fixture's strokes on two views, sent
    as a turn; a second turn, a branch from the first, and a save, so the
    cache holds a tree, a fork and a packed copy."""
    import bpy

    from tests.blender.sketch_helpers import add_stroke
    from tests.screens.scenarios import CRATE_BUNDLE
    from whittle import formats
    from whittle.addon import operators, sketch, views

    stage.crate()
    obj = sketch.ensure_sketch_layer(stage.scene)
    bundle = formats.read_bundle(CRATE_BUNDLE)
    for view_id in sorted(bundle.views):
        views.add_view(obj.data, lambda _i, view=bundle.views[view_id]: view)
    for stroke in bundle.strokes:
        add_stroke(obj, stroke.points, radius=stroke.radius, opacity=stroke.opacity,
                   cyclic=stroke.cyclic, view=stroke.view)
    script = stage.script("protocol", TURNS)
    first, second = yield from stage.turns([PROMPT, "Make the wood darker."], script)
    # Another take on the second turn: a fork of the first turn's session.
    stage.run(operators.branch_node, second)
    yield from stage.turns(["Make the wood lighter."], script)
    bpy.ops.wm.save_as_mainfile(filepath=str(stage.work / "crate.blend"))
    yield 0.5
    yield Snap("history", popup=Popup("panel", "WHITTLE_PT_history"))
    # The request's own overlay, in an editor split off the viewport.
    screen = stage.window.screen
    known = {area.as_pointer() for area in screen.areas}
    with bpy.context.temp_override(**stage.override()):
        bpy.ops.screen.area_split(direction="VERTICAL", factor=0.5)
    area = next(area for area in screen.areas if area.as_pointer() not in known)
    area.ui_type = "IMAGE_EDITOR"
    area.spaces.active.image = bpy.data.images.load(
        str(stage.ctl.session.request_dir(first) / "views" / "1" / "overlay.png"))
    yield 0.3
    region = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=stage.window, screen=screen, area=area, region=region):
        bpy.ops.image.view_all(fit_view=True)
    yield 0.5


SHOTS = [
    Shot("history", "The branched history the page's session.json holds.", popup(), setup=sketched_turn),
    Shot("overlay", "A request's overlay.png: the crate from view 1 with its strokes.",
         region(box=(8, 239, 642, 481)), setup=sketched_turn),
]
