# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path

from tests.agent.fakes import FakeBlender, FakeError
from whittle import protocol
from whittle.agent.connection import BridgeCallError, Connection, HandshakeError

REPO = Path(__file__).resolve().parents[2]


class ConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.blender = FakeBlender(responses={
            "exec": lambda p: {"echo": p["code"]},
            "inspect": FakeError("not_found", "no such object"),
        })
        self.port = await self.blender.start()

    async def asyncTearDown(self):
        await self.blender.stop()

    async def open(self, token="secret"):
        conn = await Connection.open(self.port, token, "fake", timeout=2)
        self.addAsyncCleanup(conn.close)
        return conn

    async def test_handshake_sends_token_protocol_and_mode(self):
        await self.open()
        hello = self.blender.hello
        self.assertEqual((hello["token"], hello["protocol"], hello["mode"]), ("secret", 1, "fake"))
        self.assertEqual(hello["pid"], os.getpid())

    async def test_wrong_token_is_a_handshake_error(self):
        with self.assertRaises(HandshakeError):
            await Connection.open(self.port, "wrong", "fake", timeout=2)

    async def test_bad_welcome_is_a_handshake_error(self):
        self.blender.welcome = {"v": 1, "type": "welcome", "protocol": 99}
        with self.assertRaises(HandshakeError):
            await Connection.open(self.port, "secret", "fake", timeout=2)

    async def test_no_listener_is_a_handshake_error(self):
        await self.blender.stop()
        with self.assertRaises(HandshakeError):
            await Connection.open(self.port, "secret", "fake", timeout=2)

    async def test_results_correlate_out_of_order(self):
        conn = await self.open()
        serve = asyncio.create_task(conn.serve())
        gate = self.blender.hold("exec")
        first = asyncio.create_task(conn.call("exec", {"code": "first"}))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(conn.call("exec", {"code": "second"}))
        self.assertEqual(await asyncio.wait_for(second, 2), {"echo": "second"})
        self.assertFalse(first.done())
        gate.set_result(None)
        self.assertEqual(await asyncio.wait_for(first, 2), {"echo": "first"})
        serve.cancel()

    async def test_error_result_raises(self):
        conn = await self.open()
        serve = asyncio.create_task(conn.serve())
        with self.assertRaises(BridgeCallError) as cm:
            await conn.call("inspect", {"query": "object"})
        self.assertEqual((cm.exception.code, cm.exception.message), ("not_found", "no such object"))
        serve.cancel()

    async def test_timeout(self):
        conn = await self.open()
        serve = asyncio.create_task(conn.serve())
        self.blender.hold("exec")
        with self.assertRaises(BridgeCallError) as cm:
            await conn.call("exec", {"code": "slow"}, timeout=0.1)
        self.assertEqual(cm.exception.code, protocol.ErrorCode.TIMEOUT)
        serve.cancel()

    async def test_eof_fails_pending_calls(self):
        conn = await self.open()
        serve = asyncio.create_task(conn.serve())
        self.blender.hold("exec")
        pending = asyncio.create_task(conn.call("exec", {"code": "x"}, timeout=None))
        await asyncio.sleep(0.05)
        await self.blender.stop()
        with self.assertRaises(BridgeCallError) as cm:
            await asyncio.wait_for(pending, 2)
        self.assertEqual(cm.exception.code, protocol.ErrorCode.AGENT_CRASHED)
        await asyncio.wait_for(serve, 2)
        self.assertTrue(conn.closed.is_set())

    async def test_incoming_calls_reach_the_handler(self):
        conn = await self.open()

        async def handler(method, params):
            if method == "boom":
                raise RuntimeError("kaput")
            if method == "nope":
                raise BridgeCallError("busy", "try later")
            return {"method": method, **params}

        conn.set_handler(handler)
        serve = asyncio.create_task(conn.serve())
        self.assertEqual(await self.blender.call("ping", {"a": 1}), (True, {"method": "ping", "a": 1}))
        with self.assertLogs("whittle.agent", "ERROR"):
            ok, error = await self.blender.call("boom")
        self.assertFalse(ok)
        self.assertEqual(error["code"], "internal")
        self.assertIn("kaput", error["detail"])
        self.assertEqual(await self.blender.call("nope"),
                         (False, {"code": "busy", "message": "try later", "detail": None}))
        serve.cancel()

    async def test_events_are_delivered(self):
        conn = await self.open()
        await conn.send_event("text", {"turn_id": "n1", "text": "hi"})
        ev = await self.blender.wait_event("text")
        self.assertEqual(ev["data"], {"turn_id": "n1", "text": "hi"})


class EntryPointTest(unittest.TestCase):
    def run_agent(self, *args, env=None, timeout=20):
        full_env = {**os.environ, "PYTHONPATH": str(REPO), **(env or {})}
        return subprocess.run([sys.executable, "-s", "-P", "-m", "whittle.agent", *args],
                              env=full_env, capture_output=True, text=True, timeout=timeout)

    def test_handshake_failure_exits_2(self):
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        result = self.run_agent("--port", str(port), "--fake", "x.json")
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_bad_arguments_exit_2(self):
        self.assertEqual(self.run_agent().returncode, 2)


class EntryPointServeTest(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_and_eof_exit_0(self):
        for how in ("shutdown", "eof"):
            with self.subTest(how=how):
                blender = FakeBlender()
                port = await blender.start()
                env = {**os.environ, "PYTHONPATH": str(REPO), "WHITTLE_TOKEN": "secret"}
                script = REPO / "tests" / "fixtures" / "fake" / "ping.json"
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-s", "-P", "-m", "whittle.agent", "--port", str(port),
                    "--fake", str(script), env=env,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                try:
                    await asyncio.wait_for(blender.handshaken.wait(), 10)
                    await asyncio.wait_for(blender.call("ping"), 5)
                    if how == "shutdown":
                        self.assertEqual(await blender.call("shutdown"), (True, {}))
                    else:
                        await blender.stop()
                    self.assertEqual(await asyncio.wait_for(proc.wait(), 10), 0)
                finally:
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
                    await blender.stop()
