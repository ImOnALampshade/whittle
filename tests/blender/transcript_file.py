# SPDX-License-Identifier: GPL-3.0-or-later
"""Open Transcript and the saved file in one fresh Blender, for
tests/blender/test_chats.py:

    blender -b --factory-startup --python tests/blender/transcript_file.py -- BLEND FAKE_SCRIPT

The transcript is shown in the Scripting workspace's Text Editor, where the
space holds a user of the Text, and saved; the file is reopened to see what
it carries. Then: Open Transcript with no controller, after a chat switch and
after opening the file; a save with Save Chats off, read as bytes; deleting
the chat it shows, then an undo past that; a file an older Whittle saved with
the Text in it. Prints one RESULT line of JSON."""

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import bpy  # noqa: E402

from tests.blender.helpers import pump  # noqa: E402
from tests.blender.history_helpers import STROKE  # noqa: E402
from tests.blender.sketch_helpers import add_stroke, look_at_view  # noqa: E402
from tests.fixtures.crate.scene import build_scene  # noqa: E402
from whittle import addon  # noqa: E402
from whittle.addon import chats, operators, prefs, sketch, transcript, turn, views  # noqa: E402

BLEND, FAKE = sys.argv[sys.argv.index("--") + 1:][:2]
# Only the transcript's text has this: the prompt, as it heads a turn there.
MARK = b"Prompt: Recolour it."
errors = []


def send(prompt: str) -> str:
    scene = bpy.context.scene
    obj = sketch.ensure_sketch_layers(scene)
    if not views.load_views(obj.data):
        views.add_view(obj.data, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))
    add_stroke(obj, "free", STROKE, view=1, radius=0.01)
    scene.whittle.prompt = prompt
    ctl, node = operators.submit_sketch(bpy.context, FAKE)
    pump(ctl, lambda: (ctl.last_finished or {}).get("turn_id") == node or ctl.errors, 30, f"turn {node}")
    errors.extend(ctl.errors)
    return node


def space():
    """The Scripting workspace's Text Editor: -b opens no new editors, and
    the factory file has this one."""
    return next(a.spaces.active for a in bpy.data.screens["Scripting"].areas if a.type == "TEXT_EDITOR")


def show() -> "bpy.types.Text":
    text = operators.open_transcript(bpy.context)
    space().text = text
    return text


def in_file(path: str) -> list[str]:
    # Blender will not read the open file as a library.
    copy = shutil.copy(path, f"{path}.copy.blend")
    with bpy.data.libraries.load(copy) as (data_from, _data_to):
        return [name for name in data_from.texts if name != chats.HOLDER]


def carries_text(path: str) -> bool:
    return MARK in Path(path).read_bytes()


def can_open() -> bool:
    return bpy.ops.whittle.open_transcript.poll()


def main() -> dict:
    addon.register()
    crate = build_scene()
    scene = bpy.context.scene
    scene.whittle.target_auto = False
    scene.whittle.targets.add().object = crate
    result = {"before_any_chat": can_open()}
    send("Make the crate bigger.")
    a = chats.get().current
    operators.new_chat(bpy.context)
    result["new_chat_without_turns"] = can_open()
    send("Recolour it.")
    b = chats.get().current

    text = show()
    result["users"] = text.users
    result["shown"] = MARK.decode() in text.as_string()
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=False)
    result["after_save"] = {"open": transcript.TEXT_NAME in bpy.data.texts, "space": space().text == text}
    result["saved"] = in_file(BLEND)

    operators.switch_chat(bpy.context, a)
    result["after_switch"] = {"controller": turn.current() is not None, "can_open": can_open()}
    if can_open():
        body = show().as_string()
        result["after_switch"]["a"] = "Prompt: Make the crate bigger." in body
        result["after_switch"]["b"] = MARK.decode() in body
    operators.switch_chat(bpy.context, b)

    turn.shutdown_current()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    result["reopened"] = {"texts": [t.name for t in bpy.data.texts if t.name != chats.HOLDER],
                          "space": space().text is not None, "controller": turn.current() is not None,
                          "can_open": can_open()}
    if can_open():
        result["reopened"]["operator"] = sorted(bpy.ops.whittle.open_transcript())
        result["reopened"]["shown"] = MARK.decode() in bpy.data.texts[transcript.TEXT_NAME].as_string()

    show()
    off = SimpleNamespace(**{**prefs.DEFAULTS, "store_chats": False})
    with mock.patch.object(prefs, "get", return_value=off):
        bpy.ops.wm.save_mainfile(compress=False)
    result["save_chats_off"] = {"texts": in_file(BLEND), "bytes": carries_text(BLEND)}

    # Deleting another chat leaves the view; deleting the one it shows ends it,
    # and an undo step from before that, which still holds the Text, does not
    # bring it back: chats are never undone.
    bpy.ops.ed.undo_push(message="Transcript open")
    operators.delete_chat(bpy.context, a)
    result["deleted_another"] = transcript.TEXT_NAME in bpy.data.texts
    operators.delete_chat(bpy.context, b)
    result["deleted_it"] = {"open": transcript.TEXT_NAME in bpy.data.texts, "space": space().text is not None}
    bpy.ops.ed.undo_push(message="Chats deleted")
    bpy.ops.ed.undo()
    result["deleted_then_undone"] = {"open": transcript.TEXT_NAME in bpy.data.texts,
                                     "space": space().text is not None}
    bpy.ops.ed.redo()
    result["deleted_then_redone"] = transcript.TEXT_NAME in bpy.data.texts

    # A Text as an older Whittle left it: a plain datablock in the file.
    old = bpy.data.texts.new(transcript.TEXT_NAME)
    old.write(MARK.decode())
    space().text = old
    addon.unregister()
    bpy.ops.wm.save_mainfile(compress=False)
    result["older_file"] = {"texts": in_file(BLEND), "bytes": carries_text(BLEND)}
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    addon.register()
    addon._after_load()
    bpy.ops.wm.save_mainfile(compress=False)
    result["older_file_saved_again"] = {"texts": in_file(BLEND), "bytes": carries_text(BLEND)}
    result["errors"] = errors
    return result


try:
    print("RESULT " + json.dumps(main()), flush=True)
finally:
    turn.shutdown_current()
