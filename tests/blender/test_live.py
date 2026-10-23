# SPDX-License-Identifier: GPL-3.0-or-later
"""Live smoke test against the real Claude agent. Costs money, so it only runs
with WHITTLE_LIVE=1 (run_tests.sh then starts Blender with --online-mode)."""

import os
import unittest

import bpy

from tests.blender.helpers import CRATE_BUNDLE, AgentTestCase, pump
from tests.fixtures.crate.scene import build_scene
from whittle.protocol import Event, Method

LIVE = os.environ.get("WHITTLE_LIVE") == "1"
PROMPT = ("This is a connectivity test. Do not read the request bundle. Call mcp__blender__exec "
          "exactly once with code `print(2 + 2)` and label `probe`, then reply with the single word done.")


@unittest.skipUnless(LIVE, "set WHITTLE_LIVE=1 to run tests that call the Claude API")
@unittest.skipUnless(os.environ.get("ANTHROPIC_API_KEY"), "the live tests need ANTHROPIC_API_KEY")
class LiveAgentTest(AgentTestCase):
    def test_trivial_exec_round_trip(self):
        if not bpy.app.online_access:
            self.skipTest("Blender needs --online-mode for the live test")
        build_scene()
        ctl = self.make_controller(script=None, model="claude-haiku-5-5",
                                   settings={"max_turns": 4, "max_budget_usd": 0.10})
        execs = []
        handler = ctl.process.handlers[Method.EXEC]

        def recording(params):
            result = handler(params)
            execs.append((params, result))
            return result

        ctl.process.handlers[Method.EXEC] = recording
        ctl.run_bundle(CRATE_BUNDLE, PROMPT)
        try:
            pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 180, "the live turn")
        finally:
            for event in ctl.events:
                if event["name"] in (Event.LOG, Event.ERROR, Event.TEXT, Event.TOOL_USE, Event.TURN_FINISHED):
                    print(f"\n  [{event['name']}] {event['data']}", end="")
            print("\n  agent log tail:\n    " + "\n    ".join(ctl.process.log_tail(15)))
        self.assertEqual(ctl.errors, [])
        finished = ctl.last_finished
        self.assertFalse(finished["is_error"], finished)
        self.assertTrue(finished["session_id"])
        self.assertTrue(execs, "the agent's exec reached Blender")
        params, result = execs[0]
        self.assertEqual(params["code"].strip(), "print(2 + 2)")
        self.assertEqual(result["stdout"], "4\n")
        ctl.stop(wait=True)

    def test_amendment_reaches_the_agent(self):
        if not bpy.app.online_access:
            self.skipTest("Blender needs --online-mode for the live test")
        build_scene()
        ctl = self.make_controller(script=None, model="claude-haiku-5-5",
                                   settings={"max_turns": 6, "max_budget_usd": 0.10})
        prompt = ("This is a connectivity test. Do not read the request bundle. Call mcp__blender__exec "
                  "with code `print(1)`, then reply done.")
        ctl.run_bundle(CRATE_BUNDLE, prompt)
        try:
            pump(ctl, lambda: ctl._started or ctl.errors, 120, "the live turn to start")
            ctl.amend("Also call mcp__blender__exec with code `print(2)` before you reply.")
            pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 180, "the amended turn")
            first = ctl.last_finished
            # A second turn in the same session shows whether total_cost_usd is
            # a running session total or per query.
            ctl.last_finished = None
            ctl.run_bundle(CRATE_BUNDLE, "This is a connectivity test. Reply with the single word done.")
            pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 120, "the second turn")
            second = ctl.last_finished
        finally:
            for event in ctl.events:
                if event["name"] in (Event.LOG, Event.ERROR, Event.TOOL_USE, Event.AMEND_DELIVERED,
                                     Event.TURN_FINISHED):
                    print(f"\n  [{event['name']}] {event['data']}", end="")
            print()
        self.assertEqual(ctl.errors, [])
        self.assertFalse(first["is_error"], first)
        delivered = [e["data"] for e in ctl.events if e["name"] == Event.AMEND_DELIVERED]
        self.assertEqual([d["amend"] for d in delivered], [1], "the amendment was delivered")
        self.assertEqual(first["amends_undelivered"], [])
        self.assertFalse(second["is_error"], second)
        print(f"  cost: first turn {first['cost_usd']} (session {first['session_cost_usd']}), "
              f"second turn {second['cost_usd']} (session {second['session_cost_usd']})")
        self.assertGreater(second["session_cost_usd"], first["session_cost_usd"],
                           "total_cost_usd is a running session total")
        ctl.stop(wait=True)

    def test_live_fork(self):
        """A branch from an earlier node forks the SDK conversation at that
        node's last message: the new session has the first turn, not the second."""
        import json
        import subprocess

        from tests.blender.helpers import agent_python
        from whittle.addon import history
        from unittest import mock

        if not bpy.app.online_access:
            self.skipTest("Blender needs --online-mode for the live test")
        build_scene()
        ctl = self.make_controller(script=None, model="claude-haiku-5-5",
                                   settings={"max_turns": 3, "max_budget_usd": 0.10})
        prompts = ["Connectivity test ALPHA. Do not read the request bundle. Call mcp__blender__exec "
                   "once with code `print(1)`, then reply done.",
                   "Connectivity test BRAVO. Call mcp__blender__exec once with code `print(2)`, "
                   "then reply done.",
                   "Connectivity test CHARLIE. Reply with the single word ok, no tools."]
        nodes = []
        with mock.patch.object(history, "undo_push"):
            try:
                for i, prompt in enumerate(prompts):
                    if i == 2:
                        ctl.history.restore(nodes[0], bpy.context.scene)
                    ctl.last_finished = None
                    ctl.run_bundle(CRATE_BUNDLE, prompt)
                    pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 180, f"live turn {i + 1}")
                    nodes.append(ctl.last_finished["turn_id"])
            finally:
                for event in ctl.events:
                    if event["name"] in (Event.LOG, Event.ERROR, Event.TURN_FINISHED):
                        print(f"\n  [{event['name']}] {event['data']}", end="")
                print()
                ctl.stop(wait=True)
        self.assertEqual(ctl.errors, [])
        n1, n2, n3 = (ctl.history.node(n) for n in nodes)
        print(f"  sessions: {n1.agent_session_id} {n2.agent_session_id} {n3.agent_session_id}; "
              f"uuids {n1.agent_message_uuid} {n2.agent_message_uuid}; starts {ctl.session_starts}")
        self.assertTrue(n1.agent_message_uuid and n2.agent_message_uuid)
        self.assertEqual(n2.agent_session_id, n1.agent_session_id)
        third = ctl.session_starts[-1]
        self.assertEqual((third["resume"], third["fork"], third["resume_at"]),
                         (n1.agent_session_id, True, n1.agent_message_uuid))
        self.assertNotEqual(n3.agent_session_id, n1.agent_session_id)
        script = ("import json, sys\n"
                  "from claude_agent_sdk import get_session_messages\n"
                  "msgs = get_session_messages(sys.argv[1], directory=sys.argv[2])\n"
                  "print(json.dumps([json.dumps(m.message, default=str) for m in msgs]))\n")
        out = subprocess.run([str(agent_python()), "-c", script, n3.agent_session_id, str(ctl.session.root)],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        text = "\n".join(json.loads(out.stdout.strip().splitlines()[-1]))
        self.assertIn("ALPHA", text)
        self.assertIn("CHARLIE", text)
        self.assertNotIn("BRAVO", text, "the fork stops at the first turn")
