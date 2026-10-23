# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.agent.fakes import FakeBlender, FakeError
from whittle.agent.connection import BridgeCallError, Connection
from whittle.agent.fake import CRASH_EXIT_CODE, FakeRunner


class FakeRunnerCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.blender = FakeBlender(responses={
            "exec": {"stdout": "ok\n", "error": None, "diff": {}, "notes": []},
            "render": {"path": "/tmp/r.png", "strokes_path": "/tmp/s.png", "width": 8, "height": 8},
            "ask": {"answer": "yes"},
            "inspect": FakeError("not_found", "missing"),
        })
        port = await self.blender.start()
        self.conn = await Connection.open(port, "secret", "fake", timeout=2)
        self.serve = asyncio.create_task(self.conn.serve())
        self.exits = []

    async def asyncTearDown(self):
        self.serve.cancel()
        await self.conn.close()
        await self.blender.stop()

    def tmp(self) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="whittle-fake-"))
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def runner(self, turns, **extra):
        path = self.tmp() / "script.json"
        path.write_text(json.dumps({"turns": turns, **extra}))
        return FakeRunner(self.conn, path, exit=self.exits.append)

    async def finished(self):
        return (await self.blender.wait_event("turn_finished"))["data"]


class FakeRunnerTest(FakeRunnerCase):
    async def test_steps_make_calls_and_events(self):
        runner = self.runner([{"steps": [
            {"say": "hello"},
            {"call": "exec", "params": {"code": "x"}, "expect": "ok"},
            {"call": "render", "params": {"view": 1, "mode": "overlay"}},
            {"ask": "Sure?", "choices": ["yes"]},
            {"call": "inspect", "params": {"query": "object"}, "expect": "error:not_found"},
        ], "finish": {"result": "done"}}])
        with self.assertRaises(BridgeCallError):
            await runner.submit("n0001", "/b", "p")
        await runner.start_session({"session_dir": "/s"})
        await runner.submit("n0001", "/b", "p")
        with self.assertRaises(BridgeCallError) as cm:
            await runner.submit("n0002", "/b", "p")
        self.assertEqual(cm.exception.code, "busy")
        data = await self.finished()
        self.assertEqual(data["errors"], [])
        self.assertEqual((data["result_text"], data["interrupted"]), ("done", False))
        self.assertRegex(data["session_id"], r"^fake-[0-9a-f]{8}$")
        self.assertRegex(data["message_uuid"], r"^fake-msg-[0-9a-f]{8}$")
        self.assertEqual([m for m, _ in self.blender.calls], ["exec", "render", "ask", "inspect"])
        self.assertEqual(self.blender.calls[2][1], {"question": "Sure?", "choices": ["yes"]})
        results = [e["data"] for e in self.blender.events if e["name"] == "tool_result"]
        self.assertEqual(results[1]["images"], ["/tmp/r.png", "/tmp/s.png"])
        self.assertTrue(results[3]["is_error"])
        names = self.blender.event_names()
        self.assertEqual(names[names.index("turn_started") + 2], "text")
        await asyncio.sleep(0.05)
        self.assertIsNone(runner.turn_id)

    async def test_if_views_follows_the_request(self):
        """A script that checks against the sketch does so only when the
        request has sketch views; a prompt-only request takes the else steps."""
        steps = [{"if_views": [{"call": "render", "params": {"view": "first", "mode": "overlay"}}],
                  "else": [{"say": "no sketch"}]}]
        runner = self.runner([{"steps": steps}, {"steps": steps}])
        await runner.start_session({})
        folder = self.tmp()
        (folder / "request.json").write_text(json.dumps({"views": []}))
        await runner.submit("n0001", str(folder), "p")
        self.assertEqual((await self.finished())["errors"], [])
        self.assertEqual(self.blender.calls, [])
        self.assertIn("no sketch", [e["data"].get("text") for e in self.blender.events if e["name"] == "text"])
        self.blender.events.clear()
        await asyncio.sleep(0.05)
        (folder / "request.json").write_text(json.dumps({"views": [4, 2]}))
        await runner.submit("n0002", str(folder), "p")
        await self.finished()
        self.assertEqual(self.blender.calls, [("render", {"view": 2, "mode": "overlay"})])

    async def test_expect_mismatch_reports_an_error(self):
        runner = self.runner([{"steps": [{"call": "inspect", "params": {}, "expect": "ok"}]}])
        await runner.start_session({})
        await runner.submit("n0001", "/b", "")
        error = (await self.blender.wait_event("error"))["data"]
        self.assertEqual(error["code"], "expect_failed")
        self.assertEqual(len((await self.finished())["errors"]), 1)

    async def test_interrupt_stops_after_the_current_step(self):
        runner = self.runner([{"steps": [{"sleep": 0.2}, {"say": "too late"}]}])
        await runner.start_session({})
        await runner.submit("n0001", "/b", "")
        await asyncio.sleep(0.05)
        await runner.interrupt("n0001")
        data = await self.finished()
        self.assertTrue(data["interrupted"])
        self.assertNotIn("text", self.blender.event_names())

    async def test_delay_holds_an_announced_call(self):
        """A delayed call is announced at once and made only after the delay,
        or as soon as the turn is interrupted."""
        runner = self.runner([{"steps": [{"call": "exec", "params": {"code": "x"}, "delay": 30}]}])
        await runner.start_session({})
        await runner.submit("n0001", "/b", "")
        await self.blender.wait_event("tool_use")
        await asyncio.sleep(0.1)
        self.assertEqual(self.blender.calls, [])
        await runner.interrupt("n0001")
        data = await asyncio.wait_for(self.finished(), 5)
        self.assertTrue(data["interrupted"])
        self.assertEqual([m for m, _ in self.blender.calls], ["exec"])

    async def test_out_of_turns_finishes_with_an_error(self):
        runner = self.runner([])
        await runner.start_session({})
        await runner.submit("n0001", "/b", "")
        data = await self.finished()
        self.assertTrue(data["is_error"])

    async def test_fail_exits_with_code_3(self):
        runner = self.runner([{"steps": [{"fail": "boom"}, {"say": "never"}]}])
        await runner.start_session({})
        with self.assertLogs("whittle.agent", "ERROR"):
            await runner.submit("n0001", "/b", "")
            for _ in range(100):
                if self.exits:
                    break
                await asyncio.sleep(0.01)
        self.assertEqual(self.exits[0], CRASH_EXIT_CODE)
        await runner.close()

    async def started(self, turns, bundle_dir="/b/nodes/n0001/request"):
        runner = self.runner(turns)
        await runner.start_session({})
        await runner.submit("n0001", bundle_dir, "")
        await self.blender.wait_event("turn_started")
        return runner

    def delivered(self):
        return [(e["data"]["amend"], e["data"]["via"]) for e in self.blender.events
                if e["name"] == "amend_delivered"]

    async def test_amend_rides_on_the_next_call(self):
        runner = await self.started([{"steps": [{"wait_amend": 5}, {"call": "exec", "params": {"code": "x"}}]}])
        await runner.amend("n0001", "taller", "/b/nodes/n0001/amend-1", 1)
        data = await self.finished()
        result = next(e["data"] for e in self.blender.events if e["name"] == "tool_result")
        self.assertIn("<user_amendment>\nUser amendment 1: taller\nNew strokes: call mcp__whittle__request "
                      "with amend=1 to see them.\n</user_amendment>", result["summary"])
        self.assertEqual(self.delivered(), [(1, "tool_result")])
        self.assertEqual((data["errors"], data["amends_undelivered"]), ([], []))

    async def test_amend_at_the_end_is_delivered_by_query(self):
        runner = await self.started([{"steps": [{"wait_amend": 5}],
                                      "after_amend": [{"say": "Folded in."}]}])
        await runner.amend("n0001", "a handle", None, 1)
        data = await self.finished()
        self.assertEqual(self.delivered(), [(1, "query")])
        texts = [e["data"]["text"] for e in self.blender.events if e["name"] == "text"]
        self.assertEqual(texts, ["Folded in."])
        self.assertEqual((data["errors"], data["amends_undelivered"]), ([], []))

    async def test_default_after_amend_says_the_text(self):
        runner = await self.started([{"steps": [{"wait_amend": 5}]}])
        await runner.amend("n0001", "a handle", None, 1)
        await self.finished()
        texts = [e["data"]["text"] for e in self.blender.events if e["name"] == "text"]
        self.assertEqual(texts, ["Amendment received: a handle"])

    async def test_interrupt_leaves_amendments_undelivered(self):
        runner = await self.started([{"steps": [{"wait_amend": 5}, {"sleep": 20}, {"say": "never"}]}])
        await runner.amend("n0001", "taller", None, 1)
        await asyncio.sleep(0.05)
        start = asyncio.get_running_loop().time()
        await runner.interrupt("n0001")
        data = await self.finished()
        self.assertLess(asyncio.get_running_loop().time() - start, 1.0, "the sleep is cut short")
        self.assertTrue(data["interrupted"])
        self.assertEqual(data["amends_undelivered"], [1])
        self.assertEqual(self.delivered(), [])
        self.assertNotIn("text", self.blender.event_names())

    async def test_amend_checks_the_turn(self):
        runner = self.runner([{"steps": []}])
        with self.assertRaises(BridgeCallError) as cm:
            await runner.amend("n0001", "x", None, 1)
        self.assertEqual(cm.exception.code, "no_session")
        await runner.start_session({})
        with self.assertRaises(BridgeCallError) as cm:
            await runner.amend("n0001", "x", None, 1)
        self.assertEqual(cm.exception.code, "not_found")
        await runner.submit("n0001", "/b", "")
        await self.finished()
        with self.assertRaises(BridgeCallError) as cm:
            await runner.amend("n0001", "x", None, 1)
        self.assertEqual(cm.exception.code, "not_found")

    async def test_wait_amend_times_out_as_an_error(self):
        await self.started([{"steps": [{"wait_amend": 0.05}]}])
        data = await self.finished()
        self.assertEqual(len(data["errors"]), 1)
        self.assertIn("no amendment", data["errors"][0])

    async def test_read_amend_reads_the_bundle(self):
        root = self.tmp()
        crate = Path(__file__).resolve().parents[1] / "fixtures" / "crate" / "request"
        shutil.copytree(crate, root / "n0001" / "amend-1")
        runner = await self.started([{"steps": [{"read_amend": 1}, {"read_amend": 2}]}],
                                    bundle_dir=str(root / "n0001" / "request"))
        data = await self.finished()
        texts = [e["data"]["text"] for e in self.blender.events if e["name"] == "text"]
        self.assertEqual(texts, ["amend 1: 3 strokes, views [1, 2]"])
        self.assertEqual(len(data["errors"]), 1, "amendment 2 has no bundle")
        self.assertIsNone(runner.turn_id)


class FakeSessionTest(FakeRunnerCase):
    async def turn_session(self, runner, turn_id):
        await runner.submit(turn_id, "/b", "", ("note one",))
        data = (await self.blender.wait_event("turn_finished", where=lambda d: d["turn_id"] == turn_id))["data"]
        return data["session_id"]

    async def test_fresh_fork_and_resume_ids(self):
        runner = self.runner([{"steps": []}] * 4)
        await runner.start_session({})
        first = await self.turn_session(runner, "n0001")
        await runner.start_session({"resume": first, "fork": True, "resume_at": "u1"})
        forked = await self.turn_session(runner, "n0002")
        await runner.start_session({"resume": first, "fork": False})
        resumed = await self.turn_session(runner, "n0003")
        await runner.start_session({})
        fresh = await self.turn_session(runner, "n0004")
        self.assertEqual(resumed, first)
        self.assertEqual(len({first, forked, fresh}), 3)
        logs = [e["data"]["message"] for e in self.blender.events if e["name"] == "log"]
        self.assertIn(f"fake session {forked}: resume={first} fork=True resume_at=u1", logs)
        self.assertIn("context: note one", logs)

    async def test_the_store_gets_a_line_per_turn(self):
        store = self.tmp() / "sdk"
        runner = self.runner([{"steps": []}] * 2)
        await runner.start_session({"store_dir": str(store)})
        first = await self.turn_session(runner, "n0001")
        await runner.start_session({"resume": first, "fork": False, "store_dir": str(store)})
        await self.turn_session(runner, "n0002")
        lines = (store / f"{first}.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(line)["turn_id"] for line in lines], ["n0001", "n0002"])
        logs = [e["data"]["message"] for e in self.blender.events if e["name"] == "log"]
        self.assertIn(f"fake session {first}: resume={first} fork=False resume_at=None store={store} "
                      "stored_lines=1", logs)

    async def test_resume_fails(self):
        runner = self.runner([{"steps": []}], resume_fails=True)
        with self.assertRaises(BridgeCallError) as cm:
            await runner.start_session({"resume": "fake-0000"})
        self.assertEqual(cm.exception.code, "internal")
        with self.assertRaises(BridgeCallError):
            await runner.submit("n0001", "/b", "")
        await runner.start_session({})
        self.assertRegex(await self.turn_session(runner, "n0001"), r"^fake-")


class FakeModelTest(FakeRunnerCase):
    async def test_models_and_model_switches(self):
        runner = self.runner([{"steps": [], "finish": {}}, {"steps": [], "finish": {}}],
                             models={"models": ["claude-opus-5-5", "claude-opus-4-6"], "source": "api"})
        await runner.start_session({"session_dir": "/s", "model": "claude-opus-5-5"})
        models = (await self.blender.wait_event("models"))["data"]
        self.assertEqual((models["models"], models["source"]), (["claude-opus-5-5", "claude-opus-4-6"], "api"))
        await runner.submit("n0001", "/b", "p", model="claude-opus-5-5")
        await self.finished()
        await runner.submit("n0002", "/b", "p", model="claude-opus-4-6")
        await self.blender.wait_event("turn_finished", where=lambda d: d["turn_id"] == "n0002")
        logs = [e["data"]["message"] for e in self.blender.events if e["name"] == "log"]
        self.assertIn("session model: claude-opus-5-5", logs)
        self.assertEqual([m for m in logs if m.startswith("model:")], ["model: claude-opus-4-6"])
        self.assertEqual(runner.model, "claude-opus-4-6")
        await runner.start_session({"session_dir": "/s", "model": "claude-opus-5-5"})
        self.assertEqual(self.blender.event_names().count("models"), 1, "reported once per process")
