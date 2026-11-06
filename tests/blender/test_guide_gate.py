# SPDX-License-Identifier: GPL-3.0-or-later
"""The question before a style guide this install has not approved goes out:
which paths ask, what approves, that nothing reads an unapproved guide, the
box over the composer, every route that sends, and the warning for a file's
absolute path."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.test_chats import ChatCase
from tests.blender.test_file_settings import PREFS, FileSettingsCase
from tests.blender.test_keys import press_enter
from tests.blender.ui_helpers import RecordingLayout
from whittle import protocol, style
import whittle.addon as addon
from whittle.addon import history, operators, prefs, props, turn, ui

STORE = props.FILE_SETTINGS["style_file"]


def saved_as(blend) -> mock._patch:
    """The open file as if saved at blend, for code that only asks where it is."""
    return mock.patch.object(prefs, "bpy", SimpleNamespace(data=SimpleNamespace(filepath=str(blend), scenes=bpy.data.scenes),
                                                           path=bpy.path, context=bpy.context))


class GateCase(FileSettingsCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(prefs.forget_approvals)
        prefs.forget_approvals()
        # PREFS is shared with the file's other tests.
        self.addCleanup(setattr, PREFS, "style_file", PREFS.style_file)
        PREFS.style_file = ""
        self.guide = self.write("style.md", "Theirs.")

    def write(self, name: str, text: str) -> Path:
        path = self.folder / name
        path.write_text(text)
        return path

    def arrive(self, path) -> str:
        """The file holds path as a load brings it: nothing set it here."""
        self.scene.whittle[STORE] = str(path)
        return str(path)

    def draw(self, ctl=None) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_main(layout, ui.Ctx(scene=self.scene, hist=None, ctl=ctl, comparing=None, width=240))
        return layout


class WhichPathsTest(GateCase):
    def held(self) -> str:
        return prefs.held_guide(self.scene)

    def test_a_files_own_path_asks(self):
        self.assertEqual(self.held(), "")
        path = self.arrive(self.guide)
        self.assertEqual(self.held(), path)

    def test_a_relative_path_in_a_saved_file_asks(self):
        self.arrive("//style.md")
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(self.held(), "//style.md")

    def test_a_relative_preference_asks_as_the_file_decides_where_it_leads(self):
        PREFS.style_file = "//style.md"
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(self.held(), "//style.md")

    def test_the_users_own_preference_never_asks(self):
        for path in (str(self.guide), "~/style.md"):
            PREFS.style_file = path
            self.assertEqual(self.held(), "", path)
            self.assertFalse(prefs.guide_held(path, per_file=False))

    def test_an_empty_path_never_asks(self):
        self.arrive("")
        self.assertEqual(self.held(), "")
        self.arrive("   ")
        self.assertEqual(self.held(), "")

    def test_a_path_that_cannot_be_read_as_it_stands_never_asks(self):
        self.arrive("style.md")
        self.assertEqual(self.held(), "", "load_guide refuses it unread")
        self.arrive("//style.md")
        self.assertEqual(self.held(), "", "an unsaved file: it leads nowhere yet")

    def test_a_file_naming_the_users_own_preference_is_their_guide(self):
        PREFS.style_file = str(self.guide)
        self.arrive(self.guide)
        self.assertEqual(self.held(), "")

    def test_another_scene_answers_for_itself(self):
        other = bpy.data.scenes.new("Other")
        self.addCleanup(bpy.data.scenes.remove, other)
        self.arrive(self.guide)
        self.assertEqual(prefs.held_guide(other), "")

    def test_the_key_is_the_same_for_the_same_file(self):
        key = prefs.guide_key(str(self.guide))
        (self.folder / "sub").mkdir()
        with saved_as(self.folder / "sub" / "a.blend"):
            self.assertEqual(prefs.guide_key("//../style.md"), key)
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(prefs.guide_key("//style.md"), key)

    def test_a_question_reaches_only_the_open_files_folder(self):
        self.arrive("//link/../secret/style.md")
        with saved_as(self.folder / "a.blend"):
            self.held()
            with mock.patch("os.path.realpath", side_effect=AssertionError("touched the disk")), \
                    mock.patch("os.lstat", side_effect=AssertionError("touched the disk")), \
                    mock.patch("os.stat", side_effect=AssertionError("touched the disk")):
                self.held()
                prefs.guide_location("//link/../secret/style.md")

    def test_a_link_with_a_dotdot_after_it_asks(self):
        # //link/../style.md reads secret/style.md through the link, whatever
        # the text says: an approval of the file beside the .blend says nothing.
        link = self.folder / "link"
        (self.folder / "secret" / "deep").mkdir(parents=True)
        (self.folder / "secret" / "style.md").write_text("@private.txt")
        (self.folder / "secret" / "private.txt").write_text("Private.")
        try:
            link.symlink_to(self.folder / "secret" / "deep", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"cannot make a symlink here: {exc}")
        self.arrive("//link/../style.md")
        with saved_as(self.folder / "a.blend"):
            self.assertTrue(prefs.approve_guide("//style.md"))
            self.assertEqual(self.held(), "//link/../style.md")
            self.assertIn(str(link), prefs.guide_location("//link/../style.md"), "and the box shows it")
            self.assertEqual(prefs.session_settings(self.scene)["style_guide"], "")
            self.assertEqual(bpy.ops.whittle.style_guide_read(path="//link/../style.md"), {"FINISHED"})
            self.assertEqual(prefs.style_guide("//link/../style.md").text, "Private.", "Read Now tells the truth")

    def test_nor_does_a_users_preference_pass_it(self):
        link = self.folder / "link"
        (self.folder / "secret").mkdir()
        try:
            link.symlink_to(self.folder / "secret", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"cannot make a symlink here: {exc}")
        PREFS.style_file = str(self.guide)
        self.arrive(f"{link}/../style.md")
        self.assertEqual(self.held(), f"{link}/../style.md")

    def test_a_file_opened_through_a_link_counts_from_where_it_is(self):
        # The read walks up from the real folder, so the key has to.
        real = self.folder / "deep" / "shots"
        real.mkdir(parents=True)
        (self.folder / "deep" / "style.md").write_text("Theirs.")
        try:
            (self.folder / "shots").symlink_to(real, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"cannot make a symlink here: {exc}")
        self.arrive("//../style.md")
        self.assertTrue(prefs.approve_keys({prefs.guide_key(str(self.guide))}))
        with saved_as(self.folder / "shots" / "a.blend"):
            self.assertEqual(self.held(), "//../style.md", "it does not lead to the approved file")
            self.assertEqual(prefs.guide_location("//../style.md"), str(self.folder / "deep" / "style.md"))


class ApprovalTest(GateCase):
    def test_setting_the_path_approves_it(self):
        self.props.style_file = str(self.guide)
        self.assertEqual(prefs.held_guide(self.scene), "")
        self.assertEqual(style.read_approved(self.folder), {prefs.guide_key(str(self.guide))})

    def test_setting_the_preference_approves_it(self):
        with saved_as(self.folder / "a.blend"):
            prefs._style_file_set(None, "//style.md", "", True)
            self.arrive("//style.md")
            self.assertEqual(prefs.held_guide(self.scene), "")

    def test_confirming_the_field_unchanged_approves_nothing(self):
        path = self.arrive(self.guide)
        with mock.patch.object(style, "load_guide", side_effect=AssertionError("read")):
            self.props.style_file = path
        self.assertEqual(prefs.held_guide(self.scene), path)
        self.assertFalse((self.folder / style.APPROVALS_NAME).exists())

    def test_nor_does_an_unset_field_showing_a_relative_default(self):
        PREFS.style_file = "//style.md"
        with saved_as(self.folder / "a.blend"), mock.patch.object(style, "load_guide",
                                                                  side_effect=AssertionError("read")):
            self.props.style_file = "//style.md"
            self.assertEqual(prefs.held_guide(self.scene), "//style.md")
        self.assertNotIn(STORE, self.props, "and it pins nothing on the file")

    def test_changing_a_held_path_is_a_choice(self):
        self.arrive(self.write("theirs.md", "Theirs."))
        self.props.style_file = str(self.guide)
        self.assertEqual(prefs.held_guide(self.scene), "")
        self.assertEqual(prefs.session_settings(self.scene)["style_guide"], "Theirs.")

    def test_the_preferences_field_unchanged_approves_nothing(self):
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(prefs._style_file_set(None, "//style.md", "//style.md", True), "//style.md")
            self.assertFalse((self.folder / style.APPROVALS_NAME).exists())
            with mock.patch.object(style, "load_guide", side_effect=AssertionError("read")):
                prefs._style_file_changed(SimpleNamespace(style_file="//style.md"), None)

    def test_a_load_approves_nothing(self):
        self.arrive(self.guide)
        with mock.patch.object(addon.chats, "after_load"), mock.patch.object(addon.history, "sync_from_scene"), \
                mock.patch.object(addon.history, "invalidate"):
            addon._after_load()
        self.assertTrue(prefs.held_guide(self.scene))
        self.assertFalse((self.folder / style.APPROVALS_NAME).exists())

    def test_nothing_goes_in_the_file(self):
        self.arrive(self.guide)
        before = dict(self.props.items())
        self.assertEqual(bpy.ops.whittle.style_guide_approve(), {"FINISHED"})
        self.assertEqual(dict(self.props.items()), before)

    def test_it_lasts_past_this_blender(self):
        self.arrive(self.guide)
        bpy.ops.whittle.style_guide_approve()
        prefs.forget_approvals()
        self.assertEqual(prefs.held_guide(self.scene), "", "read back from the user folder")

    def test_one_approval_covers_every_file_leading_there(self):
        self.arrive(self.guide)
        bpy.ops.whittle.style_guide_approve()
        self.arrive("//../style.md")
        with saved_as(self.folder / "sub" / "a.blend"):
            self.assertEqual(prefs.held_guide(self.scene), "")

    def test_another_blenders_approval_is_kept_and_found(self):
        other = prefs.guide_key(str(self.write("other.md", "Other.")))
        prefs.held_guide(self.scene)
        style.write_approved(self.folder, {other})
        self.arrive(self.guide)
        bpy.ops.whittle.style_guide_approve()
        self.assertEqual(style.read_approved(self.folder), {other, prefs.guide_key(str(self.guide))})

    def test_a_record_that_cannot_be_read_asks_again(self):
        self.arrive(self.guide)
        bpy.ops.whittle.style_guide_approve()
        (self.folder / style.APPROVALS_NAME).write_text("{")
        prefs.forget_approvals()
        self.assertTrue(prefs.held_guide(self.scene))

    def test_a_record_that_cannot_be_written_lasts_until_blender_closes(self):
        self.arrive(self.guide)
        self.addCleanup(prefs._unrecorded.clear)
        with mock.patch.object(style, "write_approved", side_effect=OSError("read-only")):
            self.assertFalse(prefs.approve_guide(str(self.guide)))
            self.assertEqual(prefs.held_guide(self.scene), "")
            with mock.patch.object(addon.chats, "after_load"), mock.patch.object(addon.history, "sync_from_scene"), \
                    mock.patch.object(addon.history, "invalidate"):
                addon._after_load()
            self.assertEqual(prefs.held_guide(self.scene), "", "past a load in the same Blender")

    def test_the_next_write_records_what_could_not_be(self):
        other = str(self.write("other.md", "Other."))
        with mock.patch.object(style, "write_approved", side_effect=OSError("read-only")):
            prefs.approve_guide(str(self.guide))
        self.assertTrue(prefs.approve_guide(other))
        self.assertEqual(style.read_approved(self.folder), {prefs.guide_key(other), prefs.guide_key(str(self.guide))})
        self.assertEqual(prefs._unrecorded, {})

    def test_an_approval_is_not_lost_to_a_later_versions_record(self):
        later = {"format": style.APPROVALS_FORMAT, "version": 2, "guides": ["/keep/me.md"]}
        (self.folder / style.APPROVALS_NAME).write_text(json.dumps(later))
        self.addCleanup(prefs._unrecorded.clear)
        path = self.arrive(self.guide)
        self.assertEqual(prefs.held_guide(self.scene), path)
        self.assertFalse(prefs.approve_guide(path), "the operator warns")
        self.assertEqual(prefs.held_guide(self.scene), "")
        self.assertEqual(json.loads((self.folder / style.APPROVALS_NAME).read_text()), later)

    def test_a_deeply_nested_record_only_asks(self):
        (self.folder / style.APPROVALS_NAME).write_text("[" * 200000)
        path = self.arrive(self.guide)
        self.assertEqual(prefs.held_guide(self.scene), path)
        self.assertEqual(bpy.ops.whittle.style_guide_approve(), {"FINISHED"})
        self.assertEqual(prefs.held_guide(self.scene), "")

    def test_a_path_that_is_not_utf8_is_approved_like_any_other(self):
        path = self.arrive(f"{self.folder}/caf\udce9.md")
        self.assertEqual(prefs.held_guide(self.scene), path)
        self.assertEqual(bpy.ops.whittle.style_guide_approve(), {"FINISHED"})
        self.assertEqual(prefs.held_guide(self.scene), "")
        prefs.forget_approvals()
        self.assertEqual(prefs.held_guide(self.scene), "", "from the record")
        self.arrive(self.guide)
        self.assertEqual(bpy.ops.whittle.style_guide_approve(), {"FINISHED"}, "and the next one still records")
        self.assertEqual(len(style.read_approved(self.folder)), 2)

    def test_a_relative_path_set_and_replaced_before_the_first_save_is_not_approved(self):
        self.props.style_file = "//typo.md"
        self.props.style_file = ""
        self.props.style_file = "//kept.md"
        with saved_as(self.folder / "a.blend"):
            prefs.settle_unsaved_approvals()
            self.assertEqual(style.read_approved(self.folder), {prefs.guide_key("//kept.md")})
        self.assertEqual(prefs._approved_unsaved, set())

    def test_a_relative_preference_replaced_before_the_first_save_is_not_approved(self):
        prefs._style_file_set(None, "//typo.md", "", True)
        PREFS.style_file = "//typo.md"
        with saved_as(self.folder / "a.blend"):
            prefs.settle_unsaved_approvals()
            kept = {prefs.guide_key("//typo.md")}
        self.assertEqual(style.read_approved(self.folder), kept, "still set, so approved")
        prefs._style_file_set(None, "//typo2.md", "", True)
        PREFS.style_file = "//other.md"
        with saved_as(self.folder / "b.blend"):
            prefs.settle_unsaved_approvals()
        self.assertEqual(style.read_approved(self.folder), kept)

    def test_the_record_is_read_once_and_not_by_a_redraw(self):
        self.arrive(self.guide)
        prefs.held_guide(self.scene)
        with mock.patch.object(style, "read_approved", side_effect=AssertionError("read in a redraw")):
            self.draw()
            prefs.held_guide(self.scene)


class NoReadTest(GateCase):
    """load_guide is the one way to the disk: counted through every route."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(style, "load_guide", wraps=style.load_guide)
        self.load = patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.arrive(self.guide)

    def test_a_refresh_leaves_it(self):
        prefs.refresh_style_guides()
        prefs.refresh_style_guides(self.scene)
        self.load.assert_not_called()

    def test_the_settings_leave_it(self):
        settings = prefs.session_settings(self.scene)
        self.assertEqual((settings["style_guide"], settings["style_incomplete"]), ("", False))
        self.load.assert_not_called()

    def test_a_refresh_still_reads_the_users_own(self):
        PREFS.style_file = str(self.write("mine.md", "Mine."))
        prefs.refresh_style_guides()
        self.assertEqual([c.args[0] for c in self.load.call_args_list], [PREFS.style_file])

    def test_a_save_leaves_it(self):
        with mock.patch.object(addon.chats, "after_save"), mock.patch.object(addon.chats, "before_save"):
            addon._before_save(str(self.folder / "a.blend"))
            addon._after_save(str(self.folder / "a.blend"))
        self.load.assert_not_called()

    def test_a_reset_to_a_held_default_leaves_it(self):
        PREFS.style_file = "//style.md"
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(bpy.ops.whittle.file_setting_reset(key="style_file"), {"FINISHED"})
        self.load.assert_not_called()

    def test_drawing_leaves_it(self):
        self.draw()
        self.load.assert_not_called()

    def test_read_now_reads_and_approves_nothing(self):
        self.assertEqual(bpy.ops.whittle.style_guide_read(path=self.path), {"FINISHED"})
        self.load.assert_called_once()
        self.assertEqual(prefs.style_guide(self.path).text, "Theirs.")
        self.assertEqual(prefs.held_guide(self.scene), self.path)
        self.assertEqual(prefs.session_settings(self.scene)["style_guide"], "", "listed, and still not sent")

    def test_use_this_guide_reads_it(self):
        bpy.ops.whittle.style_guide_approve()
        self.load.assert_called_once()
        self.assertEqual(prefs.session_settings(self.scene)["style_guide"], "Theirs.")


class GateBoxTest(GateCase):
    def test_a_box_over_the_composer(self):
        path = self.arrive(self.guide)
        self.props.prompt = "Add a lid."
        layout = self.draw()
        self.assertIn(ui.GUIDE_TITLE, layout.labels())
        self.assertIn("go to Claude", layout.text())
        self.assertIn(os.path.basename(path), "".join(layout.labels()), "a long path wraps")
        self.assertEqual([c["idname"] for c in layout.operators()
                          if c["idname"].startswith("whittle.style_guide")],
                         ["whittle.style_guide_approve", "whittle.style_guide_read", "whittle.style_guide_skip"])
        (read,) = layout.operators("whittle.style_guide_read")
        self.assertEqual(read["props"].path, path)
        (send,) = layout.operators("whittle.submit")
        self.assertFalse(layout.is_enabled(send))

    def test_the_box_shows_the_absolute_path_of_a_relative_one(self):
        self.arrive("//../style.md")
        with saved_as(self.folder / "sub" / "a.blend"):
            lines = "".join(self.draw().labels())
        self.assertIn(str(self.guide), lines)

    def test_the_box_says_who_names_the_guide(self):
        self.arrive(self.guide)
        self.assertIn("This file names it", " ".join(self.draw().labels()))
        props.reset_file_setting(self.scene, "style_file")
        PREFS.style_file = "//style.md"
        with saved_as(self.folder / "a.blend"):
            lines = " ".join(self.draw().labels())
        self.assertNotIn("This file names", lines)
        self.assertIn("Your Defaults name it", lines)

    def test_more_from_elsewhere_than_rows_shows_the_count(self):
        elsewhere = self.folder / "oth"
        elsewhere.mkdir()
        names = [f"a{i:02}.md" for i in range(12)] + ["z-private.md"]
        for name in names:
            (elsewhere / name).write_text("x")
        (self.folder / "pack").mkdir()
        self.arrive(self.write("pack/top.md", "\n".join(f"@../oth/{name}" for name in names)))
        path = str(self.folder / "pack" / "top.md")
        bpy.ops.whittle.style_guide_read(path=path)
        labels = self.draw().labels()
        self.assertFalse([text for text in labels if "z-private" in text], "hidden behind the rows")
        self.assertIn("and 4 more files", labels)

    def test_read_now_lists_the_files(self):
        self.write("base.md", "Base.")
        path = self.arrive(self.write("top.md", "@base.md\n@gone.md"))
        bpy.ops.whittle.style_guide_read(path=path)
        layout = self.draw()
        self.assertIn(ui.GUIDE_FILES, layout.labels())
        self.assertIn("base.md", layout.labels())
        self.assertIn("gone.md", layout.text(), "and what is missing")
        self.assertTrue(layout.operators("whittle.style_guide_approve"), "the question stands")

    def test_no_box_once_approved(self):
        self.arrive(self.guide)
        bpy.ops.whittle.style_guide_approve()
        self.assertNotIn(ui.GUIDE_TITLE, self.draw().labels())
        self.assertFalse(bpy.ops.whittle.style_guide_approve.poll(), "never asked again")

    def test_no_box_during_a_turn(self):
        self.arrive(self.guide)
        with mock.patch.object(ui.Ctx, "busy", True):
            self.assertNotIn(ui.GUIDE_TITLE, self.draw().labels())

    def test_going_without_it(self):
        self.arrive(self.guide)
        self.assertEqual(bpy.ops.whittle.style_guide_skip(), {"FINISHED"})
        self.assertEqual(props.file_settings(self.scene)["style_file"], "", "no guide for this file, set")
        self.assertEqual(prefs.held_guide(self.scene), "")
        self.assertFalse(style.read_approved(self.folder), "and nothing approved")
        self.assertEqual(prefs.session_settings(self.scene)["style_guide"], "")

    def test_going_without_a_held_default_overrides_it_for_this_file(self):
        PREFS.style_file = "//style.md"
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(bpy.ops.whittle.style_guide_skip(), {"FINISHED"})
            self.assertEqual(prefs.held_guide(self.scene), "")

    def test_a_linked_scene_says_it_will_not_keep(self):
        self.arrive(self.guide)
        reports = []
        context = SimpleNamespace(scene=SimpleNamespace(whittle=self.props, library=object()))
        operator = SimpleNamespace(report=lambda kind, text: reports.append((kind, text)))
        operators.WHITTLE_OT_style_guide_skip.execute(operator, context)
        self.assertEqual(reports, [({"WARNING"}, operators.LINKED_SCENE)])
        self.arrive(self.guide)
        operator.key = "style_file"
        context = SimpleNamespace(scene=SimpleNamespace(whittle=self.props, library=object()), area=None)
        with mock.patch.object(props, "reset_file_setting"), mock.patch.object(prefs, "refresh_style_guides"):
            operators.WHITTLE_OT_file_setting_reset.execute(operator, context)
        self.assertEqual(reports[1:], [({"WARNING"}, operators.LINKED_SCENE)])

    def test_the_popover_says_it_is_held(self):
        path = self.arrive(self.guide)
        layout = self.popover()
        self.assertIn(prefs.HELD_NOTE, layout.labels())
        self.assertNotIn("Read at the next turn.", layout.labels(), "no turn will read it")
        self.assertEqual([b["props"].path for b in layout.operators("whittle.style_guide_read")], [path])
        bpy.ops.whittle.style_guide_read(path=path)
        labels = self.popover().labels()
        self.assertIn("Would be sent:", labels)
        self.assertNotIn("Sent with each turn:", labels)


class AbsoluteWarningTest(GateCase):
    def warnings(self) -> list[str]:
        return [line for line in self.popover().labels() if "travel" in line]

    def test_a_saved_files_absolute_path_warns(self):
        self.props.style_file = str(self.guide)
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(prefs.absolute_guide_warning(self.scene), prefs.ABSOLUTE_GUIDE)
            with mock.patch.object(ui.prefs, "absolute_guide_warning", wraps=prefs.absolute_guide_warning):
                self.assertTrue(self.warnings())

    def test_a_windows_path_warns_on_any_platform(self):
        self.arrive("C:\\repo\\style.md")
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(prefs.absolute_guide_warning(self.scene), prefs.ABSOLUTE_GUIDE)

    def test_an_unsaved_file_has_the_first_save_to_come(self):
        self.props.style_file = str(self.guide)
        self.assertEqual(prefs.absolute_guide_warning(self.scene), "")
        self.assertEqual(self.warnings(), [])

    def test_a_path_that_travels_does_not_warn(self):
        for path in ("//style.md", "~/style.md", ""):
            self.arrive(path)
            with saved_as(self.folder / "a.blend"):
                self.assertEqual(prefs.absolute_guide_warning(self.scene), "", path)

    def test_the_preferences_default_is_not_the_files_to_carry(self):
        PREFS.style_file = str(self.guide)
        with saved_as(self.folder / "a.blend"):
            self.assertEqual(prefs.absolute_guide_warning(self.scene), "")

    def test_it_touches_no_disk(self):
        self.arrive(self.guide)
        with saved_as(self.folder / "a.blend"), mock.patch("os.stat", side_effect=AssertionError("touched the disk")), \
                mock.patch.object(style, "load_guide", side_effect=AssertionError("read")):
            prefs.absolute_guide_warning(self.scene)


class SendRoutesTest(ChatCase):
    """Every way to send, with a file holding a guide nothing approved."""

    def setUp(self):
        super().setUp()
        self.addCleanup(prefs.forget_approvals)
        prefs.forget_approvals()
        self.addCleanup(props.reset_file_setting, self.scene, "style_file")
        self.addCleanup(prefs._guides.clear)
        self.guide = self.user_dir / "style.md"
        self.guide.write_text("Theirs.")
        patcher = mock.patch.object(style, "load_guide", wraps=style.load_guide)
        self.load = patcher.start()
        self.addCleanup(patcher.stop)

    def arrive(self) -> None:
        self.scene.whittle[STORE] = str(self.guide)

    def refused(self) -> None:
        """Every route is refused, the draft stays and nothing read the guide."""
        self.assertEqual(self.props.prompt, "Add a lid.")
        self.load.assert_not_called()

    def test_send(self):
        self.arrive()
        self.props.prompt = "Add a lid."
        self.assertFalse(bpy.ops.whittle.submit.poll(), "its tooltip says why")
        with self.assertRaisesRegex(RuntimeError, operators.GUIDE_HELD):
            operators.submit_sketch(bpy.context, self.fake)
        self.refused()

    def test_the_tooltip_says_why(self):
        self.arrive()
        with self.assertRaisesRegex(RuntimeError, operators.GUIDE_HELD):
            bpy.ops.whittle.submit()

    def test_the_send_key(self):
        self.arrive()
        self.props.prompt = "Add a lid."
        with mock.patch.object(operators, "submit_sketch") as submit:
            self.assertEqual(bpy.ops.whittle.send_key(), {"CANCELLED"})
        submit.assert_not_called()
        self.refused()

    def test_enter(self):
        # Enter in the Ask Claude popup is this too: guide_gate presses it there.
        self.arrive()
        self.props.prompt = "Add a lid."
        with mock.patch.object(operators, "submit_sketch") as submit:
            self.assertEqual(press_enter(), ({"PASS_THROUGH"}, []))
        submit.assert_not_called()
        self.refused()

    def test_retry_changes_nothing_first(self):
        ctl, node = self.send("Make the crate bigger.")
        history.active().tree.node(node).status = "failed"
        current = history.active().current
        self.load.reset_mock()
        self.arrive()
        self.assertFalse(operators.can_retry(history.active(), ctl, node), "the button is disabled")
        with self.assertRaisesRegex(RuntimeError, operators.GUIDE_HELD):
            operators.retry(bpy.context, node, self.fake)
        self.assertEqual(history.active().current, current, "no branch was taken")
        self.load.assert_not_called()

    def test_run_bundle(self):
        self.arrive()
        with self.assertRaisesRegex(RuntimeError, operators.GUIDE_HELD):
            operators.run_bundle(bpy.context, self.fake)
        self.load.assert_not_called()

    def test_a_controller_made_some_other_way_still_has_no_guide(self):
        # Start Agent, a start point: no turn, but they make a controller.
        self.arrive()
        ctl = operators.controller(self.fake)
        self.controllers.append(ctl)
        self.assertEqual(ctl.commands.settings["style_guide"], "")
        self.load.assert_not_called()

    def test_amend_reads_nothing(self):
        ctl, _node = self.send("Make the crate bigger.")
        self.load.reset_mock()
        self.arrive()
        ctl.turn_id, ctl._accepted = "n0009", True
        ctl.bundle = SimpleNamespace(request=SimpleNamespace(parent="n0001", target=[]))
        ctl._from_sketch = True
        real = ctl.process
        self.addCleanup(setattr, ctl, "process", real)
        ctl.process = mock.MagicMock(bridge=mock.MagicMock(interrupted=False))
        with mock.patch.object(turn.bundle, "write_bundle"), mock.patch.object(turn.sketch, "pending_count", return_value=1), \
                mock.patch.object(turn.sketch, "stamp_pending"):
            ctl.amend("And the lid.")
        self.load.assert_not_called()

    def test_answer_reads_nothing(self):
        ctl, _node = self.send("Make the crate bigger.")
        self.load.reset_mock()
        self.arrive()
        ctl.question = {"question": "Which wood?"}
        real = ctl.process
        self.addCleanup(setattr, ctl, "process", real)
        ctl.process = mock.MagicMock(bridge=mock.MagicMock(deferred={"c1": protocol.Method.ASK}))
        self.props.ask_answer = "Oak."
        self.assertTrue(operators.answer(bpy.context))
        ctl.process.bridge.resolve.assert_called_once()
        self.assertEqual(self.props.ask_answer, "")
        self.load.assert_not_called()

    def test_the_turn_runs_with_the_guide_once_approved(self):
        self.arrive()
        self.assertEqual(bpy.ops.whittle.style_guide_approve(), {"FINISHED"})
        ctl, node = self.send("Add a lid.")
        self.assertEqual(ctl.session_starts[-1]["settings"]["style_guide"], "Theirs.")
        self.assertEqual(json.loads((ctl.session.request_dir(node) / "request.json").read_text())
                         ["settings"]["style_file"], str(self.guide))

    def test_approving_restarts_an_agent_started_without_the_guide(self):
        self.arrive()
        ctl = operators.controller(self.fake)
        self.controllers.append(ctl)
        self.start_ready(ctl)
        self.assertFalse(ctl.launch_changed)
        bpy.ops.whittle.style_guide_approve()
        self.assertTrue(ctl.launch_changed, "the next turn gets the guide")

    def test_going_without_it_sends(self):
        self.arrive()
        self.assertEqual(bpy.ops.whittle.style_guide_skip(), {"FINISHED"})
        ctl, _node = self.send("Add a lid.")
        self.assertEqual(ctl.session_starts[-1]["settings"]["style_guide"], "")
        self.load.assert_not_called()
