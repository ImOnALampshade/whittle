# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from pathlib import Path


class AgentEnvironmentTest(unittest.TestCase):
    def test_sdk_is_the_pinned_version(self):
        import claude_agent_sdk

        self.assertEqual(claude_agent_sdk.__version__, "0.2.167")

    def test_sdk_bundles_the_cli(self):
        import claude_agent_sdk

        cli = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        self.assertTrue(cli.is_file())


if __name__ == "__main__":
    unittest.main()
