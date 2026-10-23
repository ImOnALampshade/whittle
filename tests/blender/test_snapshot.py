# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import tempfile
import unittest
from pathlib import Path

import bmesh
import bpy

from tests.fixtures.crate.scene import clear_scene
from whittle import formats
from whittle.addon import snapshot


def cube(name, size=0.5, collection=None):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def material(name, colour):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = colour
    return mat


def passthrough_group(name):
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    inp, out = group.nodes.new("NodeGroupInput"), group.nodes.new("NodeGroupOutput")
    group.links.new(inp.outputs[0], out.inputs[0])
    return group


def names(collection):
    return sorted(b.name for b in collection)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        clear_scene()
        for collection in (bpy.data.materials, bpy.data.node_groups, bpy.data.collections):
            for block in list(collection):
                collection.remove(block)
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-snapshot-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scene = bpy.context.scene
        self.props = bpy.data.collections.new("Props")
        scene.collection.children.link(self.props)
        self.crate = cube("Crate", collection=self.props)
        self.handle = cube("Crate_Handle", 0.1, collection=self.props)
        self.handle.parent = self.crate
        self.other = cube("Other")
        self.cutter = cube("Cutter", 0.2)
        self.wood = material("Wood", (0.5, 0.3, 0.1, 1.0))
        self.metal = material("Metal", (0.2, 0.2, 0.2, 1.0))
        self.crate.data.materials.append(self.wood)
        self.crate.data.materials.append(self.metal)
        self.other.data.materials.append(self.wood)
        self.crate.modifiers.new("Bevel", "BEVEL")
        boolean = self.crate.modifiers.new("Cut", "BOOLEAN")
        boolean.object = self.cutter
        self.crate.modifiers.new("GN", "NODES").node_group = passthrough_group("GN")
        # Other tests may leave a library behind (sketch mode loads brushes).
        self.libraries = list(bpy.data.libraries)
        self.blend = self.tmp / "start.blend"
        self.snap = snapshot.write(self.blend, [self.crate, self.handle])
        self.before = self.state()

    def state(self):
        crate = bpy.data.objects["Crate"]
        return {
            "objects": names(bpy.data.objects),
            "meshes": names(bpy.data.meshes),
            "materials": names(bpy.data.materials),
            "node_groups": names(bpy.data.node_groups),
            "verts": [tuple(round(c, 5) for c in v.co) for v in crate.data.vertices],
            "location": tuple(crate.location),
            "modifiers": [(m.name, m.type) for m in crate.modifiers],
            "cutter": crate.modifiers["Cut"].object.name,
            "gn": crate.modifiers["GN"].node_group.name,
            "slots": [s.material.name for s in crate.material_slots],
            "wood": tuple(bpy.data.materials["Wood"].diffuse_color),
            "other_wood": tuple(bpy.data.objects["Other"].material_slots[0].material.diffuse_color),
            "collections": [c.name for c in crate.users_collection],
            "handle_parent": bpy.data.objects["Crate_Handle"].parent.name,
            "handle_collections": [c.name for c in bpy.data.objects["Crate_Handle"].users_collection],
        }

    def test_manifest(self):
        again = snapshot.read(self.blend)
        self.assertEqual(again.manifest, self.snap.manifest)
        crate = self.snap.manifest["objects"][0]
        self.assertEqual((crate["name"], crate["data_name"], crate["collections"]), ("Crate", "Crate", ["Props"]))
        self.assertEqual(crate["materials"], ["Wood", "Metal"])
        self.assertEqual(crate["node_groups"], ["GN"])
        self.assertEqual(self.snap.manifest["objects"][1]["parent"], "Crate")
        self.assertEqual(self.snap.manifest["datablocks"]["materials"], ["Wood", "Metal"])
        self.assertTrue(crate["uid"])
        formats.validate_target(self.snap.manifest)

    def test_restore_undoes_edits(self):
        self.crate.data.vertices[0].co.x += 1.0
        self.crate.data.update()
        self.crate.location.z = 3.0
        self.wood.diffuse_color = (1.0, 0.0, 0.0, 1.0)
        self.crate.modifiers.remove(self.crate.modifiers["Bevel"])
        self.metal.name = "Steel"
        restored = snapshot.restore(self.snap)
        self.assertEqual(restored, ["Crate", "Crate_Handle"])
        after = self.state()
        for key, value in self.before.items():
            if key == "materials":
                continue
            self.assertEqual(after[key], value, key)
        # The renamed material is not the target's any more; the snapshot's
        # Metal comes back beside it.
        self.assertEqual(after["materials"], ["Metal", "Steel", "Wood"])
        self.assertEqual(list(bpy.data.libraries), self.libraries)

    def test_restore_brings_back_a_deleted_object(self):
        bpy.data.objects.remove(self.handle)
        self.crate.name = "Box"
        snapshot.restore(self.snap)
        self.assertIn("Crate", bpy.data.objects)
        self.assertEqual(bpy.data.objects["Crate_Handle"].parent.name, "Crate")
        self.assertEqual([c.name for c in bpy.data.objects["Crate_Handle"].users_collection], ["Props"])
        self.assertNotIn("Box", bpy.data.objects, "the renamed object is the snapshot's, by uid")
        self.assertFalse([n for n in names(bpy.data.objects) if ".00" in n])
        self.assertEqual(list(bpy.data.libraries), self.libraries)

    def test_remove_deletes_only_added_objects(self):
        lid = cube("Crate_Lid", collection=self.props)
        user = cube("UserThing")
        snapshot.restore(self.snap, remove=["Crate_Lid", "Crate", "Missing"])
        self.assertNotIn("Crate_Lid", bpy.data.objects)
        self.assertNotIn("Crate_Lid", bpy.data.meshes, "its orphan mesh goes too")
        self.assertIn("Crate", bpy.data.objects, "a snapshot object is never removed")
        self.assertIn(user.name, bpy.data.objects)
        del lid

    def test_no_suffixed_names_or_libraries(self):
        snapshot.restore(self.snap)
        snapshot.restore(self.snap)
        after = self.state()
        self.assertEqual(after, self.before)
        for attr in ("objects", "meshes", "materials", "node_groups"):
            self.assertFalse([n for n in names(getattr(bpy.data, attr)) if ".00" in n], attr)
        self.assertEqual(list(bpy.data.libraries), self.libraries)
        self.assertEqual(bpy.data.objects["Cutter"].users_collection[0], bpy.context.scene.collection)

    def test_restore_from_edit_mode(self):
        bpy.context.view_layer.objects.active = self.crate
        bpy.ops.object.mode_set(mode="EDIT")
        snapshot.restore(self.snap)
        self.assertEqual(bpy.data.objects["Crate"].mode, "OBJECT")
        self.assertEqual(self.state()["verts"], self.before["verts"])


if __name__ == "__main__":
    unittest.main()
