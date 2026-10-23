# SPDX-License-Identifier: GPL-3.0-or-later
"""Handlers for the agent's calls. Each runs on Blender's main thread from the
bridge queue and returns plain JSON data, a Deferred, or raises BridgeError."""

import difflib
from collections.abc import Callable
from dataclasses import dataclass, field

import bpy
from mathutils import Vector

from .. import formats
from ..protocol import ErrorCode, Method
from . import execution, render, sketch, snapshot
from .bridge import BridgeError, Deferred
from .bundle import UID_PROP

INSPECT_QUERIES = ("summary", "object", "materials", "node_groups", "scene")


@dataclass
class CommandContext:
    session: formats.SessionDir
    turn_id: Callable[[], str | None] = lambda: None
    bundle: Callable[[], formats.Bundle | None] = lambda: None
    settings: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # Background runs have nobody to answer a question.
    attended: Callable[[], bool] = lambda: not bpy.app.background
    on_ask: Callable[[str, list], None] | None = None
    namespace: execution.ExecNamespace | None = None
    checkpoints: int = 0
    # The running turn's amendment bundles; their views join the request's.
    amend_bundles: Callable[[], list[formats.Bundle]] = lambda: []
    # The node number the running turn's sketch strokes are stamped with, or
    # None when its strokes did not come from the live sketch.
    turn_number: Callable[[], int | None] = lambda: None
    # Objects this turn's exec calls created, in order.
    added: list[str] = field(default_factory=list)
    # What a checkpoint saves: the targets and the objects made this turn.
    turn_objects: Callable[[], list] = lambda: []
    # Told (appended objects, {name: session_uid of the object each replaced})
    # after a checkpoint restore, so the turn keeps track of its objects.
    on_restored: Callable[[list, dict], None] | None = None
    # This turn's checkpoints: id -> {"snapshot", "uids": session uids then}.
    checkpoint_state: dict = field(default_factory=dict)
    # This turn's calls that can change the scene (exec, restore_checkpoint),
    # failed ones included: a turn without any changed nothing.
    edits: int = 0

    def __post_init__(self):
        if self.namespace is None:
            self.namespace = execution.ExecNamespace(self.targets)

    def reset_turn(self) -> None:
        self.added.clear()
        self.notes.clear()
        self.checkpoints = 0
        self.edits = 0
        self.checkpoint_state.clear()

    def views(self) -> dict[int, formats.View]:
        """The request's views and those of its amendments. View ids are global
        on the sketch, so they never clash."""
        bundle = self.bundle()
        merged = dict(bundle.views) if bundle else {}
        for amend in self.amend_bundles():
            merged.update(amend.views)
        return merged

    def targets(self) -> list:
        """The request's targets as they are now. Found by whittle_uid, so a
        target the agent renamed is still one."""
        bundle = self.bundle()
        if bundle is None:
            return []
        found = []
        for entry, holder in zip(bundle.request.target, snapshot.holders(bundle.request.target)):
            if holder is None:
                # A bundle written from another file carries uids this one
                # never stamped: its targets go by name.
                holder = bpy.data.objects.get(entry["name"])
            if holder is not None and holder not in found:
                found.append(holder)
        return found

    def take_notes(self) -> list[str]:
        notes, self.notes = self.notes, []
        return notes


def require(params: dict, key: str, types, *, optional: bool = False, default=None):
    value = params.get(key)
    if value is None:
        if optional:
            return default
        raise BridgeError(ErrorCode.BAD_REQUEST, f"missing parameter {key!r}")
    types = types if isinstance(types, tuple) else (types,)
    if not isinstance(value, types) or (isinstance(value, bool) and bool not in types):
        raise BridgeError(ErrorCode.BAD_REQUEST, f"parameter {key!r} has the wrong type")
    return value


def build_handlers(ctx: CommandContext) -> dict:
    return {
        Method.EXEC: lambda p: handle_exec(ctx, p),
        Method.INSPECT: lambda p: handle_inspect(ctx, p),
        Method.RENDER: lambda p: handle_render(ctx, p),
        Method.CHECKPOINT: lambda p: handle_checkpoint(ctx, p),
        Method.RESTORE_CHECKPOINT: lambda p: handle_restore_checkpoint(ctx, p),
        Method.ASK: lambda p: handle_ask(ctx, p),
    }


# -- exec ---------------------------------------------------------------------

def handle_exec(ctx: CommandContext, params: dict) -> dict:
    code = require(params, "code", str)
    ctx.edits += 1
    # In Edit Mode the live mesh is the edit mesh, not obj.data: the code
    # would read stale data, and what it wrote would be lost on leaving.
    snapshot.leave_edit_mode(ctx.turn_objects())
    result = execution.run(code, ctx.namespace)
    ctx.added += [name for name in result["diff"]["added"] if name not in ctx.added]
    result["notes"] = ctx.take_notes()
    return result


# -- inspect ------------------------------------------------------------------

def _r(values, digits=4) -> list:
    return [round(float(v), digits) + 0.0 for v in values]


def _object_summary(obj, targets) -> dict:
    info = {
        "name": obj.name,
        "type": obj.type,
        "location": _r(obj.location),
        "rotation_euler": _r(obj.rotation_euler),
        "scale": _r(obj.scale),
        "dimensions": _r(obj.dimensions),
        "parent": obj.parent.name if obj.parent else None,
        "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers],
        "materials": [s.material.name if s.material else None for s in obj.material_slots],
        "is_target": obj in targets,
        "hidden": obj.hide_get() if obj.name in bpy.context.view_layer.objects else True,
    }
    if obj.type == "MESH":
        mesh = obj.data
        info["verts"] = len(mesh.vertices)
        info["faces"] = len(mesh.polygons)
        info["triangles"] = sum(len(p.vertices) - 2 for p in mesh.polygons)
    return info


def _plain(value):
    """JSON-ready copy of an RNA value. Multi-dimensional arrays (a hook's
    matrix_inverse) come back as mathutils objects, so nesting is flattened
    into lists; anything else unexpected is dropped."""
    if isinstance(value, float):
        return round(value, 5)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    try:
        items = list(value)
    except TypeError:
        return None
    items = [_plain(v) for v in items]
    return None if any(v is None for v in items) else items


def _simple_props(struct) -> dict:
    props = {}
    for prop in struct.bl_rna.properties:
        if prop.identifier in ("rna_type", "name", "type") or prop.is_readonly:
            continue
        value = getattr(struct, prop.identifier, None)
        if prop.type in ("BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"):
            if prop.type == "ENUM" and prop.is_enum_flag:
                value = sorted(value)
            value = _plain(value)
            if value is not None:
                props[prop.identifier] = value
        elif prop.type == "POINTER" and value is not None and hasattr(value, "name"):
            props[prop.identifier] = value.name
    return props


def _missing_object(name: str, targets) -> BridgeError:
    """not_found for an object name, naming the targets and any close match
    so the next call can get it right."""
    message = f"no object named {name!r}"
    close = difflib.get_close_matches(name, [o.name for o in bpy.data.objects], n=3)
    if close:
        message += "; similar names: " + ", ".join(close)
    message += "; targets are: " + (", ".join(o.name for o in targets) or "none")
    return BridgeError(ErrorCode.NOT_FOUND, message)


def _inspect_object(ctx, params) -> dict:
    if params.get("name") is None:
        raise BridgeError(ErrorCode.BAD_REQUEST, "query 'object' needs name, the object's name; "
                                                 "query 'summary' lists every object")
    name = require(params, "name", str)
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise _missing_object(name, ctx.targets())
    info = _object_summary(obj, ctx.targets())
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    info["world_bounds"] = {
        "min": _r(min(c[i] for c in corners) for i in range(3)),
        "max": _r(max(c[i] for c in corners) for i in range(3)),
        "corners": [_r(c) for c in corners],
    }
    info["modifiers"] = [{"name": m.name, "type": m.type, "settings": _simple_props(m)}
                         for m in obj.modifiers]
    info["vertex_groups"] = [g.name for g in obj.vertex_groups]
    info["custom_properties"] = {k: v for k, v in obj.items()
                                 if isinstance(v, (int, float, str, bool))}
    if obj.type == "MESH":
        mesh = obj.data
        info["mesh"] = {"name": mesh.name, "edges": len(mesh.edges),
                        "color_attributes": [a.name for a in mesh.color_attributes],
                        "uv_layers": [u.name for u in mesh.uv_layers]}
    return info


def _material_info(mat) -> dict:
    info = {"name": mat.name, "users": mat.users, "diffuse_color": _r(mat.diffuse_color),
            "is_grease_pencil": mat.is_grease_pencil, "use_nodes": bool(mat.node_tree)}
    tree = mat.node_tree
    if tree is not None:
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None:
            info["base_color"] = _r(bsdf.inputs["Base Color"].default_value)
            info["roughness"] = round(bsdf.inputs["Roughness"].default_value, 4)
            info["metallic"] = round(bsdf.inputs["Metallic"].default_value, 4)
        info["nodes"] = len(tree.nodes)
    return info


def _node_group_info(group) -> dict:
    sockets = [{"name": item.name, "in_out": item.in_out, "socket_type": item.socket_type}
               for item in group.interface.items_tree if item.item_type == "SOCKET"]
    return {"name": group.name, "type": group.bl_idname, "users": group.users,
            "nodes": len(group.nodes), "interface": sockets}


def _scene_info() -> dict:
    scene = bpy.context.scene
    units = scene.unit_settings
    return {
        "name": scene.name,
        "units": {"system": units.system, "scale_length": units.scale_length,
                  "length_unit": units.length_unit},
        "frame_current": scene.frame_current,
        "render_engine": scene.render.engine,
        "camera": scene.camera.name if scene.camera else None,
        "counts": {"objects": len(scene.objects), "meshes": len(bpy.data.meshes),
                   "materials": len(bpy.data.materials), "node_groups": len(bpy.data.node_groups)},
    }


def handle_inspect(ctx: CommandContext, params: dict) -> dict:
    result = _inspect(ctx, params)
    result["notes"] = ctx.take_notes()
    return result


def _inspect(ctx: CommandContext, params: dict) -> dict:
    query = require(params, "query", str)
    if query not in INSPECT_QUERIES:
        raise BridgeError(ErrorCode.BAD_REQUEST,
                          f"unknown query {query!r}; use one of {', '.join(INSPECT_QUERIES)}")
    if query == "summary":
        targets = ctx.targets()
        return {"objects": [_object_summary(o, targets) for o in bpy.context.scene.objects],
                "targets": [o.name for o in targets]}
    if query == "object":
        return _inspect_object(ctx, params)
    if query == "materials":
        return {"materials": [_material_info(m) for m in bpy.data.materials]}
    if query == "node_groups":
        return {"node_groups": [_node_group_info(g) for g in bpy.data.node_groups]}
    return _scene_info()


# -- render -------------------------------------------------------------------

def handle_render(ctx: CommandContext, params: dict) -> dict:
    mode = require(params, "mode", str)
    if mode not in formats.RENDER_MODES:
        raise BridgeError(ErrorCode.BAD_REQUEST,
                          f"unknown mode {mode!r}; use one of {', '.join(formats.RENDER_MODES)}")
    view_id = require(params, "view", int, optional=True)
    cam = require(params, "camera", dict, optional=True)
    size = require(params, "size", int, optional=True,
                   default=int(ctx.settings.get("render_size") or 512))
    if (view_id is None) == (cam is None):
        known = sorted(ctx.views())
        raise BridgeError(ErrorCode.BAD_REQUEST,
                          "give exactly one of view (a sketch view id; this turn has "
                          f"{', '.join(map(str, known)) or 'none'}) or camera "
                          "({location, look_at}, world-space points in metres)")
    if mode == "overlay" and view_id is None:
        raise BridgeError(ErrorCode.BAD_REQUEST, "overlay renders need a sketch view (view=<id>); "
                                                 "with a camera, use shaded, wireframe or matcap")
    if not render.MIN_SIZE <= size <= render.MAX_SIZE:
        raise BridgeError(ErrorCode.BAD_REQUEST, f"size must be {render.MIN_SIZE}..{render.MAX_SIZE}")

    if view_id is not None:
        known = ctx.views()
        view = known.get(view_id)
        if view is None:
            hint = "" if known else " (this request has no sketch: place a camera instead)"
            raise BridgeError(ErrorCode.NOT_FOUND, f"no view {view_id}; views: {sorted(known)}{hint}")
        spec, aspect = view.camera, view.aspect
    else:
        try:
            location = [float(v) for v in cam["location"]]
            look_at = [float(v) for v in cam["look_at"]]
            if len(location) != 3 or len(look_at) != 3:
                raise ValueError("location and look_at need three numbers")
            spec = render.camera_from_look_at(location, look_at, cam.get("lens_mm"))
        except (KeyError, TypeError, ValueError) as exc:
            raise BridgeError(ErrorCode.BAD_REQUEST, f"bad camera: {exc}") from None
        aspect = 1.0

    scene = bpy.context.scene
    sketch_obj = sketch.find_sketch_object()
    if mode == "overlay" and sketch_obj is None:
        raise BridgeError(ErrorCode.NOT_FOUND, "there is no Whittle Sketch object to overlay; "
                                               "render this view in shaded mode instead")
    out = ctx.session.next_render_path(ctx.turn_id() or "n0000", view_id, mode)
    turn = ctx.turn_number()
    # Strokes drawn since the submit are for later; the agent sees only its
    # turn's strokes, amendments included.
    keep = None if turn is None else (lambda t, _amend: t == turn)
    result = render.render(scene, spec, mode, size, out, aspect=aspect, sketch=sketch_obj,
                           targets=ctx.targets(), keep_strokes=keep)
    result["notes"] = ctx.take_notes()
    return result


# -- checkpoint and ask -------------------------------------------------------

def _running_turn(ctx: CommandContext) -> str:
    turn = ctx.turn_id()
    if turn is None:
        raise BridgeError(ErrorCode.BAD_REQUEST, "no running turn")
    return turn


def handle_checkpoint(ctx: CommandContext, params: dict) -> dict:
    label = require(params, "label", str, optional=True, default="")
    turn = _running_turn(ctx)
    number = ctx.checkpoints + 1
    checkpoint = f"c{number}"
    blend, _manifest = ctx.session.checkpoint_paths(turn, checkpoint)
    objects = ctx.turn_objects()
    snap = snapshot.write(blend, objects)
    ctx.checkpoints = number
    ctx.checkpoint_state[checkpoint] = {"snapshot": snap, "label": label,
                                        "uids": {o.session_uid for o in bpy.data.objects}}
    return {"checkpoint_id": checkpoint, "label": label, "restorable": True,
            "objects": [o.name for o in objects], "notes": ctx.take_notes()}


def handle_restore_checkpoint(ctx: CommandContext, params: dict) -> dict:
    checkpoint = require(params, "checkpoint_id", str)
    _running_turn(ctx)
    state = ctx.checkpoint_state.get(checkpoint)
    if state is None:
        known = ", ".join(ctx.checkpoint_state) or "none"
        raise BridgeError(ErrorCode.NOT_FOUND, f"no checkpoint {checkpoint!r} this turn (checkpoints: {known})")
    snap = state["snapshot"]
    ctx.edits += 1
    # Only what the agent made after the checkpoint goes; the user's objects
    # and anything older stay.
    later = [o for o in bpy.data.objects if o.name in ctx.added and o.session_uid not in state["uids"]
             and o.name not in snap.names]
    remove = [o.name for o in later]
    # Keyed by whittle_uid: the restored copy carries the uid of the object it
    # replaced, whatever either is called.
    replaced = {o[UID_PROP]: o.session_uid for o in bpy.data.objects if UID_PROP in o}
    names = snapshot.restore(snap, remove=remove)
    removed = [name for name in remove if name not in bpy.data.objects]
    if ctx.on_restored is not None:
        ctx.on_restored([bpy.data.objects[n] for n in names if n in bpy.data.objects], replaced)
    return {"restored": names, "removed": removed, "notes": ctx.take_notes()}


def handle_ask(ctx: CommandContext, params: dict):
    question = require(params, "question", str)
    choices = require(params, "choices", list, optional=True, default=[])
    if not ctx.attended():
        return {"answer": "", "unattended": True}
    if ctx.on_ask is not None:
        ctx.on_ask(question, [str(c) for c in choices])
    return Deferred()
