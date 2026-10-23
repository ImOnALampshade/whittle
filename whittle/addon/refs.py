# SPDX-License-Identifier: GPL-3.0-or-later
"""Reference images: attached to one request, or pinned to the session so
every request carries them, and placeable as image empties in the scene."""

import filecmp
import math
import os
from pathlib import Path

import bpy
from bpy.props import EnumProperty, IntProperty

from . import targets, views

REF_PATH_PROP = "whittle_ref_path"
ALIGNS = ("FRONT", "RIGHT", "TOP", "VIEW")
ALPHA = 0.5
# Placed behind the model as seen from that side, so it never hides it.
BEHIND = 1.0
_ROTATIONS = {"FRONT": (math.pi / 2, 0.0, 0.0), "RIGHT": (math.pi / 2, 0.0, math.pi / 2),
              "TOP": (0.0, 0.0, 0.0)}


def _key(path) -> str:
    return os.path.normcase(os.path.normpath(bpy.path.abspath(str(path))))


def clear_sent(scene, sent) -> int:
    """After a successful turn: the references it sent are done with, except
    pinned ones. Returns how many were removed."""
    done = {_key(p) for p in sent}
    refs = scene.whittle.refs
    removed = 0
    for i in reversed(range(len(refs))):
        ref = refs[i]
        if not ref.pinned and ref.path and _key(ref.path) in done:
            refs.remove(i)
            removed += 1
    return removed


def add_back(scene, paths) -> int:
    """Attaches reference images again, skipping any whose content a listed
    reference already has: a pinned reference was sent too, and stays listed.
    Returns how many were added."""
    refs = scene.whittle.refs
    listed = [Path(bpy.path.abspath(r.path)) for r in refs if r.path]
    listed = [p for p in listed if p.is_file()]
    added = 0
    for path in map(Path, paths):
        if not path.is_file() or any(_same_image(path, other) for other in listed):
            continue
        refs.add().path = str(path)
        listed.append(path)
        added += 1
    return added


def _same_image(a: Path, b: Path) -> bool:
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def place_empty(scene, path, *, align: str = "FRONT", size: float = 2.0, view=None):
    """An image empty showing the reference, half transparent, in "Whittle
    References". FRONT, RIGHT and TOP stand it behind the 3D cursor as seen
    from that side; VIEW faces the viewport (view is its RegionView3D) and
    falls back to FRONT without one."""
    if align not in ALIGNS:
        raise ValueError(f"unknown alignment {align!r}")
    source = bpy.path.abspath(str(path))
    if not Path(source).is_file():
        raise FileNotFoundError(f"reference image not found: {source}")
    image = bpy.data.images.load(source, check_existing=True)
    if align == "VIEW" and view is None:
        align = "FRONT"
    obj = bpy.data.objects.new(f"Ref {Path(source).stem}", None)
    obj.empty_display_type = "IMAGE"
    obj.data = image
    obj.empty_display_size = size
    obj.use_empty_image_alpha = True
    obj.color[3] = ALPHA
    obj.hide_render = True
    obj[targets.REFERENCE_PROP] = "image"
    obj[REF_PATH_PROP] = str(path)
    cursor = scene.cursor.location.copy()
    if align == "VIEW":
        obj.rotation_euler = view.view_rotation.to_euler()
        obj.location = view.view_location
        obj.empty_image_offset = (-0.5, -0.5)
    else:
        obj.rotation_euler = _ROTATIONS[align]
        if align == "FRONT":
            obj.location = (cursor.x, cursor.y + BEHIND, cursor.z)
        elif align == "RIGHT":
            obj.location = (cursor.x - BEHIND, cursor.y, cursor.z)
        else:
            obj.location = (cursor.x, cursor.y, cursor.z - 0.01)
        # Standing on the cursor rather than centred on it, so a side view
        # of a prop lines up with the ground.
        obj.empty_image_offset = (-0.5, -0.5) if align == "TOP" else (-0.5, 0.0)
    targets.ensure_collection(scene, targets.REFERENCE_COLLECTION).objects.link(obj)
    return obj


class WHITTLE_OT_ref_pin(bpy.types.Operator):
    bl_idname = "whittle.ref_pin"
    bl_label = "Pin Reference"
    bl_description = "Pinned references go with every request; unpinned ones only with the next"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=0, min=0)

    def execute(self, context):
        refs = context.scene.whittle.refs
        if self.index >= len(refs):
            return {"CANCELLED"}
        refs[self.index].pinned = not refs[self.index].pinned
        return {"FINISHED"}


class WHITTLE_OT_ref_place(bpy.types.Operator):
    bl_idname = "whittle.ref_place"
    bl_label = "Place Reference"
    bl_description = "Show this reference image in the scene as a half-transparent image empty"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=0, min=0)
    align: EnumProperty(name="Align", default="VIEW", items=[
        ("VIEW", "View", "Facing the current view"),
        ("FRONT", "Front", "Behind the model, seen from the front"),
        ("RIGHT", "Right", "Behind the model, seen from the right"),
        ("TOP", "Top", "Under the model, seen from above")])

    def execute(self, context):
        refs = context.scene.whittle.refs
        if self.index >= len(refs) or not refs[self.index].path:
            return {"CANCELLED"}
        # The chip's menu runs this in the sidebar, which has no view of its
        # own: the view is the viewport's beside it.
        viewport = views.viewport_from_context(context)
        view = viewport.rv3d if viewport is not None else None
        try:
            obj = place_empty(context.scene, refs[self.index].path, align=self.align, view=view)
        except (OSError, RuntimeError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Placed {obj.name}")
        return {"FINISHED"}


CLASSES = (WHITTLE_OT_ref_pin, WHITTLE_OT_ref_place)
