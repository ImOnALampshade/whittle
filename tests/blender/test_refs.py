# SPDX-License-Identifier: GPL-3.0-or-later
import json
import math
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Quaternion, Vector

from tests.blender.helpers import CRATE_BUNDLE, pump
from tests.blender.history_helpers import STROKE, HistoryTurnCase
from tests.blender.sketch_helpers import add_stroke
from tests.blender.ui_helpers import RecordingLayout
from whittle.addon import operators, refs, targets, ui

PNG = CRATE_BUNDLE / "views" / "1" / "overlay.png"


class RefsCase(HistoryTurnCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-refs-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.front = self.tmp / "front.png"
        self.side = self.tmp / "side.png"
        shutil.copyfile(PNG, self.front)
        shutil.copyfile(PNG, self.side)
        self.props.refs.clear()
        self.addCleanup(self.props.refs.clear)
        self.addCleanup(self.remove_reference_objects)

    def remove_reference_objects(self):
        for obj in list(bpy.data.objects):
            if obj.get(targets.REFERENCE_PROP) == "image":
                bpy.data.objects.remove(obj)

    def add_ref(self, path, pinned=False):
        ref = self.props.refs.add()
        ref.path = str(path)
        ref.pinned = pinned
        return ref

    def paths(self):
        return [Path(r.path).name for r in self.props.refs]


class ClearSentTest(RefsCase):
    def test_keeps_pinned_and_unsent(self):
        self.add_ref(self.front, pinned=True)
        self.add_ref(self.side)
        other = self.tmp / "other.png"
        shutil.copyfile(PNG, other)
        self.add_ref(other)
        removed = refs.clear_sent(self.scene, [self.front, self.side])
        self.assertEqual(removed, 1)
        self.assertEqual(self.paths(), ["front.png", "other.png"])


class RefsTurnTest(RefsCase):
    def submit_with_refs(self, ctl, prompt="Use the references."):
        add_stroke(self.obj, "free", STROKE, view=1, radius=0.01)
        sent = [Path(r.path) for r in self.props.refs]
        return ctl.run_sketch(prompt, targets=targets.resolve(self.scene), refs=sent, scene=self.scene)

    def test_success_clears_unpinned_refs(self):
        self.add_ref(self.front, pinned=True)
        self.add_ref(self.side)
        ctl = self.controller("sketch_turn.json")
        node = self.submit_with_refs(ctl)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 30, "the turn")
        self.assertEqual(ctl.errors, [])
        request = json.loads((ctl.session.request_dir(node) / "request.json").read_text())
        self.assertEqual(request["refs"], ["refs/front.png", "refs/side.png"])
        self.assertEqual(self.paths(), ["front.png"])
        self.assertTrue(self.props.refs[0].pinned)

    def test_branch_attaches_the_sent_refs_again(self):
        shutil.copyfile(CRATE_BUNDLE / "views" / "1" / "strokes.png", self.side)
        self.add_ref(self.front, pinned=True)
        self.add_ref(self.side)
        ctl = self.controller("sketch_turn.json")
        node = self.submit_with_refs(ctl)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 30, "the turn")
        self.assertEqual(self.paths(), ["front.png"])
        operators.branch_node(bpy.context, node)
        # The pinned one is still listed, so only the cleared one comes back,
        # from the copy the request kept.
        self.assertEqual(self.paths(), ["front.png", "side.png"])
        self.assertEqual(Path(self.props.refs[1].path).parent, ctl.session.request_dir(node) / "refs")
        self.assertFalse(self.props.refs[1].pinned)

    def test_failed_turn_keeps_every_ref(self):
        self.add_ref(self.front, pinned=True)
        self.add_ref(self.side)
        ctl = self.controller("crash.json")
        self.submit_with_refs(ctl)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 30, "the turn")
        self.assertEqual(self.paths(), ["front.png", "side.png"])


class PlaceEmptyTest(RefsCase):
    def test_place_empty(self):
        images = len(bpy.data.images)
        obj = refs.place_empty(self.scene, self.front)
        self.assertEqual((obj.type, obj.empty_display_type), ("EMPTY", "IMAGE"))
        self.assertEqual(Path(obj.data.filepath).name, "front.png")
        self.assertEqual(obj[targets.REFERENCE_PROP], "image")
        self.assertEqual(obj[refs.REF_PATH_PROP], str(self.front))
        self.assertIn(obj, bpy.data.collections[targets.REFERENCE_COLLECTION].objects[:])
        self.assertTrue(obj.use_empty_image_alpha)
        self.assertAlmostEqual(obj.color[3], refs.ALPHA)
        self.assertTrue(obj.hide_render)
        self.assertFalse(targets.eligible(obj))
        self.assertEqual(len(bpy.data.images), images + 1)

        again = refs.place_empty(self.scene, self.front, align="TOP")
        self.assertIsNot(again, obj)
        self.assertEqual(len(bpy.data.images), images + 1, "the image is loaded once")

    def test_alignment(self):
        expected = {"FRONT": (math.pi / 2, 0, 0), "RIGHT": (math.pi / 2, 0, math.pi / 2), "TOP": (0, 0, 0)}
        for align, rotation in expected.items():
            with self.subTest(align=align):
                obj = refs.place_empty(self.scene, self.front, align=align)
                for got, want in zip(obj.rotation_euler, rotation):
                    self.assertAlmostEqual(got, want, places=5)
                # The image faces the side it is seen from.
                normal = obj.rotation_euler.to_matrix() @ Vector((0, 0, 1))
                facing = {"FRONT": Vector((0, -1, 0)), "RIGHT": Vector((1, 0, 0)), "TOP": Vector((0, 0, 1))}
                self.assertAlmostEqual(normal.dot(facing[align]), 1.0, places=5)

    def test_view_alignment_and_fallback(self):
        fallback = refs.place_empty(self.scene, self.front, align="VIEW")
        self.assertAlmostEqual(fallback.rotation_euler.x, math.pi / 2, places=5)
        view = SimpleNamespace(view_rotation=Quaternion((1, 0, 0), math.radians(60)),
                               view_location=Vector((0.1, 0.2, 0.3)))
        obj = refs.place_empty(self.scene, self.front, align="VIEW", view=view)
        self.assertAlmostEqual(obj.rotation_euler.x, math.radians(60), places=5)
        self.assertEqual(tuple(round(v, 5) for v in obj.location), (0.1, 0.2, 0.3))

    def test_place_facing_the_view_from_the_sidebar(self):
        # The chip's menu runs in the sidebar region, which has no view of
        # its own (tests/gui's references_view): the viewport beside it has.
        self.add_ref(self.front)
        rv3d = SimpleNamespace(view_rotation=Quaternion((1, 0, 0), math.radians(60)),
                               view_location=Vector((0.1, 0.2, 0.3)))
        sidebar = SimpleNamespace(type="UI", data=None)
        main = SimpleNamespace(type="WINDOW", data=rv3d)
        area = SimpleNamespace(type="VIEW_3D", regions=[sidebar, main])
        context = SimpleNamespace(area=area, region=sidebar, region_data=None, scene=self.scene)
        op = SimpleNamespace(index=0, align="VIEW", report=lambda *_args: None)
        self.assertEqual(refs.WHITTLE_OT_ref_place.execute(op, context), {"FINISHED"})
        (obj,) = [o for o in bpy.data.objects if o.get(targets.REFERENCE_PROP) == "image"]
        self.assertAlmostEqual(obj.rotation_euler.x, math.radians(60), places=5)

    def test_missing_image(self):
        with self.assertRaises(FileNotFoundError):
            refs.place_empty(self.scene, self.tmp / "nope.png")

    def test_operators(self):
        self.add_ref(self.front)
        self.assertEqual(bpy.ops.whittle.ref_pin(index=0), {"FINISHED"})
        self.assertTrue(self.props.refs[0].pinned)
        self.assertEqual(bpy.ops.whittle.ref_place(index=0, align="RIGHT"), {"FINISHED"})
        placed = [o for o in bpy.data.objects if o.get(targets.REFERENCE_PROP) == "image"]
        self.assertEqual(len(placed), 1)
        self.assertEqual(bpy.ops.whittle.ref_place(index=5), {"CANCELLED"})

    def test_reference_chips_have_pin_and_a_menu_to_place(self):
        self.add_ref(self.front, pinned=True)
        layout = RecordingLayout()
        ui.draw_references(layout, ui.Ctx(scene=self.scene, hist=None, ctl=None, comparing=None))
        self.assertEqual([c["icon"] for c in layout.operators("whittle.ref_pin")], ["PINNED"])
        self.assertEqual(layout.operators("whittle.ref_menu")[0]["props"].index, 0)
        menu = RecordingLayout()
        ui.draw_ref_menu(menu, 0)
        (pin,) = menu.operators("whittle.ref_pin")
        self.assertEqual((pin["text"], pin["props"].index), ("Unpin", 0))
        places = menu.operators("whittle.ref_place")
        self.assertEqual([(c["props"].index, c["props"].align) for c in places],
                         [(0, "VIEW"), (0, "FRONT"), (0, "RIGHT"), (0, "TOP")])
        self.assertEqual(len(menu.operators("whittle.open_image")), 1)
        self.assertEqual(menu.operators("whittle.ref_remove")[0]["props"].index, 0)
