# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent runs on an Anthropic API key only: no key, no start; and the
bundled CLI never sees another way to sign in, nor the user's own Claude
configuration."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.blender.helpers import AgentTestCase, pump
from whittle.addon import chats, paths, prefs, process
from whittle.addon.process import AgentState

KEY = "sk-ant-api03-test-key-0123456789"
SIGN_INS = {
    "CLAUDE_CODE_OAUTH_TOKEN": "oauth", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "refresh",
    "ANTHROPIC_AUTH_TOKEN": "bearer", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1",
    "CLAUDE_CODE_USE_FOUNDRY": "1", "CLAUDE_CODE_SESSION_ACCESS_TOKEN": "session",
    "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR": "3", "CLAUDE_CONFIG_DIR": "/home/someone/.claude",
    "CLAUDECODE": "1", "ANTHROPIC_MODEL": "claude-other",
}


def no_env_key():
    """Blender's environment without ANTHROPIC_API_KEY, for one block."""
    patch = mock.patch.dict(os.environ)
    patch.start()
    os.environ.pop("ANTHROPIC_API_KEY", None)
    return patch


class KeyTest(AgentTestCase):
    def test_no_key_does_not_start(self):
        patch = no_env_key()
        self.addCleanup(patch.stop)
        ctl = self.make_controller(script=None)
        with mock.patch.object(process.subprocess, "Popen") as popen:
            ctl.start()
        popen.assert_not_called()
        self.assertEqual(ctl.process.state, AgentState.NEEDS_KEY)
        self.assertEqual(ctl.process.reason, process.NO_KEY)
        self.assertFalse(ctl.process.alive)
        ctl.process.clear_key()
        self.assertEqual(ctl.process.state, AgentState.STOPPED)

    def test_no_key_keeps_the_prompt(self):
        """Send without a key writes nothing and raises, so the prompt stays
        in the box and the attention box asks for a key."""
        patch = no_env_key()
        self.addCleanup(patch.stop)
        ctl = self.make_controller(script=None)
        with self.assertRaises(RuntimeError):
            ctl.run_sketch("Add a lid.", targets=[])
        self.assertEqual(ctl.process.state, AgentState.NEEDS_KEY)
        self.assertFalse(ctl.session.node_dir("n0001").exists())

    def test_the_preference_comes_before_the_environment(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "  from-env  "}):
            self.assertEqual(prefs.api_key(), ("from-env", "environment"))
            with mock.patch.object(prefs, "get", return_value=SimpleNamespace(api_key=" typed ")):
                self.assertEqual(prefs.api_key(), ("typed", "preferences"))
        patch = no_env_key()
        self.addCleanup(patch.stop)
        self.assertEqual(prefs.api_key(), ("", None))

    def test_the_fake_agent_needs_no_key(self):
        patch = no_env_key()
        self.addCleanup(patch.stop)
        self.start_ready(self.make_controller())


class EnvironmentTest(AgentTestCase):
    def test_other_sign_ins_are_stripped(self):
        base = {"PATH": "/usr/bin", "HTTPS_PROXY": "http://proxy", "ANTHROPIC_BASE_URL": "http://gw",
                "WHITTLE_AGENT_PYTHON": "/py", "ANTHROPIC_API_KEY": "old", "DISABLE_TELEMETRY": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", **SIGN_INS}
        env = process.agent_environment(base, api_key=KEY, config_dir=Path("/w/claude"))
        self.assertEqual(env, {"PATH": "/usr/bin", "HTTPS_PROXY": "http://proxy",
                               "ANTHROPIC_BASE_URL": "http://gw", "WHITTLE_AGENT_PYTHON": "/py",
                               "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                               "ANTHROPIC_API_KEY": KEY, "CLAUDE_CONFIG_DIR": "/w/claude"})
        env = process.agent_environment(base, api_key="", config_dir=Path("/w/claude"))
        self.assertNotIn("ANTHROPIC_API_KEY", env, "the fake agent gets no key it was not given")

    def test_the_clis_own_traffic_is_off_unless_asked_for(self):
        env = process.agent_environment({"PATH": "/usr/bin"}, api_key=KEY, config_dir=Path("/w/claude"))
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1", "off by default")
        env = process.agent_environment({"PATH": "/usr/bin"}, api_key=KEY, config_dir=Path("/w/claude"),
                                        usage_data=True)
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", env, "the preference turns it back on")
        env = process.agent_environment({"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}, api_key=KEY,
                                        config_dir=Path("/w/claude"), usage_data=True)
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1",
                         "an opt-out in Blender's own environment still stands")

    def test_the_agent_runs_with_the_key_and_a_private_config(self):
        seen = {}

        def popen(argv, **kwargs):
            seen.update(kwargs["env"])
            raise OSError("not really")

        ctl = self.make_controller(script=None)
        # Background Blender runs offline; the start goes as far as Popen.
        online = SimpleNamespace(app=SimpleNamespace(online_access=True))
        with mock.patch.dict(os.environ, {**SIGN_INS, "ANTHROPIC_API_KEY": KEY}), \
                mock.patch.object(process, "bpy", online), \
                mock.patch.object(process.subprocess, "Popen", popen):
            ctl.start()
        self.assertEqual(ctl.process.state, AgentState.FAILED)
        self.assertEqual(seen["ANTHROPIC_API_KEY"], KEY)
        self.assertEqual(Path(seen["CLAUDE_CONFIG_DIR"]), self.user_dir / "claude")
        self.assertEqual(Path(seen["CLAUDE_CONFIG_DIR"]), paths.claude_config_dir())
        self.assertEqual(seen["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1",
                         "the preference is off by default")
        for name in SIGN_INS:
            if name != "CLAUDE_CONFIG_DIR":
                self.assertNotIn(name, seen)

    def test_the_cli_folder_is_whittles_own(self):
        self.assertEqual(chats.config_dir(), self.user_dir / "claude")
        self.assertTrue(chats.config_dir().is_dir())

    def test_the_key_is_never_written(self):
        """Neither the agent's log nor anything in Whittle's user folder
        holds the key; the controller keeps only its digest."""
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": KEY}):
            ctl = self.make_controller()
            self.start_ready(ctl)
            self.assertNotIn(KEY, repr(ctl.launch_settings()))
            ctl.stop(wait=True)
        pump(ctl, lambda: not ctl.process.alive, 10, "the agent to stop")
        for path in self.user_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY.encode(), path.read_bytes(), path)
        self.assertTrue(list(self.user_dir.rglob("agent-*.log")), "the log was looked at")
