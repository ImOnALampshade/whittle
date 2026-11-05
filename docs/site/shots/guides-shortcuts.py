# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for the Keyboard shortcuts guide."""

from tests.docshots.spec import Shot, preferences

SHOTS = [
    Shot("ask-claude", "The Shift+Alt+C popup under the pointer, a prompt half typed.", scenario="shortcut_popup"),
    Shot("keymap", "Whittle's keys in Preferences, Keymap, filtered by name.",
         preferences("KEYMAP", search="Whittle")),
]
