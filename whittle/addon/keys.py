# SPDX-License-Identifier: GPL-3.0-or-later
"""Default keys for sketching: toggle Sketch mode, the next stroke type,
Capture View and Send, so a tablet's express keys can be mapped to them.

They are add-on items in the 3D View keymap, which applies in every mode
over the viewport, Grease Pencil Draw Mode included, and they are listed and
rebindable in Preferences → Keymap (3D View → 3D View (Global)). All share
Shift+Alt, like Shift+Alt+C, on keys Blender 5.2's default keymap leaves
free outside modal maps (docs/decisions.md)."""

import bpy

KEYMAP = ("3D View", "VIEW_3D")
MODS = {"shift": True, "alt": True}
KEYS = (
    ("whittle.sketch_toggle", "D"),       # D for draw
    ("whittle.next_stroke_type", "N"),    # N for next
    ("whittle.capture_view", "V"),        # V for view
    ("whittle.submit", "RET"),            # Enter sends, as in the prompt box
)

_keymaps: list = []


def register_keymap() -> None:
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        # Background Blender has no key configurations.
        return
    name, space_type = KEYMAP
    km = kc.keymaps.new(name=name, space_type=space_type)
    for idname, key in KEYS:
        _keymaps.append((km, km.keymap_items.new(idname, key, "PRESS", **MODS)))


def unregister_keymap() -> None:
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
