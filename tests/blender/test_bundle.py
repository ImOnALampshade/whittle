# SPDX-License-Identifier: GPL-3.0-or-later
import math
import shutil
import tempfile
import unittest
from pathlib import Path

import bpy
from mathutils import Vector

from tests.blender.sketch_helpers import add_stroke, look_at_view
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import bundle, render, sketch, views

SETTINGS = {"self_check_rounds": 2, "poly_budget": 800, "style_notes": "chunky", "render_size": 512}
A_POINTS = [(-0.15 + 0.3 * i / 7, -0.25, 0.25 + 0.02 * math.sin(i)) for i in range(8)]
A_RADIUS = [0.012 + 0.001 * i for i in range(8)]
B_POINTS = [(0.2 * math.cos(2 * math.pi * i / 12), 0.2 * math.sin(2 * math.pi * i / 12), 0.7)
            for i in range(12)]
C_POINTS = [(-0.1 + 0.05 * i, 0.40, 0.25) for i in range(5)]
D_POINTS = [(0.4, -0.3, 0.1), (0.45, -0.3, 0.2), (0.5, -0.3, 0.3)]
E_POINTS = [(-0.25, -0.25, 0.5), (0.25, -0.25, 0.5)]


def remove_sketch():
    obj = sketch.find_sketch_object()
    if obj is not None:
        bpy.data.objects.remove(obj)


def files_under(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def patch_max(pixels, x, y, channel, radius=1):
    h, w, _ = pixels.shape
    row = h - 1 - int(y)
    col = int(x)
    patch = pixels[max(0, row - radius):row + radius + 1, max(0, col - radius):col + radius + 1]
    if channel == "alpha":
        return patch[..., 3].max()
    return patch.reshape(-1, 4)[patch[..., 3].reshape(-1).argmax()]


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.crate = build_scene()
        remove_sketch()
        self.scene = bpy.context.scene
        self.scene.unit_settings.scale_length = 0.01
        self.addCleanup(setattr, self.scene.unit_settings, "scale_length", 1.0)
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-bundle-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.obj = sketch.ensure_sketch_layers(self.scene)
        gp = self.obj.data
        self.view1 = views.add_view(gp, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))
        self.view2 = views.add_view(gp, lambda i: look_at_view(i, (0, -2, 0.25), (0, 0, 0.25)))
        add_stroke(self.obj, "carve", A_POINTS, radius=A_RADIUS, opacity=0.5, view=2)
        add_stroke(self.obj, "add", B_POINTS, cyclic=True, view=1)
        add_stroke(self.obj, "note", C_POINTS, view=2)
        add_stroke(self.obj, "free", D_POINTS)
        add_stroke(self.obj, "crease", E_POINTS, view=1)
        gp.layers["crease"].hide = True
        self.ref = self.tmp / "my ref!.png"
        shutil.copyfile(Path(__file__).resolve().parents[1] / "fixtures" / "crate" / "request" / "views"
                        / "1" / "overlay.png", self.ref)

    def write(self, name="request", **kwargs):
        args = dict(scene=self.scene, sketch_obj=self.obj, node="n0003", parent="n0002",
                    prompt="Carve a slot.", targets=[self.crate], refs=[self.ref],
                    settings=SETTINGS, render_size=128)
        args.update(kwargs)
        return bundle.write_bundle(self.tmp / name, **args)

    def test_layout_and_request(self):
        written = self.write()
        dest = self.tmp / "request"
        self.assertEqual(files_under(dest), {
            "request.json", "strokes.json", "refs/my_ref.png",
            "views/1/camera.json", "views/1/overlay.png", "views/1/strokes.png",
            "views/2/camera.json", "views/2/overlay.png", "views/2/strokes.png"})
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["my ref!.png", "request"])
        again = formats.read_bundle(dest)
        req = again.request
        self.assertEqual((req.node, req.parent, req.prompt, req.amend), ("n0003", "n0002", "Carve a slot.", None))
        uid = self.crate[bundle.UID_PROP]
        self.assertEqual(req.target, [{"uid": uid, "name": "Crate", "type": "MESH"}])
        self.assertEqual(req.stroke_types, ["free", "add", "carve", "note"])
        self.assertEqual(req.views, [1, 2])
        self.assertEqual(req.refs, ["refs/my_ref.png"])
        self.assertEqual((dest / "refs" / "my_ref.png").read_bytes(), self.ref.read_bytes())
        self.assertEqual(req.units, {"system": "METRIC", "scale_length": 0.01})
        self.assertEqual(req.settings, {"self_check_rounds": 2, "poly_budget": 800, "style_notes": "chunky"})
        self.assertEqual(written.request, req)

        self.write("second")
        self.assertEqual(formats.read_bundle(self.tmp / "second").request.target[0]["uid"], uid)

    def test_strokes(self):
        strokes = self.write().strokes
        self.assertEqual([(s.index, s.type, s.view) for s in strokes],
                         [(0, "free", 2), (1, "add", 1), (2, "carve", 2), (3, "note", 2)])
        d, b, a, c = strokes
        self.assertTrue(b.cyclic)
        self.assertFalse(a.cyclic)
        for stroke, drawn in ((a, A_POINTS), (b, B_POINTS), (c, C_POINTS), (d, D_POINTS)):
            self.assertEqual(len(stroke.points), len(drawn))
            for got, want in zip(stroke.points, drawn):
                for x, y in zip(got, want):
                    self.assertAlmostEqual(x, y, delta=1e-5)
        self.assertEqual(a.radius, [round(r, 5) for r in A_RADIUS])
        self.assertEqual(a.opacity, [0.5] * 8)
        self.assertEqual(d.radius, [0.01] * 3)

        self.assertTrue(all(a.on_surface))
        for n in a.normal:
            for x, y in zip(n, (0.0, -1.0, 0.0)):
                self.assertAlmostEqual(x, y, delta=1e-3)
        self.assertEqual(set(a.hit_object), {"Crate"})
        for stroke in (b, c):
            self.assertFalse(any(stroke.on_surface))
            self.assertEqual(set(stroke.normal), {None})
            self.assertEqual(set(stroke.hit_object), {None})

        drawing = self.obj.data.layers["free"].frames[0].drawing
        self.assertEqual(sketch._curve_ints(drawing, sketch.VIEW_ATTRIBUTE), [0],
                         "the writer does not tag strokes")

    def test_cameras_and_images(self):
        written = self.write()
        self.assertEqual(written.views[2].to_json(), self.view2.to_json())
        self.assertEqual((written.views[2].width, written.views[2].height), (800, 600))
        overlay = render.load_pixels(written.overlay_path(2))
        strokes = render.load_pixels(written.strokes_png_path(2))
        self.assertEqual(overlay.shape, (96, 128, 4))
        self.assertEqual(strokes.shape, (96, 128, 4))
        self.assertGreater(overlay[..., 3].min(), 0.99, "overlays are flattened")
        self.assertEqual(strokes[0, 0, 3], 0.0)
        x, y = views.to_pixel(self.view2, A_POINTS[4], 128, 96)
        self.assertGreater(patch_max(strokes, x, y, "alpha"), 0.5)
        r, g, b, _a = patch_max(strokes, x, y, "rgb")
        self.assertGreater(r, max(g, b))
        r, g, b, _a = patch_max(overlay, x, y, "rgb")
        self.assertGreater(r, max(g, b))

    def test_scene_is_untouched(self):
        before = render.snapshot_settings(self.scene)
        counts = (len(bpy.data.images), len(bpy.data.cameras), len(bpy.data.objects))
        self.write()
        self.assertEqual(render.snapshot_settings(self.scene), before)
        self.assertEqual((len(bpy.data.images), len(bpy.data.cameras), len(bpy.data.objects)), counts)

    def assert_nothing_written(self):
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["my ref!.png"])

    def test_failures_leave_nothing(self):
        with self.assertRaisesRegex(bundle.BundleError, "not found"):
            self.write(refs=[self.tmp / "missing.png"])
        self.assert_nothing_written()

        (self.tmp / "request").mkdir()
        with self.assertRaisesRegex(bundle.BundleError, "exists"):
            self.write()
        (self.tmp / "request").rmdir()

        views.clear_views(self.obj.data)
        with self.assertRaisesRegex(bundle.BundleError, "view"):
            self.write()
        self.assert_nothing_written()

    def test_prompt_only(self):
        sketch.clear_strokes(self.obj)
        views.add_view(self.obj.data, lambda i: look_at_view(i, (0, -2, 0.25), (0, 0, 0.25)))
        written = self.write(refs=[])
        self.assertEqual(written.strokes, [])
        self.assertEqual(written.request.views, [3])
        self.assertEqual(written.request.stroke_types, [])

        views.clear_views(self.obj.data)
        written = self.write("bare", refs=[])
        self.assertEqual(written.request.views, [])
        self.assertFalse((self.tmp / "bare" / "views").exists())

        written = self.write("no-sketch", refs=[], sketch_obj=None)
        self.assertEqual((written.strokes, written.request.views), ([], []))

    def test_on_surface_tolerance(self):
        view = self.view2
        depsgraph = bpy.context.evaluated_depsgraph_get()
        offsets = (-0.003, -0.0005, 0.0005, 0.003, 0.03, -0.03)
        points = [(0.05, -0.25 + dy, 0.2) for dy in offsets]
        on, normals, hits = bundle.surface_info(self.scene, depsgraph, view, points)
        self.assertEqual(on, [True, True, True, True, False, False])

        ortho = look_at_view(9, (0, -2, 0.25), (0, 0, 0.25), ortho=True)
        on, _n, _h = bundle.surface_info(self.scene, depsgraph, ortho, [(0.1, -0.25, 0.1), (0.1, 0.25, 0.1)])
        self.assertEqual(on, [True, False], "the back face is hidden in ortho too")

    def test_on_surface_seen_at_a_grazing_angle(self):
        # The crate's top seen almost edge on. The draw tool puts points short
        # of an oblique surface along the line of sight (tests/gui's
        # blank_sketch measured 5 cm at 2.5 m): they are still on it.
        eye = Vector((0.0, -2.5, 0.75))
        view = look_at_view(9, tuple(eye), (0, 0, 0.5))
        depsgraph = bpy.context.evaluated_depsgraph_get()
        on_top = Vector((0.05, 0.0, 0.5))
        towards_eye = (eye - on_top).normalized()
        points = [on_top + towards_eye * 0.05, on_top + towards_eye * 0.002,
                  on_top + Vector((0, 0, 0.05)), on_top - towards_eye * 0.4]
        on, _normals, hits = bundle.surface_info(self.scene, depsgraph, view, points)
        self.assertEqual(on, [True, True, False, False])
        self.assertEqual(hits[:2], ["Crate", "Crate"])
