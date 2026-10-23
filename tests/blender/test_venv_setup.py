# SPDX-License-Identifier: GPL-3.0-or-later
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import TempUserDir
from tests.blender.ui_helpers import RecordingLayout
from tests.blender.test_sidebar import fake_controller
from whittle import venv
from whittle.addon import prefs, setup, turn, ui
from whittle.addon.process import AgentState


class VenvSetupTest(unittest.TestCase):
    def setUp(self):
        self._user = TempUserDir()
        self.user = self._user.__enter__()
        self.addCleanup(self._user.__exit__, None, None, None)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("WHITTLE_AGENT_PYTHON", None)
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.addCleanup(setattr, setup, "_current", None)
        self.addCleanup(turn.set_current, None)

    def test_dry_run_operator_logs_the_exact_commands(self):
        ctl = SimpleNamespace(process=SimpleNamespace(state=AgentState.NEEDS_SETUP, reason="x",
                                                      clear_setup=mock.Mock()),
                              running=False, busy=False)
        turn.set_current(ctl)
        result = bpy.ops.whittle.venv_install(dry_run=True)
        self.assertEqual(result, {"FINISHED"})
        done = setup.current()
        self.assertEqual((done.state, done.dry_run), ("done", True))
        log = done.log_path.read_text()
        python = venv.venv_python(self.user / "venv")
        install = " ".join(str(a) for a in venv.install_command(python, setup.lock_path()))
        self.assertIn(f"$ {install}\n", log)
        self.assertIn("--require-hashes --only-binary :all: --no-deps", log)
        self.assertFalse((self.user / "venv").exists())
        self.assertFalse(setup.timer_registered())
        ctl.process.clear_setup.assert_not_called()
        self.assertEqual(ctl.process.state, AgentState.NEEDS_SETUP)

    def test_real_install_refused_offline_and_in_background(self):
        self.assertTrue(bpy.ops.whittle.venv_install.poll(), "nothing running")
        if not bpy.app.online_access:
            with self.assertRaises(RuntimeError) as cm:
                setup.begin()
            self.assertIn("Online Access", str(cm.exception))
        # Background Blender never downloads anything, even with online access.
        online = SimpleNamespace(online_access=True, background=True)
        with mock.patch.object(setup, "bpy", _BpyWith(online)):
            with self.assertRaises(RuntimeError) as cm:
                setup.begin()
        self.assertIn("interface", str(cm.exception))
        self.assertIsNone(setup.current())
        self.assertFalse((self.user / "venv").exists())

    def test_refused_during_a_turn(self):
        turn.set_current(SimpleNamespace(running=True, busy=True,
                                         process=SimpleNamespace(state=AgentState.BUSY)))
        self.assertFalse(bpy.ops.whittle.venv_install.poll())
        with self.assertRaises(RuntimeError) as cm:
            setup.begin(dry_run=True)
        self.assertIn("turn", str(cm.exception))

    def test_refused_while_installing(self):
        setup._current = SimpleNamespace(running=True, state="running")
        self.assertFalse(bpy.ops.whittle.venv_install.poll())
        self.assertTrue(bpy.ops.whittle.venv_cancel.poll())
        with self.assertRaises(RuntimeError):
            setup.begin(dry_run=True)

    def test_foreign_folder_is_refused(self):
        folder = self.user / "venv"
        folder.mkdir()
        (folder / "notes.txt").write_text("mine")
        with self.assertRaises(RuntimeError) as cm:
            setup.begin(dry_run=True)
        self.assertIn("not made by Whittle", str(cm.exception))
        self.assertEqual([p.name for p in folder.iterdir()], ["notes.txt"])

    def test_stale_venv_is_rebuilt_with_clear(self):
        folder = self.user / "venv"
        folder.mkdir()
        old = self.user / "old.lock"
        old.write_text("# old\n")
        venv.write_marker(folder, old, sdk="0.2.0", base_python=Path("/usr/bin/python3"))
        done = setup.begin(dry_run=True)
        self.assertIn("-m venv --clear", done.log_path.read_text())

    def test_finished_setup_clears_needs_setup(self):
        clear = mock.Mock()
        turn.set_current(SimpleNamespace(process=SimpleNamespace(state=AgentState.NEEDS_SETUP,
                                                                 clear_setup=clear)))
        setup._finished(SimpleNamespace(state="done", dry_run=False, venv=self.user / "venv"))
        clear.assert_called_once()

    def test_install_asks_for_confirmation_first(self):
        confirm = mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_confirm=confirm))
        op = SimpleNamespace(reinstall=False, dry_run=False, execute=mock.Mock())
        with mock.patch.object(setup, "begin") as begin:
            result = setup.WHITTLE_OT_venv_install.invoke(op, context, object())
        self.assertEqual(result, {"RUNNING_MODAL"})
        confirm.assert_called_once()
        self.assertEqual(confirm.call_args.kwargs["message"], setup.install_summary())
        begin.assert_not_called()
        op.execute.assert_not_called()
        self.assertIsNone(setup.current())

    def test_timer_survives_loading_a_file(self):
        setup._current = SimpleNamespace(running=True, state="running", step="install",
                                         tick=lambda: 1.0, cancel=mock.Mock())
        setup._start_timer()
        self.addCleanup(setup._stop_timer)
        bpy.ops.wm.read_homefile(use_empty=True)
        self.assertTrue(setup.timer_registered())

    def test_install_summary(self):
        summary = setup.install_summary()
        self.assertIn("30 pinned packages", summary)
        self.assertIn("claude-agent-sdk 0.2.167", summary)
        self.assertIn(str(self.user / "venv"), summary)

    def attention(self, ctl) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_attention(layout, ui.Ctx(scene=bpy.context.scene, hist=None, ctl=ctl, comparing=None))
        return layout

    def test_attention_shows_setup_not_restart(self):
        layout = self.attention(fake_controller(AgentState.NEEDS_SETUP, reason="The agent environment "
                                                                                 "is not set up yet",
                                                alive=False))
        (install,) = layout.operators("whittle.venv_install")
        self.assertEqual(install["text"], "Set Up…")
        self.assertEqual(install["layout"].operator_context, "INVOKE_DEFAULT", "keeps its confirmation")
        self.assertEqual(layout.operators("whittle.agent_start"), [])
        self.assertIn("Set up Claude to start", layout.labels())
        self.assertFalse(any(layout.alerted(c) for c in layout.calls if c["kind"] in ("label", "operator")),
                         "a first run is not a failure")
        layout = self.attention(fake_controller(AgentState.NEEDS_SETUP, reason="Set up for an earlier "
                                                "version", alive=False))
        self.assertIn("Set up for an earlier version", layout.text(), "a specific reason is shown")

        setup._current = SimpleNamespace(running=True, state="running", step="install",
                                         describe_progress=lambda: "install: sdk.whl 43.1 / 114.1 MB")
        layout = self.attention(fake_controller(AgentState.NEEDS_SETUP, reason="x", alive=False))
        self.assertEqual(len(layout.operators("whittle.venv_cancel")), 1)
        self.assertEqual(layout.operators("whittle.venv_install"), [])
        self.assertIn("43.1 / 114.1 MB", layout.text())
        self.assertFalse(any(c["kind"] == "box" and c["child"].alert for c in layout.calls),
                         "a setup under way is not an alarm")

    def test_crash_still_offers_restart(self):
        layout = self.attention(fake_controller(AgentState.CRASHED, reason="exited with code 1", alive=False))
        self.assertEqual(len(layout.operators("whittle.agent_start")), 1)
        self.assertEqual(layout.operators("whittle.venv_install"), [])

    def test_preferences_environment_box(self):
        p = SimpleNamespace(venv_dir="")
        layout = RecordingLayout()
        prefs.draw_environment(layout, p, setup)
        self.assertEqual([c["props"] for c in layout.operators("whittle.venv_install")][1].reinstall, True)
        self.assertIn("Not set up yet", layout.labels())


class _BpyWith:
    """bpy with another bpy.app, since bpy.app's flags are read-only."""

    def __init__(self, app):
        self.app = app

    def __getattr__(self, name):
        return getattr(bpy, name)


if __name__ == "__main__":
    unittest.main()
