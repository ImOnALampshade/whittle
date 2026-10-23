# SPDX-License-Identifier: GPL-3.0-or-later
"""Enter sends from the prompt box; Shift+Enter adds a line.

Blender's multi-line text box ends editing on Enter and adds a line on
Shift+Enter, but has no hook for Enter itself: clicking elsewhere ends
editing too, and a property's update cannot tell the two apart. The box
keeps the Enter press to itself and lets the release through, while a
Shift+Enter (a new line) lets nothing through. So the composer fields'
update notes when one was confirmed, and a Window keymap item on the
release of Enter sends what was confirmed just before it."""

import time

import bpy

# How soon after a field is confirmed the release of Enter must follow.
WINDOW = 0.5

# Which operator sends each composer field.
SENDERS = {"prompt": "submit", "amend_text": "amend", "ask_answer": "answer"}

KEYS = ("RET", "NUMPAD_ENTER")

_confirmed: tuple[str, float] | None = None
_keymaps: list = []


def updater(name: str):
    """The update callback for the composer field `name`. Blank text
    never sends, which also keeps clearing a field from counting."""

    def update(props, _context) -> None:
        global _confirmed
        if getattr(props, name).strip():
            _confirmed = (name, time.monotonic())

    return update


def take_confirmed(now: float | None = None) -> str | None:
    """The field confirmed within WINDOW of `now`, once."""
    global _confirmed
    confirmed, _confirmed = _confirmed, None
    if confirmed is None:
        return None
    name, at = confirmed
    if (time.monotonic() if now is None else now) - at > WINDOW:
        return None
    return name


class WHITTLE_OT_enter_send(bpy.types.Operator):
    bl_idname = "whittle.enter_send"
    bl_label = "Send on Enter"
    bl_description = "Send the prompt box's text when Enter confirms it"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        name = take_confirmed()
        if name is None:
            return {"PASS_THROUGH"}
        op = getattr(bpy.ops.whittle, SENDERS[name])
        if not op.poll():
            # Sending is not possible right now (a comparison, say); the
            # text stays in the box and the button says why.
            return {"PASS_THROUGH"}
        op("EXEC_DEFAULT")
        return {"FINISHED"}


CLASSES = (WHITTLE_OT_enter_send,)


def register_keymap() -> None:
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        # Background Blender has no key configurations.
        return
    km = kc.keymaps.new(name="Window", space_type="EMPTY")
    for key in KEYS:
        _keymaps.append((km, km.keymap_items.new(WHITTLE_OT_enter_send.bl_idname, key, "RELEASE")))


def unregister_keymap() -> None:
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
