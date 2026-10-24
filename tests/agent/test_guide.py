# SPDX-License-Identifier: GPL-3.0-or-later
"""AGENTS.md, the working guide, names files and links that exist, so it
cannot quietly drift from the repo it describes."""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "AGENTS.md"
# Relative paths the guide writes in backticks, by the folder they start in.
ROOTS = {"whittle/": REPO, "tests/": REPO, "docs/": REPO, "agent_env/": REPO,
         "addon/": REPO / "whittle", "agent/": REPO / "whittle"}


class GuideTest(unittest.TestCase):
    def setUp(self):
        self.text = GUIDE.read_text()

    def test_every_link_exists(self):
        links = re.findall(r"\]\(([^)#]+)\)", self.text)
        self.assertTrue(links)
        for link in links:
            self.assertTrue((REPO / link).exists(), link)

    def test_every_path_exists(self):
        paths = [p for p in re.findall(r"`([\w./-]+)`", self.text)
                 if p.startswith(tuple(ROOTS)) and "<" not in p and not p.endswith(".log")]
        self.assertGreater(len(paths), 20)
        for path in paths:
            root = next(base for prefix, base in ROOTS.items() if path.startswith(prefix))
            self.assertTrue((root / path).exists(), path)

    def test_every_script_exists(self):
        for script in set(re.findall(r"\./(\w+\.sh)", self.text)):
            self.assertTrue((REPO / script).is_file(), script)

    def test_it_is_the_only_guide(self):
        # Claude Code reads AGENTS.md itself; a CLAUDE.md would be a second copy to keep in step.
        self.assertFalse((REPO / "CLAUDE.md").exists())


if __name__ == "__main__":
    unittest.main()
