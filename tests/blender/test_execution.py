# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
import unittest

import bmesh
import bpy

from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import commands, execution


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.crate = build_scene()
        self.ns = execution.ExecNamespace(lambda: [self.crate])

    def run_code(self, code):
        return execution.run(code, self.ns)

    def test_stdout_is_captured(self):
        result = self.run_code("print(2 + 2)")
        self.assertEqual(result["stdout"], "4\n")
        self.assertIsNone(result["error"])

    def test_namespace_persists_and_has_helpers(self):
        self.run_code("value = 41")
        result = self.run_code("print(value + 1, whittle.targets()[0].name, Vector((1, 0, 0)).length)")
        self.assertEqual(result["stdout"], "42 Crate 1.0\n")

    def test_view3d_override_raises_in_background(self):
        result = self.run_code("whittle.view3d_override()")
        self.assertEqual(result["error"]["type"], "RuntimeError")

    def test_syntax_error(self):
        result = self.run_code("def broken(:\n    pass")
        self.assertEqual(result["error"]["type"], "SyntaxError")
        self.assertIn("<whittle exec 1>", result["error"]["traceback"])

    def test_a_helper_from_an_earlier_run_shows_its_own_lines(self):
        self.run_code("def helper(x):\n    y = x\n    return 1 / y")
        error = self.run_code("a = 1\nb = 2\nhelper(0)")["error"]
        self.assertIn("return 1 / y", error["traceback"])
        self.assertIn("helper(0)", error["traceback"])
        self.assertTrue(error["traceback"].startswith("Traceback"))

    def test_keyboard_interrupt_is_an_error(self):
        result = self.run_code("raise KeyboardInterrupt")
        self.assertEqual(result["error"]["type"], "KeyboardInterrupt")

    def test_runtime_error_traceback_is_trimmed(self):
        result = self.run_code("x = 1\n\ndef f():\n    raise ValueError('nope')\n\nf()")
        error = result["error"]
        self.assertEqual(error["type"], "ValueError")
        self.assertEqual(error["message"], "nope")
        self.assertNotIn("execution.py", error["traceback"])
        self.assertIn("raise ValueError('nope')", error["traceback"])
        self.assertTrue(error["traceback"].startswith("Traceback"))

    def test_sys_exit_does_not_escape(self):
        result = self.run_code("import sys\nsys.exit(3)")
        self.assertEqual(result["error"]["type"], "SystemExit")

    def test_stdout_is_truncated(self):
        result = self.run_code("print('x' * 50000)")
        self.assertLess(len(result["stdout"]), execution.STDOUT_LIMIT + 100)
        self.assertIn("truncated", result["stdout"])

    def test_diff_reports_changes(self):
        result = self.run_code(
            "mesh = bpy.data.meshes.new('Extra')\n"
            "bpy.context.scene.collection.objects.link(bpy.data.objects.new('Extra', mesh))\n"
            "c = bpy.data.objects['Crate']\n"
            "c.location.x += 1\n"
            "c.modifiers.new('Bevel', 'BEVEL')\n"
            "bm = bmesh.new(); bm.from_mesh(c.data)\n"
            "bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=1)\n"
            "bm.to_mesh(c.data); bm.free()\n")
        diff = result["diff"]
        self.assertEqual(diff["added"], ["Extra"])
        self.assertEqual(diff["removed"], [])
        (changed,) = diff["changed"]
        self.assertEqual(changed["name"], "Crate")
        self.assertEqual(set(changed["fields"]), {"location", "modifiers", "counts"})

    def test_diff_reports_removal(self):
        result = self.run_code("bpy.data.objects.remove(bpy.data.objects['Crate'])")
        self.assertEqual(result["diff"]["removed"], ["Crate"])

    def test_no_change_no_diff(self):
        result = self.run_code("print(len(bpy.data.objects))")
        self.assertEqual(result["diff"], {"added": [], "removed": [], "changed": []})


class EditModeTest(unittest.TestCase):
    def setUp(self):
        self.crate = build_scene()
        view_layer = bpy.context.view_layer
        view_layer.objects.active = self.crate
        self.crate.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        self.addCleanup(self.leave)

    def leave(self):
        if self.crate.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

    def test_exec_leaves_edit_mode_first(self):
        bm = bmesh.from_edit_mesh(self.crate.data)
        for v in bm.verts:
            v.co.z += 10
        bmesh.update_edit_mesh(self.crate.data)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = commands.CommandContext(session=formats.SessionDir(tmp.name), turn_objects=lambda: [self.crate])
        result = commands.handle_exec(ctx, {"code": "obj = bpy.data.objects['Crate']\n"
                                                    "print(max(v.co.z for v in obj.data.vertices))\n"
                                                    "obj.data.vertices[0].co.x = 100"})
        self.assertIsNone(result["error"])
        self.assertEqual(self.crate.mode, "OBJECT")
        self.assertGreater(float(result["stdout"]), 10, "the code saw the user's edit")
        self.assertEqual(self.crate.data.vertices[0].co.x, 100, "and what it wrote stays")
