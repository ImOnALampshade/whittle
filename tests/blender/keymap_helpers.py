# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender's default keymap, for checking Whittle's keys against it, and a
fake key configuration that records what the add-on registers.

Background Blender has no key configurations, so the default keymap is
generated from its source, as Blender itself does. Modal maps only apply
while their own operator runs, and it has the keyboard then, so they are
left out."""

import os
import runpy
from types import SimpleNamespace

import bpy

MODIFIERS = ("shift", "alt", "ctrl", "oskey")


def default_keymaps():
    """(name, args, content) of every keymap Blender 5.2 builds by default."""
    path = os.path.join(bpy.utils.system_resource("SCRIPTS"), "presets", "keyconfig", "keymap_data",
                        "blender_default.py")
    data = runpy.run_path(path)
    return list(data["generate_keymaps"](data["Params"]()))


def clashes(key: str, mods: dict, keymaps=None) -> list[str]:
    """'keymap: operator' for each non-modal default item on key with exactly
    these modifiers (or any)."""
    found = []
    for name, args, content in keymaps if keymaps is not None else default_keymaps():
        if args.get("modal"):
            continue
        for idname, event, _props in content["items"]:
            if event is None or event.get("type") != key:
                continue
            if event.get("any") or all(bool(event.get(m)) == bool(mods.get(m)) for m in MODIFIERS):
                found.append(f"{name}: {idname}")
    return found


def fake_keyconfig():
    """(window manager, keymaps made as [(name, space_type)], items made as
    [(idname, key, value, mods)]) for a register_keymap to run against."""
    items, names = [], []
    keymap = SimpleNamespace(keymap_items=SimpleNamespace(
        new=lambda idname, key, value, **mods: items.append((idname, key, value, mods)) or items[-1],
        remove=items.remove))
    keyconfig = SimpleNamespace(keymaps=SimpleNamespace(
        new=lambda name, space_type: names.append((name, space_type)) or keymap))
    return SimpleNamespace(keyconfigs=SimpleNamespace(addon=keyconfig)), names, items
