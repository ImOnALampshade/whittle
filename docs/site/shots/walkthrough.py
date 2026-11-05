# SPDX-License-Identifier: GPL-3.0-or-later
"""The walkthrough: one crate from a plain box to the finished chest, on one
continuing scene. The story runs twice, the same both times: once in the tall
window for the sidebar and its popups, so a long sidebar needs no stitching,
and once in the wide one for what shows the viewport. The replies are the fake
agent's, written here; the edits they describe are real, so each render and
viewport shot shows what the reply says."""

import math

from tests.docshots.spec import (BEVEL_AND_LID, METAL_HANDLES, ROPE_HANDLES, Popup, Shot, Snap, Until, done,
                                 exec_, popup, say, sidebar, viewport, window)

WIDE = 1.5
# The two views the sketch is drawn from, as (direction, distance).
FRONT = ((-1.2, -4.0, 2.4), 1.3)
SIDE = ((-6.0, -1.0, 1.8), 1.3)
FINAL = ((-2.4, -4.0, 2.2), 1.35)
# The viewport around the crate, without its corners' gizmos.
AROUND = (70, 110, 700, 600)
# The window without its status bar, which says what the last simulated drag was.
NO_STATUS = (0, 0, 1600, 978)
# The viewport and the sidebar, without the editors around them.
WORK = (58, 78, 1235, 828)
# The crate and the top of the sidebar, where the comparison bar is.
COMPARING = (300, 78, 990, 620)
# Parts of the sidebar, as (x, y, width, height); in Draw Mode it runs on, empty,
# to the window's end. Each follows from the turns above it.
SKETCH_START = (0, 300, 420, 68)
SKETCH_STRIP = (0, 300, 420, 300)
QUESTION = (0, 300, 420, 330)
SKETCHED_TURN = (0, 300, 420, 400)
LATER_TURN = (0, 540, 420, 315)
LAST_TURN = (0, 465, 420, 390)
UNDONE = (0, 470, 420, 410)

PROMPT_LID = "Bevel the edges and add a lid that overhangs a little."
PROMPT_SKETCH = "Add a latch here, carve a finger slot in the lid, sharpen its front edge and paint the side panel."
PROMPT_ROPE = "Add rope handles on both sides."
PROMPT_METAL = "Add metal handles on both sides."
PROMPT_TOO_DARK = "Make the wood much darker."
PROMPT_DARKER = "Make the wood a little darker."

LATCH = """brass = bpy.data.materials.new('Brass')
brass.diffuse_color = (0.8, 0.58, 0.18, 1)
brass.metallic = 1.0
bm = bmesh.new()
for size, centre in (((0.11, 0.012, 0.09), (0, -0.256, 0.425)),
                     ((0.05, 0.012, 0.13), (0, -0.287, 0.49)),
                     ((0.02, 0.03, 0.02), (0, -0.3, 0.44))):
    verts = bmesh.ops.create_cube(bm, size=1.0)['verts']
    bmesh.ops.scale(bm, vec=size, verts=verts)
    bmesh.ops.translate(bm, vec=centre, verts=verts)
mesh = bpy.data.meshes.new('Latch')
bm.to_mesh(mesh)
bm.free()
mesh.materials.append(brass)
bpy.context.scene.collection.objects.link(bpy.data.objects.new('Latch', mesh))"""

# The lid's scale goes into its mesh first, so sizes here are real ones.
LID_EDITS = """lid = bpy.data.objects['Crate_Lid']
lid.data.transform(Matrix.Diagonal((0.56, 0.56, 0.05, 1.0)))
lid.scale = (1, 1, 1)
bm = bmesh.new()
bm.from_mesh(lid.data)
bm.edges.ensure_lookup_table()
front = next(e for e in bm.edges if all(v.co.y < -0.27 and v.co.z > 0.02 for v in e.verts))
bmesh.ops.bevel(bm, geom=[front, *front.verts], offset=0.022, segments=1, profile=0.5, affect='EDGES')
for co, no in (((-0.13, 0, 0), (1, 0, 0)), ((0.13, 0, 0), (1, 0, 0)),
               ((0, -0.035, 0), (0, 1, 0)), ((0, 0.035, 0), (0, 1, 0))):
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=co, plane_no=no)
bm.normal_update()
top = [f for f in bm.faces if f.normal.z > 0.9]
cell = min(top, key=lambda f: f.calc_center_median().xy.length)
slot = bmesh.ops.extrude_discrete_faces(bm, faces=[cell])['faces'][0]
bmesh.ops.translate(bm, verts=slot.verts, vec=(0, 0, -0.03))
bm.normal_update()
bm.to_mesh(lid.data)
bm.free()
lid.modifiers['Bevel'].width = 0.004
print(whittle.mesh_report(lid))"""

SIDE_PANEL = """crate = bpy.data.objects['Crate']
paint = bpy.data.materials.new('Panel')
paint.diffuse_color = (0.13, 0.3, 0.36, 1)
crate.data.materials.append(paint)
bm = bmesh.new()
bm.from_mesh(crate.data)
for co, no in (((0, -0.2, 0), (0, 1, 0)), ((0, 0.2, 0), (0, 1, 0)),
               ((0, 0, -0.21), (0, 0, 1)), ((0, 0, -0.07), (0, 0, 1))):
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=co, plane_no=no)
bm.normal_update()
side = [f for f in bm.faces if f.normal.x < -0.9]
min(side, key=lambda f: (f.calc_center_median() - Vector((-0.25, 0, -0.14))).length).material_index = 1
bm.to_mesh(crate.data)
bm.free()"""

TOO_DARK = "bpy.data.materials['Wood'].diffuse_color = (0.05, 0.03, 0.02, 1)"
DARKER = "bpy.data.materials['Wood'].diffuse_color = (0.24, 0.14, 0.06, 1)"


def look(location, look_at=(0.0, 0.0, 0.3)) -> dict:
    """A render as the agent asks for one."""
    return {"call": "render", "params": {"camera": {"location": list(location), "look_at": list(look_at)},
                                         "mode": "matcap", "size": 192}}


TURNS = [
    {"steps": [say("I'll bevel the crate's edges, then add a lid that overhangs by 3 cm."),
               exec_("bevel and lid", BEVEL_AND_LID, delay=8),
               look((-0.9, -1.2, 0.85)),
               say("Done: the crate has soft edges and a lid.")],
     "finish": done("Bevelled the edges and added a lid.")},
    {"steps": [say("Looking at the crate where you sketched."),
               look((-0.45, -1.3, 1.0)),
               {"ask": "Should the latch be brass or dark iron?", "choices": ["Brass", "Dark iron"]},
               say("Brass it is. The latch first, then the lid and the side panel."),
               exec_("brass latch", LATCH),
               exec_("finger slot and front edge", LID_EDITS),
               exec_("side panel", SIDE_PANEL),
               look((-0.9, -1.2, 0.85)),
               say("The latch is on, the lid has a finger slot and a chamfered front edge, "
                   "and the side panel is painted.")],
     "finish": done("Added the latch, slot, chamfer and panel.")},
    {"steps": [say("Adding a rope handle on each side."),
               exec_("rope handles", ROPE_HANDLES), look((-1.1, -1.0, 0.8)),
               say("Both sides have a rope handle.")],
     "finish": done("Added rope handles.")},
    {"steps": [say("Adding a metal bar handle on each side."),
               exec_("metal handles", METAL_HANDLES), look((-1.1, -1.0, 0.8)),
               say("Both sides have a metal handle.")],
     "finish": done("Added metal handles.")},
    {"steps": [say("Darkening the wood."),
               exec_("darken", TOO_DARK), look((-0.9, -1.2, 0.85)),
               say("The wood is much darker now.")],
     "finish": done("Darkened the wood.")},
    {"steps": [say("Darkening the wood a little, so the lid and the rope stand out."),
               exec_("darken", DARKER), look((-0.9, -1.2, 0.85)),
               say("The wood is a shade darker; the lid, latch and rope read clearly against it.")],
     "finish": done("Darkened the wood a little.")},
]


def hand_drawn(points, closed: bool = False, step: float = 0.012, wobble: float = 0.0016) -> list:
    """A polyline as a hand draws it: many points, not quite straight."""
    if closed:
        points = [*points, points[0]]
    drawn = []
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        count = max(2, round(length / step))
        for k in range(count):
            t = k / count
            n = len(drawn)
            drawn.append(tuple(a[i] + (b[i] - a[i]) * t + wobble * math.sin(n * 0.7 + i * 2.1) for i in range(3)))
    if not closed:
        drawn.append(tuple(points[-1]))
    return drawn


# Each is (type, closed, points), in world space, a little off the surfaces.
FRONT_STROKES = [
    # The latch, on the front below the lid.
    ("add", True, [(-0.06, -0.262, 0.47), (0.06, -0.262, 0.47), (0.06, -0.262, 0.38), (-0.06, -0.262, 0.38)]),
    # A finger slot in the lid.
    ("carve", True, [(-0.13, -0.035, 0.552), (0.13, -0.035, 0.552), (0.13, 0.035, 0.552), (-0.13, 0.035, 0.552)]),
    # The lid's front edge.
    ("crease", False, [(-0.28, -0.282, 0.552), (0.28, -0.282, 0.552)]),
    # A note pointing at the latch: the shaft, then the head.
    ("note", False, [(-0.42, -0.36, 0.66), (-0.28, -0.32, 0.54), (-0.08, -0.275, 0.44)]),
    ("note", False, [(-0.15, -0.3, 0.41), (-0.08, -0.275, 0.44), (-0.12, -0.3, 0.5)]),
]
SIDE_STROKES = [
    # The side panel to paint.
    ("region", True, [(-0.262, -0.2, 0.04), (-0.262, 0.2, 0.04), (-0.262, 0.2, 0.18), (-0.262, -0.2, 0.18)]),
]


def draw(stage, strokes, view: int) -> None:
    from tests.blender.sketch_helpers import add_stroke
    from whittle.addon import sketch

    obj = sketch.find_sketch_object()
    for stroke_type, closed, points in strokes:
        sketch.set_active_type(obj, stroke_type)
        add_stroke(obj, stroke_type, hand_drawn(points, closed), radius=0.006, cyclic=closed, view=view)
    sketch.ensure_region_fills(obj)


def to_top(stage) -> None:
    """The sidebar scrolled to its top, for a shot of the whole window."""
    import bpy

    override = stage.override()
    override["region"] = next(r for r in override["area"].regions if r.type == "UI")
    with bpy.context.temp_override(**override):
        bpy.ops.view2d.scroll_up(deltay=100000)


def story(stage, wanted: set):
    """The whole story; each run shoots the shots in wanted, and ends after the last."""
    import bpy

    from whittle.addon import compare, operators, sketch

    def snap(*names, popup=None):
        return Snap(*[n for n in names if n in wanted], popup=popup)

    # A plain crate, selected.
    stage.crate()
    script = stage.script("walkthrough", TURNS)
    space = stage.override()["area"].spaces.active
    space.shading.type = "SOLID"
    space.shading.light = "MATCAP"
    space.shading.studio_light = "basic_side.exr"
    space.shading.color_type = "MATERIAL"
    space.overlay.show_cursor = False
    space.overlay.show_object_origins = False
    stage.orbit(*FINAL)
    yield 0.3
    yield snap("plain-crate")
    space.overlay.show_outline_selected = False

    # A change by prompt.
    stage.props.prompt = PROMPT_LID
    yield 0.2
    yield snap("first-prompt")
    first = stage.submit(PROMPT_LID, script)
    yield Until(lambda: stage.tools("pending"), "the first call in flight")
    yield snap("first-running")
    yield stage.finished(first)
    yield 0.3
    yield snap("first-done", "first-done-view")

    # The next change, sketched from two views.
    stage.run(sketch.start_session)
    yield Until(lambda: sketch.current_session() is not None, "sketch mode")
    space.show_region_asset_shelf = False
    yield 0.3
    yield snap("sketch-start")
    stage.orbit(*FRONT)
    yield 0.3
    sketch.current_session().capture()
    draw(stage, FRONT_STROKES, 1)
    yield 0.3
    yield snap("sketch-front")
    stage.orbit(*SIDE)
    yield 0.3
    sketch.current_session().capture()
    draw(stage, SIDE_STROKES, 2)
    yield 0.3
    yield snap("sketch-side")
    bpy.context.window_manager.whittle_show_views = True
    stage.props.prompt = PROMPT_SKETCH
    yield 0.3
    yield snap("sketch-ready")

    # Claude asks; the answer finishes the turn.
    second = stage.submit(PROMPT_SKETCH, script)
    yield Until(lambda: stage.ctl.question is not None, "the question")
    yield snap("question")
    stage.run(operators.answer, "Brass")
    yield stage.finished(second)
    stage.button("whittle.sketch_stop")
    yield Until(lambda: sketch.current_session() is None, "the end of sketch mode")
    # The trash icon, past its confirmation: the last view would go with the next turns.
    with bpy.context.temp_override(**stage.override()):
        bpy.ops.whittle.clear_sketch("EXEC_DEFAULT", True)
    stage.orbit(*FINAL)
    yield 0.3
    yield snap("sketch-done", "sketch-done-view")

    # Another take: rope handles, then metal ones from the same point.
    (rope,) = yield from stage.turns([PROMPT_ROPE], script)
    yield 0.3
    yield snap("rope-view")
    yield snap("turn-menu", popup=Popup("operator", "whittle.turn_menu", {"node": rope}))
    stage.run(operators.branch_node, rope)
    stage.props.prompt = PROMPT_METAL
    yield 0.3
    yield snap("edit-resend")
    yield from stage.turns([PROMPT_METAL], script)
    yield 0.3
    yield snap("branched", "metal-view")
    yield snap("history-branches", popup=Popup("panel", "WHITTLE_PT_history"))
    yield snap("compare-menu", popup=Popup("operator", "whittle.turn_menu", {"node": rope}))

    # Comparing the two, and keeping the rope.
    stage.run(operators.compare_node, rope)
    yield 0.5
    to_top(stage)
    yield 0.3
    yield snap("comparing-rope")
    stage.button("whittle.compare_toggle")
    yield 0.5
    yield snap("comparing-metal")
    stage.button("whittle.compare_toggle")
    yield 0.5
    stage.button("whittle.compare_end", keep=True)
    yield Until(lambda: compare.active() is None, "the end of the comparison")
    yield 0.3
    yield snap("kept-rope")

    # A turn too far, undone.
    yield from stage.turns([PROMPT_TOO_DARK], script)
    yield 0.3
    yield snap("too-dark")
    yield from stage.press("Z", ctrl=True)
    yield from stage.settle()
    yield 0.5
    yield snap("undone", "undone-view")

    # The last turn, and the whole tree.
    yield from stage.turns([PROMPT_DARKER], script)
    yield 0.3
    to_top(stage)
    yield 0.3
    yield snap("final-window")
    yield snap("final-history", popup=Popup("panel", "WHITTLE_PT_history"))


def tall(stage):
    return story(stage, {s.name for s in SHOTS if s.setup is tall})


def wide(stage):
    return story(stage, {s.name for s in SHOTS if s.setup is wide})


def shot(name: str, description: str, capture) -> Shot:
    return Shot(name, description, capture, setup=tall if capture.kind in ("sidebar", "popup") else wide, wide=WIDE)


SHOTS = [
    shot("plain-crate", "A plain crate, selected, with the Whittle sidebar open.", window(crop=NO_STATUS)),
    shot("first-prompt", "The first prompt typed, the crate as its target.", sidebar()),
    shot("first-running", "The first turn running: a call in flight.", sidebar()),
    shot("first-done", "The first turn finished.", sidebar()),
    shot("first-done-view", "The crate with soft edges and a lid.", viewport(crop=AROUND)),
    shot("sketch-start", "Sketch pressed: the stroke types, nothing drawn yet.", sidebar(crop=SKETCH_START)),
    shot("sketch-front", "Add, carve, crease and note strokes from the front.", viewport(crop=AROUND)),
    shot("sketch-side", "A region stroke from the side, the first strokes still in place.", viewport(crop=AROUND)),
    shot("sketch-ready", "Six strokes over two views and the prompt, ready to send.", sidebar(crop=SKETCH_STRIP)),
    shot("question", "The turn paused on a question with two choices.", sidebar(crop=QUESTION)),
    shot("sketch-done", "The sketched turn finished.", sidebar(crop=SKETCHED_TURN)),
    shot("sketch-done-view", "The crate with its latch, slot, chamfer and side panel.", viewport(crop=AROUND)),
    shot("rope-view", "The crate with rope handles.", viewport(crop=AROUND)),
    shot("turn-menu", "The rope handles turn's menu.", popup()),
    shot("edit-resend", "Edit & Resend: back before the turn, a new prompt typed.", sidebar(crop=LATER_TURN)),
    shot("branched", "The metal handles branch, with the branch switcher.", sidebar(crop=LAST_TURN)),
    shot("metal-view", "The crate with metal handles.", viewport(crop=AROUND)),
    shot("history-branches", "The history popover with two branches.", popup()),
    shot("compare-menu", "The rope handles turn's menu, with Compare With Current.", popup()),
    shot("comparing-rope", "Comparing: the rope handles turn shown.", window(crop=COMPARING)),
    shot("comparing-metal", "Comparing, swapped: the current scene shown.", window(crop=COMPARING)),
    shot("kept-rope", "After Keep This: the rope handles branch again.", sidebar(crop=LAST_TURN)),
    shot("too-dark", "A turn that went too far: the wood nearly black.", viewport(crop=AROUND)),
    shot("undone", "After Ctrl+Z: one later turn, Return to Latest.", sidebar(crop=UNDONE)),
    shot("undone-view", "After Ctrl+Z: the wood as it was.", viewport(crop=AROUND)),
    shot("final-window", "The finished chest and its conversation.", window(crop=WORK)),
    shot("final-history", "The history popover with the whole tree.", popup()),
]
