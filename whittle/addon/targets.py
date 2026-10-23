# SPDX-License-Identifier: GPL-3.0-or-later
"""The target picker: an explicit object list plus an optional collection,
stored on scene.whittle. Nothing picked means the agent makes new objects."""

import bpy

from . import sketch

EXCLUDED_TYPES = ("CAMERA", "LIGHT", "LIGHT_PROBE", "SPEAKER")
# Marks the wireframe copies of a history node shown as a ghost; the value is
# the node id.
GHOST_PROP = "whittle_ghost"
# Marks Whittle's helpers (the ground, the scale reference, reference image
# empties); the value says which. They are never targets.
REFERENCE_PROP = "whittle_reference"
REFERENCE_COLLECTION = "Whittle References"


def eligible(obj) -> bool:
    return (obj is not None and obj.type not in EXCLUDED_TYPES and obj.name != sketch.SKETCH_NAME
            and GHOST_PROP not in obj and REFERENCE_PROP not in obj)


def ensure_collection(scene, name: str):
    """The collection of that name, made and linked under the scene's own
    collection if needed."""
    collection = bpy.data.collections.get(name)
    if collection is None or collection.library is not None:
        collection = bpy.data.collections.new(name)
    if collection not in scene.collection.children_recursive:
        scene.collection.children.link(collection)
    return collection


def resolve(scene) -> list:
    """The picked objects and the collection's objects, each once, in the
    scene, never the sketch or a camera, light, probe or speaker."""
    props = scene.whittle
    found = [t.object for t in props.targets]
    if props.target_collection is not None:
        found += list(props.target_collection.all_objects)
    seen, out = set(), []
    for obj in found:
        if not eligible(obj) or obj.name in seen or obj.name not in scene.objects:
            continue
        seen.add(obj.name)
        out.append(obj)
    return out


def add(scene, objects) -> int:
    """Appends objects to the list, skipping duplicates; returns how many were added.
    Entries whose object was deleted since go, so the list never shows an
    empty row."""
    props = scene.whittle
    for i in reversed(range(len(props.targets))):
        if props.targets[i].object is None:
            props.targets.remove(i)
    props.target_index = min(props.target_index, max(len(props.targets) - 1, 0))
    present = {t.object.name for t in props.targets if t.object is not None}
    added = 0
    for obj in objects:
        if not eligible(obj) or obj.name in present:
            continue
        props.targets.add().object = obj
        present.add(obj.name)
        added += 1
    return added


def set_from_selection(context) -> int:
    props = context.scene.whittle
    props.targets.clear()
    props.target_index = 0
    return add(context.scene, context.selected_objects)


def describe(scene, max_chars: int = 0, names: list[str] | None = None) -> str:
    """The target in a few words: 'Crate, Crate_Lid', 'Crate + 2 more',
    'New objects'. With max_chars, the names are cut down
    to fit. names replaces the picked list (a running turn's targets)."""
    props = scene.whittle
    picked = names if names is not None else [t.object.name for t in props.targets if eligible(t.object)]
    collection = props.target_collection
    suffix = ""
    if collection is not None:
        count = len([o for o in collection.all_objects if eligible(o)])
        if not picked:
            return f"{collection.name} ({count})" if count else f"New objects in {collection.name}"
        suffix = f" + {collection.name} ({count})"
    if not picked:
        return "New objects"
    text = ", ".join(picked) + suffix
    if not max_chars or len(text) <= max_chars:
        return text
    for shown in range(len(picked) - 1, 0, -1):
        text = ", ".join(picked[:shown]) + f" + {len(picked) - shown} more" + suffix
        if len(text) <= max_chars:
            return text
    return f"{picked[0]} + {len(picked) - 1} more{suffix}" if len(picked) > 1 else picked[0] + suffix


def auto_pick(view_layer) -> list:
    """What Auto targets: the eligible selected objects, the active one
    first; else the active object alone; else nothing (new objects)."""
    active = view_layer.objects.active
    selected = [o for o in view_layer.objects.selected if eligible(o)]
    if selected:
        if active in selected:
            selected.remove(active)
            selected.insert(0, active)
        return selected
    if eligible(active) and active.visible_get(view_layer=view_layer):
        return [active]
    return []


def sync_auto(scene, view_layer) -> bool:
    """With Auto on, makes the target list what auto_pick says; returns
    whether it changed. The list is only written when it differs, so the
    depsgraph update the write causes finds nothing more to do."""
    props = scene.whittle
    if not props.target_auto:
        return False
    wanted = auto_pick(view_layer)
    if [t.object for t in props.targets] == wanted:
        return False
    props.targets.clear()
    props.target_index = 0
    for obj in wanted:
        props.targets.add().object = obj
    return True


def select_list(scene, view_layer=None) -> None:
    """After Whittle itself set the target list (a turn's end, a restore, a
    start point...): with Auto on, the selection becomes exactly the list,
    the active object kept if it is in it, so the next Auto sync agrees with
    the history instead of undoing it. An active object in another mode
    than Object Mode (the sketch being drawn on, a mesh in Edit Mode) stays
    active and selected, so the user's tool keeps working."""
    props = scene.whittle
    if not props.target_auto:
        return
    if view_layer is None:
        view_layer = bpy.context.view_layer if bpy.context.scene == scene else scene.view_layers[0]
    active = view_layer.objects.active
    held = active if active is not None and active.mode != "OBJECT" else None
    wanted = []
    for obj in (t.object for t in props.targets if eligible(t.object)):
        # An object linked a moment ago (a restore appends them) is not in
        # view_layer.objects until the view layer syncs, but can be selected.
        try:
            obj.select_set(True, view_layer=view_layer)
        except RuntimeError:
            continue
        wanted.append(obj)
    for obj in view_layer.objects:
        if obj not in wanted and obj != held and obj.select_get(view_layer=view_layer):
            obj.select_set(False, view_layer=view_layer)
    if held is None and view_layer.objects.active not in wanted:
        view_layer.objects.active = wanted[0] if wanted else None
