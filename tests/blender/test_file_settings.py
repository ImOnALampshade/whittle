# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-file overrides of the session settings (triangle budget, self-check
rounds, render size, palette, bevel style, style notes): stored on the scene
and saved with the file, read by every session started for it, shown in the
agent popover with "(default)" while unset and a reset button."""

import json
import subprocess
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import REPO, AgentTestCase, TempUserDir
from tests.blender.test_sidebar import AddonTestCase
from tests.blender.ui_helpers import RecordingLayout
from whittle import style
from whittle.addon import prefs, props, ui
from whittle.agent import prompt

PREFS = SimpleNamespace(**{**prefs.DEFAULTS, "poly_budget": 1500, "style_notes": "low poly",
                           "self_check_rounds": 2, "render_size": 384, "palette": "pine, brass",
                           "bevel_style": "subtle"})
FROM_PREFS = {key: getattr(PREFS, key) for key in prefs.SESSION_SETTINGS}


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

    def field_texts(self, layout) -> dict:
        """Each setting's name as the popover shows it: the field's own text,
        or the label above a field drawn without one."""
        found = {}
        calls = layout.calls
        for i, call in enumerate(calls):
            if call["kind"] == "prop" and call["prop"] in props.FILE_SETTINGS:
                text = call["text"] or [c for c in calls[:i] if c["kind"] == "label"][-1]["text"]
                found[call["prop"]] = text
        return found

    def test_every_session_setting_has_an_override(self):
        self.assertEqual(list(props.FILE_SETTINGS), list(prefs.SESSION_SETTINGS))
        rna = props.WhittleSceneProps.bl_rna.properties
        for key in props.FILE_SETTINGS:
            with self.subTest(key=key):
                self.assertEqual(rna[key].name, prefs.LABELS[key])
                self.assertTrue(rna[key].description.startswith(prefs.DESCRIPTIONS[key]))
        for key in ("self_check_rounds", "render_size"):
            self.assertEqual((rna[key].hard_min, rna[key].hard_max), prefs.LIMITS[key])

    def test_unset_reads_the_preferences(self):
        self.assertEqual(props.file_settings(self.scene), {})
        for key, value in FROM_PREFS.items():
            self.assertEqual(getattr(self.props, key), value, key)
        self.assertEqual(prefs.session_settings(), FROM_PREFS)

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

    def test_rounds_and_render_size(self):
        self.props.self_check_rounds = 0
        self.props.render_size = 768
        settings = prefs.session_settings()
        self.assertEqual((settings["self_check_rounds"], settings["render_size"]), (0, 768),
                         "no self-check rounds is a real choice")
        self.props.self_check_rounds = 50
        self.props.render_size = 8
        self.assertEqual((self.props.self_check_rounds, self.props.render_size), (10, 64), "kept in bounds")
        self.props[props.FILE_SETTINGS["render_size"]] = 99999
        self.assertEqual(prefs.session_settings()["render_size"], 1024, "a hand-edited value too")

    def test_palette_and_bevel_style(self):
        self.props.palette = "weathered oak, dark iron"
        self.props.bevel_style = ""
        settings = prefs.session_settings()
        self.assertEqual((settings["palette"], settings["bevel_style"]), ("weathered oak, dark iron", ""),
                         "an empty bevel style overrides the preference's")
        text = prompt.build(settings)
        self.assertIn("- Colour palette: weathered oak, dark iron\n", text)
        self.assertIn(f"- Bevel style: {style.NO_BEVEL_STYLE}\n", text)
        self.assertIn("- Notes: low poly\n", text)
        props.reset_file_setting(self.scene, "bevel_style")
        self.assertIn(f"- Bevel style: {style.BEVEL_STYLES['subtle']}\n", prompt.build(prefs.session_settings()))

    def test_other_scene_keeps_the_preferences(self):
        self.props.poly_budget = 600
        self.props.palette = "red"
        other = bpy.data.scenes.new("Other")
        self.addCleanup(bpy.data.scenes.remove, other)
        self.assertEqual(prefs.session_settings(other), FROM_PREFS)

    def test_wrong_type_counts_as_unset(self):
        self.props[props.FILE_SETTINGS["poly_budget"]] = "many"
        self.props[props.FILE_SETTINGS["palette"]] = 3
        self.props[props.FILE_SETTINGS["render_size"]] = 512.0
        self.assertEqual(props.file_settings(self.scene), {})
        self.assertEqual((self.props.poly_budget, self.props.palette, self.props.render_size),
                         (1500, "pine, brass", 384))

    def test_reset_operator(self):
        self.props.poly_budget = 600
        self.props.style_notes = "chunky"
        self.props.render_size = 256
        self.assertEqual(bpy.ops.whittle.file_setting_reset(key="poly_budget"), {"FINISHED"})
        self.assertEqual(bpy.ops.whittle.file_setting_reset(key="render_size"), {"FINISHED"})
        self.assertEqual(props.file_settings(self.scene), {"style_notes": "chunky"})
        self.assertEqual((self.props.poly_budget, self.props.render_size), (1500, 384))
        for key in prefs.SESSION_SETTINGS:
            self.assertEqual(bpy.ops.whittle.file_setting_reset(key=key), {"FINISHED"}, key)
        self.assertEqual(props.file_settings(self.scene), {})

    def test_popover(self):
        layout = self.popover()
        self.assertIn("For This File", layout.labels())
        self.assertEqual(self.field_texts(layout), {key: f"{prefs.LABELS[key]} (default)" for key in prefs.SESSION_SETTINGS})
        self.assertEqual(list(self.field_texts(layout)), list(prefs.SESSION_SETTINGS), "in the preferences' order")
        self.assertEqual(self.resets(layout), dict.fromkeys(prefs.SESSION_SETTINGS, False))
        own_line = [c["prop"] for c in layout.of("prop") if c["prop"] in props.FILE_SETTINGS and c["text"] == ""]
        self.assertEqual(own_line, ["palette", "bevel_style", "style_notes"], "text gets a line of its own")

        self.props.style_notes = "chunky"
        self.props.palette = "oak"
        self.props.self_check_rounds = 1
        layout = self.popover()
        texts = self.field_texts(layout)
        self.assertEqual((texts["style_notes"], texts["palette"], texts["self_check_rounds"]),
                         ("Style Notes", "Palette", "Self-check Rounds"))
        self.assertEqual((texts["poly_budget"], texts["bevel_style"]),
                         ("Triangle Budget (default)", "Bevel Style (default)"))
        self.assertEqual(self.resets(layout), {**dict.fromkeys(prefs.SESSION_SETTINGS, False),
                                               "style_notes": True, "palette": True, "self_check_rounds": True})

    def test_popover_without_a_scene(self):
        layout = RecordingLayout()
        ui.draw_agent(layout, None)
        self.assertNotIn("For This File", layout.labels())
        self.assertEqual(layout.operators("whittle.file_setting_reset"), [])

    def test_saved_with_the_file(self):
        values = {"poly_budget": 600, "self_check_rounds": 5, "render_size": 256, "palette": "oak, iron",
                  "bevel_style": "chunky", "style_notes": "chunky"}
        for key, value in values.items():
            setattr(self.props, key, value)
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
        self.assertEqual(json.loads(line[5:]), values)


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
        for key, value in (("poly_budget", 640), ("self_check_rounds", 1), ("render_size", 256),
                           ("palette", "teal"), ("bevel_style", "none")):
            with self.subTest(key=key):
                setattr(self.scene.whittle, key, value)
                self.assertEqual(ctl.launch_settings()["settings"][key], value)
                self.assertTrue(ctl.launch_changed)
                props.reset_file_setting(self.scene, key)
                self.assertFalse(ctl.launch_changed)
