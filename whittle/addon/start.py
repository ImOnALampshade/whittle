# SPDX-License-Identifier: GPL-3.0-or-later
"""Start points: what node 0 of the history is.

- From the existing scene: the picked or selected objects as they are.
- Blank: the scene as it is with nothing selected or targeted, so the first
  turn makes new objects. Nothing is added to the scene.
- A primitive, or an object or collection asset from the Asset Browser.

A start can be taken again until the first turn. After that node 0 is what
every turn grew from, so the Start panel goes away."""

from pathlib import Path

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from .. import tree
from . import compare, history, operators, targets, turn

TARGET_COLLECTION = "Whittle Target"
# What a start put in the scene: "made" for an object or collection it created
# (a primitive, an appended asset), "linked" for one of the file's own that it
# only linked in. A retaken start takes these back out.
START_PROP = "whittle_start"
PRIMITIVES = ("CUBE", "CYLINDER", "CONE", "UV_SPHERE", "ICO_SPHERE", "PLANE", "MONKEY")
ASSET_TYPES = ("OBJECT", "COLLECTION")

class StartError(RuntimeError):
    pass


def can_start(hist, ctl, comparing) -> str | None:
    """Why a start point cannot be taken now, or None."""
    if turn.busy(ctl):
        return "Wait for the turn to finish"
    if comparing is not None:
        return "End the comparison first"
    if hist is not None and hist.tree is not None and hist.tree.visible_children(hist.tree.root):
        return "The history already has turns; restore or branch from a node instead"
    return None


def _check(ctl) -> None:
    reason = can_start(ctl.history, ctl, compare.active())
    if reason:
        raise StartError(reason)


def _record(ctl, scene, objects, label: str) -> str:
    try:
        return ctl.history.start(objects, scene, label=label)
    except tree.TreeError as exc:
        raise StartError(str(exc)) from exc


def _take_back(scene, keep=()) -> None:
    """Undoes what an earlier start put in the scene, so a retaken start's
    node 0 holds only what the new start chose."""
    keep = {o.as_pointer() for o in keep}
    for found in [c for c in bpy.data.collections if START_PROP in c and c.library is None]:
        if found.as_pointer() in keep:
            continue
        if found[START_PROP] == "made":
            _remove_collection(found)
            continue
        del found[START_PROP]
        if found.name in scene.collection.children:
            scene.collection.children.unlink(found)
    collection = bpy.data.collections.get(TARGET_COLLECTION)
    if collection is None or collection.library is not None:
        return
    for obj in list(collection.objects):
        role = obj.get(START_PROP)
        if role is None or obj.as_pointer() in keep:
            continue
        if role == "made":
            bpy.data.objects.remove(obj)
            continue
        del obj[START_PROP]
        collection.objects.unlink(obj)
        if not obj.users_collection:
            # It came from elsewhere in the scene; leave it in the scene.
            scene.collection.objects.link(obj)


def _remove_collection(collection) -> None:
    """An appended collection asset goes with the objects and collections it
    brought; an object also in some other collection stays."""
    inside = [collection, *collection.children_recursive]
    pointers = {c.as_pointer() for c in inside}
    for obj in list(collection.all_objects):
        if all(c.as_pointer() in pointers for c in obj.users_collection):
            bpy.data.objects.remove(obj)
    for child in reversed(inside):
        if child.as_pointer() == collection.as_pointer() or child.users <= 1:
            bpy.data.collections.remove(child)


def _set_targets(scene, objects, collection=None) -> None:
    props = scene.whittle
    props.targets.clear()
    props.target_index = 0
    props.target_collection = collection
    targets.add(scene, objects)
    targets.select_list(scene)


# -- start points -------------------------------------------------------------------

def start_existing(context, ctl) -> str:
    """The selected objects become the target (the picker as it is when
    nothing eligible is selected), and node 0 is written now."""
    _check(ctl)
    scene = context.scene
    if any(targets.eligible(o) for o in context.selected_objects):
        _set_targets(scene, context.selected_objects, None)
    # What earlier starts made is now part of the scene the user starts
    # from, so a later retake must not take it away.
    for block in [*bpy.data.objects, *bpy.data.collections]:
        if START_PROP in block:
            del block[START_PROP]
    _record(ctl, scene, targets.resolve(scene), tree.ROOT_LABEL)
    return f"Start: {targets.describe(scene)}"


def start_blank(context, ctl) -> None:
    """The scene as it is, with nothing selected and nothing targeted, so the
    first turn makes new objects (they become the targets after it). Adds
    nothing to the scene; objects already in it are left alone."""
    _check(ctl)
    scene = context.scene
    _take_back(scene)
    view_layer = context.view_layer
    # The take-back may have removed objects the list still holds.
    view_layer.update()
    for obj in view_layer.objects:
        if obj is not None:
            obj.select_set(False)
    view_layer.objects.active = None
    _set_targets(scene, [])
    _record(ctl, scene, [], "Blank")


def start_primitive(context, ctl, kind: str, *, size: float = 1.0):
    """A primitive standing at the 3D cursor (its base at z = 0), as the sole
    target, in the target collection."""
    if kind not in PRIMITIVES:
        raise StartError(f"unknown primitive {kind!r}")
    if size <= 0:
        raise StartError("the size must be positive")
    _check(ctl)
    scene = context.scene
    _take_back(scene)
    name = kind.replace("_", " ").title().replace(" ", "")
    obj = bpy.data.objects.new(name, primitive_mesh(kind, size, name))
    obj[START_PROP] = "made"
    collection = targets.ensure_collection(scene, TARGET_COLLECTION)
    collection.objects.link(obj)
    cursor = scene.cursor.location
    obj.location = (cursor.x, cursor.y, 0.0)
    _set_targets(scene, [obj], collection)
    _record(ctl, scene, targets.resolve(scene), f"Primitive: {name}")
    return obj


def start_asset(context, ctl, *, filepath: str, id_type: str, name: str, local: bool = False) -> list:
    """An object or collection asset becomes the target. One from another
    file is appended (no library is left behind); one in this file is used
    in place."""
    if id_type not in ASSET_TYPES:
        raise StartError(f"only object and collection assets can be a start, not {id_type.lower()}")
    if not name:
        raise StartError("no asset named")
    _check(ctl)
    scene = context.scene
    attr = "objects" if id_type == "OBJECT" else "collections"
    if local:
        block = getattr(bpy.data, attr).get(name)
        if block is None:
            raise StartError(f"there is no {id_type.lower()} {name!r} in this file")
    else:
        block = _append(bpy.path.abspath(filepath), attr, name)
    # A local asset may itself be what an earlier start linked.
    _take_back(scene, keep=[block] if local else ())

    if id_type == "OBJECT":
        if block.name in scene.objects:
            if block.get(START_PROP) is not None:
                del block[START_PROP]
            _set_targets(scene, [block])
        else:
            collection = targets.ensure_collection(scene, TARGET_COLLECTION)
            collection.objects.link(block)
            block[START_PROP] = "linked" if local else "made"
            if block.parent is None and not local:
                block.location = scene.cursor.location
            _set_targets(scene, [block], collection)
    else:
        if block not in scene.collection.children_recursive:
            scene.collection.children.link(block)
            block[START_PROP] = "linked" if local else "made"
        _set_targets(scene, [], block)
    objects = targets.resolve(scene)
    _record(ctl, scene, objects, f"Asset: {name}")
    return objects


def _append(path: str, attr: str, name: str):
    if not Path(path).is_file():
        raise StartError(f"the asset file {path} does not exist")
    before = {lib.as_pointer() for lib in bpy.data.libraries}
    found = False
    with bpy.data.libraries.load(path, link=False, assets_only=True, clear_asset_data=True) as (src, dst):
        found = name in getattr(src, attr)
        if found:
            setattr(dst, attr, [name])
    try:
        if not found or not getattr(dst, attr) or getattr(dst, attr)[0] is None:
            raise StartError(f"there is no {attr[:-1]} asset {name!r} in {path}")
        return getattr(dst, attr)[0]
    finally:
        # Appending leaves a Library behind even though nothing is linked.
        for lib in list(bpy.data.libraries):
            if lib.as_pointer() not in before:
                bpy.data.libraries.remove(lib)


# -- meshes -----------------------------------------------------------------------

def primitive_mesh(kind: str, size: float, name: str):
    """A mesh whose largest side is `size`, centred on x and y with its base
    at z = 0, so the object stands on the ground at its origin."""
    bm = bmesh.new()
    try:
        ops = bmesh.ops
        if kind == "CUBE":
            ops.create_cube(bm, size=1.0)
        elif kind == "CYLINDER":
            ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.5, radius2=0.5, depth=1.0)
        elif kind == "CONE":
            ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.5, radius2=0.0, depth=1.0)
        elif kind == "UV_SPHERE":
            ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.5)
        elif kind == "ICO_SPHERE":
            ops.create_icosphere(bm, subdivisions=2, radius=0.5)
        elif kind == "PLANE":
            ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
        elif kind == "MONKEY":
            ops.create_monkey(bm)
        else:
            raise StartError(f"unknown primitive {kind!r}")
        _fit(bm, size)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    return mesh


def _fit(bm, size: float) -> None:
    lo = [min(v.co[i] for v in bm.verts) for i in range(3)]
    hi = [max(v.co[i] for v in bm.verts) for i in range(3)]
    scale = size / max(h - l for h, l in zip(hi, lo))
    centre = [(h + l) / 2 for h, l in zip(hi, lo)]
    for v in bm.verts:
        v.co = ((v.co.x - centre[0]) * scale, (v.co.y - centre[1]) * scale, (v.co.z - lo[2]) * scale)
    bm.normal_update()


# -- operators ------------------------------------------------------------------------

def _controller(context):
    return operators.controller(context.window_manager.whittle_fake_script)


class _StartOperator:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return can_start(history.active(), turn.current(), compare.active()) is None

    def run(self, context, ctl) -> str:
        raise NotImplementedError

    def execute(self, context):
        try:
            message = self.run(context, _controller(context))
        except (StartError, RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        return {"FINISHED"}


class WHITTLE_OT_start_existing(_StartOperator, bpy.types.Operator):
    bl_idname = "whittle.start_existing"
    bl_label = "Start From Selection"
    bl_description = "Start from the scene as it is: the selected objects are the target"

    def run(self, context, ctl):
        return start_existing(context, ctl)


class WHITTLE_OT_start_blank(_StartOperator, bpy.types.Operator):
    bl_idname = "whittle.start_blank"
    bl_label = "Start Blank"
    bl_description = ("Start from this scene with nothing selected: Claude makes new objects. "
                      "Nothing is added to the scene")

    def run(self, context, ctl):
        start_blank(context, ctl)
        return "Blank start: Claude makes new objects"


class WHITTLE_OT_start_primitive(_StartOperator, bpy.types.Operator):
    bl_idname = "whittle.start_primitive"
    bl_label = "Start From Primitive"
    bl_description = "Start from a primitive standing at the 3D cursor"

    kind: EnumProperty(name="Primitive", default="CUBE", items=[
        (k, k.replace("_", " ").title(), f"Start from a {k.replace('_', ' ').lower()}") for k in PRIMITIVES])
    size: FloatProperty(name="Size", default=1.0, min=0.01, soft_max=10.0, subtype="DISTANCE",
                        unit="LENGTH", description="Its largest side")

    def run(self, context, ctl):
        obj = start_primitive(context, ctl, self.kind, size=self.size)
        return f"Start: {obj.name}"


class WHITTLE_OT_start_asset(_StartOperator, bpy.types.Operator):
    bl_idname = "whittle.start_asset"
    bl_label = "Start Whittle From Asset"
    bl_description = "Start a Whittle session from this asset: it becomes the target"

    filepath: StringProperty(name="File", subtype="FILE_PATH", default="", options={"SKIP_SAVE"})
    id_type: EnumProperty(name="Type", default="OBJECT", options={"SKIP_SAVE"}, items=[
        ("OBJECT", "Object", ""), ("COLLECTION", "Collection", ""), ("MATERIAL", "Material", ""),
        ("OTHER", "Other", "")])
    name: StringProperty(name="Name", default="", options={"SKIP_SAVE"})
    local: BoolProperty(name="In This File", default=False, options={"SKIP_SAVE"})

    def invoke(self, context, event):
        asset = getattr(context, "asset", None)
        if asset is not None:
            kind = asset.id_type if asset.id_type in ("OBJECT", "COLLECTION", "MATERIAL") else "OTHER"
            self.id_type = kind
            if asset.local_id is not None:
                self.local, self.name = True, asset.local_id.name
            else:
                self.local, self.name = False, asset.name
                self.filepath = asset.full_library_path
        return self.execute(context)

    def run(self, context, ctl):
        objects = start_asset(context, ctl, filepath=self.filepath, id_type=self.id_type,
                              name=self.name, local=self.local)
        return f"Start: {', '.join(o.name for o in objects) or self.name}"


def draw_asset_menu(self, context):
    """The Asset Browser's context menu entry."""
    asset = getattr(context, "asset", None)
    if asset is None or asset.id_type not in ASSET_TYPES:
        return
    self.layout.separator()
    self.layout.operator_context = "INVOKE_DEFAULT"
    self.layout.operator("whittle.start_asset", icon="GREASEPENCIL")


CLASSES = (WHITTLE_OT_start_existing, WHITTLE_OT_start_blank, WHITTLE_OT_start_primitive,
           WHITTLE_OT_start_asset)

