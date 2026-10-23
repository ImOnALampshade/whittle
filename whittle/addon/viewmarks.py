# SPDX-License-Identifier: GPL-3.0-or-later
"""View markers: while sketching, a small camera in the viewport where each
sketch view was captured, pointing the way it looked. Clicking one runs
whittle.view_snap, which moves the viewport back to that view.

A gizmo group, so Blender does the hovering, the picking and the click; the
markers keep a constant size on screen. The viewport's Gizmos overlay
toggle hides them with every other gizmo, and
WindowManager.whittle_show_view_markers hides only them."""

import math

import bpy
from mathutils import Matrix

from . import sketch, views

SHOW_PROP = "whittle_show_view_markers"
# Size on screen, as a fraction of the gizmo size preference.
SCALE = 0.6
LINE_WIDTH = 2.0
COLOUR = (0.85, 0.85, 0.85)
CURRENT_COLOUR = (1.0, 0.6, 0.15)
HIGHLIGHT_COLOUR = (1.0, 1.0, 1.0)
ALPHA = 0.7
# A perspective frustum's depth for its long side of 1, kept in bounds so a
# very wide or narrow lens still reads as a camera.
DEPTH_RANGE = (0.35, 1.4)
ORTHO_DEPTH = 0.7


def shown(context) -> bool:
    return (sketch.current_session() is not None
            and bool(getattr(context.window_manager, SHOW_PROP, False)))


def marker_shape(view) -> tuple[list, list]:
    """(line vertices, triangle vertices) of a view's marker in its camera
    space (looking down -Z, +Y up), long side 1: a frustum from the eye for
    a perspective view, a box for an orthographic one, each with a triangle
    above it marking up. The triangles are what a click picks."""
    width, height = max(1, view.width), max(1, view.height)
    if width >= height:
        hx, hy = 0.5, 0.5 * height / width
    else:
        hx, hy = 0.5 * width / height, 0.5
    if view.is_perspective:
        depth = 0.5 / math.tan(view.camera["angle"] / 2.0)
        depth = min(max(depth, DEPTH_RANGE[0]), DEPTH_RANGE[1])
        near = [(0.0, 0.0, 0.0)] * 4
    else:
        depth = ORTHO_DEPTH
        near = [(-hx, -hy, 0.0), (hx, -hy, 0.0), (hx, hy, 0.0), (-hx, hy, 0.0)]
    far = [(-hx, -hy, -depth), (hx, -hy, -depth), (hx, hy, -depth), (-hx, hy, -depth)]
    up = [(-hx * 0.6, hy * 1.15, -depth), (hx * 0.6, hy * 1.15, -depth), (0.0, hy * 1.15 + hx * 0.5, -depth)]
    lines = []
    for i in range(4):
        j = (i + 1) % 4
        lines += [near[i], far[i], far[i], far[j]]
        if not view.is_perspective:
            lines += [near[i], near[j]]
    lines += [up[0], up[1], up[1], up[2], up[2], up[0]]
    tris = [far[0], far[1], far[2], far[0], far[2], far[3], *up]
    for i in range(4):
        j = (i + 1) % 4
        tris += [near[i], far[i], far[j]]
        if not view.is_perspective:
            tris += [near[i], far[j], near[j]]
    return lines, tris


def marker_matrix(view) -> Matrix:
    """The marker's placement: the view's eye and orientation, unscaled."""
    world = Matrix(view.view_matrix).inverted()
    return Matrix.Translation(world.translation) @ world.to_3x3().normalized().to_4x4()


def viewport_view(region, rv3d):
    """What the viewport shows now, as a view, to hide the marker it is at."""
    if region is None or rv3d is None:
        return None
    return views.view_from_matrices(0, rv3d.view_matrix, rv3d.window_matrix, region.width, region.height)


class WHITTLE_GT_view(bpy.types.Gizmo):
    """One view's marker."""
    bl_idname = "WHITTLE_GT_view"
    __slots__ = ("lines", "tris", "key")

    def setup(self):
        self.lines = self.tris = self.key = None

    def set_shape(self, view, key) -> None:
        lines, tris = marker_shape(view)
        self.lines = self.new_custom_shape("LINES", lines)
        self.tris = self.new_custom_shape("TRIS", tris)
        self.key = key

    def draw(self, context):
        if self.lines is not None:
            self.draw_custom_shape(self.lines)

    def draw_select(self, context, select_id):
        if self.tris is not None:
            self.draw_custom_shape(self.tris, select_id=select_id)


class WHITTLE_GGT_views(bpy.types.GizmoGroup):
    """The markers of the sketch's views, kept in step with them as the
    viewport redraws."""
    bl_idname = "WHITTLE_GGT_views"
    bl_label = "Whittle Sketch Views"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context):
        return shown(context)

    def setup(self, context):
        self.marks = {}

    def draw_prepare(self, context):
        obj = sketch.find_sketch_object()
        stored = views.load_views(obj.data) if obj is not None else []
        current = views.current_view(obj.data) if obj is not None else None
        sync(self, stored, current.id if current is not None else None,
             viewport_view(context.region, context.region_data),
             getattr(context.region_data, "view_distance", 1.0))


def sync(group, stored, current_id, here, view_distance) -> None:
    """Makes the group's markers match the stored views: one per view, the
    current one coloured, and the one the viewport is at hidden."""
    marks = group.marks
    wanted = {v.id: v for v in stored}
    for view_id in [i for i in marks if i not in wanted]:
        group.gizmos.remove(marks.pop(view_id))
    for view_id, view in wanted.items():
        key = (view.view_matrix, view.window_matrix, view.width, view.height)
        gz = marks.get(view_id)
        if gz is None:
            gz = group.gizmos.new(WHITTLE_GT_view.bl_idname)
            gz.target_set_operator("whittle.view_snap").id = view_id
            gz.use_draw_scale = True
            gz.scale_basis = SCALE
            gz.line_width = LINE_WIDTH
            gz.alpha = ALPHA
            gz.color_highlight = HIGHLIGHT_COLOUR
            gz.alpha_highlight = 1.0
            marks[view_id] = gz
        if gz.key != key:
            gz.set_shape(view, key)
            gz.matrix_basis = marker_matrix(view)
        gz.color = CURRENT_COLOUR if view_id == current_id else COLOUR
        gz.hide = here is not None and views.same_place(view, here, view_distance)


CLASSES = (WHITTLE_GT_view, WHITTLE_GGT_views)
