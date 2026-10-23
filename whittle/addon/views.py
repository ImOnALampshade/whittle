# SPDX-License-Identifier: GPL-3.0-or-later
"""Sketch views: camera snapshots taken from the 3D viewport, stored on the
sketch datablock and written to the bundle as camera.json.

Everything is derived from the viewport's view and projection matrices, never
from SpaceView3D.lens (the viewport uses a 72 mm sensor, so the lens alone gives
the wrong field of view). RegionView3D.update() is never called: it crashes
Blender in background mode, and the matrices are only read.
"""

import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

from mathutils import Matrix, Vector

from .. import formats

log = logging.getLogger("whittle")

ANGLE_THRESHOLD_DEG = 15.0
# Fraction of the viewport's view distance the eye may move before it is a new view.
MOVE_THRESHOLD = 0.10
# Relative change in field of view (angle or ortho scale) that makes a new view.
ZOOM_THRESHOLD = 0.15
VIEWS_PROP = "whittle_views"
NEXT_VIEW_PROP = "whittle_next_view"
# Gap left between an orthographic camera's eye and the nearest visible depth.
ORTHO_EYE_MARGIN = 0.01


def _matrix(value) -> Matrix:
    return value.copy() if isinstance(value, Matrix) else Matrix(value)


def _rows(matrix: Matrix) -> list:
    return [[float(x) for x in row] for row in matrix]


# -- camera maths -------------------------------------------------------------

def clip_range(window_matrix) -> tuple[float, float, bool]:
    """(near, far, is_perspective) recovered from a projection matrix."""
    p = _matrix(window_matrix)
    if abs(p[3][3]) > 0.5:
        near = (p[2][3] + 1.0) / p[2][2]
        far = (p[2][3] - 1.0) / p[2][2]
        return near, far, False
    near = p[2][3] / (p[2][2] - 1.0)
    far = p[2][3] / (p[2][2] + 1.0)
    return near, far, True


def camera_spec(view_matrix, window_matrix, width: int, height: int) -> dict:
    """The render camera that reproduces the viewport's projection exactly at
    width x height. The long side picks the sensor fit."""
    view = _matrix(view_matrix)
    p = _matrix(window_matrix)
    near, far, perspective = clip_range(p)
    if width >= height:
        fit, scale = "HORIZONTAL", p[0][0]
    else:
        fit, scale = "VERTICAL", p[1][1]
    matrix_world = view.inverted()
    if not perspective and near <= 0.0:
        # An orthographic viewport shows geometry behind its pivot (its near
        # plane is negative) but a camera's clip_start must be positive, so the
        # eye moves back. The projection is parallel, so nothing else changes.
        shift = ORTHO_EYE_MARGIN - near
        matrix_world = matrix_world @ Matrix.Translation((0.0, 0.0, shift))
        near, far = ORTHO_EYE_MARGIN, far + shift
    return {
        "matrix_world": _rows(matrix_world),
        "type": "PERSP" if perspective else "ORTHO",
        "angle": 2.0 * math.atan(1.0 / scale),
        "ortho_scale": 2.0 / scale,
        "sensor_fit": fit,
        "clip_start": float(near),
        "clip_end": float(far),
    }


def view_from_matrices(view_id: int, view_matrix, window_matrix, width: int, height: int, *,
                       from_camera: str | None = None) -> formats.View:
    width, height = max(1, int(width)), max(1, int(height))
    camera = camera_spec(view_matrix, window_matrix, width, height)
    return formats.View(
        id=view_id,
        view_matrix=_rows(_matrix(view_matrix)),
        window_matrix=_rows(_matrix(window_matrix)),
        is_perspective=camera["type"] == "PERSP",
        width=width,
        height=height,
        from_camera=from_camera,
        camera=camera,
    )


def view_from_camera(view_id: int, camera_obj, scene, depsgraph) -> formats.View:
    """A view looking through a scene camera, sized like its render so the
    overlay matches the camera frame. Lens shift is not represented."""
    render = scene.render
    pct = render.resolution_percentage / 100.0
    width = max(1, round(render.resolution_x * pct))
    height = max(1, round(render.resolution_y * pct))
    view_matrix = camera_obj.matrix_world.normalized().inverted()
    window_matrix = camera_obj.calc_matrix_camera(depsgraph, x=width, y=height)
    return view_from_matrices(view_id, view_matrix, window_matrix, width, height,
                              from_camera=camera_obj.name)


def view_from_region(view_id: int, rv3d, region, scene, depsgraph) -> formats.View:
    """A view from a viewport. rv3d needs view_matrix, window_matrix and
    view_perspective; region needs width and height."""
    if rv3d.view_perspective == "CAMERA" and scene.camera is not None:
        return view_from_camera(view_id, scene.camera, scene, depsgraph)
    return view_from_matrices(view_id, rv3d.view_matrix, rv3d.window_matrix,
                              region.width, region.height)


def eye_and_forward(view: formats.View) -> tuple[Vector, Vector]:
    """The viewport eye and its unit viewing direction, in world space."""
    world = Matrix(view.view_matrix).inverted()
    forward = (world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    return world.translation.copy(), forward


def _field_of_view(view: formats.View) -> float:
    return view.camera["angle"] if view.is_perspective else view.camera["ortho_scale"]


def substantially_different(last: formats.View, current: formats.View, view_distance: float) -> bool:
    """True when the direction turned by more than the angle threshold, the
    view moved by more than a fraction of the view distance, the projection
    type changed, or the field of view changed noticeably.

    Movement is measured at the pivot the viewport orbits around (eye plus
    view_distance along the line of sight), so orbiting counts only through
    its angle, while panning and dollying count as movement."""
    if last.is_perspective != current.is_perspective:
        return True
    eye_a, fwd_a = eye_and_forward(last)
    eye_b, fwd_b = eye_and_forward(current)
    cos = max(-1.0, min(1.0, fwd_a.dot(fwd_b)))
    if math.degrees(math.acos(cos)) > ANGLE_THRESHOLD_DEG:
        return True
    distance = max(view_distance, 1e-6)
    pivot_a, pivot_b = eye_a + fwd_a * distance, eye_b + fwd_b * distance
    if (pivot_a - pivot_b).length > MOVE_THRESHOLD * distance:
        return True
    fov_a, fov_b = _field_of_view(last), _field_of_view(current)
    return abs(fov_b - fov_a) > ZOOM_THRESHOLD * max(abs(fov_a), 1e-9)


def to_pixel(view: formats.View, co, width: int, height: int) -> tuple[float, float] | None:
    """World point -> pixel (x right, y down) in a width x height image rendered
    from the view; None when the point is behind a perspective eye."""
    clip = Matrix(view.window_matrix) @ Matrix(view.view_matrix) @ Vector((*co, 1.0))
    if clip.w <= 1e-9:
        return None
    x, y = clip.x / clip.w, clip.y / clip.w
    return (x + 1.0) * 0.5 * width, (1.0 - y) * 0.5 * height


# -- storage on the sketch datablock ------------------------------------------

def load_views(gp) -> list[formats.View]:
    raw = gp.get(VIEWS_PROP)
    if not raw:
        return []
    try:
        return [formats.View.from_json(v) for v in json.loads(raw)]
    except (ValueError, TypeError, KeyError) as exc:
        log.warning("ignoring unreadable sketch views: %s", exc)
        return []


def save_views(gp, views: list[formats.View]) -> None:
    gp[VIEWS_PROP] = json.dumps([v.to_json() for v in views], separators=(",", ":"))


def add_view(gp, make: Callable[[int], formats.View]) -> formats.View:
    """Stores a new view under the next id; ids are never reused."""
    views = load_views(gp)
    view_id = max(int(gp.get(NEXT_VIEW_PROP, 1)), max((v.id for v in views), default=0) + 1)
    view = make(view_id)
    view.id = view_id
    views.append(view)
    save_views(gp, views)
    gp[NEXT_VIEW_PROP] = view_id + 1
    return view


def merge_views(gp, incoming) -> dict[int, int]:
    """Stores views brought back from a request; returns each one's id on the
    sketch. A view already stored under its id is reused. Ids are never
    reused, but a sketch object made afresh counts from 1 again, so a clash
    with a different view gets a new id."""
    stored = {v.id: v for v in load_views(gp)}
    mapping = {}
    for view in incoming:
        have = stored.get(view.id)
        if have is not None and have.to_json() == view.to_json():
            mapping[view.id] = view.id
            continue
        if have is None:
            stored[view.id] = view
            save_views(gp, list(stored.values()))
            gp[NEXT_VIEW_PROP] = max(int(gp.get(NEXT_VIEW_PROP, 1)), view.id + 1)
            mapping[view.id] = view.id
            continue
        added = add_view(gp, lambda new_id, v=view: formats.View.from_json({**v.to_json(), "id": new_id}))
        stored[added.id] = added
        mapping[view.id] = added.id
    return mapping


def latest_view(gp) -> formats.View | None:
    return max(load_views(gp), key=lambda v: v.id, default=None)


def prune_views(gp, keep_ids: set[int]) -> None:
    """Drops views no stroke uses any more; the latest is always kept, since it
    is the one new strokes are tagged with."""
    views = load_views(gp)
    if not views:
        return
    latest = max(v.id for v in views)
    save_views(gp, [v for v in views if v.id in keep_ids or v.id == latest])


def clear_views(gp) -> None:
    save_views(gp, [])


# -- viewport discovery (GUI only) --------------------------------------------

@dataclass
class Viewport:
    area: object
    region: object
    rv3d: object


def viewports(window_manager) -> list[Viewport]:
    """Every 3D viewport region, including each quad-view quarter."""
    found = []
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type == "WINDOW" and region.data is not None:
                    found.append(Viewport(area, region, region.data))
    return found


def viewport_from_context(context) -> Viewport | None:
    area = context.area
    if area is None or area.type != "VIEW_3D":
        return None
    region = context.region
    if region is None or region.type != "WINDOW":
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
    if region is None:
        return None
    rv3d = context.region_data or region.data or area.spaces.active.region_3d
    return Viewport(area, region, rv3d)
