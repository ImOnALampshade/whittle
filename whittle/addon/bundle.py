# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes a request bundle from the live sketch: request.json, strokes.json,
views/<id>/{camera.json, overlay.png, strokes.png} and refs/.

The writer only reads the sketch; the one change it makes to the file is the
whittle_uid it gives target objects that lack one.
"""

import os
import re
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

import bpy
from mathutils import Vector

from .. import formats
from . import render, sketch, views

UID_PROP = "whittle_uid"
# A point is on a surface when it lies within this distance of the first hit
# along its view ray, measured across the surface: metres plus a fraction of
# the point's depth. The draw tool places points short of an oblique surface
# along the line of sight (exact head-on, about 5 cm at 2.5 m on a face seen
# at 11 degrees), so the gap along the ray would grow as 1/cos of the angle;
# along the ray it may be this many times the tolerance.
SURFACE_TOLERANCE = (0.001, 0.01)
SURFACE_GRAZING = 10.0
SETTINGS_KEYS = ("self_check_rounds", "poly_budget", "style_notes")


class BundleError(Exception):
    pass


def ensure_uid(obj) -> str:
    uid = obj.get(UID_PROP)
    if not isinstance(uid, str) or not uid:
        uid = uuid.uuid4().hex
        obj[UID_PROP] = uid
    return uid


def target_entries(objects) -> list[dict]:
    return [{"uid": ensure_uid(o), "name": o.name, "type": o.type} for o in objects]


def _r(value: float, digits: int) -> float:
    # + 0.0 turns -0.0 into 0.0.
    return round(float(value), digits) + 0.0


def surface_info(scene, depsgraph, view: formats.View, points) -> tuple[list, list, list]:
    """For each world point: on_surface, the surface normal and the object hit
    (None off the surface). The ray runs along the view's line of sight to the
    point; an orthographic ray starts at the render camera's eye plane, which
    lies in front of everything the viewport showed."""
    eye = Vector([row[3] for row in view.camera["matrix_world"][:3]])
    _view_eye, forward = views.eye_and_forward(view)
    abs_tol, rel_tol = SURFACE_TOLERANCE
    on_surface, normals, hits = [], [], []
    for co in points:
        p = Vector(co)
        if view.is_perspective:
            origin = eye
            offset = p - eye
            depth = offset.length
            direction = offset.normalized() if depth > 1e-9 else forward
        else:
            depth = (p - eye).dot(forward)
            origin = p - forward * depth
            direction = forward
        hit, location, normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction)
        tol = abs_tol + rel_tol * abs(depth)
        if (hit and abs((p - location).dot(normal.normalized())) <= tol
                and abs((location - origin).length - depth) <= SURFACE_GRAZING * tol):
            on_surface.append(True)
            normals.append([_r(c, 4) for c in normal.normalized()])
            hits.append(obj.name if obj is not None else None)
        else:
            on_surface.append(False)
            normals.append(None)
            hits.append(None)
    return on_surface, normals, hits


StrokeFilter = Callable[[int, int], bool]


def gather_strokes(scene, depsgraph, sketch_obj, views_by_id: dict[int, formats.View],
                   fallback_view: int | None, stroke_filter: StrokeFilter | None = None
                   ) -> list[formats.Stroke]:
    """Every visible stroke in type order, then stroke order, or only those
    whose (turn, amend) stamps pass stroke_filter. Untagged strokes, and any
    whose view is gone, get fallback_view."""
    strokes = []
    for s in sketch.iter_strokes(sketch_obj):
        if stroke_filter is not None and not stroke_filter(s.turn, s.amend):
            continue
        view_id = s.view if s.view in views_by_id else fallback_view
        if view_id is None:
            raise BundleError("there is no sketch view yet: capture a view before submitting")
        on_surface, normals, hits = surface_info(scene, depsgraph, views_by_id[view_id], s.points)
        strokes.append(formats.Stroke(
            index=len(strokes), type=s.layer, view=view_id, cyclic=s.cyclic,
            points=[[_r(c, 5) for c in p] for p in s.points],
            radius=[_r(r, 5) for r in s.radius],
            opacity=[_r(o, 3) for o in s.opacity],
            on_surface=on_surface, normal=normals, hit_object=hits,
        ))
    return strokes


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def check_refs(paths) -> None:
    missing = [str(p) for p in paths if not Path(p).is_file()]
    if missing:
        raise BundleError(f"reference image not found: {', '.join(missing)}")


def copy_refs(paths, dest_dir: Path) -> list[str]:
    """Copies reference images under unique, filesystem-safe names; returns
    their bundle-relative paths."""
    sources = [Path(p) for p in paths]
    check_refs(sources)
    names, taken = [], set()
    for src in sources:
        stem = _UNSAFE.sub("_", src.stem).strip("._") or "ref"
        suffix = _UNSAFE.sub("", src.suffix.lower())
        name, n = f"{stem}{suffix}", 1
        while name in taken:
            n += 1
            name = f"{stem}-{n}{suffix}"
        taken.add(name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest_dir / name)
        names.append(f"refs/{name}")
    return names


def write_bundle(dest, *, scene, sketch_obj, node: str, parent: str | None, prompt: str,
                 targets, refs=(), settings: dict, render_size: int = 512,
                 depsgraph=None, amend: int | None = None,
                 stroke_filter: StrokeFilter | None = None,
                 target_collection: str | None = None) -> formats.Bundle:
    """Writes the request folder at dest, which must not exist yet. Everything
    goes into a hidden sibling folder first and is validated, so dest either
    holds a whole bundle or nothing.

    An amendment bundle passes its number and a stroke_filter on the strokes'
    (turn, amend) stamps; its overlays then show only the strokes it holds."""
    dest = Path(dest)
    if dest.exists():
        raise BundleError(f"{dest} already exists")
    # Checked before anything is created, so a missing image leaves no trace.
    check_refs(refs)
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    stored = views.load_views(sketch_obj.data) if sketch_obj is not None else []
    by_id = {v.id: v for v in stored}
    latest = max(stored, key=lambda v: v.id, default=None)

    strokes = []
    if sketch_obj is not None:
        strokes = gather_strokes(scene, depsgraph, sketch_obj, by_id, latest.id if latest else None,
                                 stroke_filter)
    used = sorted({s.view for s in strokes})
    if not strokes and latest is not None:
        used = [latest.id]
    bundle_views = [by_id[i] for i in used]
    present = {s.type for s in strokes}

    request = formats.Request(
        node=node, parent=parent, prompt=prompt,
        target=target_entries(targets),
        stroke_types=[t for t in formats.STROKE_TYPES if t in present],
        views=used,
        units={"system": scene.unit_settings.system,
               # The property is single precision; 0.01 should not read 0.0099999998.
               "scale_length": float(f"{scene.unit_settings.scale_length:.7g}")},
        settings={k: settings[k] for k in SETTINGS_KEYS if k in settings},
        amend=amend,
        target_collection=target_collection,
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.{uuid.uuid4().hex[:8]}.tmp"
    tmp.mkdir()
    try:
        request.refs = copy_refs(refs, tmp / "refs")
        formats.write_request(tmp, request, strokes, bundle_views)
        for view in bundle_views:
            folder = tmp / "views" / str(view.id)
            render.render(scene, view.camera, "overlay", render_size, folder / "overlay.png",
                          aspect=view.aspect, sketch=sketch_obj, targets=list(targets),
                          strokes_out=folder / "strokes.png", keep_strokes=stroke_filter)
        formats.read_bundle(tmp)
        os.rename(tmp, dest)
    except BaseException as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        if isinstance(exc, (formats.FormatError, OSError)):
            raise BundleError(f"cannot write the request bundle: {exc}") from exc
        raise
    return formats.read_bundle(dest)
