# SPDX-License-Identifier: GPL-3.0-or-later
"""A crate scene with a sketch, the add-on registered and undo pushes
recorded, for history tests that run turns through the fake agent."""

import json
from unittest import mock

import bpy

from tests.blender.helpers import AgentTestCase, pump
from tests.blender.sketch_helpers import add_stroke, look_at_view
from tests.fixtures.crate.scene import build_scene
from whittle.addon import compare, history, sketch, targets, views

STROKE = [(-0.15 + 0.05 * i, -0.25, 0.3) for i in range(7)]


class HistoryTurnCase(AgentTestCase):
    def setUp(self):
        super().setUp()
        sketch.end_session()
        self.crate = build_scene()
        old = sketch.find_sketch_object()
        if old is not None:
            bpy.data.objects.remove(old)
        compare.reset()
        compare.clear_ghost()
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.addCleanup(compare.reset)
        self.scene = bpy.context.scene
        self.props = self.scene.whittle
        # These tests pick targets by hand.
        self.props.target_auto = False
        self.props.targets.clear()
        self.props.target_collection = None
        self.props.prompt = ""
        self.props.amend_text = ""
        self.props.history_node = ""
        self.props.targets.add().object = self.crate
        self.obj = sketch.ensure_sketch_layers(self.scene)
        views.add_view(self.obj.data, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))
        patcher = mock.patch.object(history, "undo_push")
        self.undo = patcher.start()
        self.addCleanup(patcher.stop)

    def controller(self, script="history.json", **kwargs):
        from whittle.addon import turn

        ctl = self.make_controller(script, **kwargs)
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        return ctl

    def submit(self, ctl, prompt):
        """Starts a sketch run from the current targets; returns its node."""
        add_stroke(self.obj, "free", STROKE, view=1, radius=0.01)
        return ctl.run_sketch(prompt, targets=targets.resolve(self.scene), scene=self.scene)

    def turn(self, ctl, prompt="Make it so.", timeout=30):
        node = self.submit(ctl, prompt)
        self.wait(ctl, node, timeout)
        return node

    def wait(self, ctl, node, timeout=30):
        pump(ctl, lambda: (ctl.last_finished or {}).get("turn_id") == node or ctl.errors,
             timeout, f"turn {node} to finish")
        self.assertEqual(ctl.errors, [])
        return ctl.last_finished

    def context_lines(self, ctl, node):
        """The context lines the fake agent received with node's submit."""
        return [e["data"]["message"][len("context: "):] for e in ctl.events
                if e["name"] == "log" and e["data"].get("turn_id") == node
                and e["data"]["message"].startswith("context: ")]

    def local_records(self, ctl, node):
        lines = ctl.session.transcript_path(node).read_text().splitlines()
        return [r for r in map(json.loads, lines) if r["type"] == "local"]
