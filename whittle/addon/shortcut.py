# SPDX-License-Identifier: GPL-3.0-or-later
"""Shift+Alt+C: straight into typing a prompt, with no mouse.

Blender has no way to start editing a sidebar field from Python, so the
shortcut opens the Whittle sidebar (for the conversation) and, under the
pointer, a popup holding the composer's own field, already in edit mode,
as F2 does for renaming. Enter confirms the field and closes the popup on
its press, and enter.py's Enter handling sends it on the release, so it
sends exactly as Enter in the sidebar's box does; Escape closes the popup
and leaves the field as it was. While a turn runs the field is the
amendment, and while Claude asks, the answer."""

import bpy

from . import operators, turn

KEY = ("C", {"shift": True, "alt": True})
CATEGORY = "Whittle"
# A sidebar opened by the shortcut lists its tabs only once it has drawn;
# picking the Whittle tab is retried for this long.
TAB_RETRIES = 10
TAB_RETRY = 0.05

# Each composer field's popup title. Every field has the same placeholder,
# here and in the sidebar: the title (or the sidebar's question) says what
# the text is for.
FIELDS = {"prompt": "Ask Claude",
          "amend_text": "Amend the Running Turn",
          "ask_answer": "Answer Claude"}
PLACEHOLDER = "Ask Claude…"
# A dim line under the popup's field, cut to its width.
HINT = "Enter sends · End keeps your draft · long prompts: use the sidebar box"
POPUP_UNITS = 22

# The field the open popup types into, picked when the shortcut is
# pressed: a turn ending while typing would otherwise swap the field under
# the cursor.
_field: str | None = None
_keymaps: list = []


def field(ctl) -> str:
    """The composer field to type into: the answer while Claude asks, the
    amendment while a turn runs, else the prompt."""
    if operators.busy(ctl):
        return "ask_answer" if getattr(ctl, "question", None) is not None else "amend_text"
    return "prompt"


def find_view3d(context):
    """The 3D viewport the conversation shows in: the one under the
    pointer, else the largest in the window."""
    if context.area is not None and context.area.type == "VIEW_3D":
        return context.area
    screen = context.window.screen if context.window is not None else None
    areas = [a for a in screen.areas if a.type == "VIEW_3D"] if screen is not None else []
    return max(areas, key=lambda a: a.width * a.height, default=None)


def show_sidebar(area) -> None:
    """Opens the area's sidebar on the Whittle tab."""
    if area is None:
        return
    area.spaces.active.show_region_ui = True
    region = next((r for r in area.regions if r.type == "UI"), None)
    if region is None or _pick_tab(region):
        return
    # A sidebar that was hidden lists no tabs until it has drawn once.
    tries = iter(range(TAB_RETRIES))

    def retry():
        try:
            if _pick_tab(region) or next(tries, None) is None:
                return None
        except ReferenceError:
            # The area went away (a file load, a closed window).
            return None
        return TAB_RETRY

    bpy.app.timers.register(retry, first_interval=TAB_RETRY)


def _pick_tab(region) -> bool:
    if region.active_panel_category == CATEGORY:
        return True
    try:
        region.active_panel_category = CATEGORY
    except (AttributeError, TypeError, ValueError):
        # The region has not listed its tabs yet: no such value.
        return False
    region.tag_redraw()
    return region.active_panel_category == CATEGORY


class WHITTLE_PT_type_prompt(bpy.types.Panel):
    """The popup the shortcut opens: the composer's field, in edit mode."""
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Ask Claude"
    bl_ui_units_x = POPUP_UNITS

    def draw(self, context):
        name = _field or field(turn.current())
        layout = self.layout
        layout.label(text=FIELDS[name])
        # Only a one-line field takes the keyboard as a popup opens; the
        # multi-line box never does (docs/decisions.md).
        layout.activate_init = True
        layout.prop(context.scene.whittle, name, text="", placeholder=PLACEHOLDER)
        row = layout.row()
        row.active = False
        row.label(text=hint(context))


def hint(context) -> str:
    """HINT, fitted to the popup's width: as many of its parts as fit whole,
    so a font wider than Blender's own drops the last tips rather than
    cutting one."""
    from . import ui

    scale = (context.preferences.system.ui_scale if context.preferences else 1.0) or 1.0
    ctx = ui.Ctx(scene=None, hist=None, ctl=None, comparing=None, scale=scale)
    # The popup's border and the label's own padding.
    room = ctx.px(POPUP_UNITS) - ctx.px(1.5)
    parts = HINT.split(" · ")
    for n in range(len(parts), 0, -1):
        text = " · ".join(parts[:n])
        if ctx.measure(text) <= room:
            return text
    return ctx.fit(parts[0], room)


class WHITTLE_OT_type_prompt(bpy.types.Operator):
    bl_idname = "whittle.type_prompt"
    bl_label = "Ask Claude"
    bl_description = ("Open the Whittle sidebar and a prompt field under the pointer, ready to type: Enter "
                      "sends, Esc closes. While a turn runs it amends the turn, or answers Claude's question")

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.scene is not None

    def invoke(self, context, event):
        global _field
        _field = field(turn.current())
        show_sidebar(find_view3d(context))
        bpy.ops.wm.call_panel(name=WHITTLE_PT_type_prompt.__name__, keep_open=False)
        return {"FINISHED"}

    def execute(self, context):
        return self.invoke(context, None)


CLASSES = (WHITTLE_PT_type_prompt, WHITTLE_OT_type_prompt)


def register_keymap() -> None:
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        # Background Blender has no key configurations.
        return
    # The Window keymap, so it works over any editor and in every mode:
    # nothing in the default keymap uses Shift+Alt+C (docs/decisions.md).
    km = kc.keymaps.new(name="Window", space_type="EMPTY")
    key, mods = KEY
    _keymaps.append((km, km.keymap_items.new(WHITTLE_OT_type_prompt.bl_idname, key, "PRESS", **mods)))


def unregister_keymap() -> None:
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
