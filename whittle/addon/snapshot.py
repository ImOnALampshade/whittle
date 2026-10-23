# SPDX-License-Identifier: GPL-3.0-or-later
"""Snapshots of target objects: written with bpy.data.libraries.write beside a
target.json manifest, and restored by appending them back over the current
datablocks, so everything else in the file is left alone."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import bpy

from .. import formats
from .bundle import UID_PROP, ensure_uid
from .targets import GHOST_PROP

log = logging.getLogger("whittle")

# bpy.data collections an append never adds to, or that hold no datablocks of
# their own to pair or remove.
_NOT_APPENDED = frozenset({"libraries", "screens", "window_managers", "workspaces", "all_ids"})
# Shape keys belong to the mesh, curve or lattice that owns them and go with
# it; two of the same name are never the same datablock.
_OWNED = frozenset({"shape_keys"})
DATA_COLLECTIONS = {"MESH": "meshes", "CURVE": "curves", "SURFACE": "curves", "FONT": "curves",
                    "GREASEPENCIL": "grease_pencils", "LATTICE": "lattices", "META": "metaballs",
                    "CAMERA": "cameras", "LIGHT": "lights", "ARMATURE": "armatures"}
_SUFFIX = re.compile(r"^(.*)\.\d{3,}$")


def id_collections() -> tuple[str, ...]:
    """Every bpy.data collection an append can add a datablock to: an object
    can bring in collections, actions, worlds or texts as well as its data."""
    return tuple(p.identifier for p in bpy.data.bl_rna.properties
                 if p.type == "COLLECTION" and p.identifier not in _NOT_APPENDED)


@dataclass
class Snapshot:
    blend: Path
    manifest: dict

    @property
    def names(self) -> list[str]:
        return [o["name"] for o in self.manifest["objects"]]


# -- writing ------------------------------------------------------------------

def _gn_groups(obj) -> list:
    return [m.node_group for m in obj.modifiers if m.type == "NODES" and m.node_group is not None]


def _nested_groups(groups) -> list:
    """The node groups and every group nested inside them, each once."""
    seen, order, todo = set(), [], list(groups)
    while todo:
        group = todo.pop(0)
        if group is None or group.name in seen:
            continue
        seen.add(group.name)
        order.append(group)
        todo += [n.node_tree for n in group.nodes if n.type == "GROUP" and n.node_tree is not None]
    return order


def _collection_names(obj, scene) -> list[str]:
    # The scene's master collection has no datablock of its own; "" stands for it.
    return ["" if c == scene.collection else c.name for c in obj.users_collection]


LOOSE = ("materials", "node_groups")


def manifest_for(objects, scene=None, loose=()) -> dict:
    scene = scene or bpy.context.scene
    entries, materials, groups = [], [], []
    for obj in objects:
        slots = [s.material.name if s.material else None for s in obj.material_slots]
        gn = _gn_groups(obj)
        entries.append({
            "uid": ensure_uid(obj), "name": obj.name, "type": obj.type,
            "data_name": obj.data.name if obj.data is not None else None,
            "collections": _collection_names(obj, scene),
            "parent": obj.parent.name if obj.parent else None,
            "parent_uid": obj.parent.get(UID_PROP) if obj.parent else None,
            "materials": slots,
            "node_groups": [g.name for g in gn],
        })
        materials += [m for m in slots if m and m not in materials]
        groups += [g.name for g in _nested_groups(gn) if g.name not in groups]
    manifest = {"format": formats.TARGET_FORMAT, "version": formats.VERSION, "objects": entries,
                "datablocks": {"materials": materials, "node_groups": groups, "images": []}}
    used = {"materials": set(materials), "node_groups": set(groups)}
    extra = {attr: [b.name for b in loose if b.id_type == _ID_TYPES[attr] and b.name not in used[attr]]
             for attr in LOOSE}
    if any(extra.values()):
        manifest["loose"] = extra
    return manifest


_ID_TYPES = {"materials": "MATERIAL", "node_groups": "NODETREE"}


def write(blend: Path, objects, scene=None, *, loose=()) -> Snapshot:
    """Writes the objects (and everything they use) to blend, and the manifest
    beside it as <blend>.json. Loose materials and node groups are written
    too, so a restore puts them back even when no object here uses them."""
    blend = Path(blend)
    blend.parent.mkdir(parents=True, exist_ok=True)
    objects, loose = list(objects), list(loose)
    manifest = manifest_for(objects, scene, loose)
    bpy.data.libraries.write(str(blend), set(objects) | set(loose), path_remap="ABSOLUTE",
                             fake_user=False, compress=True)
    formats.write_target_manifest(blend.with_suffix(".json"), manifest)
    return Snapshot(blend, manifest)


def read(blend: Path) -> Snapshot:
    blend = Path(blend)
    if not blend.is_file():
        raise formats.FormatError(f"{blend}: missing")
    return Snapshot(blend, formats.read_target_manifest(blend.with_suffix(".json")))


# -- restoring ----------------------------------------------------------------

def _ids(attr: str) -> set[int]:
    return {block.as_pointer() for block in getattr(bpy.data, attr)}


def _original_name(block, names_in_file: set[str]) -> str | None:
    """The name a datablock had in the snapshot: its own name, or that name
    with the numeric suffix the append added on a clash."""
    if block.name in names_in_file:
        return block.name
    match = _SUFFIX.match(block.name)
    if match and match.group(1) in names_in_file:
        return match.group(1)
    return None


def objects_by_uid(uids) -> list:
    """The objects carrying one of these whittle_uids; never a ghost copy."""
    uids = set(uids)
    return [o for o in bpy.data.objects if o.get(UID_PROP) in uids and GHOST_PROP not in o]


def leave_edit_mode(objects) -> bool:
    """Leaves Edit Mode (or another mode) when it involves an object about to
    be replaced. A mode on some other object, such as the sketch being drawn
    on, is left alone."""
    obj = bpy.context.object
    if obj is None or obj.mode == "OBJECT":
        return False
    replaced = {o.as_pointer() for o in objects}
    involved = obj.as_pointer() in replaced or any(o.mode != "OBJECT" for o in objects)
    if not involved:
        return False
    wm = bpy.context.window_manager
    if wm is not None and wm.windows and bpy.context.window is None:
        with bpy.context.temp_override(window=wm.windows[0]):
            bpy.ops.object.mode_set(mode="OBJECT")
    else:
        bpy.ops.object.mode_set(mode="OBJECT")
    return True


def _resolve_collection(name: str, scene):
    if name == "":
        return scene.collection
    return bpy.data.collections.get(name)


def holders(entries, leaving=()) -> list:
    """The object each manifest entry stands for now, by whittle_uid, or None:
    a rename since the snapshot is followed, and an unrelated object that has
    taken the entry's name is never mistaken for it. A copy carries its
    original's uid, so of several objects with one uid the entry's namesake
    is taken first, then one not about to be removed, and none stands for two
    entries."""
    leaving = {o.as_pointer() for o in leaving}
    claimed: set[int] = set()
    found = []
    for entry in entries:
        matches = [o for o in objects_by_uid([entry["uid"]]) if o.as_pointer() not in claimed]
        matches.sort(key=lambda o: (o.name != entry["name"], o.as_pointer() in leaving))
        holder = matches[0] if matches else None
        if holder is not None:
            claimed.add(holder.as_pointer())
        found.append(holder)
    return found


def _alive(block) -> bool:
    try:
        block.name
    except ReferenceError:
        return False
    return True


def _take_name(block, name: str, attr: str) -> None:
    if block.name == name:
        return
    if attr != "objects":
        # Data that clashes with something else keeps the suffix the append
        # gave it; only the objects' names are the snapshot's to claim.
        block.name = name
        return
    holder = bpy.data.objects.get(name)
    # The scene object of that name is not the one being restored (that one
    # was found by uid and replaced): it moves aside rather than going.
    block.rename(name, mode="ALWAYS")
    if holder is not None and holder != block:
        log.info("renamed %r to %r to restore %r", name, holder.name, name)


def restore(snap: Snapshot, *, remove=(), remove_uids=(), scene=None) -> list[str]:
    """Puts the snapshot's objects, their data, materials and node groups back
    exactly as written. Each object replaces the scene object with its
    whittle_uid, whatever it is called now; materials and node groups (the
    objects' and the loose ones) replace whatever now has their names, so a
    shared material reverts for every object that uses it. Objects named in `remove`, or carrying a whittle_uid
    in `remove_uids`, (and not in the snapshot) are deleted with their unused
    data. Anything else in the file is left alone. Returns the restored
    object names."""
    scene = scene or bpy.context.scene
    manifest = snap.manifest
    entries = manifest["objects"]
    # Resolved now: the append brings in objects with the snapshot's uids.
    named = [o for o in (bpy.data.objects.get(n) for n in remove) if o is not None]
    matched = holders(entries, named)
    claimed = [h for h in matched if h is not None]
    doomed = list({o.as_pointer(): o for o in named + objects_by_uid(remove_uids)
                   if o not in claimed}.values())
    if leave_edit_mode(claimed + doomed):
        log.info("left Edit Mode to restore the snapshot")
    attrs = id_collections()
    before = {attr: _ids(attr) for attr in attrs}
    libraries = {lib.as_pointer() for lib in bpy.data.libraries}
    current = {attr: {b.name: b for b in getattr(bpy.data, attr)} for attr in attrs}

    with bpy.data.libraries.load(str(snap.blend), link=False) as (src, dst):
        in_file = {attr: set(getattr(src, attr)) for attr in attrs if hasattr(src, attr)}
        # Each entry in the file with the scene object it replaces.
        wanted = [(e, h) for e, h in zip(entries, matched) if e["name"] in in_file["objects"]]
        dst.objects = [e["name"] for e, _ in wanted]
        loose_names = manifest.get("loose", {})
        for attr in LOOSE:
            setattr(dst, attr, [n for n in loose_names.get(attr, []) if n in in_file.get(attr, ())])
    appended = list(dst.objects)
    loose = [(attr, block) for attr in LOOSE for block in getattr(dst, attr) if block is not None]

    # Appended datablock pointer -> (appended, recorded name, bpy.data
    # collection name, the datablock it replaces or None).
    revert: dict[int, tuple] = {}

    def pair(block, name, attr, old):
        if block is None or not name or block.as_pointer() in revert:
            return
        if old is not None and old.as_pointer() not in before[attr]:
            old = None
        revert[block.as_pointer()] = (block, name, attr, old)

    def by_name(name, attr):
        return current[attr].get(name)

    for (entry, holder), obj in zip(wanted, appended):
        pair(obj, entry["name"], "objects", holder)
        data_attr = DATA_COLLECTIONS.get(entry["type"])
        if data_attr and obj.data is not None:
            # The holder's data is what this replaces, so linked duplicates
            # follow. With no holder, only an unused block of the recorded
            # name is taken over: one in use belongs to something else.
            old = holder.data if holder is not None else None
            if old is None:
                unused = by_name(entry["data_name"], data_attr)
                old = unused if unused is not None and unused.users == 0 else None
            pair(obj.data, entry["data_name"], data_attr, old)
        for slot, name in zip(obj.material_slots, entry["materials"]):
            pair(slot.material, name, "materials", by_name(name, "materials"))
        for group, name in zip(_gn_groups(obj), entry["node_groups"]):
            pair(group, name, "node_groups", by_name(name, "node_groups"))
            for nested in _nested_groups([group])[1:]:
                original = _original_name(nested, in_file.get("node_groups", set()))
                if original in manifest["datablocks"]["node_groups"]:
                    pair(nested, original, "node_groups", by_name(original, "node_groups"))
    for attr, block in loose:
        # Only an existing block of the name is replaced: one nobody has
        # now is not brought back, and goes as unused.
        name = _original_name(block, in_file.get(attr, set()))
        if name is not None and by_name(name, attr) is not None:
            pair(block, name, attr, by_name(name, attr))

    for block, name, attr, old in revert.values():
        if old is not None and _alive(old) and old != block:
            old.user_remap(block)
            getattr(bpy.data, attr).remove(old)
        _take_name(block, name, attr)

    # Anything else the append brought in (an object a modifier points at, a
    # collection, an action, an image) belongs to the rest of the file: what
    # is there now wins.
    for attr in attrs:
        if attr in _OWNED:
            continue
        collection = getattr(bpy.data, attr)
        for block in list(collection):
            pointer = block.as_pointer()
            if pointer in before[attr] or pointer in revert:
                continue
            original = _original_name(block, in_file.get(attr, set()))
            existing = current[attr].get(original) if original else None
            if existing is not None and _alive(existing) and existing.as_pointer() in before[attr]:
                block.user_remap(existing)
                collection.remove(block)

    for (entry, _), obj in zip(wanted, appended):
        if obj.users_collection:
            continue
        # The object was gone, so nothing handed it its collections.
        targets = [c for c in (_resolve_collection(n, scene) for n in entry["collections"]) if c]
        for collection in targets or [scene.collection]:
            collection.objects.link(obj)

    for obj in doomed:
        if not _alive(obj):
            continue
        data, data_attr = obj.data, DATA_COLLECTIONS.get(obj.type)
        bpy.data.objects.remove(obj)
        if data is not None and data_attr is not None and data.users == 0:
            getattr(bpy.data, data_attr).remove(data)

    _remove_orphans(before)
    for lib in list(bpy.data.libraries):
        if lib.as_pointer() not in libraries:
            bpy.data.libraries.remove(lib)
    return [obj.name for obj in appended]


def _remove_orphans(before: dict[str, set[int]]) -> None:
    """Removes datablocks the append added that nothing uses any more."""
    changed = True
    while changed:
        changed = False
        for attr, known in before.items():
            collection = getattr(bpy.data, attr)
            if not hasattr(collection, "remove"):
                continue
            for block in list(collection):
                if block.as_pointer() not in known and block.users == 0:
                    collection.remove(block)
                    changed = True
