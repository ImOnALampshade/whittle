# SPDX-License-Identifier: GPL-3.0-or-later
"""Enter sends from the prompt box: the confirm window, which operator
each field sends with, and the keymap's registration."""

import unittest
from types import SimpleNamespace
from unittest import mock

import bpy

from whittle.addon import enter


class FakeOp:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def poll(self):
        return self.ok

    def __call__(self, mode):
        self.calls.append(mode)
        return {"FINISHED"}


class EnterTest(unittest.TestCase):
    def setUp(self):
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.props = bpy.context.scene.whittle
        self.addCleanup(setattr, enter, "_confirmed", None)
        for name in enter.SENDERS:
            self.addCleanup(setattr, self.props, name, "")

    def press(self, **ops):
        whittle = SimpleNamespace(**{name: FakeOp() for name in enter.SENDERS.values()} | ops)
        with mock.patch.object(enter, "bpy", SimpleNamespace(ops=SimpleNamespace(whittle=whittle))):
            result = enter.WHITTLE_OT_enter_send.invoke(None, bpy.context, None)
        return result, whittle

    def test_each_field_sends_with_its_operator(self):
        for name, sender in enter.SENDERS.items():
            with self.subTest(name):
                setattr(self.props, name, "taller")
                result, whittle = self.press()
                self.assertEqual(result, {"FINISHED"})
                self.assertEqual(getattr(whittle, sender).calls, ["EXEC_DEFAULT"])
                others = [op for key, op in vars(whittle).items() if key != sender]
                self.assertTrue(all(not op.calls for op in others))

    def test_enter_elsewhere_passes_through(self):
        result, whittle = self.press()
        self.assertEqual(result, {"PASS_THROUGH"})
        self.assertEqual(whittle.submit.calls, [])

    def test_a_confirm_sends_once(self):
        self.props.prompt = "Add a lid."
        self.assertEqual(self.press()[0], {"FINISHED"})
        self.assertEqual(self.press()[0], {"PASS_THROUGH"}, "a second Enter has nothing confirmed")

    def test_blank_text_never_counts(self):
        self.props.prompt = "   \n "
        self.assertEqual(self.press()[0], {"PASS_THROUGH"})

    def test_a_late_enter_does_not_send(self):
        # Clicking away confirms too; an Enter pressed long after is not
        # the one that confirmed the box.
        self.props.prompt = "Add a lid."
        _name, at = enter._confirmed
        self.assertIsNone(enter.take_confirmed(now=at + enter.WINDOW + 0.1))
        self.props.prompt = "Add a lid!"
        self.assertEqual(enter.take_confirmed(now=enter._confirmed[1] + 0.1), "prompt")

    def test_nothing_sent_when_sending_is_not_possible(self):
        self.props.prompt = "Add a lid."
        result, whittle = self.press(submit=FakeOp(ok=False))
        self.assertEqual(result, {"PASS_THROUGH"})
        self.assertEqual(whittle.submit.calls, [])

    def test_registers_in_the_window_keymap(self):
        # Background Blender has no key configurations, so a stand-in.
        items = []
        keymap = SimpleNamespace(keymap_items=SimpleNamespace(
            new=lambda idname, key, value, **mods: items.append((idname, key, value, mods)) or items[-1],
            remove=items.remove))
        names = []
        keyconfig = SimpleNamespace(keymaps=SimpleNamespace(
            new=lambda name, space_type: names.append((name, space_type)) or keymap))
        wm = SimpleNamespace(keyconfigs=SimpleNamespace(addon=keyconfig))
        enter.unregister_keymap()
        with mock.patch.object(enter, "bpy", SimpleNamespace(context=SimpleNamespace(window_manager=wm))):
            enter.register_keymap()
            self.assertEqual(names, [("Window", "EMPTY")])
            self.assertEqual(sorted(items), sorted(("whittle.enter_send", key, "RELEASE", {}) for key in enter.KEYS))
            self.assertEqual(set(enter.KEYS), {"RET", "NUMPAD_ENTER"})
            enter.unregister_keymap()
        self.assertEqual(items, [], "unregistering removes them")
        self.assertEqual(enter._keymaps, [])

    def test_keymap_follows_registration(self):
        if bpy.context.window_manager.keyconfigs.addon is None:
            self.assertEqual(enter._keymaps, [], "background Blender has no key configurations")
            return
        keys = sorted(kmi.type for _km, kmi in enter._keymaps)
        self.assertEqual(keys, sorted(enter.KEYS))
        self.assertTrue(all(kmi.value == "RELEASE" and not kmi.shift for _km, kmi in enter._keymaps))
        self.assertTrue(all(kmi.idname == "whittle.enter_send" for _km, kmi in enter._keymaps))


if __name__ == "__main__":
    unittest.main()
