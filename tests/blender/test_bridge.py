# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import bpy

from tests.blender.helpers import CRATE_BUNDLE, AgentTestCase, pump
from tests.fixtures.crate.scene import build_scene
from whittle import platforms
from whittle.addon import paths, process
from whittle.addon.bridge import Deferred
from whittle.addon.process import AgentState
from whittle.chats import project_key
from whittle.protocol import ErrorCode, Event, Method


def call_and_wait(test, ctl, method, params, timeout=10.0):
    box = {}
    ctl.bridge.call(method, params, lambda ok, data: box.update(ok=ok, data=data))
    pump(ctl, lambda: "ok" in box, timeout, f"the {method} result")
    return box["ok"], box["data"]


class HandshakeTest(AgentTestCase):
    def test_fake_agent_reaches_ready(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        self.assertEqual(ctl.process.hello["mode"], "fake")
        self.assertEqual(ctl.process.hello["pid"], ctl.process.popen.pid)
        self.assertIsNone(ctl.bridge.listener, "the listener closes after the handshake")

    def test_wrong_token_fails(self):
        ctl = self.make_controller(agent_token="0" * 64)
        ctl.start()
        pump(ctl, lambda: ctl.process.state != AgentState.STARTING, 15, "the handshake")
        self.assertEqual(ctl.process.state, AgentState.FAILED)
        self.assertIn("token", ctl.process.reason)

    def test_missing_python_needs_setup(self):
        ctl = self.make_controller(python=self.user_dir / "no-such-python")
        ctl.process.python = None
        ctl.start()
        self.assertEqual(ctl.process.state, AgentState.NEEDS_SETUP)

    def test_real_agent_refused_without_online_access(self):
        if bpy.app.online_access:
            self.skipTest("online access is enabled")
        ctl = self.make_controller(script=None)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            ctl.start()
        self.assertEqual(ctl.process.state, AgentState.FAILED)
        self.assertIn("Online Access", ctl.process.reason)

    def test_ping(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        ok, data = call_and_wait(self, ctl, Method.PING, {})
        self.assertTrue(ok)
        self.assertAlmostEqual(data["time"], time.time(), delta=5)

    def test_unknown_method_from_blender(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        ok, data = call_and_wait(self, ctl, "frobnicate", {})
        self.assertFalse(ok)
        self.assertEqual(data["code"], ErrorCode.UNKNOWN_METHOD)


class LifecycleTest(AgentTestCase):
    def test_stop_exits_cleanly(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        popen = ctl.process.popen
        self.assertIs(ctl.process.tree.popen, popen)
        ctl.stop()
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 8, "the agent to stop")
        self.assertEqual(popen.poll(), 0)
        self.assertIsNone(ctl.process.tree, "the process tree is let go with the process")

    @unittest.skipIf(sys.platform == "win32", "Windows uses a Job Object (tests/agent/test_platforms.py)")
    def test_the_agent_runs_in_its_own_process_group_and_stops_on_terminate(self):
        import os
        import signal

        ctl = self.make_controller()
        self.start_ready(ctl)
        popen = ctl.process.popen
        self.assertEqual(os.getpgid(popen.pid), popen.pid, "a kill reaches the CLI it runs too")
        popen.send_signal(signal.SIGTERM)
        self.assertEqual(popen.wait(timeout=10), 0, "a terminate closes the session cleanly")

    def test_stop_and_wait(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        popen = ctl.process.popen
        ctl.stop(wait=True)
        self.assertEqual(ctl.process.state, AgentState.STOPPED)
        self.assertEqual(popen.poll(), 0)

    def test_agent_exits_when_socket_closes(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        popen = ctl.process.popen
        ctl.bridge.sock.close()
        self.assertEqual(popen.wait(timeout=5), 0)

    def test_crash_fails_the_running_turn(self):
        build_scene()
        ctl = self.make_controller("crash.json")
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.process.state == AgentState.CRASHED, 15, "the crash")
        self.assertIn("code 3", ctl.process.reason)
        self.assertFalse(ctl.running)
        self.assertTrue(ctl.last_finished["is_error"])
        self.assertTrue(any("About to crash" in line for line in ctl.stream.lines()))
        self.assertTrue(any("scripted crash" in line for line in ctl.process.log_tail()))

    def test_crash_fails_pending_calls(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        ctl.process.popen.kill()
        ctl.process.popen.wait(timeout=5)
        results = []
        ctl.bridge.call(Method.PING, {}, lambda ok, data: results.append((ok, data)))
        pump(ctl, lambda: ctl.process.state == AgentState.CRASHED, 10, "the crash")
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0][0])
        self.assertEqual(results[0][1]["code"], ErrorCode.AGENT_CRASHED)


class ResumeFoldersTest(AgentTestCase):
    """A killed Windows agent leaves the SDK's claude-resume-* folder: the next
    start clears stale ones (the rules are tested in tests/agent/test_platforms.py)."""

    def test_start_clears_and_records_the_agent_and_its_exit_forgets_it(self):
        with mock.patch.object(process, "clear_resume_folders") as clear, \
                mock.patch.object(platforms, "note_agent") as note, \
                mock.patch.object(platforms, "forget_agent") as forget:
            ctl = self.make_controller()
            self.start_ready(ctl)
            pid = ctl.process.popen.pid
            ctl.stop(wait=True)
        clear.assert_called_once_with()
        self.assertEqual(note.call_args.args[:2], (paths.agents_dir(), pid))
        self.assertLessEqual(note.call_args.args[2], time.time())
        forget.assert_called_once_with(paths.agents_dir(), pid)

    def test_clears_whittles_stale_folders_on_windows_only(self):
        temp = self.user_dir / "temp"
        old = time.time() - 2 * platforms.RESUME_STALE_AFTER

        def resume_folder(name, cwd):
            folder = temp / name
            transcript = folder / "projects" / project_key(cwd) / "s.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text("{}\n")
            for path in (transcript, transcript.parent, transcript.parent.parent, folder):
                os.utime(path, (old, old))
            return folder

        stale = resume_folder("claude-resume-whittle", paths.cache_dir() / "f1" / "chats" / "c1")
        other = resume_folder("claude-resume-other", self.user_dir / "elsewhere")
        with mock.patch.object(process.tempfile, "gettempdir", return_value=str(temp)):
            self.assertEqual(process.clear_resume_folders(platform="linux"), [])
            self.assertTrue(stale.exists())
            self.assertEqual(process.clear_resume_folders(platform="win32"), [stale])
        self.assertFalse(stale.exists())
        self.assertTrue(other.exists(), "another program's folder stays")


class ModalTest(AgentTestCase):
    def test_scene_calls_wait_for_the_users_modal_operation(self):
        from whittle.addon import bridge as bridges

        ctl = self.make_controller()
        self.start_ready(ctl)
        with mock.patch.object(bridges, "modal_running", return_value=True):
            self.assertTrue(ctl.bridge._wait_for_modal(Method.EXEC))
            self.assertFalse(ctl.bridge._wait_for_modal(Method.INSPECT), "reading goes at once")
            with mock.patch.object(bridges, "MODAL_WAIT", 0.0):
                self.assertFalse(ctl.bridge._wait_for_modal(Method.EXEC), "never for ever")
        self.assertFalse(ctl.bridge._wait_for_modal(Method.EXEC))


class StopBeforeHelloTest(AgentTestCase):
    def test_stop_before_the_handshake_still_stops(self):
        build_scene()
        ctl = self.make_controller()
        ctl.run_bundle(CRATE_BUNDLE)
        self.assertEqual(ctl.process.state, AgentState.STARTING)
        popen = ctl.process.popen
        ctl.stop()
        self.assertIsNone(ctl._pending_run, "stopping drops the waiting run")
        pump(ctl, lambda: ctl.process.state == AgentState.STOPPED, 10, "the agent to stop")
        self.assertEqual(popen.wait(timeout=5), 0, "the agent exited on shutdown, not a kill")
        self.assertIsNone(ctl.turn_id)


class RunBundleStartFailureTest(AgentTestCase):
    def test_failed_start_reports_and_forgets_the_run(self):
        from unittest import mock

        from tests.blender.helpers import agent_python
        from whittle.addon import paths

        build_scene()
        ctl = self.make_controller(python=None)
        with mock.patch.object(paths, "agent_python", lambda: None):
            with self.assertRaisesRegex(RuntimeError, "agent environment is not set up"):
                ctl.run_bundle(CRATE_BUNDLE)
        self.assertEqual(ctl.process.state, AgentState.NEEDS_SETUP)
        self.assertIsNone(ctl._pending_run)

        # A later start for some other reason must not run the old bundle.
        ctl.process.python = agent_python()
        self.start_ready(ctl)
        for _ in range(20):
            ctl.bridge.tick()
            time.sleep(0.01)
        self.assertFalse(ctl.running)
        self.assertFalse(ctl.session_ready)


class BridgeRobustnessTest(AgentTestCase):
    def test_unencodable_result_becomes_an_internal_error(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        script = self.user_dir / "unencodable.json"
        script.write_text(json.dumps({"turns": [{"steps": [
            {"call": "inspect", "params": {"query": "summary"}, "expect": "error:internal"},
            {"call": "exec", "params": {"code": "import os\nprint(os.fsdecode(b'caf\\xe9.png'))",
                                        "label": "surrogate"}, "expect": "ok"}]}]}))
        ctl.stop(wait=True)
        build_scene()
        ctl = self.make_controller(script)
        ctl.process.handlers[Method.INSPECT] = lambda params: {"value": object()}
        with self.assertLogs("whittle", "ERROR"):
            ctl.run_bundle(CRATE_BUNDLE)
            pump(ctl, lambda: ctl.last_finished is not None, 20, "the turn to finish")
        self.assertEqual(ctl.last_finished["errors"], [])
        results = [e["data"] for e in ctl.events if e["name"] == Event.TOOL_RESULT]
        self.assertIn("cannot be encoded", results[0]["summary"])
        self.assertIn("caf", results[1]["summary"])
        self.assertEqual(ctl.process.state, AgentState.READY)

    def test_failing_event_callback_does_not_stop_the_bridge(self):
        build_scene()
        ctl = self.make_controller("exec_inspect_render.json")
        original = ctl.on_event
        failures = []

        def flaky(msg):
            if msg["name"] == Event.TEXT and not failures:
                failures.append(msg)
                raise OSError("disk full")
            original(msg)

        ctl.run_bundle(CRATE_BUNDLE)
        ctl.bridge.on_event = flaky
        with self.assertLogs("whittle", "ERROR"):
            pump(ctl, lambda: ctl.last_finished is not None, 30, "the turn to finish")
        self.assertEqual(len(failures), 1)
        self.assertFalse(ctl.last_finished["is_error"], ctl.last_finished)

    def test_timer_callback_crashes_the_agent_instead_of_dying(self):
        from whittle.addon import bridge as bridge_mod

        ctl = self.make_controller()
        self.start_ready(ctl)
        b = ctl.bridge

        def broken():
            raise TypeError("boom")

        b.tick = broken
        bridge_mod.start_timer(b)
        try:
            timer = bridge_mod._timer
            with self.assertLogs("whittle", "ERROR"):
                self.assertIsNone(timer())
        finally:
            bridge_mod.stop_timer()
        self.assertEqual(ctl.process.state, AgentState.CRASHED)
        self.assertIn("boom", ctl.process.reason)


class TurnTest(AgentTestCase):
    def setUp(self):
        super().setUp()
        build_scene()

    def run_turn(self, script, timeout=30.0, **kwargs):
        ctl = self.make_controller(script, **kwargs)
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, timeout, "the turn to finish")
        self.assertEqual(ctl.errors, [])
        return ctl

    def test_exec_inspect_render_end_to_end(self):
        ctl = self.run_turn("exec_inspect_render.json")
        finished = ctl.last_finished
        self.assertFalse(finished["is_error"], finished)
        self.assertEqual(finished["errors"], [])
        self.assertRegex(finished["session_id"], r"^fake-[0-9a-f]{8}$")
        self.assertIn("Crate_Lid", bpy.data.objects)

        names = [e["name"] for e in ctl.events]
        self.assertEqual(names[0], Event.STATUS)
        self.assertLess(names.index(Event.TURN_STARTED), names.index(Event.TOOL_USE))
        self.assertEqual(names[-2], Event.TURN_FINISHED)

        results = [e["data"] for e in ctl.events if e["name"] == Event.TOOL_RESULT]
        images = [p for r in results for p in r["images"]]
        self.assertEqual(len(images), 3, "overlay + strokes + shaded")
        for path in images:
            self.assertTrue(Path(path).is_file(), path)
        renders = ctl.session.renders_dir("n0001")
        self.assertEqual(sorted(p.name for p in renders.glob("*-overlay.png")), ["001-v1-overlay.png"])

        request = ctl.session.request_dir("n0001")
        self.assertTrue((request / "request.json").is_file())
        transcript = ctl.session.transcript_path("n0001").read_text().splitlines()
        self.assertEqual([json.loads(l)["name"] for l in transcript][-1], Event.TURN_FINISHED)

    def test_code_errors_are_results_not_bridge_errors(self):
        ctl = self.run_turn("bad_code.json")
        self.assertEqual(ctl.last_finished["errors"], [])
        results = [e["data"] for e in ctl.events if e["name"] == Event.TOOL_RESULT]
        self.assertTrue(results[0]["is_error"])
        self.assertIn("SyntaxError", results[0]["summary"])
        self.assertIn("ValueError", results[1]["summary"])

    def test_at_most_one_render_per_tick(self):
        ctl = self.make_controller("renders.json")
        render_ticks = []
        handler = ctl.process.handlers[Method.RENDER]

        def counting(params):
            render_ticks.append(ctl.bridge.ticks)
            return handler(params)

        ctl.process.handlers[Method.RENDER] = counting
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.last_finished is not None, 30, "the turn to finish")
        self.assertFalse(ctl.last_finished["is_error"], ctl.last_finished)
        self.assertEqual(len(render_ticks), 5)
        self.assertEqual(len(set(render_ticks)), 5, f"renders ran on ticks {render_ticks}")

    def test_ask_unattended_in_background(self):
        ctl = self.run_turn("ask.json")
        results = [e["data"] for e in ctl.events if e["name"] == Event.TOOL_RESULT]
        self.assertIn('"unattended": true', results[0]["summary"])

    def test_ask_deferred_then_answered(self):
        ctl = self.make_controller("ask.json")
        ctl.commands.attended = lambda: True
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.question is not None, 20, "the question")
        self.assertEqual(ctl.question["question"], "Bevel the lid edges?")
        self.assertEqual(ctl.question["choices"], ["yes", "no"])
        self.assertEqual(list(ctl.bridge.deferred.values()), [Method.ASK])
        self.assertTrue(ctl.answer("yes please"))
        pump(ctl, lambda: ctl.last_finished is not None, 20, "the turn to finish")
        results = [e["data"] for e in ctl.events if e["name"] == Event.TOOL_RESULT]
        self.assertIn("yes please", results[0]["summary"])

    def test_interrupt_drops_queued_calls(self):
        ctl = self.make_controller("interrupt.json")
        handler = ctl.process.handlers[Method.EXEC]
        ran = []

        def interrupting(params):
            # The user interrupts while the first exec runs; the calls queued
            # behind it must not run.
            if not ran:
                ctl.interrupt()
            ran.append(params["label"])
            return handler(params)

        ctl.process.handlers[Method.EXEC] = interrupting
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.last_finished is not None, 20, "the turn to finish")
        self.assertTrue(ctl.last_finished["interrupted"])
        self.assertEqual(len(ran), 1)
        results = [e["data"] for e in ctl.events if e["name"] == Event.TOOL_RESULT]
        self.assertEqual(len(results), 3)
        refused = [r for r in results if r["is_error"]]
        self.assertEqual(len(refused), 2)
        self.assertTrue(all("interrupted" in r["summary"] for r in refused))
        texts = [e["data"]["text"] for e in ctl.events if e["name"] == Event.TEXT]
        self.assertNotIn("This should not be said after an interrupt.", texts)
        self.assertFalse(ctl.bridge.interrupted, "the flag clears when the turn ends")

    def assert_resumed(self, ctl, first):
        """The new SDK session resumed the conversation the last turn ended in."""
        self.assertEqual(len(ctl.session_starts), 2)
        self.assertEqual((ctl.session_starts[-1]["resume"], ctl.session_starts[-1]["fork"]), (first, False))
        self.assertEqual(ctl.last_finished["session_id"], first)

    def test_session_ended_by_the_agent_is_restarted(self):
        ctl = self.run_turn("end_session.json")
        first = ctl.last_finished["session_id"]
        self.assertFalse(ctl.session_ready, "the session_ended status was seen")
        ctl.last_finished = None
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 20, "the second turn")
        self.assertEqual(ctl.errors, [])
        self.assert_resumed(ctl, first)
        self.assertEqual(ctl.last_finished["turn_id"], "n0002")

    def test_unreported_session_end_is_restarted_on_submit(self):
        ctl = self.run_turn("end_session.json")
        first = ctl.last_finished["session_id"]
        # As if the session_ended status had not arrived before the next run.
        ctl.session_ready = True
        ctl.live_node = "n0001"
        ctl.last_finished = None
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 20, "the second turn")
        self.assertEqual(ctl.errors, [])
        self.assert_resumed(ctl, first)
        self.assertEqual(ctl.last_finished["turn_id"], "n0002", "the retry reuses the node")
        self.assertFalse(ctl.session.request_dir("n0003").exists())

    def test_no_session_after_the_end_was_reported_is_retried(self):
        ctl = self.run_turn("end_session.json")
        first = ctl.last_finished["session_id"]
        self.assertFalse(ctl.session_ready)
        ctl.last_finished = None
        # A submit already on its way when the session ended: the agent
        # answers no_session after its session_ended status.
        ctl.submit(CRATE_BUNDLE)
        pump(ctl, lambda: ctl.last_finished is not None or ctl.errors, 20, "the retried turn")
        self.assertEqual(ctl.errors, [])
        self.assert_resumed(ctl, first)
        self.assertEqual(ctl.last_finished["turn_id"], "n0002")
        self.assertFalse(ctl.session.node_dir("n0003").exists())

    def test_session_end_fails_an_accepted_turn(self):
        script = self.user_dir / "slow.json"
        script.write_text(json.dumps({"turns": [{"steps": [{"sleep": 5}]}]}))
        ctl = self.make_controller(script)
        ctl.run_bundle(CRATE_BUNDLE)
        pump(ctl, lambda: ctl._accepted, 15, "the submit to be accepted")
        ctl.on_event({"name": Event.STATUS,
                      "data": {"turn_id": None, "state": "session_ended", "detail": "CLI gone"}})
        self.assertFalse(ctl.running)
        self.assertEqual(ctl.last_finished["subtype"], "session_ended")
        self.assertEqual(ctl.last_finished["errors"], ["CLI gone"])
        self.assertFalse(ctl.session_ready)

    def test_a_new_controller_continues_the_session_nodes(self):
        first = self.run_turn("ping.json")
        self.assertEqual(first.last_finished["turn_id"], "n0001")
        first.stop(wait=True)
        transcript = first.session.transcript_path("n0001")
        request = first.session.request_dir("n0001") / "request.json"
        before = transcript.read_bytes(), request.read_bytes()
        (first.session.request_dir("n0001") / "marker").write_text("first turn")

        second = self.run_turn("ping.json")
        self.assertEqual(second.last_finished["turn_id"], "n0002")
        self.assertEqual((transcript.read_bytes(), request.read_bytes()), before)
        self.assertTrue((first.session.request_dir("n0001") / "marker").exists())
        self.assertTrue(second.session.transcript_path("n0002").exists())

    def test_submit_refuses_an_existing_node(self):
        ctl = self.make_controller()
        ctl.session.node_dir("n0001").mkdir(parents=True)
        ctl._next_node = 1
        with self.assertRaises(FileExistsError):
            ctl.submit(CRATE_BUNDLE)
        self.assertFalse(ctl.running)

    def test_large_messages_cross_the_socket(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        script = self.user_dir / "big.json"
        code = "s = '" + "x" * (1 << 20) + "'\nprint(len(s))"
        script.write_text(json.dumps({"turns": [{"steps": [
            {"call": "exec", "params": {"code": code, "label": "big"}, "expect": "ok"}]}]}))
        ctl.stop(wait=True)
        ctl = self.run_turn(script)
        results = [e["data"] for e in ctl.events if e["name"] == Event.TOOL_RESULT]
        self.assertIn("1048576", results[0]["summary"])

    def test_a_file_cannot_carry_a_fake_script(self):
        from whittle.addon import props

        # A fake script's steps run any Python: one saved in a shared .blend
        # would run when the user pressed Send.
        saved = props.WhittleSceneProps.__annotations__
        self.assertNotIn("fake_script", saved)
        self.assertNotIn("bundle_path", saved)

    def test_run_bundle_operator_body(self):
        import os

        from whittle import addon
        from whittle.addon import operators, turn
        from tests.blender.helpers import FAKE_SCRIPTS, agent_python

        env = mock.patch.dict(os.environ, {"WHITTLE_AGENT_PYTHON": str(agent_python())})
        env.start()
        self.addCleanup(env.stop)
        addon.register()
        try:
            bpy.context.window_manager.whittle_bundle_path = str(CRATE_BUNDLE)
            ctl = operators.run_bundle(bpy.context, str(FAKE_SCRIPTS / "exec_inspect_render.json"))
            self.controllers.append(ctl)
            self.assertIs(turn.current(), ctl)
            pump(ctl, lambda: ctl.last_finished is not None, 30, "the turn to finish")
            self.assertFalse(ctl.last_finished["is_error"], ctl.last_finished)
            root = ctl.session.root
            self.assertEqual((root.parent.name, root.parents[2]), ("chats", self.user_dir / "cache"),
                             "an unsaved file's chats are in its cache")
            self.assertTrue((root / "nodes" / "n0001" / "request" / "strokes.json").is_file())
        finally:
            addon.unregister()
        self.assertIsNone(turn.current(), "unregister stops and forgets the controller")


class DeferredTest(AgentTestCase):
    def test_resolve_unknown_call_is_false(self):
        ctl = self.make_controller()
        self.start_ready(ctl)
        self.assertFalse(ctl.bridge.resolve("b999", {}))
        self.assertIsInstance(Deferred(), Deferred)
