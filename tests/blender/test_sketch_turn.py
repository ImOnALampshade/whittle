# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
import os
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import FAKE_SCRIPTS, AgentTestCase, agent_python, pump
from tests.blender.sketch_helpers import add_stroke, fake_viewport, look_at_view
from tests.fixtures.crate.scene import build_scene
from whittle import formats
from whittle.addon import sketch, views
from whittle.addon.process import AgentState

A_POINTS = [(-0.15 + 0.05 * i, -0.25, 0.3) for i in range(7)]
B_POINTS = [(0.2, 0.0, 0.7), (0.0, 0.2, 0.7), (-0.2, 0.0, 0.7), (0.0, -0.2, 0.7)]
F_POINTS = [(0.0, -0.25, 0.1), (0.1, -0.25, 0.1)]


class SketchTurnTest(AgentTestCase):
    def setUp(self):
        super().setUp()
        self.crate = build_scene()
        old = sketch.find_sketch_object()
        if old is not None:
            bpy.data.objects.remove(old)
        self.scene = bpy.context.scene
        self.obj = sketch.ensure_sketch_layers(self.scene)
        gp = self.obj.data
        views.add_view(gp, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))
        views.add_view(gp, lambda i: look_at_view(i, (0, -2, 0.3), (0, 0, 0.3)))
        views.add_view(gp, lambda i: look_at_view(i, (-1.5, -1.5, 0.8), (0, 0, 0.3)))
        add_stroke(self.obj, "carve", A_POINTS, view=2, radius=0.01)
        add_stroke(self.obj, "add", B_POINTS, view=1, cyclic=True)

    def strokes(self):
        return [(s.layer, s.view, s.turn, len(s.points)) for s in sketch.iter_strokes(self.obj)]

    def run_and_finish(self, ctl, prompt="Carve a slot."):
        node = ctl.run_sketch(prompt, targets=[self.crate])
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 30, "the turn to finish")
        return node

    def test_end_to_end(self):
        ctl = self.make_controller("sketch_turn.json")
        node = ctl.run_sketch("Carve a slot.", targets=[self.crate])
        self.assertEqual(node, "n0001")
        self.assertEqual([t for _l, _v, t, _n in self.strokes()], [1, 1], "the sent strokes are stamped")
        pump(ctl, lambda: ctl.running, 15, "the turn to start")
        add_stroke(self.obj, "free", F_POINTS, view=1)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 30, "the turn to finish")
        self.assertEqual(ctl.errors, [])
        self.assertFalse(ctl.last_finished["is_error"], ctl.last_finished)

        written = formats.read_bundle(ctl.session.request_dir("n0001"))
        self.assertEqual((written.request.node, written.request.parent), ("n0001", "n0000"))
        self.assertEqual(written.request.prompt, "Carve a slot.")
        self.assertEqual([(s.type, s.view) for s in written.strokes], [("add", 1), ("carve", 2)])
        self.assertTrue(all(written.strokes[1].on_surface))
        renders = sorted(p.name for p in ctl.session.renders_dir("n0001").iterdir())
        self.assertIn("001-v1-overlay.png", renders)

        self.assertEqual(self.strokes(), [("free", 1, 0, 2)], "sent strokes go, pending ones stay")
        self.assertEqual([v.id for v in views.load_views(self.obj.data)], [1, 3])

    def test_crashed_turn_keeps_its_strokes_for_the_next_run(self):
        ctl = self.make_controller("crash.json")
        ctl.run_sketch("Carve a slot.", targets=[self.crate])
        pump(ctl, lambda: ctl.process.state == AgentState.CRASHED, 15, "the crash")
        self.assertTrue(ctl.last_finished["is_error"])
        self.assertEqual([t for _l, _v, t, _n in self.strokes()], [1, 1])
        self.assertEqual(len(views.load_views(self.obj.data)), 3)

        second = self.make_controller("sketch_turn.json")
        node = second.run_sketch("Again.", targets=[self.crate])
        self.assertEqual(node, "n0002")
        self.assertEqual([t for _l, _v, t, _n in self.strokes()], [2, 2])
        pump(second, lambda: second.last_finished is not None or second.errors, 30, "the second turn")
        self.assertEqual(second.errors, [])
        self.assertEqual(self.strokes(), [])
        # The crash came before any edit, so n0001 folded into the start.
        self.assertTrue(second.history.node("n0001").folded)
        self.assertEqual(formats.read_bundle(second.session.request_dir("n0002")).request.parent, "n0000")

    def test_run_that_cannot_start_writes_nothing(self):
        from whittle.addon import paths

        ctl = self.make_controller(python=None)
        with mock.patch.object(paths, "agent_python", lambda: None):
            with self.assertRaisesRegex(RuntimeError, "agent environment is not set up"):
                ctl.run_sketch("Carve.", targets=[self.crate])
        self.assertFalse(ctl.session.node_dir("n0001").exists())
        self.assertEqual([t for _l, _v, t, _n in self.strokes()], [0, 0])

        good = self.make_controller("sketch_turn.json")
        self.assertEqual(self.run_and_finish(good), "n0001")
        self.assertEqual(good.errors, [])

    def test_run_dropped_before_the_agent_is_ready_removes_its_bundle(self):
        ctl = self.make_controller("sketch_turn.json")
        node = ctl.run_sketch("Carve.", targets=[self.crate])
        self.assertTrue(ctl.session.request_dir(node).is_dir())
        ctl.stop()
        self.assertIsNone(ctl._pending_run)
        self.assertFalse(ctl.session.node_dir(node).exists())
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        self.assertEqual(self.run_and_finish(ctl), "n0001", "the dropped run's number is reused")
        written = formats.read_bundle(ctl.session.request_dir("n0001"))
        self.assertEqual(written.request.parent, "n0000")

    def test_hidden_strokes_of_a_dropped_run_survive_the_next_run(self):
        ctl = self.make_controller("sketch_turn.json")
        node = ctl.run_sketch("Carve.", targets=[self.crate])
        ctl.stop()
        self.assertEqual([t for _l, _v, t, _n in self.strokes()], [0, 0], "a dropped run unstamps")
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        self.obj.data.layers["carve"].hide = True
        self.assertEqual(self.run_and_finish(ctl), node)
        self.assertEqual(ctl.errors, [])
        written = formats.read_bundle(ctl.session.request_dir(node))
        self.assertEqual([s.type for s in written.strokes], ["add"])
        kept = [(s.layer, s.view, s.turn) for s in sketch.iter_strokes(self.obj, include_hidden=True)]
        self.assertEqual(kept, [("carve", 2, 0)], "unsent strokes stay")

    def test_failed_write_keeps_the_node_number(self):
        ctl = self.make_controller("sketch_turn.json")
        views.clear_views(self.obj.data)
        with self.assertRaisesRegex(Exception, "no sketch view"):
            ctl.run_sketch("Carve.", targets=[self.crate])
        with self.assertRaisesRegex(Exception, "not found"):
            ctl.run_sketch("Carve.", targets=[self.crate], refs=["/nonexistent/whittle-ref.png"])
        self.assertFalse((ctl.session.root / "nodes").exists() and any((ctl.session.root / "nodes").iterdir()))
        self.assertEqual([t for _l, _v, t, _n in self.strokes()], [0, 0])

        views.add_view(self.obj.data, lambda i: look_at_view(i, (0, -2, 0.3), (0, 0, 0.3)))
        self.assertEqual(self.run_and_finish(ctl), "n0001")
        self.assertEqual(ctl.errors, [])
        written = formats.read_bundle(ctl.session.request_dir("n0001"))
        self.assertEqual((written.request.node, written.request.parent), ("n0001", "n0000"))

    def test_a_second_run_while_one_waits_is_refused(self):
        ctl = self.make_controller("sketch_turn.json")
        ctl.run_sketch("Carve.", targets=[self.crate])
        with self.assertRaisesRegex(RuntimeError, "waiting"):
            ctl.run_sketch("Again.", targets=[self.crate])
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 30, "the turn to finish")

    def test_no_session_retry_keeps_the_sketch_node(self):
        ctl = self.make_controller(FAKE_SCRIPTS / "end_session.json")
        self.run_and_finish(ctl)
        self.assertFalse(ctl.session_ready)
        ctl.last_finished = None
        add_stroke(self.obj, "free", F_POINTS, view=3)
        # As if the session_ended status had not arrived before the next run.
        ctl.session_ready = True
        ctl.live_node = "n0001"
        node = self.run_and_finish(ctl)
        self.assertEqual(ctl.errors, [])
        self.assertEqual((node, ctl.last_finished["turn_id"]), ("n0002", "n0002"))
        first = ctl.history.node("n0001").agent_session_id
        self.assertEqual(ctl.session_starts[-1]["resume"], first, "the ended conversation is resumed")
        self.assertEqual(ctl.last_finished["session_id"], first)
        self.assertFalse(ctl.session.node_dir("n0003").exists())

    def test_request_tool_reads_the_written_bundle(self):
        from whittle.agent import tools

        ctl = self.make_controller("sketch_turn.json")
        self.run_and_finish(ctl)
        root = ctl.session.request_dir("n0001")
        result = asyncio.run(tools.request_tool(tools.ToolContext(connection=None, bundle_dir=str(root)), {}))
        self.assertNotIn("is_error", result)
        images = [b for b in result["content"] if b["type"] == "image"]
        self.assertEqual(len(images), 2)
        text = result["content"][0]["text"]
        payload = text.split("world space):\n", 1)[1]
        self.assertEqual(json.loads(payload), [s.to_json() for s in formats.read_bundle(root).strokes])


class SketchOperatorTest(AgentTestCase):
    def setUp(self):
        super().setUp()
        self.crate = build_scene()
        old = sketch.find_sketch_object()
        if old is not None:
            bpy.data.objects.remove(old)
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)

    def test_stroke_type_operators(self):
        self.assertEqual(bpy.ops.whittle.stroke_type(type="carve"), {"FINISHED"})
        obj = sketch.find_sketch_object()
        self.assertEqual(sketch.active_type(obj), "carve")
        self.assertEqual(bpy.ops.whittle.next_stroke_type(), {"FINISHED"})
        self.assertEqual(sketch.active_type(obj), "crease")

    def test_capture_view_body(self):
        from whittle.addon import operators

        vp = fake_viewport(look_at_view(0, (0, -2, 0.3), (0, 0, 0.3)))
        with mock.patch.object(views, "viewport_from_context", lambda context: vp):
            view = operators.capture_view(bpy.context)
        self.assertEqual(view.id, 1)
        self.assertEqual([v.id for v in views.load_views(sketch.find_sketch_object().data)], [1])
        with mock.patch.object(views, "viewport_from_context", lambda context: None):
            with self.assertRaises(RuntimeError):
                operators.capture_view(bpy.context)

    def test_submit_sketch_body(self):
        from whittle.addon import operators, turn

        obj = sketch.ensure_sketch_layers(bpy.context.scene)
        views.add_view(obj.data, lambda i: look_at_view(i, (0, -2, 0.3), (0, 0, 0.3)))
        add_stroke(obj, "carve", A_POINTS)
        ref = self.user_dir / "ref.png"
        ref.write_bytes((FAKE_SCRIPTS.parent / "crate" / "request" / "views" / "1" / "overlay.png").read_bytes())
        props = bpy.context.scene.whittle
        props.prompt = "Carve a slot."
        props.refs.add().path = str(ref)
        props.targets.add().object = self.crate
        # The selection no longer decides the target.
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        # A value the developer exported comes back afterwards.
        env = mock.patch.dict(os.environ, {"WHITTLE_AGENT_PYTHON": str(agent_python())})
        env.start()
        self.addCleanup(env.stop)
        ctl, node = operators.submit_sketch(bpy.context, str(FAKE_SCRIPTS / "sketch_turn.json"))
        self.controllers.append(ctl)
        self.assertIs(turn.current(), ctl)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 30, "the turn to finish")
        self.assertEqual(ctl.errors, [])
        req = formats.read_bundle(ctl.session.request_dir(node)).request
        self.assertEqual([t["name"] for t in req.target], ["Crate"])
        self.assertEqual(req.refs, ["refs/ref.png"])
        self.assertEqual(req.prompt, "Carve a slot.")
        props.refs.clear()
        props.targets.clear()
        props.prompt = ""
