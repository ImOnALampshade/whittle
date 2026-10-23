# SPDX-License-Identifier: GPL-3.0-or-later
"""The GUI checks' pieces that need no window (./gui_checks.sh runs the
checks themselves): every check in the catalog has its phases, and each
phase opens a file the run provides."""

import unittest

from tests.gui import catalog, checks


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


if __name__ == "__main__":
    unittest.main()
