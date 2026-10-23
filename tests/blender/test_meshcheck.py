# SPDX-License-Identifier: GPL-3.0-or-later
"""whittle.mesh_report and whittle.weld: what the agent sees about a mesh."""

import unittest

import bmesh
import bpy
from mathutils import Matrix, Vector

from tests.fixtures.crate.scene import build_scene, clear_scene
from whittle.addon import execution, meshcheck


def link(name, bm):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def sphere_bm():
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=0.5)
    return bm


def horn_bm(matrix):
    """A closed cone whose base sits 0.15 m inside a 0.5 m sphere."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.1, radius2=0.0, depth=0.4, matrix=matrix)
    return bm


HORN = Matrix.Translation((0.0, 0.0, 0.5)) @ Matrix.Rotation(0.4, 4, "Y")


class MeshReportTest(unittest.TestCase):
    def setUp(self):
        clear_scene()

    def test_plain_sphere_is_one_closed_shell(self):
        r = meshcheck.mesh_report(link("Ball", sphere_bm()))
        self.assertEqual(r["shells"], 1)
        self.assertEqual(r["open_edges"], 0)
        self.assertEqual(r["self_intersections"], 0)
        self.assertTrue(r["watertight"])
        self.assertGreater(r["volume"], 0.4)
        self.assertEqual(r["tris"], 24 * 10 * 2 + 24 * 2)

    def test_fused_horn_reports_one_clean_shell(self):
        ball = link("Ball", sphere_bm())
        horn = link("Horn", horn_bm(HORN))
        mod = ball.modifiers.new("Fuse", "BOOLEAN")
        mod.operation = "UNION"
        mod.solver = "EXACT"
        mod.object = horn
        horn.hide_set(True)
        r = meshcheck.mesh_report(ball)
        self.assertEqual(r["shells"], 1)
        self.assertEqual(r["self_intersections"], 0)
        self.assertEqual(r["open_edges"], 0)
        self.assertTrue(r["watertight"])
        plain = meshcheck.mesh_report(ball, evaluated=False)
        self.assertGreater(r["tris"], plain["tris"], "evaluated=True counts the live boolean")

    def test_buried_base_join_reports_shells_and_intersections(self):
        bm = sphere_bm()
        horn = horn_bm(HORN)
        mesh = bpy.data.meshes.new("tmp")
        horn.to_mesh(mesh)
        horn.free()
        bm.from_mesh(mesh)
        bpy.data.meshes.remove(mesh)
        r = meshcheck.mesh_report(link("Ball", bm))
        self.assertEqual(r["shells"], 2)
        self.assertGreater(r["self_intersections"], 0)
        # This is why an edge check alone is not enough: each shell is closed.
        self.assertEqual(r["open_edges"], 0)
        self.assertTrue(r["watertight"])

    def test_open_mesh_reports_boundary_edges(self):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.delete(bm, geom=[next(iter(bm.faces))], context="FACES_ONLY")
        r = meshcheck.mesh_report(link("Box", bm))
        self.assertEqual(r["open_edges"], 4)
        self.assertFalse(r["watertight"])

    def test_inside_out_mesh_has_negative_volume(self):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        r = meshcheck.mesh_report(link("Box", bm))
        self.assertLess(r["volume"], 0)
        self.assertFalse(r["watertight"])

    def test_report_is_in_world_space(self):
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        box = link("Box", bm)
        box.scale = (2.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        self.assertAlmostEqual(meshcheck.mesh_report(box)["volume"], 2.0, places=4)

    def test_weld_joins_an_unwelded_sweep(self):
        curve = bpy.data.curves.new("Sweep", "CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = 0.02
        curve.bevel_resolution = 1
        curve.use_fill_caps = True
        spline = curve.splines.new("POLY")
        spline.points.add(3)
        for i, p in enumerate(spline.points):
            p.co = (i * 0.1, 0.0, (i % 2) * 0.05, 1.0)
        tmp = bpy.data.objects.new("tmp", curve)
        bpy.context.scene.collection.objects.link(tmp)
        self.assertGreater(meshcheck.mesh_report(tmp)["shells"], 1, "curves are measured through to_mesh")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph))
        sweep = bpy.data.objects.new("Sweep", mesh)
        bpy.context.scene.collection.objects.link(sweep)
        before = meshcheck.mesh_report(sweep)
        self.assertEqual(before["shells"], 3)
        self.assertGreater(before["duplicate_verts"], 0)
        self.assertGreater(meshcheck.weld(sweep)["removed_verts"], 0)
        after = meshcheck.mesh_report(sweep)
        self.assertEqual((after["shells"], after["duplicate_verts"], after["open_edges"]), (1, 0, 0))
        self.assertTrue(after["watertight"])

    def test_helpers_are_in_the_exec_namespace(self):
        crate = build_scene()
        ns = execution.ExecNamespace(lambda: [crate])
        result = execution.run(
            "r = whittle.mesh_report(whittle.targets()[0])\n"
            "print(r['shells'], r['tris'], r['watertight'], whittle.weld(whittle.targets()[0]))", ns)
        self.assertIsNone(result["error"])
        self.assertEqual(result["stdout"], "1 12 True {'removed_verts': 0}\n")

    def test_bad_input_raises(self):
        with self.assertRaises(TypeError):
            meshcheck.mesh_report(None)
        empty = bpy.data.objects.new("Empty", None)
        bpy.context.scene.collection.objects.link(empty)
        with self.assertRaises(TypeError):
            meshcheck.mesh_report(empty)
        with self.assertRaises(TypeError):
            meshcheck.weld(empty)
