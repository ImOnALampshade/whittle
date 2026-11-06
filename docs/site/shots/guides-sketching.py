# SPDX-License-Identifier: GPL-3.0-or-later
"""The Sketching guide's screenshots."""

from tests.docshots.spec import (LID, Shot, Snap, Until, done, exec_, preferences, render, say, sidebar, viewport)

def markers(stage):
    """The sketching scenario's two views from outside, close enough to read."""
    from tests.blender.sketch_helpers import add_stroke
    from tests.screens.scenarios import CRATE_BUNDLE
    from whittle import formats
    from whittle.addon import sketch, views

    stage.crate()
    space = stage.override()["area"].spaces.active
    space.overlay.show_cursor = False
    space.overlay.show_outline_selected = False
    obj = sketch.ensure_sketch_layer(stage.scene)
    bundle = formats.read_bundle(CRATE_BUNDLE)
    for view_id in sorted(bundle.views):
        views.add_view(obj.data, lambda _i, view=bundle.views[view_id]: view)
    for stroke in bundle.strokes:
        add_stroke(obj, stroke.points, radius=stroke.radius, opacity=stroke.opacity,
                   cyclic=stroke.cyclic, view=stroke.view)
    stage.run(sketch.start_session)
    yield Until(lambda: sketch.current_session() is not None, "sketch mode")
    space.show_region_asset_shelf = False
    stage.orbit((-2.0, -6.0, 4.0), 4.5, (0.6, -0.5, 0.3))
    yield 0.5


def send_and_amend(stage):
    """The sketching scenario's strokes sent; a stroke drawn during the turn;
    the finished turn."""
    import bpy

    from tests.blender.sketch_helpers import add_stroke
    from tests.screens.scenarios import CRATE_BUNDLE
    from whittle import formats
    from whittle.addon import sketch, views

    stage.crate()
    obj = sketch.ensure_sketch_layer(stage.scene)
    bundle = formats.read_bundle(CRATE_BUNDLE)
    for view_id in sorted(bundle.views):
        views.add_view(obj.data, lambda _i, view=bundle.views[view_id]: view)
    for stroke in bundle.strokes:
        add_stroke(obj, stroke.points, radius=stroke.radius, opacity=stroke.opacity,
                   cyclic=stroke.cyclic, view=stroke.view)
    bpy.context.window_manager.whittle_show_views = True
    stage.run(sketch.start_session)
    yield Until(lambda: sketch.current_session() is not None, "sketch mode")
    script = stage.script("sketch-turn", [{"steps": [
        say("Adding a lid that overhangs the crate, and carving the slot in the front."),
        exec_("add lid", LID),
        exec_("carve slot", "print('carving')", delay=12),
        render((1.5, -1.5, 1.2)),
        say("The lid overhangs a little and the slot is cut."),
    ], "finish": done("Added a lid and carved the slot.")}])
    node = stage.submit(bundle.request.prompt, script)
    yield Until(lambda: len(stage.tools("ok")) >= 1 and len(stage.tools("pending")) >= 1, "the slow call in flight")
    add_stroke(obj, [(-0.1, -0.27, 0.56), (0.0, -0.27, 0.62), (0.1, -0.27, 0.56)], radius=0.006, view=2)
    yield 0.5
    yield Snap("during-turn")
    yield stage.finished(node)
    yield 0.5
    yield Snap("after-turn")


SHOTS = [
    Shot("sketch-strip", "Sketch mode: the stroke count and the view list.", scenario="sketching"),
    Shot("view-markers", "A marker where each view was captured.", viewport(crop=(280, 300, 430, 300)), setup=markers),
    Shot("during-turn", "Strokes sent, a new one drawn, Amend offered.", sidebar(), setup=send_and_amend, deadline=120),
    Shot("after-turn", "The finished sketch turn.", sidebar(), setup=send_and_amend),
    Shot("keymap", "The add-on's keys in the Keymap preferences.", preferences("KEYMAP", search="Whittle")),
]
