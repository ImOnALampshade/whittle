# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-scene state: scene.whittle."""

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty, StringProperty

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
FILE_SETTINGS = {"poly_budget": "file_poly_budget", "style_notes": "file_style_notes"}


def _clean(key: str, value):
    return max(value, prefs.MIN_POLY_BUDGET) if key == "poly_budget" else value


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
    props = scene.whittle
    if FILE_SETTINGS[key] in props:
        del props[FILE_SETTINGS[key]]


def _file_setting(key: str) -> dict:
    """get and set for a per-file setting's property."""
    def getter(props):
        found = file_settings(props.id_data).get(key)
        return found if found is not None else getattr(prefs.get(), key)

    def setter(props, value):
        props[FILE_SETTINGS[key]] = _clean(key, value)

    return {"get": getter, "set": setter}


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
    poly_budget: IntProperty(
        name="Triangle Budget", min=prefs.MIN_POLY_BUDGET, **_file_setting("poly_budget"),
        description="Rough triangle budget for the whole target, for this file. Unset, it is the "
                    "preferences' Triangle Budget")
    style_notes: StringProperty(
        name="Style Notes", **_file_setting("style_notes"),
        description="Extra style guidance for the agent, for this file, e.g. 'chunky bevels'. "
                    "Unset, it is the preferences' Style Notes")


CLASSES = (WhittleRef, WhittleTarget, WhittleSceneProps)


def register_props():
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
    del bpy.types.WindowManager.whittle_bundle_path
    del bpy.types.WindowManager.whittle_fake_script
    del bpy.types.WindowManager.whittle_show_all_chats
    del bpy.types.WindowManager.whittle_show_views
    del bpy.types.WindowManager.whittle_show_view_markers
    del bpy.types.Scene.whittle
