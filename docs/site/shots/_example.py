# SPDX-License-Identifier: GPL-3.0-or-later
"""A worked example of each kind of shot (README.md beside this file).
./docs_shots.sh --all leaves it out; ./docs_shots.sh _example shoots it, into
build/docs-shots/images/_example/, not the site."""

from tests.docshots.spec import (LID, Popup, Shot, Snap, done, exec_, popup, preferences, region, render, say,
                                 sidebar, turns, viewport, window)


def lid_then_handles(stage):
    """One continuing scene: a shot after the first turn, more after the
    second, from a fake script in docs/site/shots/fake/_example/."""
    stage.crate()
    script = stage.fake("lid_and_handles.json")
    yield from stage.turns(["Add a lid to the crate."], script)
    yield Snap("after-lid")
    yield from stage.turns(["Add rope handles on both sides."], script)
    stage.orbit((3.0, -4.0, 2.5), 2.2)
    yield 0.3
    yield Snap("after-handles", "after-handles-viewport", "outliner")
    yield Snap("turn-menu", popup=Popup("operator", "whittle.turn_menu", {"node": stage.history().tree.current}))


def ready(stage):
    """The Preferences as a user sees them once the setup has run."""
    stage.agent_ready()
    yield 0.1


def install_dialog(stage):
    """A file browser, opened as Install from Disk does."""
    import bpy

    with bpy.context.temp_override(window=stage.window, screen=stage.window.screen):
        bpy.ops.extensions.package_install_files("INVOKE_DEFAULT")
    yield 1.0


def typed(stage):
    """A plain state, with a fake script written inline."""
    stage.crate()
    script = stage.script("inline", [{"steps": [say("Adding a lid."), exec_("add lid", LID),
                                                render((1.5, -1.5, 1.2))], "finish": done("Added a lid.")}])
    yield from stage.turns(["Add a lid."], script)
    stage.props.prompt = "Now round its corners."
    yield 0.2


SHOTS = [
    # Reuse a scenario from tests/screens/catalog.py: it says what to capture.
    Shot("chat-menu", "The chat menu over three chats.", scenario="chat_menu"),
    # A scenario, captured some other way.
    Shot("conversation-viewport", "The viewport after three turns.", viewport(), scenario="conversation"),
    # One scripted turn, no code at all.
    Shot("one-turn", "One finished turn.", sidebar(), setup=turns("stream.json", "Add a lid to the crate.")),
    # A sequence on one scene: one Blender, each shot where a Snap names it.
    Shot("after-lid", "The sidebar after the first turn.", sidebar(), setup=lid_then_handles),
    Shot("after-handles", "The sidebar after the second turn.", sidebar(), setup=lid_then_handles),
    Shot("after-handles-viewport", "The crate after the second turn.", viewport(), setup=lid_then_handles),
    Shot("outliner", "The Outliner's list after the second turn.", region("OUTLINER"), setup=lid_then_handles),
    Shot("turn-menu", "An earlier turn's menu.", popup(), setup=lid_then_handles),
    # The whole window, and the top of the sidebar only.
    Shot("whole-window", "The whole window with a prompt typed.", window(), setup=typed),
    Shot("sidebar-top", "The first 240 pixels of the sidebar.", sidebar(crop=(0, 0, 320, 240)), setup=typed),
    # A popup from its panel.
    Shot("agent-popover", "The agent popover.", popup(panel="WHITTLE_PT_agent"), setup=typed),
    # The Preferences window: as it opens, and the section's whole length.
    Shot("preferences", "Whittle's preferences as Blender opens them.", preferences()),
    Shot("preferences-full", "All of Whittle's preferences.", preferences(full=True)),
    Shot("extensions", "The Get Extensions section.", preferences("EXTENSIONS")),
    Shot("keymap", "Whittle's keys in the Keymap section.", preferences("KEYMAP", search="Whittle")),
    Shot("preferences-ready", "The agent environment set up.", preferences(scroll=6), setup=ready),
    Shot("install-menu", "Install from Disk in the Extensions menu.",
         preferences("EXTENSIONS", menu="USERPREF_MT_extensions_settings")),
    # Cropped: the rest of a file browser shows this machine's folders.
    Shot("install-options", "Install from Disk's options.", window(of="FILE_BROWSER", crop=(820, 40, 240, 130)),
         setup=install_dialog),
]
