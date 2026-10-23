# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for bpy.types.UILayout that records what draw code asks for.
Panels cannot be drawn in background Blender, so draw functions are tested
against this instead."""

from types import SimpleNamespace


class RecordingLayout:
    def __init__(self, calls=None, depth=0):
        self.calls = calls if calls is not None else []
        self.depth = depth
        self.alert = False
        self.enabled = True
        self.active = True
        self.scale_y = 1.0
        self.scale_x = 1.0
        self.alignment = "EXPAND"
        self.emboss = "NORMAL"
        self.operator_context = "EXEC_REGION_WIN"

    def _record(self, kind, **data):
        record = {"kind": kind, "depth": self.depth, "layout": self, **data}
        self.calls.append(record)
        return record

    def _child(self, kind, **data):
        child = RecordingLayout(self.calls, self.depth + 1)
        self._record(kind, child=child, **data)
        return child

    def row(self, **kw):
        return self._child("row", **kw)

    def column(self, **kw):
        return self._child("column", **kw)

    def box(self):
        return self._child("box")

    def split(self, **kw):
        return self._child("split", **kw)

    def grid_flow(self, **kw):
        return self._child("grid_flow", **kw)

    def panel(self, idname, *, default_closed=False):
        header = RecordingLayout(self.calls, self.depth + 1)
        body = RecordingLayout(self.calls, self.depth + 1)
        self._record("panel", idname=idname, default_closed=default_closed, child=header, body=body)
        return header, body

    def panel_prop(self, data, prop):
        return self.panel(prop, default_closed=not getattr(data, prop, False))

    def label(self, *, text="", icon="NONE", **kw):
        self._record("label", text=text, icon=icon)

    def prop(self, data, prop, **kw):
        self._record("prop", data=data, prop=prop, **kw)

    def textbox(self, data, prop, **kw):
        # Recorded as a prop, so field lookups find either kind.
        self._record("prop", data=data, prop=prop, textbox=True, **kw)

    def operator(self, idname, **kw):
        props = SimpleNamespace()
        self._record("operator", idname=idname, props=props, **kw)
        return props

    def menu(self, menu, **kw):
        self._record("menu", menu=menu, **kw)

    def popover(self, panel, **kw):
        self._record("popover", panel=panel, **kw)

    def template_icon(self, *, icon_value=0, scale=1.0):
        self._record("template_icon", icon_value=icon_value, scale=scale)

    def template_list(self, *args, **kw):
        self._record("template_list", args=args, **kw)

    def separator(self, **kw):
        self._record("separator", **kw)

    # -- queries --------------------------------------------------------------

    def of(self, kind):
        return [c for c in self.calls if c["kind"] == kind]

    def operators(self, idname=None):
        return [c for c in self.of("operator") if idname is None or c["idname"] == idname]

    def menus(self):
        return [c["menu"] for c in self.of("menu")]

    def labels(self):
        return [c["text"] for c in self.of("label")]

    def text(self):
        """Every label, joined: for checking wrapped text."""
        return " ".join(self.labels())

    def props(self):
        return [c["prop"] for c in self.of("prop")]

    def is_enabled(self, record):
        """Whether a recorded item is enabled, counting its parents' state."""
        return self._chain(record, "enabled")

    def is_active(self, record):
        return self._chain(record, "active")

    def alerted(self, record):
        return not self._chain(record, "alert", want=False)

    def in_panel(self, record, prefix):
        """Whether a recorded item is drawn inside the body of a layout panel
        whose id starts with prefix (a recording draws every panel open)."""
        bodies = {id(c["body"]): c for c in self.calls if c["kind"] == "panel"}
        parents = {id(c[key]): c["layout"] for c in self.calls for key in ("child", "body") if key in c}
        layout = record["layout"]
        while layout is not None:
            panel = bodies.get(id(layout))
            if panel is not None and panel["idname"].startswith(prefix):
                return True
            layout = parents.get(id(layout))
        return False

    def _chain(self, record, attr, want=True):
        layout = record["layout"]
        parents = {id(c[key]): c["layout"] for c in self.calls for key in ("child", "body") if key in c}
        while layout is not None:
            if getattr(layout, attr) != want:
                return False
            layout = parents.get(id(layout))
        return True
