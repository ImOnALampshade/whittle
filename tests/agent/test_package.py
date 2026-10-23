# SPDX-License-Identifier: GPL-3.0-or-later
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

BPY_FREE = ["whittle", "whittle.protocol", "whittle.formats", "whittle.venv", "whittle.platforms", "whittle.chats",
            "whittle.caches", "whittle.agent", "whittle.agent.__main__", "whittle.agent.connection",
            "whittle.agent.dispatch", "whittle.agent.fake", "whittle.agent.prompt", "whittle.agent.tools"]

CHECK = """
import importlib, sys
class Blocked:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in ('bpy', 'bmesh', 'mathutils', 'claude_agent_sdk'):
            raise ImportError('blocked: ' + name)
sys.meta_path.insert(0, Blocked())
for module in sys.argv[1:]:
    importlib.import_module(module)
print('ok')
"""


class PackageTest(unittest.TestCase):
    def test_bpy_free_modules_import_without_bpy_or_the_sdk(self):
        result = subprocess.run([sys.executable, "-c", CHECK, *BPY_FREE], cwd=REPO,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runner_is_the_only_sdk_import(self):
        for path in (REPO / "whittle").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            top_level = [l for l in text.splitlines() if l.startswith(("import claude_agent_sdk", "from claude_agent_sdk"))]
            if path.name != "runner.py":
                self.assertEqual(top_level, [], f"{path} imports the SDK at module level")

    def test_agent_never_imports_bpy(self):
        for path in (REPO / "whittle" / "agent").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^\s*(import|from)\s+(bpy|bmesh|mathutils)\b", str(path))

    def test_version_matches_manifest(self):
        import whittle

        manifest = (REPO / "whittle" / "blender_manifest.toml").read_text()
        self.assertIn(f'version = "{whittle.__version__}"', manifest)
