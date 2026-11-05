# SPDX-License-Identifier: GPL-3.0-or-later
"""Shots for guides/references: chips over the prompt, a chip's menu, what a
finished turn leaves, and a reference placed behind the model."""

from tests.docshots.spec import LID, Popup, Shot, Snap, done, exec_, popup, render, say, sidebar, viewport

PROMPT = "Add a lid like the one in the reference drawings."
SIZE = 512


def drawing(stage, name: str, paper):
    """A plain elevation of the crate with an overhanging lid, standing on the
    image's bottom edge at the scale a placed reference shows it: the image is
    two metres wide, so 256 pixels a metre."""
    import bpy
    import numpy as np

    pixels = np.ones((SIZE, SIZE, 4), dtype=np.float32)
    pixels[..., :3] = paper
    ink = (0.12, 0.10, 0.08)

    def box(left, bottom, right, top):
        pixels[bottom:top, left:left + 4, :3] = ink
        pixels[bottom:top, right - 4:right, :3] = ink
        pixels[bottom:bottom + 4, left:right, :3] = ink
        pixels[top - 4:top, left:right, :3] = ink

    box(187, 0, 325, 128)
    box(175, 128, 337, 148)
    for y in (42, 85):
        pixels[y:y + 3, 187:325, :3] = ink

    image = bpy.data.images.new(name, SIZE, SIZE)
    image.pixels.foreach_set(pixels.ravel())
    path = stage.work / f"{name}.png"
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


def attach(stage):
    """crate_front.png pinned, crate_side.png for the next request only."""
    for name, paper, pinned in (("crate_front", (0.93, 0.86, 0.72), True), ("crate_side", (0.76, 0.84, 0.92), False)):
        ref = stage.props.refs.add()
        ref.path = str(drawing(stage, name, paper))
        ref.pinned = pinned


def attached(stage):
    stage.crate()
    attach(stage)
    stage.props.prompt = PROMPT
    yield 0.5
    yield Snap("attached")
    yield Snap("chip-menu", popup=Popup("operator", "whittle.ref_menu", {"index": 0}))
    script = stage.script("lid", [{"steps": [say("Adding a lid with an overhang, as in both drawings."),
                                             exec_("add lid", LID), render((1.5, -1.5, 1.2))],
                                   "finish": done("Added the lid. It overhangs the sides as the drawings show.")}])
    yield from stage.turns([PROMPT], script)
    yield 0.5


def placed(stage):
    import bpy

    stage.crate()
    attach(stage)
    with bpy.context.temp_override(**stage.override()):
        bpy.ops.whittle.ref_place(index=0, align="FRONT")
    # A post behind the drawing shows it is see-through, and the floor grid
    # shows it stands on the same ground as the crate.
    bpy.ops.mesh.primitive_cylinder_add(radius=0.14, depth=1.5, location=(0.55, 1.7, 0.75))
    bpy.context.object.name = "Post"
    bpy.context.object.color = (0.75, 0.25, 0.15, 1.0)
    space = stage.override()["area"].spaces.active
    space.shading.color_type = "OBJECT"
    space.overlay.show_object_origins = False
    bpy.ops.object.select_all(action="DESELECT")
    stage.orbit((0.9, -3.0, 0.9), 4.2, look_at=(0.0, 0.3, 0.75))
    yield 0.5


SHOTS = [
    Shot("attached", "Two reference images over the prompt, the first pinned.", sidebar(), setup=attached),
    Shot("chip-menu", "The menu of a reference's chip.", popup(), setup=attached),
    Shot("after-turn", "After a turn: the pinned reference stays, the other is gone.", sidebar(), setup=attached),
    Shot("placed", "A reference placed behind the crate.", viewport(crop=(240, 0, 640, 620)), setup=placed),
]
