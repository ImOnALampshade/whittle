# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import unittest

from whittle.agent.connection import BridgeCallError
from whittle.agent.dispatch import DEFAULT_MODEL, make_dispatcher


class RecordingRunner:
    def __init__(self):
        self.calls = []

    async def start_session(self, params):
        self.calls.append(("start_session", params))

    async def submit(self, turn_id, bundle_dir, prompt, context=(), model=None):
        self.calls.append(("submit", turn_id, bundle_dir, prompt, context, model))

    async def amend(self, turn_id, text, bundle_dir, number):
        self.calls.append(("amend", turn_id, text, bundle_dir, number))

    async def interrupt(self, turn_id):
        self.calls.append(("interrupt", turn_id))

    async def close(self):
        pass


class DispatchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runner = RecordingRunner()
        self.shutdown = asyncio.Event()
        self.dispatch = make_dispatcher(self.runner, self.shutdown)

    async def assertCode(self, code, method, params):
        with self.assertRaises(BridgeCallError) as cm:
            await self.dispatch(method, params)
        self.assertEqual(cm.exception.code, code)

    async def test_ping_and_shutdown(self):
        self.assertIn("time", await self.dispatch("ping", {}))
        self.assertFalse(self.shutdown.is_set())
        self.assertEqual(await self.dispatch("shutdown", {}), {})
        self.assertTrue(self.shutdown.is_set())

    async def test_unknown_method(self):
        await self.assertCode("unknown_method", "dance", {})

    async def test_start_session_defaults(self):
        await self.dispatch("start_session", {"session_dir": "/tmp/s"})
        (_, params), = self.runner.calls
        self.assertEqual(params, {"session_dir": "/tmp/s", "store_dir": None, "model": DEFAULT_MODEL,
                                  "resume": None, "fork": False, "resume_at": None, "settings": {}})
        await self.assertCode("bad_request", "start_session", {"session_dir": "/s", "store_dir": 3})

    async def test_start_session_branch(self):
        await self.dispatch("start_session", {"session_dir": "/s", "resume": "S", "fork": True,
                                              "resume_at": "u1"})
        (_, params), = self.runner.calls
        self.assertEqual((params["resume"], params["fork"], params["resume_at"]), ("S", True, "u1"))
        await self.assertCode("bad_request", "start_session", {"session_dir": "/s", "resume_at": 7})

    async def test_start_session_validation(self):
        await self.assertCode("bad_request", "start_session", {})
        await self.assertCode("bad_request", "start_session", {"session_dir": 3})
        await self.assertCode("bad_request", "start_session", {"session_dir": "/s", "fork": "yes"})
        await self.assertCode("bad_request", "start_session", {"session_dir": "/s", "settings": {"max_turns": "4"}})
        await self.assertCode("bad_request", "start_session",
                              {"session_dir": "/s", "settings": {"max_budget_usd": "cheap"}})

    async def test_submit(self):
        self.assertEqual(await self.dispatch("submit", {"turn_id": "n0001", "bundle_dir": "/b"}),
                         {"accepted": True})
        self.assertEqual(self.runner.calls, [("submit", "n0001", "/b", "", (), None)])
        await self.assertCode("bad_request", "submit", {"turn_id": "n0001"})

    async def test_submit_context(self):
        params = {"turn_id": "n0002", "bundle_dir": "/b", "context": ["one", "two"]}
        await self.dispatch("submit", params)
        self.assertEqual(self.runner.calls, [("submit", "n0002", "/b", "", ("one", "two"), None)])
        await self.assertCode("bad_request", "submit", {**params, "context": "one"})
        await self.assertCode("bad_request", "submit", {**params, "context": [1]})

    async def test_submit_model(self):
        params = {"turn_id": "n0003", "bundle_dir": "/b", "model": "claude-sonnet-5-5"}
        await self.dispatch("submit", params)
        await self.dispatch("submit", {**params, "model": None})
        self.assertEqual([c[-1] for c in self.runner.calls], ["claude-sonnet-5-5", None])
        await self.assertCode("bad_request", "submit", {**params, "model": 5})

    async def test_amend_and_interrupt(self):
        self.assertEqual(await self.dispatch("amend", {"turn_id": "n1", "text": "taller"}), {"queued": True})
        self.assertEqual(await self.dispatch("interrupt", {"turn_id": "n1"}), {})
        self.assertEqual(self.runner.calls, [("amend", "n1", "taller", None, None), ("interrupt", "n1")])

    async def test_amend_number_and_bundle(self):
        params = {"turn_id": "n1", "text": "", "bundle_dir": "/s/nodes/n1/amend-2", "amend": 2}
        self.assertEqual(await self.dispatch("amend", params), {"queued": True})
        self.assertEqual(self.runner.calls, [("amend", "n1", "", "/s/nodes/n1/amend-2", 2)])
        await self.assertCode("bad_request", "amend", {**params, "amend": "2"})
        await self.assertCode("bad_request", "amend", {**params, "amend": True})
        await self.assertCode("bad_request", "amend", {"turn_id": "n1"})
