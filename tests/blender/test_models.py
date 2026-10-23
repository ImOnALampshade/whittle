# SPDX-License-Identifier: GPL-3.0-or-later
"""The model per chat: the composer's model button and its menu, the list
the menu offers (the agent's report, kept in the user folder), and a chat's
model going with its turns, switched between turns without a new session."""

import json
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import FAKE_SCRIPTS, TempUserDir
from tests.blender.test_chats import ChatCase
from tests.blender.test_sidebar import AddonTestCase, fake_controller
from tests.blender.ui_helpers import RecordingLayout
from whittle import models as store
from whittle.addon import chats, models, operators, prefs, ui

REPORT = {"models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-4-6", "claude-mythos-5-1"],
          "source": "api"}


def item_names(layout) -> list[tuple[str, str]]:
    return [(c["text"], c["icon"]) for c in layout.operators("whittle.chat_model")]


class MenuTest(AddonTestCase):
    def setUp(self):
        super().setUp()
        user = TempUserDir()
        user.__enter__()
        self.addCleanup(user.__exit__, None, None, None)

    def test_the_latest_of_each_family_with_a_check_on_the_chats(self):
        layout = RecordingLayout()
        models.draw_models(layout, "claude-sonnet-5-5", store.catalog([]), "claude-opus-5-5", now=0)
        self.assertEqual(item_names(layout)[:4], [("Opus 5.5", "BLANK1"), ("Sonnet 5.5", "CHECKMARK"),
                                                  ("Haiku 5.5", "BLANK1"), ("Fable 5.1", "BLANK1")])
        self.assertEqual([c["props"].model for c in layout.operators("whittle.chat_model")][:4],
                         ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"])
        self.assertEqual(layout.menus(), ["WHITTLE_MT_models_older"])
        other = layout.operators("whittle.chat_model")[-1]
        self.assertEqual((other["text"], other["props"].model), ("Other Model…", ""))
        self.assertEqual(other["layout"].operator_context, "INVOKE_DEFAULT")
        default, = layout.operators("whittle.default_model")
        self.assertEqual((default["text"], default["props"].model),
                         ("Use Sonnet 5.5 for New Chats", "claude-sonnet-5-5"))
        self.assertEqual(layout.labels(), [models.EFFORT_LABEL, models.BUILT_IN])

    def test_an_older_or_custom_model_stays_in_sight(self):
        found = store.catalog([], source="cli", fetched=0)
        layout = RecordingLayout()
        models.draw_models(layout, "claude-opus-4-6", found, "claude-opus-4-6", now=7200)
        self.assertEqual(item_names(layout)[0], ("Opus 4.6", "CHECKMARK"))
        self.assertEqual(layout.operators("whittle.default_model"), [], "it is the default already")
        self.assertEqual(layout.labels(), [models.EFFORT_LABEL, "Listed by Claude 2 hours ago"])
        layout = RecordingLayout()
        models.draw_models(layout, "my-proxy-model", found, "claude-opus-5-5")
        self.assertEqual(item_names(layout)[0], ("my-proxy-model", "CHECKMARK"))

    def test_older_models_by_family(self):
        layout = RecordingLayout()
        models.draw_older_models(layout, "claude-opus-4-7", store.catalog([]))
        self.assertEqual(layout.labels(), ["Opus", "Sonnet", "Haiku", "Fable"])
        self.assertIn(("Opus 4.7", "CHECKMARK"), item_names(layout))
        self.assertEqual([t for t, _ in item_names(layout)][:5], ["Opus 5", "Opus 4.8", "Opus 4.7", "Opus 4.6",
                                                                 "Opus 4.5"])
        layout = RecordingLayout()
        models.draw_older_models(layout, "claude-opus-5-5", store.catalog([], known=("claude-opus-5-5",)))
        self.assertEqual(layout.labels(), ["No older models"])

    def test_the_composer_has_the_model_button_between_turns(self):
        layout = self.draw(fake_controller())
        button = next(c for c in layout.of("menu") if c["menu"] == "WHITTLE_MT_models")
        self.assertEqual(button["text"], "claude-test")
        with mock.patch.object(models, "chat_model", return_value="claude-haiku-5-5"):
            layout = self.draw()
        button = next(c for c in layout.of("menu") if c["menu"] == "WHITTLE_MT_models")
        self.assertEqual(button["text"], "Haiku 5.5")
        layout = self.draw(fake_controller(running=True))
        self.assertNotIn("WHITTLE_MT_models", layout.menus(), "the model changes between turns")

    def test_the_agent_popover_names_the_model(self):
        layout = RecordingLayout()
        with mock.patch.object(models, "chat_model", return_value="claude-fable-5-1"):
            ui.draw_agent(layout, None)
        self.assertIn("Model: Fable 5.1 (claude-fable-5-1)", layout.labels())
        self.assertIn("Effort: High", layout.labels(), "no chat yet: the default")

    def test_the_effort_section_checks_the_chats(self):
        layout = RecordingLayout()
        models.draw_models(layout, "claude-opus-5-5", store.catalog([]), "claude-opus-5-5", now=0)
        efforts = layout.operators("whittle.chat_effort")
        self.assertEqual([(c["text"], c["icon"], c["props"].effort) for c in efforts],
                         [("Low", "BLANK1", "low"), ("Medium", "BLANK1", "medium"),
                          ("High", "CHECKMARK", "high")], "high by default")
        layout = RecordingLayout()
        models.draw_models(layout, "claude-opus-5-5", store.catalog([]), "claude-opus-5-5", effort="low")
        self.assertEqual([c["icon"] for c in layout.operators("whittle.chat_effort")],
                         ["CHECKMARK", "BLANK1", "BLANK1"])
        self.assertEqual(item_names(layout)[:4], [("Opus 5.5", "CHECKMARK"), ("Sonnet 5.5", "BLANK1"),
                                                  ("Haiku 5.5", "BLANK1"), ("Fable 5.1", "BLANK1")],
                         "the models are as they were")

    def test_not_while_a_turn_runs(self):
        self.assertEqual(models.blocker(fake_controller(running=True)), models.BUSY)
        self.assertEqual(models.blocker(SimpleNamespace(running=False, busy=False, question={"q": 1})),
                         models.BUSY)
        self.assertIsNone(models.blocker(fake_controller()))
        self.assertIsNone(models.blocker(None))

    def test_the_cache_is_read_again_when_it_changes(self):
        self.assertEqual(models.catalog().source, "")
        models.received({"models": ["claude-opus-6"], "source": "cli"})
        found = models.catalog()
        self.assertEqual((found.latest()[0].id, found.source), ("claude-opus-6", "cli"))
        models.received({"models": []})
        self.assertEqual(models.catalog().latest()[0].id, "claude-opus-6", "an empty report keeps the list")


class ChatModelTest(ChatCase):
    def setUp(self):
        super().setUp()
        script = json.loads((FAKE_SCRIPTS / "history.json").read_text())
        script["models"] = REPORT
        path = self.user_dir / "models.json-script.json"
        path.write_text(json.dumps(script))
        self.fake = str(path)

    def model_logs(self, ctl):
        return [e["data"]["message"] for e in ctl.events
                if e["name"] == "log" and e["data"]["message"].startswith(("model:", "session model:"))]

    def test_a_chat_keeps_its_model_and_changes_it_between_turns(self):
        ctl, _n1 = self.send("Make the crate bigger.")
        self.assertEqual(ctl.session_starts[-1]["model"], prefs.DEFAULTS["model"])
        chat = self.store.current
        self.assertEqual(self.store.model(chat), prefs.DEFAULTS["model"], "the first turn keeps the default")
        # The agent's report is the menu's list now.
        found = models.catalog()
        self.assertEqual(found.source, "api")
        self.assertIn("claude-mythos-5-1", [m.id for m in found.latest()])

        self.assertEqual(bpy.ops.whittle.chat_model(model="claude-opus-4-6"), {"FINISHED"})
        self.assertEqual(models.chat_model(), "claude-opus-4-6")
        same, _n2 = self.send("Add a lid.")
        self.assertIs(same, ctl)
        self.assertEqual(len(ctl.session_starts), 1, "the session carries on, on the new model")
        self.assertEqual(self.model_logs(ctl), ["session model: claude-opus-5-5", "model: claude-opus-4-6"])

        # A new chat starts on the default; going back finds the chat's own.
        operators.new_chat(bpy.context)
        self.assertEqual(models.chat_model(), prefs.DEFAULTS["model"])
        other, _ = self.send("Make it bigger again.")
        self.assertEqual(other.session_starts[-1]["model"], prefs.DEFAULTS["model"])
        operators.switch_chat(bpy.context, chat)
        self.assertEqual(models.chat_model(), "claude-opus-4-6")
        back, _ = self.send("Sand the edges.")
        self.assertEqual(back.session_starts[-1]["model"], "claude-opus-4-6")

    def test_a_new_default_leaves_a_chat_with_turns_alone(self):
        self.send("Make the crate bigger.")
        changed = SimpleNamespace(**{**prefs.DEFAULTS, "model": "claude-haiku-5-5"})
        with mock.patch.object(prefs, "get", return_value=changed):
            self.assertEqual(models.chat_model(), prefs.DEFAULTS["model"])
            operators.new_chat(bpy.context)
            self.assertEqual(models.chat_model(), "claude-haiku-5-5")

    def test_the_model_cannot_change_during_a_turn(self):
        self.props.prompt = "Make the crate bigger."
        ctl, node = operators.submit_sketch(bpy.context, self.fake)
        self.controllers.append(ctl)
        self.assertFalse(bpy.ops.whittle.chat_model.poll())
        self.wait(ctl, node)
        self.assertTrue(bpy.ops.whittle.chat_model.poll())

    def effort_logs(self, ctl):
        return [e["data"]["message"] for e in ctl.events
                if e["name"] == "log" and e["data"]["message"].startswith(("effort:", "session effort:"))]

    def test_a_chat_keeps_its_effort_and_changes_it_between_turns(self):
        ctl, _n1 = self.send("Make the crate bigger.")
        self.assertEqual(ctl.session_starts[-1]["effort"], "high", "a new chat runs at high")
        chat = self.store.current
        self.assertEqual(models.chat_effort(), "high")

        self.assertEqual(bpy.ops.whittle.chat_effort(effort="low"), {"FINISHED"})
        self.assertEqual((models.chat_effort(), self.store.effort(chat)), ("low", "low"))
        same, _n2 = self.send("Add a lid.")
        self.assertIs(same, ctl)
        self.assertEqual(len(ctl.session_starts), 1, "the session carries on, at the new effort")
        self.assertEqual(self.effort_logs(ctl), ["session effort: high", "effort: low"])

        # A new chat starts at high; going back finds the chat's own, and a
        # session started for it runs at it from the start.
        operators.new_chat(bpy.context)
        self.assertEqual(models.chat_effort(), "high")
        other, _ = self.send("Make it bigger again.")
        self.assertEqual(other.session_starts[-1]["effort"], "high")
        operators.switch_chat(bpy.context, chat)
        self.assertEqual(models.chat_effort(), "low")
        back, _ = self.send("Sand the edges.")
        self.assertEqual(back.session_starts[-1]["effort"], "low")

    def test_the_effort_cannot_change_during_a_turn(self):
        self.props.prompt = "Make the crate bigger."
        ctl, node = operators.submit_sketch(bpy.context, self.fake)
        self.controllers.append(ctl)
        self.assertFalse(bpy.ops.whittle.chat_effort.poll())
        self.wait(ctl, node)
        self.assertTrue(bpy.ops.whittle.chat_effort.poll())

    def test_an_unknown_effort_is_refused(self):
        with self.assertRaises(ValueError):
            models.set_chat_effort("max")

    def test_a_file_without_a_chat_gets_one(self):
        self.assertIsNone(chats.get())
        models.set_chat_model("claude-sonnet-5-5")
        self.assertEqual(self.store.model(self.store.current), "claude-sonnet-5-5")
        ctl, _ = self.send("Make the crate bigger.")
        self.assertEqual(ctl.session_starts[-1]["model"], "claude-sonnet-5-5")
