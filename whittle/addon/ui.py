# SPDX-License-Identifier: GPL-3.0-or-later
"""The Whittle tab in the 3D viewport sidebar, laid out as a chat: what Claude
is working on, the conversation of the current branch, the sketch button
(its tools only while sketching) and a prompt box. History lives in each
turn's menu, a branch switcher under a turn with siblings, and a popover with
the whole tree. docs/ui.md is the spec.

Drawing is done by plain functions of (layout, ...) so tests can drive them
with a recording layout; they never write to Blender data."""

import json
import time
import zlib
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from pathlib import Path

import blf
import bpy
from bpy.props import IntProperty, StringProperty

from .. import chats as chat_store
from .. import formats, markdown, tree as trees
from . import chats, compare, conversation, history, models, operators, paths, prefs, previews, setup, sketch, start
from . import shortcut, targets, turn, views
from .process import AgentState
from .stream import tool_detail

# The header shows activity only; everything else about the agent is in its
# popover, and a problem the user must act on is a box in the panel body.
BUSY_STATES = (AgentState.STARTING, AgentState.BUSY, AgentState.STOPPING)
TOOL_ICONS = {"pending": "SORTTIME", "ok": "CHECKMARK", "error": "CANCEL"}
NODE_ICONS = {"interrupted": "PAUSE", "failed": "CANCEL", "running": "SORTTIME"}
NOTE_ICONS = {"note": "INFO", "warning": "ERROR", "error": "ERROR"}
STROKE_ICONS = {"free": "STROKE", "add": "ADD", "carve": "REMOVE", "crease": "MOD_BEVEL",
                "region": "SELECT_SET", "note": "TEXT"}
# One icon button, at UI scale 1.
UNIT = 20
# What a box's border and inset take from the text inside it.
BOX_PAD = 10
# A label's icon and the gap after it.
ICON_PX = 20
# The sidebar's tab strip and the panel's margins on both sides: what is left
# of the region's width for a label's text.
REGION_MARGIN = 58
# The turn thumbnail grows with the sidebar, between these scales.
THUMBNAIL_SCALE = (4.0, 8.0)
THUMBNAIL_PER_UNIT = 0.36
NODE_THUMBNAIL_SCALE = 1.5
# The link button at the end of a Markdown line, in UI units.
LINK_UNITS = 1.0
# Drawn in the margin once per quote level, dim.
QUOTE_BAR = "\u258f"
# Prompt lines in a user bubble.
BUBBLE_PROMPT_LINES = 4
EXPANDED_TURNS = 2
COLLAPSED_TURNS = 3
# History popover: indentation per branch level, in UI units (the same step
# at every level, so depth reads at a glance), and the level beyond which
# rows stop stepping right. Wide enough that a turn's title is rarely cut.
INDENT = 1.0
MAX_INDENT_LEVEL = 4
HISTORY_UNITS = 24
HISTORY_ICON = "RECOVER_LAST"
# Marks the first row of a branch in the history popover: an arrow turning
# off the line above, not a disclosure triangle that looks collapsible.
BRANCH_MARK = "↳"
LOG_LINES = 20
# The chat menu: its width in UI units, and how many chats it lists before
# "Show N More".
CHATS_UNITS = 18
CHATS_SHOWN = 20
# What the panel header keeps beside the chat title: the collapse arrow,
# the title button's own padding and chevron, and the agent icon.
HEADER_RESERVE = 3.6
SWITCHED_NOTE = "The scene is as you left it; Claude will look at it before editing."
ASSET_HINT = "Or right-click an asset in the Asset Browser"
WRAP_CACHE = 1024


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def shorten(text: str, chars: int) -> str:
    """The first line of text, cut to chars with an ellipsis."""
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    chars = max(chars, 4)
    return line if len(line) <= chars else line[:chars - 1].rstrip() + "…"


def _ui_points() -> float:
    try:
        return bpy.context.preferences.ui_styles[0].widget.points
    except (AttributeError, IndexError):
        return 11.0


_wrap_cache: dict = {}


@dataclass
class Ctx:
    """What every part of the panel draws from. width is the room a label's
    text has at the panel's top level, in pixels."""
    scene: object
    hist: object
    ctl: object
    comparing: object
    width: int = 222
    scale: float = 1.0
    points: float = field(default_factory=_ui_points)
    # Set by draw_main when the attention box already reports a crash, so
    # the turn it ended does not report it again.
    crash_shown: bool = False
    # Set by draw_main when the attention box is shown.
    attention: bool = False
    # The open file's chats (whittle.chats.Chats), or None before there are any.
    chats: object = None

    def __post_init__(self):
        # Background Blender reports a UI scale of 0.
        self.scale = self.scale or 1.0

    @property
    def props(self):
        return self.scene.whittle

    @property
    def busy(self) -> bool:
        return operators.busy(self.ctl)

    @property
    def tree(self):
        return self.hist.tree if self.hist is not None else None

    def px(self, units: float) -> int:
        return int(units * UNIT * self.scale)

    # -- text measured with the UI font, so lines use the width they have --

    def measure(self, text: str) -> float:
        blf.size(0, self.points * self.scale)
        return blf.dimensions(0, text)[0]

    def wrap(self, text: str, width: float) -> list[str]:
        """text in lines no wider than width pixels, broken at spaces (a word
        too long for a line is broken where it must be). Blank lines stay."""
        key = (text, int(width), self.points, self.scale)
        found = _wrap_cache.get(key)
        if found is not None:
            return found
        out = []
        for paragraph in text.splitlines() or [""]:
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}" if line else word
                if self.measure(candidate) <= width:
                    line = candidate
                    continue
                if line:
                    out.append(line)
                while len(word) > 1 and self.measure(word) > width:
                    n = self._fitting(word, width)
                    out.append(word[:n])
                    word = word[n:]
                line = word
            out.append(line)
        if len(_wrap_cache) > WRAP_CACHE:
            _wrap_cache.clear()
        _wrap_cache[key] = out
        return out

    def _fitting(self, text: str, width: float) -> int:
        """How many leading characters of text fit width (at least one)."""
        lo, hi = 1, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.measure(text[:mid]) <= width:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def fit(self, text: str, width: float, *, words: bool = True) -> str:
        """The first line of text, cut with an ellipsis to fit width; with
        words, at a word's end when one is near."""
        line = next((part.strip() for part in text.splitlines() if part.strip()), "")
        if self.measure(line) <= width:
            return line
        n = self._fitting(line, max(width - self.measure("…"), 1))
        cut = line[:n]
        if words and " " in cut and n < len(line) and line[n] != " ":
            head = cut.rsplit(" ", 1)[0]
            if len(head) >= n * 0.6:
                cut = head
        return cut.rstrip(" ,.;:·-") + "…"

    def lines(self, text: str, width: float, limit: int = 0) -> list[str]:
        lines = self.wrap(text, width)
        if limit and len(lines) > limit:
            lines = lines[:limit - 1] + [self.fit(" ".join(lines[limit - 1:]), width)]
        return lines


def make_ctx(context, width: int | None = None) -> Ctx:
    scale = (context.preferences.system.ui_scale if context.preferences else 1.0) or 1.0
    if width is None:
        region = context.region
        width = max(120, (region.width if region else 280) - int(REGION_MARGIN * scale))
    return Ctx(scene=context.scene, hist=history.active(), ctl=turn.current(),
               comparing=compare.active(), width=width, scale=scale, chats=chats.get())


def _split_end(layout, ctx: Ctx, end_px: int, width: int | None = None):
    """(left, right) parts of one row whose right end is end_px wide, so
    buttons on the right keep their size whatever the text on the left."""
    width = width or ctx.width
    factor = min(0.95, max(0.2, 1.0 - end_px / max(width, 1)))
    split = layout.split(factor=factor, align=True)
    left = split.row()
    right = split.row(align=True)
    right.alignment = "RIGHT"
    return left, right


def _dim_label(layout, text: str, icon: str = "NONE") -> None:
    row = layout.row()
    row.active = False
    row.label(text=text, icon=icon)


def markdown_lines(text: str, ctx: Ctx, width: float) -> list[markdown.Line]:
    """Claude's Markdown laid out for width pixels. A label pads its text,
    so the lines are made a little narrower than the room they get."""
    key = ("md", text, int(width), ctx.points, ctx.scale)
    found = _wrap_cache.get(key)
    if found is None:
        slack = ctx.px(0.6)
        found = markdown.layout(text, width - slack, ctx.measure, code_width=width - BOX_PAD - slack,
                                link_room=ctx.px(LINK_UNITS))
        if len(_wrap_cache) > WRAP_CACHE:
            _wrap_cache.clear()
        _wrap_cache[key] = found
    return found


def draw_markdown(layout, lines: list[markdown.Line], ctx: Ctx, width: float) -> None:
    """Lines from markdown_lines: list items with their marker in a margin
    and their text hanging beside it, a code block in one box under its
    language and a copy button, quotes dim with a bar per level, footnotes
    dim, headings by level (H1 under a double line, H2 a line, H5 and H6
    dim), maths centred, a table as a box of columns, a <details> section
    as a closed sub-panel, a rule as a line and a gap as a little space. A
    line with a link ends with a button that opens it (a menu of them when
    it has several)."""
    col = layout.column(align=True)
    step = markdown.indent_step(ctx.measure)
    code = None  # the open code box: (indent, quote), its column, its quote bars
    pending = None  # a block without a language: (its code to copy, the row's width)
    for line in lines:
        if line.kind == "codehead" or (line.kind == "code" and (code is None or code[0] != (line.indent, line.quote))):
            bars, inner, room = _quote_margin(col, line, step, width)
            box = _indented(inner, line.indent - line.quote * step, room).box()
            box.active = not line.quote
            code = ((line.indent, line.quote), box.column(align=True), bars)
            if line.kind == "codehead":
                head_room = room - (line.indent - line.quote * step)
                if line.text:
                    _draw_code_head(code[1], line.text, line.copy, ctx, head_room)
                    _bar_labels(bars)
                else:
                    # No language: no empty head row, the copy button goes
                    # on the code's first row.
                    pending = (line.copy, head_room)
                continue
        if line.kind == "code":
            if pending is not None:
                _draw_code_head(code[1], line.text, pending[0], ctx, pending[1], dim=False)
                pending = None
            else:
                code[1].label(text=line.text)
            _bar_labels(code[2])
            continue
        code = pending = None
        if line.kind == "gap":
            if line.quote:
                # The bars run on through a gap in a quote.
                row = col.row(align=True)
                row.scale_y = 0.5
                _bar_labels(_quote_margin(row, line, step, width)[0])
            else:
                col.separator(factor=0.5)
        elif line.kind == "rule":
            col.separator(type="LINE")
        elif line.kind == "table":
            bars, inner, room = _quote_margin(col, line, step, width)
            _bar_labels(bars, line.height)
            indent = line.indent - line.quote * step
            draw_table(_indented(inner, indent, room), line, room - indent)
        elif line.kind == "details":
            _draw_details(col, line, ctx, width, step)
        else:
            _draw_text_line(col, line, width, step)


def _quote_margin(row, line: markdown.Line, step: float, width: float):
    """A dim column per quote level at the left of row, each one indent step
    wide: ([columns], the rest of row, its width in pixels)."""
    if not line.quote:
        return [], row, width
    row = row.row(align=True)
    bars = []
    for _ in range(line.quote):
        split = row.split(factor=min(0.5, step / max(width, 1)), align=True)
        bar = split.column(align=True)
        bar.active = False
        bars.append(bar)
        row = split.column(align=True)
        width -= step
    return bars, row, width


def _bar_labels(bars, rows: int = 1) -> None:
    for bar in bars:
        for _ in range(rows):
            bar.label(text=QUOTE_BAR)


def _indented(layout, indent: float, width: float):
    """The part of a row right of indent pixels."""
    if not indent:
        return layout
    split = layout.split(factor=min(0.5, indent / max(width, 1)), align=True)
    split.row()
    return split.column(align=True)


def _draw_code_head(layout, text: str, copy: str, ctx: Ctx, width: float, *, dim: bool = True) -> None:
    """A row of a code block with a button copying the code at its end: the
    language, dim, or with no language the code's first line."""
    left, right = _split_end(layout.row(align=True), ctx, ctx.px(1.2), int(width))
    left.active = not dim
    left.label(text=text)
    right.emboss = "NONE"
    right.operator("whittle.copy_code", text="", icon="COPYDOWN").text = copy


def _draw_text_line(col, line: markdown.Line, width: float, step: float) -> None:
    row = col.row(align=True)
    row.active = not (line.quote or line.kind == "note" or line.level >= 5)
    if line.kind == "heading" and line.level == 1:
        row.scale_y = 1.25
    bars, target, room = _quote_margin(row, line, step, width)
    _bar_labels(bars)
    target = target.row(align=True)
    indent = line.indent - line.quote * step
    if indent > 0.5:
        split = target.split(factor=min(0.5, indent / max(room, 1)), align=True)
        margin = split.row()
        margin.alignment = "RIGHT"
        margin.label(text=line.marker)
        target = split.row(align=True)
    if line.kind == "math":
        target.alignment = "CENTER"
    if line.links:
        target.alignment = "LEFT"
        target.label(text=line.text)
        button = target.row()
        button.emboss = "NONE"
        if len(line.links) == 1:
            (text, url), = line.links
            props = button.operator("whittle.open_link", text="", icon="URL")
            props.url, props.text = url, text
        else:
            button.operator("whittle.link_menu", text="", icon="URL").links = json.dumps(line.links)
    else:
        target.label(text=line.text)
    if line.kind == "heading" and line.level <= 2:
        col.separator(type="LINE")
        if line.level == 1:
            # A double line sets the title apart from the sections under it.
            col.separator(type="LINE", factor=0.2)


def draw_table(layout, line: markdown.Line, width: float) -> None:
    """A Markdown table in a box: a column per table column, as wide as the
    layout gave it, the header row bold above a line and a line between
    rows; each cell's lines aligned as its column says."""
    table = line.table
    total = sum(table.widths) + BOX_PAD
    # A table that had to wrap takes the whole width (the columns share the
    # little slack the layout kept back); a narrow one keeps its own width.
    if not table.fills and total < width - 1:
        split = layout.split(factor=total / width, align=True)
        layout = split.column()
        split.column()
    box = layout.box()
    box.active = not line.quote
    rows = box.column(align=True)
    for r, cells in enumerate(table.rows):
        if r:
            rows.separator(type="LINE", factor=0.6 if r == 1 else 0.3)
        height = max(len(cell) for cell in cells)
        for column, cell, align in zip(_columns(rows, table.widths), cells, table.aligns):
            for text in list(cell) + [""] * (height - len(cell)):
                row = column.row(align=True)
                row.alignment = align
                row.label(text=text)


def _columns(layout, widths) -> list:
    """Side-by-side columns of the given widths, by nested splits."""
    out = []
    rest = sum(widths)
    for j, w in enumerate(widths):
        if j == len(widths) - 1:
            out.append(layout.column(align=True))
            break
        split = layout.split(factor=w / max(rest, 1), align=True)
        out.append(split.column(align=True))
        layout = split.column(align=True)
        rest -= w
    return out


def _draw_details(layout, line: markdown.Line, ctx: Ctx, width: float, step: float) -> None:
    """A <details> section: a sub-panel, closed at first, its summary as the
    header. Its id comes from its content, so it stays open or closed
    across redraws."""
    key = zlib.crc32("\n".join([line.text] + [part.text for part in line.body]).encode())
    bars, inner, room = _quote_margin(layout, line, step, width)
    _bar_labels(bars)
    indent = line.indent - line.quote * step
    header, body = _indented(inner, indent, room).panel(f"whittle_md_{key:08x}", default_closed=True)
    header.active = not line.quote
    header.label(text=ctx.fit(line.text, width - line.indent - ctx.px(1.5)))
    if body is not None and line.body:
        draw_markdown(body, line.body, ctx, width)


def _wrapped(layout, text: str, ctx: Ctx, width: int, *, icon: str = "NONE", limit: int = 0) -> None:
    room = width - (ICON_PX * ctx.scale if icon != "NONE" else 0)
    col = layout.column(align=True)
    for i, line in enumerate(ctx.lines(text, room, limit)):
        col.label(text=line, icon=icon if i == 0 else ("BLANK1" if icon != "NONE" else "NONE"))


# -- header and the agent popover ------------------------------------------------

def agent_state(ctl) -> AgentState:
    return ctl.process.state if ctl is not None else AgentState.STOPPED


def current_model(ctl, found) -> str:
    """The model the current chat's next turn runs on."""
    return (getattr(ctl, "model", None) if ctl is not None else None) or models.chat_model(found)


def draw_indicator(layout, ctl) -> None:
    """One unembossed button in the panel header opening the agent popover:
    an hourglass while Claude is starting or stopping outside a turn, else a
    gear. A running turn already shows its progress in the conversation, so
    the header does not say it again; problems are in the panel body."""
    row = layout.row()
    row.emboss = "NONE"
    running = ctl is not None and getattr(ctl, "running", False)
    icon = "SORTTIME" if agent_state(ctl) in BUSY_STATES and not running else "PREFERENCES"
    row.popover("WHITTLE_PT_agent", text="", icon=icon)


def draw_agent(layout, ctl) -> None:
    state = agent_state(ctl)
    layout.label(text=f"Agent: {state}", icon="SORTTIME" if state in BUSY_STATES else "NONE")
    reason = ctl.process.reason if ctl is not None and state in (AgentState.CRASHED, AgentState.FAILED) \
        else None
    if reason:
        # The panel says only that Claude stopped; the details are here.
        col = layout.column(align=True)
        col.active = False
        for line in Ctx(scene=None, hist=None, ctl=None, comparing=None, width=240).lines(reason, 240, 4):
            col.label(text=line, icon="BLANK1")
    found = chats.get()
    model = current_model(ctl, found)
    short = models.button_text(model)
    layout.label(text=f"Model: {short} ({model})" if short != model else f"Model: {model}", icon="BLANK1")
    layout.label(text=f"Effort: {models.chat_effort(found).title()}", icon="BLANK1")
    if ctl is not None:
        blend = paths.blend_path()
        if blend is None:
            layout.label(text="Chats: unsaved file", icon="ERROR")
            _dim_label(layout, "Saving the file stores its chats in it.", "BLANK1")
        else:
            layout.label(text=f"Chats: in {blend.name}", icon="FILE_BLEND")
    col = layout.column(align=True)
    if ctl is not None and ctl.process.alive:
        col.operator("whittle.agent_stop", text="Stop Agent", icon="PAUSE")
    else:
        col.operator("whittle.agent_start", text="Start Agent", icon="PLAY")
    col.operator("preferences.addon_show", text="Preferences…", icon="PREFERENCES").module = prefs.PACKAGE


# -- attention ----------------------------------------------------------------

def _crashed_turn(ctx: Ctx, conv) -> str | None:
    """The turn a crash ended, when it can be sent again."""
    if conv is None or not conv.turns:
        return None
    last = conv.turns[-1]
    if last.status != "failed" or last.node is None or last.running:
        return None
    return last.node if operators.can_retry(ctx.hist, ctx.ctl, last.node) else None


def draw_attention(layout, ctx: Ctx, conv=None) -> bool:
    """A box only when the user has to act: set up, add an API key,
    restart. Only a real failure is red, and then only its line, never its
    button.
    Returns whether it drew one."""
    ctl = ctx.ctl
    width = ctx.width - BOX_PAD
    running = setup.current()
    if running is not None and running.running:
        box = layout.box()
        _wrapped(box, f"Setting up Claude: {running.describe_progress()}", ctx, width, icon="SORTTIME")
        box.operator("whittle.venv_cancel", text="Cancel", icon="CANCEL")
        return True
    state = agent_state(ctl)
    if state == AgentState.NEEDS_SETUP:
        # A first run is not a failure: neutral, unless a setup failed.
        box = layout.box()
        box.label(text="Set up Claude to start", icon="INFO")
        reason = ctl.process.reason if ctl is not None else None
        if reason and reason != setup_reason():
            col = box.column()
            col.active = False
            _wrapped(col, reason, ctx, width, limit=3)
        if running is not None and running.state in ("failed", "cancelled") and not running.dry_run:
            col = box.column()
            col.alert = running.state == "failed"
            _wrapped(col, f"Last setup {running.state}: {running.reason}", ctx, width, limit=3)
        row = box.row()
        row.operator_context = "INVOKE_DEFAULT"
        row.operator("whittle.venv_install", text="Set Up…", icon="IMPORT")
        return True
    if state == AgentState.NEEDS_KEY and not prefs.api_key()[0]:
        # Not a failure either: the one thing left to do before Claude runs.
        box = layout.box()
        box.label(text="Add an API key to start", icon="INFO")
        col = box.column()
        col.active = False
        _wrapped(col, "Whittle runs Claude with your own Anthropic API key, billed to your "
                 "Console account.", ctx, width, limit=3)
        _draw_key_buttons(box)
        return True
    if state in (AgentState.CRASHED, AgentState.FAILED) and ctl.process.reason:
        box = layout.box()
        line = box.row()
        line.alert = True
        line.label(text="Claude stopped unexpectedly" if state == AgentState.CRASHED
                   else "Claude could not start", icon="ERROR")
        node = _crashed_turn(ctx, conv)
        if node is not None:
            ctx.crash_shown = True
            box.operator("whittle.retry", text="Restart and Retry", icon="FILE_REFRESH").node = node
        else:
            box.operator("whittle.agent_start", text="Restart", icon="FILE_REFRESH")
        return True
    problem = getattr(ctl, "key_problem", None)
    if problem:
        box = layout.box()
        line = box.row()
        line.alert = True
        line.label(text=problem, icon="ERROR")
        _draw_key_buttons(box)
        return True
    return False


def _draw_key_buttons(layout) -> None:
    """Where the key goes, and where to get one."""
    row = layout.row(align=True)
    # In the order the steps happen: get a key, then paste it.
    row.operator("wm.url_open", text="Get a Key", icon="URL").url = prefs.KEYS_URL
    row.operator("preferences.addon_show", text="Preferences…", icon="PREFERENCES").module = prefs.PACKAGE


def setup_reason() -> str:
    """The generic reason a missing environment gives, already said by the box."""
    return "The agent environment is not set up yet"


# -- targets ------------------------------------------------------------------

def _turn_target_names(ctl) -> list[str] | None:
    if ctl is None or not getattr(ctl, "running", False):
        return None
    try:
        return [o.name for o in ctl.commands.targets()]
    except (AttributeError, ReferenceError, TypeError):
        return None


def draw_target_line(layout, ctx: Ctx) -> None:
    """What the next request works on. With Auto it follows the selection;
    with nothing selected it says that Claude will make new objects. With
    Auto off the rows below list the targets, so this line only counts
    them."""
    props = ctx.props
    end = ctx.px(2.6)
    left, right = _split_end(layout.row(), ctx, end)
    names = _turn_target_names(ctx.ctl) if ctx.busy else None
    room = ctx.width - end - ICON_PX * ctx.scale
    icon = "LOCKED" if ctx.busy else "OBJECT_DATA"
    picked = [t for t in props.targets if targets.eligible(t.object)]
    if names is None and not picked and props.target_collection is None:
        # Said in full, over two lines if it must: "New objects" alone
        # read as a target of its own.
        none = "Nothing selected" if props.target_auto else "No targets"
        col = left.column(align=True)
        col.active = False
        _wrapped(col, f"{none}: Claude adds new objects", ctx, room + ICON_PX * ctx.scale,
                 icon=icon, limit=2)
    else:
        if names is None and not props.target_auto:
            text = _plural(len(targets.resolve(ctx.scene)), "target")
        else:
            text = ctx.fit(targets.describe(ctx.scene, int(room / (6.2 * ctx.scale)), names), room,
                           words=False)
        left.label(text=text, icon=icon)
    # The lock says the target cannot change now; Auto steps back with it.
    right.active = not ctx.busy
    right.prop(props, "target_auto", text="Auto", toggle=True)
    if not props.target_auto:
        draw_manual_targets(layout, ctx)


def _selected_untargeted(scene) -> list:
    try:
        selected = list(bpy.context.view_layer.objects.selected)
    except AttributeError:
        return []
    picked = {t.object.name for t in scene.whittle.targets if t.object is not None}
    return [o for o in selected if targets.eligible(o) and o.name not in picked]


def draw_manual_targets(layout, ctx: Ctx) -> None:
    """The picked objects, one plain row each with its remove button, then
    a button adding what is selected. The rest is in the ⋯ popover."""
    props = ctx.props
    col = layout.column(align=True)
    col.enabled = not ctx.busy
    end = ctx.px(1.2)
    for i, item in enumerate(props.targets):
        if item.object is None:
            continue
        left, right = _split_end(col.row(), ctx, end)
        left.label(text=ctx.fit(item.object.name, ctx.width - end - ICON_PX * ctx.scale), icon="OBJECT_DATA")
        right.operator("whittle.target_remove", text="", icon="X", emboss=False).index = i
    if props.target_collection is not None:
        count = len([o for o in props.target_collection.all_objects if targets.eligible(o)])
        col.label(text=ctx.fit(f"{props.target_collection.name} ({count})", ctx.width - ICON_PX * ctx.scale),
                  icon="OUTLINER_COLLECTION")
    new = _selected_untargeted(ctx.scene)
    left, right = _split_end(col.row(), ctx, end)
    sub = left.row()
    sub.enabled = bool(new)
    text = f"Add {new[0].name}" if len(new) == 1 else (f"Add {len(new)} Selected" if new else "Add Selected")
    sub.operator("whittle.target_add", text=ctx.fit(text, ctx.width - end - ctx.px(1.5)), icon="ADD")
    right.popover("WHITTLE_PT_targets", text="", icon="THREE_DOTS")


def draw_target_options(layout) -> None:
    """The ⋯ popover beside the manual target list."""
    props = bpy.context.scene.whittle
    layout.prop(props, "target_collection", text="", icon="OUTLINER_COLLECTION")
    col = layout.column(align=True)
    col.operator("whittle.target_from_selection", text="Replace With Selection", icon="RESTRICT_SELECT_OFF")
    col.operator("whittle.target_clear", text="Clear", icon="X")


# -- comparison and start --------------------------------------------------------

def draw_comparison(layout, ctx: Ctx) -> None:
    """While comparing: what is shown, then Swap, Keep This (only while the
    compared turn is shown, since keeping the current scene is just Done)
    and Done. Their tooltips say that saving now saves what is shown."""
    comparing = ctx.comparing
    if comparing is None:
        return
    box = layout.box()
    inner = ctx.width - BOX_PAD
    if comparing.showing == compare.LIVE:
        text = "Showing: the current scene"
    else:
        label = ""
        if ctx.tree is not None and comparing.other in ctx.tree.nodes:
            node = ctx.tree.node(comparing.other)
            label = f"Start: {conversation.start_label(ctx.hist.session, node)}" if node.parent is None \
                else node.label
        label = label.strip().rstrip(".")
        text = f"Showing: {label}" if label else "Showing: an earlier turn"
    box.label(text=ctx.fit(text, inner - ICON_PX * ctx.scale), icon="ARROW_LEFTRIGHT")
    row = box.row(align=True)
    # Text only: with icons the three do not fit the default width.
    row.operator("whittle.compare_toggle", text="Swap")
    if comparing.showing != compare.LIVE:
        row.operator("whittle.compare_end", text="Keep This").keep = True
    row.operator("whittle.compare_end", text="Done").keep = False


def draw_start(layout) -> None:
    """Where node 0 comes from: one row under a dim "Start from", so the
    three read as ways to begin (beside them, they no longer fit the
    default sidebar width). Text only, for the same reason. The Asset
    Browser hint is in the Primitive menu."""
    col = layout.column(align=True)
    _dim_label(col, "Start from")
    row = col.row(align=True)
    row.operator("whittle.start_existing", text="Selection")
    row.operator("whittle.start_blank", text="Blank")
    row.menu("WHITTLE_MT_start_primitive", text="Primitive")


def can_offer_start(ctx: Ctx, conv: conversation.Conversation) -> bool:
    """While nothing has been sent yet, and not once the user is plainly on
    their way: sketching, or a prompt typed with a target picked. After a
    first turn that failed and folded away, the history popover offers the
    start points instead, so the panel stays on the failure and its Retry."""
    if conv.turns or ctx.busy or sketch.current_session() is not None:
        return False
    if ctx.props.prompt.strip() and targets.resolve(ctx.scene):
        return False
    return start.can_start(ctx.hist, ctx.ctl, ctx.comparing) is None


def draw_start_line(layout, conv: conversation.Conversation, ctx: Ctx) -> None:
    """A start point taken before the first turn, as one dim line. Once
    there are turns, the start is in the history popover."""
    if conv.root is None or conv.path_turns or ctx.tree is None:
        return
    root, label = conv.root
    if ctx.tree.node(root).label == trees.ROOT_LABEL:
        return
    _dim_label(layout, ctx.fit(f"Start: {label}", ctx.width))


# -- the conversation ---------------------------------------------------------------

def _siblings(node: str | None, ctx: Ctx) -> list[str]:
    """The node's non-folded siblings, itself included, when it has any."""
    tree = ctx.tree
    if tree is None or node is None or node not in tree.nodes or tree.node(node).folded:
        return []
    siblings = tree.siblings(node)
    return siblings if len(siblings) > 1 else []


def draw_switcher(layout, node: str | None, ctx: Ctx) -> bool:
    """‹ 1/2 › over the node's siblings, in the bubble's last row left of
    its ⋯, as chat apps do. An arrow that leads nowhere now is drawn
    greyed, so both ends of the count stay put. Returns whether it drew."""
    siblings = _siblings(node, ctx)
    if not siblings:
        return False
    i = siblings.index(node)
    row = layout.row(align=True)
    row.alignment = "RIGHT"
    for target, icon in ((siblings[i - 1] if i > 0 else None, "TRIA_LEFT"), (None, ""),
                         (siblings[i + 1] if i + 1 < len(siblings) else None, "TRIA_RIGHT")):
        if not icon:
            label = row.row(align=True)
            label.alignment = "RIGHT"
            label.active = False
            label.label(text=f"{i + 1}/{len(siblings)}")
            continue
        if target is not None and operators.can_switch(ctx.hist, ctx.ctl, target):
            row.operator("whittle.branch_switch", text="", icon=icon, emboss=False).node = target
        else:
            # A disabled unembossed button draws nothing at all; a dim icon
            # shows the end of the list.
            sub = row.row(align=True)
            sub.active = False
            sub.label(text="", icon=icon)
    return True


def draw_turn_menu_button(layout, turn: conversation.Turn, ctx: Ctx) -> None:
    sub = layout.row(align=True)
    sub.enabled = ctx.tree is not None and turn.node in ctx.tree.nodes and not turn.running
    sub.operator("whittle.turn_menu", text="", icon="THREE_DOTS", emboss=False).node = turn.node or ""


def _compared(turn: conversation.Turn, ctx: Ctx) -> bool:
    return ctx.comparing is not None and turn.node is not None and turn.node == ctx.comparing.other


def draw_bubble(layout, turn: conversation.Turn, ctx: Ctx) -> None:
    """The user's message: a box with the prompt at its full width and, on
    its last line, the branch switcher (with siblings) and the turn's ⋯
    (edit and resend, go back, compare...). What the request carried
    besides the prompt is a dim line. The turn being compared is marked."""
    box = layout.box()
    col = box.column(align=True)
    inner = ctx.width - BOX_PAD
    text = " ".join(turn.prompt.split()) or "(sketch only)"
    rows = [(line, False) for line in ctx.lines(text, inner, BUBBLE_PROMPT_LINES)]
    summary = turn.request.summary()
    if summary:
        rows.append((summary, True))
    switcher = bool(_siblings(turn.node, ctx))
    compared = _compared(turn, ctx)
    menu_px = ctx.px(1.2 + (3.4 if switcher else 0) + (1 if compared else 0))
    if turn.node is not None:
        last, dim = rows[-1]
        room = inner - menu_px - (ICON_PX * ctx.scale if dim else 0)
        if ctx.measure(last) > room:
            # The last word goes down a line so the ⋯ keeps its place.
            head, _, tail = last.rpartition(" ")
            if head and not dim and ctx.measure(head) <= room:
                rows[-1:] = [(head, False), (tail, False)]
            else:
                rows.append(("", False))
    for i, (line, dim) in enumerate(rows):
        target = col
        if i == len(rows) - 1 and turn.node is not None:
            target, right = _split_end(col.row(), ctx, menu_px, inner)
            if switcher:
                draw_switcher(right, turn.node, ctx)
            if compared:
                right.label(text="", icon="ARROW_LEFTRIGHT")
            draw_turn_menu_button(right, turn, ctx)
        row = target.row()
        row.active = not dim
        row.label(text=line, icon="GREASEPENCIL" if dim else "NONE")


def _segments(entries) -> list[tuple[str, object]]:
    """Entries in drawing order, with each run of tool calls (and thinking)
    gathered into one group."""
    out, group = [], None
    for entry in entries:
        if entry.kind in ("submit", "turn", "stopping"):
            continue
        if entry.kind in ("tool", "thinking"):
            if group is None:
                group = []
                out.append(("tools", group))
            group.append(entry)
            continue
        group = None
        out.append((entry.kind, entry))
    return out


def _group_header(group) -> tuple[str, str]:
    tools = [e for e in group if e.kind == "tool"]
    pending = [e for e in tools if e.status == "pending"]
    if len(pending) > 1:
        return f"Running {len(pending)} tools", "SORTTIME"
    if pending:
        return pending[-1].text, "SORTTIME"
    thought = any(e.kind == "thinking" for e in group)
    if not tools:
        return "Thought", "TOOL_SETTINGS"
    used = f"used {_plural(len(tools), 'tool')}"
    return (f"Thought, {used}" if thought else used.capitalize()), "TOOL_SETTINGS"


def thumbnail_scale(ctx: Ctx) -> float:
    low, high = THUMBNAIL_SCALE
    return max(low, min(high, ctx.width / (UNIT * ctx.scale) * THUMBNAIL_PER_UNIT))


def draw_thumbnail(layout, path: str, ctx: Ctx) -> None:
    """The turn's picture alone: Open Render is in the turn's ⋯ menu."""
    row = layout.row()
    row.alignment = "LEFT"
    row.template_icon(icon_value=previews.icon(path), scale=thumbnail_scale(ctx))


def _render_row(layout, path: str) -> None:
    """A render inside the tool group, with its own button to open it."""
    row = layout.row()
    row.alignment = "LEFT"
    row.template_icon(icon_value=previews.icon(path), scale=THUMBNAIL_SCALE[0])
    row.operator("whittle.open_image", text="", icon="IMAGE_DATA", emboss=False).filepath = path


def draw_tool_group(layout, group, ctx: Ctx, key: str, first_call: int, footer: str = "") -> None:
    text, icon = _group_header(group)
    header, body = layout.panel(f"whittle_tools_{key}", default_closed=True)
    header.label(text=ctx.fit(text, ctx.width - ctx.px(2.2)), icon=icon)
    if body is None:
        return
    inner = ctx.width - ctx.px(1)
    call = first_call
    for entry in group:
        if entry.kind == "thinking":
            col = body.column(align=True)
            col.active = False
            _wrapped(col, entry.text, ctx, inner, limit=4)
            continue
        h, b = body.panel(f"whittle_call_{key}_{call}", default_closed=True)
        call += 1
        h.label(text=ctx.fit(entry.text, inner - ctx.px(2.2)), icon=TOOL_ICONS.get(entry.status, "TOOL_SETTINGS"))
        if b is not None:
            col = b.column(align=True)
            for line in tool_detail(entry):
                col.label(text=ctx.fit(line, inner - ctx.px(1), words=False) if line.strip() else line)
        for path in entry.images:
            _render_row(body, path)
    if footer:
        _dim_label(body, footer)


def draw_note(layout, entry, ctx: Ctx) -> None:
    """A note is dim; a warning keeps its icon but is never red."""
    col = layout.column(align=True)
    col.active = entry.kind != "note"
    _wrapped(col, entry.text, ctx, ctx.width, icon=NOTE_ICONS.get(entry.kind, "INFO"), limit=3)


def draw_user_note(layout, entry, ctx: Ctx) -> None:
    """An amendment or an answer: a small user bubble inside the turn."""
    box = layout.box()
    prefix = "Amend" if entry.kind == "amend" else "Answer"
    _wrapped(box, f"{prefix}: {entry.text}", ctx, ctx.width - BOX_PAD, limit=4)


def draw_question(layout, ctl, ctx: Ctx) -> None:
    """Claude asking: the question and a button per choice. Not red: it is
    the conversation, not an error. A free answer goes in the prompt box."""
    question = getattr(ctl, "question", None) if ctl is not None else None
    if question is None:
        return
    box = layout.box()
    row = box.row()
    row.label(text="", icon="QUESTION")
    room = ctx.width - BOX_PAD - ICON_PX * ctx.scale
    draw_markdown(row, markdown_lines(question["question"], ctx, room), ctx, room)
    if question.get("choices"):
        row = box.row(align=True)
        for choice in question["choices"]:
            row.operator("whittle.answer", text=choice).text = choice


def _phase_line(layout, ctl, in_flight: bool) -> None:
    """Where the running turn is. While a tool call is in flight its group
    header already shows the hourglass, so Working… is left out then."""
    if getattr(ctl, "interrupting", False):
        text = "Stopping…"
    elif not getattr(ctl, "running", False) or ctl.status.get("phase") == "starting":
        text = "Starting Claude…"
    elif in_flight:
        return
    else:
        text = "Working…"
    _dim_label(layout, text, "SORTTIME")


def _asking(ctx: Ctx) -> bool:
    return ctx.ctl is not None and getattr(ctx.ctl, "question", None) is not None


def draw_turn_body(layout, turn: conversation.Turn, ctx: Ctx, *, last: bool = False) -> None:
    """A turn's content below its bubble: Claude's text, tool groups, notes,
    its picture, then how it ended."""
    key = turn.node or "run"
    end = turn.end
    entries = turn.entries
    if turn.running and _asking(ctx):
        # The question block below says it; its in-flight call would repeat it.
        entries = [e for e in entries if not (e.kind == "tool" and e.tool == "ask" and e.status == "pending")]
    segments = _segments(entries)
    groups = [i for i, (kind, _) in enumerate(segments) if kind == "tools"]
    group_n = call_n = 0
    for i, (kind, item) in enumerate(segments):
        if kind == "tools":
            footer = ""
            if end is not None and groups and i == groups[-1] and end.steps is not None:
                footer = _plural(end.steps, "step") + (f" · ${end.cost:.4f}" if end.cost is not None else "")
            draw_tool_group(layout, item, ctx, f"{key}_{group_n}", call_n, footer)
            group_n += 1
            call_n += sum(1 for e in item if e.kind == "tool")
        elif kind == "text":
            # Always in full: a fold in the middle of a reply was a chore.
            draw_markdown(layout, markdown_lines(item.text, ctx, ctx.width), ctx, ctx.width)
        elif kind in ("amend", "answer"):
            draw_user_note(layout, item, ctx)
        else:
            draw_note(layout, item, ctx)
    picture = turn.renders[-1] if turn.running and turn.renders else (None if turn.running else turn.picture)
    if picture:
        draw_thumbnail(layout, picture, ctx)
    if turn.running:
        if _asking(ctx):
            draw_question(layout, ctx.ctl, ctx)
        else:
            in_flight = any(e.kind == "tool" and e.status == "pending" for e in entries)
            _phase_line(layout, ctx.ctl, in_flight)
    elif turn.status == "interrupted":
        _dim_label(layout, "Stopped, changes undone" if turn.restored else "Stopped, changes kept", "PAUSE")
    elif turn.status == "failed":
        if last and ctx.crash_shown:
            # The attention box reports the crash and offers to retry.
            _dim_label(layout, "Interrupted", "PAUSE")
            return
        draw_failure(layout, turn, ctx, retry=last and turn.node is not None)


def draw_failure(layout, turn: conversation.Turn, ctx: Ctx, *, retry: bool) -> None:
    """A failed turn's end: its reason in red, one line (two at most), with
    Retry at the right of the first."""
    end = ctx.px(3.6) if retry else 0
    # A split leaves a gap between its parts, and a label pads its text.
    room = ctx.width - end - ICON_PX * ctx.scale - (ctx.px(0.8) if retry else 0)
    lines = ctx.lines(" ".join((turn.failure or "Failed").split()), room, 2)
    if retry:
        left, right = _split_end(layout.row(), ctx, end)
        right.enabled = operators.can_retry(ctx.hist, ctx.ctl, turn.node)
        right.operator("whittle.retry", text="Retry", icon="FILE_REFRESH").node = turn.node
    else:
        left = layout.row()
    col = left.column(align=True)
    col.alert = True
    for i, line in enumerate(lines):
        col.label(text=line, icon="CANCEL" if i == 0 else "BLANK1")


def draw_expanded(layout, turn: conversation.Turn, ctx: Ctx, *, last: bool = False) -> None:
    draw_bubble(layout, turn, ctx)
    draw_turn_body(layout, turn, ctx, last=last)


def draw_collapsed(layout, turn: conversation.Turn, ctx: Ctx) -> None:
    """An older turn as one closed panel headed by its prompt, with no
    buttons: opened, it is the whole turn, ⋯ included."""
    header, body = layout.panel(f"whittle_turn_{turn.node}", default_closed=True)
    icon = NODE_ICONS.get(turn.status, "NONE")
    # The header's disclosure arrow and inset take about two units.
    room = ctx.width - ctx.px(2) - (ICON_PX * ctx.scale if icon != "NONE" else 0)
    header.label(text=ctx.fit(turn.prompt or "(sketch only)", room), icon=icon)
    if body is not None:
        draw_expanded(body, turn, ctx)


def draw_conversation(layout, conv: conversation.Conversation, ctx: Ctx) -> None:
    path = conv.path_turns
    extra = [t for t in conv.turns if t.folded or t.running]
    expanded = path[-EXPANDED_TURNS:] if path else []
    collapsed = path[:len(path) - len(expanded)]
    if len(collapsed) > COLLAPSED_TURNS:
        earlier, collapsed = collapsed[:-COLLAPSED_TURNS], collapsed[-COLLAPSED_TURNS:]
        header, body = layout.panel("whittle_earlier", default_closed=True)
        header.label(text=f"{_plural(len(earlier), 'earlier turn')}")
        if body is not None:
            for turn in earlier:
                draw_collapsed(body, turn, ctx)
    for turn in collapsed:
        draw_collapsed(layout, turn, ctx)
    shown = expanded + extra
    for turn in shown:
        last = turn is shown[-1] and not turn.running and not conv.later
        draw_expanded(layout, turn, ctx, last=last)
    if conv.later and not ctx.busy:
        text = "Return to Latest"
        end = int(ctx.measure(text) + ctx.px(1.6))
        left, right = _split_end(layout.row(), ctx, end)
        left.active = False
        left.label(text=_plural(len(conv.later), "later turn"))
        sub = right.row(align=True)
        sub.enabled = operators.can_switch(ctx.hist, ctx.ctl, conv.later[-1])
        sub.operator("whittle.branch_switch", text=text, icon="LOOP_FORWARDS").node = conv.later[-1]
    if not ctx.attention:
        # Notes outside a turn are about a run that did not start; the
        # attention box already says why.
        for entry in conv.notes:
            draw_note(layout, entry, ctx)


# -- sketch ----------------------------------------------------------------------

def stroke_summary(obj, ctl) -> str:
    """The sketch's strokes in a few words, or "" when there is nothing to
    say (the row is then left out). Outside a turn it also counts strokes
    an earlier turn was sent with that are still shown (one that was
    stopped or failed keeps them) and views without strokes, so Clear and
    the view list stay reachable whenever the viewport shows something."""
    counts = sketch.stroke_counts(obj) if obj is not None else {}
    pending = counts.get(0, 0)
    if ctl is not None and getattr(ctl, "running", False):
        number = ctl._turn_number()
        sent = counts.get(number, 0) if number is not None else 0
        if not sent and not pending:
            return ""
        return f"{sent} sent · {pending} new"
    earlier = sum(n for stamp, n in counts.items() if stamp != 0)
    stored = views.load_views(obj.data) if obj is not None else []
    parts = []
    if pending:
        parts.append(_plural(pending, "stroke"))
    if earlier:
        parts.append(f"{earlier} sent" if pending else f"{_plural(earlier, 'stroke')} sent")
    if stored:
        parts.append(_plural(len(stored), "view"))
    return " · ".join(parts)


def draw_sketch(layout, ctx: Ctx) -> None:
    """The Sketch button; while sketching it stays pressed with Capture View
    beside it, and the stroke types (the active one named) go on a row of
    their own; and, once there is something drawn, its count over the
    list of views."""
    obj = sketch.find_sketch_object()
    sketching = sketch.current_session() is not None
    if not sketching:
        row = layout.row()
        row.alignment = "LEFT"
        row.operator("whittle.sketch", text="Sketch", icon="GREASEPENCIL")
    else:
        # Packed to the left, so a wide sidebar does not stretch the buttons.
        row = layout.row()
        row.alignment = "LEFT"
        row.operator("whittle.sketch_stop", text="Sketch", icon="GREASEPENCIL", depress=True)
        row.operator("whittle.capture_view", text="Capture View", icon="CAMERA_DATA")
        row = layout.row()
        row.alignment = "LEFT"
        tools = row.row(align=True)
        tools.alignment = "LEFT"
        active = sketch.active_type(obj) if obj is not None else None
        for stroke_type in formats.STROKE_TYPES:
            tools.operator("whittle.stroke_type", text="", icon=STROKE_ICONS[stroke_type],
                           depress=stroke_type == active).type = stroke_type
        if active:
            name = row.row()
            name.active = False
            name.label(text=active.capitalize())

    summary = stroke_summary(obj, ctx.ctl)
    if not summary:
        return
    # Open or closed is a window-manager property, not a layout panel's own
    # state, so it can be read and set from Python.
    header, body = layout.panel_prop(bpy.context.window_manager, "whittle_show_views")
    left = header.row()
    right = header.row(align=True)
    right.alignment = "RIGHT"
    left.label(text=summary)
    right.operator("whittle.clear_sketch", text="", icon="TRASH", emboss=False)
    if body is None:
        return
    stored = views.load_views(obj.data) if obj is not None else []
    if not stored:
        _dim_label(body, "No views yet: orbit and draw, or capture one")
        return
    used = {}
    for s in sketch.iter_strokes(obj, include_hidden=True):
        used[s.view] = used.get(s.view, 0) + 1
    latest = max(v.id for v in stored)
    tag = "current"
    for view in stored:
        current = view.id == latest
        text = f"View {view.id} · {_plural(used.get(view.id, 0), 'stroke')}"
        # The view new strokes go to is tagged when the row has room;
        # dimming the others would read as disabled. A panel's body is
        # inset by about a unit.
        room = ctx.width - ctx.px(2.2) - ICON_PX * ctx.scale
        current_tag = current and ctx.measure(f"{text}  {tag}") <= room
        end = ctx.px(1.2) + (int(ctx.measure(tag)) + ctx.px(0.4) if current_tag else 0)
        left, right = _split_end(body.row(), ctx, end)
        left.label(text=text, icon="VIEW_CAMERA" if current else "CAMERA_DATA")
        if current_tag:
            note = right.row()
            note.alignment = "RIGHT"
            note.active = False
            note.label(text=tag)
        right.operator("whittle.view_remove", text="", icon="X", emboss=False).id = view.id


# -- composer ----------------------------------------------------------------------

# How tall the prompt box starts; it scrolls past that.
COMPOSER_LINES = 3
# The model button's room beyond its text: padding and the menu's chevron.
MODEL_PAD = 2.0

def draw_references(layout, ctx: Ctx) -> None:
    """The references as attachment chips right above the prompt, packed
    into as few rows as fit. A chip is its picture and name, and opens the
    reference's menu (pin, place, open, remove); a pinned one carries a
    pressed pin beside it that unpins it."""
    refs = ctx.props.refs
    if not len(refs):
        return
    # A button pads its text, and chips in a row keep a gap between them.
    pad = ctx.px(1.1)
    chips = []
    for i, ref in enumerate(refs):
        name = Path(bpy.path.abspath(ref.path)).name if ref.path else "(no image)"
        extra = pad + ICON_PX * ctx.scale + (ctx.px(1.2) if ref.pinned else 0)
        text = ctx.fit(name, ctx.width - extra)
        chips.append((i, ref, text, ctx.measure(text) + extra))
    col = layout.column(align=False)
    row, used = None, 0.0
    for i, ref, text, width in chips:
        if row is None or used + width > ctx.width:
            row = col.row()
            row.alignment = "LEFT"
            used = 0.0
        used += width
        chip = row.row(align=True)
        # Sized to its text: a row would stretch a lone chip across the panel.
        chip.ui_units_x = width / ctx.px(1)
        icon_value = previews.icon(bpy.path.abspath(ref.path)) if ref.path else 0
        if icon_value:
            chip.operator("whittle.ref_menu", text=text, icon_value=icon_value).index = i
        else:
            chip.operator("whittle.ref_menu", text=text, icon="IMAGE_DATA").index = i
        if ref.pinned:
            chip.operator("whittle.ref_pin", text="", icon="PINNED", depress=True).index = i


def can_send(ctx: Ctx) -> bool:
    props = ctx.props
    if ctx.comparing is not None or ctx.busy or agent_state(ctx.ctl) == AgentState.NEEDS_SETUP:
        return False
    return bool(props.prompt.strip() or len(props.refs)
                or sketch.pending_count(sketch.find_sketch_object()))


def draw_composer(layout, ctx: Ctx) -> None:
    """References, the one prompt box, then Send (or Stop) and the
    history button. The box is multi-line and wraps, so a long draft can be
    read and edited in place; it is the only place the draft shows."""
    props = ctx.props
    draw_references(layout, ctx)
    ctl = ctx.ctl
    name = shortcut.field(ctl)
    asking = name == "ask_answer"
    row = layout.row(align=True)
    row.textbox(props, name, initial_visible_lines=COMPOSER_LINES, placeholder=shortcut.FIELDS[name][1])
    row.operator("whittle.ref_add", text="", icon="FILE_IMAGE")

    # The model button (not while a turn runs: the model changes between
    # turns) and the history button keep their widths: sharing the row
    # evenly squeezed the icon.
    model = None if ctx.busy else models.button_text(current_model(ctl, ctx.chats))
    history_px = ctx.px(1.8)
    model_px = ctx.measure(model) + ctx.px(MODEL_PAD) if model else 0
    end_px = history_px + model_px
    split = layout.split(factor=min(0.9, max(0.35, 1.0 - end_px / max(ctx.width, 1))))
    row, right = split.row(), split.row()
    row.scale_y = right.scale_y = 1.4
    if model:
        ends = right.split(factor=model_px / end_px, align=True)
        ends.menu("WHITTLE_MT_models", text=model)
        right = ends.row()
    if ctx.busy:
        main = row.row(align=True)
        # Answer and Amend show once there is something to send with them,
        # so the button row is just Stop until then.
        if asking and props.ask_answer.strip():
            main.operator("whittle.answer", text="Answer", icon="CHECKMARK")
        pending = sketch.pending_count(sketch.find_sketch_object())
        if (props.amend_text.strip() and not asking) or pending:
            sub = main.row(align=True)
            sub.enabled = bool(getattr(ctl, "can_amend", True))
            sub.operator("whittle.amend", text="Amend", icon="ADD")
        main.menu("WHITTLE_MT_stop", text="Stop", icon="CANCEL")
    else:
        sub = row.row()
        sub.enabled = can_send(ctx)
        branching = ctx.tree is not None and not ctx.tree.is_leaf(ctx.tree.current)
        sub.operator("whittle.submit", text="Send as Branch" if branching else "Send", icon="PLAY")
    right.popover("WHITTLE_PT_history", text="", icon=HISTORY_ICON)


# -- the whole panel -----------------------------------------------------------------

def draw_main(layout, ctx: Ctx) -> None:
    conv = conversation.build(ctx.hist, ctx.ctl)
    ctx.attention = draw_attention(layout, ctx, conv)
    draw_target_line(layout, ctx)
    draw_comparison(layout, ctx)
    if can_offer_start(ctx, conv):
        draw_start(layout)
    draw_start_line(layout, conv, ctx)
    draw_conversation(layout, conv, ctx)
    draw_switched(layout, ctx)
    layout.separator()
    draw_sketch(layout, ctx)
    draw_composer(layout, ctx)


# -- chats ------------------------------------------------------------------------

def chat_title(found) -> str:
    if found is None or found.current is None or found.current not in found:
        return chat_store.NEW_TITLE
    return found.entry(found.current).title


def draw_chat_title(layout, ctx: Ctx) -> None:
    """The panel header's left side: the current chat's title opening the
    chat menu, cut at a word's end to leave room for the agent icon."""
    row = layout.row()
    row.alignment = "LEFT"
    room = ctx.width - ctx.px(HEADER_RESERVE)
    row.popover("WHITTLE_PT_chats", text=ctx.fit(chat_title(ctx.chats), room))


def draw_switched(layout, ctx: Ctx) -> None:
    """After switching to a chat, until its next turn: the scene is not
    what its last turn left, and Claude will be told."""
    found = ctx.chats
    if found is None or found.current is None or found.switched != found.current or ctx.busy:
        return
    col = layout.column(align=True)
    col.active = False
    _wrapped(col, SWITCHED_NOTE, ctx, ctx.width, icon="INFO")


def chat_line(entry, now: float) -> str:
    """A chat's second row in the menu: '12 turns · 2 hours ago · 1.9 MB'."""
    age = chat_store.age_label(now - chat_store.epoch(entry.updated))
    return f"{_plural(entry.turns, 'turn')} · {age} · {chat_store.size_label(entry.size)}"


def draw_chats(layout, ctx: Ctx, now: float | None = None) -> None:
    """The chat menu: New Chat, then the file's chats, most recently active
    first, each its title (click to go back to it) over a dim line of its
    turns, age and stored size, with ✓ on the current one and a trash icon
    on the others; then the total and what can be done to this chat."""
    found = ctx.chats
    now = time.time() if now is None else now
    layout.operator("whittle.chat_new", text="New Chat", icon="ADD")
    _dim_label(layout, "Conversations")
    listed = found.listed() if found is not None else []
    if not listed:
        _dim_label(layout, "Nothing sent yet", "BLANK1")
    show_all = getattr(bpy.context.window_manager, "whittle_show_all_chats", False)
    shown = listed if show_all else listed[:CHATS_SHOWN]
    end = ctx.px(1.4)
    # A button pads its text on both sides.
    room = ctx.width - end - ctx.px(1.2)
    col = layout.column(align=True)
    for chat in shown:
        entry = found.entry(chat)
        current = chat == found.current
        left, right = _split_end(col.row(), ctx, end)
        title = left.row(align=True)
        title.alignment = "LEFT"
        title.emboss = "PULLDOWN_MENU"
        title.operator("whittle.chat_switch", text=ctx.fit(entry.title, room)).chat = chat
        if current:
            right.label(text="", icon="CHECKMARK")
        else:
            right.operator("whittle.chat_delete", text="", icon="TRASH", emboss=False).chat = chat
        line = col.row()
        line.active = False
        line.label(text=chat_line(entry, now), icon="BLANK1")
    if len(listed) > CHATS_SHOWN:
        more = len(listed) - CHATS_SHOWN
        layout.prop(bpy.context.window_manager, "whittle_show_all_chats", emboss=False,
                    text="Show Fewer" if show_all else f"Show {more} More",
                    icon="TRIA_UP" if show_all else "TRIA_DOWN")
    layout.separator()
    total = found.total_size() if found is not None else 0
    where = "when saved" if paths.blend_path() is None else "in this file"
    _dim_label(layout, f"{_plural(len(listed), 'chat')} · {chat_store.size_label(total)} {where}")
    items = layout.column(align=True)
    has_turns = found is not None and found.current in found and bool(found.entry(found.current).turns)
    if has_turns:
        row = items.row()
        row.alignment = "LEFT"
        row.emboss = "PULLDOWN_MENU"
        row.operator("whittle.chat_rename", text="Rename This Chat…", icon="GREASEPENCIL")
        row = items.row()
        row.alignment = "LEFT"
        row.emboss = "PULLDOWN_MENU"
        row.enabled = operators.can_delete_chat(found, ctx.ctl, found.current) is None
        row.operator("whittle.chat_delete", text="Delete This Chat…", icon="TRASH").chat = found.current
    if found is not None and found.to_delete("OTHERS"):
        row = items.row()
        row.alignment = "LEFT"
        row.emboss = "PULLDOWN_MENU"
        row.operator("whittle.chat_delete_many", text="Delete Other Chats…", icon="TRASH")


# -- history popover and menus -------------------------------------------------------

def branch_levels(tree) -> dict[str, int]:
    """How far each node is indented: a node with one child continues its
    line, so only a branch point steps its children in. Siblings share a
    level whatever was drawn before them, and a long session without
    branches stays flat."""
    levels = {}
    for node, _depth in tree.walk():
        if node.parent is None:
            levels[node.id] = 0
            continue
        parent = node.parent
        levels[node.id] = levels[parent] + (1 if len(tree.visible_children(parent)) > 1 else 0)
    return levels


def draw_history(layout, ctx: Ctx) -> None:
    """The whole tree, one row per node: its thumbnail, its title (click to
    go back to it; the current one highlighted) and ⋯ with the rest. A row's
    indentation comes from its branch level alone (branch_levels), the same
    step at every level, drawn as fixed-width cells at the start of the row,
    never as a nested layout. The first row of each branch is marked with
    an arrow turning off the line above, and the row it branches from says
    how many branches leave it."""
    tree = ctx.tree
    row = layout.row()
    left, right = _split_end(row, ctx, ctx.px(5))
    left.label(text="History")
    if tree is None:
        _dim_label(layout, "Nothing sent yet")
        return
    if compare.ghost_node() is not None:
        right.operator("whittle.ghost_toggle", text="Hide Ghost", icon="GHOST_ENABLED")
    draw_comparison(layout, ctx)
    if not tree.visible_children(tree.root) and start.can_start(ctx.hist, ctx.ctl, ctx.comparing) is None:
        # Nothing kept yet (a first turn that failed and folded away): the
        # start points the panel no longer shows.
        draw_start(layout)
    levels = branch_levels(tree)
    col = layout.column(align=True)
    for node, _depth in tree.walk():
        level = min(levels[node.id], MAX_INDENT_LEVEL)
        forks = len(tree.visible_children(node.id))
        fork_text = f"{forks} branches" if forks > 1 else ""
        end = ctx.px(1.2) + (int(ctx.measure(fork_text)) + ctx.px(0.6) if fork_text else 0)
        row_left, right = _split_end(col.row(), ctx, end)
        # The indentation, branch mark and thumbnail take a fixed part, so
        # the title gets the rest of the row whatever its length.
        lead_units = INDENT * level + NODE_THUMBNAIL_SCALE - 0.2
        room = ctx.width - end
        split = row_left.split(factor=min(0.6, ctx.px(lead_units) / max(room, 1)), align=True)
        part = split.row(align=True)
        part.alignment = "LEFT"
        if level:
            if level > 1:
                pad = part.row()
                pad.ui_units_x = INDENT * (level - 1)
                pad.label(text="")
            starts = node.parent is not None and len(tree.visible_children(node.parent)) > 1
            mark = part.row()
            mark.ui_units_x = INDENT
            mark.active = False
            mark.label(text=BRANCH_MARK if starts else "")
        thumb = ctx.hist.session.thumb_path(node.id)
        if thumb.is_file():
            part.template_icon(icon_value=previews.icon(str(thumb)), scale=NODE_THUMBNAIL_SCALE)
        else:
            part.label(text="", icon="BLANK1")
        current = node.id == tree.current
        icon = NODE_ICONS.get(node.status, "NONE")
        label = f"Start: {conversation.start_label(ctx.hist.session, node)}" if node.id == tree.root \
            else node.label
        # Drawn like menu items: the text starts at the left, the row lights
        # up under the pointer, and the current one stays lit. The full
        # title is in the button's tooltip.
        title = split.row(align=True)
        title.alignment = "LEFT"
        title.emboss = "PULLDOWN_MENU"
        title.enabled = operators.can_restore(ctx.hist, ctx.ctl, node.id)
        # A button pads its text on both sides.
        text_room = room - ctx.px(lead_units) - ctx.px(1.5) - (ICON_PX * ctx.scale if icon != "NONE" else 0)
        title.operator("whittle.history_restore", text=ctx.fit(label, text_room), icon=icon,
                       depress=current).node = node.id
        if fork_text:
            note = right.row()
            note.alignment = "RIGHT"
            note.active = False
            note.label(text=fork_text)
        right.operator("whittle.turn_menu", text="", icon="THREE_DOTS", emboss=False).node = node.id
    layout.separator()
    layout.operator("whittle.open_transcript", text="Open Transcript", icon="TEXT")


def turn_render(hist, node: str) -> str | None:
    """The last render a finished turn made, if any."""
    if hist is None or node is None:
        return None
    renders = [p for e in conversation.transcript_entries(hist.session, node) if e.kind == "tool"
               for p in e.images]
    return renders[-1] if renders else None


def draw_turn_menu(layout, hist, ctl, node: str) -> None:
    tree = hist.tree if hist is not None else None
    if tree is None or node not in tree.nodes:
        layout.label(text="This turn is not in the history")
        return
    root = node == tree.root
    items = []
    if not root:
        items.append(("whittle.history_branch", "Edit & Resend", "GREASEPENCIL",
                      operators.can_branch(hist, ctl, node)))
    if not tree.node(node).folded:
        items.append(("whittle.history_restore", "Go Back to the Start" if root else "Go Back to This Turn",
                      "LOOP_BACK",
                      operators.can_restore(hist, ctl, node)))
        items.append(("whittle.history_compare", "Compare With Current", "ARROW_LEFTRIGHT",
                      operators.can_compare(hist, ctl, node)))
    for idname, text, icon, allowed in items:
        row = layout.row()
        row.enabled = allowed
        row.operator(idname, text=text, icon=icon).node = node
    if root:
        return
    if node == tree.current:
        shown = compare.ghost_node() is not None
        layout.operator("whittle.ghost_toggle", text="Hide Ghost" if shown else "Ghost of Previous Turn",
                        icon="GHOST_ENABLED" if shown else "GHOST_DISABLED")
    render = turn_render(hist, node)
    if render:
        layout.operator("whittle.open_image", text="Open Render", icon="IMAGE_DATA").filepath = render
    layout.operator("whittle.open_transcript", text="Open Transcript", icon="TEXT")


def draw_ref_menu(layout, index: int) -> None:
    refs = bpy.context.scene.whittle.refs
    pinned = index < len(refs) and refs[index].pinned
    layout.operator("whittle.ref_pin", text="Unpin" if pinned else "Pin to Every Request",
                    icon="UNPINNED" if pinned else "PINNED").index = index
    layout.separator()
    for align, text, icon in (("VIEW", "Place Facing the View", "VIEW_CAMERA"),
                              ("FRONT", "Place Behind, Front", "BLANK1"),
                              ("RIGHT", "Place Behind, Right", "BLANK1"),
                              ("TOP", "Place Below, Top", "BLANK1")):
        props = layout.operator("whittle.ref_place", text=text, icon=icon)
        props.index = index
        props.align = align
    layout.separator()
    if index < len(refs) and refs[index].path:
        layout.operator("whittle.open_image", text="Open Image", icon="IMAGE_DATA").filepath = refs[index].path
    layout.operator("whittle.ref_remove", text="Remove", icon="X").index = index


# -- classes --------------------------------------------------------------------

class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Whittle"


class WHITTLE_PT_main(_Panel, bpy.types.Panel):
    # The current chat's title takes the label's place, over the header's width.
    bl_label = ""
    bl_options = {"HEADER_LAYOUT_EXPAND"}

    def draw_header(self, context):
        draw_chat_title(self.layout, make_ctx(context))

    def draw_header_preset(self, context):
        draw_indicator(self.layout, turn.current())

    def draw(self, context):
        draw_main(self.layout, make_ctx(context))


class WHITTLE_PT_agent(bpy.types.Panel):
    """The agent's state, model and session, opened from the header icon."""
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Claude"
    bl_ui_units_x = 14

    def draw(self, context):
        draw_agent(self.layout, turn.current())


class WHITTLE_PT_targets(bpy.types.Panel):
    """The target collection, Replace With Selection and Clear, opened from
    the ⋯ beside the manual target list."""
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Targets"
    bl_ui_units_x = 12

    def draw(self, context):
        draw_target_options(self.layout)


class WHITTLE_PT_history(bpy.types.Panel):
    """The whole history tree, opened from the button beside Send."""
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "History"
    bl_description = "History: every turn and branch, to go back to, compare or edit and resend"
    bl_ui_units_x = HISTORY_UNITS

    def draw(self, context):
        scale = (context.preferences.system.ui_scale if context.preferences else 1.0) or 1.0
        draw_history(self.layout, make_ctx(context, int((HISTORY_UNITS * UNIT - 24) * scale)))


class WHITTLE_PT_chats(bpy.types.Panel):
    """The chat menu, opened from the chat title in the panel header."""
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Chats"
    bl_description = "Chats: start a new chat or go back to an earlier one"
    bl_ui_units_x = CHATS_UNITS

    def draw(self, context):
        scale = (context.preferences.system.ui_scale if context.preferences else 1.0) or 1.0
        draw_chats(self.layout, make_ctx(context, int((CHATS_UNITS * UNIT - 24) * scale)))


class WHITTLE_MT_start_primitive(bpy.types.Menu):
    bl_label = "Primitive"
    bl_idname = "WHITTLE_MT_start_primitive"

    def draw(self, context):
        for kind in start.PRIMITIVES:
            self.layout.operator("whittle.start_primitive",
                                 text=kind.replace("_", " ").title()).kind = kind
        self.layout.separator()
        row = self.layout.row()
        row.active = False
        row.label(text=ASSET_HINT, icon="ASSET_MANAGER")


class WHITTLE_MT_stop(bpy.types.Menu):
    bl_label = "Stop"
    bl_idname = "WHITTLE_MT_stop"

    def draw(self, context):
        self.layout.operator("whittle.interrupt", text="Stop and Keep Changes", icon="PAUSE").mode = "KEEP"
        self.layout.operator("whittle.interrupt", text="Stop and Undo This Turn",
                             icon="LOOP_BACK").mode = "RESTORE"


class WHITTLE_OT_turn_menu(bpy.types.Operator):
    """A turn's menu. An operator rather than a Menu so the node it is for
    travels as a property."""
    bl_idname = "whittle.turn_menu"
    bl_label = "Turn"
    bl_description = "Edit and resend this turn, go back to it, compare it, or open its render or transcript"

    node: StringProperty(name="Node", default="", options={"SKIP_SAVE"})

    def invoke(self, context, event):
        node = self.node
        hist = history.active()
        title = ""
        if hist is not None and hist.tree is not None and node in hist.tree.nodes:
            found = hist.tree.node(node)
            title = f"Start: {found.label}" if found.parent is None else found.label
        context.window_manager.popup_menu(
            lambda menu, ctx: draw_turn_menu(menu.layout, history.active(), turn.current(), node),
            title=shorten(title, 40))
        return {"FINISHED"}

    def execute(self, context):
        return self.invoke(context, None)


class WHITTLE_OT_ref_menu(bpy.types.Operator):
    bl_idname = "whittle.ref_menu"
    bl_label = "Reference"
    bl_description = "Pin this reference, place it in the scene, open it, or remove it"

    index: IntProperty(default=0, min=0, options={"SKIP_SAVE"})

    def invoke(self, context, event):
        index = self.index
        context.window_manager.popup_menu(lambda menu, _ctx: draw_ref_menu(menu.layout, index),
                                          title="Reference")
        return {"FINISHED"}

    def execute(self, context):
        return self.invoke(context, None)


def link_entry(text: str, url: str) -> str:
    """A link in the menu of a line's links: its text and the site."""
    host = urlsplit(url).hostname or url.removeprefix("mailto:")
    return host if text == url else f"{shorten(text, 40)} · {host}"


class WHITTLE_OT_open_link(bpy.types.Operator):
    """wm.url_open with the link's text and address as its tooltip."""
    bl_idname = "whittle.open_link"
    bl_label = "Open Link"
    bl_options = {"INTERNAL"}

    url: StringProperty(name="URL", default="", options={"SKIP_SAVE"})
    text: StringProperty(name="Text", default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        if properties.text and properties.text != properties.url:
            return f"Open “{properties.text}”: {properties.url}"
        return f"Open {properties.url}"

    def execute(self, context):
        if not markdown.openable(self.url):
            self.report({"ERROR"}, f"Only web and mail links open: {self.url}")
            return {"CANCELLED"}
        bpy.ops.wm.url_open(url=self.url)
        return {"FINISHED"}


class WHITTLE_OT_link_menu(bpy.types.Operator):
    """The links of a Markdown line with more than one, as a menu."""
    bl_idname = "whittle.link_menu"
    bl_label = "Links"
    bl_options = {"INTERNAL"}

    # [[text, url], ...] as JSON.
    links: StringProperty(default="[]", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        try:
            links = json.loads(properties.links)
        except ValueError:
            links = []
        return "Open a link on this line: " + ", ".join(f"“{text}”" for text, _url in links)

    def invoke(self, context, event):
        try:
            links = json.loads(self.links)
        except ValueError:
            return {"CANCELLED"}

        def draw(menu, _ctx):
            for text, url in links:
                props = menu.layout.operator("whittle.open_link", text=link_entry(text, url), icon="URL")
                props.url, props.text = url, text

        context.window_manager.popup_menu(draw, title="Open Link")
        return {"FINISHED"}

    def execute(self, context):
        return self.invoke(context, None)


class WHITTLE_OT_copy_code(bpy.types.Operator):
    bl_idname = "whittle.copy_code"
    bl_label = "Copy Code"
    bl_description = "Copy this code block to the clipboard"
    bl_options = {"INTERNAL"}

    text: StringProperty(default="", options={"SKIP_SAVE"})

    def execute(self, context):
        context.window_manager.clipboard = self.text
        self.report({"INFO"}, "Copied the code")
        return {"FINISHED"}


class WHITTLE_PT_debug(_Panel, bpy.types.Panel):
    bl_label = "Development"
    bl_parent_id = "WHITTLE_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.preferences.view.show_developer_ui

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        ctl = turn.current()
        if ctl is not None and ctl.bundle is not None:
            # The folder of the request last sent, for Run Bundle below.
            layout.label(text=f"Last sent bundle: {Path(ctl.bundle.root).name}", icon="FILE_FOLDER")
        col = layout.column(align=True)
        col.label(text="Fake Script")
        col.prop(wm, "whittle_fake_script", text="")
        col.separator()
        col.label(text="Bundle")
        col.prop(wm, "whittle_bundle_path", text="")
        layout.operator("whittle.run_bundle")
        row = layout.row(align=True)
        row.operator("whittle.agent_start")
        row.operator("whittle.agent_stop")
        if ctl is not None and ctl.process.state in (AgentState.CRASHED, AgentState.FAILED):
            box = layout.box()
            box.label(text="Agent log:")
            for line in ctl.process.log_tail(LOG_LINES):
                box.label(text=line[:160])


CLASSES = (WHITTLE_MT_start_primitive, WHITTLE_MT_stop, WHITTLE_OT_turn_menu, WHITTLE_OT_ref_menu,
           WHITTLE_OT_open_link, WHITTLE_OT_link_menu, WHITTLE_OT_copy_code,
           WHITTLE_PT_main, WHITTLE_PT_agent, WHITTLE_PT_targets, WHITTLE_PT_history, WHITTLE_PT_chats,
           WHITTLE_PT_debug)
