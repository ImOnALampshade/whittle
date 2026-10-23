# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on preferences, with defaults when the add-on is not registered."""

import os
from types import SimpleNamespace

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from ..models import DEFAULT_MODEL

PACKAGE = __package__.rpartition(".")[0]

DEFAULTS = {
    "api_key": "",
    "model": DEFAULT_MODEL,
    "agent_python": "",
    "venv_dir": "",
    "self_check_rounds": 3,
    "render_size": 512,
    "poly_budget": 2000,
    "style_notes": "",
    "store_chats": True,
}
MIN_POLY_BUDGET = 10
LOG_LINES = 8
# Where to make an API key; the attention box and the preferences link here.
KEYS_URL = "https://platform.claude.com/settings/keys"
ENV_KEY = "ANTHROPIC_API_KEY"


def _model_search(_self, _context, edit_text):
    """The model field offers the model menu's list, newest of each family
    first; any other id can still be typed, so a newer model needs no
    extension update."""
    from . import models

    found = models.catalog()
    ids = [m.id for m in found.latest()] + [m.id for older in found.older().values() for m in older]
    text = (edit_text or "").strip().lower()
    return [m for m in ids if text in m]


def _key_changed(_self, _context):
    """A key typed while the sidebar asks for one clears the ask."""
    from . import turn

    ctl = turn.current()
    if ctl is not None:
        ctl.process.clear_key()


class WhittlePreferences(bpy.types.AddonPreferences):
    bl_idname = PACKAGE

    api_key: StringProperty(
        name="Anthropic API Key", subtype="PASSWORD", default=DEFAULTS["api_key"],
        update=_key_changed,
        description="The key Claude runs with, billed to its Anthropic Console account. Empty: "
                    "ANTHROPIC_API_KEY from Blender's environment, if set")
    model: StringProperty(
        name="Model", default=DEFAULTS["model"], search=_model_search, search_options={"SUGGESTION"},
        description="The Claude model new chats start with; each chat can change its own with the "
                    "model button beside Send")
    venv_dir: StringProperty(
        name="Environment Folder", subtype="DIR_PATH", default=DEFAULTS["venv_dir"],
        description="Where the agent's private Python environment lives; empty means the "
                    "extension's own user folder")
    agent_python: StringProperty(
        name="Agent Python", subtype="FILE_PATH", default=DEFAULTS["agent_python"],
        description="Development override for the Python that runs the agent")
    self_check_rounds: IntProperty(name="Self-check Rounds", default=DEFAULTS["self_check_rounds"],
                                   min=0, max=10,
                                   description="How many fix rounds the agent may spend after its renders")
    render_size: IntProperty(name="Render Size", default=DEFAULTS["render_size"], min=64, max=1024,
                             description="Pixel size of the agent's self-check renders")
    poly_budget: IntProperty(name="Triangle Budget", default=DEFAULTS["poly_budget"], min=MIN_POLY_BUDGET,
                             description="Rough triangle budget for the whole target")
    style_notes: StringProperty(name="Style Notes", default=DEFAULTS["style_notes"],
                                description="Extra style guidance for the agent, e.g. 'chunky bevels'")
    store_chats: BoolProperty(
        name="Save Chats in the .blend", default=DEFAULTS["store_chats"],
        description="Store every chat inside the .blend when it is saved, so it travels with the file: "
                    "prompts, Claude's replies and code, reference images and renders. Off: chats stay "
                    "in this computer's cache only, and files saved from now on carry none")

    def draw(self, context):
        from . import setup

        layout = self.layout
        box = layout.box()
        box.label(text="Claude", icon="USER")
        box.prop(self, "api_key")
        _, source = api_key()
        row = box.row()
        if source == "environment":
            row.label(text=f"Using {ENV_KEY} from Blender's environment.", icon="INFO")
        elif source is None:
            row.label(text="Whittle needs an Anthropic API key to run Claude.", icon="INFO")
        else:
            row.label(text="Usage is billed to the key's Anthropic Console account.", icon="INFO")
        row.operator("wm.url_open", text="Get an API Key", icon="URL").url = KEYS_URL
        box.prop(self, "model", text="Model for New Chats")
        col = box.column()
        col.active = False
        col.label(text="Powered by Claude. Whittle is not made by or affiliated with Anthropic.",
                  icon="BLANK1")

        box = layout.box()
        box.label(text="Agent Environment", icon="CONSOLE")
        draw_environment(box, self, setup)

        box = layout.box()
        box.label(text="Defaults", icon="PREFERENCES")
        row = box.row()
        row.prop(self, "poly_budget")
        row.prop(self, "self_check_rounds")
        row.prop(self, "render_size")
        box.prop(self, "style_notes")

        box = layout.box()
        box.label(text="Files", icon="FILE_BLEND")
        box.prop(self, "store_chats")

        box = layout.box()
        box.label(text="Development", icon="SCRIPT")
        box.prop(self, "agent_python")


def draw_environment(layout, p, setup) -> None:
    """The venv folder, its state, the install buttons and the log of the
    last setup. A plain function so tests can draw it."""
    layout.prop(p, "venv_dir")
    text, icon = setup.describe()
    layout.label(text=text, icon=icon)
    running = setup.current()
    row = layout.row(align=True)
    if running is not None and running.running:
        row.operator("whittle.venv_cancel", icon="CANCEL")
    else:
        row.operator_context = "INVOKE_DEFAULT"
        row.operator("whittle.venv_install", icon="IMPORT")
        row.operator("whittle.venv_install", text="Reinstall", icon="FILE_REFRESH").reinstall = True
    if running is not None:
        col = layout.column(align=True)
        for line in running.log_tail(LOG_LINES):
            col.label(text=line[:160])


def get():
    addon = bpy.context.preferences.addons.get(PACKAGE)
    if addon is None or addon.preferences is None:
        return SimpleNamespace(**DEFAULTS)
    p = addon.preferences
    return SimpleNamespace(**{key: getattr(p, key) for key in DEFAULTS})


def api_key() -> tuple[str, str | None]:
    """The key the agent runs with and where it came from: the preference
    first ("preferences"), else ANTHROPIC_API_KEY in Blender's environment
    ("environment"), else ("", None). A key typed in the preferences is the
    user's explicit choice, so it wins over one inherited from a shell."""
    typed = (get().api_key or "").strip()
    if typed:
        return typed, "preferences"
    inherited = os.environ.get(ENV_KEY, "").strip()
    if inherited:
        return inherited, "environment"
    return "", None


def session_settings(scene=None) -> dict:
    """The settings a session starts with: the preferences, then the scene's
    per-file overrides (props.file_settings). The scene defaults to the
    context's, so the settings follow the open file."""
    from . import props

    p = get()
    settings = {"self_check_rounds": p.self_check_rounds, "poly_budget": p.poly_budget,
                "style_notes": p.style_notes, "render_size": p.render_size}
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    settings.update(props.file_settings(scene))
    return settings


CLASSES = (WhittlePreferences,)
