# SPDX-License-Identifier: GPL-3.0-or-later
"""The GUI checks' pieces that need no window (./gui_checks.sh runs the
checks themselves): every check in the catalog has its phases, and each
phase opens a file the run provides; the alias that imports the installed
extension as `whittle`; the spy that records what a real draw drew."""

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.blender.ui_helpers import RecordingLayout
from tests.gui import catalog, checks
from tests.gui.alias import Alias
from tests.gui.spy import Spy, SpyLayout


class GuiChecksTest(unittest.TestCase):
    def test_every_check_has_its_phases(self):
        self.assertEqual(set(checks.PHASES), set(catalog.CHECKS))
        for name, check in catalog.CHECKS.items():
            with self.subTest(check=name):
                self.assertTrue(check.description)
                self.assertEqual(len(checks.PHASES[name]), len(check.phases))

    def test_the_first_phase_opens_the_startup_file(self):
        # Later phases may open what an earlier one saved; the first has
        # only the copy of the factory startup file.
        for name, check in catalog.CHECKS.items():
            with self.subTest(check=name):
                self.assertEqual(check.phases[0].open, "base.blend")

    def test_waits_from_the_screenshot_stage_become_checks_waits(self):
        from tests.screens import scenarios

        step = checks.Until.of(scenarios.Until(lambda: True, "something"))
        self.assertIsInstance(step, checks.Until)
        self.assertEqual(step.what, "something")
        self.assertTrue(step.check())


class AliasTest(unittest.TestCase):
    """The checks import the installed extension through an alias."""

    TARGET = "gui_alias_target"
    NAME = "gui_alias_name"

    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        package = folder / self.TARGET
        (package / "sub").mkdir(parents=True)
        (package / "__init__.py").write_text("VALUE = 1\n")
        (package / "sub" / "__init__.py").write_text("")
        (package / "sub" / "leaf.py").write_text("THING = object()\n")
        sys.path.insert(0, str(folder))
        self.addCleanup(sys.path.remove, str(folder))
        self.addCleanup(self._forget)
        self.alias = Alias(self.NAME, self.TARGET).install()
        self.addCleanup(self.alias.remove)

    def _forget(self):
        for name in [m for m in sys.modules if m.split(".")[0] == self.TARGET]:
            del sys.modules[name]

    def test_imports_give_the_target_modules_objects(self):
        from gui_alias_name import VALUE, sub
        from gui_alias_name.sub.leaf import THING

        self.assertEqual(VALUE, 1)
        self.assertIs(sub, importlib.import_module(f"{self.TARGET}.sub"))
        self.assertIs(THING, importlib.import_module(f"{self.TARGET}.sub.leaf").THING)

    def test_nothing_under_the_alias_says_where_it_was_loaded_from(self):
        # Blender would list such a module as a policy violation of the
        # extension in the Preferences.
        import gui_alias_name.sub.leaf  # noqa: F401

        names = [m for m in sys.modules if m.split(".")[0] == self.NAME]
        self.assertEqual(sorted(names), [self.NAME, f"{self.NAME}.sub", f"{self.NAME}.sub.leaf"])
        for name in names:
            with self.subTest(module=name):
                self.assertIsNone(getattr(sys.modules[name], "__file__", None))

    def test_attributes_set_through_the_alias_reach_the_target(self):
        import gui_alias_name

        gui_alias_name.VALUE = 2
        self.assertEqual(importlib.import_module(self.TARGET).VALUE, 2)

    def test_refuses_a_name_already_imported(self):
        import gui_alias_name  # noqa: F401

        with self.assertRaises(RuntimeError):
            Alias(self.NAME, self.TARGET).install()


class _Watched(RecordingLayout):
    """A stand-in for a real layout that notes what is set on it."""

    def __init__(self, calls=None, depth=0):
        super().__init__(calls, depth)
        self.__dict__["set"] = []

    def __setattr__(self, name, value):
        if "set" in self.__dict__:
            self.__dict__["set"].append(name)
        super().__setattr__(name, value)

    def row(self, **kw):
        return self._child_watched("row", **kw)

    def _child_watched(self, kind, **data):
        child = _Watched(self.calls, self.depth + 1)
        self._record(kind, child=child, **data)
        return child

    def operator(self, idname, **kw):
        props = SimpleNamespace()
        self._record("operator", idname=idname, props=props, **kw)
        return props


class SpyTest(unittest.TestCase):
    def test_records_and_passes_every_call_on(self):
        real = _Watched()
        spy = SpyLayout(real)
        row = spy.row(align=True)
        row.active = False
        row.label(text="Where the key comes from", icon="INFO")
        row.operator("wm.url_open", text="Get a Key").url = "https://example.com"
        self.assertEqual(real.labels(), ["Where the key comes from"])
        self.assertEqual(real.operators("wm.url_open")[0]["props"].url, "https://example.com")
        self.assertEqual([p.url for p in spy.operator_props("wm.url_open")], ["https://example.com"])
        self.assertFalse(spy.is_active(spy.operators("wm.url_open")[0]))
        # Only what the draw code set reaches the real layout: a new row
        # keeps what it inherits.
        self.assertEqual(real.of("row")[0]["child"].set, ["active"])
        self.assertEqual(real.set, [])

    def test_wraps_a_class_draw_until_removed(self):
        class Panel:
            def draw(self, context):
                self.layout.label(text=f"drawn for {context}")

        original = Panel.draw
        spy = Spy(Panel)
        instance = SimpleNamespace(layout=RecordingLayout())
        Panel.draw(instance, "the sidebar")
        self.assertEqual((spy.count, spy.latest.labels()), (1, ["drawn for the sidebar"]))
        self.assertEqual(instance.layout.labels(), ["drawn for the sidebar"])
        spy.remove()
        self.assertIs(Panel.draw, original)

    def test_keeps_a_failed_draw(self):
        class Panel:
            def draw(self, context):
                raise ValueError("no such property")

        with Spy(Panel) as spy:
            with self.assertRaises(ValueError):
                Panel.draw(SimpleNamespace(layout=RecordingLayout()), None)
        self.assertEqual(spy.count, 1)
        self.assertIn("no such property", spy.errors[-1])


if __name__ == "__main__":
    unittest.main()
