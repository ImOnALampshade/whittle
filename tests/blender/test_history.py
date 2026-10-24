# SPDX-License-Identifier: GPL-3.0-or-later
"""The history tree as turns build it: one node per turn with its snapshot,
the outcome of interrupted, crashed and refused turns, and the Restore and
Branch buttons, end to end with the fake agent."""

import unittest.mock

import bpy
import numpy as np

from tests.blender.helpers import pump
from tests.blender.history_helpers import STROKE, HistoryTurnCase
from tests.blender.sketch_helpers import add_stroke, look_at_view
from whittle import formats, tree
from whittle.addon import history, operators, render, sketch, targets, turn, views
from whittle.addon.process import AgentState


class NodesTest(HistoryTurnCase):
    def test_first_run_writes_the_root(self):
        ctl = self.controller()
        self.turn(ctl, "Scale it.")
        hist = ctl.history
        root = hist.node("n0000")
        self.assertEqual((root.status, root.label, root.snapshot, root.parent), ("complete", "Start", True, None))
        self.assertTrue(ctl.session.target_blend("n0000").is_file())
        self.assertTrue(ctl.session.thumb_path("n0000").is_file())
        saved, recovered = tree.read_session(ctl.session.session_path())
        self.assertEqual(recovered, [])
        self.assertEqual(set(saved.nodes), {"n0000", "n0001"})

    def test_each_turn_makes_one_node(self):
        ctl = self.controller()
        for i, prompt in enumerate(("Scale it.", "Add a lid.", "Recolour."), start=1):
            node = self.turn(ctl, prompt)
            self.assertEqual(node, formats.node_id(i))
            found = ctl.history.node(node)
            self.assertEqual(found.status, "complete")
            self.assertEqual(found.parent, formats.node_id(i - 1))
            self.assertEqual(found.label, prompt)
            self.assertTrue(found.snapshot)
            self.assertRegex(found.agent_session_id, r"^fake-[0-9a-f]{8}$")
            self.assertRegex(found.agent_message_uuid, r"^fake-msg-[0-9a-f]{8}$")
            self.assertEqual(found.cost_usd, 0.0)
            self.assertEqual(found.num_turns, 2)
            self.assertIsInstance(found.duration_ms, int)
            for path in (ctl.session.target_blend(node), ctl.session.target_blend(node).with_suffix(".json"),
                         ctl.session.thumb_path(node), ctl.session.transcript_path(node)):
                self.assertTrue(path.is_file(), path)
            self.assertEqual(ctl.history.current, node)
            self.assertEqual(self.props.history_node, node)
            steps = [c.args[0] for c in self.undo.call_args_list]
            self.assertEqual(len(steps), 2 * i, "one undo step before and one after each turn")
            self.assertEqual(steps[-2:], [turn.TURN_START_UNDO, f"Whittle: {node} {prompt}"])
        lid = ctl.history.node("n0002")
        self.assertEqual(lid.created_uids, [bpy.data.objects["Crate_Lid"]["whittle_uid"]])
        self.assertEqual(len({ctl.history.node(n).agent_session_id for n in ("n0001", "n0002", "n0003")}), 1,
                         "turns in a row share the live session")

    def test_thumbnails_frame_the_target(self):
        """However far away the user sketched from, the thumbnail is filled
        by the target, seen from the sketch's side."""
        out = self.user_dir / "thumb.png"
        for view in (look_at_view(9, (6.0, -7.0, 5.0), (0, 0, 0.3)), look_at_view(9, (0.9, -1.0, 0.8), (0, 0, 0.3)),
                     look_at_view(9, (0.0, -9.0, 0.3), (0, 0, 0.3), ortho=True, ortho_scale=12.0), None):
            with self.subTest(view=view and view.camera["type"]):
                self.assertEqual(history.thumbnail([self.crate], out, view, self.scene), out)
                pixels = render.load_pixels(out)
                self.assertEqual(pixels.shape[0], pixels.shape[1])
                rows, cols = np.nonzero(np.any(np.abs(pixels[..., :3] - render.BACKGROUND) > 0.02, axis=-1))
                self.assertTrue(rows.size)
                span = max(np.ptp(rows), np.ptp(cols)) + 1
                self.assertGreater(span / pixels.shape[0], 0.75)
                self.assertLess(span / pixels.shape[0], 1.0, "the target is not cut off")
                self.assertTrue(all(0 < v.min() and v.max() < pixels.shape[0] - 1 for v in (rows, cols)),
                                "the target is not cut off")

    def test_parent_follows_the_current_node(self):
        ctl = self.controller()
        self.turn(ctl)
        self.turn(ctl)
        operators.restore_node(bpy.context, "n0001")
        node = self.turn(ctl)
        request = formats.read_bundle(ctl.session.request_dir(node)).request
        self.assertEqual(request.parent, "n0001")
        self.assertEqual(ctl.history.node("n0001").children, ["n0002", node])


class OutcomeTest(HistoryTurnCase):
    def start_interrupted(self, restore):
        ctl = self.controller("history_interrupt.json")
        node = self.submit(ctl, "Lid.")
        pump(ctl, lambda: any(e["name"] == "tool_result" for e in ctl.events), 15, "the first tool result")
        ctl.interrupt(restore=restore)
        self.wait(ctl, node)
        return ctl, node

    def test_interrupt_keep(self):
        ctl, node = self.start_interrupted(restore=False)
        found = ctl.history.node(node)
        self.assertEqual((found.status, found.kept_partial, found.restored), ("interrupted", True, False))
        self.assertEqual(ctl.history.current, node)
        self.assertEqual(len(found.created_uids), 1)

    def test_interrupt_restore(self):
        ctl, node = self.start_interrupted(restore=True)
        found = ctl.history.node(node)
        self.assertEqual((found.status, found.kept_partial, found.restored), ("interrupted", False, True))
        self.assertEqual(found.created_uids, [])
        self.assertEqual(ctl.history.current, node)
        manifest = formats.read_target_manifest(ctl.session.target_blend(node).with_suffix(".json"))
        start = formats.read_target_manifest(ctl.session.checkpoint_paths(node, "start")[1])
        self.assertEqual([o["name"] for o in manifest["objects"]], [o["name"] for o in start["objects"]])
        self.assertEqual(tuple(bpy.data.objects["Crate"].scale), (1.0, 1.0, 1.0))
        after = self.turn(ctl, "Go on.")
        lines = self.context_lines(ctl, after)
        self.assertTrue(any("interrupted" in line and node in line for line in lines), lines)
        self.assertEqual(len(ctl.session_starts), 1, "the live session carries on")

    def test_crash_leaves_a_failed_node(self):
        ctl = self.controller("history_crash.json")
        node = self.submit(ctl, "Scale.")
        pump(ctl, lambda: ctl.process.state == AgentState.CRASHED, 15, "the crash")
        found = ctl.history.node(node)
        self.assertEqual(found.status, "failed")
        self.assertIsNone(found.agent_session_id)
        self.assertTrue(found.snapshot, "the partial edit is snapshotted")
        self.assertEqual(ctl.history.current, node)
        self.assertIsNone(ctl.live_node)

    def test_failed_turn_that_changed_nothing_folds_into_its_parent(self):
        ctl = self.controller("fail_untouched.json")
        node = self.turn(ctl, "Scale it.")
        self.assertTrue(ctl.last_finished["is_error"])
        hist = ctl.history
        found = hist.node(node)
        self.assertEqual((found.status, found.folded, found.snapshot), ("failed", True, False))
        self.assertEqual(hist.current, "n0000", "the parent stays current")
        self.assertEqual(self.props.history_node, "n0000")
        self.assertEqual([n.id for n, _d in hist.tree.walk()], ["n0000"])
        self.assertFalse(ctl.session.thumb_path(node).exists())
        self.assertTrue(ctl.session.transcript_path(node).is_file(), "the transcript is kept")
        self.assertEqual([c.args[0] for c in self.undo.call_args_list], [turn.TURN_START_UNDO],
                         "nothing changed, so no undo step after it")
        self.assertFalse(operators.can_restore(hist, ctl, node))
        self.assertTrue(operators.can_branch(hist, ctl, node), "editing it only brings its prompt back")
        self.assertFalse(operators.can_compare(hist, ctl, node))
        self.assertTrue(any("not kept in the history" in e.text for e in ctl.stream.entries()))

        # A failed turn that did edit the scene is a node of its own.
        edited = self.turn(ctl, "Scale it again.")
        self.assertFalse(hist.node(edited).folded)
        self.assertEqual(hist.node(edited).parent, "n0000")
        self.assertEqual(hist.current, edited)
        self.assertEqual(hist.node("n0000").children, [node, edited])
        self.assertEqual([n.id for n, _d in hist.tree.walk()], ["n0000", edited])

        reloaded = history.get(ctl.session.root, reload=True)
        self.assertTrue(reloaded.node(node).folded)
        self.assertEqual(reloaded.current, edited)

    def test_running_node_reloads_as_failed(self):
        ctl = self.controller()
        self.turn(ctl)
        hist = ctl.history
        hist.tree.add("n0002", "n0001", prompt="Never finished.")
        hist.tree.current = "n0002"
        hist.save()
        reloaded = history.get(ctl.session.root, reload=True)
        self.assertEqual(reloaded.node("n0002").status, "failed")
        self.assertFalse(reloaded.can_restore("n0002"))
        self.assertFalse(operators.can_restore(reloaded, None, "n0002"))
        self.assertTrue(operators.can_restore(reloaded, None, "n0001"))
        saved, recovered = tree.read_session(ctl.session.session_path())
        self.assertEqual((saved.node("n0002").status, recovered), ("failed", []), "the recovery was saved")

    def test_refused_submit_is_discarded(self):
        ctl = self.controller("refuse.json")
        node = self.submit(ctl, "No.")
        pump(ctl, lambda: ctl.errors, 15, "the refusal")
        self.assertNotIn(node, ctl.history.tree.nodes)
        self.assertEqual(ctl.history.current, "n0000")
        self.assertEqual(ctl.history.node("n0000").children, [])
        self.assertFalse(ctl.running)
        self.assertFalse(ctl.session.node_dir(node).exists(), "the refused node's folder goes")
        self.assertEqual(sketch.pending_count(self.obj), 1, "its strokes are pending again")
        self.assertEqual(formats.node_id(ctl._next_node), node, "its number is free again")

    def test_a_submit_that_fails_before_sending_leaves_nothing_running(self):
        ctl = self.controller()
        self.props.prompt = "Lid."
        ctl.hold_prompt(self.scene, "Lid.")
        self.props.prompt = ""
        with unittest.mock.patch.object(ctl.history, "begin", side_effect=tree.TreeError("broken")):
            node = self.submit(ctl, "Lid.")
            pump(ctl, lambda: ctl.errors, 15, "the failure")
        self.assertIn("broken", ctl.errors[0])
        self.assertFalse(ctl.busy)
        self.assertIsNone(ctl.turn_id)
        self.assertFalse(ctl.session.node_dir(node).exists())
        self.assertEqual(sketch.pending_count(self.obj), 1)
        self.assertEqual(self.props.prompt, "Lid.", "the prompt came back")
        ctl.errors.clear()
        self.assertEqual(self.turn(ctl, "Lid."), node, "the next run takes the number")

    def test_a_crash_while_resuming_does_not_wedge_the_next_run(self):
        ctl = self.controller()
        self.start_ready(ctl)
        ctl._pending_run = (ctl.session.root, "x", None, False)
        ctl._session_starting = True
        ctl._on_session_started(False, {"code": "agent_crashed", "message": "gone"}, {"resume": "s1"})
        self.assertIsNone(ctl._resume_failed, "a crash says nothing about resuming")
        self.assertIsNone(ctl._pending_run)
        ctl._session_starting = True
        ctl._on_state(AgentState.CRASHED, "gone")
        self.assertFalse(ctl._session_starting, "the next agent starts its own session")
        ctl.errors.clear()

    def test_run_bundle_waits_for_a_pending_run(self):
        ctl = self.controller()
        ctl._pending_run = (ctl.session.root, "x", "n0001", True)
        self.addCleanup(setattr, ctl, "_pending_run", None)
        with self.assertRaisesRegex(RuntimeError, "already waiting"):
            ctl.run_bundle(ctl.session.root)


class ButtonsTest(HistoryTurnCase):
    def test_restore_sets_the_targets(self):
        ctl = self.controller()
        self.turn(ctl)
        self.turn(ctl)
        self.assertIn("Crate_Lid", [t.object.name for t in self.props.targets])
        self.undo.reset_mock()
        operators.restore_node(bpy.context, "n0001")
        self.assertNotIn("Crate_Lid", bpy.data.objects)
        self.assertEqual([t.object.name for t in self.props.targets], ["Crate"])
        self.assertEqual(self.undo.call_count, 1)
        self.assertEqual(ctl.history.current, "n0001")
        self.assertEqual(self.props.history_node, "n0001")

    def test_branch_makes_a_sibling(self):
        ctl = self.controller()
        self.turn(ctl, "Scale it.")
        self.turn(ctl, "Add a lid.")
        self.assertEqual(operators.branch_node(bpy.context, "n0002"), "n0001")
        self.assertEqual(self.props.prompt, "Add a lid.")
        self.assertEqual(ctl.history.current, "n0001")
        self.assertNotIn("Crate_Lid", bpy.data.objects)
        node = self.turn(ctl, self.props.prompt)
        self.assertEqual(node, "n0003")
        self.assertEqual(ctl.history.node(node).parent, "n0001")
        self.assertEqual(ctl.history.node("n0001").children, ["n0002", "n0003"])
        with self.assertRaises(RuntimeError):
            operators.branch_node(bpy.context, "n0000")
        self.assertFalse(operators.can_branch(ctl.history, ctl, "n0000"))

    def resubmit(self, ctl):
        """Submit as the user would after Branch: without drawing anything."""
        node = ctl.run_sketch(self.props.prompt, targets=targets.resolve(self.scene), scene=self.scene)
        self.wait(ctl, node)
        return node, formats.read_bundle(ctl.session.request_dir(node))

    def test_branch_brings_back_the_sketch(self):
        ctl = self.controller()
        n1 = self.turn(ctl, "Move it.")
        self.assertEqual(sketch.pending_count(self.obj), 0, "a finished turn clears its strokes")
        # Drawn after the turn: it stays, beside the strokes brought back.
        add_stroke(self.obj, "region", STROKE, view=1, cyclic=True)
        operators.branch_node(bpy.context, n1)
        self.assertEqual(sketch.pending_count(self.obj), 2)
        self.assertEqual(sketch.used_views(self.obj), {1})
        node, sent = self.resubmit(ctl)
        self.assertEqual(ctl.history.node(node).parent, "n0000")
        self.assertEqual(sorted(s.type for s in sent.strokes), ["free", "region"])
        first = formats.read_bundle(ctl.session.request_dir(n1))
        replayed = next(s for s in sent.strokes if s.type == "free")
        for a, b in zip(first.strokes[0].points, replayed.points):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=4)
        self.assertEqual(sent.request.views, [1])

    def test_branch_of_a_failed_turn_does_not_double_its_strokes(self):
        ctl = self.controller("history_crash.json")
        node = self.submit(ctl, "Scale.")
        pump(ctl, lambda: ctl.process.state == AgentState.CRASHED, 15, "the crash")
        self.assertEqual(sum(sketch.stroke_counts(self.obj).values()), 1, "a failed turn keeps its strokes")
        self.undo.reset_mock()
        operators.branch_node(bpy.context, node)
        self.assertEqual(sketch.stroke_counts(self.obj), {0: 1}, "one copy, pending again")
        self.assertEqual(self.undo.call_count, 1, "one undo step, after the replay")
        self.assertIn("edit & resend", self.undo.call_args.args[0])

    def test_branch_gives_a_clashing_view_a_new_id(self):
        ctl = self.controller()
        n1 = self.turn(ctl, "Move it.")
        # A sketch object made afresh numbers its views from 1 again.
        bpy.data.objects.remove(self.obj)
        self.obj = sketch.ensure_sketch_layers(self.scene)
        views.add_view(self.obj.data, lambda i: look_at_view(i, (0, -3, 0.5), (0, 0, 0.3)))
        operators.branch_node(bpy.context, n1)
        self.assertEqual(sketch.used_views(self.obj), {2})
        stored = {v.id: v for v in views.load_views(self.obj.data)}
        sent = formats.read_bundle(ctl.session.request_dir(n1)).views[1]
        self.assertEqual(stored[2].view_matrix, sent.view_matrix)
        self.assertNotEqual(stored[1].view_matrix, sent.view_matrix)

    def test_empty_submit_is_refused(self):
        ctl = self.controller()
        with self.assertRaises(ValueError):
            ctl.run_sketch("  ", targets=targets.resolve(self.scene), scene=self.scene)
        self.assertFalse((ctl.session.root / "nodes").exists(), "nothing is written")
        self.assertFalse(ctl.busy)

    def test_buttons_wait_for_the_turn(self):
        ctl = self.controller("history_interrupt.json")
        node = self.submit(ctl, "Lid.")
        self.assertFalse(operators.can_restore(ctl.history, ctl, "n0000"))
        with self.assertRaises(RuntimeError):
            operators.restore_node(bpy.context, "n0000")
        ctl.interrupt(restore=False)
        self.wait(ctl, node)
        self.assertTrue(operators.can_restore(ctl.history, ctl, "n0000"))
        self.assertIs(turn.current(), ctl)
