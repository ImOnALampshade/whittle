# SPDX-License-Identifier: GPL-3.0-or-later
"""The chat-style sidebar's behaviour: Auto targets following the
selection, the branch switcher, edit and resend, Retry, Send handing the
prompt back, and the conversation built from the history."""

import json
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import FAKE_SCRIPTS
from tests.blender.history_helpers import HistoryTurnCase
from tests.blender.sketch_helpers import add_stroke
from tests.blender.test_sidebar import AddonTestCase
from whittle import formats
from whittle.addon import autotarget, compare, conversation, history, operators, sketch, stream, targets, turn
from whittle.protocol import Event


def selected(scene=None):
    return sorted(o.name for o in bpy.context.view_layer.objects.selected)


class AutoTargetTest(AddonTestCase):
    def setUp(self):
        super().setUp()
        self.lid = bpy.data.objects.new("Crate_Lid", bpy.data.meshes.new("Crate_Lid"))
        self.scene.collection.objects.link(self.lid)
        self.addCleanup(bpy.data.objects.remove, self.lid)
        self.camera = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        self.scene.collection.objects.link(self.camera)
        self.addCleanup(bpy.data.objects.remove, self.camera)
        self.layer = bpy.context.view_layer
        self.select()
        self.props.target_auto = True

    def select(self, *objects, active=None):
        for obj in self.layer.objects:
            obj.select_set(obj in objects)
        self.layer.objects.active = active

    def picked(self):
        return [t.object.name for t in self.props.targets]

    def sync(self):
        return autotarget.sync(self.scene, self.layer)

    def test_follows_the_selection_active_first(self):
        self.select(self.crate, self.lid, self.camera, active=self.lid)
        self.assertTrue(self.sync())
        self.assertEqual(self.picked(), ["Crate_Lid", "Crate"], "the active object first, never a camera")
        self.assertFalse(self.sync(), "an unchanged selection writes nothing")

    def test_nothing_selected_keeps_the_active_object(self):
        self.select(active=self.crate)
        self.sync()
        self.assertEqual(self.picked(), ["Crate"])
        self.select()
        self.sync()
        self.assertEqual(self.picked(), [], "nothing at all: new objects")

    def test_holds_still_while_sketching_comparing_or_running(self):
        self.select(self.crate, active=self.crate)
        self.sync()
        self.select(self.lid, active=self.lid)
        with mock.patch.object(sketch, "current_session", return_value=object()):
            self.assertFalse(self.sync())
        with mock.patch.object(compare, "active", return_value=object()):
            self.assertFalse(self.sync())
        turn.set_current(SimpleNamespace(busy=True, running=True))
        self.addCleanup(turn.set_current, None)
        self.assertFalse(self.sync())
        self.assertEqual(self.picked(), ["Crate"])
        turn.set_current(None)
        self.assertTrue(self.sync())
        self.assertEqual(self.picked(), ["Crate_Lid"])

    def test_not_outside_object_mode(self):
        self.select(self.crate, active=self.crate)
        self.sync()
        bpy.ops.object.mode_set(mode="EDIT")
        self.addCleanup(bpy.ops.object.mode_set, mode="OBJECT")
        self.lid.select_set(True)
        self.assertFalse(self.sync())
        self.assertEqual(self.picked(), ["Crate"])

    def test_manual_mode_keeps_the_list_and_turning_auto_on_syncs(self):
        self.props.target_auto = False
        self.props.targets.add().object = self.crate
        self.select(self.lid, active=self.lid)
        self.assertFalse(self.sync())
        self.assertEqual(self.picked(), ["Crate"])
        self.props.target_auto = True
        self.assertEqual(self.picked(), ["Crate_Lid"], "turning Auto on takes the selection at once")

    def test_a_depsgraph_update_syncs(self):
        self.select(self.crate, active=self.crate)
        self.layer.update()
        self.assertEqual(self.picked(), ["Crate"])
        self.lid.select_set(True)
        self.layer.update()
        self.assertEqual(sorted(self.picked()), ["Crate", "Crate_Lid"])

    def test_whittle_setting_the_list_selects_it(self):
        self.select(self.lid, active=self.lid)
        self.props.targets.clear()
        self.props.targets.add().object = self.crate
        targets.select_list(self.scene, self.layer)
        self.assertEqual(selected(), ["Crate"])
        self.assertEqual(self.layer.objects.active, self.crate)
        self.assertFalse(self.sync(), "the next sync agrees with the list")
        self.props.targets.clear()
        targets.select_list(self.scene, self.layer)
        self.assertEqual(selected(), [])
        self.assertIsNone(self.layer.objects.active)
        self.props.target_auto = False
        self.lid.select_set(True)
        self.props.targets.add().object = self.crate
        targets.select_list(self.scene, self.layer)
        self.assertEqual(selected(), ["Crate_Lid"], "with Auto off the selection is left alone")


class ChatTurnCase(HistoryTurnCase):
    script = "history.json"

    def setUp(self):
        super().setUp()
        self.ctl = self.controller(self.script)
        self.fake = str(FAKE_SCRIPTS / self.script)

    def send(self, prompt):
        """Types the prompt, draws a stroke and presses Send."""
        add_stroke(self.obj, "free", [(-0.15 + 0.05 * i, -0.25, 0.3) for i in range(7)], view=1, radius=0.01)
        self.props.prompt = prompt
        ctl, node = operators.submit_sketch(bpy.context, self.fake)
        self.assertIs(ctl, self.ctl)
        return node


class BranchTest(ChatTurnCase):
    def branches(self):
        """n0001 -> (n0002, n0003): two takes on the second turn."""
        first = self.send("Scale it.")
        self.wait(self.ctl, first)
        second = self.send("Add a lid.")
        self.wait(self.ctl, second)
        operators.branch_node(bpy.context, second)
        third = self.send("Recolour it instead.")
        self.wait(self.ctl, third)
        return first, second, third

    def test_edit_and_resend_makes_a_sibling(self):
        first = self.send("Scale it.")
        self.wait(self.ctl, first)
        second = self.send("Add a lid.")
        self.assertEqual(self.props.prompt, "", "Send empties the prompt box")
        self.wait(self.ctl, second)
        self.assertEqual(bpy.ops.whittle.history_branch(node=second), {"FINISHED"})
        self.assertEqual(self.ctl.history.current, first)
        self.assertEqual(self.props.prompt, "Add a lid.", "the edited turn's prompt is back")
        self.assertTrue(sketch.pending_count(self.obj), "and its strokes")
        conv = conversation.build(self.ctl.history, self.ctl)
        self.assertEqual(conv.later, [second])
        third = self.send("Add a lid with hinges.")
        self.wait(self.ctl, third)
        tree = self.ctl.history.tree
        self.assertEqual(tree.node(third).parent, first)
        self.assertEqual(tree.siblings(third), [second, third])

    def test_switching_branches(self):
        first, second, third = self.branches()
        self.undo.reset_mock()
        self.props.target_auto = True
        self.assertEqual(bpy.ops.whittle.branch_switch(node=second), {"FINISHED"})
        self.assertEqual(self.ctl.history.current, second)
        self.assertEqual(self.props.history_node, second)
        self.undo.assert_called_once_with(f"{history.UNDO_PREFIX}: switch to {second}")
        self.assertEqual(selected(), sorted(t.object.name for t in self.props.targets),
                         "with Auto on the restored targets are selected")
        self.assertIn("Crate_Lid", selected())
        # Switching to the first turn's branch lands on its newest leaf.
        self.assertEqual(operators.switch_branch(bpy.context, first), third)
        self.assertEqual(self.ctl.history.current, third)
        self.assertNotIn("Crate_Lid", [o.name for o in self.scene.objects])

    def test_switching_waits_for_the_turn(self):
        _first, second, third = self.branches()
        hist = self.ctl.history
        self.assertTrue(operators.can_switch(hist, self.ctl, second))
        node = self.send("Darker.")
        self.assertFalse(operators.can_switch(hist, self.ctl, second))
        with self.assertRaises(RuntimeError):
            operators.switch_branch(bpy.context, second)
        self.wait(self.ctl, node)
        self.assertIsNone(operators.switch_target(hist, "n9999"))


class RetryTest(ChatTurnCase):
    script = "fail_untouched.json"

    def test_retry_a_folded_then_a_recorded_failure(self):
        hist = self.ctl.history
        node = self.send("Add a lid.")
        self.wait(self.ctl, node)
        self.assertTrue(hist.tree.node(node).folded)
        self.assertEqual(self.ctl.last_folded, node)
        self.assertEqual(self.props.prompt, "", "the folded turn shows its prompt; Retry brings it back")
        conv = conversation.build(hist, self.ctl)
        self.assertEqual([(t.node, t.folded) for t in conv.turns], [(node, True)])
        self.assertTrue(operators.can_retry(hist, self.ctl, node))

        # The second scripted turn edits the crate, then fails: a node.
        self.props.prompt = ""
        ctl, again = operators.retry(bpy.context, node, self.fake)
        self.assertNotEqual(again, node)
        self.assertIsNone(self.ctl.last_folded, "a new run clears the folded turn")
        self.wait(self.ctl, again)
        self.assertEqual(hist.tree.node(again).parent, hist.tree.node(node).parent)
        found = hist.tree.node(again)
        self.assertEqual((found.status, found.folded), ("failed", False))
        self.assertEqual(hist.current, again)
        self.assertEqual(self.props.prompt, "", "a turn that changed the scene keeps it out")

        # Retrying it goes back to its parent and sends its request again.
        ctl, third = operators.retry(bpy.context, again, self.fake)
        self.wait(self.ctl, third)
        self.assertEqual(hist.tree.node(third).parent, found.parent)
        self.assertEqual(hist.tree.node(third).status, "complete")
        self.assertEqual(hist.tree.siblings(third), [again, third])
        with self.assertRaises(RuntimeError):
            operators.retry(bpy.context, third, self.fake)


class PromptHandBackTest(ChatTurnCase):
    def test_a_run_that_never_starts_gives_the_prompt_back(self):
        self.props.prompt = ""
        self.ctl.hold_prompt(self.scene, "Add a lid.")
        self.ctl._pending_run = (self.ctl.session.request_dir("n0042"), "Add a lid.", None, False)
        self.ctl._drop_pending_run()
        self.assertEqual(self.props.prompt, "Add a lid.")
        self.props.prompt = "and hinges"
        self.ctl.hold_prompt(self.scene, "Add a lid.")
        self.ctl._pending_run = (self.ctl.session.request_dir("n0042"), "Add a lid.", None, False)
        self.ctl._drop_pending_run()
        self.assertEqual(self.props.prompt, "Add a lid. and hinges", "typed text is kept after it")


class KeyProblemTest(unittest.TestCase):
    def test_classifies_refused_keys(self):
        for text in ("Invalid API key · Fix external API key",
                     "API Error: 401 {\"type\":\"authentication_error\"}",
                     "Not logged in · Please run /login"):
            with self.subTest(text=text):
                self.assertEqual(turn.key_problem(text), "The API key was refused")
        self.assertIsNone(turn.key_problem("error_max_turns"))
        self.assertIsNone(turn.key_problem(""))


class ConversationModelTest(unittest.TestCase):
    def test_transcript_records_replay_as_entries(self):
        records = [
            {"type": "local", "name": "submit", "data": {"node": "n0001", "prompt": "Add a lid."}},
            {"type": "event", "name": Event.TEXT, "data": {"turn_id": "n0001", "text": "Adding a lid."}},
            {"type": "event", "name": Event.TOOL_USE,
             "data": {"turn_id": "n0001", "tool_use_id": "a", "tool": "exec", "input": {"label": "lid"}}},
            {"type": "event", "name": Event.TOOL_RESULT,
             "data": {"turn_id": "n0001", "tool_use_id": "a", "is_error": True, "summary": "boom"}},
            {"type": "local", "name": "amend", "data": {"amend": 1, "text": "taller", "strokes": 2}},
            {"type": "event", "name": Event.AMEND_DELIVERED, "data": {"turn_id": "n0001", "amend": 1,
                                                                      "via": "tool_result"}},
            {"type": "local", "name": "answer", "data": {"question": "Bevel?", "answer": "yes"}},
            {"type": "local", "name": "target_edited", "data": {"edits": [{"name": "Crate", "kind": "transform"}]}},
            {"type": "local", "name": "interrupt", "data": {"mode": "keep"}},
            {"type": "event", "name": Event.TURN_FINISHED,
             "data": {"turn_id": "n0001", "is_error": True, "interrupted": False, "num_turns": 4,
                      "cost_usd": 0.01, "subtype": "error_max_turns", "errors": []}},
        ]
        entries = stream.entries_from_records(records, "n0001")
        self.assertEqual([e.kind for e in entries],
                         ["text", "tool", "amend", "note", "answer", "stopping", "turn"],
                         "a target_edited record from an older session is not shown")
        self.assertEqual(entries[2].text, "taller (+ 2 new strokes)")
        self.assertEqual(entries[4].text, "yes")
        end = entries[-1]
        self.assertEqual((end.status, end.result, end.steps, end.cost), ("failed", "Claude ran out of steps",
                                                                         4, 0.01))
        self.assertTrue(all(e.turn_id == "n0001" for e in entries))

    def test_failure_reasons(self):
        self.assertEqual(stream.failure_reason({"errors": ["the agent exited with code 3\ntrace"]}),
                         "the agent exited with code 3")
        self.assertEqual(stream.failure_reason({"subtype": "session_ended"}), "the session ended")
        self.assertEqual(stream.failure_reason({"subtype": "error_odd_thing"}), "error odd thing")
        long = stream.failure_reason({"errors": ["x" * 500]})
        self.assertEqual(len(long), stream.REASON_CHARS)

    def test_request_summary(self):
        self.assertEqual(conversation.Request(strokes=3, views=2, refs=1).summary(), "3 strokes · 2 views · 1 ref")
        self.assertEqual(conversation.Request().summary(), "")

    def test_reads_request_and_transcript_once(self):
        session = formats.SessionDir(tempfile.mkdtemp(prefix="whittle-conv-"))
        self.addCleanup(shutil.rmtree, session.root, True)
        request = session.request_dir("n0001")
        request.mkdir(parents=True)
        (request / "request.json").write_text(json.dumps({"views": [1, 2], "refs": ["refs/a.png"]}))
        (request / "strokes.json").write_text(json.dumps({"strokes": [{}, {}, {}]}))
        info = conversation.request_info(session, "n0001")
        self.assertEqual((info.strokes, info.views, info.refs), (3, 2, 1))
        session.transcript_path("n0001").write_text(json.dumps(
            {"type": "event", "name": "text", "data": {"text": "hello"}}) + "\nnot json\n")
        first = conversation.transcript_entries(session, "n0001")
        self.assertEqual([e.text for e in first], ["hello"])
        self.assertIs(conversation.transcript_entries(session, "n0001"), first, "cached")
        conversation.clear_cache()


if __name__ == "__main__":
    unittest.main()
