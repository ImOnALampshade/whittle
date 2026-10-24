# SPDX-License-Identifier: GPL-3.0-or-later
"""What Blender's own redraws of a panel or the add-on's preferences drew.

Blender has no Python API for what a region shows. A Spy wraps a class's
draw method, so each real redraw (the sidebar, a popover, the Preferences
window) runs the class's own code against a SpyLayout: every call goes on
to the real layout, and is recorded as tests/blender/ui_helpers.py's
RecordingLayout records it, so the same queries read it."""

import traceback
from types import SimpleNamespace

from tests.blender.ui_helpers import RecordingLayout

# Draws kept per spy: the latest is what is on screen.
KEEP = 20


class _Props:
    """An operator button's properties: values set are recorded and passed
    on. The real ones belong to the button, which the next redraw frees."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "values", SimpleNamespace())

    def __setattr__(self, name, value):
        setattr(self.values, name, value)
        setattr(self._real, name, value)

    def __getattr__(self, name):
        return getattr(self.values, name)


class SpyLayout(RecordingLayout):
    """A real UILayout, recorded. Records keep their own copies of alert,
    enabled and active and of operator properties, never the real layout,
    which Blender frees after the draw."""

    _OWN = ("alert", "enabled", "active", "scale_x", "scale_y", "alignment", "emboss", "operator_context")

    def __init__(self, real, calls=None, depth=0):
        # RecordingLayout's defaults, kept here only: setting them on the real
        # layout would undo what it inherits from its parent.
        object.__setattr__(self, "_real", real)
        probe = RecordingLayout(calls, depth)
        for name, value in vars(probe).items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name in self._OWN:
            setattr(self._real, name, value)

    def __getattr__(self, name):
        # Anything not recorded (another template, ui_units_x, ...) goes to the
        # real layout as it is.
        return getattr(self._real, name)

    def _wrap(self, kind, real, **data):
        child = SpyLayout(real, self.calls, self.depth + 1)
        self._record(kind, child=child, **data)
        return child

    def row(self, **kw):
        return self._wrap("row", self._real.row(**kw), **kw)

    def column(self, **kw):
        return self._wrap("column", self._real.column(**kw), **kw)

    def box(self):
        return self._wrap("box", self._real.box())

    def split(self, **kw):
        return self._wrap("split", self._real.split(**kw), **kw)

    def grid_flow(self, **kw):
        return self._wrap("grid_flow", self._real.grid_flow(**kw), **kw)

    def panel(self, idname, *, default_closed=False):
        return self._panel(self._real.panel(idname, default_closed=default_closed), idname, default_closed)

    def panel_prop(self, data, prop):
        return self._panel(self._real.panel_prop(_real(data), prop), prop, None)

    def _panel(self, pair, idname, default_closed):
        header, body = pair
        header = SpyLayout(header, self.calls, self.depth + 1)
        # A closed panel has no body; the record says so with None.
        body = SpyLayout(body, self.calls, self.depth + 1) if body is not None else None
        self._record("panel", idname=idname, default_closed=default_closed, child=header, body=body)
        return header, body

    def label(self, *, text="", icon="NONE", **kw):
        self._record("label", text=text, icon=icon)
        self._real.label(text=text, icon=icon, **kw)

    def prop(self, data, prop, **kw):
        self._record("prop", data=data, prop=prop, **kw)
        self._real.prop(_real(data), prop, **kw)

    def textbox(self, data, prop, **kw):
        self._record("prop", data=data, prop=prop, textbox=True, **kw)
        self._real.textbox(_real(data), prop, **kw)

    def operator(self, idname, **kw):
        props = _Props(self._real.operator(idname, **kw))
        self._record("operator", idname=idname, props=props.values, **kw)
        return props

    def menu(self, menu, **kw):
        self._record("menu", menu=menu, **kw)
        self._real.menu(menu, **kw)

    def popover(self, panel, **kw):
        self._record("popover", panel=panel, **kw)
        self._real.popover(panel, **kw)

    def template_icon(self, *, icon_value=0, scale=1.0):
        self._record("template_icon", icon_value=icon_value, scale=scale)
        self._real.template_icon(icon_value=icon_value, scale=scale)

    def template_list(self, *args, **kw):
        self._record("template_list", args=args, **kw)
        self._real.template_list(*(_real(a) for a in args), **kw)

    def separator(self, **kw):
        self._record("separator", **kw)
        self._real.separator(**kw)

    # -- queries --------------------------------------------------------------

    def operator_props(self, idname: str) -> list:
        """The properties each button of an operator was given."""
        return [c["props"] for c in self.operators(idname)]

    def find_prop(self, prop: str):
        found = [c for c in self.of("prop") if c["prop"] == prop]
        return found[0] if found else None


class _Self:
    """The panel or preferences instance a draw method gets, with the
    recording layout as its layout."""

    def __init__(self, real, layout):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "layout", layout)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


def _real(value):
    return value._real if isinstance(value, (_Self, SpyLayout)) else value


class Spy:
    """Wraps cls.<method> until remove(): Blender looks the method up on the
    class at each redraw, so the wrapper runs for every real draw."""

    def __init__(self, cls, method: str = "draw"):
        self.cls = cls
        self.method = method
        self.original = cls.__dict__[method]
        self.draws: list[SpyLayout] = []
        self.errors: list[str] = []
        self.count = 0
        original = self.original

        def draw(this, context):
            layout = SpyLayout(this.layout)
            try:
                return original(_Self(this, layout), context)
            except Exception:
                self.errors.append(traceback.format_exc())
                raise
            finally:
                self.count += 1
                self.draws = (self.draws + [layout])[-KEEP:]

        setattr(cls, method, draw)

    @property
    def latest(self) -> SpyLayout | None:
        return self.draws[-1] if self.draws else None

    def remove(self) -> None:
        setattr(self.cls, self.method, self.original)

    def __enter__(self) -> "Spy":
        return self

    def __exit__(self, *exc) -> None:
        self.remove()
