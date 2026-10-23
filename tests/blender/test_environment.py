# SPDX-License-Identifier: GPL-3.0-or-later
import unittest

import bpy


class BlenderEnvironmentTest(unittest.TestCase):
    def test_blender_is_5_2_or_newer(self):
        self.assertGreaterEqual(bpy.app.version[:2], (5, 2))

    def test_grease_pencil_drawings_take_custom_stroke_attributes(self):
        gp = bpy.data.grease_pencils.new("EnvProbe")
        try:
            drawing = gp.layers.new("free").frames.new(1).drawing
            drawing.add_strokes([2])
            attr = drawing.attributes.new("whittle_view", "INT", "CURVE")
            attr.data[0].value = 3
            self.assertEqual(drawing.attributes["whittle_view"].data[0].value, 3)
        finally:
            bpy.data.grease_pencils.remove(gp)


if __name__ == "__main__":
    unittest.main()
