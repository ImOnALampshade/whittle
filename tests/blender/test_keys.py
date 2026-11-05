# SPDX-License-Identifier: GPL-3.0-or-later
"""The default sketch keys: where they are registered, that Blender's own
keymap leaves them free, and the Toggle Sketch Mode operator they start
with. Pressing them in a GUI Blender with simulated keys was checked by
hand (docs/progress.md)."""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import AgentTestCase, agent_python
from tests.blender.keymap_helpers import clashes, default_keymaps, fake_keyconfig
from tests.blender.test_sidebar import fake_controller
from tests.blender.ui_helpers import RecordingLayout
from whittle.addon import enter, keys, operators, prefs, process, setup, turn, ui
from whittle.addon.process import AgentState


class KeymapTest(unittest.TestCase):
    def test_registers_in_the_3d_view_keymap(self):
        wm, names, items = fake_keyconfig()
        with mock.patch.object(keys, "bpy", SimpleNamespace(context=SimpleNamespace(window_manager=wm))):
            keys.register_keymap()
            self.assertEqual(names, [("3D View", "VIEW_3D")])
            self.assertEqual(items, [
                ("whittle.sketch_toggle", "D", "PRESS", {"shift": True, "alt": True}),
                ("whittle.next_stroke_type", "N", "PRESS", {"shift": True, "alt": True}),
                ("whittle.capture_view", "V", "PRESS", {"shift": True, "alt": True}),
                ("whittle.send_key", "RET", "PRESS", {"shift": True, "alt": True}),
            ])
            keys.unregister_keymap()
        self.assertEqual(items, [])
        self.assertEqual(keys._keymaps, [])

    def test_the_keymap_applies_over_the_viewport_in_every_mode(self):
        # An add-on keymap must match a default one's name and space; the
        # 3D View keymap is the viewport's in every mode, Draw Mode included.
        found = {name: args for name, args, _content in default_keymaps()}
        name, space_type = keys.KEYMAP
        self.assertEqual(found[name]["space_type"], space_type)
        self.assertEqual(found[name].get("region_type"), "WINDOW")

    def test_unused_by_the_default_keymap(self):
        keymaps = default_keymaps()
        for idname, key in keys.KEYS:
            self.assertEqual(clashes(key, keys.MODS, keymaps), [], idname)

    def test_every_key_runs_a_whittle_operator(self):
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        for idname, _key in keys.KEYS:
            module, name = idname.split(".")
            self.assertTrue(hasattr(getattr(bpy.ops, module), name), idname)
            self.assertIn(f"{module.upper()}_OT_{name}", dir(bpy.types))
        if bpy.context.window_manager.keyconfigs.addon is None:
            self.assertEqual(keys._keymaps, [], "background Blender has no key configurations")
        else:
            self.assertEqual([kmi.idname for _km, kmi in keys._keymaps], [i for i, _k in keys.KEYS])

    def test_distinct_from_ask_claude(self):
        from whittle.addon import shortcut

        key, mods = shortcut.KEY
        self.assertEqual(mods, keys.MODS, "one modifier pair for every Whittle key")
        self.assertNotIn(key, [k for _i, k in keys.KEYS])
        self.assertEqual(len({k for _i, k in keys.KEYS}), len(keys.KEYS))


class SendKeyTest(unittest.TestCase):
    """Shift+Alt+Enter does what Enter in the prompt box would."""

    def action(self, *, busy=False, question=None, prompt="", amend="", answer="", refs=0, pending=0):
        props = SimpleNamespace(prompt=prompt, amend_text=amend, ask_answer=answer, refs=[None] * refs)
        context = SimpleNamespace(scene=SimpleNamespace(whittle=props))
        ctl = SimpleNamespace(question=question)
        with mock.patch.object(operators.turn, "current", return_value=ctl), \
                mock.patch.object(operators, "busy", return_value=busy), \
                mock.patch.object(operators.sketch, "find_sketch_object", return_value=None), \
                mock.patch.object(operators.sketch, "pending_count", return_value=pending):
            return operators.send_key_action(context)

    def test_between_turns_it_sends(self):
        self.assertEqual(self.action(prompt="Add a lid."), "submit")
        self.assertEqual(self.action(refs=1), "submit", "a reference alone")
        self.assertEqual(self.action(pending=2), "submit", "strokes alone")
        self.assertIsNone(self.action(prompt="  "), "nothing to send")
        self.assertIsNone(self.action(amend="Make it red"), "the amend box is not sent between turns")

    def test_during_a_turn_it_amends(self):
        self.assertEqual(self.action(busy=True, amend="Make it red"), "amend")
        self.assertEqual(self.action(busy=True, pending=1), "amend", "new strokes alone")
        self.assertIsNone(self.action(busy=True), "nothing to amend with")
        self.assertIsNone(self.action(busy=True, prompt="Next request."), "the prompt waits for the turn's end")

    def test_while_claude_asks_it_answers(self):
        asking = {"question": "Overhang or flush?", "choices": []}
        self.assertEqual(self.action(busy=True, question=asking, answer="Flush"), "answer")
        self.assertIsNone(self.action(busy=True, question=asking, amend="Make it red"),
                          "the box is the answer while Claude asks")
        self.assertEqual(self.action(busy=True, question=asking, pending=1), "amend")

    def test_nothing_to_send_runs_nothing(self):
        op = SimpleNamespace()
        with mock.patch.object(operators, "send_key_action", return_value=None):
            self.assertEqual(operators.WHITTLE_OT_send_key.execute(op, SimpleNamespace()), {"CANCELLED"})


def press_enter() -> tuple[set, list[str]]:
    """Enter's operator needs an event, so a background Blender does not run
    it: its invoke directly, returning its result and its error reports. A
    RuntimeError out of invoke is the nested operator's error, which the user
    would get as a traceback, so that fails the test."""
    errors = []

    def report(kinds, text):
        if "ERROR" in kinds:
            errors.append(text)

    try:
        result = enter.WHITTLE_OT_enter_send.invoke(SimpleNamespace(report=report), bpy.context, None)
    except RuntimeError as exc:
        raise AssertionError(f"Enter raised instead of reporting: {exc}") from exc
    return result, errors


def press(op) -> tuple[set, list[str]]:
    """`op`'s result and error reports, which Blender raises from its own call."""
    try:
        return op(), []
    except RuntimeError as exc:
        return {"CANCELLED"}, [str(exc).strip().removeprefix("Error: ")]


class SendRoutesTest(AgentTestCase):
    """The Send button, Shift+Alt+Enter and Enter in the box end alike, through
    the real operators: a nested operator's error report would reach the user
    as a Python traceback, which fails `press_enter` and, for the key, does not
    match the line."""

    ROUTES = {"button": lambda: press(bpy.ops.whittle.submit),
              "key": lambda: press(bpy.ops.whittle.send_key),
              "enter": press_enter}

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ["WHITTLE_AGENT_PYTHON"] = str(agent_python())
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.addCleanup(turn.set_current, None)
        self.addCleanup(setattr, enter, "_confirmed", None)
        self.props = bpy.context.scene.whittle
        for name in enter.SENDERS:
            self.addCleanup(setattr, self.props, name, "")

    def ctx(self):
        return ui.Ctx(scene=bpy.context.scene, hist=None, ctl=turn.current(), comparing=None)

    def assert_reports(self, route, line):
        """`route` ends on the error line alone, the prompt still in the box."""
        turn.set_current(None)
        self.props.prompt = f"Add a lid by {route}."
        _result, errors = self.ROUTES[route]()
        self.assertEqual(errors, [line])
        self.assertEqual(self.props.prompt, f"Add a lid by {route}.")

    def test_no_key_reports_the_line_and_keeps_the_prompt(self):
        for route in self.ROUTES:
            with self.subTest(route):
                self.assert_reports(route, process.NO_KEY)
                self.assertEqual(turn.current().process.state, AgentState.NEEDS_KEY)
                self.assertTrue(ui.can_send(self.ctx()), "a key may have been added since")
                self.assertTrue(ui.draw_attention(RecordingLayout(), self.ctx()), "the box asks for a key")

    def test_no_environment_reports_the_line_and_keeps_the_prompt(self):
        del os.environ["WHITTLE_AGENT_PYTHON"]
        for route in self.ROUTES:
            with self.subTest(route):
                self.assert_reports(route, "The agent environment is not set up yet")
                self.assertEqual(turn.current().process.state, AgentState.NEEDS_SETUP)
                self.assertTrue(ui.draw_attention(RecordingLayout(), self.ctx()), "the box offers Set Up")

    def test_keys_send_nothing_where_the_button_is_disabled(self):
        del os.environ["WHITTLE_AGENT_PYTHON"]
        ctl = fake_controller(AgentState.NEEDS_SETUP, reason="Not set up", alive=False)
        turn.set_current(ctl)
        self.props.prompt = "Add a lid."
        self.assertFalse(ui.can_send(self.ctx()))
        self.assertFalse(bpy.ops.whittle.submit.poll())
        with mock.patch.object(operators, "submit_sketch") as submit:
            self.assertEqual(bpy.ops.whittle.send_key(), {"CANCELLED"})
            self.props.prompt = "Add a lid!"
            self.assertEqual(press_enter(), ({"PASS_THROUGH"}, []))
        submit.assert_not_called()
        self.assertEqual(self.props.prompt, "Add a lid!")

    def test_the_button_says_why_it_is_disabled(self):
        turn.set_current(fake_controller(AgentState.NEEDS_SETUP, reason="Not set up", alive=False))
        with self.assertRaisesRegex(RuntimeError, operators.SETUP_FIRST):
            bpy.ops.whittle.submit()

    def test_a_refused_amendment_reports_the_line(self):
        turn.set_current(fake_controller(running=True))
        for route in ("key", "enter"):
            with self.subTest(route), mock.patch.object(operators, "amend", side_effect=ValueError("no bundle")):
                self.props.amend_text = "Make it red"
                self.assertEqual(self.ROUTES[route](), ({"CANCELLED"}, ["no bundle"]))

    def test_a_key_sends_as_the_button_does(self):
        ctl = SimpleNamespace(running=True)
        for route in self.ROUTES:
            with self.subTest(route), mock.patch.object(operators, "submit_sketch", return_value=(ctl, "n0001")) as submit:
                self.props.prompt = "Add a lid."
                self.assertEqual(self.ROUTES[route](), ({"FINISHED"}, []))
                submit.assert_called_once()

    def strand(self):
        """A send that found no environment, so the agent needs setting up."""
        os.environ.pop("WHITTLE_AGENT_PYTHON", None)
        self.assert_reports("button", "The agent environment is not set up yet")
        self.assertEqual(turn.current().process.state, AgentState.NEEDS_SETUP)

    def assert_reaches_the_agent(self, route):
        """`route` gets as far as the agent's start, which now asks for the key."""
        ctl = turn.current()
        self.props.prompt = "Add a lid."
        self.assertEqual(self.ROUTES[route]()[1], [process.NO_KEY])
        self.assertIs(turn.current(), ctl)
        self.assertEqual(ctl.process.state, AgentState.NEEDS_KEY)

    def test_a_chosen_environment_lets_every_route_send(self):
        for name in ("agent_python", "venv_dir"):
            update = prefs.WhittlePreferences.__annotations__[name].keywords["update"]
            for route in self.ROUTES:
                with self.subTest(f"{name} {route}"):
                    self.strand()
                    os.environ["WHITTLE_AGENT_PYTHON"] = str(agent_python())
                    update(None, bpy.context)
                    self.assertTrue(ui.can_send(self.ctx()))
                    self.assertTrue(bpy.ops.whittle.submit.poll())
                    self.assertFalse(ui.draw_attention(RecordingLayout(), self.ctx()), "nothing to set up")
                    self.assert_reaches_the_agent(route)

    def test_the_keys_find_an_environment_set_up_elsewhere(self):
        # Nothing here hears of a second Blender's setup: the key looks again.
        for route in ("key", "enter"):
            with self.subTest(route):
                self.strand()
                os.environ["WHITTLE_AGENT_PYTHON"] = str(agent_python())
                self.assert_reaches_the_agent(route)

    def test_the_keys_still_refuse_without_an_environment(self):
        self.strand()
        self.assertEqual(self.ROUTES["key"](), ({"CANCELLED"}, []))
        self.assertEqual(turn.current().process.state, AgentState.NEEDS_SETUP)

    def test_set_up_finds_an_environment_set_up_elsewhere(self):
        self.strand()
        os.environ["WHITTLE_AGENT_PYTHON"] = str(agent_python())
        confirm = mock.Mock()
        context = SimpleNamespace(window_manager=SimpleNamespace(invoke_confirm=confirm))
        op = SimpleNamespace(reinstall=False, dry_run=False, report=mock.Mock())
        self.assertEqual(setup.WHITTLE_OT_venv_install.invoke(op, context, object()), {"FINISHED"})
        confirm.assert_not_called()
        op.report.assert_called_once_with({"INFO"}, setup.FOUND)
        self.assertTrue(ui.can_send(self.ctx()))


class ToggleTest(unittest.TestCase):
    def run_toggle(self, active):
        op = SimpleNamespace(report=mock.Mock())
        context = SimpleNamespace(area=SimpleNamespace(type="VIEW_3D"))
        with mock.patch.object(operators.sketch, "current_session", return_value=object() if active else None), \
                mock.patch.object(operators.sketch, "start_session") as start, \
                mock.patch.object(operators.sketch, "end_session") as end:
            result = operators.WHITTLE_OT_sketch_toggle.execute(op, context)
        return result, start, end, op

    def test_starts_when_not_sketching(self):
        result, start, end, _op = self.run_toggle(active=False)
        self.assertEqual(result, {"FINISHED"})
        start.assert_called_once()
        end.assert_not_called()

    def test_stops_when_sketching(self):
        result, start, end, _op = self.run_toggle(active=True)
        self.assertEqual(result, {"FINISHED"})
        end.assert_called_once()
        start.assert_not_called()

    def test_poll(self):
        poll = operators.WHITTLE_OT_sketch_toggle.poll
        outliner = SimpleNamespace(area=SimpleNamespace(type="OUTLINER"))
        viewport = SimpleNamespace(area=SimpleNamespace(type="VIEW_3D"))
        with mock.patch.object(operators.sketch, "current_session", return_value=None):
            self.assertTrue(poll(viewport))
            self.assertFalse(poll(outliner), "sketching starts in a 3D viewport")
        with mock.patch.object(operators.sketch, "current_session", return_value=object()):
            self.assertTrue(poll(outliner), "and stops from anywhere")


if __name__ == "__main__":
    unittest.main()
