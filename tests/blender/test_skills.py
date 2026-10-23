# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs every Python block in every recipe skill in a fresh crate scene, so the
recipes the agent copies from stay correct for this Blender."""

import re
import unittest

import bmesh
import bpy
from mathutils import Matrix

from tests.fixtures.crate.scene import build_scene, clear_scene
from whittle.addon import execution, meshcheck
from whittle.agent import prompt

BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)


class RecipeSkillsTest(unittest.TestCase):
    def test_every_recipe_block_runs(self):
        for name in prompt.SKILLS:
            with self.subTest(skill=name):
                crate = build_scene()
                ns = execution.ExecNamespace(lambda: [crate])
                blocks = BLOCK.findall(prompt.load_skill(name))
                self.assertTrue(blocks, f"{name} has no python blocks")
                for i, code in enumerate(blocks):
                    result = execution.run(code, ns)
                    self.assertIsNone(result["error"], f"{name} block {i}: {result['error']}")
                    self.assertTrue(result["stdout"].strip(), f"{name} block {i} printed nothing")
                    print(f"\n  {name}[{i}]: {result['stdout'].strip().splitlines()[-1]}", end="")

    def test_boolean_recipe_cuts_the_crate(self):
        crate = build_scene()
        ns = execution.ExecNamespace(lambda: [crate])
        blocks = BLOCK.findall(prompt.load_skill("boolean-carve"))
        before = len(crate.data.polygons)
        for code in blocks:
            self.assertIsNone(execution.run(code, ns)["error"])
        crate = bpy.data.objects["Crate"]
        self.assertGreater(len(crate.data.polygons), before)
        self.assertNotIn("Crate_cutter", bpy.data.objects)
        self.assertEqual([m.name for m in crate.modifiers], [])


def horned_ball_scene():
    """A UV sphere head, the case the horn example in modeling-practices.md comes from."""
    clear_scene()
    mesh = bpy.data.meshes.new("Ball")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.5)
    bm.to_mesh(mesh)
    bm.free()
    ball = bpy.data.objects.new("Ball", mesh)
    bpy.context.scene.collection.objects.link(ball)
    ball.location.z = 0.5
    bpy.context.view_layer.update()
    return ball


class FusePartsTest(unittest.TestCase):
    def setUp(self):
        self.ball = horned_ball_scene()
        self.ns = execution.ExecNamespace(lambda: [self.ball])
        self.blocks = BLOCK.findall(prompt.load_skill("fuse-parts"))

    def run_code(self, code):
        result = execution.run(code, self.ns)
        self.assertIsNone(result["error"], result["error"])
        return result

    def report(self):
        return meshcheck.mesh_report(bpy.data.objects["Ball"])

    def test_grown_horns_are_one_clean_shell(self):
        grow = self.blocks[0].replace("base_radius = 0.07", "base_radius = 0.12")
        for side in (1, -1):
            self.run_code(grow.replace("Vector((0.4, 0.0, 1.0))", f"Vector(({0.6 * side}, 0.0, 1.0))")
                          .replace("Vector((0.25, 0.0, 0.0))", f"Vector(({0.25 * side}, 0.0, 0.0))"))
        r = self.report()
        self.assertGreater(r["tris"], 32 * 14 * 2 + 64)
        self.assertEqual((r["shells"], r["self_intersections"], r["open_edges"], r["ngons"]), (1, 0, 0, 0))
        self.assertTrue(r["watertight"])

    def test_self_union_repairs_a_buried_base_join(self):
        head = self.report()["volume"]
        bm = bmesh.new()
        bm.from_mesh(self.ball.data)
        bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.1, radius2=0.0, depth=0.4,
                              matrix=Matrix.Translation((0.15, 0.0, 0.5)) @ Matrix.Rotation(0.4, 4, "Y"))
        bm.to_mesh(self.ball.data)
        bm.free()
        faked = self.report()
        self.assertEqual(faked["shells"], 2)
        self.assertGreater(faked["self_intersections"], 0)
        define = self.blocks[1].split("\n\n\ntarget =")[0]
        self.run_code(define + "\nfuse_parts(whittle.targets()[0], [])\n")
        r = self.report()
        self.assertEqual((r["shells"], r["self_intersections"], r["open_edges"], r["duplicate_verts"]), (1, 0, 0, 0))
        self.assertTrue(r["watertight"])
        self.assertGreater(r["volume"], head + 0.0005, "the union keeps the horn")
        self.assertLess(r["volume"], faked["volume"], "and drops the buried base")
