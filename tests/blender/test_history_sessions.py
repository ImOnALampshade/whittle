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
from whittle.addon import chats, history, paths, turn
from whittle.addon.process import AgentState


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
