# SPDX-License-Identifier: GPL-3.0-or-later
import json
import math
import unittest
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

from tests.blender.sketch_helpers import fake_viewport, look_at_view
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import render, views


def projection_of(spec, width, height):
    scene = bpy.context.scene
    with render.temp_camera(scene, spec) as cam:
        return cam.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=width, y=height)


def assert_matrix_close(test, a, b, tol=1e-5):
    for row_a, row_b in zip(Matrix(a), Matrix(b)):
        for x, y in zip(row_a, row_b):
            test.assertAlmostEqual(x, y, delta=tol * max(1.0, abs(y)))


class CameraSpecTest(unittest.TestCase):
    def setUp(self):
        build_scene()

    def test_round_trip_through_a_render_camera(self):
        for ortho in (False, True):
            for size in ((800, 600), (600, 800)):
                with self.subTest(ortho=ortho, size=size):
                    view = look_at_view(1, (1.3, -1.5, 1.1), (0, 0, 0.3), size=size, ortho=ortho,
                                        clip=(0.1, 50.0))
                    self.assertEqual(view.camera["type"], "ORTHO" if ortho else "PERSP")
                    self.assertEqual(view.camera["sensor_fit"],
                                     "HORIZONTAL" if size[0] >= size[1] else "VERTICAL")
                    again = projection_of(view.camera, *size)
                    assert_matrix_close(self, again, view.window_matrix)

    def test_clip_range(self):
        for ortho in (False, True):
            view = look_at_view(1, (0, -3, 0), (0, 0, 0), ortho=ortho, clip=(0.25, 40.0))
            near, far, persp = views.clip_range(view.window_matrix)
            self.assertEqual(persp, not ortho)
            self.assertAlmostEqual(near, 0.25, places=4)
            self.assertAlmostEqual(far, 40.0, delta=1e-3)

    def test_ortho_viewport_with_negative_near_moves_the_eye_back(self):
        base = look_at_view(1, (0, -3, 0), (0, 0, 0), ortho=True, clip=(0.1, 10.0))
        # An orthographic viewport's projection: near -5, far 5.
        p = Matrix(base.window_matrix)
        near, far = -5.0, 5.0
        p[2][2] = -2.0 / (far - near)
        p[2][3] = -(far + near) / (far - near)
        spec = views.camera_spec(base.view_matrix, p, 800, 600)
        self.assertGreater(spec["clip_start"], 0.0)
        eye = Matrix(spec["matrix_world"]).translation
        self.assertAlmostEqual(eye.y, -3.0 - 5.01, places=4)
        # A point 1 m behind the original eye keeps its place on screen and is in range.
        point = Vector((0.3, -4.0, 0.2))
        cam_view = Matrix(spec["matrix_world"]).inverted()
        depth = -(cam_view @ point).z
        self.assertTrue(spec["clip_start"] < depth < spec["clip_end"])
        new_p = projection_of(spec, 800, 600)
        ndc_old = p @ Matrix(base.view_matrix) @ point.to_4d()
        ndc_new = new_p @ cam_view @ point.to_4d()
        self.assertAlmostEqual(ndc_old.x, ndc_new.x, places=5)
        self.assertAlmostEqual(ndc_old.y, ndc_new.y, places=5)


class CaptureTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        self.scene = bpy.context.scene
        self.depsgraph = bpy.context.evaluated_depsgraph_get()

    def test_view_from_region_perspective(self):
        look_at = (0.0, 0.0, 0.3)
        want = look_at_view(0, (1.3, -1.5, 1.1), look_at, size=(1000, 700))
        vp = fake_viewport(want)
        view = views.view_from_region(4, vp.rv3d, vp.region, self.scene, self.depsgraph)
        formats.validate_camera(view.to_json())
        self.assertEqual((view.id, view.width, view.height), (4, 1000, 700))
        self.assertIsNone(view.from_camera)
        self.assertTrue(view.is_perspective)
        x, y = views.to_pixel(view, look_at, 1000, 700)
        self.assertAlmostEqual(x, 500, delta=1)
        self.assertAlmostEqual(y, 350, delta=1)

    def test_view_from_region_in_camera_view(self):
        data = bpy.data.cameras.new("Shot")
        cam = bpy.data.objects.new("Shot", data)
        self.scene.collection.objects.link(cam)
        cam.location = (0.0, -3.0, 0.4)
        cam.rotation_euler = (math.radians(90), 0.0, 0.0)
        self.scene.camera = cam
        self.scene.render.resolution_x, self.scene.render.resolution_y = 1920, 1080
        self.scene.render.resolution_percentage = 50
        rv3d = SimpleNamespace(view_perspective="CAMERA", view_matrix=Matrix(), window_matrix=Matrix())
        region = SimpleNamespace(width=300, height=300)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        view = views.view_from_region(2, rv3d, region, self.scene, depsgraph)
        self.assertEqual(view.from_camera, "Shot")
        self.assertEqual((view.width, view.height), (960, 540))
        assert_matrix_close(self, view.view_matrix, cam.matrix_world.inverted())
        assert_matrix_close(self, projection_of(view.camera, 960, 540), view.window_matrix)
        x, y = views.to_pixel(view, (0.0, 0.0, 0.4), 960, 540)
        self.assertAlmostEqual(x, 480, delta=1)
        self.assertAlmostEqual(y, 270, delta=1)

    def test_behind_the_eye_has_no_pixel(self):
        view = look_at_view(1, (0, -2, 0), (0, 0, 0))
        self.assertIsNone(views.to_pixel(view, (0, -3, 0), 800, 600))


def orbit(view_id, degrees, *, distance=2.0, pivot=(0.0, 0.0, 0.3), **kwargs):
    a = math.radians(degrees)
    eye = (pivot[0] + distance * math.sin(a), pivot[1] - distance * math.cos(a), pivot[2])
    return look_at_view(view_id, eye, pivot, **kwargs)


class DifferenceTest(unittest.TestCase):
    def setUp(self):
        build_scene()

    def test_thresholds(self):
        base = orbit(1, 0)
        cases = {
            "same": (orbit(2, 0), False),
            "10 degrees": (orbit(2, 10), False),
            "20 degrees": (orbit(2, 20), True),
            "persp vs ortho": (orbit(2, 0, ortho=True), True),
            "angle +20 %": (orbit(2, 0, lens_mm=50.0 / 1.25), True),
        }
        for name, (other, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(views.substantially_different(base, other, 2.0), expected)
        panned = lambda dx: look_at_view(2, (dx, -2.0, 0.3), (dx, 0.0, 0.3))
        start = look_at_view(1, (0.0, -2.0, 0.3), (0.0, 0.0, 0.3))
        self.assertFalse(views.substantially_different(start, panned(0.1), 2.0), "pan 5 %")
        self.assertTrue(views.substantially_different(start, panned(0.3), 2.0), "pan 15 %")
        dollied = look_at_view(2, (0.0, -1.6, 0.3), (0.0, 0.0, 0.3))
        self.assertTrue(views.substantially_different(start, dollied, 1.6), "dolly 20 %")


class StorageTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        self.gp = bpy.data.grease_pencils.new("Views Test")

    def tearDown(self):
        bpy.data.grease_pencils.remove(self.gp)

    def make(self, view_id):
        return look_at_view(view_id, (0, -2, 0.3), (0, 0, 0.3))

    def test_ids_round_trip_and_prune(self):
        ids = [views.add_view(self.gp, self.make).id for _ in range(3)]
        self.assertEqual(ids, [1, 2, 3])
        loaded = views.load_views(self.gp)
        self.assertEqual([v.to_json() for v in loaded][1]["id"], 2)
        self.assertEqual(views.latest_view(self.gp).id, 3)
        views.prune_views(self.gp, {1})
        self.assertEqual([v.id for v in views.load_views(self.gp)], [1, 3])
        self.assertEqual(views.add_view(self.gp, self.make).id, 4, "ids are never reused")
        views.clear_views(self.gp)
        self.assertEqual(views.add_view(self.gp, self.make).id, 5)

    def test_corrupt_storage_reads_as_empty(self):
        self.gp[views.VIEWS_PROP] = "{not json"
        with self.assertLogs("whittle", "WARNING"):
            self.assertEqual(views.load_views(self.gp), [])
        self.gp[views.VIEWS_PROP] = json.dumps([{"id": 1}])
        with self.assertLogs("whittle", "WARNING"):
            self.assertEqual(views.load_views(self.gp), [])
        self.assertIsNone(views.latest_view(bpy.data.grease_pencils.new("Empty")))
