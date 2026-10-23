# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import tempfile
import unittest

from tests.blender.helpers import CRATE_BUNDLE
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import commands
from whittle.addon.bridge import BridgeError
from whittle.protocol import ErrorCode


class InspectTest(unittest.TestCase):
    def setUp(self):
        build_scene()
        bundle = formats.read_bundle(CRATE_BUNDLE)
        folder = tempfile.mkdtemp(prefix="whittle-inspect-")
        self.addCleanup(shutil.rmtree, folder, True)
        self.ctx = commands.CommandContext(session=formats.SessionDir(folder), bundle=lambda: bundle)

    def inspect(self, **params):
        return commands.handle_inspect(self.ctx, params)

    def test_summary(self):
        data = self.inspect(query="summary")
        self.assertEqual(data["targets"], ["Crate"])
        (crate,) = [o for o in data["objects"] if o["name"] == "Crate"]
        self.assertEqual(crate["verts"], 8)
        self.assertEqual(crate["faces"], 6)
        self.assertEqual(crate["triangles"], 12)
        self.assertEqual(crate["dimensions"], [0.5, 0.5, 0.5])
        self.assertTrue(crate["is_target"])
        self.assertEqual(crate["materials"], ["Wood"])

    def test_object(self):
        import bpy

        bpy.data.objects["Crate"].modifiers.new("Bevel", "BEVEL").width = 0.02
        data = self.inspect(query="object", name="Crate")
        self.assertEqual(data["world_bounds"]["min"], [-0.25, -0.25, 0.0])
        self.assertEqual(data["world_bounds"]["max"], [0.25, 0.25, 0.5])
        self.assertEqual(len(data["world_bounds"]["corners"]), 8)
        (bevel,) = data["modifiers"]
        self.assertEqual(bevel["type"], "BEVEL")
        self.assertAlmostEqual(bevel["settings"]["width"], 0.02, places=4)

    def test_object_not_found(self):
        with self.assertRaises(BridgeError) as cm:
            self.inspect(query="object", name="Nope")
        self.assertEqual(cm.exception.code, ErrorCode.NOT_FOUND)
        self.assertIn("targets are: Crate", cm.exception.message)
        with self.assertRaises(BridgeError) as cm:
            self.inspect(query="object", name="crate")
        self.assertIn("similar names: Crate", cm.exception.message, "a near miss names the object")

    def test_object_needs_name(self):
        with self.assertRaises(BridgeError) as cm:
            self.inspect(query="object")
        self.assertEqual(cm.exception.code, ErrorCode.BAD_REQUEST)

    def test_unknown_query(self):
        with self.assertRaises(BridgeError) as cm:
            self.inspect(query="everything")
        self.assertEqual(cm.exception.code, ErrorCode.BAD_REQUEST)

    def test_materials(self):
        names = [m["name"] for m in self.inspect(query="materials")["materials"]]
        self.assertIn("Wood", names)

    def test_node_groups(self):
        import bpy

        group = bpy.data.node_groups.new("Scatter", "GeometryNodeTree")
        group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        try:
            (info,) = [g for g in self.inspect(query="node_groups")["node_groups"] if g["name"] == "Scatter"]
            self.assertEqual(info["type"], "GeometryNodeTree")
            self.assertEqual(info["interface"][0]["name"], "Geometry")
        finally:
            bpy.data.node_groups.remove(group)

    def test_scene(self):
        data = self.inspect(query="scene")
        self.assertEqual(data["units"]["system"], "METRIC")
        self.assertEqual(data["counts"]["objects"], 1)

    def test_results_are_plain_json(self):
        import json

        for query in commands.INSPECT_QUERIES:
            params = {"query": query, "name": "Crate"}
            json.dumps(commands.handle_inspect(self.ctx, params))

    def test_every_modifier_type_is_plain_json(self):
        import json

        import bpy

        crate = bpy.data.objects["Crate"]
        kinds = [item.identifier for item in
                 bpy.types.Modifier.bl_rna.properties["type"].enum_items]
        for kind in kinds:
            try:
                crate.modifiers.new(kind.lower(), kind)
            except (RuntimeError, TypeError):
                pass
        self.assertIn("HOOK", [m.type for m in crate.modifiers])
        data = self.inspect(query="object", name="Crate")
        json.dumps(data)
        (hook,) = [m for m in data["modifiers"] if m["type"] == "HOOK"]
        matrix = hook["settings"]["matrix_inverse"]
        self.assertEqual([len(row) for row in matrix], [4, 4, 4, 4])
