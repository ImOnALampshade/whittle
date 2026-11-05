# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for Agent tools and skills: one sketched turn that calls every
tool the fake agent can reach, and the four renders the agent saw in it."""

from tests.docshots.spec import LID, Shot, Snap, done, exec_, region, say, sidebar

MODES = ("overlay", "shaded", "wireframe", "matcap")
SIZE = 480
GAP = 8
# The sheet, centred at 1:1 in the image editor, from the window's top left.
SHEET = (305, 102, 968, 728)
# The sidebar down to the end of the tool group, which is all the figure is
# about.
TOOL_ROWS = (0, 0, 280, 738)


def view_render(mode: str) -> dict:
    return {"call": "render", "params": {"view": "first", "mode": mode, "size": SIZE}, "expect": "ok"}


TURN = {"steps": [
    say("Adding a lid, then checking it against the sketch."),
    {"call": "inspect", "params": {"query": "summary"}, "expect": "ok"},
    {"call": "inspect", "params": {"query": "object", "name": "Crate"}, "expect": "ok"},
    {"call": "checkpoint", "params": {"label": "before the lid"}, "expect": "ok"},
    exec_("add lid", LID, expect="ok"),
    {"call": "restore_checkpoint", "params": {"checkpoint_id": "c1"}, "expect": "ok"},
    exec_("add lid again", LID, expect="ok"),
    *[view_render(mode) for mode in MODES],
    say("The lid sits where you drew it."),
], "finish": done("Added a lid.")}


class OpenGroups:
    """A layout whose tool groups start open and whose calls stay closed.
    Blender has no Python API for a layout panel's state, so the groups are
    made to start open, in this Blender only, before they first draw."""

    def __init__(self, layout):
        self.layout = layout

    def __getattr__(self, name):
        return getattr(self.layout, name)

    def panel(self, idname, default_closed=False):
        header, body = self.layout.panel(idname, default_closed=idname.startswith("whittle_call_"))
        return header, OpenGroups(body) if body is not None else None


def tile_renders(paths: dict):
    """The turn's four renders as one image's pixels, two by two in MODES
    order, read and kept as data so they are the pixels the agent got."""
    import bpy
    import numpy as np

    tiles = []
    for mode in MODES:
        image = bpy.data.images.load(paths[mode])
        image.colorspace_settings.name = "Non-Color"
        width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        bpy.data.images.remove(image)
        tiles.append(pixels.reshape(height, width, 4))
    sheet = np.full((height * 2 + GAP, width * 2 + GAP, 4), 0.19, dtype=np.float32)
    sheet[..., 3] = 1.0
    for index, tile in enumerate(tiles):
        x = (index % 2) * (width + GAP)
        y = (1 - index // 2) * (height + GAP)
        sheet[y:y + height, x:x + width] = tile
    return sheet


def one_turn(stage):
    """The crate with the fixture's strokes on two views, sent as a turn; the
    sidebar; then most of the 3D viewport's area turned into an image editor
    showing the renders."""
    import bpy

    from tests.blender.sketch_helpers import add_stroke
    from tests.screens.scenarios import CRATE_BUNDLE
    from whittle import formats
    from whittle.addon import sketch, ui, views

    draw = ui.draw_tool_group
    ui.draw_tool_group = lambda layout, *args, **kwargs: draw(OpenGroups(layout), *args, **kwargs)
    # The fake reports an overlay's strokes-only image too; the real agent
    # names it in the caption and does not report it.
    render_row = ui._render_row
    ui._render_row = lambda layout, path: None if path.endswith("-strokes.png") else render_row(layout, path)
    stage.crate()
    obj = sketch.ensure_sketch_layers(stage.scene)
    bundle = formats.read_bundle(CRATE_BUNDLE)
    for view_id in sorted(bundle.views):
        views.add_view(obj.data, lambda _i, view=bundle.views[view_id]: view)
    for stroke in bundle.strokes:
        add_stroke(obj, stroke.type, stroke.points, radius=stroke.radius, opacity=stroke.opacity,
                   cyclic=stroke.cyclic, view=stroke.view)
    yield from stage.turns(["Add a lid to the crate."], stage.script("tools", [TURN]))
    yield 0.3
    yield Snap("tool-rows")

    paths = {}
    for entry in stage.tools("ok"):
        for path in entry.images:
            for mode in MODES:
                if path.endswith(f"-{mode}.png"):
                    paths[mode] = path
    pixels = tile_renders(paths)
    image = bpy.data.images.new("Agent renders", pixels.shape[1], pixels.shape[0], alpha=False, is_data=True)
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    # The harness keeps looking for a 3D viewport, so a sliver of it stays.
    override = stage.override()
    with bpy.context.temp_override(**override):
        bpy.ops.screen.area_split(direction="VERTICAL", factor=0.2)
    yield 0.5
    override = stage.override()
    area = override["area"]
    area.type = "IMAGE_EDITOR"
    space = area.spaces.active
    space.image = image
    space.show_region_header = space.show_region_toolbar = space.show_region_ui = space.show_gizmo = False
    yield 0.5
    main = next(r for r in area.regions if r.type == "WINDOW")
    with bpy.context.temp_override(window=override["window"], screen=override["screen"], area=area, region=main):
        bpy.ops.image.view_zoom_ratio(ratio=1.0)
        bpy.ops.image.view_all()
        bpy.ops.image.view_zoom_ratio(ratio=1.0)
    yield 0.5


SHOTS = [
    Shot("tool-rows", "One group of tool calls open: a row for each call, a thumbnail under each render.",
         sidebar(crop=TOOL_ROWS), setup=one_turn),
    Shot("render-modes", "The four render modes from one sketch view.", region(box=SHEET), setup=one_turn),
]
