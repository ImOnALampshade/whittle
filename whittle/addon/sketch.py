# SPDX-License-Identifier: GPL-3.0-or-later
"""The Whittle Sketch Grease Pencil object: one layer per stroke type, strokes
tagged with the view they were drawn from and the turn they were sent with,
and the sketch session that watches the viewport while the user draws."""

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import bpy
import numpy as np
from mathutils import Matrix, Vector

from .. import formats
from . import views

log = logging.getLogger("whittle")

SKETCH_NAME = "Whittle Sketch"
MATERIAL_NAME = "Whittle Stroke"
# Curve-domain INT attributes. 0 means untagged / pending.
VIEW_ATTRIBUTE = "whittle_view"
TURN_ATTRIBUTE = "whittle_turn"
# The amendment a stroke was sent with during its turn; 0 for the turn's own
# request (or a pending stroke).
AMEND_ATTRIBUTE = "whittle_amend"
# Built-in: strokes sharing a non-zero fill id are filled together.
FILL_ATTRIBUTE = "fill_id"
# Built-in: a stroke with this set draws no outline.
HIDE_ATTRIBUTE = "hide_stroke"
LAYER_TYPES = formats.STROKE_TYPES
LAYER_COLOURS = {
    "free": (1.0, 1.0, 1.0),
    "add": (0.1, 0.85, 0.15),
    "carve": (0.95, 0.1, 0.05),
    "crease": (1.0, 0.85, 0.0),
    "region": (0.1, 0.4, 1.0),
    "note": (0.55, 0.55, 0.55),
}
# Region fills are translucent so the model shows through them.
FILL_ALPHA = 0.35
POLL_INTERVAL = 0.25
# Every type layer keeps its one drawing keyed at Blender's lowest frame, so the
# sketch is the same wherever the playhead is and the draw tool, which paints
# into the key at or before the current frame, always reaches it.
SKETCH_FRAME = -1048574


def find_sketch_object():
    obj = bpy.data.objects.get(SKETCH_NAME)
    if obj is not None and obj.type == "GREASEPENCIL":
        return obj
    return None


def ensure_sketch_object(scene):
    obj = find_sketch_object()
    if obj is None:
        gp = bpy.data.grease_pencils.new(SKETCH_NAME)
        obj = bpy.data.objects.new(SKETCH_NAME, gp)
    if scene.collection.objects.get(obj.name) is None and obj.name not in scene.objects:
        scene.collection.objects.link(obj)
    gp = obj.data
    if MATERIAL_NAME not in [m.name for m in gp.materials if m]:
        gp.materials.append(_stroke_material())
    return obj


def _stroke_material():
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is None or mat.grease_pencil is None:
        mat = bpy.data.materials.new(MATERIAL_NAME)
        bpy.data.materials.create_gpencil_data(mat)
    mat.grease_pencil.color = (1.0, 1.0, 1.0, 1.0)
    # Only strokes with a fill id are filled (region strokes); the material's
    # show_fill flag no longer decides that.
    mat.grease_pencil.fill_color = (1.0, 1.0, 1.0, FILL_ALPHA)
    return mat


def ensure_layer(gp, stroke_type: str):
    layer = gp.layers.get(stroke_type)
    if layer is None:
        layer = gp.layers.new(stroke_type, set_active=False)
    layer.tint_color = LAYER_COLOURS[stroke_type]
    layer.tint_factor = 1.0
    # Lit strokes come out about a quarter as bright in Workbench renders.
    layer.use_lights = False
    return layer, _sketch_frame(layer, create=True).drawing


def _sketch_frame(layer, *, create: bool = False):
    """The layer's fixed sketch key. A layer keyed elsewhere (by a timeline
    key or auto-keying) has its earliest key moved there and its empty keys
    removed, so later keys stop hiding it."""
    frame = next((f for f in layer.frames if f.frame_number == SKETCH_FRAME), None)
    if frame is not None or not create:
        return frame
    others = sorted(f.frame_number for f in layer.frames)
    if others:
        layer.frames.move(others[0], SKETCH_FRAME)
        for number in others[1:]:
            stray = next(f for f in layer.frames if f.frame_number == number)
            if len(stray.drawing.strokes) == 0:
                layer.frames.remove(number)
    else:
        layer.frames.new(SKETCH_FRAME)
    return next(f for f in layer.frames if f.frame_number == SKETCH_FRAME)


def ensure_sketch_layers(scene):
    """The sketch object with all six type layers; 'free' is active when no
    type layer is."""
    obj = ensure_sketch_object(scene)
    gp = obj.data
    for stroke_type in LAYER_TYPES:
        ensure_layer(gp, stroke_type)
    if gp.layers.active is None or gp.layers.active.name not in LAYER_TYPES:
        gp.layers.active = gp.layers["free"]
    return obj


# -- the active stroke type ---------------------------------------------------

def active_type(obj) -> str:
    layer = obj.data.layers.active
    return layer.name if layer is not None and layer.name in LAYER_TYPES else "free"


def set_active_type(obj, stroke_type: str) -> None:
    """Makes the type's layer active, so the draw tool puts new strokes on it."""
    if stroke_type not in LAYER_TYPES:
        raise ValueError(f"unknown stroke type {stroke_type!r}")
    layer, _drawing = ensure_layer(obj.data, stroke_type)
    obj.data.layers.active = layer
    obj.active_material_index = 0


def next_type(obj) -> str:
    i = LAYER_TYPES.index(active_type(obj))
    return LAYER_TYPES[(i + 1) % len(LAYER_TYPES)]


# -- reading strokes ----------------------------------------------------------

@dataclass
class SketchStroke:
    layer: str
    drawing: object
    index: int
    view: int
    turn: int
    amend: int
    cyclic: bool
    points: list          # world space
    radius: list
    opacity: list


def _type_layers(obj, include_hidden: bool):
    for stroke_type in LAYER_TYPES:
        layer = obj.data.layers.get(stroke_type)
        if layer is None or (layer.hide and not include_hidden):
            continue
        frame = _sketch_frame(layer)
        if frame is None:
            continue
        yield layer, frame.drawing


def _read(attributes, name: str, count: int, dtype, key: str = "value"):
    attr = attributes.get(name)
    if attr is None:
        return None
    values = np.empty(count * (3 if key == "vector" else 1), dtype=dtype)
    attr.data.foreach_get(key, values)
    return values


def _curve_ints(drawing, name: str) -> list[int]:
    n = len(drawing.strokes)
    values = _read(drawing.attributes, name, n, np.int32)
    return [0] * n if values is None else values.tolist()


def iter_strokes(obj, *, include_hidden: bool = False) -> Iterator[SketchStroke]:
    """Strokes of each type layer's sketch drawing, in type order then stroke
    order. radius, opacity and cyclic only exist as attributes once something
    has written them; until then every stroke has the defaults."""
    for layer, drawing in _type_layers(obj, include_hidden):
        count = len(drawing.strokes)
        if count == 0:
            continue
        matrix = obj.matrix_world @ layer.matrix_local
        attrs = drawing.attributes
        n_points = len(attrs["position"].data)
        positions = _read(attrs, "position", n_points, np.float32, "vector").reshape(-1, 3)
        radius = _read(attrs, "radius", n_points, np.float32)
        opacity = _read(attrs, "opacity", n_points, np.float32)
        cyclic = _read(attrs, "cyclic", count, bool)
        view_ids = _curve_ints(drawing, VIEW_ATTRIBUTE)
        turns = _curve_ints(drawing, TURN_ATTRIBUTE)
        amends = _curve_ints(drawing, AMEND_ATTRIBUTE)
        offsets = [o.value for o in drawing.curve_offsets]
        identity = matrix == Matrix.Identity(4)
        for i in range(count):
            start, end = offsets[i], offsets[i + 1]
            local = positions[start:end].tolist()
            points = local if identity else [list(matrix @ Vector(p)) for p in local]
            stroke = drawing.strokes[i] if radius is None or opacity is None or cyclic is None else None
            yield SketchStroke(
                layer=layer.name, drawing=drawing, index=i, view=view_ids[i], turn=turns[i],
                amend=amends[i],
                cyclic=bool(cyclic[i]) if cyclic is not None else bool(stroke.cyclic),
                points=points,
                radius=(radius[start:end].tolist() if radius is not None
                        else [p.radius for p in stroke.points]),
                opacity=(opacity[start:end].tolist() if opacity is not None
                         else [p.opacity for p in stroke.points]),
            )


def read_strokes(obj) -> list[dict]:
    """Strokes of the sketch object as plain dicts (type, view, points)."""
    return [{"type": s.layer, "view": s.view, "points": s.points}
            for s in iter_strokes(obj, include_hidden=True)]


# -- tagging ------------------------------------------------------------------

def ensure_int_attribute(drawing, name: str):
    attr = drawing.attributes.get(name)
    if attr is None:
        attr = drawing.attributes.new(name, "INT", "CURVE")
    return attr


def _set_where(obj, name: str, value: int, predicate, *, include_hidden: bool = True) -> int:
    """Sets the curve attribute `name` to value on strokes whose current value
    satisfies predicate; returns how many changed."""
    changed = 0
    for _layer, drawing in _type_layers(obj, include_hidden):
        current = _curve_ints(drawing, name)
        hits = [i for i, v in enumerate(current) if predicate(v)]
        if not hits:
            continue
        data = ensure_int_attribute(drawing, name).data
        for i in hits:
            data[i].value = value
        changed += len(hits)
    return changed


def untagged(obj) -> list[tuple[object, int]]:
    return [(drawing, i) for _layer, drawing in _type_layers(obj, True)
            for i, v in enumerate(_curve_ints(drawing, VIEW_ATTRIBUTE)) if v == 0]


def tag_strokes(obj, view_id: int, *, only_untagged: bool = True) -> int:
    return _set_where(obj, VIEW_ATTRIBUTE, view_id,
                      (lambda v: v == 0) if only_untagged else (lambda v: True))


def _stamp(obj, select: Callable[[int, int], bool], turn_number: int, amend: int, *,
           include_hidden: bool = True) -> int:
    """Sets (turn, amend) on the strokes whose current (turn, amend) satisfy
    select; returns how many changed."""
    changed = 0
    for _layer, drawing in _type_layers(obj, include_hidden):
        current = zip(_curve_ints(drawing, TURN_ATTRIBUTE), _curve_ints(drawing, AMEND_ATTRIBUTE))
        hits = [i for i, (t, a) in enumerate(current) if select(t, a)]
        if not hits:
            continue
        turns = ensure_int_attribute(drawing, TURN_ATTRIBUTE).data
        amends = drawing.attributes.get(AMEND_ATTRIBUTE)
        if amend or amends is not None:
            amends = ensure_int_attribute(drawing, AMEND_ATTRIBUTE).data
        for i in hits:
            turns[i].value = turn_number
            if amends is not None:
                amends[i].value = amend
        changed += len(hits)
    return changed


def stamp_strokes(obj, turn_number: int) -> int:
    """Marks every visible stroke as sent with this turn. Strokes still stamped
    by an earlier turn that failed are sent again, so they are re-stamped too."""
    return _stamp(obj, lambda t, a: True, turn_number, 0, include_hidden=False)


def unstamp_strokes(obj, turn_number: int) -> int:
    """Marks the strokes stamped with this turn as unsent again, hidden ones
    included, for a run that never reached the agent."""
    return _stamp(obj, lambda t, a: t == turn_number, 0, 0)


def stamp_pending(obj, turn_number: int, amend: int) -> int:
    """Marks the visible pending strokes as sent with amendment `amend` of the
    running turn, so they share its fate: a finished turn removes them too."""
    return _stamp(obj, lambda t, a: t == 0, turn_number, amend, include_hidden=False)


def unstamp_amend(obj, turn_number: int, amend: int) -> int:
    """Makes an amendment's strokes pending again, hidden ones included, for an
    amendment the agent never received."""
    return _stamp(obj, lambda t, a: t == turn_number and a == amend, 0, 0)


def stroke_counts(obj) -> dict[int, int]:
    """Visible strokes per turn stamp; 0 counts the pending ones."""
    counts = Counter()
    for _layer, drawing in _type_layers(obj, False):
        counts.update(_curve_ints(drawing, TURN_ATTRIBUTE))
    return dict(counts)


def pending_count(obj) -> int:
    return stroke_counts(obj).get(0, 0) if obj is not None else 0


@contextmanager
def isolate_strokes(obj, keep: Callable[[int, int], bool]):
    """While active, strokes whose (turn, amend) fail keep draw nothing: no
    outline and no fill. Each drawing's hide and fill attributes come back as
    they were, absent ones removed again."""
    saved = []
    try:
        for _layer, drawing in _type_layers(obj, True):
            stamps = zip(_curve_ints(drawing, TURN_ATTRIBUTE), _curve_ints(drawing, AMEND_ATTRIBUTE))
            hidden = [i for i, (t, a) in enumerate(stamps) if not keep(t, a)]
            if not hidden:
                continue
            saved.append((drawing, {name: _read_attribute(drawing, name)
                                    for name in (HIDE_ATTRIBUTE, FILL_ATTRIBUTE)}))
            hide = drawing.attributes.get(HIDE_ATTRIBUTE) or drawing.attributes.new(
                HIDE_ATTRIBUTE, "BOOLEAN", "CURVE")
            fill = drawing.attributes.get(FILL_ATTRIBUTE)
            for i in hidden:
                hide.data[i].value = True
                if fill is not None:
                    fill.data[i].value = 0
            drawing.tag_positions_changed()
        yield
    finally:
        for drawing, values in saved:
            for name, value in values.items():
                _write_attribute(drawing, name, value)
            drawing.tag_positions_changed()


def _read_attribute(drawing, name: str):
    attr = drawing.attributes.get(name)
    if attr is None:
        return None
    return [d.value for d in attr.data]


def _write_attribute(drawing, name: str, values) -> None:
    attr = drawing.attributes.get(name)
    if values is None:
        if attr is not None:
            drawing.attributes.remove(attr)
        return
    if attr is None:
        return
    for d, value in zip(attr.data, values):
        d.value = value


def remove_turn_strokes(obj, turn_number: int) -> int:
    removed = 0
    for _layer, drawing in _type_layers(obj, True):
        hits = [i for i, v in enumerate(_curve_ints(drawing, TURN_ATTRIBUTE)) if v == turn_number]
        if hits:
            drawing.remove_strokes(indices=hits)
            removed += len(hits)
    return removed


def view_depth(obj, view: formats.View) -> float | None:
    """How far in front of the view's eye its strokes lie on average, or
    None when it has none in front of it."""
    eye, forward = views.eye_and_forward(view)
    depths = [(Vector(p) - eye).dot(forward) for s in iter_strokes(obj, include_hidden=True)
              if s.view == view.id for p in s.points]
    depths = [d for d in depths if d > 0.0]
    return sum(depths) / len(depths) if depths else None


def used_views(obj) -> set[int]:
    return {v for _layer, drawing in _type_layers(obj, True)
            for v in _curve_ints(drawing, VIEW_ATTRIBUTE) if v}


def ensure_region_fills(obj) -> int:
    """Gives each unfilled region stroke its own fill id, so it renders as a
    translucent area. The draw tool leaves fill ids at 0."""
    layer = obj.data.layers.get("region")
    if layer is None:
        return 0
    changed = 0
    for frame in layer.frames:
        drawing = frame.drawing
        ids = _curve_ints(drawing, FILL_ATTRIBUTE)
        next_id = max(ids, default=0) + 1
        missing = [i for i, v in enumerate(ids) if v == 0]
        if not missing:
            continue
        data = ensure_int_attribute(drawing, FILL_ATTRIBUTE).data
        for i in missing:
            data[i].value = next_id
            next_id += 1
        changed += len(missing)
    if changed:
        for frame in layer.frames:
            frame.drawing.tag_positions_changed()
    return changed


def clear_strokes(obj) -> None:
    for layer in obj.data.layers:
        for frame in layer.frames:
            if len(frame.drawing.strokes):
                frame.drawing.remove_strokes()
    views.clear_views(obj.data)


# -- loading a bundle's strokes -----------------------------------------------

def load_strokes(scene, strokes: list[formats.Stroke]):
    """Replaces the sketch's strokes with the given ones (world space)."""
    return _write_strokes(scene, strokes, append=False)


def add_strokes(scene, strokes: list[formats.Stroke]):
    """Adds the given strokes (world space) as pending ones, after the
    strokes already drawn."""
    return _write_strokes(scene, strokes, append=True)


def _write_strokes(scene, strokes: list[formats.Stroke], *, append: bool):
    obj = ensure_sketch_object(scene)
    gp = obj.data
    by_type: dict[str, list[formats.Stroke]] = {t: [] for t in LAYER_TYPES}
    for stroke in strokes:
        by_type[stroke.type].append(stroke)
    for stroke_type, group in by_type.items():
        if not group and (append or gp.layers.get(stroke_type) is None):
            continue
        _layer, drawing = ensure_layer(gp, stroke_type)
        if not append and len(drawing.strokes):
            drawing.remove_strokes()
        if not group:
            continue
        first = len(drawing.strokes)
        drawing.add_strokes([len(s.points) for s in group])
        view_data = ensure_int_attribute(drawing, VIEW_ATTRIBUTE).data
        turn_data = ensure_int_attribute(drawing, TURN_ATTRIBUTE).data
        for i, src in enumerate(group, start=first):
            dst = drawing.strokes[i]
            dst.cyclic = src.cyclic
            dst.material_index = 0
            for point, co, radius, opacity in zip(dst.points, src.points, src.radius, src.opacity):
                point.position = co
                point.radius = radius
                point.opacity = opacity
            view_data[i].value = src.view
            turn_data[i].value = 0
    ensure_region_fills(obj)
    return obj


# -- the sketch session -------------------------------------------------------

class SketchSession:
    """Sketching state for the sketch object: the user's saved tool settings
    and the watcher that tags new strokes with the view they were drawn from,
    capturing a new view when the viewport has moved substantially.

    Strokes are tagged from a depsgraph handler, which runs as soon as the
    draw tool adds a stroke, before the user can orbit away. The timer is a
    fallback for strokes added without a depsgraph update."""

    def __init__(self, scene, *, viewport_provider: Callable[[], views.Viewport | None] | None = None,
                 clock: Callable[[], float] = time.monotonic, use_timer: bool = True,
                 window_manager=None):
        self.scene = scene
        self.viewport_provider = viewport_provider
        self._window_manager = window_manager
        self.clock = clock
        self.use_timer = use_timer
        self.active = False
        self._saved: dict = {}
        self._previous_active: str | None = None
        # Per viewport: (last view matrix seen, when it last changed).
        self._seen: dict[int, tuple[tuple, float]] = {}
        # One bound method each, so the timer and the handler can be found
        # again to unregister them.
        self._timer = self._tick
        self._handler = self._on_depsgraph_update
        self._tagging = False

    def enter(self, context) -> None:
        obj = ensure_sketch_layers(self.scene)
        view_layer = context.view_layer
        current = view_layer.objects.active
        if current is not None and current is not obj and current.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        self._previous_active = current.name if current is not None and current is not obj else None
        view_layer.objects.active = obj
        obj.select_set(True)
        tools = self.scene.tool_settings
        self._saved = {"gpencil_stroke_placement_view3d": tools.gpencil_stroke_placement_view3d,
                       "gpencil_surface_offset": tools.gpencil_surface_offset,
                       "use_keyframe_insert_auto": tools.use_keyframe_insert_auto}
        # Strokes stick to the surface under the cursor; off the surface they
        # fall back to the view plane at the 3D cursor's depth.
        tools.gpencil_stroke_placement_view3d = "SURFACE"
        tools.gpencil_surface_offset = 0.0
        # Auto-keying would give the drawing a new key at the playhead, away
        # from the fixed sketch key.
        tools.use_keyframe_insert_auto = False
        if obj.mode != "PAINT_GREASE_PENCIL":
            bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
        self.active = True
        if self.use_timer and not bpy.app.timers.is_registered(self._timer):
            bpy.app.timers.register(self._timer, first_interval=POLL_INTERVAL)
        if self._handler not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(self._handler)

    def exit(self, context=None, *, from_timer: bool = False) -> None:
        if not self.active:
            return
        self.active = False
        # The timer ends itself by returning None; unregistering it from inside
        # its own callback is left to Blender.
        if self.use_timer and not from_timer and bpy.app.timers.is_registered(self._timer):
            bpy.app.timers.unregister(self._timer)
        self._remove_handler()
        try:
            tools = self.scene.tool_settings
            for key, value in self._saved.items():
                setattr(tools, key, value)
        except ReferenceError:
            return
        obj = find_sketch_object()
        if obj is not None and obj.mode != "OBJECT":
            view_layer = (context or bpy.context).view_layer
            if view_layer.objects.active is obj:
                bpy.ops.object.mode_set(mode="OBJECT")
        if self._previous_active and obj is not None:
            previous = bpy.data.objects.get(self._previous_active)
            if previous is not None and previous.name in (context or bpy.context).view_layer.objects:
                (context or bpy.context).view_layer.objects.active = previous

    def capture(self, viewport: views.Viewport | None = None) -> formats.View:
        """Captures a new view from the viewport; it becomes the current view.
        Strokes still waiting for a tag belong to the view before it."""
        viewport = viewport or self.active_viewport()
        if viewport is None:
            raise RuntimeError("there is no 3D viewport to capture")
        obj = ensure_sketch_object(self.scene)
        current = views.current_view(obj.data)
        if current is not None:
            tag_strokes(obj, current.id)
        return self._store(obj, viewport)

    def _store(self, obj, viewport: views.Viewport) -> formats.View:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return views.add_view(obj.data, lambda view_id: views.view_from_region(
            view_id, viewport.rv3d, viewport.region, self.scene, depsgraph))

    def poll(self) -> float | None:
        """One watcher step: tags new strokes with the current view, first
        capturing a new one if the viewport moved substantially."""
        if not self.active:
            return None
        obj = find_sketch_object()
        if obj is None:
            # The sketch was deleted under the session: leave properly, so the
            # user's tool settings come back and the handler goes.
            self.exit(from_timer=True)
            return None
        self._tag_pending(obj)
        return POLL_INTERVAL

    def _tag_pending(self, obj, depsgraph=None) -> None:
        if self._tagging:
            return
        # Tagging writes attributes and may evaluate the depsgraph, which runs
        # the handler again; the guard keeps that from re-entering.
        self._tagging = True
        try:
            # Asked every step, so the viewport heuristic sees each change.
            viewport = self.active_viewport()
            if viewport is None or not untagged(obj):
                return
            depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
            candidate = views.view_from_region(0, viewport.rv3d, viewport.region, self.scene, depsgraph)
            current = views.current_view(obj.data)
            distance = float(getattr(viewport.rv3d, "view_distance", 1.0))
            if current is None or views.substantially_different(current, candidate, distance):
                current = views.add_view(obj.data, lambda view_id: candidate)
            tag_strokes(obj, current.id)
            ensure_region_fills(obj)
        except Exception:
            log.exception("sketch watcher step failed")
        finally:
            self._tagging = False

    def _on_depsgraph_update(self, scene, depsgraph) -> None:
        if not self.active:
            self._remove_handler()
            return
        try:
            obj = find_sketch_object()
        except ReferenceError:
            return
        if obj is None or scene != self.scene:
            return
        gp = obj.data
        if any(u.id.original == gp or u.id.original == obj for u in depsgraph.updates):
            self._tag_pending(obj, depsgraph)

    def _remove_handler(self) -> None:
        handlers = bpy.app.handlers.depsgraph_update_post
        while self._handler in handlers:
            handlers.remove(self._handler)

    def _tick(self):
        interval = self.poll()
        if interval is None:
            _forget(self)
        return interval

    def active_viewport(self) -> views.Viewport | None:
        """The viewport the user is most likely drawing in: the one whose view
        changed most recently, else the largest."""
        if self.viewport_provider is not None:
            return self.viewport_provider()
        found = views.viewports(self._window_manager or bpy.context.window_manager)
        if not found:
            return None
        now = self.clock()
        best, best_time = None, None
        for vp in found:
            key = vp.region.as_pointer()
            matrix = tuple(tuple(row) for row in vp.rv3d.view_matrix)
            seen = self._seen.get(key)
            changed = seen[1] if seen is not None and seen[0] == matrix else (now if seen else 0.0)
            self._seen[key] = (matrix, changed)
            if changed > 0.0 and (best_time is None or changed > best_time):
                best, best_time = vp, changed
        if best is not None:
            return best
        return max(found, key=lambda vp: vp.region.width * vp.region.height)


_session: SketchSession | None = None


def current_session() -> SketchSession | None:
    return _session if _session is not None and _session.active else None


def start_session(context, **kwargs) -> SketchSession:
    global _session
    end_session(context)
    _session = SketchSession(context.scene, **kwargs)
    _session.enter(context)
    return _session


def _forget(session: SketchSession) -> None:
    global _session
    if _session is session:
        _session = None


def after_undo() -> None:
    """An undo can take the sketch out of Draw Mode, or remove it, behind the
    session's back: the session then ends, without putting back tool
    settings the undo already put back."""
    session = current_session()
    if session is None:
        return
    obj = find_sketch_object()
    if obj is not None and obj.mode == "PAINT_GREASE_PENCIL":
        return
    session._saved = {}
    end_session()


def end_session(context=None) -> None:
    global _session
    session, _session = _session, None
    if session is not None:
        try:
            session.exit(context)
        except (RuntimeError, ReferenceError) as exc:
            log.warning("could not leave sketch mode cleanly: %s", exc)
