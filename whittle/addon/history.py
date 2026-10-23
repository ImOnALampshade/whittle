# SPDX-License-Identifier: GPL-3.0-or-later
"""The history tree on the Blender side: a snapshot of the target per node,
restoring and branching, and session.json kept in step with the scene.

One History per session folder. Every change is saved at once, so a new
controller (a Blender restart) picks the tree up from disk."""

import logging
import shutil
import time
from pathlib import Path

import bpy

from .. import formats, tree
from . import bundle, render, sketch, snapshot, targets, views
from . import refs as references

log = logging.getLogger("whittle")

UNDO_PREFIX = "Whittle"
THUMB_SIZE = 128
ROOT = formats.node_id(0)

objects_by_uid = snapshot.objects_by_uid


def undo_push(message: str) -> None:
    """One undo step for the scene as it is now. Undo needs a window, so
    background Blender has none."""
    wm = bpy.context.window_manager
    if wm is None or not wm.windows:
        return
    try:
        with bpy.context.temp_override(window=wm.windows[0]):
            bpy.ops.ed.undo_push(message=message)
    except RuntimeError as exc:
        log.warning("undo push failed: %s", exc)


def thumbnail(objects, out: Path, view: formats.View | None, scene) -> Path | None:
    """A small square shaded render of just these objects, filling the frame:
    seen from the side the view looked from, or from three-quarters. The
    view's own camera is not used, since the user may have sketched from far
    away or zoomed in on a detail. None when there is nothing to show or the
    render fails."""
    objects = [o for o in objects if o.name in scene.objects]
    if not objects:
        return None
    if view is not None:
        spec = render.frame_camera(objects, direction=-views.eye_and_forward(view)[1])
    else:
        spec = render.frame_camera(objects)
    try:
        render.render(scene, spec, "shaded", THUMB_SIZE, out, aspect=1.0, only=objects)
    except Exception:
        log.exception("thumbnail render failed")
        return None
    return out


def _alive(objects) -> list:
    out, seen = [], set()
    for obj in objects:
        try:
            pointer = obj.as_pointer()
            obj.name
        except ReferenceError:
            continue
        if pointer not in seen:
            seen.add(pointer)
            out.append(obj)
    return out


def _own_uids(created) -> None:
    """A copy carries its original's whittle_uid; an object the agent made
    gets one of its own, so restoring matches every object to itself."""
    made = {o.as_pointer() for o in created}
    seen: set[str] = set()
    for obj in created:
        uid = obj.get(bundle.UID_PROP)
        if not uid:
            continue
        shared = uid in seen or any(o.as_pointer() not in made for o in objects_by_uid([uid]))
        if shared:
            del obj[bundle.UID_PROP]
        else:
            seen.add(uid)


def _mirror(scene, node: str, chat: str = "") -> None:
    # scene.whittle.history_node is saved in Blender's undo steps, so undo
    # rolls the current node back with the scene; sync_from_scene reads it.
    # scene.whittle.chat names the chat the node belongs to.
    if scene is not None and hasattr(scene, "whittle"):
        try:
            scene.whittle.history_node = node
            scene.whittle.chat = chat
        except (AttributeError, ReferenceError):
            pass


def chat_id(session: formats.SessionDir) -> str:
    """The chat a session folder is (chats/<id>/), or "" for a folder of its own."""
    root = Path(session.root)
    return root.name if root.parent.name == "chats" else ""


class History:
    def __init__(self, session: formats.SessionDir):
        self.session = session
        self.chat = chat_id(session)
        self.tree: tree.Tree | None = None
        # Why session.json could not be read, when it could not.
        self.error: str | None = None

    # -- persistence ----------------------------------------------------------

    def load(self) -> None:
        path = self.session.session_path()
        self.tree, self.error = None, None
        if not path.is_file():
            return
        try:
            self.tree, recovered = tree.read_session(path)
        except formats.FormatError as exc:
            log.error("cannot read the history: %s", exc)
            self.error = str(exc)
            return
        if recovered:
            log.warning("turns %s did not finish before Blender closed", ", ".join(recovered))
            self.save()

    def save(self) -> None:
        if self.tree is not None:
            tree.write_session(self.session.session_path(), self.tree)

    @property
    def current(self) -> str | None:
        return self.tree.current if self.tree is not None else None

    def node(self, node_id: str) -> tree.Node:
        if self.tree is None:
            raise tree.TreeError("there is no history yet")
        return self.tree.node(node_id)

    # -- nodes ------------------------------------------------------------------

    def ensure_root(self, objects, scene, *, label: str = tree.ROOT_LABEL) -> str:
        """Node 0, the target as it was before the first turn, written the
        first time the session folder runs a turn (or by a start point)."""
        if self.tree is not None:
            return self.tree.root
        path = self.session.session_path()
        if self.error is not None and path.exists():
            # Kept for a person to look at; a fresh tree starts beside it.
            aside = path.with_name(f"session.json.bad-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.move(path, aside)
            log.warning("unreadable history moved to %s", aside)
        fresh = tree.Tree.new(ROOT, label=label)
        objects = _alive(objects)
        ok = self._write_snapshot(ROOT, objects, scene, None)
        fresh.finish(ROOT, snapshot=ok)
        self.tree, self.error = fresh, None
        _mirror(scene, ROOT, self.chat)
        self.save()
        return ROOT

    def start(self, objects, scene, *, label: str = tree.ROOT_LABEL) -> str:
        """A start point: node 0 becomes these objects as they are now. Until
        the first turn the start can be taken again; after it, node 0 is
        what every turn grew from, so it stays."""
        if self.tree is None:
            return self.ensure_root(objects, scene, label=label)
        root = self.tree.node(self.tree.root)
        if self.tree.visible_children(root.id):
            raise tree.TreeError("the history already has turns, so its start cannot change")
        # A blank start renders no thumbnail; the old one must not stay.
        self.session.thumb_path(root.id).unlink(missing_ok=True)
        root.snapshot = self._write_snapshot(root.id, _alive(objects), scene, None)
        root.label = label
        self.tree.current = root.id
        _mirror(scene, root.id, self.chat)
        self.save()
        return root.id

    def begin(self, node: str, prompt: str, *, continued_session: str | None = None) -> tree.Node:
        """A running node under the current one. A resubmit of the same node
        keeps it where it is. continued_session is the SDK session the turn
        carries on, when it is known before the turn ends."""
        if self.tree is None:
            raise tree.TreeError("the history has no root yet")
        parent = self.tree.node(node).parent if node in self.tree.nodes else self.tree.current
        added = self.tree.add(node, parent, prompt=prompt)
        added.continued_session = continued_session
        self.save()
        return added

    def forget_session(self, node: str | None) -> None:
        if self.tree is None or node not in self.tree.nodes:
            return
        self.tree.node(node).continued_session = None
        self.save()

    def discard(self, node: str) -> None:
        if self.tree is None or node not in self.tree.nodes:
            return
        self.tree.discard(node)
        self.save()

    def finish(self, node: str, objects, data: dict, *, scene, created=(), restored: bool = False,
               kept_partial: bool = False, view: formats.View | None = None) -> tree.Node:
        """The end of a turn: the target's snapshot and thumbnail, the turn's
        outcome, and the node becomes current. A snapshot that fails leaves
        the node without one (it cannot be restored) rather than raising."""
        created = _alive(created)
        _own_uids(created)
        uids = [bundle.ensure_uid(o) for o in created]
        ok = self._write_snapshot(node, _alive(objects), scene, view)
        if restored or data.get("interrupted"):
            status = "interrupted"
        elif data.get("is_error"):
            status = "failed"
        else:
            status = "complete"
        finished = self.tree.finish(
            node, status=status, agent_session_id=data.get("session_id"),
            agent_message_uuid=data.get("message_uuid"), cost_usd=data.get("cost_usd"),
            num_turns=data.get("num_turns"), duration_ms=data.get("duration_ms"),
            kept_partial=kept_partial, restored=restored, snapshot=ok, created_uids=uids)
        self.tree.current = node
        _mirror(scene, node, self.chat)
        self.save()
        return finished

    def fold(self, node: str, data: dict) -> tree.Node:
        """The end of a failed turn that changed nothing: no snapshot, and the
        node folds into its parent, which stays current. The node is kept so
        its SDK session still counts (a submit from the parent forks the
        conversation before the failure) and its folder is never reused."""
        folded = self.tree.finish(
            node, status="failed", folded=True, agent_session_id=data.get("session_id"),
            agent_message_uuid=data.get("message_uuid"), cost_usd=data.get("cost_usd"),
            num_turns=data.get("num_turns"), duration_ms=data.get("duration_ms"), snapshot=False)
        if self.tree.current == node:
            self.tree.current = folded.parent
        self.save()
        return folded

    def _write_snapshot(self, node: str, objects, scene, view) -> bool:
        try:
            snapshot.write(self.session.target_blend(node), objects, scene)
        except Exception:
            log.exception("snapshot of %s failed", node)
            return False
        thumbnail(objects, self.session.thumb_path(node), view, scene)
        return True

    # -- restore and branch -----------------------------------------------------

    def can_restore(self, node: str) -> bool:
        if self.tree is None or node not in self.tree.nodes:
            return False
        return self.tree.node(node).snapshot and self.session.target_blend(node).is_file()

    def recorded_names(self) -> dict[str, set[str]]:
        """Every name each whittle_uid had in a node's snapshot."""
        names: dict[str, set[str]] = {}
        if self.tree is None:
            return names
        for node in self.tree.nodes:
            path = self.session.target_blend(node).with_suffix(".json")
            if not path.is_file():
                continue
            try:
                manifest = formats.read_target_manifest(path)
            except formats.FormatError as exc:
                log.warning("skipping the manifest of %s: %s", node, exc)
                continue
            for entry in manifest["objects"]:
                names.setdefault(entry["uid"], set()).add(entry["name"])
        return names

    def separate_copies(self, scene) -> set[str]:
        """Duplicating an object copies its whittle_uid, so the user's copy of
        something the agent made would be taken for it and removed with it.
        Of the objects sharing an agent-made uid, the one the history knows
        (by a recorded name, then by being a target) keeps the uid and the
        rest get their own, which makes them the user's. Returns the uids
        whose original cannot be told from its copies: nothing carrying them
        may be removed."""
        if self.tree is None:
            return set()
        shared = {}
        for obj in objects_by_uid(self.tree.all_created_uids()):
            shared.setdefault(obj[bundle.UID_PROP], []).append(obj)
        shared = {uid: objs for uid, objs in shared.items() if len(objs) > 1}
        if not shared:
            return set()
        recorded = self.recorded_names()
        picked = set()
        if hasattr(scene, "whittle"):
            picked = {t.object.as_pointer() for t in scene.whittle.targets if t.object is not None}
        unsure = set()
        for uid, objs in shared.items():
            rank = {o.as_pointer(): (o.name in recorded.get(uid, ()), o.as_pointer() in picked)
                    for o in objs}
            best = max(rank.values())
            originals = [o for o in objs if rank[o.as_pointer()] == best]
            if best == (False, False) or len(originals) > 1:
                log.warning("cannot tell which of %s the agent made; none will be removed",
                            ", ".join(o.name for o in objs))
                unsure.add(uid)
                continue
            for obj in objs:
                if obj is not originals[0]:
                    del obj[bundle.UID_PROP]
                    bundle.ensure_uid(obj)
                    log.info("%r is a copy of %r and now the user's own", obj.name, originals[0].name)
        return unsure

    def removable_uids(self, scene) -> set[str]:
        """The uids a restore may remove objects by: the agent's objects, each
        told apart from the user's copies of it."""
        if self.tree is None:
            return set()
        return self.tree.all_created_uids() - self.separate_copies(scene)

    def restore(self, node: str, scene, *, undo: bool = True) -> list[str]:
        """Puts the scene's target back as it was at the node: its objects come
        back, and objects the agent made that the node lacks are removed. The
        user's own objects are never deleted. The node becomes current."""
        if not self.can_restore(node):
            raise RuntimeError(f"node {node} has no snapshot to restore")
        snap = snapshot.read(self.session.target_blend(node))
        keep = {entry["uid"] for entry in snap.manifest["objects"]}
        names = snapshot.restore(snap, remove_uids=self.removable_uids(scene) - keep, scene=scene)
        restored = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
        if hasattr(scene, "whittle"):
            scene.whittle.targets.clear()
            scene.whittle.target_index = 0
            targets.add(scene, restored)
            targets.select_list(scene)
        self.tree.current = node
        _mirror(scene, node, self.chat)
        self.save()
        if undo:
            undo_push(f"{UNDO_PREFIX}: restore {node}")
        return names

    def branch(self, node: str, scene) -> str:
        """Another take on a node's turn: its parent is restored, and the
        node's prompt, sketch strokes, views and references come back, so the
        next submit makes a sibling of it. A completed turn cleared its
        strokes and references when it finished, so they are read from its
        request. All of it is one undo step. Returns the parent."""
        found = self.node(node)
        if found.parent is None:
            raise RuntimeError("the start of the history has no turn to take again")
        self.restore(found.parent, scene, undo=False)
        if hasattr(scene, "whittle"):
            scene.whittle.prompt = found.prompt
            self._replay_request(node, scene)
        undo_push(f"{UNDO_PREFIX}: edit & resend {node}")
        return found.parent

    def _replay_request(self, node: str, scene) -> None:
        """The node's request strokes go back on the sketch as pending ones,
        after any the user has drawn since; its references are attached again."""
        request_dir = self.session.request_dir(node)
        if not request_dir.is_dir():
            return
        try:
            sent = formats.read_bundle(request_dir)
        except formats.FormatError as exc:
            log.warning("cannot bring back the sketch of %s: %s", node, exc)
            return
        obj = sketch.find_sketch_object()
        if obj is not None:
            # A turn that failed or was interrupted kept its strokes, stamped
            # with its number: the request's copies replace them.
            sketch.remove_turn_strokes(obj, formats.node_number(node))
        if sent.strokes:
            obj = sketch.ensure_sketch_layers(scene)
            ids = views.merge_views(obj.data, [sent.views[i] for i in sorted(sent.views)])
            for stroke in sent.strokes:
                stroke.view = ids.get(stroke.view, stroke.view)
            sketch.add_strokes(scene, sent.strokes)
        references.add_back(scene, [request_dir / ref for ref in sent.request.refs])


# -- the history the UI shows ---------------------------------------------------

_cache: dict[Path, History] = {}


def get(root, *, reload: bool = False) -> History:
    """The History of a session folder, read from disk once (or again with
    reload)."""
    key = Path(root).resolve()
    found = _cache.get(key)
    if found is None or reload:
        found = History(formats.SessionDir(root))
        found.load()
        _cache[key] = found
    return found


def active() -> History | None:
    """The running controller's history, else the current chat's, if it has one."""
    from . import chats, turn

    ctl = turn.current()
    if ctl is not None:
        return ctl.history
    folder = chats.current_folder()
    if folder is None or not (folder / "session.json").is_file():
        return None
    return get(folder)


def invalidate() -> None:
    """Forgets every cached tree; a file load may point at another session."""
    _cache.clear()


def sync_from_scene(scene=None, *, reason: str = "undo") -> str | None:
    """After undo, redo or a file load: the current node follows the scene's
    mirror of it, since the scene is what the next turn starts from. Returns
    the current node."""
    scene = scene or bpy.context.scene
    if scene is None or not hasattr(scene, "whittle"):
        return None
    found = active()
    if found is None or found.tree is None:
        return None
    if scene.whittle.chat not in ("", found.chat):
        # An undo step from another chat rolls the scene back, but chats
        # are not undone: the current chat stays where it is.
        return found.tree.current
    # An empty mirror is a scene from before the first turn, which is what
    # the root recorded.
    node = scene.whittle.history_node or found.tree.root
    if node == found.tree.current:
        return node
    if node not in found.tree.nodes:
        log.warning("the scene shows history node %s, which the history does not have; "
                    "keeping %s as current", node, found.tree.current)
        return found.tree.current
    if reason == "load":
        log.info("the reopened file shows history node %s, not %s; following the file",
                 node, found.tree.current)
    found.tree.current = node
    found.save()
    return node
