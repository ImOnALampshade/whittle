# SPDX-License-Identifier: GPL-3.0-or-later
"""The model menu on the Blender side: the list it offers (the agent's last
report, kept in the user folder, over the bundled list), which model the
current chat runs on and at what effort, the composer's model button and
the menu itself.
whittle/models.py reads the ids and keeps the cache (architecture §15)."""

import logging
import time

import bpy
from bpy.props import StringProperty

from .. import chats as chat_store
from .. import models as store
from . import chats, paths, prefs

log = logging.getLogger("whittle")

CUSTOM_HINT = "Any model id, e.g. claude-opus-4-1"
SOURCES = {"api": "Listed by the Models API", "cli": "Listed by Claude"}
BUILT_IN = "Built-in list until Claude starts"
BUSY = "The model can change once this turn ends"
MENU_DESCRIPTION = "Model: the Claude model this chat runs on, from its next turn"

# The catalog, read again only when the cache file (or its place) changes.
_loaded: tuple[tuple, store.Catalog] | None = None


def cache_path():
    return paths.user_dir() / store.CACHE_NAME


def catalog() -> store.Catalog:
    global _loaded
    path = cache_path()
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        stamp = (str(path), None)
    if _loaded is None or _loaded[0] != stamp:
        _loaded = (stamp, store.load(path))
    return _loaded[1]


def received(data: dict) -> None:
    """The agent's report of the models the account offers: kept for the
    menu, and for the next Blender session."""
    ids = [m for m in data.get("models") or [] if isinstance(m, str)]
    if not ids:
        return
    try:
        store.write_cache(cache_path(), ids, str(data.get("source") or "cli"))
    except OSError as exc:
        log.warning("could not keep the model list: %s", exc)


def default_model() -> str:
    """The add-on's Model preference: what new chats start with."""
    return (prefs.get().model or "").strip() or store.DEFAULT_MODEL


def chat_model(found=None) -> str:
    """The model the current chat runs on: its own, else the default."""
    found = chats.get() if found is None else found
    model = found.model(found.current) if found is not None else None
    return model or default_model()


def set_chat_model(model: str) -> str:
    """The current chat runs on model from its next turn; a file without a
    chat yet gets one. Returns the chat."""
    found = chats.get(create=True)
    if found is None:
        raise RuntimeError("the current chat cannot be opened")
    chat = found.ensure_current()
    found.set_model(chat, model)
    return chat


def chat_effort(found=None) -> str:
    """The effort the current chat runs at: its own, else the default."""
    found = chats.get() if found is None else found
    return store.effort_level(found.effort(found.current) if found is not None else None)


def set_chat_effort(effort: str) -> str:
    """The current chat runs at effort from its next turn; a file without a
    chat yet gets one. Returns the chat."""
    if effort not in store.EFFORTS:
        raise ValueError(f"effort must be one of {', '.join(store.EFFORTS)}")
    found = chats.get(create=True)
    if found is None:
        raise RuntimeError("the current chat cannot be opened")
    chat = found.ensure_current()
    found.set_effort(chat, effort)
    return chat


def blocker(ctl) -> str | None:
    """Why the model cannot change now: never during a turn."""
    from . import operators

    if operators.busy(ctl) or getattr(ctl, "question", None) is not None:
        return BUSY
    return None


def source_line(found: store.Catalog, now: float | None = None) -> str:
    if not found.source:
        return BUILT_IN
    now = time.time() if now is None else now
    label = SOURCES.get(found.source, "Listed by Claude")
    return f"{label} {chat_store.age_label(now - found.fetched)}"


# -- drawing -------------------------------------------------------------------------

def button_text(model_id: str) -> str:
    """What the composer's button says: the short name, "Opus 5.5"."""
    return store.short_name(model_id)


OLDER_LABEL = "Older Models"


def _item(layout, model: store.Model, current: str) -> None:
    layout.operator("whittle.chat_model", text=model.name,
                    icon="CHECKMARK" if model.id == current else "BLANK1").model = model.id


EFFORT_LABEL = "Effort"
EFFORT_HINTS = {
    "low": "Least thinking: fastest and cheapest, for small, clear edits",
    "medium": "Some thinking: quicker turns for routine edits",
    "high": "The most thinking Whittle offers: best for multi-step edits (the default)",
}


def draw_efforts(layout, effort: str) -> None:
    """The Effort section: a dim heading and the levels, ✓ on the chat's."""
    row = layout.row()
    row.active = False
    row.label(text=EFFORT_LABEL, icon="BLANK1")
    for level in store.EFFORTS:
        layout.operator("whittle.chat_effort", text=level.title(),
                        icon="CHECKMARK" if level == effort else "BLANK1").effort = level


def draw_models(layout, current: str, found: store.Catalog, default: str, now: float | None = None,
                effort: str = store.DEFAULT_EFFORT) -> None:
    """The model menu: the newest of each family with ✓ on the chat's, the
    Older Models submenu, another id by hand, the chat's effort, and making
    the chat's model the default for new chats."""
    latest = found.latest()
    if current not in {m.id for m in latest}:
        # An older or custom model the chat runs on stays in sight, first.
        model = found.find(current)
        if model is not None:
            _item(layout, model, current)
        else:
            layout.operator("whittle.chat_model", text=current, icon="CHECKMARK").model = current
        layout.separator()
    for model in latest:
        _item(layout, model, current)
    layout.separator()
    layout.menu("WHITTLE_MT_models_older", text=OLDER_LABEL, icon="BLANK1")
    row = layout.row()
    row.operator_context = "INVOKE_DEFAULT"
    row.operator("whittle.chat_model", text="Other Model…", icon="BLANK1").model = ""
    layout.separator()
    draw_efforts(layout, effort)
    if current != default:
        layout.separator()
        layout.operator("whittle.default_model", text=f"Use {store.short_name(current)} for New Chats",
                        icon="BLANK1").model = current
    layout.separator()
    row = layout.row()
    row.active = False
    row.label(text=source_line(found, now), icon="BLANK1")


def draw_older_models(layout, current: str, found: store.Catalog) -> None:
    """Older Models: one column per family, newest first."""
    older = found.older()
    if not older:
        row = layout.row()
        row.active = False
        row.label(text="No older models")
        return
    row = layout.row()
    for family, models in older.items():
        col = row.column()
        sub = col.row()
        sub.active = False
        sub.label(text=family.title())
        for model in models:
            _item(col, model, current)


class WHITTLE_MT_models(bpy.types.Menu):
    bl_idname = "WHITTLE_MT_models"
    bl_label = "Model"
    bl_description = MENU_DESCRIPTION

    def draw(self, context):
        draw_models(self.layout, chat_model(), catalog(), default_model(), effort=chat_effort())


class WHITTLE_MT_models_older(bpy.types.Menu):
    bl_idname = "WHITTLE_MT_models_older"
    # No title: a menu's title rule spans only its first column, and the
    # family names head the columns.
    bl_label = ""
    bl_description = "Earlier versions of each model"

    def draw(self, context):
        draw_older_models(self.layout, chat_model(), catalog())


class WHITTLE_OT_chat_model(bpy.types.Operator):
    bl_idname = "whittle.chat_model"
    bl_label = "Model"
    bl_description = "Run this chat on this model from its next turn"
    bl_options = {"INTERNAL"}

    model: StringProperty(name="Model ID", default="", description=CUSTOM_HINT, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        from . import turn

        reason = blocker(turn.current())
        if reason:
            cls.poll_message_set(reason)
        return reason is None

    @classmethod
    def description(cls, context, properties):
        if not properties.model:
            return "Run this chat on another model, by its id"
        model = store.parse(properties.model)
        named = f"{model.full_name} ({model.id})" if model is not None else properties.model
        return f"{named}\n{cls.bl_description}"

    def invoke(self, context, event):
        if not self.model.strip():
            self.model = chat_model()
            return context.window_manager.invoke_props_dialog(self, title="Other Model",
                                                              confirm_text="Use Model")
        return self.execute(context)

    def execute(self, context):
        model = self.model.strip()
        if not model:
            return {"CANCELLED"}
        try:
            set_chat_model(model)
        except (OSError, RuntimeError) as exc:
            self.report({"ERROR"}, f"Could not change the model: {exc}")
            return {"CANCELLED"}
        from .bridge import redraw_view3d

        redraw_view3d()
        return {"FINISHED"}


class WHITTLE_OT_chat_effort(bpy.types.Operator):
    bl_idname = "whittle.chat_effort"
    bl_label = "Effort"
    bl_description = "How much Claude thinks in this chat, from its next turn"
    bl_options = {"INTERNAL"}

    effort: StringProperty(name="Effort", default=store.DEFAULT_EFFORT, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        from . import turn

        reason = blocker(turn.current())
        if reason:
            cls.poll_message_set(reason)
        return reason is None

    @classmethod
    def description(cls, context, properties):
        hint = EFFORT_HINTS.get(properties.effort)
        return f"{hint}\n{cls.bl_description}" if hint else cls.bl_description

    def execute(self, context):
        try:
            set_chat_effort(self.effort)
        except (OSError, RuntimeError, ValueError) as exc:
            self.report({"ERROR"}, f"Could not change the effort: {exc}")
            return {"CANCELLED"}
        from .bridge import redraw_view3d

        redraw_view3d()
        return {"FINISHED"}


class WHITTLE_OT_default_model(bpy.types.Operator):
    bl_idname = "whittle.default_model"
    bl_label = "Use for New Chats"
    bl_description = "Make this the model new chats start with (the add-on's Model preference)"
    bl_options = {"INTERNAL"}

    model: StringProperty(default="", options={"SKIP_SAVE"})

    def execute(self, context):
        addon = context.preferences.addons.get(prefs.PACKAGE)
        if addon is None or addon.preferences is None or not self.model.strip():
            return {"CANCELLED"}
        addon.preferences.model = self.model.strip()
        context.preferences.is_dirty = True
        return {"FINISHED"}


CLASSES = (WHITTLE_MT_models, WHITTLE_MT_models_older, WHITTLE_OT_chat_model, WHITTLE_OT_chat_effort,
           WHITTLE_OT_default_model)
