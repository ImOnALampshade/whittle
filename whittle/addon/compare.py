# SPDX-License-Identifier: GPL-3.0-or-later
"""Comparing history nodes: an A/B toggle between the live scene and another
node, and the parent node shown as a wireframe ghost.

The toggle restores whole snapshots, so each side comes back exactly; the
ghost is an appended copy kept apart by name, collection and a marker
property, so nothing that matches targets by name or uid can pick it up."""

import logging
from pathlib import Path

import bpy

from . import history, snapshot
from .bundle import UID_PROP
from .targets import GHOST_PROP

log = logging.getLogger("whittle")

GHOST_COLLECTION = "Whittle Ghost"
GHOST_PREFIX = "Ghost · "
LIVE = "live"


def _base_name(name: str) -> str:
    # The append gives clashing names a numeric suffix; the ghost name drops it.
    match = snapshot._SUFFIX.match(name)
    return match.group(1) if match else name


def _manifest_uids(snap: snapshot.Snapshot) -> set[str]:
    return {entry["uid"] for entry in snap.manifest["objects"]}


class Compare:
    """Shows either the scene as it was when the comparison started ("live")
    or another node. Nothing here is an undo step until it ends."""

    def __init__(self, hist: history.History, other: str):
        self.history = hist
        self.base = hist.current
        self.other = other
        self.showing = LIVE
        self._live: snapshot.Snapshot | None = None
        self._other: snapshot.Snapshot | None = None
        # The uids showing the other node may remove objects by.
        self._removable: set[str] = set()
        # The target list when the comparison started, as (uid, name) pairs:
        # showing the other node can remove a target, and the copy appended
        # when live comes back is another object the list does not point at.
        self._targets: list[tuple[str | None, str]] = []

    @property
    def live_blend(self) -> Path:
        return self.history.session.compare_dir() / "live.blend"

    def start(self, scene) -> None:
        if not self.history.can_restore(self.other):
            raise RuntimeError(f"node {self.other} has no snapshot to compare")
        from . import targets

        self._other = snapshot.read(self.history.session.target_blend(self.other))
        self._removable = self.history.removable_uids(scene)
        # Everything showing the other node could replace or remove has to be
        # in the live snapshot, or toggling back would lose it: its objects,
        # and the materials and node groups it replaces by name, which some
        # object outside the snapshot may be all that uses now.
        snaps = [self._other]
        if self.base is not None and self.history.can_restore(self.base):
            snaps.append(snapshot.read(self.history.session.target_blend(self.base)))
        uids = self.history.tree.all_created_uids().union(*map(_manifest_uids, snaps))
        live = targets.resolve(scene) + snapshot.objects_by_uid(uids)
        live = list({o.as_pointer(): o for o in live}.values())
        names = {attr: {n for snap in snaps for n in snap.manifest["datablocks"][attr]}
                 for attr in snapshot.LOOSE}
        loose = [b for attr in snapshot.LOOSE for b in getattr(bpy.data, attr) if b.name in names[attr]]
        self._live = snapshot.write(self.live_blend, live, scene, loose=loose)
        if hasattr(scene, "whittle"):
            self._targets = [(t.object.get(UID_PROP), t.object.name)
                             for t in scene.whittle.targets if t.object is not None]
        try:
            self.show(self.other, scene)
        except Exception:
            # The scene may be half replaced: back to live if that works.
            # If it does not, the comparison stays, so Swap or Done can try
            # again and the live snapshot is not lost.
            self.showing = self.other
            try:
                self.show(LIVE, scene)
            except Exception:
                log.exception("could not go back to the live scene")
                raise
            self._forget()
            raise

    def _snap(self, side: str) -> snapshot.Snapshot:
        return self._live if side == LIVE else self._other

    def show(self, side: str, scene) -> None:
        if side == self.showing:
            return
        incoming, outgoing = self._snap(side), self._snap(self.showing)
        gone = _manifest_uids(outgoing) - _manifest_uids(incoming)
        if side != LIVE:
            # As a Restore would: only the agent's objects go. The user's
            # stay in the scene even when the node never had them.
            gone &= self._removable
        # Back to live, whatever the node brought in that the live scene
        # lacked goes: the live snapshot holds every object with one of the
        # node's uids, so those were all appended.
        snapshot.restore(incoming, remove_uids=gone, scene=scene)
        self.showing = side
        if side == LIVE:
            self._put_back_targets(scene)

    def _put_back_targets(self, scene) -> None:
        """The live side's target list, found by uid (the object of that uid
        with the recorded name first) and then by name."""
        if not hasattr(scene, "whittle"):
            return
        from . import targets

        found = []
        for uid, name in self._targets:
            holders = snapshot.objects_by_uid([uid]) if uid else []
            holders.sort(key=lambda o: o.name != name)
            obj = holders[0] if holders else bpy.data.objects.get(name)
            if obj is not None:
                found.append(obj)
        scene.whittle.targets.clear()
        scene.whittle.target_index = 0
        targets.add(scene, found)
        targets.select_list(scene)

    def toggle(self, scene) -> str:
        self.show(self.other if self.showing == LIVE else LIVE, scene)
        return self.showing

    def end(self, scene, *, keep: bool) -> None:
        """Keep: the node shown becomes current, as a Restore. Otherwise the
        live scene comes back and the current node stays. When that fails
        the comparison stays, with the live snapshot, so it can be tried
        again."""
        if keep:
            self.history.restore(self.other, scene)
        else:
            self.show(LIVE, scene)
            history.undo_push(f"{history.UNDO_PREFIX}: end comparison")
        self._forget()

    def _forget(self) -> None:
        """The comparison is over: its live snapshot goes."""
        global _active
        if _active is self:
            _active = None
        for path in (self.live_blend, self.live_blend.with_suffix(".json")):
            path.unlink(missing_ok=True)


_active: Compare | None = None


def active() -> Compare | None:
    return _active


def start(hist: history.History, node: str, scene) -> Compare:
    global _active
    if _active is not None:
        raise RuntimeError("a comparison is already running")
    comparison = Compare(hist, node)
    # Active from the start, so a start that cannot go back to live still
    # leaves a comparison to end.
    _active = comparison
    try:
        comparison.start(scene)
    except BaseException:
        if _active is comparison and comparison._live is None:
            _active = None
        raise
    return comparison


def reset() -> None:
    """Forgets the comparison without touching the scene (a file load)."""
    global _active
    _active = None


def forget() -> None:
    """Ends the comparison without touching the scene: an undo already put
    back a scene from before it."""
    if _active is not None:
        _active._forget()


# -- ghost ------------------------------------------------------------------------

def _ghost_collection(scene):
    collection = bpy.data.collections.get(GHOST_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(GHOST_COLLECTION)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def show_ghost(hist: history.History, node: str, scene) -> list:
    """Appends the node's target as wireframe copies in their own collection.
    Everything the append brings in is renamed with the ghost prefix."""
    clear_ghost()
    if not hist.can_restore(node):
        raise RuntimeError(f"node {node} has no snapshot to show")
    snap = snapshot.read(hist.session.target_blend(node))
    # Made before the append, so it is not taken for something the append
    # brought in.
    collection = _ghost_collection(scene)
    attrs = snapshot.id_collections()
    before = {attr: snapshot._ids(attr) for attr in attrs}
    libraries = {lib.as_pointer() for lib in bpy.data.libraries}
    with bpy.data.libraries.load(str(snap.blend), link=False) as (src, dst):
        dst.objects = [name for name in snap.names if name in src.objects]
    ghosts = list(dst.objects)
    for attr in attrs:
        for block in getattr(bpy.data, attr):
            if block.as_pointer() not in before[attr] and not block.name.startswith(GHOST_PREFIX):
                block.name = GHOST_PREFIX + _base_name(block.name)
    for obj in ghosts:
        collection.objects.link(obj)
        obj.display_type = "WIRE"
        obj.hide_select = True
        obj.hide_render = True
        obj.show_in_front = True
        if UID_PROP in obj:
            del obj[UID_PROP]
        obj[GHOST_PROP] = node
    for lib in list(bpy.data.libraries):
        if lib.as_pointer() not in libraries:
            bpy.data.libraries.remove(lib)
    return ghosts


def ghost_node() -> str | None:
    for obj in bpy.data.objects:
        if GHOST_PROP in obj:
            return str(obj[GHOST_PROP])
    return None


def clear_ghost() -> int:
    """Removes the ghost objects, then whatever the ghost append brought in
    that nothing uses now, and the ghost collection. Works from names and
    the marker alone, so it also cleans a file saved with a ghost showing."""
    ghosts = [o for o in bpy.data.objects if GHOST_PROP in o]
    for obj in ghosts:
        bpy.data.objects.remove(obj)
    changed = True
    while changed:
        changed = False
        for attr in snapshot.id_collections():
            collection = getattr(bpy.data, attr)
            if not hasattr(collection, "remove"):
                continue
            for block in list(collection):
                if block.name.startswith(GHOST_PREFIX) and block.users == 0:
                    collection.remove(block)
                    changed = True
    found = bpy.data.collections.get(GHOST_COLLECTION)
    if found is not None and not found.objects and not found.children:
        bpy.data.collections.remove(found)
    for lib in list(bpy.data.libraries):
        if Path(bpy.path.abspath(lib.filepath)).name == "target.blend" and lib.users == 0:
            bpy.data.libraries.remove(lib)
    return len(ghosts)
