# SPDX-License-Identifier: GPL-3.0-or-later
"""The default sketch keys: where they are registered, that Blender's own
keymap leaves them free, and the Toggle Sketch Mode operator they start
with. Pressing them in a GUI Blender with simulated keys was checked by
hand (docs/progress.md)."""

import unittest
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.keymap_helpers import clashes, default_keymaps, fake_keyconfig
from whittle.addon import keys, operators


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
