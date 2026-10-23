# SPDX-License-Identifier: GPL-3.0-or-later
"""Mid-turn checkpoints: blender.checkpoint saves the turn's objects and
restore_checkpoint puts them back, removing what the agent made after it,
without confusing a later Interrupt -> Restore."""

import bpy

from tests.blender.helpers import pump
from tests.blender.history_helpers import HistoryTurnCase
from whittle import formats


def mesh_coords(obj):
    return [tuple(round(c, 5) for c in v.co) for v in obj.data.vertices]


class CheckpointTest(HistoryTurnCase):
    def test_restore_checkpoint(self):
        verts = mesh_coords(self.crate)
        location = tuple(self.crate.location)
        ctl = self.controller("checkpoint.json")
        node = self.turn(ctl, "Try something risky.")
        finished = ctl.last_finished
        self.assertEqual(finished["errors"], [], "c1 restores and c9 is not_found")

        blend, manifest = ctl.session.checkpoint_paths(node, "c1")
        self.assertTrue(blend.is_file() and manifest.is_file())
        self.assertEqual([o["name"] for o in formats.read_target_manifest(manifest)["objects"]], ["Crate"])

        crate = bpy.data.objects["Crate"]
        self.assertEqual(tuple(crate.scale), (1.5, 1.5, 1.5))
        self.assertEqual(tuple(crate.location), location)
        self.assertEqual(mesh_coords(crate), verts)
        self.assertNotIn("Crate_Lid", bpy.data.objects)
        self.assertNotIn("Crate_Lid", bpy.data.meshes)
        self.assertEqual([s.material.name for s in crate.material_slots], ["Wood"])
        self.assertEqual(ctl.history.node(node).created_uids, [])
        self.assertEqual([t.object.name for t in self.props.targets], ["Crate"])

        second = self.turn(ctl, "Again.")
        self.assertTrue(ctl.session.checkpoint_paths(second, "c1")[0].is_file(),
                        "checkpoint ids start again each turn")
        self.assertFalse(ctl.session.checkpoint_paths(second, "c2")[0].exists())

    def test_interrupt_restore_after_a_checkpoint_restore(self):
        ctl = self.controller("checkpoint_interrupt.json")
        node = self.submit(ctl, "Risky.")
        # exec, checkpoint, exec, restore_checkpoint
        pump(ctl, lambda: sum(e["name"] == "tool_result" for e in ctl.events) == 4, 15,
             "the checkpoint restore")
        bpy.context.view_layer.update()
        self.assertNotIn("Crate_Lid", bpy.data.objects)

        ctl.interrupt(restore=True)
        finished = self.wait(ctl, node)
        self.assertEqual(finished["restored"], ["Crate"])
        crate = bpy.data.objects["Crate"]
        self.assertEqual(tuple(crate.scale), (1.0, 1.0, 1.0))
        self.assertAlmostEqual(crate.location.z, 0.25)
        self.assertEqual(ctl.history.node(node).created_uids, [], "the crate existed before the turn")

    def test_a_target_the_agent_renamed_is_still_saved(self):
        ctl = self.controller("checkpoint_rename.json")
        node = self.turn(ctl, "Rename it.")
        uid = ctl.bundle.request.target[0]["uid"]
        self.assertEqual(ctl.last_finished["errors"], [])

        _blend, manifest = ctl.session.checkpoint_paths(node, "c1")
        self.assertEqual([o["name"] for o in formats.read_target_manifest(manifest)["objects"]], ["Hull"])
        hull = bpy.data.objects["Hull"]
        self.assertEqual(hull.get("whittle_uid"), uid)
        self.assertEqual(tuple(hull.scale), (1.0, 1.0, 1.0), "the checkpoint restore undid the scale")
        self.assertEqual(hull.location.z, 1.0)

        snap = formats.read_target_manifest(ctl.session.target_blend(node).with_suffix(".json"))
        self.assertEqual([o["name"] for o in snap["objects"]], ["Hull"])
        ctl.history.restore("n0000", self.scene)
        self.assertEqual([o.name for o in bpy.data.objects if o.get("whittle_uid") == uid], ["Crate"])
        ctl.history.restore(node, self.scene)
        self.assertEqual(bpy.data.objects["Hull"].location.z, 1.0)
