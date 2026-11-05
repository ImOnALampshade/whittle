# SPDX-License-Identifier: GPL-3.0-or-later
"""Which SDK session each turn runs in: the live client carries on along a
branch, a submit from anywhere else resumes or forks the conversation that
matches the scene, and a conversation that cannot be resumed gives way to a
fresh one."""

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import bpy

from tests.blender.helpers import REPO, pump
from tests.blender.history_helpers import HistoryTurnCase
from whittle import tree
from whittle.addon import chats, conversation, history, paths, transcript, turn, ui
from whittle.addon.process import AgentState
from whittle.protocol import SESSION_ENDED, Event


def start_params(start):
    return {key: start[key] for key in ("resume", "fork", "resume_at")}


class SessionBookkeepingTest(HistoryTurnCase):
    def restart(self, ctl):
        """As if Blender closed and opened the file again."""
        ctl.stop(wait=True)
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        turn.set_current(None)
        history.invalidate()
        return self.controller()

    def test_sessions_follow_the_tree(self):
        ctl = self.controller()
        hist = ctl.history

        n1 = self.turn(ctl, "Scale it.")
        self.assertEqual([start_params(s) for s in ctl.session_starts],
                         [{"resume": None, "fork": False, "resume_at": None}])
        self.assertEqual(self.context_lines(ctl, n1), [])
        s1, u1 = hist.node(n1).agent_session_id, hist.node(n1).agent_message_uuid

        n2 = self.submit(ctl, "Add a lid.")
        self.assertEqual(hist.node(n2).continued_session, s1,
                         "known before the turn ends, so a crash mid-turn still records it")
        self.wait(ctl, n2)
        self.assertEqual(len(ctl.session_starts), 1, "the live client carries on")
        self.assertEqual(hist.node(n2).agent_session_id, s1)
        self.assertIsNone(hist.node(n1).continued_session, "a fresh session has no id yet")

        hist.restore(n1, self.scene)
        n3 = self.turn(ctl, "Another lid.")
        self.assertEqual(start_params(ctl.session_starts[-1]), {"resume": s1, "fork": True, "resume_at": u1})
        s3 = hist.node(n3).agent_session_id
        self.assertIsNone(hist.node(n3).continued_session, "a fork is not the session it forks")
        self.assertNotEqual(s3, s1, "a fork is a new session")
        lines = self.context_lines(ctl, n3)
        self.assertTrue(any(n1 in line and "other branches" in line for line in lines), lines)

        hist.restore(n2, self.scene)
        n4 = self.turn(ctl, "Nudge.")
        self.assertEqual(start_params(ctl.session_starts[-1]), {"resume": s1, "fork": False, "resume_at": None},
                         "a leaf that ends its session is resumed as it is")
        self.assertEqual(hist.node(n4).agent_session_id, s1)
        self.assertEqual(self.context_lines(ctl, n4), [])
        self.assertEqual(len(ctl.session_starts), 3)

        ctl = self.restart(ctl)
        self.assertEqual(ctl.history.current, n4)
        n5 = self.turn(ctl, "Nudge again.")
        self.assertEqual([start_params(s) for s in ctl.session_starts],
                         [{"resume": s1, "fork": False, "resume_at": None}])
        self.assertEqual(ctl.history.node(n5).agent_session_id, s1)
        self.assertEqual(ctl.history.node(n5).parent, n4)
        self.assertEqual(ctl.history.node(n5).continued_session, s1)

        ctl.history.restore("n0000", self.scene)
        n6 = self.turn(ctl, "From scratch.")
        self.assertEqual(start_params(ctl.session_starts[-1]), {"resume": None, "fork": False, "resume_at": None})
        self.assertEqual(self.context_lines(ctl, n6), [])
        self.assertNotIn(ctl.history.node(n6).agent_session_id, (s1, s3))

    def test_failed_resume_falls_back_to_a_fresh_session(self):
        ctl = self.controller()
        n1 = self.turn(ctl, "Scale it.")
        s1 = ctl.history.node(n1).agent_session_id
        ctl.stop(wait=True)
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        turn.set_current(None)

        ctl = self.controller("resume_fails.json")
        n2 = self.turn(ctl, "Add a lid.")
        self.assertEqual([start_params(s) for s in ctl.session_starts],
                         [{"resume": s1, "fork": False, "resume_at": None},
                          {"resume": None, "fork": False, "resume_at": None}])
        lines = self.context_lines(ctl, n2)
        self.assertTrue(any("could not be resumed" in line for line in lines), lines)
        found = ctl.history.node(n2)
        self.assertEqual(found.status, "complete")
        self.assertNotEqual(found.agent_session_id, s1)

    def resume_fails(self, script="resume_fails.json"):
        """A controller whose next submit cannot resume the earlier conversation."""
        ctl = self.controller()
        self.turn(ctl, "Scale it.")
        ctl.stop(wait=True)
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        turn.set_current(None)
        return self.controller(script)

    def warnings(self, entries):
        return [e.text for e in entries if e.kind == "warning" and "Could not resume" in e.text]

    def test_the_resume_warning_stays_with_its_turn(self):
        ctl = self.resume_fails()
        node = self.submit(ctl, "Add a lid.")
        pump(ctl, lambda: ctl.turn_id == node, 15, "the turn to start")
        conv = conversation.build(ctl.history, ctl)
        self.assertEqual(conv.turns[-1].node, node)
        self.assertTrue(conv.turns[-1].running)
        self.assertEqual(len(self.warnings(conv.turns[-1].entries)), 1, "while the turn runs")
        self.assertEqual(self.warnings(conv.notes), [], "and only there")

        self.wait(ctl, node)
        conv = conversation.build(ctl.history, ctl)
        self.assertEqual(conv.turns[-1].node, node)
        self.assertEqual(len(self.warnings(conv.turns[-1].entries)), 1, "once it has finished")
        self.assertEqual(self.warnings(conv.notes), [])
        self.assertIn("warning", [kind for kind, _item in ui._segments(conv.turns[-1].entries)])
        self.assertIn(">> Warning: Could not resume", transcript.format_transcript(self.local_records(ctl, node)))

        ctl.stop(wait=True)
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        turn.set_current(None)
        history.invalidate()
        conversation.clear_cache()
        conv = conversation.build(self.controller().history, None)
        self.assertEqual(conv.turns[-1].node, node)
        self.assertEqual(len(self.warnings(conv.turns[-1].entries)), 1, "and in a reopened file")

    def test_the_resume_warning_shows_while_its_run_waits(self):
        ctl = self.resume_fails()
        self.start_ready(ctl)
        ctl._pending_run = (ctl.session.root, "x", None, False)
        self.addCleanup(setattr, ctl, "_pending_run", None)
        with mock.patch.object(ctl, "_advance"):
            ctl._on_session_started(False, {"message": "gone"}, {"resume": "s1"})
        self.assertEqual(len(self.warnings(conversation.build(ctl.history, ctl).notes)), 1)

    def test_the_resume_warning_goes_with_the_turn_that_ran(self):
        ctl = self.resume_fails("resume_refused.json")
        node = self.submit(ctl, "Add a lid.")
        pump(ctl, lambda: ctl.errors, 15, "the refusal")
        self.assertFalse(ctl.session.node_dir(node).exists())
        ctl.errors.clear()

        # The refused turn's number comes round again and takes the warning,
        # and resuming fails again when the session this run finds has ended.
        self.assertEqual(self.submit(ctl, "Add a lid."), node)
        self.wait(ctl, node)
        self.assertEqual([r["name"] for r in self.local_records(ctl, node)].count("warning"), 1)
        conv = conversation.build(ctl.history, ctl)
        self.assertEqual(len(self.warnings(conv.turns[-1].entries)), 1)
        self.assertEqual(len(self.warnings(e for e in ctl.stream.entries() if e.turn_id == node)), 1,
                         "the refused turn's warning did not come back with its number")

    def test_the_resume_warning_waits_for_the_turn_the_agent_takes(self):
        ctl = self.resume_fails("resume_refused_once.json")
        first = self.submit(ctl, "Add a lid.")
        pump(ctl, lambda: ctl.errors, 15, "the refusal")
        ctl.errors.clear()

        # The fresh session carries on, so nothing fails again, yet this
        # submit is the one that tells the agent the conversation was lost.
        node = self.turn(ctl, "Add a lid.")
        self.assertEqual(node, first)
        self.assertEqual([s["resume"] is None for s in ctl.session_starts], [False, True])
        self.assertTrue(any("could not be resumed" in line for line in self.context_lines(ctl, node)))
        self.assertEqual([r["name"] for r in self.local_records(ctl, node)].count("warning"), 1)
        conv = conversation.build(ctl.history, ctl)
        self.assertEqual(len(self.warnings(conv.turns[-1].entries)), 1)

    def assert_lost_on(self, ctl, node):
        """The fresh session's turn told the agent and keeps the user's warning."""
        self.assertIsNotNone(ctl.session_starts[0]["resume"])
        self.assertIsNone(ctl.session_starts[-1]["resume"])
        self.assertTrue(any("could not be resumed" in line for line in self.context_lines(ctl, node)))
        names = [r["name"] for r in self.local_records(ctl, node)]
        self.assertEqual((names.count("submit"), names.count("warning")), (2, 1))
        conv = conversation.build(ctl.history, ctl)
        self.assertEqual(conv.turns[-1].node, node)
        self.assertEqual(len(self.warnings(conv.turns[-1].entries)), 1)

    def test_a_session_gone_at_the_first_submit_warns_too(self):
        ctl = self.resume_fails("resume_lost.json")
        self.assert_lost_on(ctl, self.turn(ctl, "Add a lid."))

    def test_a_session_end_before_the_refusal_warns_once(self):
        ctl = self.resume_fails("resume_lost.json")
        answer = ctl._on_submit_result

        def after_the_end(ok, data):
            # The real agent's order: its status, then no_session.
            if not ok:
                ctl.on_event({"name": Event.STATUS,
                              "data": {"turn_id": None, "state": SESSION_ENDED, "detail": "the agent CLI stopped"}})
            answer(ok, data)

        with mock.patch.object(ctl, "_on_submit_result", after_the_end):
            node = self.turn(ctl, "Add a lid.")
        self.assert_lost_on(ctl, node)

    def test_a_session_end_while_idle_warns_of_nothing(self):
        ctl = self.controller()
        self.start_ready(ctl)
        ctl._resumed = True
        ctl.on_event({"name": Event.STATUS, "data": {"turn_id": None, "state": SESSION_ENDED, "detail": "gone"}})
        self.assertEqual(self.warnings(ctl.stream.entries()), [], "the next run tries to resume again")

    def test_a_warning_left_waiting_goes_with_its_session(self):
        ctl = self.controller()
        self.turn(ctl, "Scale it.")
        ctl._resume_warning = ctl.stream.note("Could not resume.", kind="warning")
        ctl.on_event({"name": Event.STATUS, "data": {"turn_id": None, "state": SESSION_ENDED, "detail": "gone"}})
        node = self.turn(ctl, "Add a lid.")
        self.assertEqual(len(ctl.session_starts), 2, "resumed in another session")
        self.assertNotIn("warning", [r["name"] for r in self.local_records(ctl, node)])

    def test_a_stopped_agent_takes_the_waiting_warning_with_it(self):
        ctl = self.controller()
        self.start_ready(ctl)
        ctl._resume_warning = ctl.stream.note("Could not resume.", kind="warning")
        ctl.stop(wait=True)
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        self.assertIsNone(ctl._resume_warning)

    def test_a_resent_submit_keeps_one_resume_warning(self):
        ctl = self.resume_fails("resume_retried.json")
        node = self.turn(ctl, "Add a lid.")
        names = [r["name"] for r in self.local_records(ctl, node)]
        self.assertEqual(names.count("submit"), 2, "sent again after no_session")
        self.assertEqual(names.count("warning"), 1)

    def test_a_later_turn_leaves_the_resume_warning_behind(self):
        ctl = self.resume_fails()
        first = self.turn(ctl, "Add a lid.")
        second = self.turn(ctl, "Taller.")
        self.assertIn("warning", [r["name"] for r in self.local_records(ctl, first)])
        self.assertNotIn("warning", [r["name"] for r in self.local_records(ctl, second)])


class SceneFollowingTest(HistoryTurnCase):
    """The current node follows the scene: after undo or redo, and when a
    saved file is opened again."""

    def saved_current(self, ctl):
        found, _ = tree.read_session(ctl.session.session_path())
        return found.current

    def test_undo_and_redo_move_the_current_node(self):
        from whittle import addon

        self.assertIn(addon._after_undo, bpy.app.handlers.undo_post)
        self.assertIn(addon._after_undo, bpy.app.handlers.redo_post)
        ctl = self.controller()
        n1 = self.turn(ctl, "Scale it.")
        n2 = self.turn(ctl, "Add a lid.")
        self.assertEqual(self.props.history_node, n2)

        # What Blender's undo does to the scene property, then its handler.
        self.props.history_node = n1
        addon._after_undo()
        self.assertEqual((ctl.history.current, self.saved_current(ctl)), (n1, n1))

        self.props.history_node = "n0099"
        with self.assertLogs("whittle", "WARNING"):
            addon._after_undo()
        self.assertEqual(self.saved_current(ctl), n1, "an unknown node changes nothing")

        self.props.history_node = ""
        addon._after_undo()
        self.assertEqual(self.saved_current(ctl), "n0000", "before the first turn is the root")

        self.props.history_node = n2
        addon._after_undo()
        self.assertEqual(self.saved_current(ctl), n2)
        n3 = self.turn(ctl, "Nudge.")
        self.assertEqual(ctl.history.node(n3).parent, n2)

    def test_reopened_file_wins_over_session_json(self):
        blend = self.user_dir / "scene.blend"
        unsaved = mock.patch.object(paths, "blend_path", return_value=None)
        unsaved.start()
        self.addCleanup(unsaved.stop)
        chats.reset()
        self.session_dir = chats.current_folder(create=True)
        ctl = self.controller()
        n1 = self.turn(ctl, "Scale it.")
        n2 = self.turn(ctl, "Add a lid.")
        s1 = ctl.history.node(n1).agent_session_id
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
        # Restored but not saved: session.json says n1, the file still n2.
        ctl.history.restore(n1, self.scene)
        self.assertEqual(self.saved_current(ctl), n1)
        ctl.stop(wait=True)
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")

        script = (f"import sys, json; sys.path.insert(0, {str(REPO)!r})\n"
                  "import bpy\n"
                  "from whittle import addon, tree\n"
                  "from whittle.addon import history\n"
                  "addon.register()\n"
                  f"bpy.ops.wm.open_mainfile(filepath={str(blend)!r})\n"
                  "h = history.active()\n"
                  "plan = tree.session_plan(h.tree, h.current, None)\n"
                  "added = h.begin('n0099', 'next')\n"
                  "print('RESULT', json.dumps({'scene': bpy.context.scene.whittle.history_node,\n"
                  "    'current': h.current, 'parent': added.parent, 'folder': str(h.session.root),\n"
                  "    'plan': [plan.resume, plan.fork, plan.resume_at, list(plan.notes)]}))\n")
        env = {**os.environ, "WHITTLE_USER_DIR": str(self.user_dir / "user")}
        out = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-expr", script],
                             capture_output=True, text=True, timeout=120, env=env)
        line = next((l for l in out.stdout.splitlines() if l.startswith("RESULT ")), None)
        self.assertIsNotNone(line, out.stdout[-2000:] + out.stderr[-2000:])
        result = json.loads(line[len("RESULT "):])
        self.assertEqual(result["scene"], n2)
        self.assertEqual(result["current"], n2)
        self.assertEqual(result["parent"], n2, "the next submit starts from what the file shows")
        self.assertEqual(result["plan"], [s1, False, None, []],
                         "n2 ends its session, so it resumes as it is rather than forking at n1")
        # Opened with another user folder: its chat came out of the file
        # into a cache there.
        chat = Path(result["folder"])
        self.assertEqual(chat.parents[2], self.user_dir / "user" / "cache")
        self.assertEqual(chat.name, self.session_dir.name)
        found, _ = tree.read_session(chat / "session.json")
        self.assertEqual(found.current, n2)
