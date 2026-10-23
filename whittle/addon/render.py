# SPDX-License-Identifier: GPL-3.0-or-later
"""Workbench renders from sketch views or agent-described cameras, with the
user's strokes composited for overlay renders. The scene is always left as it
was found."""

import math
import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

# Imported under another name: render() takes the sketch object as `sketch`.
from . import sketch as sketch_strokes

CAMERA_NAME = "Whittle Render Camera"
WIRE_MODIFIER = "_whittle_wire"
# Renders are transparent; agent-facing images get a flat mid-grey backdrop so
# white strokes and pale materials stay visible.
BACKGROUND = (0.32, 0.32, 0.32)
# The render tool's own bounds (its schema says the same).
MIN_SIZE = 64
MAX_SIZE = 1024
DEFAULT_LENS_MM = 50.0
SENSOR_MM = 36.0

_SETTINGS = (
    # (path from the scene, attribute)
    ("render", "engine"),
    ("render", "resolution_x"),
    ("render", "resolution_y"),
    ("render", "resolution_percentage"),
    ("render", "film_transparent"),
    ("render", "filepath"),
    ("render.image_settings", "file_format"),
    ("render.image_settings", "color_mode"),
    ("render.image_settings", "color_depth"),
    ("display.shading", "light"),
    ("display.shading", "color_type"),
    ("display.shading", "studio_light"),
    ("view_settings", "view_transform"),
    ("view_settings", "look"),
    ("view_settings", "exposure"),
    ("view_settings", "gamma"),
    ("", "camera"),
)


def _owner(scene, path: str):
    owner = scene
    for part in filter(None, path.split(".")):
        owner = getattr(owner, part)
    return owner


def snapshot_settings(scene) -> dict:
    values = {(p, a): getattr(_owner(scene, p), a) for p, a in _SETTINGS}
    values["hide_render"] = {o.name: o.hide_render for o in scene.objects}
    return values


@contextmanager
def render_settings(scene):
    saved = snapshot_settings(scene)
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.image_settings.color_depth = "8"
        # Standard keeps stroke and material colours flat.
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.view_settings.exposure = 0.0
        scene.view_settings.gamma = 1.0
        yield
    finally:
        for path, attr in _SETTINGS:
            # light must be restored before studio_light: the valid studio
            # lights depend on it.
            try:
                setattr(_owner(scene, path), attr, saved[(path, attr)])
            except (TypeError, ValueError, ReferenceError):
                pass
        for obj in scene.objects:
            if obj.name in saved["hide_render"]:
                obj.hide_render = saved["hide_render"][obj.name]


# -- cameras ------------------------------------------------------------------

def camera_from_look_at(location, look_at, lens_mm: float | None = None) -> dict:
    eye, target = Vector(location), Vector(look_at)
    direction = target - eye
    if direction.length < 1e-6:
        raise ValueError("camera location and look_at are the same point")
    rotation = direction.to_track_quat("-Z", "Y").to_matrix().to_4x4()
    matrix = Matrix.Translation(eye) @ rotation
    lens = float(lens_mm or DEFAULT_LENS_MM)
    return {
        "matrix_world": [list(row) for row in matrix],
        "type": "PERSP",
        "angle": 2 * math.atan(SENSOR_MM / (2 * lens)),
        "ortho_scale": 6.0,
        "sensor_fit": "HORIZONTAL",
        "clip_start": 0.01,
        "clip_end": 1000.0,
    }


@contextmanager
def temp_camera(scene, spec: dict):
    data = bpy.data.cameras.new(CAMERA_NAME)
    obj = None
    try:
        data.type = spec["type"]
        data.sensor_fit = spec["sensor_fit"]
        if spec["type"] == "ORTHO":
            data.ortho_scale = spec["ortho_scale"]
        else:
            data.angle = spec["angle"]
        data.clip_start = spec["clip_start"]
        data.clip_end = spec["clip_end"]
        obj = bpy.data.objects.new(CAMERA_NAME, data)
        scene.collection.objects.link(obj)
        obj.matrix_world = Matrix(spec["matrix_world"])
        scene.camera = obj
        yield obj
    finally:
        if obj is not None:
            bpy.data.objects.remove(obj)
        bpy.data.cameras.remove(data)


def world_bounds(objects) -> tuple[Vector, Vector] | None:
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    if not corners:
        return None
    return (Vector((min(c[i] for c in corners) for i in range(3))),
            Vector((max(c[i] for c in corners) for i in range(3))))


def frame_camera(objects, direction=(1.0, -1.0, 0.8), lens_mm: float = DEFAULT_LENS_MM,
                 margin: float = 1.1) -> dict:
    """A look-at camera for a square image, from `direction` (pointing from
    the objects towards the camera; three-quarter by default), placed just
    far enough back that every corner of the objects' world bounds is in
    frame with `margin` to spare. A unit box at the origin when there is
    nothing to frame."""
    bounds = world_bounds(objects)
    lo, hi = bounds if bounds else (Vector((-0.5, -0.5, -0.5)), Vector((0.5, 0.5, 0.5)))
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-3)
    back = Vector(direction).normalized()
    # The same axes camera_from_look_at gives a camera looking along -back.
    axes = (-back).to_track_quat("-Z", "Y").to_matrix()
    right, up = axes.col[0], axes.col[1]
    tan_half = SENSOR_MM / (2 * lens_mm)
    # Fitting the box's corners rather than its bounding sphere keeps a
    # flat or long target from shrinking to a sliver.
    distance = 0.0
    for x in (lo.x, hi.x):
        for y in (lo.y, hi.y):
            for z in (lo.z, hi.z):
                offset = Vector((x, y, z)) - centre
                side = max(abs(offset.dot(right)), abs(offset.dot(up)))
                distance = max(distance, side * margin / tan_half + offset.dot(back))
    distance = max(distance, radius * 0.1, 1e-3)
    eye = centre + back * distance
    spec = camera_from_look_at(eye, centre, lens_mm)
    spec["clip_start"] = max(1e-3, (distance - radius) * 0.5)
    spec["clip_end"] = distance + radius * 4
    return spec


def resolution(size: int, aspect: float) -> tuple[int, int]:
    if aspect >= 1.0:
        return size, max(1, round(size / aspect))
    return max(1, round(size * aspect)), size


# -- pixels -------------------------------------------------------------------

def load_pixels(path) -> np.ndarray:
    """Raw file values as float32 (h, w, 4); Non-Color so nothing is converted."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        w, h = image.size
        pixels = np.empty(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        return pixels.reshape(h, w, 4)
    finally:
        bpy.data.images.remove(image)


def save_pixels(pixels: np.ndarray, path) -> None:
    h, w, _ = pixels.shape
    image = bpy.data.images.new("whittle-composite", w, h, alpha=True)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.pixels.foreach_set(np.ascontiguousarray(pixels, dtype=np.float32).ravel())
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)


def composite(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    """Straight-alpha `top over bottom`. Where top is opaque the result is top;
    where it is fully transparent the result is bottom."""
    ta, ba = top[..., 3:4], bottom[..., 3:4]
    out_a = ta + ba * (1.0 - ta)
    premult = top[..., :3] * ta + bottom[..., :3] * ba * (1.0 - ta)
    rgb = np.divide(premult, out_a, out=np.zeros_like(premult), where=out_a > 0)
    rgb = np.where(ta >= 1.0, top[..., :3], np.where(ta <= 0.0, bottom[..., :3], rgb))
    return np.concatenate([rgb, out_a], axis=-1).astype(np.float32)


def flatten(pixels: np.ndarray, background=BACKGROUND) -> np.ndarray:
    bg = np.empty_like(pixels)
    bg[..., :3] = background
    bg[..., 3] = 1.0
    return composite(pixels, bg)


# -- rendering ----------------------------------------------------------------

def _render_to(scene, path: Path) -> None:
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def _set_mode(scene, mode: str) -> None:
    shading = scene.display.shading
    if mode == "matcap":
        shading.light = "MATCAP"
    else:
        shading.light = "STUDIO"
        shading.color_type = "MATERIAL"


@contextmanager
def _wireframes(objects):
    meshes = [o for o in objects if o.type == "MESH"]
    added = []
    try:
        diag = _bounds_diagonal(meshes) or 1.0
        for obj in meshes:
            mod = obj.modifiers.new(WIRE_MODIFIER, "WIREFRAME")
            mod.thickness = 0.005 * diag
            added.append((obj, mod))
        yield
    finally:
        for obj, mod in added:
            obj.modifiers.remove(mod)


def _bounds_diagonal(objects) -> float:
    bounds = world_bounds(objects)
    return (bounds[1] - bounds[0]).length if bounds else 0.0


def _hide_only(scene, hidden) -> None:
    hidden = set(hidden)
    for obj in scene.objects:
        obj.hide_render = obj.hide_render or obj in hidden


def _show_only(scene, keep) -> None:
    for obj in scene.objects:
        obj.hide_render = obj is not keep


def render(scene, camera: dict, mode: str, size: int, out: Path, *, aspect: float = 1.0,
           sketch=None, targets=(), strokes_out: Path | None = None,
           keep_strokes: Callable[[int, int], bool] | None = None, only=None) -> dict:
    """Renders one image to `out`. Overlay mode also writes the strokes-only PNG
    to `strokes_out`, showing only the strokes whose (turn, amend) stamps pass
    keep_strokes when it is given. With `only`, every other object is left
    out of the render. Returns {path, strokes_path, width, height, ms}."""
    if mode not in ("shaded", "wireframe", "matcap", "overlay"):
        raise ValueError(f"unknown render mode {mode!r}")
    start = time.perf_counter()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = resolution(min(int(size), MAX_SIZE), aspect)
    base_tmp = out.with_name(f".{out.stem}.base.png")
    strokes_tmp = out.with_name(f".{out.stem}.strokes.png")
    try:
        with render_settings(scene), temp_camera(scene, camera):
            scene.render.resolution_x, scene.render.resolution_y = width, height
            _set_mode(scene, "shaded" if mode == "overlay" else mode)
            if sketch is not None:
                _hide_only(scene, [sketch])
            if only is not None:
                keep = {o.as_pointer() for o in only}
                _hide_only(scene, [o for o in scene.objects if o.as_pointer() not in keep])
            if mode == "wireframe":
                with _wireframes(targets or [o for o in scene.objects if o.type == "MESH"]):
                    _render_to(scene, base_tmp)
            else:
                _render_to(scene, base_tmp)
            if mode == "overlay":
                if sketch is None:
                    raise ValueError("overlay renders need the sketch object")
                _show_only(scene, sketch)
                if keep_strokes is None:
                    _render_to(scene, strokes_tmp)
                else:
                    with sketch_strokes.isolate_strokes(sketch, keep_strokes):
                        _render_to(scene, strokes_tmp)
        base = flatten(load_pixels(base_tmp))
        strokes_path = None
        if mode == "overlay":
            strokes = load_pixels(strokes_tmp)
            strokes_path = Path(strokes_out) if strokes_out else out.with_name(f"{out.stem}-strokes.png")
            strokes_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(strokes_tmp, strokes_path)
            save_pixels(composite(strokes, base), out)
        else:
            save_pixels(base, out)
    finally:
        for tmp in (base_tmp, strokes_tmp):
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
    return {"path": str(out), "strokes_path": str(strokes_path) if strokes_path else None,
            "width": width, "height": height, "ms": round((time.perf_counter() - start) * 1000, 1)}
