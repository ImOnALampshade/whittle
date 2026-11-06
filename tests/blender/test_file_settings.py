# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-file overrides of the session settings (triangle budget, self-check
rounds, render size, style notes): stored on the scene and saved with the
file, read by every session started for it, shown in the agent popover with
"(default)" while unset and a reset button. Style Notes is a path: the guide
it points at is read before a turn, and its text is what the session gets."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import REPO, AgentTestCase, TempUserDir, pump
from tests.blender.test_sidebar import AddonTestCase
from tests.blender.ui_helpers import RecordingLayout
from whittle import style
import whittle.addon as addon
from whittle.addon import operators, prefs, props, turn, ui
from whittle.agent import prompt

PREFS = SimpleNamespace(**{**prefs.DEFAULTS, "poly_budget": 1500, "style_file": "/styles/default.md",
                           "self_check_rounds": 2, "render_size": 384})
FROM_PREFS = {**{key: getattr(PREFS, key) for key in prefs.SESSION_SETTINGS},
              "style_guide": "", "style_incomplete": True}  # /styles/default.md does not exist


class FileSettingsCase(AddonTestCase):
    def setUp(self):
        super().setUp()
        for key in props.FILE_SETTINGS:
            props.reset_file_setting(self.scene, key)
        self.addCleanup(lambda: [props.reset_file_setting(self.scene, k) for k in props.FILE_SETTINGS])
        patcher = mock.patch.object(prefs, "get", return_value=PREFS)
        patcher.start()
        self.addCleanup(patcher.stop)
        prefs._guides.clear()
        self.addCleanup(prefs._guides.clear)

    def popover(self) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_agent(layout, None, self.scene)
        return layout


class FileSettingsTest(FileSettingsCase):
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
        for key in prefs.SESSION_SETTINGS:
            self.assertEqual(getattr(self.props, key), FROM_PREFS[key], key)
        self.assertEqual(prefs.session_settings(), FROM_PREFS)

    def test_set_overrides_the_preferences(self):
        self.props.poly_budget = 600
        self.assertEqual(props.file_settings(self.scene), {"poly_budget": 600})
        self.assertEqual(prefs.session_settings(self.scene)["style_file"], PREFS.style_file,
                         "the other stays default")
        self.props.style_file = ""
        settings = prefs.session_settings()
        self.assertEqual((settings["poly_budget"], settings["style_file"]), (600, ""),
                         "an empty path is an override too: no guide in this file")
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

    def test_other_scene_keeps_the_preferences(self):
        self.props.poly_budget = 600
        self.props.style_file = "/styles/red.md"
        other = bpy.data.scenes.new("Other")
        self.addCleanup(bpy.data.scenes.remove, other)
        self.assertEqual(prefs.session_settings(other), FROM_PREFS)

    def test_wrong_type_counts_as_unset(self):
        self.props[props.FILE_SETTINGS["poly_budget"]] = "many"
        self.props[props.FILE_SETTINGS["style_file"]] = 3
        self.props[props.FILE_SETTINGS["render_size"]] = 512.0
        self.assertEqual(props.file_settings(self.scene), {})
        self.assertEqual((self.props.poly_budget, self.props.style_file, self.props.render_size),
                         (1500, PREFS.style_file, 384))

    def test_old_scene_keys_are_ignored(self):
        for key in ("palette", "bevel_style", "style_notes"):
            self.props[f"file_{key}"] = "a value from an older Whittle"
            self.assertFalse(hasattr(self.props, key))
            self.addCleanup(self.props.pop, f"file_{key}")
        self.assertEqual(props.file_settings(self.scene), {})
        self.assertEqual(prefs.session_settings(), FROM_PREFS)
        self.assertNotIn("older Whittle", prompt.build(prefs.session_settings()))

    def test_reset_operator(self):
        self.props.poly_budget = 600
        self.props.style_file = "/styles/chunky.md"
        self.props.render_size = 256
        self.assertEqual(bpy.ops.whittle.file_setting_reset(key="poly_budget"), {"FINISHED"})
        self.assertEqual(bpy.ops.whittle.file_setting_reset(key="render_size"), {"FINISHED"})
        self.assertEqual(props.file_settings(self.scene), {"style_file": "/styles/chunky.md"})
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
        self.assertEqual(own_line, ["style_file"], "a path gets a line of its own")

        self.props.style_file = "/styles/chunky.md"
        self.props.self_check_rounds = 1
        layout = self.popover()
        texts = self.field_texts(layout)
        self.assertEqual((texts["style_file"], texts["self_check_rounds"]), ("Style Notes", "Self-check Rounds"))
        self.assertEqual(texts["poly_budget"], "Triangle Budget (default)")
        self.assertEqual(self.resets(layout), {**dict.fromkeys(prefs.SESSION_SETTINGS, False),
                                               "style_file": True, "self_check_rounds": True})

    def test_each_reset_is_on_its_field_line(self):
        self.props.style_file = "/styles/chunky.md"
        layout = self.popover()
        parents = {id(c["child"]): c["layout"] for c in layout.calls if "child" in c}
        for key in props.FILE_SETTINGS:
            (field,) = [c for c in layout.of("prop") if c["prop"] == key]
            (reset,) = [c for c in layout.operators("whittle.file_setting_reset") if c["props"].key == key]
            self.assertIs(parents[id(reset["layout"])], field["layout"], key)
        (label,) = [c for c in layout.of("label") if c["text"] == "Style Notes"]
        self.assertEqual(label["icon"], "NONE", "at the fields' edge, not indented past it")

    def test_popover_without_a_scene(self):
        layout = RecordingLayout()
        ui.draw_agent(layout, None)
        self.assertNotIn("For This File", layout.labels())
        self.assertEqual(layout.operators("whittle.file_setting_reset"), [])

    def test_saved_with_the_file(self):
        values = {"poly_budget": 600, "self_check_rounds": 5, "render_size": 256, "style_file": "//style.md"}
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
        for key, value in (("poly_budget", 640), ("self_check_rounds", 1), ("render_size", 256)):
            with self.subTest(key=key):
                setattr(self.scene.whittle, key, value)
                self.assertEqual(ctl.launch_settings()["settings"][key], value)
                self.assertTrue(ctl.launch_changed)
                props.reset_file_setting(self.scene, key)
                self.assertFalse(ctl.launch_changed)

    def test_the_guide_text_decides_a_restart_and_not_its_path(self):
        (self.user_dir / "sub").mkdir()
        guide = self.user_dir / "style.md"
        guide.write_text("Worn edges.")
        self.scene.whittle.style_file = str(guide)
        ctl = self.make_controller()
        self.start_ready(ctl)
        self.assertFalse(ctl.launch_changed)
        self.scene.whittle.style_file = str(self.user_dir / "sub" / ".." / "style.md")
        self.assertFalse(ctl.launch_changed, "what a Save As does to a path: the same guide, other text")
        other = self.user_dir / "other.md"
        other.write_text("Sharp edges.")
        self.scene.whittle.style_file = str(other)
        self.assertTrue(ctl.launch_changed, "another guide is another text")

    def test_a_changed_guide_restarts_the_agent_for_the_next_turn(self):
        guide = self.user_dir / "style.md"
        guide.write_text("Worn edges.")
        self.scene.whittle.style_file = str(guide)
        ctl = self.make_controller()
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        self.start_ready(ctl)
        self.assertEqual(ctl.launch_settings()["settings"]["style_guide"], "Worn edges.")
        fake = str(ctl.process.fake_script)

        self.assertIs(operators.controller(fake), ctl)
        self.assertTrue(ctl.process.alive, "the same text: the agent stays")

        guide.write_text("Sharp edges.")
        self.assertTrue(ctl.process.alive)
        self.assertFalse(ctl.launch_changed, "nothing reads the disk until a turn is on its way")
        self.assertIs(operators.controller(fake), ctl)
        self.assertFalse(ctl.process.alive, "a new text stops the agent, so the next start has it")
        self.assertEqual(ctl.launch_settings()["settings"]["style_guide"], "Sharp edges.")

    def test_a_changed_import_restarts_the_agent_too(self):
        base = self.user_dir / "base.md"
        base.write_text("Worn edges.")
        top = self.user_dir / "style.md"
        top.write_text("@base.md")
        self.scene.whittle.style_file = str(top)
        ctl = self.make_controller()
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        self.start_ready(ctl)
        base.write_text("Sharp edges.")
        operators.controller(str(ctl.process.fake_script))
        self.assertFalse(ctl.process.alive)

    def test_a_running_turn_does_not_read_the_guide(self):
        guide = self.user_dir / "style.md"
        guide.write_text("Worn edges.")
        self.scene.whittle.style_file = str(guide)
        ctl = self.make_controller()
        turn.set_current(ctl)
        self.addCleanup(turn.set_current, None)
        with mock.patch.object(operators, "busy", return_value=True), \
                mock.patch.object(style, "load_guide") as load:
            self.assertIs(operators.controller(str(ctl.process.fake_script)), ctl)
        load.assert_not_called()

    def test_the_session_gets_the_text_and_the_request_the_path(self):
        guide = self.user_dir / "style.md"
        guide.write_text("Costs $5 and ${poly_budget}.")
        self.scene.whittle.style_file = str(guide)
        ctl = self.make_controller()
        self.start_ready(ctl)
        ctl.start_session()
        settings = ctl.session_starts[-1]["settings"]
        self.assertEqual((settings["style_guide"], settings["style_incomplete"]),
                         ("Costs $5 and ${poly_budget}.", False))
        self.assertIn("Costs $5 and ${poly_budget}.", prompt.build(settings))

    def test_an_amend_does_not_read_the_guide(self):
        guide = self.user_dir / "style.md"
        guide.write_text("Worn.")
        self.scene.whittle.style_file = str(guide)
        ctl = self.make_controller()
        prefs._guides.clear()
        ctl.turn_id, ctl._accepted, ctl.bundle = "n0001", True, SimpleNamespace(request=SimpleNamespace(parent="n0000", target=[]))
        ctl.process = mock.MagicMock(bridge=mock.MagicMock(interrupted=False))
        ctl._from_sketch = True
        with mock.patch.object(style, "load_guide", side_effect=AssertionError("read for an amend")), \
                mock.patch.object(turn.sketch, "pending_count", return_value=1), \
                mock.patch.object(turn.sketch, "stamp_pending"), \
                mock.patch.object(turn.bundle, "write_bundle") as write:
            ctl.amend("And the lid.")
        write.assert_called_once()

    def test_a_cold_start_uses_the_scene_that_sent(self):
        other = bpy.data.scenes.new("Other window")
        self.addCleanup(bpy.data.scenes.remove, other)
        (self.user_dir / "this.md").write_text("This scene.")
        (self.user_dir / "other.md").write_text("The other scene.\n@gone.md")
        self.scene.whittle.style_file = str(self.user_dir / "this.md")
        other.whittle.style_file = str(self.user_dir / "other.md")
        prefs.refresh_style_guides(other)
        ctl = self.make_controller()
        with mock.patch.object(turn.bundle, "write_bundle"), mock.patch.object(ctl.history, "ensure_root"):
            ctl.run_sketch("Carve.", targets=[], scene=other)
            pump(ctl, lambda: ctl.session_starts, 15.0, "the session to start")
        settings = ctl.session_starts[-1]["settings"]
        self.assertEqual((settings["style_file"], settings["style_guide"], settings["style_incomplete"]),
                         (other.whittle.style_file, "The other scene.", True))
        notes = []
        ctl._local = lambda _name, data: notes.append(data["text"])
        ctl._warn_of_guide("n0001")
        self.assertEqual(notes, [turn.GUIDE_WARNING], "the warning is about the same scene's guide")

    def test_the_conversation_warns_once(self):
        ctl = self.make_controller()
        notes = []
        ctl._local = lambda name, data: notes.append(data["text"])
        with mock.patch.object(prefs, "session_settings", return_value={"style_incomplete": True}):
            ctl._warn_of_guide("n0001")
            ctl._warn_of_guide("n0002")
        self.assertEqual(notes, [turn.GUIDE_WARNING])
        self.assertEqual([e.turn_id for e in ctl.stream.entries() if e.kind == "warning"], ["n0001"])
        with mock.patch.object(prefs, "session_settings", return_value={"style_incomplete": False}):
            ctl._warn_of_guide("n0003")
        with mock.patch.object(prefs, "session_settings", return_value={"style_incomplete": True}):
            ctl._warn_of_guide("n0004")
        self.assertEqual(len(notes), 2, "a guide that broke again says so again")


class StylePathSaveTest(unittest.TestCase):
    """Real saves of // paths in a fresh Blender: the steps are in
    tests/blender/style_path_file.py."""

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        root = Path(os.path.realpath(folder.name))
        cls.root = root / "repo"
        env = {**os.environ, "WHITTLE_USER_DIR": str(root / "user")}
        out = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python",
                              str(REPO / "tests" / "blender" / "style_path_file.py"), "--", str(cls.root)],
                             capture_output=True, text=True, timeout=120, env=env)
        line = next((l for l in out.stdout.splitlines() if l.startswith("RESULT ")), None)
        assert line is not None, out.stdout[-3000:] + out.stderr[-3000:]
        cls.r = json.loads(line[len("RESULT "):])
        cls.moved = {**cls.r["set"], "Scene": "//../../style/base.md", "Windows": "//../../style/base.md",
                     "Inside": "//../../props/local.md"}
        cls.copied = {**cls.r["set"], "Scene": "//../style/base.md", "Windows": "//../style/base.md",
                      "Inside": "//../props/local.md"}

    def test_a_windows_path_reads_on_any_platform(self):
        self.assertEqual(self.r["set"]["Windows"], "//..\\style\\base.md", "the field keeps what was written")
        self.assertEqual(self.r["guide_windows"], self.r["guide"])
        self.assertEqual(self.r["cached_windows"], "Worn edges.", "the last read is found by the text as written")

    def test_saves_in_the_folder_change_nothing(self):
        for step in ("first_save", "plain_save", "same_folder"):
            self.assertEqual(self.r[step], self.r["set"], step)
        for name in ("first", "beside"):
            self.assertEqual(self.r["on_disk"][name]["values"], self.r["set"], name)

    def test_save_as_rewrites_every_scene_with_a_blend_relative_path(self):
        self.assertEqual(self.r["save_as"], self.moved)
        self.assertIsNone(self.r["save_as"]["Unset"], "an unset override stays unset")
        self.assertEqual(self.r["save_as"]["Cleared"], "", "no guide stays no guide")
        self.assertEqual(self.r["on_disk"]["moved"], {"values": self.moved, "guide": "Worn edges."})
        self.assertEqual((self.r["guide_after_save_as"], self.r["guide_windows_after_save_as"],
                          self.r["local_after_save_as"]), ("Worn edges.", "Worn edges.", "Local."))

    def test_the_preferences_default_is_not_rewritten(self):
        self.assertEqual(self.r["preference_default"], "//preference.md")

    def test_save_copy_rewrites_the_copy_only(self):
        self.assertEqual(self.r["copy"], self.r["set"], "the open file stays where it was")
        self.assertTrue(self.r["copy_kept_the_open_file"])
        self.assertEqual(self.r["on_disk"]["copy"], {"values": self.copied, "guide": "Worn edges."})

    def test_a_failed_save_leaves_the_open_file_as_it_was(self):
        self.assertEqual(self.r["failed"], self.r["set"])
        self.assertTrue(self.r["failed_kept_the_open_file"])

    def test_a_save_reads_no_guide_on_the_way(self):
        self.assertEqual(self.r["reads_during_saves"], [0] * 5, "not from save_pre, nor from the property's update")

    def test_a_linked_scene_is_its_own_files(self):
        self.assertEqual(self.r["linked"], "//local.md")
        self.assertEqual(self.r["local_beside_linked"], "//../props/local.md")

    def test_undo_takes_the_steps_it_took_before(self):
        self.assertEqual(self.r["after_undo"]["frame"], 1, "a rewrite adds no step")
        self.assertEqual(self.r["after_redo"]["frame"], 7)

    def test_undo_and_redo_keep_naming_the_same_guide(self):
        self.assertEqual(self.r["after_undo"]["values"], self.moved)
        self.assertEqual(self.r["after_redo"]["values"], self.moved)
        moves = self.r["undo_across_moves"]
        right = {"path": "//../../p/style/a.md", "guide": "Right.", "problems": []}
        for step in ("moved", "undone", "redone", "on_disk"):
            self.assertEqual(moves[step], right, step)

    def test_an_undo_that_keeps_a_scene_does_not_rewrite_it_twice(self):
        self.assertEqual(self.r["undo_across_moves"]["untouched_by_the_undo"],
                         {"path": "//../../../p/style/a.md", "guide": "Right.", "problems": []})

    def test_a_path_set_after_a_move_counts_from_there(self):
        self.assertEqual(self.r["undo_across_moves"]["set_after_the_moves"],
                         {"path": "//local.md", "guide": "Set after the moves.", "problems": []})

    def test_a_file_opened_again_counts_from_where_it_is(self):
        self.assertEqual(self.r["undo_across_moves"]["after_reopening"],
                         {"path": "//../style/a.md", "guide": "Right.", "problems": []})

    def test_a_symlinked_folder_keeps_the_guide(self):
        if self.r["symlink"] is None:
            self.skipTest("no symlinks here")
        self.assertEqual(self.r["symlink"]["into"],
                         {"path": "//../../../work/repo/style/a.md", "guide": "Right.", "problems": []})
        self.assertEqual(self.r["symlink"]["out_of"], {"path": "//../style/a.md", "guide": "Right.", "problems": []})

    def test_a_backslash_in_a_folder_name_survives_a_move(self):
        if self.r["backslash_folder"] is None:
            self.skipTest("a backslash is a separator here")
        self.assertEqual(self.r["backslash_folder"], {"path": str(self.root / "odd\\name" / "g.md"),
                                                      "guide": "Beside.", "problems": []})


class StyleFileTest(FileSettingsCase):
    """Style Notes as a path: resolved by the add-on, cached for the popover."""

    def setUp(self):
        super().setUp()
        self._user = TempUserDir()
        self.folder = self._user.__enter__()
        self.addCleanup(self._user.__exit__, None, None, None)

    def write(self, name: str, text: str):
        path = self.folder / name
        path.write_text(text)
        return path

    def labels(self, layout) -> list[tuple[str, str]]:
        return [(c["text"], c["icon"]) for c in layout.of("label")]

    def test_setting_the_path_reads_the_guide(self):
        self.write("base.md", "Base.")
        top = self.write("style.md", "@base.md\nTop.")
        self.props.style_file = str(top)
        settings = prefs.session_settings()
        self.assertEqual((settings["style_guide"], settings["style_incomplete"]), ("Base.\nTop.", False))
        self.assertEqual(prefs.style_guide(str(top)).names(), ["style.md", "base.md"])

    def test_the_popover_lists_the_files_and_never_reads_the_disk(self):
        self.write("base.md", "Base.")
        top = self.write("style.md", "@base.md\n@gone.md")
        self.props.style_file = str(top)
        with mock.patch.object(style, "load_guide", side_effect=AssertionError("read while drawing")):
            found = self.labels(self.popover())
        self.assertIn(("style.md", "FILE_TEXT"), found)
        self.assertIn(("base.md", "FILE_TEXT"), found)
        problems = [text for text, icon in found if icon == "ERROR" or icon == "BLANK1"]
        self.assertIn("gone.md", " ".join(problems), "the warning is on the panel, not in a tooltip")
        self.assertEqual([i for t, i in found if "@gone.md" in t][0], "ERROR")

    def test_a_path_not_read_yet_says_so(self):
        self.props.style_file = "/styles/chunky.md"
        prefs._guides.clear()
        self.assertIn("Read at the next turn.", self.popover().labels())

    def test_no_path_draws_nothing(self):
        self.props.style_file = ""
        labels = self.popover().labels()
        self.assertNotIn("Read at the next turn.", labels)
        self.assertNotIn("Sent with each turn:", labels)

    def test_reset_reads_the_preferences_path(self):
        PREFS_FILE = self.write("default.md", "From the preferences.")
        self.addCleanup(setattr, PREFS, "style_file", PREFS.style_file)
        PREFS.style_file = str(PREFS_FILE)
        self.props.style_file = str(self.write("own.md", "Own."))
        self.assertEqual(prefs.session_settings()["style_guide"], "Own.")
        self.assertEqual(bpy.ops.whittle.file_setting_reset(key="style_file"), {"FINISHED"})
        self.assertEqual(prefs.session_settings()["style_guide"], "From the preferences.")

    def test_a_relative_path_needs_a_saved_file(self):
        self.assertEqual(bpy.data.filepath, "", "the suite's scene is unsaved")
        self.props.style_file = "//style.md"
        settings = prefs.session_settings()
        self.assertEqual((settings["style_guide"], settings["style_incomplete"]), ("", True))
        self.assertIn("save the file", prefs.style_guide("//style.md").problems[0])

    def test_a_relative_path_follows_the_blend(self):
        self.write("style.md", "Beside the file.")
        with mock.patch.object(bpy.path, "abspath", lambda p: str(self.folder / p[2:])), \
                mock.patch.object(prefs, "bpy", SimpleNamespace(data=SimpleNamespace(filepath="/x/a.blend"),
                                                                path=bpy.path, context=bpy.context)):
            guide = prefs.read_style_guide("//style.md")
            self.assertEqual(guide.text, "Beside the file.")
            self.assertIs(prefs.style_guide("//style.md"), guide)
        self.assertIsNone(prefs.style_guide("//style.md"), "under another .blend it is another file")

    def test_a_missing_file_is_a_problem_not_an_error(self):
        self.props.style_file = str(self.folder / "gone.md")
        settings = prefs.session_settings()
        self.assertEqual((settings["style_guide"], settings["style_incomplete"]), ("", True))
        self.assertIn(style.GUIDE_INCOMPLETE, prompt.build(settings))

    def after_load(self):
        """The load handler, with the file's chats and history left alone."""
        with mock.patch.object(addon.chats, "after_load"), mock.patch.object(addon.history, "sync_from_scene"), \
                mock.patch.object(addon.history, "invalidate"):
            addon._after_load()

    def test_opening_a_file_never_reads_the_path_it_stores(self):
        top = self.write("style.md", "Theirs.")
        self.props.style_file = str(top)
        prefs._guides.clear()
        self.addCleanup(setattr, PREFS, "style_file", PREFS.style_file)
        PREFS.style_file = str(self.write("default.md", "Mine."))
        with mock.patch.object(style, "load_guide", wraps=style.load_guide) as load:
            self.after_load()
        self.assertEqual([c.args[0] for c in load.call_args_list], [PREFS.style_file], "the user's own path only")
        self.assertIsNone(prefs.style_guide(str(top)))
        self.assertIn("Read at the next turn.", self.popover().labels())

    def test_a_preference_relative_to_the_file_waits_too(self):
        # The file decides where it leads, and what that file imports.
        self.addCleanup(setattr, PREFS, "style_file", PREFS.style_file)
        PREFS.style_file = "//style.md"
        with mock.patch.object(style, "load_guide") as load, \
                mock.patch.object(prefs, "bpy", SimpleNamespace(data=SimpleNamespace(filepath="/x/a.blend"),
                                                                path=bpy.path, context=bpy.context)):
            self.after_load()
        load.assert_not_called()

    def test_saving_reads_the_files_path(self):
        top = self.write("style.md", "Worn.")
        self.props.style_file = str(top)
        prefs._guides.clear()
        with mock.patch.object(addon.chats, "after_save"):
            addon._after_save()
        self.assertEqual(prefs.style_guide(str(top)).text, "Worn.", "saving is the user's own act")

    def test_read_now_shows_what_a_file_would_send(self):
        self.write("base.md", "Base.")
        top = self.write("style.md", "@base.md")
        self.props.style_file = str(top)
        prefs._guides.clear()
        buttons = self.popover().operators("whittle.style_guide_read")
        self.assertEqual([b["props"].path for b in buttons], [str(top)])
        self.assertEqual(bpy.ops.whittle.style_guide_read(path=str(top)), {"FINISHED"})
        layout = self.popover()
        self.assertEqual(layout.operators("whittle.style_guide_read"), [])
        self.assertIn(("base.md", "FILE_TEXT"), self.labels(layout))

    def test_a_path_not_read_is_read_before_it_is_sent(self):
        top = self.write("style.md", "Worn.\n@gone.md")
        self.props.style_file = str(top)
        prefs._guides.clear()
        settings = prefs.session_settings()
        self.assertEqual((settings["style_guide"], settings["style_incomplete"]), ("Worn.", True),
                         "not read is not the same as no guide")

    def test_drawing_never_reads_an_unread_path(self):
        self.props.style_file = str(self.write("style.md", "Worn."))
        prefs._guides.clear()
        with mock.patch.object(style, "load_guide", side_effect=AssertionError("read while drawing")):
            self.popover()

    def test_a_refresh_reads_each_path_once(self):
        self.props.style_file = str(self.write("style.md", "Worn."))
        self.addCleanup(setattr, PREFS, "style_file", PREFS.style_file)
        PREFS.style_file = ""
        with mock.patch.object(style, "load_guide", wraps=style.load_guide) as load:
            prefs._guides.clear()
            prefs.refresh_style_guides()
        self.assertEqual(load.call_count, 1)

    def test_a_long_list_is_cut_short(self):
        count = prefs.GUIDE_ROWS + 25
        prefs._guides[prefs._guide_key("/s/style.md")] = style.Guide(
            "text", tuple(f"/s/{i}.md" for i in range(count)), tuple(f"Problem {i}." for i in range(count)))
        self.props.style_file = "/s/style.md"
        prefs._guides[prefs._guide_key("/s/style.md")] = style.Guide(
            "text", tuple(f"/s/{i}.md" for i in range(count)), tuple(f"Problem {i}." for i in range(count)))
        found = self.labels(self.popover())
        self.assertEqual(len([t for t, i in found if i == "FILE_TEXT"]), prefs.GUIDE_ROWS)
        self.assertEqual(len([t for t, i in found if i == "ERROR"]), prefs.GUIDE_ROWS)
        self.assertIn(("and 25 more files", "BLANK1"), found)
        self.assertIn(("and 25 more problems", "BLANK1"), found)
        self.assertEqual(len(prefs.style_guide("/s/style.md").files), count, "the guide keeps them all")

    def test_a_short_list_is_whole(self):
        self.props.style_file = "/s/style.md"
        prefs._guides[prefs._guide_key("/s/style.md")] = style.Guide(
            "text", tuple(f"/s/{i}.md" for i in range(prefs.GUIDE_ROWS)))
        found = self.labels(self.popover())
        self.assertEqual(len([t for t, i in found if i == "FILE_TEXT"]), prefs.GUIDE_ROWS)
        self.assertFalse([t for t, _i in found if " more " in t])

    def test_only_a_few_reads_are_kept(self):
        for i in range(prefs.MAX_GUIDES_KEPT + 3):
            prefs.read_style_guide(f"/styles/{i}.md")
        self.assertEqual(len(prefs._guides), prefs.MAX_GUIDES_KEPT)
        self.assertIsNotNone(prefs.style_guide(f"/styles/{prefs.MAX_GUIDES_KEPT + 2}.md"))

