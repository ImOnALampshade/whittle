# SPDX-License-Identifier: GPL-3.0-or-later
"""History snapshots without an agent: a node's target comes back exactly,
objects the agent made come and go with their nodes, and nothing else in the
file is touched."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bmesh
import bpy

from tests.fixtures.crate.scene import clear_scene
from whittle import formats
from whittle.addon import bundle, compare, history, render, sketch, targets

ID_TYPES = ("objects", "meshes", "materials", "node_groups", "collections", "libraries", "images",
            "cameras", "grease_pencils")


def cube(name, size=0.5, collection=None):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    (collection or bpy.context.scene.collection).objects.link(obj)
    return obj


def principled(name, colour):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = colour
    mat.diffuse_color = colour
    return mat


def base_colour(mat):
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    return tuple(round(c, 4) for c in bsdf.inputs["Base Color"].default_value)


def gn_groups():
    inner = bpy.data.node_groups.new("Inner", "GeometryNodeTree")
    inner.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    inner.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    i_in, i_out = inner.nodes.new("NodeGroupInput"), inner.nodes.new("NodeGroupOutput")
    xf = inner.nodes.new("GeometryNodeTransform")
    xf.name = "XF"
    inner.links.new(i_in.outputs[0], xf.inputs[0])
    inner.links.new(xf.outputs[0], i_out.inputs[0])
    outer = bpy.data.node_groups.new("Outer", "GeometryNodeTree")
    outer.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    amount = outer.interface.new_socket("Amount", in_out="INPUT", socket_type="NodeSocketFloat")
    outer.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    o_in, o_out = outer.nodes.new("NodeGroupInput"), outer.nodes.new("NodeGroupOutput")
    group = outer.nodes.new("GeometryNodeGroup")
    group.node_tree = inner
    outer.links.new(o_in.outputs[0], group.inputs[0])
    outer.links.new(group.outputs[0], o_out.inputs[0])
    return outer, amount.identifier


def counts():
    return {attr: len(getattr(bpy.data, attr)) for attr in ID_TYPES}


def suffixed():
    return [b.name for attr in ("objects", "meshes", "materials", "node_groups")
            for b in getattr(bpy.data, attr) if ".00" in b.name]


class HistoryCase(unittest.TestCase):
    """A crate target with a child, a bevel, a boolean whose cutter is not a
    target, a nested geometry-nodes group and two slot materials, one of them
    shared with a shelf; and a bystander that is no target at all."""

    def setUp(self):
        sketch.end_session()
        clear_scene()
        for attr in ("materials", "node_groups", "collections"):
            for block in list(getattr(bpy.data, attr)):
                getattr(bpy.data, attr).remove(block)
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-history-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(compare.reset)
        undo = mock.patch.object(history, "undo_push")
        self.undo = undo.start()
        self.addCleanup(undo.stop)
        self.scene = bpy.context.scene
        self.scene.whittle.target_auto = False
        self.scene.whittle.targets.clear()
        self.scene.whittle.target_collection = None
        self.props_coll = bpy.data.collections.new("Props")
        self.scene.collection.children.link(self.props_coll)
        self.addCleanup(self._clear_data)

        self.crate = cube("Crate", collection=self.props_coll)
        self.crate.location = (0.0, 0.0, 0.25)
        self.crate.data.vertices[0].co.z -= 0.05
        self.handle = cube("Crate_Handle", 0.1, collection=self.props_coll)
        self.handle.parent = self.crate
        self.handle.location = (0.3, 0, 0)
        self.cutter = cube("Cutter", 0.2)
        self.cutter.location = (0.0, -0.3, 0.3)
        bevel = self.crate.modifiers.new("Bevel", "BEVEL")
        bevel.width, bevel.segments = 0.02, 3
        boolean = self.crate.modifiers.new("Cut", "BOOLEAN")
        boolean.object = self.cutter
        outer, self.amount = gn_groups()
        gn = self.crate.modifiers.new("GN", "NODES")
        gn.node_group = outer
        getattr(gn.properties.inputs, self.amount).value = 0.7
        self.wood = principled("Wood", (0.5, 0.3, 0.1, 1.0))
        self.paint = principled("Paint", (0.1, 0.4, 0.8, 1.0))
        self.crate.data.materials.append(self.wood)
        self.crate.data.materials.append(self.paint)
        self.shelf = cube("Shelf", 0.3)
        self.shelf.location = (2, 0, 0)
        self.shelf.data.materials.append(self.paint)
        self.bystander = cube("Bystander", 0.4)
        self.bystander.location = (-2, 1, 0)
        self.bystander.data.materials.append(principled("Stone", (0.4, 0.4, 0.4, 1.0)))

        self.session = formats.SessionDir(self.tmp / "session")
        self.history = history.History(self.session)
        self.targets = [self.crate, self.handle]
        self.history.ensure_root(self.targets, self.scene)
        self.libraries = list(bpy.data.libraries)

    def _clear_data(self):
        # Later test modules build their own scenes and expect plain names.
        clear_scene()
        for attr in ("materials", "node_groups", "collections"):
            for block in list(getattr(bpy.data, attr)):
                getattr(bpy.data, attr).remove(block)

    def capture(self):
        crate = bpy.data.objects["Crate"]
        mods = crate.modifiers
        gn = mods.get("GN")
        return {
            "verts": [tuple(round(c, 5) for c in v.co) for v in crate.data.vertices],
            "location": tuple(round(c, 5) for c in crate.location),
            "data": crate.data.name,
            "modifiers": [(m.name, m.type) for m in mods],
            "bevel": (round(mods["Bevel"].width, 5), mods["Bevel"].segments) if "Bevel" in mods else None,
            "cutter": mods["Cut"].object.name if "Cut" in mods else None,
            "gn": gn.node_group.name if gn else None,
            "amount": round(getattr(gn.properties.inputs, self.amount).value, 5) if gn else None,
            "nested": tuple(bpy.data.node_groups["Inner"].nodes["XF"].inputs["Scale"].default_value),
            "slots": [s.material.name for s in crate.material_slots],
            "wood": base_colour(bpy.data.materials["Wood"]),
            "wood_diffuse": tuple(round(c, 4) for c in bpy.data.materials["Wood"].diffuse_color),
            "shelf_paint": base_colour(bpy.data.objects["Shelf"].material_slots[0].material),
            "handle_parent": bpy.data.objects["Crate_Handle"].parent.name,
            "collections": [c.name for c in crate.users_collection],
        }

    def bystander_state(self):
        obj = bpy.data.objects["Bystander"]
        return {
            "session_uid": obj.session_uid, "pointer": obj.as_pointer(),
            "data_pointer": obj.data.as_pointer(),
            "matrix": [tuple(round(v, 6) for v in row) for row in obj.matrix_world],
            "verts": [tuple(v.co) for v in obj.data.vertices],
            "colour": tuple(obj.material_slots[0].material.diffuse_color),
            "collections": [c.name for c in obj.users_collection],
        }

    def finish(self, node, prompt, objects, created=()):
        self.history.begin(node, prompt)
        return self.history.finish(node, objects, {"session_id": "S", "message_uuid": f"u-{node}",
                                                    "is_error": False, "interrupted": False},
                                   scene=self.scene, created=created)

    def mutate(self):
        crate = bpy.data.objects["Crate"]
        crate.data.vertices[1].co.x += 0.3
        crate.data.update()
        crate.location.z = 2.0
        crate.modifiers["Bevel"].width = 0.2
        crate.modifiers.remove(crate.modifiers["Cut"])
        getattr(crate.modifiers["GN"].properties.inputs, self.amount).value = 0.1
        bpy.data.node_groups["Inner"].nodes["XF"].inputs["Scale"].default_value = (3, 3, 3)
        wood = bpy.data.materials["Wood"]
        next(n for n in wood.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"].default_value = (1, 0, 0, 1)
        wood.diffuse_color = (1, 0, 0, 1)
        crate.data.name = "Box"


class FidelityTest(HistoryCase):
    def test_round_trip(self):
        start = self.capture()
        bpy.data.node_groups["Inner"].nodes["XF"].inputs["Scale"].default_value = (2, 2, 2)
        self.crate.scale = (1.0, 1.0, 1.0)
        self.crate.modifiers["Bevel"].segments = 4
        self.finish("n0001", "first", self.targets)
        first = self.capture()
        self.assertNotEqual(first, start)
        self.mutate()
        self.assertNotEqual(self.capture(), first)

        names = self.history.restore("n0001", self.scene)
        self.assertEqual(sorted(names), ["Crate", "Crate_Handle"])
        self.assertEqual(self.capture(), first)
        self.assertEqual(self.history.current, "n0001")
        self.assertEqual(self.scene.whittle.history_node, "n0001")
        self.history.restore("n0000", self.scene)
        self.assertEqual(self.capture(), start)
        self.history.restore("n0001", self.scene)
        self.assertEqual(self.capture(), first)
        self.assertEqual(suffixed(), [])
        self.assertEqual(list(bpy.data.libraries), self.libraries)
        self.assertEqual(self.undo.call_count, 3, "one undo step per restore")
        self.assertEqual([t.object.name for t in self.scene.whittle.targets], ["Crate", "Crate_Handle"])
        saved, _ = __import__("whittle.tree", fromlist=["read_session"]).read_session(self.session.session_path())
        self.assertEqual(saved.current, "n0001")

    def test_created_objects_come_and_go_with_their_node(self):
        self.finish("n0001", "first", self.targets)
        lid = cube("Crate_Lid", 0.5, collection=self.props_coll)
        lid.scale.z = 0.1
        user = cube("UserBox", 0.2)
        bundle.ensure_uid(user)
        self.scene.whittle.targets.add().object = user
        node = self.finish("n0002", "lid", self.targets + [lid], created=[lid])
        self.assertEqual(node.created_uids, [lid["whittle_uid"]])
        manifest = formats.read_target_manifest(self.session.target_blend("n0002").with_suffix(".json"))
        self.assertIn(lid["whittle_uid"], [o["uid"] for o in manifest["objects"]])

        self.history.restore("n0001", self.scene)
        self.assertNotIn("Crate_Lid", bpy.data.objects)
        self.assertNotIn("Crate_Lid", bpy.data.meshes)
        self.assertIn("UserBox", bpy.data.objects, "a user object is never deleted")
        self.history.restore("n0002", self.scene)
        self.assertIn("Crate_Lid", bpy.data.objects)
        self.assertAlmostEqual(bpy.data.objects["Crate_Lid"].scale.z, 0.1, places=5)
        self.assertEqual(suffixed(), [])

    def test_bystander_is_untouched(self):
        before, baseline = self.bystander_state(), counts()
        self.finish("n0001", "first", self.targets)
        self.mutate()
        self.history.restore("n0000", self.scene)
        self.history.restore("n0001", self.scene)
        comparison = compare.start(self.history, "n0000", self.scene)
        comparison.toggle(self.scene)
        comparison.toggle(self.scene)
        comparison.end(self.scene, keep=False)
        compare.show_ghost(self.history, "n0000", self.scene)
        compare.clear_ghost()
        self.assertEqual(self.bystander_state(), before)
        self.assertEqual(counts(), baseline)
        self.assertEqual(suffixed(), [])


def by_uid(uid):
    return sorted(o.name for o in bpy.data.objects if o.get("whittle_uid") == uid)


class IdentityTest(HistoryCase):
    """Restore finds each object by its whittle_uid, never by a name some
    other object may have taken since."""

    def test_renamed_target_is_restored_in_place(self):
        uid = self.crate["whittle_uid"]
        self.crate.name = "Crate_Body"
        self.crate.scale = (2.0, 2.0, 2.0)
        self.finish("n0001", "rename", self.targets)

        self.history.restore("n0000", self.scene)
        self.assertEqual(by_uid(uid), ["Crate"])
        self.assertEqual(tuple(bpy.data.objects["Crate"].scale), (1.0, 1.0, 1.0))
        self.assertEqual(bpy.data.objects["Crate_Handle"].parent.name, "Crate")
        self.history.restore("n0001", self.scene)
        self.assertEqual(by_uid(uid), ["Crate_Body"])
        self.assertEqual(tuple(bpy.data.objects["Crate_Body"].scale), (2.0, 2.0, 2.0))
        self.assertEqual(suffixed(), [])
        self.assertEqual([t.object.name for t in self.scene.whittle.targets], ["Crate_Body", "Crate_Handle"])

        comparison = compare.start(self.history, "n0000", self.scene)
        self.assertEqual(by_uid(uid), ["Crate"])
        comparison.toggle(self.scene)
        self.assertEqual(by_uid(uid), ["Crate_Body"])
        comparison.end(self.scene, keep=False)
        self.assertEqual(by_uid(uid), ["Crate_Body"])

    def test_a_user_object_that_took_an_old_name_is_kept(self):
        self.finish("n0001", "first", self.targets)
        leg = cube("Leg", 0.1, collection=self.props_coll)
        self.finish("n0002", "leg", self.targets + [leg], created=[leg])
        uid = leg["whittle_uid"]
        leg.name = "TableLeg"
        self.finish("n0003", "rename", self.targets + [leg])
        mine = cube("Leg", 0.3)
        mine["mine"] = 1
        self.assertEqual(mine.name, "Leg")

        self.history.restore("n0002", self.scene)
        self.assertEqual(by_uid(uid), ["Leg"])
        self.assertNotIn("TableLeg", bpy.data.objects)
        kept = [o for o in bpy.data.objects if o.get("mine") == 1]
        self.assertEqual(len(kept), 1, "the user's object is never deleted")
        self.assertNotEqual(kept[0].name, "Leg", "it moves aside for the restored name")
        self.assertNotIn("whittle_uid", kept[0])

        self.history.restore("n0001", self.scene)
        self.assertEqual(by_uid(uid), [])
        self.assertEqual(len([o for o in bpy.data.objects if o.get("mine") == 1]), 1)

    def test_an_agent_copy_gets_its_own_uid(self):
        self.finish("n0001", "first", self.targets)
        copy = self.crate.copy()
        copy.data = self.crate.data.copy()
        copy.name = "Crate_Twin"
        self.props_coll.objects.link(copy)
        self.assertEqual(copy["whittle_uid"], self.crate["whittle_uid"])
        uid = self.crate["whittle_uid"]
        node = self.finish("n0002", "twin", self.targets + [copy], created=[copy])
        self.assertNotEqual(copy["whittle_uid"], uid)
        self.assertEqual(node.created_uids, [copy["whittle_uid"]])
        self.history.restore("n0001", self.scene)
        self.assertNotIn("Crate_Twin", bpy.data.objects)
        self.history.restore("n0002", self.scene)
        self.assertEqual(by_uid(uid), ["Crate"])
        self.assertIn("Crate_Twin", bpy.data.objects)

    def agent_lid(self):
        self.finish("n0001", "first", self.targets)
        lid = cube("Lid", 0.5, collection=self.props_coll)
        self.scene.whittle.targets.add().object = lid
        self.finish("n0002", "lid", self.targets + [lid], created=[lid])
        return lid

    def users_copy(self, obj, name):
        copy = obj.copy()
        copy.data = obj.data.copy()
        copy.name = name
        self.scene.collection.objects.link(copy)
        self.assertEqual(copy["whittle_uid"], obj["whittle_uid"])
        return copy

    def test_a_user_copy_of_an_agent_object_is_kept(self):
        lid = self.agent_lid()
        uid = lid["whittle_uid"]
        mine = self.users_copy(lid, "MyLid")
        mine["mine"] = 1

        self.history.restore("n0001", self.scene)
        self.assertNotIn("Lid", bpy.data.objects)
        self.assertIn("MyLid", bpy.data.objects, "the user's copy is never deleted")
        self.assertNotEqual(bpy.data.objects["MyLid"]["whittle_uid"], uid, "the copy is the user's own")
        self.history.restore("n0002", self.scene)
        self.assertEqual(by_uid(uid), ["Lid"])
        self.assertIn("MyLid", bpy.data.objects)

        comparison = compare.start(self.history, "n0001", self.scene)
        self.assertIn("MyLid", bpy.data.objects)
        comparison.end(self.scene, keep=True)
        self.assertIn("MyLid", bpy.data.objects)
        self.assertNotIn("Lid", bpy.data.objects)

    def test_copies_that_cannot_be_told_apart_are_all_kept(self):
        lid = self.agent_lid()
        uid = lid["whittle_uid"]
        lid.name = "Top"
        self.scene.whittle.targets.clear()
        self.users_copy(lid, "Top2")

        self.history.restore("n0001", self.scene)
        self.assertEqual(by_uid(uid), ["Top", "Top2"], "neither is removed")


class UserTargetTest(HistoryCase):
    """An object of the user's that joined the target after a node is left
    in the scene by anything that shows that node, as a Restore leaves it."""

    def setUp(self):
        super().setUp()
        self.box = cube("UserBox", 0.3)
        self.box.location = (0, 3, 0)
        self.finish("n0001", "with the box", self.targets + [self.box])

    def test_restore_keeps_it(self):
        self.history.restore("n0000", self.scene)
        self.assertIn("UserBox", bpy.data.objects)

    def test_compare_and_keep_keep_it(self):
        self.box.location.x = 1.0
        comparison = compare.start(self.history, "n0000", self.scene)
        self.assertIn("UserBox", bpy.data.objects)
        comparison.toggle(self.scene)
        self.assertEqual(bpy.data.objects["UserBox"].location.x, 1.0)
        comparison.toggle(self.scene)
        comparison.end(self.scene, keep=True)
        self.assertIn("UserBox", bpy.data.objects)
        self.assertEqual(self.history.current, "n0000")
        self.assertEqual(suffixed(), [])

    def test_compare_end_brings_back_the_live_scene(self):
        bpy.data.objects.remove(self.box)
        comparison = compare.start(self.history, "n0001", self.scene)
        self.assertIn("UserBox", bpy.data.objects, "the node shows its own box")
        comparison.end(self.scene, keep=False)
        self.assertNotIn("UserBox", bpy.data.objects, "the live scene had none")
        self.assertEqual(suffixed(), [])


class DependencyTest(HistoryCase):
    """What an appended object brings along that is not part of the target
    (a collection a modifier uses, its action) is the file's own, and never
    duplicated."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self._clear_actions)
        self.cutters = bpy.data.collections.new("Cutters")
        self.scene.collection.children.link(self.cutters)
        cube("Cut1", 0.1, collection=self.cutters)
        boolean = self.crate.modifiers.new("Bool", "BOOLEAN")
        boolean.operand_type = "COLLECTION"
        boolean.collection = self.cutters
        self.crate.keyframe_insert("location", frame=1)
        self.crate.animation_data.action.name = "CrateAction"
        self.finish("n0001", "cutters", self.targets)

    def _clear_actions(self):
        for action in list(bpy.data.actions):
            bpy.data.actions.remove(action)

    def state(self):
        crate = bpy.data.objects["Crate"]
        return {
            "collections": sorted(c.name for c in bpy.data.collections),
            "actions": sorted(a.name for a in bpy.data.actions),
            "objects": sorted(o.name for o in bpy.data.objects),
            "bool": crate.modifiers["Bool"].collection.name,
            "action": crate.animation_data.action.name,
            "counts": counts(),
        }

    def test_restores_do_not_duplicate_dependencies(self):
        before = self.state()
        for _ in range(3):
            self.history.restore("n0001", self.scene)
        self.history.restore("n0000", self.scene)
        self.history.restore("n0001", self.scene)
        self.assertEqual(self.state(), before)
        self.assertIs(bpy.data.objects["Crate"].modifiers["Bool"].collection, self.cutters)

    def test_compare_and_ghost_do_not_leak(self):
        before = self.state()
        comparison = compare.start(self.history, "n0000", self.scene)
        comparison.toggle(self.scene)
        comparison.toggle(self.scene)
        comparison.end(self.scene, keep=False)
        self.assertEqual(self.state(), before)
        compare.show_ghost(self.history, "n0001", self.scene)
        ghost = next(o for o in bpy.data.objects if targets.GHOST_PROP in o)
        self.assertTrue(ghost.modifiers["Bool"].collection.name.startswith(compare.GHOST_PREFIX))
        compare.clear_ghost()
        self.assertEqual(self.state(), before)


class FilesTest(HistoryCase):
    def test_target_manifest_and_thumbnail(self):
        lid = cube("Crate_Lid", 0.5, collection=self.props_coll)
        self.finish("n0001", "lid", self.targets + [lid], created=[lid])
        manifest = formats.read_target_manifest(self.session.target_blend("n0001").with_suffix(".json"))
        self.assertEqual([o["name"] for o in manifest["objects"]], ["Crate", "Crate_Handle", "Crate_Lid"])
        thumb = self.session.thumb_path("n0001")
        pixels = render.load_pixels(thumb)
        h, w, _ = pixels.shape
        self.assertEqual(max(h, w), history.THUMB_SIZE)
        self.assertGreater(float(pixels[..., :3].std()), 0.01, "the target is in the thumbnail")
        self.assertTrue(self.session.thumb_path("n0000").is_file())
        self.assertTrue(self.history.can_restore("n0001"))

    def test_empty_root(self):
        empty = history.History(formats.SessionDir(self.tmp / "empty"))
        empty.ensure_root([], self.scene)
        self.assertTrue(empty.can_restore("n0000"))
        self.assertFalse(empty.session.thumb_path("n0000").exists())
        self.assertEqual(empty.restore("n0000", self.scene), [])
        self.assertIn("Crate", bpy.data.objects)


class SketchModeTest(HistoryCase):
    def test_restore_keeps_the_sketch_in_draw_mode(self):
        self.finish("n0001", "first", self.targets)
        session = sketch.start_session(bpy.context, use_timer=False, viewport_provider=lambda: None)
        self.addCleanup(sketch.end_session)
        obj = sketch.find_sketch_object()
        self.assertEqual(obj.mode, "PAINT_GREASE_PENCIL")
        self.history.restore("n0000", self.scene)
        self.assertEqual(obj.mode, "PAINT_GREASE_PENCIL")
        self.assertTrue(session.active)
        self.assertFalse(targets.eligible(obj))
        self.scene.whittle.target_auto = True
        targets.select_list(self.scene)
        self.assertIs(bpy.context.view_layer.objects.active, obj, "the draw tool keeps its object")
        self.assertTrue(obj.select_get())

    def test_an_undo_out_of_draw_mode_ends_the_session(self):
        sketch.start_session(bpy.context, use_timer=False, viewport_provider=lambda: None)
        self.addCleanup(sketch.end_session)
        tools = self.scene.tool_settings
        sketch.after_undo()
        self.assertIsNotNone(sketch.current_session(), "still drawing: nothing to do")
        bpy.ops.object.mode_set(mode="OBJECT")
        tools.gpencil_stroke_placement_view3d = "CURSOR"
        sketch.after_undo()
        self.assertIsNone(sketch.current_session())
        self.assertEqual(tools.gpencil_stroke_placement_view3d, "CURSOR",
                         "the tool settings are left as the undo put them")


if __name__ == "__main__":
    unittest.main()
