# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerates the crate request bundle (JSON, view cameras and images).

    timeout 120 blender -b --factory-startup --python tests/fixtures/crate/make_bundle.py

The outputs are committed; tests only read them.
"""

import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402

from tests.fixtures.crate.scene import build_scene  # noqa: E402
from whittle import formats  # noqa: E402
from whittle.addon import render, sketch  # noqa: E402

OUT = HERE / "request"
REGION = (800, 600)
RADIUS = 0.006

VIEWS = {
    1: {"location": (1.3, -1.5, 1.1), "look_at": (0.0, 0.0, 0.3)},
    2: {"location": (0.0, -2.0, 0.45), "look_at": (0.0, 0.0, 0.35)},
}


def make_view(view_id: int, location, look_at) -> formats.View:
    spec = render.camera_from_look_at(location, look_at, 50.0)
    width, height = REGION
    scene = bpy.context.scene
    with render.temp_camera(scene, spec) as cam:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        projection = cam.calc_matrix_camera(depsgraph, x=width, y=height)
    view_matrix = Matrix(spec["matrix_world"]).inverted()
    return formats.View(
        id=view_id,
        view_matrix=[list(r) for r in view_matrix],
        window_matrix=[list(r) for r in projection],
        is_perspective=True,
        width=width,
        height=height,
        from_camera=None,
        camera=spec,
    )


def stroke(index, kind, view, points, cyclic, on_surface=False, normal=None, hit=None):
    n = len(points)
    return formats.Stroke(
        index=index, type=kind, view=view, cyclic=cyclic,
        points=[[round(c, 5) for c in p] for p in points],
        radius=[RADIUS] * n, opacity=[1.0] * n,
        on_surface=[on_surface] * n, normal=[normal] * n, hit_object=[hit] * n,
    )


def lid_outline(z=0.56, half=0.27, per_side=5):
    corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
    points = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        for i in range(per_side):
            t = i / per_side
            # A slight wobble, as a hand-drawn stroke would have.
            wobble = 0.004 * math.sin(7 * (len(points) + 1))
            points.append((x0 + (x1 - x0) * t + wobble, y0 + (y1 - y0) * t - wobble, z))
    return points


def handle_slot(center=(0.0, -0.2501, 0.38), rx=0.09, rz=0.028, count=14):
    cx, cy, cz = center
    return [(cx + rx * math.cos(2 * math.pi * i / count), cy, cz + rz * math.sin(2 * math.pi * i / count))
            for i in range(count)]


def main():
    build_scene()
    strokes = [
        stroke(0, "add", 1, lid_outline(), cyclic=True),
        stroke(1, "add", 2, [(-0.27 + 0.054 * i, -0.27, 0.56 + 0.003 * math.sin(i)) for i in range(11)],
               cyclic=False),
        stroke(2, "carve", 2, handle_slot(), cyclic=True, on_surface=True,
               normal=[0.0, -1.0, 0.0], hit="Crate"),
    ]
    views = [make_view(i, **v) for i, v in VIEWS.items()]
    request = formats.Request(
        node="n0001", parent="n0000",
        prompt="Add a lid that overhangs the crate slightly, and carve a handle slot in the front.",
        target=[{"uid": "fixture-crate", "name": "Crate", "type": "MESH"}],
        stroke_types=["add", "carve"], views=[v.id for v in views], refs=[],
        units={"system": "METRIC", "scale_length": 1.0},
        settings={"self_check_rounds": 2, "poly_budget": 500, "style_notes": ""},
    )
    formats.write_request(OUT, request, strokes, views)

    scene = bpy.context.scene
    sketch_obj = sketch.load_strokes(scene, strokes)
    for view in views:
        folder = OUT / "views" / str(view.id)
        render.render(scene, view.camera, "overlay", 512, folder / "overlay.png", aspect=view.aspect,
                      sketch=sketch_obj, strokes_out=folder / "strokes.png")
    formats.read_bundle(OUT)
    print("bundle written to", OUT)


main()
sys.stdout.flush()
os._exit(0)
