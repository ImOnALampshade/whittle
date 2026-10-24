# SPDX-License-Identifier: GPL-3.0-or-later
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

import bpy

import whittle
from tests.blender.helpers import REPO
from whittle.addon import start

PACKAGE = REPO / "whittle"


def blender(*args, timeout=60):
    return subprocess.run([bpy.app.binary_path, "--factory-startup", "--command", "extension", *args],
                          capture_output=True, text=True, timeout=timeout)


class ManifestTest(unittest.TestCase):
    def test_manifest_validates(self):
        result = blender("validate", str(PACKAGE))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_extension_builds_without_caches(self):
        out = Path(tempfile.mkdtemp(prefix="whittle-build-"))
        try:
            result = blender("build", "--source-dir", str(PACKAGE), "--output-dir", str(out))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            (archive,) = out.glob("*.zip")
            names = zipfile.ZipFile(archive).namelist()
            self.assertIn("blender_manifest.toml", names)
            self.assertIn("agent/__main__.py", names)
            self.assertIn("agent/plugin/.claude-plugin/plugin.json", names)
            for name in ("requirements.lock", "LICENSE", "venv.py", "addon/setup.py", "addon/start.py",
                         "addon/refs.py"):
                self.assertIn(name, names)
            self.assertFalse([n for n in names if "__pycache__" in n])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_license(self):
        manifest = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text())
        self.assertEqual(manifest["license"], ["SPDX:GPL-3.0-or-later"])
        self.assertEqual((PACKAGE / "LICENSE").read_bytes(), (REPO / "LICENSE").read_bytes())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", (REPO / "LICENSE").read_text()[:200])
        for path in [*PACKAGE.rglob("*.py"), *(REPO / "tests").rglob("*.py"), *REPO.glob("*.sh")]:
            if "__pycache__" in path.parts:
                continue
            with self.subTest(path=path.relative_to(REPO)):
                head = path.read_text().splitlines()[:2]
                self.assertIn("# SPDX-License-Identifier: GPL-3.0-or-later", head)

    def test_platforms_match_what_the_setup_accepts(self):
        from whittle import venv

        manifest = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text())
        self.assertEqual(manifest["platforms"], ["linux-x64", "linux-arm64", "windows-x64", "macos-arm64"])
        # Each listed platform as platform.machine() and sys.platform name it.
        named = {"linux-x64": ("x86_64", "linux"), "linux-arm64": ("aarch64", "linux"),
                 "windows-x64": ("AMD64", "win32"), "macos-arm64": ("arm64", "darwin")}
        for name in manifest["platforms"]:
            with self.subTest(platform=name):
                self.assertIsNone(venv.compatible((3, 14, 0), *named[name]))

    def test_permissions(self):
        manifest = tomllib.loads((PACKAGE / "blender_manifest.toml").read_text())
        self.assertEqual(set(manifest["permissions"]), {"network", "files"})
        for key, text in manifest["permissions"].items():
            self.assertLessEqual(len(text), 64, key)

    def test_build_script(self):
        out = Path(tempfile.mkdtemp(prefix="whittle-buildsh-"))
        try:
            result = subprocess.run([str(REPO / "build.sh"), str(out)], capture_output=True, text=True,
                                    timeout=500)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual([p.name for p in out.glob("*.zip")], [f"whittle-{whittle.__version__}.zip"])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_build_output_is_ignored(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertIn("/build/", lines)

    def test_lock_copy_matches_the_pinned_lock(self):
        self.assertEqual((PACKAGE / "requirements.lock").read_bytes(),
                         (REPO / "agent_env" / "requirements.lock").read_bytes())


def asset_entries():
    return list(bpy.types.ASSETBROWSER_MT_context_menu._dyn_ui_initialize())


class RegisterTest(unittest.TestCase):
    def registered(self):
        return [name for name in dir(bpy.types) if name.startswith("WHITTLE_")]

    def test_register_unregister_twice(self):
        import whittle
        from whittle import addon

        handlers = bpy.app.handlers
        watched = (handlers.load_pre, handlers.exit_pre, handlers.depsgraph_update_post,
                   handlers.undo_pre, handlers.undo_post, handlers.redo_post)
        before = [list(h) for h in watched]
        for _ in range(2):
            whittle.register()
            registered = self.registered()
            for name in ("WHITTLE_PT_main", "WHITTLE_PT_agent", "WHITTLE_PT_history", "WHITTLE_PT_debug",
                         "WHITTLE_PT_targets", "WHITTLE_MT_start_primitive", "WHITTLE_MT_stop"):
                self.assertIn(name, registered)
            for gone in ("WHITTLE_PT_start", "WHITTLE_PT_sketch", "WHITTLE_PT_request", "WHITTLE_PT_stream",
                         "WHITTLE_UL_targets"):
                self.assertNotIn(gone, registered)
            for op in ("amend", "open_image", "open_transcript", "target_from_selection",
                       "target_add", "target_remove", "target_clear", "view_remove", "view_snap", "sketch_toggle",
                       "venv_install", "venv_cancel", "start_existing", "start_blank", "start_primitive", "start_asset",
                       "ref_pin", "ref_place", "branch_switch", "retry", "turn_menu", "ref_menu"):
                self.assertIn(f"WHITTLE_OT_{op}", registered)
            self.assertEqual(asset_entries().count(start.draw_asset_menu), 1)
            self.assertTrue(hasattr(bpy.types.Scene, "whittle"))
            self.assertIn(addon._stop_agent, bpy.app.handlers.load_pre)
            whittle.unregister()
            self.assertEqual(self.registered(), [])
            self.assertFalse(hasattr(bpy.types.Scene, "whittle"))
            self.assertNotIn(start.draw_asset_menu, asset_entries())
        self.assertEqual([list(h) for h in watched], before)

    def test_unregister_cancels_a_running_setup(self):
        import whittle
        from whittle.addon import setup

        class Running:
            running = True
            cancelled = None

            def cancel(self, wait=0.0):
                self.cancelled = wait

        whittle.register()
        running = Running()
        setup._current = running
        self.addCleanup(setattr, setup, "_current", None)
        bpy.app.timers.register(setup._timer, first_interval=60)
        whittle.unregister()
        self.assertEqual(running.cancelled, setup.UNREGISTER_WAIT)
        self.assertFalse(setup.timer_registered())

    def test_timer_registration(self):
        from whittle.addon import bridge

        class Stub:
            def tick(self):
                return 0.25

        bridge.start_timer(Stub())
        try:
            self.assertTrue(bridge.timer_registered())
            self.assertEqual(bridge._timer(), 0.25)
        finally:
            bridge.stop_timer()
        self.assertFalse(bridge.timer_registered())
