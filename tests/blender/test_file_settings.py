# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-file overrides of the triangle budget and style notes: stored on the
scene and saved with the file, read by every session started for it, shown
in the agent popover with "(default)" while unset and a reset button."""

import json
import subprocess
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import REPO, AgentTestCase, TempUserDir
from tests.blender.test_sidebar import AddonTestCase
from tests.blender.ui_helpers import RecordingLayout
from whittle.addon import prefs, props, ui

PREFS = SimpleNamespace(**{**prefs.DEFAULTS, "poly_budget": 1500, "style_notes": "low poly"})


class FileSettingsTest(AddonTestCase):
    def setUp(self):
        super().setUp()
        for key in props.FILE_SETTINGS:
            props.reset_file_setting(self.scene, key)
        self.addCleanup(lambda: [props.reset_file_setting(self.scene, k) for k in props.FILE_SETTINGS])
        patcher = mock.patch.object(prefs, "get", return_value=PREFS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def popover(self) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_agent(layout, None, self.scene)
        return layout

    def resets(self, layout) -> dict:
        return {c["props"].key: layout.is_enabled(c) for c in layout.operators("whittle.file_setting_reset")}

    def test_unset_reads_the_preferences(self):
        self.assertEqual(props.file_settings(self.scene), {})
        self.assertEqual((self.props.poly_budget, self.props.style_notes), (1500, "low poly"))
        settings = prefs.session_settings()
        self.assertEqual((settings["poly_budget"], settings["style_notes"]), (1500, "low poly"))

    def test_set_overrides_the_preferences(self):
        self.props.poly_budget = 600
        self.assertEqual(props.file_settings(self.scene), {"poly_budget": 600})
        self.assertEqual(prefs.session_settings(self.scene)["style_notes"], "low poly", "the other stays default")
        self.props.style_notes = ""
        settings = prefs.session_settings()
        self.assertEqual((settings["poly_budget"], settings["style_notes"]), (600, ""),
                         "empty notes are an override too")
        self.assertEqual(settings["self_check_rounds"], PREFS.self_check_rounds)
        self.props.poly_budget = 3
        self.assertEqual(self.props.poly_budget, prefs.MIN_POLY_BUDGET)

    def test_other_scene_keeps_the_preferences(self):
        self.props.poly_budget = 600
        other = bpy.data.scenes.new("Other")
        self.addCleanup(bpy.data.scenes.remove, other)
        self.assertEqual(prefs.session_settings(other)["poly_budget"], 1500)

    def test_wrong_type_counts_as_unset(self):
        self.props[props.FILE_SETTINGS["poly_budget"]] = "many"
        self.assertEqual(props.file_settings(self.scene), {})
        self.assertEqual(self.props.poly_budget, 1500)

    def test_reset_operator(self):
        self.props.poly_budget = 600
        self.props.style_notes = "chunky"
        self.assertEqual(bpy.ops.whittle.file_setting_reset(key="poly_budget"), {"FINISHED"})
        self.assertEqual(props.file_settings(self.scene), {"style_notes": "chunky"})
        self.assertEqual(self.props.poly_budget, 1500)

    def test_popover(self):
        layout = self.popover()
        self.assertIn("For This File", layout.labels())
        (budget,) = [c for c in layout.of("prop") if c["prop"] == "poly_budget"]
        self.assertEqual(budget["text"], "Triangle Budget (default)")
        self.assertIn("Style Notes (default)", layout.labels())
        self.assertEqual(self.resets(layout), {"poly_budget": False, "style_notes": False})

        self.props.style_notes = "chunky"
        layout = self.popover()
        (budget,) = [c for c in layout.of("prop") if c["prop"] == "poly_budget"]
        self.assertEqual(budget["text"], "Triangle Budget (default)")
        self.assertIn("Style Notes", layout.labels())
        self.assertNotIn("Style Notes (default)", layout.labels())
        self.assertEqual(self.resets(layout), {"poly_budget": False, "style_notes": True})

    def test_popover_without_a_scene(self):
        layout = RecordingLayout()
        ui.draw_agent(layout, None)
        self.assertNotIn("For This File", layout.labels())
        self.assertEqual(layout.operators("whittle.file_setting_reset"), [])

    def test_saved_with_the_file(self):
        self.props.poly_budget = 600
        self.props.style_notes = "chunky"
        with TempUserDir() as folder:
            blend = folder / "settings.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(blend), copy=True)
            script = (f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
                      "import bpy, json\n"
                      "from whittle import addon\n"
                      "from whittle.addon import props\n"
                      "addon.register()\n"
                      "print('FILE', json.dumps(props.file_settings(bpy.context.scene)))\n")
            out = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", str(blend),
                                  "--python-expr", script], capture_output=True, text=True, timeout=120)
        (line,) = [l for l in out.stdout.splitlines() if l.startswith("FILE ")]
        self.assertEqual(json.loads(line[5:]), {"poly_budget": 600, "style_notes": "chunky"})


class LaunchTest(AgentTestCase):
    """The agent runs with the file's values, and a changed one restarts it
    for the next turn like a changed preference does."""

    def setUp(self):
        super().setUp()
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.scene = bpy.context.scene
        self.addCleanup(lambda: [props.reset_file_setting(self.scene, k) for k in props.FILE_SETTINGS])

    def test_launch_settings_follow_the_file(self):
        ctl = self.make_controller()
        self.assertEqual(ctl.launch_settings()["settings"]["poly_budget"], prefs.DEFAULTS["poly_budget"])
        self.start_ready(ctl)
        self.assertFalse(ctl.launch_changed)
        self.scene.whittle.poly_budget = 640
        self.assertEqual(ctl.launch_settings()["settings"]["poly_budget"], 640)
        self.assertTrue(ctl.launch_changed)
        props.reset_file_setting(self.scene, "poly_budget")
        self.assertFalse(ctl.launch_changed)
