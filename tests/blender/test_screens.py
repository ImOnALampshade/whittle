# SPDX-License-Identifier: GPL-3.0-or-later
"""The screenshot harness's pieces that need no window: the scenario list,
and the stitching and trimming of sidebar pages."""

import unittest

import numpy as np

from tests.screens import catalog, harness, scenarios


class ScreensTest(unittest.TestCase):
    def test_every_scenario_is_described(self):
        self.assertEqual(set(scenarios.SCENARIOS), set(catalog.SCENARIOS))
        self.assertTrue(set(catalog.WIDE) <= set(catalog.SCENARIOS))

    def page(self, rows):
        """A 1-pixel-wide page whose rows (top first) hold these values."""
        values = np.array(rows[::-1], dtype=np.float32)
        return np.repeat(values[:, None, None], 4, axis=2)

    def test_stitch_puts_later_pages_below(self):
        first, second = self.page([1, 2, 3, 4]), self.page([3, 4, 5, 6])
        out = harness.stitch([(0, first), (2, second)])
        self.assertEqual(out[::-1, 0, 0].tolist(), [1, 2, 3, 4, 5, 6])

    def test_trim_drops_flat_rows_at_the_bottom(self):
        pixels = np.zeros((6, 4, 4), dtype=np.float32)
        pixels[4, 1] = 1.0   # a panel row, two rows down from the top
        out = harness.trim_bottom(pixels, tabs=0, margin=1)
        self.assertEqual(out.shape[0], 3)


if __name__ == "__main__":
    unittest.main()
