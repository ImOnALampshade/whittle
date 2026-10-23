# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import base64
import io
import json
import os
import unittest
from unittest import mock

from claude_agent_sdk import (AssistantMessage, RateLimitEvent, SystemMessage, TextBlock, ThinkingBlock,
                              ToolResultBlock, ToolUseBlock, UserMessage)
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

from tests.agent.fakes import FakeSdkClient, StubConnection, init_message, result_message
from whittle.agent import prompt, runner
from whittle.agent.connection import BridgeCallError
from whittle.agent.runner import SdkRunner, build_options, map_message, submit_text
from whittle.agent.tools import TOOL_NAMES, ToolContext, build_servers

PARAMS = {"session_dir": "/tmp/whittle-session", "model": "claude-haiku-5-5", "resume": None,
          "fork": False, "settings": {"poly_budget": 777, "max_turns": 4, "max_budget_usd": 0.1}}


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        out.append((value & 0x7F) | (0x80 if value > 0x7F else 0))
        value >>= 7
        if not value:
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def signature(kind: str) -> str:
    """A thinking signature shaped as the CLI reads it: field 2, then 1, then
    8 holds the kind; other fields (a varint, a fixed64) around it."""
    meta = _varint(1 << 3) + _varint(300) + _field(8, kind.encode())
    inner = _field(1, meta) + _varint(3 << 3 | 1) + bytes(8)
    return base64.b64encode(_field(1, b"opaque") + _field(2, inner)).decode()
EXEC_DATA = {"stdout": "4\n", "error": None, "diff": {"added": [], "removed": [], "changed": []}, "notes": []}


def argv(options):
    transport = SubprocessCLITransport(prompt="unused", options=options)
    transport._cli_path = "/opt/claude"
    return transport._build_command()


def flag(cmd, name):
    return cmd[cmd.index(name) + 1]


class OptionsTest(unittest.TestCase):
    def test_cli_arguments(self):
        cmd = argv(build_options(PARAMS, build_servers(ToolContext(None)), inline_skills=False))
        self.assertEqual(flag(cmd, "--tools"), "Skill")
        allowed = flag(cmd, "--allowedTools").split(",")
        self.assertEqual(allowed[:len(TOOL_NAMES)], TOOL_NAMES)
        self.assertEqual(sorted(allowed[len(TOOL_NAMES):]),
                         sorted(f"Skill(whittle:{s})" for s in prompt.SKILLS))
        self.assertEqual(flag(cmd, "--permission-mode"), "dontAsk")
        self.assertEqual(flag(cmd, "--model"), "claude-haiku-5-5")
        self.assertEqual(flag(cmd, "--max-turns"), "4")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn("--setting-sources=", cmd)
        self.assertEqual(flag(cmd, "--plugin-dir"), str(prompt.PLUGIN_DIR))
        system = flag(cmd, "--system-prompt")
        self.assertIn("You are Whittle", system)
        self.assertIn("777 triangles", system)
        self.assertIn("whittle:boolean-carve", system)
        self.assertFalse([c for c in cmd if c.startswith("--resume")])
        self.assertNotIn("--effort", cmd, "no effort given, none set")

    def test_effort_and_thinking_display(self):
        options = build_options({**PARAMS, "effort": "medium"}, build_servers(ToolContext(None)),
                                inline_skills=False)
        cmd = argv(options)
        self.assertEqual(flag(cmd, "--effort"), "medium")
        # Left unset, the CLI requests display "updates" itself; an explicit
        # display would turn the mid-turn notes off.
        self.assertFalse([c for c in cmd if c.startswith(("--thinking", "--max-thinking-tokens"))])
        self.assertEqual(options.env["CLAUDE_CODE_THINKING_DISPLAY_UPDATES"], "1")

    def test_options(self):
        options = build_options({**PARAMS, "resume": "sess-0", "fork": True},
                                build_servers(ToolContext(None)), inline_skills=False)
        self.assertEqual(options.cwd, "/tmp/whittle-session")
        self.assertEqual(options.env["MCP_TOOL_TIMEOUT"], runner.MCP_TOOL_TIMEOUT_MS)
        self.assertTrue(options.env["CLAUDE_AGENT_SDK_CLIENT_APP"].startswith("whittle/"))
        self.assertEqual(options.max_budget_usd, 0.1)
        self.assertEqual((options.resume, options.fork_session), ("sess-0", True))
        self.assertEqual(set(options.mcp_servers), {"blender", "whittle"})
        cmd = argv(options)
        self.assertIn("--resume=sess-0", cmd)
        self.assertIn("--fork-session", cmd)
        self.assertFalse([c for c in cmd if c.startswith("--resume-session-at")])

    def test_branch_options(self):
        options = build_options({**PARAMS, "resume": "sess-0", "fork": True, "resume_at": "uuid-7"},
                                build_servers(ToolContext(None)), inline_skills=False)
        self.assertEqual((options.resume, options.fork_session, options.resume_session_at),
                         ("sess-0", True, "uuid-7"))
        cmd = argv(options)
        self.assertIn("--resume-session-at=uuid-7", cmd)
        self.assertIn("--fork-session", cmd)

    def test_inline_skills_mode(self):
        cmd = argv(build_options(PARAMS, build_servers(ToolContext(None)), inline_skills=True))
        self.assertEqual(flag(cmd, "--tools"), "")
        self.assertNotIn("--plugin-dir", cmd)
        self.assertEqual(flag(cmd, "--allowedTools").split(","), TOOL_NAMES)
        self.assertIn("## Recipe: lathe-profile", flag(cmd, "--system-prompt"))

    def test_submit_text(self):
        text = submit_text("Add a lid.", "/s/nodes/n0001/request")
        self.assertTrue(text.startswith("Add a lid."))
        self.assertIn("Request bundle: /s/nodes/n0001/request", text)
        self.assertIn("mcp__whittle__request", text)
        self.assertIn("interpret the sketch", submit_text("  ", "/b"))
        self.assertNotIn("<whittle_context>", text)
        self.assertNotIn("no sketch", text)
        self.assertNotIn("no sketch", submit_text("Add a lid.", "/b", sketch=(3, 2)))
        bare = submit_text("Add a lid.", "/b", sketch=(0, 0))
        self.assertIn("This request has no sketch: no strokes and no sketch views", bare)
        self.assertIn("cameras you place", bare)
        self.assertNotIn("interpret the sketch", submit_text("", "/b", sketch=(0, 0)))
        with_context = submit_text("Add a lid.", "/b", ("You are continuing from n0001.", "Second."))
        self.assertTrue(with_context.startswith("<whittle_context>\n- You are continuing from n0001.\n"
                                                "- Second.\n</whittle_context>\n\nAdd a lid."))


    def test_sketch_size(self):
        from tests.agent.test_tools import BUNDLE

        self.assertEqual(runner.sketch_size(str(BUNDLE)), (3, 2))
        self.assertIsNone(runner.sketch_size("/no/such/bundle"))


class MapMessageTest(unittest.TestCase):
    def test_init(self):
        (name, data), = map_message(init_message(), "n1")
        self.assertEqual((name, data["state"], data["turn_id"]), ("status", "running", "n1"))

    def test_assistant_blocks(self):
        msg = AssistantMessage(content=[TextBlock("plan"), ThinkingBlock("hmm", "sig"),
                                        ToolUseBlock("tu1", "mcp__blender__exec", {"code": "x"})], model="m")
        events = map_message(msg, "n1")
        self.assertEqual([e[0] for e in events], ["text", "thinking", "tool_use"])
        self.assertEqual(events[2][1]["tool"], "exec")
        self.assertEqual(events[2][1]["input"], {"code": "x"})

    def test_thinking_kind(self):
        self.assertEqual(runner.thinking_kind(signature("narration")), "narration")
        self.assertEqual(runner.thinking_kind(signature("summary")), "summary")
        for bad in ("", "sig", "!!not base64", base64.b64encode(b"\xff\xff\xff").decode(),
                    base64.b64encode(_field(2, b"\x0a\x7f")).decode()):
            self.assertIsNone(runner.thinking_kind(bad), bad)

    def test_progress_updates_are_text(self):
        msg = AssistantMessage(content=[
            ThinkingBlock("", signature("narration")),
            ThinkingBlock("  Carving the handle next.\n", signature("narration")),
            ThinkingBlock("Weighing a bevel.", signature("summary")),
            ThinkingBlock("Older model thinking.", "opaque-signature"),
            ToolUseBlock("tu1", "mcp__blender__exec", {"code": "x"})], model="m")
        events = map_message(msg, "n1")
        self.assertEqual([(n, d["text"]) for n, d in events[:4]],
                         [("thinking", ""), ("text", "Carving the handle next."),
                          ("thinking", "Weighing a bevel."), ("thinking", "Older model thinking.")])

    def test_tool_result(self):
        content = [{"type": "text", "text": "overlay\nimage: /r/001.png"}, {"type": "image", "data": "..."}]
        (name, data), = map_message(UserMessage(content=[ToolResultBlock("tu1", content, True)]), None)
        self.assertEqual(name, "tool_result")
        self.assertEqual((data["tool_use_id"], data["is_error"], data["images"]), ("tu1", True, ["/r/001.png"]))
        (_, data), = map_message(UserMessage(content=[ToolResultBlock("tu2", "plain", None)]), None)
        self.assertEqual((data["summary"], data["is_error"]), ("plain", False))

    def test_other_messages(self):
        self.assertEqual(map_message(result_message(), "n1"), [])
        self.assertEqual(map_message(UserMessage(content="hi"), "n1"), [])
        (name, data), = map_message(SystemMessage(subtype="compact_boundary", data={}), "n1")
        self.assertEqual((name, data["level"]), ("log", "debug"))
        event = RateLimitEvent.__new__(RateLimitEvent)
        self.assertEqual(map_message(event, "n1")[0][0], "log")


class RunnerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeSdkClient.instances.clear()
        FakeSdkClient.server_info = None
        self.conn = StubConnection({"exec": EXEC_DATA})
        self.scripts = []

    def make_runner(self, *turns, inline_skills=False):
        self.scripts.append(list(turns))

        def factory(options):
            return FakeSdkClient(options=options, script=self.scripts.pop(0) if self.scripts else [])

        return SdkRunner(self.conn, client_factory=factory, inline_skills=inline_skills)

    def events(self, name=None):
        return [(n, d) for n, d in self.conn.events if name is None or n == name]

    async def wait_for(self, name, count=1, timeout=5.0):
        for _ in range(int(timeout / 0.01)):
            found = self.events(name)
            if len(found) >= count:
                return found[count - 1][1]
            await asyncio.sleep(0.01)
        raise AssertionError(f"no {name} event; got {[n for n, _ in self.conn.events]}")


class SdkRunnerTest(RunnerTestCase):
    async def test_full_turn(self):
        turn = [
            init_message(),
            AssistantMessage(content=[TextBlock("Plan: add a lid.")], model="m"),
            ("tool", "mcp__blender__exec", {"code": "print(2 + 2)", "label": "probe"}, "tu1"),
            AssistantMessage(content=[TextBlock("Done.")], model="m"),
            result_message(session_id="sess-9", total_cost_usd=0.02, num_turns=3),
        ]
        r = self.make_runner(turn)
        await r.start_session(PARAMS)
        await r.submit("n0001", "/bundle", "Add a lid")
        finished = await self.wait_for("turn_finished")
        self.assertEqual(finished["session_id"], "sess-9")
        self.assertEqual(finished["cost_usd"], 0.02)
        self.assertFalse(finished["is_error"])
        self.assertFalse(finished["interrupted"])
        self.assertEqual(finished["turn_id"], "n0001")
        names = [n for n, _ in self.conn.events]
        start = names.index("turn_started")
        self.assertEqual(names[start:], ["turn_started", "status", "log", "status", "text", "tool_use",
                                         "tool_result", "text", "log", "turn_finished", "status"])
        tool_use = self.events("tool_use")[0][1]
        self.assertEqual((tool_use["tool"], tool_use["tool_use_id"]), ("exec", "tu1"))
        self.assertIn("stdout:\n4", self.events("tool_result")[0][1]["summary"])
        self.assertEqual(self.conn.calls[0][:2], ("exec", {"code": "print(2 + 2)", "label": "probe"}))
        client = FakeSdkClient.instances[0]
        self.assertIn("Request bundle: /bundle", client.queries[0])
        self.assertIsNone(r.turn_id)
        self.assertEqual(r.session_id, "sess-9")
        await r.close()
        self.assertTrue(client.disconnected)
        self.assertEqual(client.task_violations, [])

    async def test_progress_updates_reach_the_stream_as_text(self):
        turn = [
            init_message(),
            AssistantMessage(content=[ThinkingBlock("", signature("summary")),
                                      ThinkingBlock("Adding the lid first.", signature("narration"))], model="m"),
            ("tool", "mcp__blender__exec", {"code": "print(2 + 2)", "label": "probe"}, "tu1"),
            AssistantMessage(content=[TextBlock("Done.")], model="m"),
            result_message(),
        ]
        r = self.make_runner(turn)
        await r.start_session(PARAMS)
        await r.submit("n0001", "/bundle", "Add a lid")
        await self.wait_for("turn_finished")
        said = [(n, d["text"]) for n, d in self.conn.events if n in ("text", "thinking")]
        self.assertEqual(said, [("thinking", ""), ("text", "Adding the lid first."), ("text", "Done.")])
        await r.close()

    async def test_message_uuid_is_the_turns_last_message(self):
        first = [init_message(),
                 AssistantMessage(content=[TextBlock("Plan.")], model="m", uuid="a-1"),
                 UserMessage(content=[ToolResultBlock("tu1", "ok", None)], uuid="u-2"),
                 AssistantMessage(content=[TextBlock("Done.")], model="m", uuid="a-3"),
                 result_message()]
        second = [result_message()]
        r = self.make_runner(first, second)
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "", ("Context line.",))
        finished = await self.wait_for("turn_finished")
        self.assertEqual(finished["message_uuid"], "a-3")
        self.assertTrue(FakeSdkClient.instances[0].queries[0].startswith(
            "<whittle_context>\n- Context line.\n</whittle_context>\n\n"))
        await r.submit("n0002", "/b", "")
        finished = await self.wait_for("turn_finished", 2)
        self.assertIsNone(finished["message_uuid"], "a turn without messages has none")
        await r.close()

    async def test_busy_and_no_session(self):
        r = self.make_runner([init_message()])
        with self.assertRaises(BridgeCallError) as cm:
            await r.submit("n0001", "/b", "")
        self.assertEqual(cm.exception.code, "no_session")
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "")
        with self.assertRaises(BridgeCallError) as cm:
            await r.submit("n0002", "/b", "")
        self.assertEqual(cm.exception.code, "busy")
        await r.close()
        finished = await self.wait_for("turn_finished")
        self.assertTrue(finished["is_error"])

    async def test_interrupt(self):
        turn = [init_message(), ("wait_interrupt",),
                AssistantMessage(content=[TextBlock("never said")], model="m")]
        r = self.make_runner(turn)
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "")
        await self.wait_for("status", 4)
        await r.interrupt("n0002")
        await r.interrupt("n0001")
        finished = await self.wait_for("turn_finished")
        self.assertTrue(finished["interrupted"])
        self.assertEqual(FakeSdkClient.instances[0].interrupts, 1)
        self.assertNotIn("never said", [d.get("text") for _, d in self.events("text")])
        await r.close()

    async def test_restarting_a_session_closes_the_first_client(self):
        r = self.make_runner([init_message(), result_message()])
        self.scripts.append([[init_message(session_id="sess-2"), result_message(session_id="sess-2")]])
        await r.start_session(PARAMS)
        await r.start_session({**PARAMS, "resume": "sess-1", "fork": True})
        first, second = FakeSdkClient.instances
        self.assertTrue(first.disconnected)
        self.assertFalse(second.disconnected)
        self.assertEqual(second.options.resume, "sess-1")
        await r.submit("n0002", "/b", "")
        finished = await self.wait_for("turn_finished")
        self.assertEqual(finished["session_id"], "sess-2")
        await r.close()
        self.assertEqual(first.task_violations + second.task_violations, [])

    async def test_missing_plugin_skills_are_reported(self):
        r = self.make_runner([init_message(skills=["other:thing"]), result_message()])
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "")
        await self.wait_for("turn_finished")
        warnings = [d for _, d in self.events("log") if d["level"] == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("WHITTLE_INLINE_SKILLS", warnings[0]["message"])
        await r.close()

    async def test_inline_mode_does_not_warn(self):
        r = self.make_runner([init_message(skills=[]), result_message()], inline_skills=True)
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "")
        await self.wait_for("turn_finished")
        self.assertEqual([d for _, d in self.events("log") if d["level"] == "warning"], [])
        await r.close()

    async def test_stream_ending_mid_turn_fails_the_turn(self):
        r = self.make_runner([init_message(), None])
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "")
        finished = await self.wait_for("turn_finished")
        self.assertTrue(finished["is_error"])
        self.assertIn("the agent CLI stopped", finished["errors"])
        for _ in range(500):
            if any(d["state"] == "session_ended" for _, d in self.events("status")):
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("no session_ended status")
        with self.assertRaises(BridgeCallError) as cm:
            await r.submit("n0002", "/b", "")
        self.assertEqual(cm.exception.code, "no_session")
        await r.close()

    async def test_submit_while_the_ended_session_disconnects_is_refused(self):
        release = asyncio.Event()

        class SlowDisconnect(FakeSdkClient):
            async def disconnect(self):
                await release.wait()
                await super().disconnect()

        r = SdkRunner(self.conn, inline_skills=False,
                      client_factory=lambda options: SlowDisconnect(
                          options=options, script=[[init_message(), None]]))
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "")
        for _ in range(500):
            if any(d["state"] == "session_ended" for _, d in self.events("status")):
                break
            await asyncio.sleep(0)
        else:
            self.fail("no session_ended status")
        self.assertFalse(r._task.done(), "the session task is still disconnecting")
        with self.assertRaises(BridgeCallError) as cm:
            await r.submit("n0002", "/b", "")
        self.assertEqual(cm.exception.code, "no_session")
        self.assertIsNone(r.turn_id)
        release.set()
        await r.close()

    async def test_query_queued_behind_the_stop_finishes_its_turn(self):
        r = self.make_runner([init_message()])
        await r.start_session(PARAMS)
        r._commands.put_nowait(("stop", None))
        await r.submit("n0001", "/b", "")
        finished = await self.wait_for("turn_finished")
        self.assertTrue(finished["is_error"])
        self.assertEqual(finished["turn_id"], "n0001")
        self.assertIsNone(r.turn_id)
        await r.close()

    async def test_connect_failure(self):
        def factory(options):
            client = FakeSdkClient(options=options)
            client.connect_error = RuntimeError("no CLI")
            return client

        r = SdkRunner(self.conn, client_factory=factory, inline_skills=False)
        with self.assertLogs("whittle.agent", "ERROR"):
            with self.assertRaises(BridgeCallError) as cm:
                await r.start_session(PARAMS)
        self.assertIn("no CLI", cm.exception.message)
        self.assertEqual(self.events("error")[0][1]["code"], "connect_failed")


class AmendTest(RunnerTestCase):
    async def started(self, r):
        await r.start_session(PARAMS)
        await r.submit("n0001", "/s/nodes/n0001/request", "Add a lid")
        await self.wait_for("status", 3)
        return FakeSdkClient.instances[-1]

    async def test_amend_rides_on_the_next_tool_result(self):
        turn = [init_message(), ("wait", "g"),
                ("tool", "mcp__blender__exec", {"code": "print(2 + 2)"}, "tu1"), result_message()]
        r = self.make_runner(turn)
        client = await self.started(r)
        await r.amend("n0001", "Make it taller", "/s/nodes/n0001/amend-1", 1)
        client.gate("g").set()
        finished = await self.wait_for("turn_finished")
        last = client.tool_results[0]["content"][-1]["text"]
        self.assertTrue(last.startswith("<user_amendment>\nUser amendment 1: Make it taller\n"), last)
        self.assertTrue(last.endswith("</user_amendment>"), last)
        self.assertIn("mcp__whittle__request with amend=1", last)
        self.assertIn("User amendment 1", self.events("tool_result")[0][1]["summary"])
        delivered = self.events("amend_delivered")
        self.assertEqual([(d["amend"], d["via"], d["turn_id"]) for _, d in delivered],
                         [(1, "tool_result", "n0001")])
        self.assertEqual(len(client.queries), 1)
        self.assertEqual(finished["amends_undelivered"], [])
        await r.close()

    async def test_amend_after_the_result_sends_a_follow_up_query(self):
        turn = [init_message(), ("tool", "mcp__blender__exec", {"code": "x"}, "tu1"), ("wait", "g"),
                result_message(num_turns=2, total_cost_usd=0.01, duration_ms=10)]
        follow_up = [AssistantMessage(content=[TextBlock("Folded in.")], model="m"),
                     result_message(num_turns=1, total_cost_usd=0.03, duration_ms=5, session_id="sess-2")]
        r = self.make_runner(turn, follow_up)
        client = await self.started(r)
        await self.wait_for("tool_result")
        await r.amend("n0001", "Also a handle", None, 1)
        client.gate("g").set()
        finished = await self.wait_for("turn_finished")
        self.assertEqual(len(client.queries), 2)
        self.assertIn("User amendment 1: Also a handle", client.queries[1])
        self.assertNotIn("amend=1", client.queries[1], "a text-only amendment has no strokes to read")
        self.assertIn("Fold this into the current turn", client.queries[1])
        self.assertIn("Folded in.", [d["text"] for _, d in self.events("text")])
        self.assertEqual([(d["amend"], d["via"]) for _, d in self.events("amend_delivered")], [(1, "query")])
        self.assertEqual((finished["num_turns"], finished["duration_ms"]), (3, 15))
        self.assertEqual(finished["session_id"], "sess-2")
        self.assertAlmostEqual(finished["cost_usd"], 0.03)
        self.assertEqual(len(self.events("turn_finished")), 1)
        self.assertFalse(finished["is_error"])
        await r.close()

    async def test_amend_for_another_turn_is_not_found(self):
        r = self.make_runner([init_message(), result_message()])
        with self.assertRaises(BridgeCallError) as cm:
            await r.amend("n0001", "x", None, 1)
        self.assertEqual(cm.exception.code, "no_session")
        await r.start_session(PARAMS)
        with self.assertRaises(BridgeCallError) as cm:
            await r.amend("n0001", "x", None, 1)
        self.assertEqual(cm.exception.code, "not_found")
        await r.submit("n0001", "/b", "")
        await self.wait_for("turn_finished")
        for turn_id in ("n0001", "n0002"):
            with self.assertRaises(BridgeCallError) as cm:
                await r.amend(turn_id, "x", None, 1)
            self.assertEqual(cm.exception.code, "not_found")
        await r.close()

    async def test_interrupt_reports_undelivered_amendments(self):
        turn = [init_message(), ("wait_interrupt",),
                AssistantMessage(content=[TextBlock("never said")], model="m")]
        r = self.make_runner(turn)
        client = await self.started(r)
        await r.amend("n0001", "taller", "/s/nodes/n0001/amend-1", 1)
        await r.interrupt("n0001")
        finished = await self.wait_for("turn_finished")
        self.assertTrue(finished["interrupted"])
        self.assertEqual(finished["amends_undelivered"], [1])
        self.assertEqual(len(client.queries), 1)
        self.assertEqual(self.events("amend_delivered"), [])
        await r.close()

    async def test_turn_cost_is_the_growth_of_the_session_total(self):
        r = self.make_runner([init_message(), result_message(total_cost_usd=0.02)],
                             [result_message(total_cost_usd=0.05)])
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "")
        first = await self.wait_for("turn_finished")
        await r.submit("n0002", "/b", "")
        second = await self.wait_for("turn_finished", 2)
        self.assertAlmostEqual(first["cost_usd"], 0.02)
        self.assertAlmostEqual(second["cost_usd"], 0.03)
        self.assertAlmostEqual(second["session_cost_usd"], 0.05)
        await r.close()


SERVER_INFO = {"models": [
    {"value": "default", "resolvedModel": "claude-opus-5-5", "displayName": "Default"},
    {"value": "sonnet", "resolvedModel": "claude-sonnet-5-5", "displayName": "Sonnet"},
    {"value": "claude-haiku-5-5", "displayName": "Haiku"},
    {"value": "fable", "resolvedModel": "claude-fable-5-1", "disabled": True},
]}


class ModelTest(RunnerTestCase):
    """The chat's model per submit, and the models the account offers."""

    async def test_a_submit_on_another_model_switches_the_session_first(self):
        r = self.make_runner([init_message(), result_message()], [result_message()], [result_message()])
        await r.start_session(PARAMS)
        await r.submit("n0001", "/b", "one", model="claude-haiku-5-5")
        await self.wait_for("turn_finished")
        await r.submit("n0002", "/b", "two", model="claude-sonnet-5-5")
        await self.wait_for("turn_finished", 2)
        await r.submit("n0003", "/b", "three")
        await self.wait_for("turn_finished", 3)
        client = FakeSdkClient.instances[0]
        self.assertEqual([kind for kind, _ in client.log], ["query", "set_model", "query", "query"],
                         "the session's own model needs no switch, nor does a submit without one")
        self.assertEqual(client.log[1], ("set_model", "claude-sonnet-5-5"))
        self.assertEqual(r.model, "claude-sonnet-5-5")
        self.assertEqual(len(FakeSdkClient.instances), 1, "the session and its conversation stay")
        await r.close()

    async def test_a_submit_at_another_effort_switches_the_live_session(self):
        r = self.make_runner([init_message(), result_message()], [result_message()], [result_message()])
        await r.start_session({**PARAMS, "effort": "high"})
        self.assertEqual(flag(argv(FakeSdkClient.instances[0].options), "--effort"), "high")
        await r.submit("n0001", "/b", "one", effort="high")
        await self.wait_for("turn_finished")
        await r.submit("n0002", "/b", "two", model="claude-sonnet-5-5", effort="low")
        await self.wait_for("turn_finished", 2)
        await r.submit("n0003", "/b", "three")
        await self.wait_for("turn_finished", 3)
        client = FakeSdkClient.instances[0]
        self.assertEqual([kind for kind, _ in client.log],
                         ["query", "set_model", "apply_flag_settings", "query", "query"],
                         "the session's own effort needs no switch, nor does a submit without one")
        self.assertEqual(client.log[2][1], {"subtype": "apply_flag_settings", "settings": {"effortLevel": "low"}})
        self.assertEqual(r.effort, "low")
        self.assertIn("switched to effort low", [d["message"] for _, d in self.events("log")])
        self.assertEqual(len(FakeSdkClient.instances), 1, "the session and its conversation stay")
        await r.close()

    async def test_a_failed_effort_switch_fails_the_turn(self):
        class Refusing(FakeSdkClient):
            async def _send_control_request(self, request, timeout=60.0):
                raise RuntimeError("apply_flag_settings: unrecognized effortLevel")

        r = SdkRunner(self.conn, inline_skills=False,
                      client_factory=lambda options: Refusing(options=options, script=[[result_message()]]))
        await r.start_session({**PARAMS, "effort": "high"})
        with self.assertLogs("whittle.agent", "ERROR"):
            await r.submit("n0001", "/b", "one", effort="medium")
            finished = await self.wait_for("turn_finished")
        self.assertTrue(finished["is_error"])
        self.assertEqual(r.effort, "high", "the session runs on at the effort it had")
        await r.close()

    async def test_a_failed_switch_fails_the_turn(self):
        class Refusing(FakeSdkClient):
            async def set_model(self, model=None):
                raise RuntimeError("no such model")

        r = SdkRunner(self.conn, inline_skills=False,
                      client_factory=lambda options: Refusing(options=options, script=[[result_message()]]))
        await r.start_session(PARAMS)
        with self.assertLogs("whittle.agent", "ERROR"):
            await r.submit("n0001", "/b", "one", model="claude-nope")
            finished = await self.wait_for("turn_finished")
        self.assertTrue(finished["is_error"])
        self.assertIn("no such model", finished["errors"])
        self.assertEqual(r.model, PARAMS["model"])
        await r.close()

    async def models_event(self):
        for _ in range(500):
            found = self.events("models")
            if found:
                return found
            await asyncio.sleep(0.01)
        return []

    async def test_the_clis_models_stand_in_when_the_api_has_none(self):
        FakeSdkClient.server_info = SERVER_INFO
        r = self.make_runner([], [])
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            await r.start_session(PARAMS)
            (_, data), = await self.models_event()
            await r.start_session(PARAMS)
            await asyncio.sleep(0.05)
        self.assertEqual(data["models"], ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
                         "aliases resolve to ids; a disabled row is left out")
        self.assertEqual((data["source"], data["turn_id"]), ("cli", None))
        self.assertEqual(len(self.events("models")), 1)
        await r.close()

    async def test_the_models_apis_list_comes_first(self):
        FakeSdkClient.server_info = SERVER_INFO
        asked = []

        def list_models(key, base_url):
            asked.append((key, base_url))
            return [{"data": [{"id": "claude-opus-4-6"}, {"id": "claude-opus-5-5"}], "has_more": False}]

        r = SdkRunner(self.conn, inline_skills=False, list_models=list_models,
                      client_factory=lambda options: FakeSdkClient(options=options))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "ANTHROPIC_BASE_URL": "http://x"}):
            await r.start_session(PARAMS)
            (_, data), = await self.models_event()
        self.assertEqual(asked, [("sk-test", "http://x")])
        self.assertEqual(data["source"], "api")
        self.assertEqual(data["models"], ["claude-opus-4-6", "claude-opus-5-5"],
                         "the key's own list, without the CLI's")
        await r.close()

    async def test_nothing_to_report_sends_nothing(self):
        def failing(key, base_url):
            raise OSError("offline")

        r = SdkRunner(self.conn, inline_skills=False, list_models=failing,
                      client_factory=lambda options: FakeSdkClient(options=options))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with self.assertLogs("whittle.agent", "WARNING"):
                await r.start_session(PARAMS)
                await asyncio.sleep(0.05)
        self.assertEqual(self.events("models"), [])
        await r.close()

    def test_list_api_models_pages(self):
        pages = [{"data": [{"id": "a"}], "has_more": True, "last_id": "a"},
                 {"data": [{"id": "b"}], "has_more": False, "last_id": "b"}]
        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            return io.BytesIO(json.dumps(pages[len(requests) - 1]).encode())

        with mock.patch.object(runner.urllib.request, "urlopen", urlopen):
            found = runner.list_api_models("sk-test", "https://api.example/")
        self.assertEqual(found, pages)
        self.assertEqual([r.full_url for r in requests],
                         ["https://api.example/v1/models?limit=1000",
                          "https://api.example/v1/models?limit=1000&after_id=a"])
        self.assertEqual(requests[0].get_header("X-api-key"), "sk-test")
        self.assertEqual(requests[0].get_header("Anthropic-version"), "2023-06-01")
