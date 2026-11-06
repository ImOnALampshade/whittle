# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings guide's images: the Preferences, and the agent popover's
For This File."""

from tests.docshots.spec import Shot, preferences


def set_up(stage):
    """The Preferences as a user has them once the setup has run and a key is
    in: the key field shows dots, so an obviously fake value is enough."""
    stage.agent_ready()
    stage.preferences.api_key = "sk-ant-not-a-real-key"
    yield 0.1


SHOTS = [
    Shot("preferences", "All of Whittle's preferences, set up and with a key.", preferences(full=True), setup=set_up),
    Shot("agent-popover", "The agent popover: two of For This File's settings set, a guide loaded, one import missing.", scenario="agent_popover"),
    Shot("guide-gate", "A file naming a guide this computer has not approved: the box over the prompt, Send disabled.", scenario="guide_gate"),
    Shot("guide-gate-read", "The same box after Read Now, listing what the guide would send.", scenario="guide_gate_read"),
]
