# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bpy

from tests.blender.helpers import REPO, TempUserDir
from whittle import venv
from whittle.addon import paths, prefs, setup
from whittle.agent import dispatch, prompt

LOCK = REPO / "whittle" / "requirements.lock"


class PrefsDefaultsTest(unittest.TestCase):
    def test_rna_defaults_match_defaults(self):
        # The properties only exist on the RNA type while it is registered.
        bpy.utils.register_class(prefs.WhittlePreferences)
        self.addCleanup(bpy.utils.unregister_class, prefs.WhittlePreferences)
        props = prefs.WhittlePreferences.bl_rna.properties
        for key, value in prefs.DEFAULTS.items():
            with self.subTest(key=key):
                self.assertEqual(props[key].default, value)
        self.assertEqual(prefs.DEFAULTS["model"], "claude-opus-5-5")
        self.assertEqual((prefs.DEFAULTS["self_check_rounds"], prefs.DEFAULTS["render_size"],
                          prefs.DEFAULTS["poly_budget"]), (3, 512, 2000))
        self.assertEqual((prefs.DEFAULTS["api_key"], prefs.DEFAULTS["venv_dir"]), ("", ""))
        self.assertEqual(props["api_key"].subtype, "PASSWORD")
        self.assertEqual(props["venv_dir"].subtype, "DIR_PATH")

    def test_unregistered_get_falls_back_to_defaults(self):
        self.assertIsNone(bpy.context.preferences.addons.get(prefs.PACKAGE))
        self.assertEqual(vars(prefs.get()), prefs.DEFAULTS)
        self.assertEqual(prefs.session_settings(),
                         {"self_check_rounds": 3, "poly_budget": 2000, "style_notes": "", "render_size": 512})

    def test_agent_side_defaults_agree(self):
        for key, value in prompt.DEFAULTS.items():
            self.assertEqual(prefs.DEFAULTS[key], value, key)
        self.assertEqual(dispatch.DEFAULT_MODEL, prefs.DEFAULTS["model"])

    def test_model_search(self):
        # The model menu's list: the newest of each family, then the older ones.
        with TempUserDir():
            found = prefs._model_search(None, None, "")
            self.assertEqual(found[:4], ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
                                         "claude-fable-5-1"])
            self.assertIn("claude-opus-4-6", found)
            self.assertEqual(prefs._model_search(None, None, "haiku"), ["claude-haiku-5-5", "claude-haiku-4-5"])
            self.assertEqual(prefs._model_search(None, None, "gpt"), [])
            self.assertIn(prefs.DEFAULTS["model"], found)


class AgentPythonTest(unittest.TestCase):
    def setUp(self):
        self._user = TempUserDir()
        self.user = self._user.__enter__()
        self.addCleanup(self._user.__exit__, None, None, None)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("WHITTLE_AGENT_PYTHON", None)

    def make_venv(self, folder: Path, lock: Path = LOCK) -> Path:
        python = venv.venv_python(folder)
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        venv.write_marker(folder, lock, sdk="0.2.167", base_python=Path(sys.executable))
        return python

    def test_venv_dir_default_and_preference(self):
        self.assertEqual(setup.venv_dir(), self.user / "venv")
        other = Path(tempfile.mkdtemp(prefix="whittle-venvdir-"))
        self.addCleanup(shutil.rmtree, other, True)
        with mock.patch.object(prefs, "get", return_value=mock.Mock(venv_dir=str(other), agent_python="")):
            self.assertEqual(setup.venv_dir(), other.resolve())

    def test_lock_path_is_the_packaged_lock(self):
        self.assertEqual(setup.lock_path(), LOCK)
        self.assertTrue(setup.lock_path().is_file())

    def test_private_venv_counts_only_when_ready(self):
        folder = self.user / "venv"
        self.assertIsNone(paths.agent_python())
        self.assertIsNone(paths.agent_python_problem(), "missing is not a problem, just not set up")
        python = venv.venv_python(folder)
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        self.assertIsNone(paths.agent_python(), "a python without the marker is not ours")
        shutil.rmtree(folder)

        self.make_venv(folder)
        self.assertEqual(paths.agent_python(), python)
        self.assertIsNone(paths.agent_python_problem())

    def test_stale_venv_is_not_used(self):
        folder = self.user / "venv"
        old_lock = self.user / "old.lock"
        old_lock.write_bytes(LOCK.read_bytes() + b"# older\n")
        self.make_venv(folder, old_lock)
        self.assertIsNone(paths.agent_python())
        self.assertIn("earlier version", paths.agent_python_problem())

    def test_overrides_come_first(self):
        self.make_venv(self.user / "venv")
        os.environ["WHITTLE_AGENT_PYTHON"] = sys.executable
        self.assertEqual(paths.agent_python(), Path(sys.executable))

    def test_needs_setup_reason(self):
        from whittle.addon.process import AgentProcess, AgentState

        proc = AgentProcess(handlers={}, on_event=lambda m: None, use_timer=False)
        proc.start(self.user / "session")
        self.assertEqual(proc.state, AgentState.NEEDS_SETUP)
        self.assertIn("not set up", proc.reason)
        proc.clear_setup()
        self.assertEqual(proc.state, AgentState.STOPPED)
        self.assertIsNone(proc.reason)


if __name__ == "__main__":
    unittest.main()
