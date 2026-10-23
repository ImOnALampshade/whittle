# SPDX-License-Identifier: GPL-3.0-or-later
"""The file side of chats in one fresh Blender, for tests/blender/test_chats.py:

    blender -b --factory-startup --python tests/blender/chats_file.py -- BLEND FAKE_SCRIPT

Two chats are made through the operators and saved into BLEND; the file's
cache is deleted; the file is opened without the add-on (so the stored
chats can be seen in its data), then with it; an old node of the first chat
is restored; the first chat is deleted and the file saved again. Prints one
RESULT line of JSON."""

import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import bpy  # noqa: E402

from tests.blender.helpers import pump  # noqa: E402
from tests.blender.history_helpers import STROKE  # noqa: E402
from tests.blender.sketch_helpers import add_stroke, look_at_view  # noqa: E402
from tests.fixtures.crate.scene import build_scene  # noqa: E402
from whittle import addon  # noqa: E402
from whittle.addon import chats, history, operators, sketch, turn, views  # noqa: E402

BLEND, FAKE = sys.argv[sys.argv.index("--") + 1:][:2]
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


def holder_keys(prop: str) -> list[str]:
    text = bpy.data.texts.get(chats.HOLDER)
    if text is None or prop not in text:
        return []
    return sorted(text[prop].keys()) if prop == chats.PAYLOAD_PROP else [prop]


def nodes_of(chat: str) -> list[str]:
    operators.switch_chat(bpy.context, chat)
    return sorted(history.active().tree.nodes)


def main() -> dict:
    addon.register()
    crate = build_scene()
    scene = bpy.context.scene
    scene.whittle.target_auto = False
    scene.whittle.targets.add().object = crate
    send("Make the crate bigger.")
    send("Add a lid.")
    a = chats.get().current
    operators.new_chat(bpy.context)
    send("Recolour it.")
    b = chats.get().current

    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    result = {"a": a, "b": b, "in_memory_after_save": holder_keys(chats.INDEX_PROP)
              + holder_keys(chats.PAYLOAD_PROP)}
    cache = chats.root()
    result["cache_in_user_dir"] = cache.parent == Path(os.environ["WHITTLE_USER_DIR"]) / "cache"
    turn.shutdown_current()
    shutil.rmtree(cache)
    result["cache_after_delete"] = cache.exists()

    # Without the add-on nothing takes the chats out of the opened file.
    addon.unregister()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    result["in_file"] = holder_keys(chats.PAYLOAD_PROP)
    addon.register()
    addon._after_load()
    store = chats.get()
    listed, current = store.listed(), store.current
    nodes = {b: sorted(history.active().tree.nodes)}
    thumbs = history.active().session.thumb_path("n0001").is_file()
    nodes[a] = nodes_of(a)
    operators.restore_node(bpy.context, "n0001")
    result["reopened"] = {
        "listed": listed, "current": current, "nodes": nodes, "thumbs": thumbs,
        "titles": {c: store.entry(c).title for c in listed},
        "restored": {"lid": "Crate_Lid" in bpy.data.objects,
                     "scale": round(bpy.data.objects["Crate"].scale.x, 4)}}

    # Uncompressed, so the sizes say what the chats take: zstd would also
    # fold the snapshots the two chats share.
    bpy.ops.wm.save_mainfile(compress=False)
    before = os.path.getsize(BLEND)
    packed_a = store.entry(a).size
    operators.delete_chat(bpy.context, a)
    bpy.ops.wm.save_mainfile(compress=False)
    result["sizes"] = {"before_delete": before, "packed_a": packed_a, "after_delete": os.path.getsize(BLEND)}
    turn.shutdown_current()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    result["after_delete_listed"] = chats.get().listed()
    result["beside"] = sorted(os.listdir(Path(BLEND).parent))
    result["errors"] = errors
    return result


try:
    print("RESULT " + json.dumps(main()), flush=True)
finally:
    turn.shutdown_current()
