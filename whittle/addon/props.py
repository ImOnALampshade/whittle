# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-scene state: scene.whittle, and keeping a file's style guide path
naming the same guide through a first save, Save As and undo."""

import os
import uuid

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty

from .. import style
from . import enter, prefs, targets


class WhittleRef(bpy.types.PropertyGroup):
    path: StringProperty(name="Path", subtype="FILE_PATH", default="")
    pinned: BoolProperty(name="Pinned", default=False,
                         description="Send with every request instead of only the next one")


def _auto_changed(_props, context) -> None:
    # Turning Auto on takes the selection at once.
    from . import autotarget

    autotarget.sync(context.scene, context.view_layer)


def _target_poll(_self, obj) -> bool:
    return targets.eligible(obj)


class WhittleTarget(bpy.types.PropertyGroup):
    object: PointerProperty(name="Object", type=bpy.types.Object, poll=_target_poll)


# Per-file overrides of the preferences' defaults (design §10 guardrails):
# setting -> the custom property on scene.whittle that holds it, saved with the
# file. An unset field reads the preference, so it always shows what the next
# session gets; editing it sets the override, and reset_file_setting clears it.
# Every session setting can be overridden, in the preferences' order.
FILE_SETTINGS = {key: f"file_{key}" for key in prefs.SESSION_SETTINGS}

# The save under way: the file it started from, and each scene whose Style
# Notes it rewrote with the text from before (rebase_style_paths), and the
# approvals the new texts inherit once it is saved.
_rebased_from = ""
_rebased: list[tuple[bpy.types.Scene, str]] = []
_carried: set[str] = set()

# Where a // Style Notes counts from, for what an undo brings back. Undo leaves
# the file where it is but puts back text written from an earlier folder, so
# each text carries a stamp saying which: scene.whittle[STYLE_MOVE], a key of
# _moves, this session's Save As moves to a new folder and where each went. No
# stamp, or one from another session, means the folder before the first move.
# A stamp means nothing outside this session: a file is read from where it is.
# A first save that made a path relative is a move too, from nowhere: an undo
# then brings back the absolute text, which no stamp marks as set since.
STYLE_MOVE = "style_file_move"
_start_folder = ""
_moves: dict[str, str] = {}
_latest_move = ""
_first_save_moved = False


def _clean(key: str, value):
    """An integer setting kept inside its preference's bounds."""
    if key not in prefs.LIMITS:
        return value
    low, high = prefs.LIMITS[key]
    value = max(value, low)
    return value if high is None else min(value, high)


def file_settings(scene) -> dict:
    """The overrides the scene sets, by setting name. A value of the wrong
    type (a hand-edited file) counts as unset."""
    props = getattr(scene, "whittle", None) if scene is not None else None
    if props is None:
        return {}
    found = {}
    for key, store in FILE_SETTINGS.items():
        value = props.get(store)
        if type(value) is type(prefs.DEFAULTS[key]):
            found[key] = _clean(key, value)
    return found


def reset_file_setting(scene, key: str) -> None:
    """Clears the scene's override of a setting, so it reads the preference again."""
    props = scene.whittle
    if FILE_SETTINGS[key] in props:
        del props[FILE_SETTINGS[key]]


def rebase_style_paths(target: str) -> None:
    """Before a save (save_pre, where bpy.data.filepath is still the file
    being left): if it goes to another folder, every scene's // Style Notes is
    rewritten to name the same file from there, as Blender does for its own
    paths. The first save of a file has no folder to leave, and turns a path
    picked in it, which Blender stores absolute, into a // path instead: a
    path set absolute in a saved file was meant, and stays. Save As and Save
    Copy look the same here, so both write the new text and settle_style_paths
    takes it back for a copy. Written straight to the store: the property's
    update would read the new text from the old folder, as bpy.data.filepath
    has not moved yet, and save_post reads it once it has. The setter never
    runs, so the approval of what a text named moves to the new text here. A
    read walks a `..` up from a folder's real place, so the rewrite starts
    from there too, not from the symlink a file was saved through."""
    global _rebased_from
    _rebased_from = bpy.data.filepath
    _rebased.clear()
    _carried.clear()
    store = FILE_SETTINGS["style_file"]
    new_folder = _real_folder(target)
    old_folder = _real_folder(_rebased_from) if _rebased_from else ""
    for scene in bpy.data.scenes:
        path = file_settings(scene).get("style_file", "").strip()
        if scene.library is not None:
            continue
        rebased = _rewritten(path, old_folder, new_folder)
        if rebased != path:
            if not prefs.guide_held(path, per_file=True):
                _carried.add(prefs.guide_key(rebased, target))
            _rebased.append((scene, scene.whittle[store]))
            scene.whittle[store] = rebased


def _rewritten(path: str, old_folder: str, new_folder: str) -> str:
    """A Style Notes text as a save from old_folder (none: the first save) to
    new_folder leaves it."""
    if not old_folder:
        return style.relative_path(path, new_folder)
    return style.rebased_path(path, old_folder, new_folder) if path.startswith("//") else path


def settle_style_paths(saved: bool = True) -> None:
    """After a save or a failed one: if the open file stayed where it was,
    a copy was saved or nothing was, and its paths are back as they were.
    A failed Save As leaves bpy.data.filepath alone too. Otherwise the file
    moved, and the text rewritten says so. Whatever was saved, a copy too, was
    written with the new texts, so the approvals follow unless the save failed."""
    global _rebased_from, _start_folder, _first_save_moved
    left, _rebased_from = _rebased_from, ""
    if bpy.data.filepath == left:
        for scene, text in _rebased:
            scene.whittle[FILE_SETTINGS["style_file"]] = text
    elif not left:
        if _rebased:
            _start_folder = _real_folder(bpy.data.filepath)
            _first_save_moved = True
            _note_move()
    elif _real_folder(left) != _real_folder(bpy.data.filepath):
        if not _moves:
            _start_folder = _real_folder(left)
        _note_move()
    if saved:
        prefs.approve_keys(_carried)
        prefs.settle_unsaved_approvals()
    _rebased.clear()
    _carried.clear()


def _note_move() -> None:
    """The file is in a new folder: the scenes just rewritten count from it."""
    global _latest_move
    _latest_move = uuid.uuid4().hex
    _moves[_latest_move] = _real_folder(bpy.data.filepath)
    for scene, _text in _rebased:
        scene.whittle[STYLE_MOVE] = _latest_move


def follow_style_paths() -> None:
    """After an undo or redo: a // path from before a Save As would be counted
    from the new folder, where it can name another file with no warning, so
    it is rewritten to name what it named when it was written, and an absolute
    path from before the first save becomes the // path that save made of it.
    The new text is the one the save left, whose approval it carried, so none
    moves here. The steps themselves cannot hold this, as the rewrite makes
    none. Linked scenes are their own files' to rewrite."""
    if not _latest_move:
        return
    store = FILE_SETTINGS["style_file"]
    for scene in bpy.data.scenes:
        stamp = str(scene.whittle.get(STYLE_MOVE, ""))
        path = file_settings(scene).get("style_file", "").strip()
        if scene.library is not None or stamp == _latest_move:
            continue
        if path.startswith("//"):
            rewritten = style.rebased_path(path, _moves.get(stamp, _start_folder), _moves[_latest_move])
        elif _first_save_moved and stamp not in _moves:
            rewritten = style.relative_path(path, _moves[_latest_move])
            if rewritten == path:
                continue
        else:
            continue
        scene.whittle[store] = rewritten
        scene.whittle[STYLE_MOVE] = _latest_move


def forget_style_moves() -> None:
    """A file was loaded: what it holds counts from where it is, and no undo
    reaches back past this."""
    global _latest_move, _first_save_moved
    _latest_move = ""
    _first_save_moved = False
    _moves.clear()


def _real_folder(filepath: str) -> str:
    return os.path.realpath(os.path.dirname(filepath))


def _file_setting(key: str) -> dict:
    """get and set for a per-file setting's property."""
    def getter(props):
        found = file_settings(props.id_data).get(key)
        return found if found is not None else getattr(prefs.get(), key)

    def setter(props, value):
        props[FILE_SETTINGS[key]] = _clean(key, value)
        if key == "style_file":
            # Blender runs this for a set and not for a load, so what a
            # file brings with it stays unapproved. A script's set counts:
            # a script could read the file itself.
            prefs.approve_guide(value)
            if _latest_move:
                props[STYLE_MOVE] = _latest_move

    return {"get": getter, "set": setter}


def _style_file_changed(props, _context) -> None:
    # The popover redraws from what was read: it never reads the disk itself.
    prefs.read_style_guide(props.style_file)


def _file_description(key: str) -> str:
    return f"{prefs.DESCRIPTIONS[key]}. For this file; unset, it is the preferences' {prefs.LABELS[key]}"


class WhittleSceneProps(bpy.types.PropertyGroup):
    prompt: StringProperty(name="Prompt", default="", update=enter.updater("prompt"),
                           description="What to make of the sketch. Enter sends, Shift+Enter adds a "
                                       "line; Shift+Alt+C types here from anywhere. For Run Bundle "
                                       "it overrides the bundle's prompt when not empty")
    amend_text: StringProperty(name="Amend", default="", update=enter.updater("amend_text"),
                               description="A message for the running turn, sent with any strokes "
                                           "drawn since it started")
    refs: CollectionProperty(type=WhittleRef, name="References")
    ask_answer: StringProperty(name="Answer", default="", update=enter.updater("ask_answer"))
    targets: CollectionProperty(type=WhittleTarget, name="Targets")
    target_index: IntProperty(name="Target", default=0, min=0)
    target_collection: PointerProperty(
        name="Collection", type=bpy.types.Collection,
        description="Every object in this collection is a target too")
    # The history node the scene reflects. Kept on the scene so Blender's
    # undo rolls it back with the target; session.json follows it.
    history_node: StringProperty(name="History Node", default="", options={"HIDDEN"})
    # The chat history_node belongs to: an undo step from another chat
    # leaves the current chat's node alone. Empty until a chat is named here.
    chat: StringProperty(name="Chat", default="", options={"HIDDEN"})
    target_auto: BoolProperty(
        name="Auto", default=True, update=_auto_changed,
        description="Follow the selection: Claude works on the selected objects (or the active one). "
                    "Turn off to pick the objects by hand")
    # This file's overrides (FILE_SETTINGS); their tooltips are the
    # preferences' plus where an unset one comes from.
    poly_budget: IntProperty(
        name="Triangle Budget", min=prefs.MIN_POLY_BUDGET, **_file_setting("poly_budget"),
        description=_file_description("poly_budget"))
    self_check_rounds: IntProperty(
        name="Self-check Rounds", min=prefs.LIMITS["self_check_rounds"][0],
        max=prefs.LIMITS["self_check_rounds"][1], **_file_setting("self_check_rounds"),
        description=_file_description("self_check_rounds"))
    render_size: IntProperty(
        name="Render Size", min=prefs.LIMITS["render_size"][0], max=prefs.LIMITS["render_size"][1],
        **_file_setting("render_size"), description=_file_description("render_size"))
    style_file: StringProperty(
        name="Style Notes", subtype="FILE_PATH", options={"PATH_SUPPORTS_BLEND_RELATIVE"},
        update=_style_file_changed, **_file_setting("style_file"),
        description=_file_description("style_file"))


CLASSES = (WhittleRef, WhittleTarget, WhittleSceneProps)


def register_props():
    """Adds scene.whittle and the window manager's development and UI properties."""
    bpy.types.Scene.whittle = PointerProperty(type=WhittleSceneProps)
    # Development settings, on the window manager so no .blend ever carries
    # them: a fake script's steps run any Python, so one that came with a
    # file someone shared would run on Send.
    bpy.types.WindowManager.whittle_fake_script = StringProperty(
        name="Fake Script", subtype="FILE_PATH", default="", options={"SKIP_SAVE"},
        description="Play a scripted fake agent instead of Claude (development)")
    bpy.types.WindowManager.whittle_bundle_path = StringProperty(
        name="Bundle", subtype="DIR_PATH", default="", options={"SKIP_SAVE"},
        description="A request bundle folder to run (development)")
    # Whether the sketch strip's view list is open: UI state, never saved.
    bpy.types.WindowManager.whittle_show_views = BoolProperty(name="Views", default=False,
                                                              options={"SKIP_SAVE"})
    # Whether the sketch views show as markers in the viewport while
    # sketching (viewmarks.py): UI state, never saved.
    bpy.types.WindowManager.whittle_show_view_markers = BoolProperty(
        name="Show View Markers", default=True, options={"SKIP_SAVE"},
        description="While sketching, show a small camera in the viewport where each view was captured; "
                    "click one to go back to that view")
    # Whether the chat menu lists every chat, not only the latest ones.
    bpy.types.WindowManager.whittle_show_all_chats = BoolProperty(
        name="Show All Chats", default=False, options={"SKIP_SAVE"},
        description="List every chat in this file, not only the latest")


def unregister_props():
    """Removes what register_props added."""
    del bpy.types.WindowManager.whittle_bundle_path
    del bpy.types.WindowManager.whittle_fake_script
    del bpy.types.WindowManager.whittle_show_all_chats
    del bpy.types.WindowManager.whittle_show_views
    del bpy.types.WindowManager.whittle_show_view_markers
    del bpy.types.Scene.whittle
