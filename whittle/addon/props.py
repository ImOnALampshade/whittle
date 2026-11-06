# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-scene state: scene.whittle."""

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
# Notes it rewrote with the text from before (rebase_style_paths).
_rebased_from = ""
_rebased: list[tuple[bpy.types.Scene, str]] = []

# Where a // Style Notes counts from, for what an undo brings back. Undo leaves
# the file where it is but puts back text written from an earlier folder, so
# each text carries a stamp saying which: scene.whittle[STYLE_MOVE], a key of
# _moves, this session's Save As moves to a new folder and where each went. No
# stamp, or one from another session, means the folder before the first move.
# A stamp means nothing outside this session: a file is read from where it is.
STYLE_MOVE = "style_file_move"
_start_folder = ""
_moves: dict[str, str] = {}
_latest_move = ""


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
    paths. Save As and Save Copy look the same here, so both write the new
    text and settle_style_paths takes it back for a copy. Written straight to
    the store: the property's update reads the disk, which a save during a
    turn must not add to, and a file's own path is read at a Send or Read Now.
    A read walks a `..` up from a folder's real place, so the rewrite starts
    from there too, not from the symlink a file was saved through."""
    global _rebased_from
    _rebased_from = bpy.data.filepath
    _rebased.clear()
    if not _rebased_from:
        return
    store = FILE_SETTINGS["style_file"]
    old_folder, new_folder = _real_folder(_rebased_from), _real_folder(target)
    for scene in bpy.data.scenes:
        path = file_settings(scene).get("style_file", "").strip()
        if scene.library is None and path.startswith("//"):
            rebased = style.rebased_path(path, old_folder, new_folder)
            if rebased != path:
                _rebased.append((scene, scene.whittle[store]))
                scene.whittle[store] = rebased


def settle_style_paths() -> None:
    """After a save or a failed one: if the open file stayed where it was,
    a copy was saved or nothing was, and its // paths still start from here.
    A failed Save As leaves bpy.data.filepath alone too. Otherwise the file
    moved, and the text rewritten says so."""
    global _rebased_from, _start_folder, _latest_move
    left, _rebased_from = _rebased_from, ""
    if bpy.data.filepath == left:
        for scene, text in _rebased:
            scene.whittle[FILE_SETTINGS["style_file"]] = text
    elif left and _real_folder(left) != _real_folder(bpy.data.filepath):
        if not _moves:
            _start_folder = _real_folder(left)
        _latest_move = uuid.uuid4().hex
        _moves[_latest_move] = _real_folder(bpy.data.filepath)
        for scene, _text in _rebased:
            scene.whittle[STYLE_MOVE] = _latest_move
    _rebased.clear()


def follow_style_paths() -> None:
    """After an undo or redo: a // path from before a Save As would be counted
    from the new folder, where it can name another file with no warning, so
    it is rewritten to name what it named when it was written. The steps
    themselves cannot hold this, as the rewrite makes none. Linked scenes are
    their own files' to rewrite."""
    if not _latest_move:
        return
    store = FILE_SETTINGS["style_file"]
    for scene in bpy.data.scenes:
        stamp = str(scene.whittle.get(STYLE_MOVE, ""))
        path = file_settings(scene).get("style_file", "").strip()
        if scene.library is None and stamp != _latest_move and path.startswith("//"):
            scene.whittle[store] = style.rebased_path(path, _moves.get(stamp, _start_folder), _moves[_latest_move])
            scene.whittle[STYLE_MOVE] = _latest_move


def forget_style_moves() -> None:
    """A file was loaded: what it holds counts from where it is, and no undo
    reaches back past this."""
    global _latest_move
    _latest_move = ""
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
        if key == "style_file" and _latest_move:
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
