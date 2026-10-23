# SPDX-License-Identifier: GPL-3.0-or-later
"""The screenshot harness's pieces that need no window: the scenario list,
the stitching and trimming of sidebar pages, the PNG writer and the copy of
the README's images."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import bpy
import numpy as np

from tests.screens import catalog, harness, run, scenarios


class ScreensTest(unittest.TestCase):
    def test_every_scenario_is_described(self):
        self.assertEqual(set(scenarios.SCENARIOS), set(catalog.SCENARIOS))
        self.assertTrue(set(catalog.WIDE) <= set(catalog.SCENARIOS))
        self.assertTrue(set(catalog.WINDOWS) <= set(catalog.SCENARIOS))

    def test_readme_images_name_shots_the_run_makes(self):
        for label in catalog.DOCS.values():
            name = label.removeprefix("wide/")
            self.assertIn(name, catalog.SCENARIOS)
            if label.startswith("wide/"):
                self.assertIn(name, catalog.WIDE)

    def test_a_window_scenario_has_its_own_window(self):
        self.assertTrue(scenarios.SCENARIOS["hero"].window)
        self.assertEqual(catalog.window("hero"), catalog.WINDOWS["hero"])
        self.assertEqual(catalog.window("conversation"), (catalog.WINDOW, 1.0))

    def page(self, rows):
        """A 1-pixel-wide page whose rows (top first) hold these values."""
        values = np.array(rows[::-1], dtype=np.float32)
        return np.repeat(values[:, None, None], 4, axis=2)

    def test_stitch_puts_later_pages_below(self):
        first, second = self.page([1, 2, 3, 4]), self.page([3, 4, 5, 6])
        out = harness.stitch([(0, first), (2, second)])
        self.assertEqual(out[::-1, 0, 0].tolist(), [1, 2, 3, 4, 5, 6])

    def test_trim_drops_flat_rows_at_the_bottom(self):
        pixels = np.zeros((6, 4, 4), dtype=np.float32)
        pixels[4, 1] = 1.0   # a panel row, two rows down from the top
        out = harness.trim_bottom(pixels, tabs=0, margin=1)
        self.assertEqual(out.shape[0], 3)


    def roundtrip(self, pixels):
        """Writes pixels with the harness and loads them back with Blender:
        the PNG's colour type and the pixels as read."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shot.png"
            harness.save_png(pixels, path)
            colour_type = path.read_bytes()[25]
            img = bpy.data.images.load(str(path), check_existing=False)
            try:
                height, width = pixels.shape[:2]
                self.assertEqual(tuple(img.size), (width, height))
                back = np.empty(width * height * 4, dtype=np.float32)
                img.pixels.foreach_get(back)
            finally:
                bpy.data.images.remove(img)
        return colour_type, back.reshape(height, width, 4)

    def test_png_with_few_colours_is_indexed_and_lossless(self):
        rng = np.random.default_rng(1)
        levels = rng.integers(0, 4, size=(9, 13, 3)) * 85 / 255.0
        pixels = np.concatenate([levels, np.ones((9, 13, 1))], axis=2).astype(np.float32)
        colour_type, back = self.roundtrip(pixels)
        self.assertEqual(colour_type, 3)
        np.testing.assert_allclose(back[..., :3], pixels[..., :3], atol=1e-6)

    def test_png_with_many_colours_is_rgb_and_lossless(self):
        rng = np.random.default_rng(2)
        rgb = rng.integers(0, 256, size=(23, 31, 3)) / 255.0
        pixels = np.concatenate([rgb, np.ones((23, 31, 1))], axis=2).astype(np.float32)
        colour_type, back = self.roundtrip(pixels)
        self.assertEqual(colour_type, 2)
        np.testing.assert_allclose(back[..., :3], pixels[..., :3], atol=1e-6)
        self.assertTrue((back[..., 3] == 1.0).all())

    def test_copy_docs_names_each_image_after_its_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, docs = Path(tmp) / "screens", Path(tmp) / "images"
            for label in catalog.DOCS.values():
                (out / label).parent.mkdir(parents=True, exist_ok=True)
                (out / f"{label}.png").write_bytes(label.encode())
            with contextlib.redirect_stdout(io.StringIO()):
                written = run.copy_docs(out, docs)
            self.assertEqual(sorted(p.name for p in written), sorted(f"{n}.png" for n in catalog.DOCS))
            for name, label in catalog.DOCS.items():
                self.assertEqual((docs / f"{name}.png").read_bytes(), label.encode())


if __name__ == "__main__":
    unittest.main()
