# SPDX-License-Identifier: GPL-3.0-or-later
"""The Sketching guide's screenshots."""

from tests.docshots.spec import (LID, Shot, Snap, Until, done, exec_, preferences, render, say, sidebar, viewport)

# One stroke of each type on the bare crate (it spans x and y +-0.25, z 0 to 0.5).
FRONT = -0.256
KINDS = [
    # A shape to follow, up the front.
    ("free", False, [(-0.2 + 0.012 * k, FRONT, 0.06 + 0.024 * k + 0.02 * (-1) ** (k // 3)) for k in range(14)]),
    # An arched handle to build out to, over the top.
    ("add", False, [(-0.16 + 0.32 * k / 16, 0.0, 0.5 + 0.2 * (1.0 - ((k - 8) / 8) ** 2)) for k in range(17)]),
    # A slot to carve from the front.
    ("carve", True, [(0.04, FRONT, 0.3), (0.2, FRONT, 0.3), (0.2, FRONT, 0.38), (0.04, FRONT, 0.38)]),
    # The top's front edge to sharpen.
    ("crease", False, [(-0.25 + 0.5 * k / 10, FRONT, 0.502) for k in range(11)]),
    # The side panel the prompt is about.
    ("region", True, [(-0.252, -0.2, 0.08), (-0.252, 0.2, 0.08), (-0.252, 0.2, 0.42), (-0.252, -0.2, 0.42)]),
    # A note: an arrow at the slot.
    ("note", False, [(0.42, -0.5, 0.06), (0.34, -0.4, 0.14), (0.24, -0.32, 0.22), (0.14, -0.26, 0.29)]),
    ("note", False, [(0.13, -0.27, 0.22), (0.14, -0.26, 0.29), (0.2, -0.28, 0.27)]),
]


def every_kind(stage):
    """The crate from one view with a stroke of every type."""
    from tests.blender.sketch_helpers import add_stroke
    from whittle.addon import sketch

    stage.crate()
    space = stage.override()["area"].spaces.active
    space.overlay.show_cursor = False
    space.overlay.show_outline_selected = False
    obj = sketch.ensure_sketch_layers(stage.scene)
    stage.run(sketch.start_session)
    yield Until(lambda: sketch.current_session() is not None, "sketch mode")
    space.show_region_asset_shelf = False
    stage.orbit((-2.0, -4.0, 2.2), 1.5, (0.0, 0.0, 0.3))
    yield 0.3
    sketch.current_session().capture()
    for stroke_type, cyclic, points in KINDS:
        add_stroke(obj, stroke_type, points, radius=0.006, cyclic=cyclic, view=1)
    sketch.ensure_region_fills(obj)
    sketch.set_active_type(obj, "free")
    yield 0.5


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
    obj = sketch.ensure_sketch_layers(stage.scene)
    bundle = formats.read_bundle(CRATE_BUNDLE)
    for view_id in sorted(bundle.views):
        views.add_view(obj.data, lambda _i, view=bundle.views[view_id]: view)
    for stroke in bundle.strokes:
        add_stroke(obj, stroke.type, stroke.points, radius=stroke.radius, opacity=stroke.opacity,
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
    obj = sketch.ensure_sketch_layers(stage.scene)
    bundle = formats.read_bundle(CRATE_BUNDLE)
    for view_id in sorted(bundle.views):
        views.add_view(obj.data, lambda _i, view=bundle.views[view_id]: view)
    for stroke in bundle.strokes:
        add_stroke(obj, stroke.type, stroke.points, radius=stroke.radius, opacity=stroke.opacity,
                   cyclic=stroke.cyclic, view=stroke.view)
    sketch.set_active_type(obj, "add")
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
    add_stroke(obj, "add", [(-0.1, -0.27, 0.56), (0.0, -0.27, 0.62), (0.1, -0.27, 0.56)], radius=0.006, view=2)
    yield 0.5
    yield Snap("during-turn")
    yield stage.finished(node)
    yield 0.5
    yield Snap("after-turn")


SHOTS = [
    Shot("sketch-strip", "Sketch mode: stroke types, the stroke count and the view list.", scenario="sketching"),
    Shot("stroke-types", "The crate with a stroke of every type.", viewport(crop=(250, 190, 600, 460)), setup=every_kind),
    Shot("view-markers", "A marker where each view was captured.", viewport(crop=(280, 300, 430, 300)), setup=markers),
    Shot("during-turn", "Strokes sent, a new one drawn, Amend offered.", sidebar(), setup=send_and_amend, deadline=120),
    Shot("after-turn", "The finished sketch turn.", sidebar(), setup=send_and_amend),
    Shot("keymap", "The add-on's keys in the Keymap preferences.", preferences("KEYMAP", search="Whittle")),
]
