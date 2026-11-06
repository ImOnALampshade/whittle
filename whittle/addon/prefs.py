# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on preferences, with defaults when the add-on is not registered, and
which style guides this install may read and send."""

import logging
import os
from types import SimpleNamespace

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from .. import style
from ..models import DEFAULT_MODEL

log = logging.getLogger("whittle")

PACKAGE = __package__.rpartition(".")[0]

DEFAULTS = {
    "api_key": "",
    "model": DEFAULT_MODEL,
    "agent_python": "",
    "venv_dir": "",
    "self_check_rounds": 3,
    "render_size": 512,
    "poly_budget": 2000,
    "style_file": "",
    "store_chats": True,
    "usage_data": False,
}
MIN_POLY_BUDGET = 10
# The integer settings' bounds (min, max; None: unbounded), shared with the
# per-file overrides on the scene (props.py).
LIMITS = {"poly_budget": (MIN_POLY_BUDGET, None), "self_check_rounds": (0, 10), "render_size": (64, 1024)}
# The settings a session starts with (session_settings), in the order the
# Defaults box and the popover's For This File show them.
SESSION_SETTINGS = ("poly_budget", "self_check_rounds", "render_size", "style_file")
# Their names and tooltips, shared with the per-file fields.
LABELS = {"poly_budget": "Triangle Budget", "self_check_rounds": "Self-check Rounds", "render_size": "Render Size",
          "style_file": "Style Notes"}
DESCRIPTIONS = {
    "self_check_rounds": "How many fix rounds the agent may spend after its renders",
    "render_size": "Pixel size of the agent's self-check renders",
    "poly_budget": "Rough triangle budget for the whole target",
    "style_file": "A .md or .txt style guide for the agent, which can import others with @path lines, "
                  "so many files can share it. // is relative to the .blend. Empty: the agent chooses",
}
# What the last reads of the Style Notes paths found (read_style_guide): a
# few are enough, the file's and the preferences'.
_guides: dict[tuple[str, str], style.Guide] = {}
MAX_GUIDES_KEPT = 8
# How many files, and how many problems, a Style Notes field lists: a bad
# guide can name thousands, and the list has to stay readable.
GUIDE_ROWS = 10
# The guides this install approved, with the user folder they came from: draw
# code asks, so the record is read once and when a file loads. A // path set
# while the file has no folder is approved once the first save gives it one.
_approved: tuple[str | None, set[str]] | None = None
_approved_unsaved: set[str] = set()
HELD_NOTE = "Not sent until you approve it in the sidebar."
ABSOLUTE_GUIDE = "This path is absolute, so it will not travel with the file."
LOG_LINES = 8
# What the Preferences' main region keeps from its width for a line in one
# of Whittle's boxes: the region's margins, the box's border and the icon.
LINE_MARGIN = 96
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


def _style_file_changed(p, _context):
    # Runs when the path is set and not when the preferences load.
    approve_guide(p.style_file)
    read_style_guide(p.style_file)


def _environment_changed(_self, _context):
    """Another environment may be ready: the next start looks, and asks for
    a setup again if it is not."""
    from . import turn

    ctl = turn.current()
    if ctl is not None:
        ctl.process.clear_setup()


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
        update=_environment_changed,
        description="Where the agent's private Python environment lives; empty means the "
                    "extension's own user folder")
    agent_python: StringProperty(
        name="Agent Python", subtype="FILE_PATH", default=DEFAULTS["agent_python"],
        update=_environment_changed,
        description="Development override for the Python that runs the agent")
    self_check_rounds: IntProperty(name="Self-check Rounds", default=DEFAULTS["self_check_rounds"],
                                   min=LIMITS["self_check_rounds"][0], max=LIMITS["self_check_rounds"][1],
                                   description=DESCRIPTIONS["self_check_rounds"])
    render_size: IntProperty(name="Render Size", default=DEFAULTS["render_size"],
                             min=LIMITS["render_size"][0], max=LIMITS["render_size"][1],
                             description=DESCRIPTIONS["render_size"])
    poly_budget: IntProperty(name="Triangle Budget", default=DEFAULTS["poly_budget"], min=MIN_POLY_BUDGET,
                             description=DESCRIPTIONS["poly_budget"])
    style_file: StringProperty(name="Style Notes", subtype="FILE_PATH", default=DEFAULTS["style_file"],
                               options={"PATH_SUPPORTS_BLEND_RELATIVE"}, update=_style_file_changed,
                               description=DESCRIPTIONS["style_file"])
    store_chats: BoolProperty(
        name="Save Chats in the .blend", default=DEFAULTS["store_chats"],
        description="Store every chat inside the .blend when it is saved, so it travels with the file: "
                    "prompts, Claude's replies and code, reference images and renders. Off: chats stay "
                    "in this computer's cache only, and files saved from now on carry none")

    usage_data: BoolProperty(
        name="Send Claude CLI usage data", default=DEFAULTS["usage_data"],
        description="Let the bundled Claude CLI send Anthropic its own usage telemetry and error "
                    "reports. Off: it sends only the turns themselves "
                    "(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC). An idle agent restarts with the change "
                    "at the next turn")

    def draw(self, context):
        from . import setup

        layout = self.layout
        box = layout.box()
        box.label(text="Claude", icon="USER")
        box.prop(self, "api_key")
        # The line saying where the key comes from has a row of its own, so it
        # is never cut off; the link goes under it, at the right.
        _, source = api_key()
        if source == "environment":
            box.label(text=f"Using {ENV_KEY} from Blender's environment.", icon="INFO")
        elif source is None:
            box.label(text="Whittle needs an Anthropic API key to run Claude.", icon="INFO")
        else:
            box.label(text="Usage is billed to the key's Anthropic Console account.", icon="INFO")
        row = box.row()
        row.alignment = "RIGHT"
        row.operator("wm.url_open", text="Get an API Key", icon="URL").url = KEYS_URL
        box.prop(self, "model", text="Model for New Chats")
        box.prop(self, "usage_data")
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
        box.prop(self, "style_file")
        draw_style_guide(box, self.style_file, lambda text: wrap_status(text, *_line_room()),
                         held=guide_held(self.style_file, per_file=False))

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
    # The status has rows of its own, wrapped to the window, so a long
    # folder or agent path in it is never cut off.
    text, icon = setup.describe()
    col = layout.column(align=True)
    for i, line in enumerate(wrap_status(text, *_line_room())):
        col.label(text=line, icon=icon if i == 0 else "BLANK1")
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


def draw_style_guide(layout, path: str, wrap, held: bool = False) -> None:
    """Under a Style Notes field, from the last read (style_guide): the files
    being sent, then what went wrong, in lines of their own so a warning
    needs no tooltip. wrap breaks a text into lines for the layout. A held
    guide waits for the user's approval, so no turn will read it."""
    if not path.strip():
        return
    guide = style_guide(path)
    if held or guide is None:
        col = layout.column(align=True)
        col.active = False
        col.label(text=HELD_NOTE if held else "Read at the next turn.", icon="BLANK1")
    if guide is None:
        layout.operator("whittle.style_guide_read", icon="FILE_REFRESH").path = path
        return
    draw_guide_read(layout, guide, wrap, "Would be sent:" if held else "Sent with each turn:")


def draw_guide_read(layout, guide: style.Guide, wrap, title: str) -> None:
    """What a read of a guide found: its files under title, then its problems."""
    if guide.files:
        col = layout.column(align=True)
        heading = col.column(align=True)
        heading.active = False
        heading.label(text=title, icon="BLANK1")
        for name in guide.names()[:GUIDE_ROWS]:
            for i, line in enumerate(wrap(name)):
                col.label(text=line, icon="FILE_TEXT" if i == 0 else "BLANK1")
        _draw_more(col, len(guide.files), "files")
    if guide.problems:
        col = layout.column(align=True)
        for problem in guide.problems[:GUIDE_ROWS]:
            for i, line in enumerate(wrap(problem)):
                col.label(text=line, icon="ERROR" if i == 0 else "BLANK1")
        _draw_more(col, len(guide.problems), "problems")


def _draw_more(layout, count: int, what: str) -> None:
    if count > GUIDE_ROWS:
        layout.label(text=f"and {count - GUIDE_ROWS} more {what}", icon="BLANK1")


def _line_room():
    """The width a line in one of Whittle's boxes has in the region being
    drawn, and how to measure text in the UI font; no width (no wrapping)
    outside a drawn region."""
    import blf

    region = getattr(bpy.context, "region", None)
    scale = bpy.context.preferences.system.ui_scale or 1.0
    if region is None or not region.width:
        return None, None
    points = bpy.context.preferences.ui_styles[0].widget.points * scale

    def measure(text: str) -> float:
        blf.size(0, points)
        return blf.dimensions(0, text)[0]

    return region.width - LINE_MARGIN * scale, measure


def wrap_status(text: str, width: float | None, measure) -> list[str]:
    """text in lines no wider than width, broken at spaces; a word too long
    for a line, such as a path, is broken after its last path separator
    that fits (else where it must). No width: one line."""
    if not width:
        return [text]

    def fitting(head: str, word: str) -> int:
        """How many leading characters of word fit after head (none, or at
        least one when head is empty)."""
        lo, hi = 0 if head else 1, len(word)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if measure(head + word[:mid]) <= width:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def folder_end(word: str, n: int) -> int:
        """Where to cut word within its first n characters: after its last
        path separator there, else 0."""
        return max(word.rfind("/", 0, n), word.rfind("\\", 0, n)) + 1

    out, line = [], ""
    for word in text.split(" "):
        candidate = f"{line} {word}" if line else word
        if measure(candidate) <= width:
            line = candidate
            continue
        if line and measure(word) > width:
            # A path too long for a line of its own starts on this one.
            n = folder_end(word, fitting(line + " ", word))
            if n > 1:
                line, word = f"{line} {word[:n]}", word[n:]
        if line:
            out.append(line)
        while len(word) > 1 and measure(word) > width:
            n = fitting("", word)
            n = folder_end(word, n) if folder_end(word, n) > 1 else n
            out.append(word[:n])
            word = word[n:]
        line = word
    out.append(line)
    return out


def get():
    """A copy of the preferences as a namespace, or DEFAULTS when the add-on is not
    registered, so callers need not care which. Setting a field on it changes nothing."""
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


def read_style_guide(path: str) -> style.Guide:
    """Reads the style guide a Style Notes field names, for style_guide to
    give out. // needs a saved file to be relative to."""
    path = path.strip()
    if not path:
        guide = style.Guide()
    elif path.startswith("//") and not bpy.data.filepath:
        guide = style.Guide(problems=(f"{path} is relative to the .blend: save the file to use it.",))
    else:
        guide = style.load_guide(bpy.path.abspath(style.portable_path(path)))
    key = _guide_key(path)
    _guides.pop(key, None)
    _guides[key] = guide
    while len(_guides) > MAX_GUIDES_KEPT:
        del _guides[next(iter(_guides))]
    return guide


def style_guide(path: str) -> style.Guide | None:
    """What the last read of this path found, if there was one: never reads
    the disk, so draw code can ask."""
    return _guides.get(_guide_key(path.strip()))


def _guide_key(path: str) -> tuple[str, str]:
    # A // path means another file in another .blend's folder.
    return path, bpy.data.filepath


def refresh_style_guides(scene=None) -> None:
    """Reads the guide the next session would send, and the preferences' own
    for their Defaults box. Runs before each turn and when the path may have
    changed, so an edited guide reaches the next turn; never from a redraw,
    and never a guide waiting for the user's approval."""
    wanted = (_style_path(scene), (get().style_file, False))
    for path in {path for path, per_file in wanted if not guide_held(path, per_file=per_file)}:
        read_style_guide(path)


def _style_path(scene=None) -> tuple[str, bool]:
    """The Style Notes path a session of this scene gets, and whether it is
    the file's own rather than the preferences'."""
    from . import props

    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    found = props.file_settings(scene).get("style_file")
    return (get().style_file, False) if found is None else (found, True)


def _resolved(path: str, blend: str) -> str:
    return "" if path.startswith("//") and not blend else \
        bpy.path.abspath(style.portable_path(path), start=os.path.dirname(blend))


def guide_key(path: str, blend: str | None = None) -> str:
    """What this install's approval of a path is kept under, with // counted
    from blend, by default the open file. Nothing for a path that cannot be
    read as it stands: load_guide refuses it, and there is nothing to approve.
    Only strings, so asking whether a path is approved reaches nothing."""
    return style.guide_key(_resolved(path.strip(), bpy.data.filepath if blend is None else blend))


def guide_location(path: str) -> str:
    """Where a path leads from the open file, for the user to read."""
    return style.absolute_path(_resolved(path.strip(), bpy.data.filepath))


def _approved_keys() -> set[str]:
    global _approved
    from . import paths

    # The variable and not the folder itself: this runs from redraws.
    folder = os.environ.get("WHITTLE_USER_DIR")
    if _approved is None or _approved[0] != folder:
        try:
            _approved = (folder, style.read_approved(paths.user_dir()))
        except OSError as exc:
            log.warning("cannot read the approved style guides: %s", exc)
            _approved = (folder, set())
    return _approved[1]


def forget_approvals() -> None:
    """A file was loaded: the record is read again at the next question, so
    what another Blender approved counts here too."""
    global _approved
    _approved = None
    _approved_unsaved.clear()


def approve_keys(keys) -> bool:
    """Adds to the guides this install approved, and to its record if it can:
    they count until Blender closes either way. Returns whether the record has
    them. What another Blender added since this one read it stays."""
    global _approved
    from . import paths

    keys = set(keys) - {""}
    known = _approved_keys()
    if keys <= known:
        return True
    _approved = (_approved[0], known | keys)
    try:
        folder = paths.user_dir()
        _approved = (_approved[0], _approved[1] | style.read_approved(folder))
        style.write_approved(folder, _approved[1])
    except OSError as exc:
        log.warning("cannot keep the approved style guides: %s", exc)
        return False
    return True


def approve_guide(path: str) -> bool:
    """This install may read and send the guide at path, here and in any file
    that leads to it. For what the user did: their Use This Guide, or their
    setting a Style Notes field. Returns whether that was recorded."""
    path = path.strip()
    if path.startswith("//") and not bpy.data.filepath:
        _approved_unsaved.add(path)
        return True
    return approve_keys({guide_key(path)})


def settle_unsaved_approvals() -> None:
    """After a save: a // path set in the unsaved file names a guide now."""
    if bpy.data.filepath:
        approve_keys({guide_key(path) for path in _approved_unsaved})
        _approved_unsaved.clear()


def guide_held(path: str, *, per_file: bool) -> bool:
    """Whether a path waits for the user to approve it before anything reads
    it. A file's own path does, and a // one in the preferences, since the
    open file decides where that leads, unless this install approved where it
    leads. The rest of the preferences' are the user's own, and so is a
    file's path to the guide they name. Never touches the disk: this decides
    whether anything may."""
    path = path.strip()
    if not per_file and not path.startswith("//"):
        return False
    key = guide_key(path)
    if not key or key in _approved_keys():
        return False
    own = get().style_file.strip()
    return own.startswith("//") or key != guide_key(own)


def held_guide(scene=None) -> str:
    """The path the next turn from this scene would send and may not until the
    user answers; empty if there is none. Fit for a redraw."""
    path, per_file = _style_path(scene)
    return path.strip() if guide_held(path, per_file=per_file) else ""


def absolute_guide_warning(scene) -> str:
    """The line for a saved file whose own guide path names this machine's
    folders; empty otherwise. A string check: a redraw draws it."""
    from . import props

    found = props.file_settings(scene).get("style_file", "").strip()
    return ABSOLUTE_GUIDE if bpy.data.filepath and style.is_absolute(found) else ""


def read_own_style_guide() -> None:
    """The one read when a file opens: the preferences' path, which is the
    user's own. Opening a file is no act of the user's on what it stores, and
    that path could name a network share, so the file's own is read at a
    Send, a Read Now or a save. A // path counts as the file's: the file decides
    where it leads."""
    path = get().style_file
    if not path.strip().startswith("//"):
        read_style_guide(path)


def session_values(scene=None) -> dict:
    """The session settings as set, the style guide as a path: the
    preferences, then the scene's per-file overrides (props.file_settings).
    The scene defaults to the context's, so they follow the open file. Never
    reads the disk."""
    from . import props

    p = get()
    settings = {key: getattr(p, key) for key in SESSION_SETTINGS}
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    settings.update(props.file_settings(scene))
    return settings


def session_settings(scene=None) -> dict:
    """The settings a session starts with: session_values and the text of
    the style guide they point at, as last read. The text is here, not only
    the path, so a guide that changed on disk changes the settings and
    restarts the agent like any other change. A path with no read yet is read
    now: not read is not the same as no guide. So this is for sending, not
    for drawing. A guide waiting for the user's approval gives nothing, Read
    Now's text included, whichever route got here."""
    settings = session_values(scene)
    if held_guide(scene):
        guide = style.Guide()
    else:
        guide = style_guide(settings["style_file"]) or read_style_guide(settings["style_file"])
    settings["style_guide"] = guide.text
    settings["style_incomplete"] = bool(guide.problems)
    return settings


CLASSES = (WhittlePreferences,)
