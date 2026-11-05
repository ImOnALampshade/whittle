# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for the Architecture overview: what the agent's events become
in the sidebar."""

from tests.docshots.spec import Shot

SHOTS = [
    Shot("streaming", "Mid-turn: text and finished tool calls, two more calls in flight.", scenario="streaming"),
]
