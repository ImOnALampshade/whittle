# SPDX-License-Identifier: GPL-3.0-or-later
"""Watching and steering a turn: the stream, interrupt (keep or restore),
amend, ask and undo, end to end with the fake agent."""

import json
import os
import time
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import FAKE_SCRIPTS, AgentTestCase, agent_python, pump
from tests.blender.sketch_helpers import add_stroke, look_at_view
from tests.blender.ui_helpers import RecordingLayout
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import operators, prefs, sketch, turn, ui, views

A_POINTS = [(-0.15 + 0.05 * i, -0.25, 0.3) for i in range(7)]
B_POINTS = [(0.2, 0.0, 0.7), (0.0, 0.2, 0.7), (-0.2, 0.0, 0.7), (0.0, -0.2, 0.7)]
NEW_POINTS = [(0.1, -0.25, 0.15), (0.2, -0.25, 0.15), (0.2, -0.25, 0.25)]
LATER_POINTS = [(-0.2, -0.25, 0.4), (-0.1, -0.25, 0.4)]


class SteeringTestCase(AgentTestCase):
    def setUp(self):
        super().setUp()
        self.crate = build_scene()
        old = sketch.find_sketch_object()
        if old is not None:
            bpy.data.objects.remove(old)
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.scene = bpy.context.scene
        self.props = self.scene.whittle
        # Scene properties outlive the add-on's registration.
        self.props.target_auto = False
        self.props.targets.clear()
        self.props.target_collection = None
        self.props.prompt = ""
        self.props.amend_text = ""
        self.obj = sketch.ensure_sketch_layers(self.scene)
        gp = self.obj.data
        views.add_view(gp, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))
        views.add_view(gp, lambda i: look_at_view(i, (0, -2, 0.3), (0, 0, 0.3)))
        add_stroke(self.obj, "carve", A_POINTS, view=2, radius=0.01)
        add_stroke(self.obj, "add", B_POINTS, view=1, cyclic=True, radius=0.01)

    def start(self, script, prompt="Add a lid.", *, attended=False):
        ctl = self.make_controller(script)
        if attended:
            ctl.commands.attended = lambda: True
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        ctl.run_sketch(prompt, targets=[self.crate], scene=self.scene)
        pump(ctl, lambda: ctl._started or ctl.errors, 15, "the turn to start")
        self.assertEqual(ctl.errors, [])
        return ctl

    def finish(self, ctl, timeout=30):
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, timeout, "the turn to finish")
        self.assertEqual(ctl.errors, [])
        return ctl.last_finished

    def finish_next(self, ctl, node, timeout=30):
        pump(ctl, lambda: (ctl.last_finished or {}).get("turn_id") == node or ctl.errors,
             timeout, f"turn {node} to finish")
        self.assertEqual(ctl.errors, [])
        return ctl.last_finished

    def events(self, ctl, name):
        return [e["data"] for e in ctl.events if e["name"] == name]

    def stamps(self):
        return [(s.layer, s.turn, s.amend) for s in sketch.iter_strokes(self.obj, include_hidden=True)]

    def local_records(self, ctl, node="n0001"):
        lines = ctl.session.transcript_path(node).read_text().splitlines()
        return [r for r in map(json.loads, lines) if r["type"] == "local"]


class StreamTest(SteeringTestCase):
    def test_submit_streams_and_finishes(self):
        from whittle.addon import operators

        self.props.targets.add().object = self.crate
        self.props.prompt = "Add a lid."
        # A value the developer exported comes back afterwards.
        env = mock.patch.dict(os.environ, {"WHITTLE_AGENT_PYTHON": str(agent_python())})
        env.start()
        self.addCleanup(env.stop)
        ctl, node = operators.submit_sketch(bpy.context, str(FAKE_SCRIPTS / "stream.json"))
        self.controllers.append(ctl)
        self.assertEqual(self.props.prompt, "", "Send takes the prompt out of the prompt box")
        finished = self.finish(ctl)
        self.assertFalse(finished["is_error"], finished)
        self.assertEqual(self.props.prompt, "", "a turn that ran does not give it back")

        shown = [(e.kind, e.tool, e.status, len(e.images)) for e in ctl.stream.entries()
                 if e.kind not in ("note", "submit")]
        self.assertEqual(shown, [("text", None, "", 0), ("tool", "exec", "ok", 0),
                                 ("tool", "render", "ok", 2), ("tool", "render", "ok", 1),
                                 ("text", None, "", 0), ("turn", None, "done", 0)])
        exec_entry = next(e for e in ctl.stream.entries() if e.tool == "exec")
        self.assertIn("Crate_Lid", exec_entry.input["code"])
        self.assertEqual(exec_entry.text, "exec · add lid")
        self.assertIn("stdout", exec_entry.result)
        self.assertEqual(len(ctl.stream.images()), 3)
        for path in ctl.stream.images():
            self.assertTrue(os.path.isfile(path), path)

        last = json.loads(ctl.session.transcript_path(node).read_text().splitlines()[-1])
        self.assertEqual(last["name"], "turn_finished")
        self.assertIn("Crate_Lid", [t.object.name for t in self.props.targets],
                      "objects the agent made become targets")
        self.assertEqual(ctl.status["phase"], "idle")

        text = operators.open_transcript(bpy.context)
        self.assertEqual(text.name, "Whittle Transcript")
        body = text.as_string()
        for part in ("Turn n0001", "Prompt: Add a lid.", "lid.location = (0, 0, 0.52)",
                     "Turn done", "Plan: add a lid"):
            self.assertIn(part, body)


    def test_a_prompt_only_turn_runs_clean(self):
        """No strokes and no views: a valid request, and the demo script does
        not look for a sketch view that is not there."""
        bpy.data.objects.remove(self.obj)
        ctl = self.start("stream.json", "Add a lid.")
        finished = self.finish(ctl)
        self.assertFalse(finished["is_error"], finished)
        self.assertEqual(finished["errors"], [])
        self.assertEqual(self.events(ctl, "error"), [])
        self.assertFalse(any(r["is_error"] for r in self.events(ctl, "tool_result")))
        request = formats.read_bundle(ctl.session.request_dir("n0001"))
        self.assertEqual((request.strokes, request.views), ([], {}))


class InterruptTest(SteeringTestCase):
    def run_until_first_result(self, restore):
        ctl = self.start("steer_interrupt.json")
        pump(ctl, lambda: self.events(ctl, "tool_result"), 15, "the first tool result")
        started = time.monotonic()
        ctl.interrupt(restore=restore)
        self.assertEqual(ctl.status["phase"], "interrupting")
        finished = self.finish(ctl)
        self.assertLess(time.monotonic() - started, 10)
        self.assertTrue(finished["interrupted"])
        self.assertNotIn("should not be said", [d["text"] for d in self.events(ctl, "text")])
        return ctl, finished

    def test_interrupt_keep_partial(self):
        ctl, finished = self.run_until_first_result(restore=False)
        self.assertIn("Crate_Lid", bpy.data.objects)
        self.assertEqual(tuple(self.crate.scale), (1.5, 1.5, 1.5))
        self.assertEqual([t for _l, t, _a in self.stamps()], [1, 1], "an interrupted turn keeps its strokes")
        self.assertIn({"mode": "keep"}, [r["data"] for r in self.local_records(ctl)])
        self.assertIn("Crate_Lid", [t.object.name for t in self.props.targets])
        self.assertNotIn("restored", finished)

    def test_interrupt_restore_turn_start(self):
        libraries = list(bpy.data.libraries)
        ctl = self.start("steer_interrupt.json")
        pump(ctl, lambda: self.events(ctl, "tool_result"), 15, "the first tool result")
        mesh = bpy.data.meshes.new("UserBox")
        user_box = bpy.data.objects.new("UserBox", mesh)
        self.scene.collection.objects.link(user_box)
        ctl.interrupt(restore=True)
        finished = self.finish(ctl)
        self.assertTrue(finished["interrupted"])
        self.assertEqual(finished["restored"], ["Crate"])
        self.assertNotIn("Crate_Lid", bpy.data.objects)
        self.assertNotIn("Crate_Lid", bpy.data.meshes)
        crate = bpy.data.objects["Crate"]
        self.assertEqual(tuple(crate.scale), (1.0, 1.0, 1.0))
        self.assertEqual(len(crate.data.vertices), 8)
        self.assertEqual([s.material.name for s in crate.material_slots], ["Wood"])
        self.assertIn("UserBox", bpy.data.objects, "what the user added is left alone")
        for attr in ("objects", "meshes", "materials"):
            self.assertFalse([b.name for b in getattr(bpy.data, attr) if ".00" in b.name], attr)
        self.assertEqual(list(bpy.data.libraries), libraries)
        blend, manifest = ctl.session.checkpoint_paths("n0001", "start")
        self.assertTrue(blend.is_file() and manifest.is_file())
        records = self.local_records(ctl)
        self.assertIn(("interrupt", {"mode": "restore"}), [(r["name"], r["data"]) for r in records])
        self.assertIn(("restored", {"objects": ["Crate"]}), [(r["name"], r["data"]) for r in records])
        self.assertEqual([t for _l, t, _a in self.stamps()], [1, 1])
        self.assertNotIn("Crate_Lid", [t.object.name for t in self.props.targets if t.object])

    def start_with_user_lamp(self):
        lamp = bpy.data.objects.new("UserLamp", bpy.data.meshes.new("UserLamp"))
        self.scene.collection.objects.link(lamp)
        ctl = self.start("steer_rename.json")
        pump(ctl, lambda: self.events(ctl, "tool_result"), 15, "the first tool result")
        self.assertIn("Lamp_Post", ctl.commands.added, "a rename reads as added in the diff")
        return ctl

    def test_restore_keeps_an_object_the_agent_renamed(self):
        ctl = self.start_with_user_lamp()
        ctl.interrupt(restore=True)
        finished = self.finish(ctl)
        self.assertEqual(finished["restored"], ["Crate"])
        self.assertIn("Lamp_Post", bpy.data.objects, "the user's object is not the agent's to delete")
        self.assertNotIn("Crate_Lid", bpy.data.objects)

    def test_keep_does_not_adopt_an_object_the_agent_renamed(self):
        ctl = self.start_with_user_lamp()
        ctl.interrupt(restore=False)
        self.finish(ctl)
        adopted = [t.object.name for t in self.props.targets if t.object]
        self.assertIn("Crate_Lid", adopted)
        self.assertNotIn("Lamp_Post", adopted)


class AmendTest(SteeringTestCase):
    def test_amend_with_new_strokes(self):
        ctl = self.start("amend.json")
        add_stroke(self.obj, "free", NEW_POINTS, view=1, radius=0.01)
        number = ctl.amend("Make it taller", scene=self.scene)
        self.assertEqual(number, 1)
        written = formats.read_bundle(ctl.session.amend_dir("n0001", 1))
        self.assertEqual(written.request.amend, 1)
        self.assertEqual(written.request.prompt, "Make it taller")
        self.assertEqual([s.type for s in written.strokes], ["free"])
        self.assertEqual(written.request.views, [1])
        self.assertIn(("free", 1, 1), self.stamps())
        add_stroke(self.obj, "free", LATER_POINTS, view=1)
        finished = self.finish(ctl)
        self.assertFalse(finished["is_error"], finished)
        self.assertEqual(finished["amends_undelivered"], [])
        result = self.events(ctl, "tool_result")[0]
        self.assertIn("User amendment 1: Make it taller", result["summary"])
        self.assertIn("amend 1: 1 strokes, views [1]", [d["text"] for d in self.events(ctl, "text")])
        self.assertTrue(ctl.amends[1]["delivered"])
        self.assertEqual(self.stamps(), [("free", 0, 0)], "the turn's strokes go, later ones stay")
        self.assertIn("amend", [r["name"] for r in self.local_records(ctl)])

    def test_amend_after_the_last_step_is_a_follow_up(self):
        ctl = self.start("amend_follow_up.json")
        ctl.amend("Also a handle", scene=self.scene)
        finished = self.finish(ctl)
        self.assertFalse(ctl.session.amend_dir("n0001", 1).exists(), "a text-only amendment has no bundle")
        self.assertEqual([(d["amend"], d["via"]) for d in self.events(ctl, "amend_delivered")], [(1, "query")])
        self.assertIn("Folded in.", [d["text"] for d in self.events(ctl, "text")])
        self.assertFalse(finished["is_error"] or finished["interrupted"])
        self.assertEqual(self.stamps(), [], "the turn completed")

    def test_undelivered_amend_is_handed_back(self):
        ctl = self.start("amend_interrupt.json")
        add_stroke(self.obj, "free", NEW_POINTS, view=1)
        ctl.amend("Make it taller", scene=self.scene)
        self.assertTrue(ctl.session.amend_dir("n0001", 1).is_dir())
        pump(ctl, lambda: not ctl.bridge.pending, 10, "the amend to be queued")
        ctl.interrupt()
        finished = self.finish(ctl)
        self.assertEqual(finished["amends_undelivered"], [1])
        self.assertIn(("free", 0, 0), self.stamps())
        self.assertEqual(sorted(t for _l, t, _a in self.stamps()), [0, 1, 1])
        self.assertFalse(ctl.session.amend_dir("n0001", 1).exists())
        self.assertEqual(self.props.prompt, "Make it taller")
        notes = [e.text for e in ctl.stream.entries() if e.kind == "warning"]
        self.assertTrue(any("did not reach the agent" in n for n in notes), notes)

    def test_amend_needs_text_or_strokes(self):
        ctl = self.start("amend_follow_up.json")
        with self.assertRaises(ValueError):
            ctl.amend("  ", scene=self.scene)
        ctl.amend("ok", scene=self.scene)
        self.finish(ctl)
        with self.assertRaises(RuntimeError):
            ctl.amend("too late", scene=self.scene)


class AmendWhileStartingTest(SteeringTestCase):
    def begin(self, script):
        """Submits without waiting: the agent and its session are still starting."""
        ctl = self.make_controller(script)
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        ctl.run_sketch("Add a lid.", targets=[self.crate], scene=self.scene)
        self.assertFalse(ctl._started)
        return ctl

    def test_amend_right_after_submit_is_delivered(self):
        ctl = self.begin("amend.json")
        self.assertTrue(bpy.ops.whittle.amend.poll(), "Amend works from Submit on")
        add_stroke(self.obj, "free", NEW_POINTS, view=1, radius=0.01)
        self.props.amend_text = "Make it taller"
        self.assertEqual(operators.amend(bpy.context), 1)
        self.assertEqual(self.props.amend_text, "")
        finished = self.finish(ctl)
        self.assertFalse(finished["is_error"], finished)
        self.assertEqual(finished["amends_undelivered"], [])
        self.assertTrue(ctl.amends[1]["delivered"])
        self.assertIn("User amendment 1: Make it taller", self.events(ctl, "tool_result")[0]["summary"])
        self.assertIn("amend 1: 1 strokes, views [1]", [d["text"] for d in self.events(ctl, "text")])
        self.assertEqual(self.stamps(), [], "the amendment's strokes went with the turn")
        self.assertEqual(ctl.queued_amends, [])

    def test_queued_amend_of_a_refused_turn_comes_back(self):
        ctl = self.begin("refuse.json")
        ctl.amend("Make it taller", scene=self.scene)
        pump(ctl, lambda: ctl.errors, 15, "the refusal")
        self.assertEqual(self.props.prompt, "Make it taller")
        self.assertEqual(ctl.queued_amends, [])
        self.assertFalse(bpy.ops.whittle.amend.poll())


class ControllerTest(SteeringTestCase):
    """The controller the operators use follows the settings the agent was
    started with."""

    def current(self, script):
        ctl = operators.controller(str(FAKE_SCRIPTS / script))
        if ctl not in self.controllers:
            self.controllers.append(ctl)
        return ctl

    def test_an_idle_agent_restarts_when_its_settings_change(self):
        ctl = self.make_controller("ping.json")
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        self.start_ready(ctl)
        pid = ctl.process.popen.pid
        self.assertIs(self.current("ping.json"), ctl)
        self.assertEqual(ctl.process.popen.pid, pid, "nothing changed, so the agent stays")

        # The model goes with each submit: a new default keeps the agent.
        model = SimpleNamespace(**{**prefs.DEFAULTS, "model": "claude-haiku-5-5"})
        with mock.patch.object(prefs, "get", return_value=model):
            self.assertIs(self.current("ping.json"), ctl)
            self.assertEqual(ctl.process.popen.pid, pid)

        changed = SimpleNamespace(**{**prefs.DEFAULTS, "self_check_rounds": 1})
        with mock.patch.object(prefs, "get", return_value=changed):
            self.assertIs(self.current("ping.json"), ctl)
            self.assertFalse(ctl.process.alive, "the agent started with the old settings stopped")
            self.start_ready(ctl)
            self.assertIs(self.current("ping.json"), ctl)
            self.assertTrue(ctl.process.alive)

        other = self.current("stream.json")
        self.assertIsNot(other, ctl, "another fake script needs another agent")
        self.assertFalse(ctl.process.alive)
        self.assertEqual(other.process.fake_script, FAKE_SCRIPTS / "stream.json")


class AskTest(SteeringTestCase):
    def test_ask_and_answer(self):
        from whittle.addon import operators

        ctl = self.start("ask.json", attended=True)
        pump(ctl, lambda: ctl.question is not None, 15, "the question")
        self.assertEqual(ctl.status["phase"], "waiting_user")
        layout = RecordingLayout()
        ui.draw_main(layout, ui.Ctx(scene=self.scene, hist=ctl.history, ctl=ctl, comparing=None))
        buttons = [c["props"].text for c in layout.operators("whittle.answer") if hasattr(c["props"], "text")]
        self.assertEqual(buttons, ["yes", "no"])
        self.assertIn("Bevel the lid edges?", " ".join(layout.labels()))
        self.assertIn("ask_answer", layout.props(), "a free answer goes in the prompt box")
        self.assertTrue(operators.answer(bpy.context, "yes"))
        self.assertIsNone(ctl.question)
        self.finish(ctl)
        ask_result = self.events(ctl, "tool_result")[0]
        self.assertIn("yes", ask_result["summary"])
        self.assertIn({"question": "Bevel the lid edges?", "answer": "yes"},
                      [r["data"] for r in self.local_records(ctl) if r["name"] == "answer"])
        self.assertEqual(ctl.status["phase"], "idle")
        self.assertEqual(ctl.last_finished["errors"], [])

    def test_undo_during_a_turn_tells_the_agent(self):
        from whittle import addon
        from whittle.addon import operators

        ctl = self.start("ask.json", attended=True)
        pump(ctl, lambda: ctl.question is not None, 15, "the question")
        addon._after_undo()
        self.assertEqual(ctl.commands.notes, [turn.UNDO_NOTE])
        self.assertTrue(any("Undo during a turn" in e.text for e in ctl.stream.entries()))
        self.assertTrue(operators.answer(bpy.context, "yes"))
        self.assertEqual(ctl.commands.notes, [], "it went with the answer")
        self.finish(ctl)
        ctl.after_undo()
        self.assertEqual(ctl.commands.notes, [], "no turn, no note")

    def test_a_turn_ends_after_undo_frees_its_scene(self):
        # A real Ctrl+Z reads the undo step back in and frees the Scene the
        # turn began with (tests/gui's undo_turn); background Blender cannot
        # undo, so the Scene it holds is one that was removed.
        ctl = self.start("stream.json")
        node = ctl.turn_id
        gone = bpy.data.scenes.new("Freed by undo")
        ctl._scene = gone
        bpy.data.scenes.remove(gone)
        self.finish(ctl)
        self.assertEqual(ctl.history.current, node)
        self.assertFalse(ctl.history.node(node).folded)
        self.assertEqual(self.props.history_node, node)
        self.assertIn("Crate_Lid", [t.object.name for t in self.props.targets if t.object])

    def test_interrupt_while_asking(self):
        ctl = self.start("ask.json", attended=True)
        pump(ctl, lambda: ctl.question is not None, 15, "the question")
        ctl.interrupt()
        self.assertIsNone(ctl.question)
        finished = self.finish(ctl)
        self.assertTrue(finished["interrupted"])
        result = self.events(ctl, "tool_result")[0]
        self.assertTrue(result["is_error"])
        self.assertIn("interrupted", result["summary"])


# An edit, then a question that keeps the turn running.
EDIT_THEN_ASK = {"turns": [{"steps": [
    {"call": "exec", "params": {"label": "nudge", "code": "bpy.data.objects['Crate'].location.x += 0.1"},
     "expect": "ok"},
    {"ask": "Keep going?", "choices": ["yes"], "expect": "ok"},
    {"say": "Done."}], "finish": {"subtype": "success", "is_error": False, "result": "Nudged."}}]}


class TurnUndoTest(SteeringTestCase):
    """The undo steps around a turn (a real Ctrl+Z is tests/gui's undo_turn):
    background Blender cannot push or undo, so the pushes are recorded with
    the turn's edits and the prompt box at the time."""

    def setUp(self):
        super().setUp()
        from whittle.addon import history

        self.pushes = []
        self.ctl = None
        patcher = mock.patch.object(history, "undo_push", side_effect=lambda message: self.pushes.append(
            (message, self.ctl.commands.edits, self.props.prompt)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def start_turn(self):
        script = self.user_dir / "edit_then_ask.json"
        script.write_text(json.dumps(EDIT_THEN_ASK))
        self.ctl = ctl = self.make_controller(script)
        ctl.commands.attended = lambda: True
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        self.props.prompt = "Nudge it."
        ctl.hold_prompt(self.scene, "Nudge it.")
        ctl.run_sketch("Nudge it.", targets=[self.crate], scene=self.scene)
        pump(ctl, lambda: ctl.question is not None or ctl.errors, 15, "the question")
        self.assertEqual(ctl.errors, [])
        return ctl

    def test_the_turn_start_is_a_step_before_any_edit(self):
        ctl = self.start_turn()
        self.assertEqual(self.pushes, [(turn.TURN_START_UNDO, 0, "")],
                         "pushed before the agent's edit, with the sent prompt out of the box")
        ctl.answer("yes")
        self.finish(ctl)
        self.assertEqual(len(self.pushes), 2)
        self.assertTrue(self.pushes[1][0].startswith("Whittle: n0001"), "the turn's end is a step too")

    def test_a_modal_operation_puts_it_off_to_the_first_edit(self):
        modal = iter([True])
        with mock.patch.object(turn, "modal_running", side_effect=lambda: next(modal, False)):
            self.start_turn()
        self.assertEqual(self.pushes, [(turn.TURN_START_UNDO, 0, "")], "still before the edit")

    def test_undo_during_a_turn_lands_on_its_start(self):
        from whittle import addon

        self.assertIn(addon._before_undo, bpy.app.handlers.undo_pre)
        ctl = self.start_turn()
        del self.pushes[:]
        # Blender undoes to the step before the active one: the agent's edit
        # gets a step, so that is the turn's start.
        addon._before_undo()
        self.assertEqual(self.pushes, [("Whittle: n0001 so far", 1, "")])
        addon._after_undo()
        self.assertEqual(ctl.commands.notes, [turn.UNDO_NOTE])
        addon._before_undo()
        self.assertEqual(len(self.pushes), 1, "with no edit since, a second Ctrl+Z goes on past the start")
        ctl.answer("yes")
        self.finish(ctl)
        del self.pushes[:]
        ctl.before_undo()
        self.assertEqual(self.pushes, [], "no turn, no step")


class UserEditTest(SteeringTestCase):
    def test_user_edits_during_a_turn_are_not_reported(self):
        """Like Claude Code: the user may touch the scene while Claude works;
        nobody is warned or told, and no handler watches for it."""
        handlers = list(bpy.app.handlers.depsgraph_update_post)
        ctl = self.start("lock.json", attended=True)
        pump(ctl, lambda: ctl.question is not None, 15, "the question")
        self.assertEqual(list(bpy.app.handlers.depsgraph_update_post), handlers)
        self.crate.location.y += 0.3
        bpy.context.view_layer.update()
        ctl.answer("go on")
        self.finish(ctl)
        summaries = [e["summary"] for e in self.events(ctl, "tool_result")]
        self.assertFalse(any("edited" in s for s in summaries), summaries)
        self.assertEqual([e.text for e in ctl.stream.entries() if e.kind == "warning"], [])
        self.assertNotIn("target_edited", [r["name"] for r in self.local_records(ctl)])


class PendingStrokesTest(SteeringTestCase):
    def test_pending_strokes_are_not_in_turn_renders(self):
        from whittle.addon import render

        ctl = self.start("pending_render.json", attended=True)
        pump(ctl, lambda: ctl.question is not None, 15, "the question")
        pending = [(-0.24, -0.25, 0.05), (-0.2, -0.25, 0.05), (-0.16, -0.25, 0.05)]
        add_stroke(self.obj, "free", pending, view=1, radius=0.02)
        ctl.answer("yes")
        self.finish(ctl)
        rendered = self.events(ctl, "tool_result")[-1]["images"]
        strokes = render.load_pixels(rendered[1])
        h, w, _ = strokes.shape
        view = ctl.bundle.views[1]

        def alpha_near(co):
            x, y = views.to_pixel(view, co, w, h)
            row, col = h - 1 - int(y), int(x)
            return strokes[max(0, row - 2):row + 3, max(0, col - 2):col + 3, 3].max()

        self.assertTrue(all(alpha_near(p) == 0.0 for p in pending), "pending strokes are hidden")
        self.assertGreater(max(alpha_near(p) for p in B_POINTS), 0.5, "the turn's strokes are drawn")
        self.assertIn(("free", 0, 0), self.stamps(), "the pending stroke is untouched")
        attrs = self.obj.data.layers["free"].frames[0].drawing.attributes
        self.assertIsNone(attrs.get("hide_stroke"), "the hide attribute is removed again")
