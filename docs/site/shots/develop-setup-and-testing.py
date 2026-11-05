# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots for Development setup and testing: where Developer Extras is,
and the sidebar's Development panel after a fake turn."""

from tests.docshots.spec import Shot, preferences, sidebar


def fake_turn(stage):
    """A turn from a fake script, then the script's field set to a repo-relative
    path, since the real one shows this machine's folders."""
    import bpy

    bpy.context.preferences.view.show_developer_ui = True
    stage.crate()
    yield from stage.turns(["Add a lid to the crate."], stage.fake("stream.json"))
    bpy.context.window_manager.whittle_fake_script = "tests/fixtures/fake/stream.json"
    yield 0.3


SHOTS = [
    Shot("development-panel", "The Development panel after a turn played from a fake script.",
         sidebar(), setup=fake_turn, open_panels=True),
    Shot("developer-extras", "The Interface preferences' Display panel, with Developer Extras.",
         preferences("INTERFACE", full=True, crop=(0, 0, 680, 228))),
]
