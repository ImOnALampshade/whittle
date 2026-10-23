# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import bpy
import numpy as np

from tests.blender.helpers import CRATE_BUNDLE
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import commands, render, sketch
from whittle.addon.bridge import BridgeError
from whittle.protocol import ErrorCode

CAMERA = {"location": [1.5, -1.5, 1.2], "look_at": [0, 0, 0.25]}


def scene_state(scene):
    values = render.snapshot_settings(scene)
    values[("", "camera")] = scene.camera.name if scene.camera else None
    return {
        "settings": {str(k): v for k, v in values.items()},
        "objects": sorted(o.name for o in bpy.data.objects),
        "cameras": len(bpy.data.cameras),
        "images": len(bpy.data.images),
        "modifiers": {o.name: [m.name for m in o.modifiers] for o in bpy.data.objects},
    }


class RenderTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        self.scene = bpy.context.scene
        # Leave something non-default in the user's settings to prove it survives.
        self.scene.view_settings.view_transform = "AgX"
        self.scene.render.resolution_x = 1234
        self.scene.render.engine = "BLENDER_EEVEE"
        self.bundle = formats.read_bundle(CRATE_BUNDLE)
        sketch.load_strokes(self.scene, self.bundle.strokes)
        self.session = formats.SessionDir(tempfile.mkdtemp(prefix="whittle-render-"))
        self.addCleanup(shutil.rmtree, self.session.root, True)
        self.ctx = commands.CommandContext(session=self.session, turn_id=lambda: "n0001",
                                           bundle=lambda: self.bundle, settings={"render_size": 256})

    def render(self, **params):
        return commands.handle_render(self.ctx, params)

    def test_modes_produce_images_of_the_requested_size(self):
        for mode in ("shaded", "matcap", "wireframe"):
            data = self.render(mode=mode, camera=CAMERA, size=128)
            self.assertEqual((data["width"], data["height"]), (128, 128))
            pixels = render.load_pixels(data["path"])
            self.assertEqual(pixels.shape, (128, 128, 4))
            self.assertTrue((pixels[..., 3] == 1.0).all(), "agent images are opaque")
            self.assertIsNone(data["strokes_path"])

    def test_view_aspect_and_default_size(self):
        data = self.render(mode="shaded", view=1)
        self.assertEqual((data["width"], data["height"]), (256, 192))
        self.assertIn("-v1-shaded", Path(data["path"]).name)

    def test_wireframe_differs_from_shaded(self):
        shaded = render.load_pixels(self.render(mode="shaded", camera=CAMERA, size=96)["path"])
        wire = render.load_pixels(self.render(mode="wireframe", camera=CAMERA, size=96)["path"])
        self.assertFalse(np.allclose(shaded, wire))

    def test_overlay_composites_strokes(self):
        data = self.render(mode="overlay", view=1, size=512)
        overlay = render.load_pixels(data["path"])
        strokes = render.load_pixels(data["strokes_path"])
        alpha = strokes[..., 3]
        self.assertGreater((alpha == 1.0).sum(), 100, "the strokes are visible")
        opaque = alpha == 1.0
        np.testing.assert_allclose(overlay[opaque][:, :3], strokes[opaque][:, :3], atol=1 / 255)

        shaded = render.load_pixels(self.render(mode="shaded", view=1, size=512)["path"])
        clear = alpha == 0.0
        np.testing.assert_allclose(overlay[clear], shaded[clear], atol=1 / 255)

    def test_keep_strokes_hides_the_others(self):
        obj = sketch.find_sketch_object()
        drawing = obj.data.layers["add"].frames[0].drawing
        turns = sketch.ensure_int_attribute(drawing, sketch.TURN_ATTRIBUTE).data
        turns[0].value = 1
        before = sorted(a.name for a in drawing.attributes)
        everything = render.load_pixels(self.render(mode="overlay", view=1, size=256)["strokes_path"])
        self.ctx.turn_number = lambda: 1
        only_one = render.load_pixels(self.render(mode="overlay", view=1, size=256)["strokes_path"])
        self.ctx.turn_number = lambda: 9
        none = render.load_pixels(self.render(mode="overlay", view=1, size=256)["strokes_path"])
        self.assertGreater((everything[..., 3] > 0).sum(), (only_one[..., 3] > 0).sum())
        self.assertGreater((only_one[..., 3] > 0).sum(), 0)
        self.assertEqual((none[..., 3] > 0).sum(), 0, "fills and outlines both go")
        self.assertEqual(sorted(a.name for a in drawing.attributes), before)

    def test_stroke_colours_are_flat(self):
        data = self.render(mode="overlay", view=2, size=512)
        strokes = render.load_pixels(data["strokes_path"])
        solid = strokes[strokes[..., 3] > 0.95][:, :3]
        red = solid[(solid[:, 0] > 0.5) & (solid[:, 1] < 0.4)]
        self.assertGreater(len(red), 20)
        # Unlit layers come out at full tint, not darkened by Workbench lighting.
        self.assertGreater(red[:, 0].max(), 0.9)

    def test_scene_is_left_unchanged(self):
        before = scene_state(self.scene)
        self.render(mode="overlay", view=1)
        self.render(mode="wireframe", camera=CAMERA, size=64)
        self.render(mode="matcap", view=2, size=64)
        self.assertEqual(scene_state(self.scene), before)

    def test_parameter_errors(self):
        cases = [
            ({"mode": "shaded"}, ErrorCode.BAD_REQUEST),
            ({"mode": "shaded", "view": 1, "camera": CAMERA}, ErrorCode.BAD_REQUEST),
            ({"mode": "overlay", "camera": CAMERA}, ErrorCode.BAD_REQUEST),
            ({"mode": "toon", "view": 1}, ErrorCode.BAD_REQUEST),
            ({"mode": "shaded", "view": 1, "size": 4096}, ErrorCode.BAD_REQUEST),
            ({"mode": "shaded", "camera": {"location": [0, 0, 0]}}, ErrorCode.BAD_REQUEST),
            ({"mode": "shaded", "camera": {"location": [1, 1, 1], "look_at": [1, 1, 1]}}, ErrorCode.BAD_REQUEST),
            ({"mode": "shaded", "view": 7}, ErrorCode.NOT_FOUND),
        ]
        for params, code in cases:
            with self.subTest(params=params), self.assertRaises(BridgeError) as cm:
                self.render(**params)
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(BridgeError) as cm:
            self.render(mode="shaded")
        self.assertIn("this turn has 1, 2", cm.exception.message, "the error lists the view ids")

    def test_render_time(self):
        self.render(mode="shaded", view=1, size=512)
        start = time.perf_counter()
        data = self.render(mode="overlay", view=1, size=512)
        elapsed = time.perf_counter() - start
        print(f"\n  overlay render at 512 px: {elapsed * 1000:.0f} ms (reported {data['ms']:.0f} ms)")
        self.assertLess(elapsed, 10.0)

    def test_render_paths_are_sequenced(self):
        a = Path(self.render(mode="shaded", view=1, size=64)["path"]).name
        b = Path(self.render(mode="shaded", camera=CAMERA, size=64)["path"]).name
        self.assertEqual(a, "001-v1-shaded.png")
        self.assertEqual(b, "002-cam-shaded.png")


class CompositeTest(unittest.TestCase):
    def test_straight_alpha_over(self):
        top = np.array([[[1, 0, 0, 1], [1, 0, 0, 0], [1, 0, 0, 0.5]]], dtype=np.float32)
        bottom = np.array([[[0, 0, 1, 1], [0, 0, 1, 1], [0, 0, 1, 1]]], dtype=np.float32)
        out = render.composite(top, bottom)
        np.testing.assert_allclose(out[0, 0], [1, 0, 0, 1])
        np.testing.assert_allclose(out[0, 1], [0, 0, 1, 1])
        np.testing.assert_allclose(out[0, 2], [0.5, 0, 0.5, 1])
