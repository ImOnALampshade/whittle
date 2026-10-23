# SPDX-License-Identifier: GPL-3.0-or-later
"""Shift+Alt+C, straight into typing: which field the popup types into,
the sidebar it opens, the popup it draws, and the keymap item. Sending is
enter.py's (test_enter.py); the whole round trip was checked in a GUI
Blender with simulated keys (docs/decisions.md)."""

import os
import runpy
import unittest
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.ui_helpers import RecordingLayout
from whittle.addon import shortcut


def controller(*, busy=False, question=None):
    return SimpleNamespace(busy=busy, running=busy, question=question)


class FakeRegion:
    """A sidebar region whose tabs appear only once it has drawn."""

    def __init__(self, tabs=("Item", "Tool", "View", "Whittle")):
        self.type = "UI"
        self.tabs = tabs
        self._category = "Item" if tabs else ""
        self.redraws = 0

    @property
    def active_panel_category(self):
        return self._category

    @active_panel_category.setter
    def active_panel_category(self, value):
        if value not in self.tabs:
            raise TypeError(f"enum {value!r} not found in {self.tabs}")
        self._category = value

    def tag_redraw(self):
        self.redraws += 1


def area(region, kind="VIEW_3D", size=(100, 100)):
    return SimpleNamespace(type=kind, width=size[0], height=size[1], regions=[region],
                           spaces=SimpleNamespace(active=SimpleNamespace(show_region_ui=False)))


class FieldTest(unittest.TestCase):
    def test_prompt_when_idle(self):
        self.assertEqual(shortcut.field(None), "prompt")
        self.assertEqual(shortcut.field(controller()), "prompt")

    def test_amendment_while_a_turn_runs(self):
        self.assertEqual(shortcut.field(controller(busy=True)), "amend_text")

    def test_answer_while_claude_asks(self):
        ctl = controller(busy=True, question={"question": "Bevel?", "choices": []})
        self.assertEqual(shortcut.field(ctl), "ask_answer")

    def test_every_field_is_one_enter_sends(self):
        from whittle.addon import enter

        self.assertEqual(set(shortcut.FIELDS), set(enter.SENDERS))


class SidebarTest(unittest.TestCase):
    def test_opens_the_sidebar_on_the_whittle_tab(self):
        region = FakeRegion()
        view = area(region)
        shortcut.show_sidebar(view)
        self.assertTrue(view.spaces.active.show_region_ui)
        self.assertEqual(region.active_panel_category, "Whittle")
        self.assertEqual(region.redraws, 1)

    def test_a_hidden_sidebar_is_switched_once_it_lists_its_tabs(self):
        region = FakeRegion(tabs=())
        view = area(region)
        with mock.patch.object(shortcut.bpy.app.timers, "register") as register:
            shortcut.show_sidebar(view)
        self.assertTrue(view.spaces.active.show_region_ui)
        retry = register.call_args.args[0]
        self.assertEqual(retry(), shortcut.TAB_RETRY, "no tabs yet: try again")
        region.tabs = ("Item", "Whittle")
        self.assertIsNone(retry())
        self.assertEqual(region.active_panel_category, "Whittle")

    def test_retries_give_up(self):
        region = FakeRegion(tabs=())
        with mock.patch.object(shortcut.bpy.app.timers, "register") as register:
            shortcut.show_sidebar(area(region))
        retry = register.call_args.args[0]
        results = [retry() for _ in range(shortcut.TAB_RETRIES + 1)]
        self.assertIsNone(results[-1])
        self.assertEqual(results[:-1], [shortcut.TAB_RETRY] * shortcut.TAB_RETRIES)

    def test_already_on_the_tab(self):
        region = FakeRegion()
        region.active_panel_category = "Whittle"
        shortcut.show_sidebar(area(region))
        self.assertEqual(region.redraws, 0)

    def test_no_viewport(self):
        shortcut.show_sidebar(None)

    def test_the_viewport_under_the_pointer_else_the_largest(self):
        small, big = area(FakeRegion(), size=(10, 10)), area(FakeRegion(), size=(50, 50))
        outliner = area(FakeRegion(), kind="OUTLINER", size=(99, 99))
        window = SimpleNamespace(screen=SimpleNamespace(areas=[small, outliner, big]))
        self.assertIs(shortcut.find_view3d(SimpleNamespace(area=small, window=window)), small)
        self.assertIs(shortcut.find_view3d(SimpleNamespace(area=outliner, window=window)), big)
        self.assertIs(shortcut.find_view3d(SimpleNamespace(area=None, window=window)), big)
        self.assertIsNone(shortcut.find_view3d(SimpleNamespace(area=None, window=None)))


class PopupTest(unittest.TestCase):
    def setUp(self):
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.addCleanup(setattr, shortcut, "_field", None)

    def draw(self):
        layout = RecordingLayout()
        shortcut.WHITTLE_PT_type_prompt.draw(SimpleNamespace(layout=layout), bpy.context)
        return layout

    def test_the_field_takes_the_keyboard(self):
        layout = self.draw()
        self.assertTrue(layout.activate_init)
        (field,) = layout.of("prop")
        self.assertEqual(field["data"], bpy.context.scene.whittle)
        self.assertEqual(field["prop"], "prompt")
        self.assertEqual(field["placeholder"], "Ask Claude…")
        self.assertNotIn("textbox", field, "the multi-line box never takes the keyboard in a popup")
        self.assertEqual(layout.labels(), ["Ask Claude"])

    def test_the_field_picked_on_the_press_stays(self):
        shortcut._field = "amend_text"
        layout = self.draw()
        self.assertEqual(layout.props(), ["amend_text"])
        self.assertEqual(layout.labels(), ["Amend the Running Turn"])

    def test_invoke_opens_the_sidebar_and_the_popup(self):
        ctl = controller(busy=True, question={"question": "Bevel?", "choices": []})
        view = area(FakeRegion())
        context = SimpleNamespace(area=view, window=None)
        call_panel = mock.Mock()
        fake_bpy = SimpleNamespace(ops=SimpleNamespace(wm=SimpleNamespace(call_panel=call_panel)))
        with mock.patch.object(shortcut.turn, "current", return_value=ctl), \
                mock.patch.object(shortcut, "bpy", fake_bpy):
            result = shortcut.WHITTLE_OT_type_prompt.invoke(None, context, None)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(shortcut._field, "ask_answer")
        self.assertTrue(view.spaces.active.show_region_ui)
        call_panel.assert_called_once_with(name="WHITTLE_PT_type_prompt", keep_open=False)


class KeymapTest(unittest.TestCase):
    def test_registers_in_the_window_keymap(self):
        items = []
        keymap = SimpleNamespace(keymap_items=SimpleNamespace(
            new=lambda idname, key, value, **mods: items.append((idname, key, value, mods)) or items[-1],
            remove=items.remove))
        names = []
        keyconfig = SimpleNamespace(keymaps=SimpleNamespace(
            new=lambda name, space_type: names.append((name, space_type)) or keymap))
        wm = SimpleNamespace(keyconfigs=SimpleNamespace(addon=keyconfig))
        with mock.patch.object(shortcut, "bpy", SimpleNamespace(context=SimpleNamespace(window_manager=wm))):
            shortcut.register_keymap()
            self.assertEqual(names, [("Window", "EMPTY")])
            self.assertEqual(items, [("whittle.type_prompt", "C", "PRESS", {"shift": True, "alt": True})])
            shortcut.unregister_keymap()
        self.assertEqual(items, [])
        self.assertEqual(shortcut._keymaps, [])

    def test_keymap_follows_registration(self):
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        if bpy.context.window_manager.keyconfigs.addon is None:
            self.assertEqual(shortcut._keymaps, [], "background Blender has no key configurations")
            return
        ((_km, kmi),) = shortcut._keymaps
        self.assertEqual((kmi.idname, kmi.type, kmi.shift, kmi.alt, kmi.ctrl), ("whittle.type_prompt", "C", 1, 1, 0))

    def test_unused_by_the_default_keymap(self):
        # Background Blender has no key configurations, so the default
        # keymap is generated from its source, as Blender itself does.
        # Modal maps (C toggles clamping while moving) only apply while
        # their operator runs, and it has the keyboard then.
        path = os.path.join(bpy.utils.system_resource("SCRIPTS"), "presets", "keyconfig", "keymap_data",
                            "blender_default.py")
        data = runpy.run_path(path)
        key, mods = shortcut.KEY
        clashes = []
        for name, args, content in data["generate_keymaps"](data["Params"]()):
            if args.get("modal"):
                continue
            for idname, event, _props in content["items"]:
                if event is None or event.get("type") != key:
                    continue
                if event.get("any") or all(bool(event.get(m)) == bool(mods.get(m))
                                           for m in ("shift", "alt", "ctrl", "oskey")):
                    clashes.append(f"{name}: {idname}")
        self.assertEqual(clashes, [])


if __name__ == "__main__":
    unittest.main()
