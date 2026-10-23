# SPDX-License-Identifier: GPL-3.0-or-later
"""Strokes and viewports for sketch tests. The data API stands in for the draw
tool, and fake viewports stand in for RegionView3D, whose matrices are never
recomputed in background Blender."""

from types import SimpleNamespace

import bpy
from mathutils import Matrix

from whittle import formats
from whittle.addon import render, sketch, views


def add_stroke(obj, stroke_type, points, *, radius=None, opacity=None, cyclic=False, view=0, turn=0):
    """Appends a stroke to the type's layer (positions are layer-local) and
    returns its index in that layer's drawing."""
    layer, drawing = sketch.ensure_layer(obj.data, stroke_type)
    drawing.add_strokes([len(points)])
    index = len(drawing.strokes) - 1
    stroke = drawing.strokes[index]
    for i, (point, co) in enumerate(zip(stroke.points, points)):
        point.position = co
        if radius is not None:
            point.radius = radius[i] if isinstance(radius, (list, tuple)) else radius
        if opacity is not None:
            point.opacity = opacity[i] if isinstance(opacity, (list, tuple)) else opacity
    if cyclic:
        stroke.cyclic = True
    if view:
        sketch.ensure_int_attribute(drawing, sketch.VIEW_ATTRIBUTE).data[index].value = view
    if turn:
        sketch.ensure_int_attribute(drawing, sketch.TURN_ATTRIBUTE).data[index].value = turn
    return index


def look_at_view(view_id, location, look_at, size=(800, 600), ortho=False, ortho_scale=3.0,
                 lens_mm=50.0, clip=(0.01, 1000.0)) -> formats.View:
    """A view as the viewport would report it, built from a real camera's matrices."""
    spec = render.camera_from_look_at(location, look_at, lens_mm)
    spec["clip_start"], spec["clip_end"] = clip
    if ortho:
        spec["type"], spec["ortho_scale"] = "ORTHO", ortho_scale
    width, height = size
    scene = bpy.context.scene
    with render.temp_camera(scene, spec) as cam:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        projection = cam.calc_matrix_camera(depsgraph, x=width, y=height)
    return views.view_from_matrices(view_id, Matrix(spec["matrix_world"]).inverted(), projection,
                                    width, height)


def fake_viewport(view: formats.View, view_distance: float = 2.0) -> views.Viewport:
    rv3d = SimpleNamespace(
        view_matrix=Matrix(view.view_matrix), window_matrix=Matrix(view.window_matrix),
        view_perspective="PERSP" if view.is_perspective else "ORTHO",
        is_perspective=view.is_perspective, view_distance=view_distance)
    region = SimpleNamespace(width=view.width, height=view.height, type="WINDOW")
    return views.Viewport(area=SimpleNamespace(type="VIEW_3D"), region=region, rv3d=rv3d)
