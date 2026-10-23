# SPDX-License-Identifier: GPL-3.0-or-later
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy
from mathutils import Vector

from tests.blender.helpers import AgentTestCase, pump
from tests.blender.sketch_helpers import add_stroke, look_at_view
from tests.blender.ui_helpers import RecordingLayout
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import compare, history, sketch, start, targets, turn, ui, views


def clear_whittle_collections():
    for collection in list(bpy.data.collections):
        if collection.name.startswith("Whittle"):
            for obj in list(collection.objects):
                bpy.data.objects.remove(obj)
            bpy.data.collections.remove(collection)


def world_z(obj):
    return [(obj.matrix_world @ v.co).z for v in obj.data.vertices]


class StartCase(AgentTestCase):
    script = None

    def setUp(self):
        super().setUp()
        sketch.end_session()
        clear_whittle_collections()
        self.crate = build_scene()
        old = sketch.find_sketch_object()
        if old is not None:
            bpy.data.objects.remove(old)
        compare.reset()
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.addCleanup(clear_whittle_collections)
        self.scene = bpy.context.scene
        self.scene.cursor.location = (0.0, 0.0, 0.0)
        self.props = self.scene.whittle
        self.props.target_auto = False
        self.props.targets.clear()
        self.props.target_collection = None
        self.props.history_node = ""
        bpy.context.window_manager.whittle_fake_script = ""
        patcher = mock.patch.object(history, "undo_push")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctl = self.make_controller(self.script)
        turn.set_current(self.ctl)
        self.addCleanup(turn.set_current, None)

    @property
    def hist(self):
        return self.ctl.history

    def manifest_names(self, node="n0000"):
        path = self.ctl.session.target_blend(node).with_suffix(".json")
        return [o["name"] for o in formats.read_target_manifest(path)["objects"]]

    def select(self, *objects):
        for obj in self.scene.objects:
            obj.select_set(obj in objects)

    def add_turn(self):
        self.hist.tree.add("n0001", "n0000", prompt="a turn")
        self.hist.save()


class StartExistingTest(StartCase):
    def test_selection_becomes_the_target_and_node_zero(self):
        self.select(self.crate)
        message = start.start_existing(bpy.context, self.ctl)
        self.assertIn("Crate", message)
        self.assertEqual(targets.resolve(self.scene), [self.crate])
        self.assertTrue(self.ctl.session.target_blend("n0000").is_file())
        self.assertEqual(self.manifest_names(), ["Crate"])
        self.assertEqual(self.hist.current, "n0000")
        self.assertEqual(self.props.history_node, "n0000")

    def test_a_fresh_root_is_rewritten(self):
        self.select(self.crate)
        start.start_existing(bpy.context, self.ctl)
        peg = bpy.data.objects.new("Peg", bpy.data.meshes.new("Peg"))
        self.scene.collection.objects.link(peg)
        self.select(self.crate, peg)
        start.start_existing(bpy.context, self.ctl)
        self.assertEqual(sorted(self.manifest_names()), ["Crate", "Peg"])
        self.assertEqual(list(self.hist.tree.nodes), ["n0000"])

    def test_refused_once_the_history_has_turns(self):
        self.select(self.crate)
        start.start_existing(bpy.context, self.ctl)
        self.add_turn()
        with self.assertRaises(start.StartError):
            start.start_existing(bpy.context, self.ctl)
        self.assertFalse(bpy.ops.whittle.start_existing.poll())

    def test_nothing_selected_keeps_the_picker(self):
        self.props.targets.add().object = self.crate
        self.select()
        start.start_existing(bpy.context, self.ctl)
        self.assertEqual(targets.resolve(self.scene), [self.crate])
        self.assertEqual(self.manifest_names(), ["Crate"])

    def test_operator(self):
        self.select(self.crate)
        self.assertEqual(bpy.ops.whittle.start_existing(), {"FINISHED"})
        self.assertIs(turn.current(), self.ctl, "the controller is reused")
        self.assertEqual(self.manifest_names(), ["Crate"])


class StartBlankTest(StartCase):
    def counts(self):
        return (len(bpy.data.objects), len(bpy.data.collections), len(bpy.data.meshes))

    def test_blank_start(self):
        location = tuple(self.crate.location)
        self.select(self.crate)
        before = self.counts()
        self.assertIsNone(start.start_blank(bpy.context, self.ctl))
        self.assertEqual(self.counts(), before, "nothing is added to the scene")
        self.assertEqual(bpy.context.selected_objects, [], "nothing selected")
        self.assertIsNone(bpy.context.view_layer.objects.active)
        self.assertEqual(len(self.props.targets), 0)
        self.assertIsNone(self.props.target_collection)
        self.assertEqual(targets.resolve(self.scene), [])

        self.assertEqual(self.manifest_names(), [])
        self.assertEqual(self.hist.tree.node("n0000").label, "Blank")
        self.assertTrue(self.hist.can_restore("n0000"))
        self.hist.restore("n0000", self.scene, undo=False)
        self.assertIn(self.crate.name, self.scene.objects)
        self.assertEqual(tuple(self.crate.location), location, "the scene's own objects are untouched")

    def test_again_adds_nothing(self):
        start.start_blank(bpy.context, self.ctl)
        before = self.counts()
        start.start_blank(bpy.context, self.ctl)
        self.assertEqual(self.counts(), before)

    def test_operator_in_background(self):
        self.assertEqual(bpy.ops.whittle.start_blank(), {"FINISHED"})
        self.assertIsNone(sketch.current_session(), "no sketch mode either")
        self.assertIsNone(self.props.target_collection)


class StartPrimitiveTest(StartCase):
    def test_each_primitive(self):
        self.scene.cursor.location = (0.5, -0.25, 0.7)
        for kind in start.PRIMITIVES:
            with self.subTest(kind=kind):
                obj = start.start_primitive(bpy.context, self.ctl, kind, size=0.8)
                self.assertEqual(targets.resolve(self.scene), [obj])
                self.assertIn(obj, bpy.data.collections[start.TARGET_COLLECTION].objects[:])
                self.assertAlmostEqual(min(world_z(obj)), 0.0, places=5)
                self.assertAlmostEqual(max(obj.dimensions), 0.8, places=5)
                self.assertEqual((obj.location.x, obj.location.y), (0.5, -0.25))
                self.assertEqual(self.manifest_names(), [obj.name])
                if kind == "CUBE":
                    self.assertEqual(len(obj.data.vertices), 8)
                bpy.data.objects.remove(obj)
        self.assertNotIn("Whittle Ground", bpy.data.objects, "no ground or other helper")

    def test_unknown_kind(self):
        with self.assertRaises(start.StartError):
            start.start_primitive(bpy.context, self.ctl, "TEAPOT")

    def test_operator(self):
        self.assertEqual(bpy.ops.whittle.start_primitive(kind="CYLINDER", size=2.0), {"FINISHED"})
        (obj,) = targets.resolve(self.scene)
        self.assertEqual(obj.name, "Cylinder")
        self.assertAlmostEqual(obj.dimensions.z, 2.0, places=5)


class StartAssetTest(StartCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-assets-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.library = self.tmp / "assets.blend"
        barrel = bpy.data.objects.new("Barrel", start.primitive_mesh("CYLINDER", 0.6, "Barrel"))
        fence = bpy.data.collections.new("Fence")
        for name in ("Post", "Rail"):
            fence.objects.link(bpy.data.objects.new(name, start.primitive_mesh("CUBE", 0.2, name)))
        barrel.asset_mark()
        fence.asset_mark()
        bpy.data.libraries.write(str(self.library), {barrel, fence})
        for obj in list(fence.objects) + [barrel]:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(fence)
        self.libraries = len(bpy.data.libraries)

    def test_object_asset_is_appended(self):
        self.scene.cursor.location = (1.0, 2.0, 0.0)
        (obj,) = start.start_asset(bpy.context, self.ctl, filepath=str(self.library), id_type="OBJECT",
                                   name="Barrel")
        self.assertEqual(obj.name, "Barrel")
        self.assertEqual(targets.resolve(self.scene), [obj])
        self.assertIsNone(obj.asset_data, "the copy is not an asset of this file")
        self.assertEqual(len(bpy.data.libraries), self.libraries, "no library is left behind")
        self.assertEqual(tuple(obj.location), (1.0, 2.0, 0.0))
        self.assertEqual(self.manifest_names(), ["Barrel"])
        self.assertEqual(self.hist.tree.node("n0000").label, "Asset: Barrel")

    def test_collection_asset_brings_its_objects(self):
        objects = start.start_asset(bpy.context, self.ctl, filepath=str(self.library),
                                    id_type="COLLECTION", name="Fence")
        self.assertEqual(sorted(o.name for o in objects), ["Post", "Rail"])
        self.assertEqual(self.props.target_collection.name, "Fence")
        self.assertEqual(len(bpy.data.libraries), self.libraries)
        self.assertEqual(sorted(self.manifest_names()), ["Post", "Rail"])

    def test_a_retake_takes_a_collection_asset_back(self):
        start.start_asset(bpy.context, self.ctl, filepath=str(self.library), id_type="COLLECTION",
                          name="Fence")
        start.start_blank(bpy.context, self.ctl)
        self.assertNotIn("Fence", bpy.data.collections, "the appended collection goes")
        self.assertFalse({"Post", "Rail"} & set(bpy.data.objects.keys()), "with its objects")
        self.assertIsNone(self.props.target_collection)

        local = bpy.data.collections.new("Local Fence")
        local.objects.link(bpy.data.objects.new("Plank", start.primitive_mesh("CUBE", 0.2, "Plank")))
        start.start_asset(bpy.context, self.ctl, filepath="", id_type="COLLECTION", name=local.name,
                          local=True)
        self.assertIn(local.name, self.scene.collection.children)
        start.start_primitive(bpy.context, self.ctl, "CUBE")
        self.assertNotIn(local.name, self.scene.collection.children, "a local one is only unlinked")
        self.assertIn("Plank", bpy.data.objects)
        self.assertNotIn(start.START_PROP, local)

    def test_refusals(self):
        with self.assertRaises(start.StartError):
            start.start_asset(bpy.context, self.ctl, filepath=str(self.library), id_type="OBJECT",
                              name="Nope")
        with self.assertRaises(start.StartError):
            start.start_asset(bpy.context, self.ctl, filepath=str(self.library), id_type="MATERIAL",
                              name="Wood")
        with self.assertRaises(start.StartError):
            start.start_asset(bpy.context, self.ctl, filepath=str(self.tmp / "missing.blend"),
                              id_type="OBJECT", name="Barrel")
        self.assertEqual(len(bpy.data.libraries), self.libraries)
        self.assertNotIn("Barrel", bpy.data.objects)

    def test_local_asset_is_used_in_place(self):
        count = len(bpy.data.objects)
        (obj,) = start.start_asset(bpy.context, self.ctl, filepath="", id_type="OBJECT", name="Crate",
                                   local=True)
        self.assertIs(obj, self.crate)
        self.assertEqual(len(bpy.data.objects), count)
        self.assertEqual(targets.resolve(self.scene), [self.crate])

    def test_operator_with_explicit_properties(self):
        result = bpy.ops.whittle.start_asset(filepath=str(self.library), id_type="OBJECT", name="Barrel")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual([o.name for o in targets.resolve(self.scene)], ["Barrel"])

    def test_asset_browser_entry(self):
        menu = SimpleNamespace(layout=RecordingLayout())
        start.draw_asset_menu(menu, SimpleNamespace(asset=SimpleNamespace(id_type="OBJECT")))
        self.assertEqual(len(menu.layout.operators("whittle.start_asset")), 1)
        menu = SimpleNamespace(layout=RecordingLayout())
        start.draw_asset_menu(menu, SimpleNamespace(asset=SimpleNamespace(id_type="MATERIAL")))
        self.assertEqual(menu.layout.operators(), [])
        self.assertIn(start.draw_asset_menu, bpy.types.ASSETBROWSER_MT_context_menu._dyn_ui_initialize())


class RetakeTest(StartCase):
    def collection_names(self):
        return sorted(o.name for o in bpy.data.collections[start.TARGET_COLLECTION].objects)

    def test_primitive_then_primitive(self):
        start.start_primitive(bpy.context, self.ctl, "CUBE")
        sphere = start.start_primitive(bpy.context, self.ctl, "UV_SPHERE")
        self.assertEqual(targets.resolve(self.scene), [sphere])
        self.assertEqual(self.manifest_names(), [sphere.name])
        self.assertNotIn("Cube", bpy.data.objects)
        self.assertEqual(self.collection_names(), [sphere.name])

    def test_primitive_then_blank(self):
        cube = start.start_primitive(bpy.context, self.ctl, "CUBE")
        name = cube.name
        start.start_blank(bpy.context, self.ctl)
        self.assertNotIn(name, bpy.data.objects, "the retaken start takes the primitive back")
        self.assertEqual(targets.resolve(self.scene), [])
        self.assertEqual(self.manifest_names(), [])

    def test_asset_then_primitive(self):
        self.crate.users_collection[0].objects.unlink(self.crate)
        start.start_asset(bpy.context, self.ctl, filepath="", id_type="OBJECT", name="Crate", local=True)
        self.assertIn(self.crate, bpy.data.collections[start.TARGET_COLLECTION].objects[:])
        cone = start.start_primitive(bpy.context, self.ctl, "CONE")
        self.assertEqual(targets.resolve(self.scene), [cone])
        self.assertIn(self.crate.name, self.scene.objects, "a local object is only unlinked")
        self.assertNotIn(start.START_PROP, self.crate)

    def test_selection_after_a_primitive(self):
        cube = start.start_primitive(bpy.context, self.ctl, "CUBE")
        self.select(self.crate)
        message = start.start_existing(bpy.context, self.ctl)
        self.assertNotIn("Collection", message)
        self.assertIsNone(self.props.target_collection)
        self.assertEqual(targets.resolve(self.scene), [self.crate])
        self.assertEqual(self.manifest_names(), ["Crate"])
        # Now part of the scene the user started from, so a retake keeps it.
        start.start_blank(bpy.context, self.ctl)
        self.assertIn(cube.name, bpy.data.objects)


class CanStartTest(StartCase):
    def test_refusals(self):
        self.assertIsNone(start.can_start(None, None, None))
        self.assertIsNone(start.can_start(self.hist, self.ctl, None))
        busy = SimpleNamespace(running=False, busy=True)
        self.assertIn("turn", start.can_start(self.hist, busy, None))
        self.assertIn("comparison", start.can_start(self.hist, None, object()))
        start.start_existing(bpy.context, self.ctl)
        self.assertIsNone(start.can_start(self.hist, self.ctl, None))
        self.add_turn()
        self.assertIn("turns", start.can_start(self.hist, self.ctl, None))

    def draw(self):
        layout = RecordingLayout()
        ui.draw_main(layout, ui.Ctx(scene=self.scene, hist=self.hist, ctl=self.ctl, comparing=None))
        return layout

    def test_start_row(self):
        layout = self.draw()
        idnames = [c["idname"] for c in layout.operators() if c["idname"].startswith("whittle.start")]
        self.assertEqual(idnames, ["whittle.start_existing", "whittle.start_blank"])
        self.assertEqual([c["text"] for c in layout.operators() if c["idname"].startswith("whittle.start")],
                         ["Selection", "Blank"])
        self.assertEqual(layout.menus(), ["WHITTLE_MT_start_primitive", "WHITTLE_MT_models"])
        menu = SimpleNamespace(layout=RecordingLayout())
        ui.WHITTLE_MT_start_primitive.draw(menu, bpy.context)
        self.assertIn("Asset Browser", menu.layout.text(), "the hint is in the Primitive menu")
        self.props.prompt = "Add a lid."
        self.assertEqual(self.draw().menus(), ["WHITTLE_MT_start_primitive", "WHITTLE_MT_models"], "no target: still offered")
        self.props.targets.add().object = self.crate
        self.assertEqual(self.draw().menus(), ["WHITTLE_MT_models"], "a prompt typed with a target picked: no start row")
        self.props.prompt = ""
        self.props.targets.clear()

        start.start_blank(bpy.context, self.ctl)
        layout = self.draw()
        self.assertIn("Start: Blank", layout.labels(), "the start line names the start taken")
        self.assertEqual(layout.menus(), ["WHITTLE_MT_start_primitive", "WHITTLE_MT_models"],
                         "a start can be taken again until the first turn")

        self.add_turn()
        layout = self.draw()
        self.assertEqual(layout.menus(), ["WHITTLE_MT_models"])
        self.assertIn("Start: Blank", layout.labels(), "the scene is still at the start, a turn after it")


class BlankTurnTest(StartCase):
    script = "sketch_turn.json"

    def test_blank_start_then_a_turn(self):
        start.start_blank(bpy.context, self.ctl)
        obj = sketch.ensure_sketch_layers(self.scene)
        views.add_view(obj.data, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))
        # Away from the crate, so the strokes are on no surface.
        add_stroke(obj, "add", [(1.0, 1.0, 0.0), (1.2, 1.0, 0.0), (1.2, 1.2, 0.0)], view=1)
        node = self.ctl.run_sketch("A crate.", targets=targets.resolve(self.scene), scene=self.scene)
        pump(self.ctl, lambda: self.ctl.last_finished is not None or self.ctl.errors, 30, "the turn")
        self.assertEqual(self.ctl.errors, [])
        request = json.loads((self.ctl.session.request_dir(node) / "request.json").read_text())
        self.assertFalse(request.get("target_collection"))
        self.assertEqual(request["target"], [])
        self.assertEqual(request["parent"], "n0000")
        self.assertEqual(self.hist.tree.node("n0000").label, "Blank")
        self.assertEqual(self.hist.tree.node("n0000").children, [node])
        strokes = json.loads((self.ctl.session.request_dir(node) / "strokes.json").read_text())
        self.assertFalse(any(strokes["strokes"][0]["hit_object"]), "nothing to land on: no ground made")
        self.assertIsNotNone(start.can_start(self.hist, self.ctl, None))
