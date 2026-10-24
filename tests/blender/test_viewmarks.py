# SPDX-License-Identifier: GPL-3.0-or-later
"""View markers and Snap to View: the pose a snap gives the viewport, the
view new strokes go to afterwards, the markers' shape and how the gizmo
group keeps them in step. Background Blender draws no gizmos and never
recomputes a viewport's matrices, so drawing and clicking are covered by
the view_markers screenshot scenario and a check by hand
(docs/progress.md)."""

import math
import unittest
from types import SimpleNamespace
from unittest import mock

import bpy
from mathutils import Matrix, Vector

from tests.blender.sketch_helpers import add_stroke, fake_viewport, look_at_view
from tests.fixtures.crate.scene import build_scene
from whittle.addon import operators, sketch, viewmarks, views


def assert_close(test, a, b, tol=1e-4):
    for x, y in zip(a, b):
        test.assertAlmostEqual(x, y, delta=tol)


def view_matrix_of(pose):
    """The view matrix a viewport in this pose has, as Blender builds it: an
    orthographic eye sits at the pivot, a perspective one distance behind it."""
    rotation = pose.rotation.to_matrix().to_4x4()
    back = pose.distance if pose.perspective == "PERSP" else 0.0
    return (Matrix.Translation((0.0, 0.0, -back)) @ rotation.inverted()
            @ Matrix.Translation(-Vector(pose.location)))


def snap_viewport_stub(lens=50.0, distance=4.0, perspective="CAMERA"):
    rv3d = SimpleNamespace(view_perspective=perspective, view_rotation=None, view_location=None,
                           view_distance=distance)
    area = SimpleNamespace(type="VIEW_3D", spaces=SimpleNamespace(active=SimpleNamespace(lens=lens)),
                           tag_redraw=mock.Mock())
    return views.Viewport(area=area, region=SimpleNamespace(width=800, height=600, type="WINDOW"), rv3d=rv3d)


class SnapPoseTest(unittest.TestCase):
    def setUp(self):
        build_scene()

    def test_perspective_keeps_the_eye_and_direction(self):
        view = look_at_view(1, (1.5, -2.0, 1.2), (0, 0, 0.3), lens_mm=35.0)
        pose = views.snap_pose(view, 3.0, 50.0)
        self.assertEqual(pose.perspective, "PERSP")
        self.assertEqual(pose.distance, 3.0)
        for got, want in zip(view_matrix_of(pose), Matrix(view.view_matrix)):
            assert_close(self, got, want)

    def test_perspective_lens_gives_the_field_of_view(self):
        # The viewport shows 2 * atan(36 / lens) across its long side.
        view = look_at_view(1, (0, -2, 0.3), (0, 0, 0.3), lens_mm=35.0)
        pose = views.snap_pose(view, 2.0, 50.0)
        self.assertAlmostEqual(2.0 * math.atan(36.0 / pose.lens), view.camera["angle"], places=5)
        view.camera["angle"] = math.radians(178.0)
        self.assertEqual(views.snap_pose(view, 2.0, 50.0).lens, views.LENS_RANGE[0], "clamped to the lens range")

    def test_orthographic_keeps_the_lens_and_sets_the_scale(self):
        view = look_at_view(1, (0, -5, 0.3), (0, 0, 0.3), ortho=True, ortho_scale=3.0)
        pose = views.snap_pose(view, 9.0, 40.0)
        self.assertEqual((pose.perspective, pose.lens), ("ORTHO", 40.0))
        # 72 / lens times the view distance across the long side.
        self.assertAlmostEqual(72.0 * pose.distance / 40.0, view.camera["ortho_scale"], places=5)
        for got, want in zip(view_matrix_of(pose), Matrix(view.view_matrix)):
            assert_close(self, got, want)

    def test_snap_viewport_leaves_camera_view(self):
        view = look_at_view(1, (1.5, -2.0, 1.2), (0, 0, 0.3), lens_mm=35.0)
        vp = snap_viewport_stub()
        pose = views.snap_viewport(vp, view)
        rv3d = vp.rv3d
        self.assertEqual(rv3d.view_perspective, "PERSP")
        self.assertEqual(rv3d.view_distance, 4.0, "the viewport's own pivot distance by default")
        self.assertEqual(rv3d.view_rotation, pose.rotation)
        self.assertEqual(rv3d.view_location, pose.location)
        self.assertEqual(vp.area.spaces.active.lens, pose.lens)
        vp.area.tag_redraw.assert_called_once()

    def test_snap_a_real_viewport(self):
        # The startup file's 3D viewport keeps its data in background Blender.
        area = next(a for s in bpy.data.screens for a in s.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        vp = views.Viewport(area, region, area.spaces.active.region_3d)
        view = look_at_view(1, (1.5, -2.0, 1.2), (0, 0, 0.3), lens_mm=35.0)
        pose = views.snap_viewport(vp, view, 2.5)
        self.assertEqual(vp.rv3d.view_perspective, "PERSP")
        self.assertAlmostEqual(vp.rv3d.view_distance, 2.5, places=5)
        assert_close(self, vp.rv3d.view_location, pose.location)
        self.assertAlmostEqual(vp.area.spaces.active.lens, pose.lens, places=3)

    def test_same_place(self):
        a = look_at_view(1, (0, -2, 0.3), (0, 0, 0.3))
        self.assertTrue(views.same_place(a, look_at_view(2, (0, -2, 0.3), (0, 0, 0.3)), 2.0))
        self.assertFalse(views.same_place(a, look_at_view(2, (0, -2.2, 0.3), (0, 0, 0.3)), 2.0))
        self.assertFalse(views.same_place(a, look_at_view(2, (0, -2, 0.3), (0.2, 0, 0.3)), 2.0))
        self.assertFalse(views.same_place(a, look_at_view(2, (0, -2, 0.3), (0, 0, 0.3), ortho=True), 2.0))


class CurrentViewTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        self.gp = bpy.data.grease_pencils.new("Current View Test")
        self.addCleanup(bpy.data.grease_pencils.remove, self.gp)

    def make(self, view_id):
        return look_at_view(view_id, (0, -2, 0.3), (0, 0, 0.3))

    def test_latest_unless_snapped_back(self):
        self.assertIsNone(views.current_view(self.gp))
        for _ in range(3):
            views.add_view(self.gp, self.make)
        self.assertEqual(views.current_view(self.gp).id, 3)
        views.set_current_view(self.gp, 1)
        self.assertEqual(views.current_view(self.gp).id, 1)
        views.prune_views(self.gp, set())
        self.assertEqual([v.id for v in views.load_views(self.gp)], [1], "the current view is kept")
        views.add_view(self.gp, self.make)
        self.assertEqual(views.current_view(self.gp).id, 4, "a new view is current")

    def test_a_removed_current_view_falls_back_to_the_latest(self):
        for _ in range(2):
            views.add_view(self.gp, self.make)
        views.set_current_view(self.gp, 1)
        views.save_views(self.gp, [v for v in views.load_views(self.gp) if v.id != 1])
        self.assertEqual(views.current_view(self.gp).id, 2)
        views.set_current_view(self.gp, 2)
        views.clear_views(self.gp)
        self.assertNotIn(views.CURRENT_VIEW_PROP, self.gp)

    def test_merged_views_are_current_again(self):
        views.add_view(self.gp, self.make)
        views.set_current_view(self.gp, 1)
        views.merge_views(self.gp, [self.make(5)])
        self.assertEqual(views.current_view(self.gp).id, 5)


class SnapToViewTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        old = sketch.find_sketch_object()
        if old is not None:
            bpy.data.objects.remove(old)
        self.obj = sketch.ensure_sketch_layers(bpy.context.scene)
        self.addCleanup(lambda: sketch.find_sketch_object() and bpy.data.objects.remove(sketch.find_sketch_object()))
        self.front = views.add_view(self.obj.data, lambda i: look_at_view(i, (0, -3, 0.3), (0, 0, 0.3)))
        self.side = views.add_view(self.obj.data, lambda i: look_at_view(i, (3, 0, 0.3), (0, 0, 0.3)))

    def snap(self, view_id, vp=None):
        vp = vp or snap_viewport_stub()
        with mock.patch.object(views, "viewport_from_context", lambda context: vp):
            return operators.snap_to_view(bpy.context, view_id), vp

    def test_snaps_and_makes_the_view_current(self):
        add_stroke(self.obj, "free", [(0, 0.5, 0.3), (0.1, 0.5, 0.3)], view=1)
        pending = add_stroke(self.obj, "add", [(0, 0, 0.3), (0.1, 0, 0.3)])
        view, vp = self.snap(1)
        self.assertEqual(view.id, 1)
        self.assertEqual(views.current_view(self.obj.data).id, 1)
        _layer, drawing = sketch.ensure_layer(self.obj.data, "add")
        self.assertEqual(sketch._curve_ints(drawing, sketch.VIEW_ATTRIBUTE)[pending], 2,
                         "strokes drawn before the snap belong to the view before it")
        self.assertAlmostEqual(vp.rv3d.view_distance, 3.5, places=4, msg="the pivot at the view's strokes")
        assert_close(self, vp.rv3d.view_location, (0, 0.5, 0.3))

    def test_without_strokes_the_pivot_distance_stays(self):
        _view, vp = self.snap(2)
        self.assertEqual(vp.rv3d.view_distance, 4.0)

    def test_refusals(self):
        with self.assertRaisesRegex(RuntimeError, "no view 9"):
            self.snap(9)
        with mock.patch.object(views, "viewport_from_context", lambda context: None):
            with self.assertRaisesRegex(RuntimeError, "3D viewport"):
                operators.snap_to_view(bpy.context, 1)
        bpy.data.objects.remove(self.obj)
        with self.assertRaisesRegex(RuntimeError, "no sketch"):
            self.snap(1)

    def test_strokes_drawn_after_the_snap_get_its_view(self):
        self.snap(1)
        here = fake_viewport(self.front)
        session = sketch.SketchSession(bpy.context.scene, viewport_provider=lambda: here, use_timer=False)
        session.active = True
        index = add_stroke(self.obj, "free", [(0, 0, 0.3), (0.1, 0, 0.3)])
        session.poll()
        _layer, drawing = sketch.ensure_layer(self.obj.data, "free")
        self.assertEqual(sketch._curve_ints(drawing, sketch.VIEW_ATTRIBUTE)[index], 1)
        self.assertEqual([v.id for v in views.load_views(self.obj.data)], [1, 2], "no new view")


class MarkerShapeTest(unittest.TestCase):
    def setUp(self):
        build_scene()

    def test_perspective_is_a_frustum_from_the_eye(self):
        view = look_at_view(1, (0, -2, 0.3), (0, 0, 0.3), size=(800, 400))
        lines, tris = viewmarks.marker_shape(view)
        self.assertEqual(len(lines) % 2, 0)
        self.assertEqual(len(tris) % 3, 0)
        self.assertIn((0.0, 0.0, 0.0), lines, "the apex is the eye")
        self.assertTrue(all(z <= 0.0 for _x, _y, z in lines), "it points the way the view looked")
        depth = -min(z for _x, _y, z in tris)
        self.assertIn((0.5, 0.25, -depth), tris, "the long side is 1, the short one as the view's aspect")
        self.assertIn((-0.5, -0.25, -depth), tris)
        self.assertEqual(max(abs(x) for x, _y, _z in tris), 0.5)

    def test_orthographic_is_a_box(self):
        view = look_at_view(1, (0, -2, 0.3), (0, 0, 0.3), ortho=True)
        lines, _tris = viewmarks.marker_shape(view)
        self.assertNotIn((0.0, 0.0, 0.0), lines)
        self.assertEqual(len({p for p in lines if p[2] == 0.0}), 4, "a near face as wide as the far one")

    def test_matrix_is_the_eye_and_orientation(self):
        view = look_at_view(1, (1, -2, 0.5), (0, 0, 0.3))
        matrix = viewmarks.marker_matrix(view)
        eye, forward = views.eye_and_forward(view)
        assert_close(self, matrix.translation, eye)
        assert_close(self, matrix.to_3x3() @ Vector((0, 0, -1)), forward)
        self.assertAlmostEqual(matrix.to_3x3().determinant(), 1.0, places=5)


class FakeGizmo:
    def __init__(self):
        self.operator = None
        self.shapes = 0
        self.key = None
        self.hide = False

    def target_set_operator(self, idname):
        self.operator = (idname, SimpleNamespace(id=0))
        return self.operator[1]

    def set_shape(self, view, key):
        self.shapes += 1
        self.key = key


class FakeGroup:
    def __init__(self):
        self.marks = {}
        self.made = []
        self.gizmos = SimpleNamespace(new=self.new, remove=lambda gz: self.made.remove(gz))

    def new(self, idname):
        assert idname == "WHITTLE_GT_view"
        self.made.append(FakeGizmo())
        return self.made[-1]


class SyncTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        self.front = look_at_view(1, (0, -3, 0.3), (0, 0, 0.3))
        self.side = look_at_view(2, (3, 0, 0.3), (0, 0, 0.3))

    def test_one_marker_per_view_that_clicks_to_snap(self):
        group = FakeGroup()
        viewmarks.sync(group, [self.front, self.side], 2, None, 3.0)
        self.assertEqual(sorted(group.marks), [1, 2])
        for view_id, gz in group.marks.items():
            idname, props = gz.operator
            self.assertEqual((idname, props.id), ("whittle.view_snap", view_id))
            self.assertTrue(gz.use_draw_scale, "a constant size on screen")
            assert_close(self, gz.matrix_basis.translation, views.eye_and_forward(
                self.front if view_id == 1 else self.side)[0])
        self.assertEqual(group.marks[2].color, viewmarks.CURRENT_COLOUR)
        self.assertEqual(group.marks[1].color, viewmarks.COLOUR)

    def test_follows_the_views(self):
        group = FakeGroup()
        viewmarks.sync(group, [self.front, self.side], 2, None, 3.0)
        first = group.marks[1]
        viewmarks.sync(group, [self.front], 1, None, 3.0)
        self.assertEqual(list(group.marks), [1])
        self.assertIs(group.marks[1], first, "kept, not made again")
        self.assertEqual(first.shapes, 1, "its shape is only made again when the view changes")
        self.assertEqual(len(group.made), 1, "the removed view's marker is gone")
        self.assertEqual(first.color, viewmarks.CURRENT_COLOUR)

    def test_the_current_marker_takes_the_colour_given(self):
        group = FakeGroup()
        viewmarks.sync(group, [self.front, self.side], 2, None, 3.0, (0.1, 0.9, 0.2))
        self.assertEqual(group.marks[2].color, (0.1, 0.9, 0.2))
        self.assertEqual(group.marks[1].color, viewmarks.COLOUR)

    def test_the_colour_is_the_themes_active_item(self):
        theme = bpy.context.preferences.themes[0].user_interface.wcol_list_item
        old = tuple(theme.inner_sel)
        self.addCleanup(setattr, theme, "inner_sel", old)
        assert_close(self, viewmarks.current_colour(bpy.context), viewmarks.CURRENT_COLOUR, tol=0.01)
        theme.inner_sel = (0.9, 0.1, 0.5, 1.0)
        assert_close(self, viewmarks.current_colour(bpy.context), (0.9, 0.1, 0.5), tol=0.01)
        self.assertEqual(viewmarks.current_colour(SimpleNamespace(preferences=None)), viewmarks.CURRENT_COLOUR)

    def test_the_marker_the_viewport_is_at_hides(self):
        group = FakeGroup()
        here = look_at_view(0, (0, -3, 0.3), (0, 0, 0.3))
        viewmarks.sync(group, [self.front, self.side], 2, here, 3.0)
        self.assertTrue(group.marks[1].hide)
        self.assertFalse(group.marks[2].hide)


class GroupTest(unittest.TestCase):
    def setUp(self):
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)

    def test_registered(self):
        self.assertIs(bpy.types.GizmoGroup.bl_rna_get_subclass_py("WHITTLE_GGT_views"), viewmarks.WHITTLE_GGT_views)
        self.assertIs(bpy.types.Gizmo.bl_rna_get_subclass_py("WHITTLE_GT_view"), viewmarks.WHITTLE_GT_view)

    def test_shown_while_sketching_unless_turned_off(self):
        wm = bpy.context.window_manager
        self.assertTrue(getattr(wm, viewmarks.SHOW_PROP), "on by default")
        self.assertFalse(viewmarks.shown(bpy.context), "not while not sketching")
        with mock.patch.object(viewmarks.sketch, "current_session", return_value=object()):
            self.assertTrue(viewmarks.shown(bpy.context))
            setattr(wm, viewmarks.SHOW_PROP, False)
            self.addCleanup(setattr, wm, viewmarks.SHOW_PROP, True)
            self.assertFalse(viewmarks.shown(bpy.context))


if __name__ == "__main__":
    unittest.main()
