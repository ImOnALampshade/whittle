# SPDX-License-Identifier: GPL-3.0-or-later
"""Comparing the scene with another history node, and the parent node shown
as a wireframe ghost."""

import subprocess
import sys

import bpy

from tests.blender.helpers import REPO
from tests.blender.history_helpers import HistoryTurnCase
from whittle.addon import compare, operators, targets

COUNTED = ("objects", "meshes", "materials", "node_groups", "collections", "libraries")


def counts():
    return {attr: len(getattr(bpy.data, attr)) for attr in COUNTED}


def crate_state():
    crate = bpy.data.objects["Crate"]
    return {"scale": tuple(round(v, 5) for v in crate.scale),
            "location": tuple(round(v, 5) for v in crate.location),
            "lid": "Crate_Lid" in bpy.data.objects,
            "colour": tuple(round(v, 4) for v in bpy.data.materials["Wood"].diffuse_color)}


class CompareCase(HistoryTurnCase):
    def two_turns(self):
        """n0001 scales the crate, n0002 adds a lid; then the user moves it."""
        ctl = self.controller()
        self.turn(ctl, "Scale it.")
        n1 = crate_state()
        self.turn(ctl, "Add a lid.")
        bpy.data.objects["Crate"].location.x += 0.3
        return ctl, n1, crate_state()


class CompareTest(CompareCase):
    def test_toggle_and_end(self):
        ctl, n1, live = self.two_turns()
        self.undo.reset_mock()
        comparison = operators.compare_node(bpy.context, "n0001")
        self.assertIs(compare.active(), comparison)
        self.assertEqual(comparison.showing, "n0001")
        self.assertEqual(crate_state(), n1)
        self.assertEqual(comparison.toggle(self.scene), compare.LIVE)
        self.assertEqual(crate_state(), live, "the live side keeps the user's edit")
        comparison.toggle(self.scene)
        self.assertEqual(crate_state(), n1)
        self.assertEqual(self.undo.call_count, 0, "toggling is not an undo step")

        comparison.end(self.scene, keep=False)
        self.assertIsNone(compare.active())
        self.assertEqual(crate_state(), live)
        self.assertEqual(ctl.history.current, "n0002")
        self.assertEqual(self.undo.call_count, 1)
        self.assertFalse((ctl.session.compare_dir() / "live.blend").exists())
        self.assertEqual([b.name for b in bpy.data.objects if ".00" in b.name], [])

    def test_end_keeps_the_target_list(self):
        """Comparing with a node that lacks the lid removes it for a while;
        back on the live side, and after End, it is a target again."""
        self.two_turns()
        before = [t.object.name for t in self.props.targets]
        self.assertEqual(before, ["Crate", "Crate_Lid"])
        comparison = operators.compare_node(bpy.context, "n0001")
        self.assertFalse("Crate_Lid" in bpy.data.objects)
        comparison.toggle(self.scene)
        self.assertEqual([t.object.name for t in self.props.targets if t.object], before)
        comparison.toggle(self.scene)
        comparison.end(self.scene, keep=False)
        self.assertEqual([t.object.name for t in self.props.targets if t.object], before)
        self.assertEqual(len(self.props.targets), 2)
        self.assertEqual(targets.resolve(self.scene), [bpy.data.objects["Crate"], bpy.data.objects["Crate_Lid"]])

    def test_keep(self):
        ctl, n1, _live = self.two_turns()
        comparison = operators.compare_node(bpy.context, "n0001")
        comparison.toggle(self.scene)
        comparison.end(self.scene, keep=True)
        self.assertEqual(ctl.history.current, "n0001")
        self.assertEqual(crate_state(), n1)
        self.assertEqual([t.object.name for t in self.props.targets], ["Crate"])

    def test_a_failed_end_keeps_the_live_scene(self):
        ctl, _n1, live = self.two_turns()
        comparison = operators.compare_node(bpy.context, "n0001")
        ctl.session.target_blend("n0001").unlink()
        with self.assertRaises(RuntimeError):
            comparison.end(self.scene, keep=True)
        self.assertIs(compare.active(), comparison, "the comparison stays")
        self.assertTrue(comparison.live_blend.is_file(), "with the only copy of the live scene")
        comparison.end(self.scene, keep=False)
        self.assertEqual(crate_state(), live)
        self.assertIsNone(compare.active())

    def test_a_material_only_the_users_objects_use_comes_back(self):
        """n0001's crate has Wood; now the crate has another material and
        only the user's own box uses Wood, retuned since."""
        self.two_turns()
        wood = bpy.data.materials["Wood"]
        box = bpy.data.objects.new("Box", bpy.data.meshes.new("Box"))
        self.scene.collection.objects.link(box)
        box.data.materials.append(wood)
        bpy.data.objects["Crate"].material_slots[0].material = bpy.data.materials.new("Paint")
        wood.diffuse_color = (0.1, 0.9, 0.1, 1.0)
        comparison = operators.compare_node(bpy.context, "n0001")
        self.assertNotEqual(tuple(bpy.data.materials["Wood"].diffuse_color), (0.1, 0.9, 0.1, 1.0))
        comparison.end(self.scene, keep=False)
        self.assertEqual(tuple(round(v, 4) for v in box.material_slots[0].material.diffuse_color),
                         (0.1, 0.9, 0.1, 1.0), "the live side's Wood is back")
        self.assertEqual([m.name for m in bpy.data.materials if ".00" in m.name], [])

    def test_an_undo_ends_the_comparison(self):
        from whittle import addon

        self.two_turns()
        comparison = operators.compare_node(bpy.context, "n0001")
        addon._after_undo()
        self.assertIsNone(compare.active(), "the undo put back a scene from before it")
        self.assertFalse(comparison.live_blend.exists())

    def test_actions_wait_for_the_comparison(self):
        ctl, _n1, _live = self.two_turns()
        self.assertTrue(bpy.ops.whittle.submit.poll())
        self.assertTrue(operators.can_restore(ctl.history, ctl, "n0000"))
        comparison = operators.compare_node(bpy.context, "n0001")
        self.assertFalse(bpy.ops.whittle.submit.poll())
        self.assertFalse(bpy.ops.whittle.history_restore.poll())
        self.assertFalse(operators.can_restore(ctl.history, ctl, "n0000"))
        self.assertFalse(operators.can_branch(ctl.history, ctl, "n0002"))
        self.assertTrue(bpy.ops.whittle.compare_toggle.poll())
        with self.assertRaises(RuntimeError):
            self.submit(ctl, "Not now.")
        with self.assertRaises(RuntimeError):
            operators.restore_node(bpy.context, "n0000")
        with self.assertRaises(RuntimeError):
            operators.compare_node(bpy.context, "n0000")
        comparison.end(self.scene, keep=False)
        self.assertTrue(bpy.ops.whittle.submit.poll())
        self.assertFalse(operators.can_compare(ctl.history, ctl, "n0002"), "the current node is shown already")


class GhostTest(CompareCase):
    def test_ghost_of_the_parent(self):
        ctl, _n1, live = self.two_turns()
        lid = bpy.data.objects["Crate_Lid"]
        originals = {o.name: (o.as_pointer(), o.data.as_pointer(), o.get("whittle_uid"))
                     for o in (bpy.data.objects["Crate"], lid)}
        baseline = counts()
        self.assertEqual(operators.toggle_ghost(bpy.context), "n0001")
        self.assertEqual(compare.ghost_node(), "n0001")
        ghosts = [o for o in bpy.data.objects if targets.GHOST_PROP in o]
        self.assertEqual([o.name for o in ghosts], ["Ghost · Crate"])
        ghost = ghosts[0]
        self.assertEqual([c.name for c in ghost.users_collection], [compare.GHOST_COLLECTION])
        self.assertEqual((ghost.display_type, ghost.hide_render, ghost.hide_select, ghost.show_in_front),
                         ("WIRE", True, True, True))
        self.assertNotIn("whittle_uid", ghost)
        self.assertTrue(ghost.data.name.startswith(compare.GHOST_PREFIX))
        self.assertFalse(targets.eligible(ghost))
        self.assertEqual(tuple(round(v, 5) for v in ghost.scale), (1.2, 1.2, 1.2))
        self.assertEqual(len(bpy.data.libraries), baseline["libraries"])
        self.assertEqual({o.name: (o.as_pointer(), o.data.as_pointer(), o.get("whittle_uid"))
                          for o in (bpy.data.objects["Crate"], lid)}, originals)
        self.assertEqual(crate_state(), live)

        self.assertIsNone(operators.toggle_ghost(bpy.context))
        self.assertEqual(counts(), baseline)
        self.assertIsNone(compare.ghost_node())

    def test_submit_clears_the_ghost(self):
        ctl, _n1, _live = self.two_turns()
        baseline = counts()
        operators.toggle_ghost(bpy.context)
        self.turn(ctl, "Recolour.")
        self.assertIsNone(compare.ghost_node())
        self.assertNotIn(compare.GHOST_COLLECTION, bpy.data.collections)
        self.assertEqual(counts(), baseline)

    def test_clear_a_saved_ghost(self):
        _ctl, _n1, _live = self.two_turns()
        operators.toggle_ghost(bpy.context)
        blend = self.user_dir / "saved.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
        compare.clear_ghost()
        # A fresh Blender that knows nothing of the ghost but the file.
        script = (f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
                  "import bpy\n"
                  "from whittle.addon import compare\n"
                  "before = sum(1 for o in bpy.data.objects if compare.GHOST_PREFIX in o.name)\n"
                  "removed = compare.clear_ghost()\n"
                  "left = [b.name for a in ('objects', 'meshes', 'materials', 'collections')\n"
                  "        for b in getattr(bpy.data, a) if b.name.startswith(compare.GHOST_PREFIX)\n"
                  "        or b.name == compare.GHOST_COLLECTION]\n"
                  "print('GHOST', before, removed, len(left), len(bpy.data.libraries))\n")
        out = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", str(blend),
                              "--python-expr", script], capture_output=True, text=True, timeout=120)
        line = next((l for l in out.stdout.splitlines() if l.startswith("GHOST ")), None)
        self.assertIsNotNone(line, out.stdout[-2000:] + out.stderr[-2000:])
        self.assertEqual(line.split()[1:], ["1", "1", "0", "0"])
