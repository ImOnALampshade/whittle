# SPDX-License-Identifier: GPL-3.0-or-later
"""One step of a file's life with its chats' cache, in a fresh Blender, for
tests/blender/test_cache.py:

    blender -b --factory-startup --python tests/blender/cache_file.py -- STEP ARGS...

    new BLEND FAKE         an unsaved file with a turn, saved as BLEND, a
                           turn, saved, reopened, a turn, saved
    open BLEND FAKE [turn] [save] [crash]
                           opens BLEND; with turn sends one, with save
                           saves it, with crash then exits as a crash
                           would (no handlers, the cache still claimed)

Prints one RESULT line of JSON: the file id, the cache root, its record,
the current chat's nodes and what the file's folder holds."""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import bpy  # noqa: E402

from tests.blender.helpers import pump  # noqa: E402
from tests.blender.history_helpers import STROKE  # noqa: E402
from tests.blender.sketch_helpers import add_stroke, look_at_view  # noqa: E402
from tests.fixtures.crate.scene import build_scene  # noqa: E402
from whittle import addon, caches  # noqa: E402
from whittle.addon import chats, history, operators, sketch, turn, views  # noqa: E402

STEP, *ARGS = sys.argv[sys.argv.index("--") + 1:]
errors = []


def send(prompt: str, fake: str) -> str:
    scene = bpy.context.scene
    obj = sketch.ensure_sketch_layers(scene)
    if not views.load_views(obj.data):
        views.add_view(obj.data, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))
    add_stroke(obj, "free", STROKE, view=1, radius=0.01)
    scene.whittle.prompt = prompt
    ctl, node = operators.submit_sketch(bpy.context, fake)
    pump(ctl, lambda: (ctl.last_finished or {}).get("turn_id") == node or ctl.errors, 30, f"turn {node}")
    errors.extend(ctl.errors)
    return node


def state(blend: str) -> dict:
    root = chats.root()
    hist = history.active()
    found = chats.get()
    return {"id": chats.file_id(), "root": str(root) if root else None,
            "record": caches.read_record(root) if root else {},
            "listed": found.listed() if found else [],
            "nodes": sorted(hist.tree.nodes) if hist is not None and hist.tree is not None else [],
            "folder": str(hist.session.root) if hist is not None else None,
            "beside": sorted(os.listdir(Path(blend).parent))}


def new(blend: str, fake: str) -> dict:
    addon.register()
    crate = build_scene()
    scene = bpy.context.scene
    scene.whittle.target_auto = False
    scene.whittle.targets.add().object = crate
    send("Make the crate bigger.", fake)
    out = {"unsaved": {"id": chats.file_id(), "root": str(chats.root()),
                       "record": caches.read_record(chats.root())}}
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    out["first_save"] = state(blend)
    send("Add a lid.", fake)
    bpy.ops.wm.save_mainfile()
    out["second_save"] = state(blend)
    turn.shutdown_current()
    bpy.ops.wm.open_mainfile(filepath=blend)
    out["reopened"] = state(blend)
    send("Round the edges.", fake)
    bpy.ops.wm.save_mainfile()
    out["third_save"] = state(blend)
    return out


def open_file(blend: str, fake: str, *flags) -> dict:
    addon.register()
    bpy.ops.wm.open_mainfile(filepath=blend)
    out = {"opened": state(blend)}
    if "turn" in flags:
        send("Nudge it.", fake)
        out["after_turn"] = state(blend)
    if "save" in flags:
        bpy.ops.wm.save_mainfile()
        out["saved"] = state(blend)
    if "crash" in flags:
        out["errors"] = errors
        print("RESULT " + json.dumps(out), flush=True)
        # No exit handlers, no release: the cache stays claimed by a
        # process that is gone, as after a crash.
        turn.shutdown_current()
        os._exit(0)
    return out


try:
    result = {"new": new, "open": open_file}[STEP](*ARGS)
    result["errors"] = errors
    print("RESULT " + json.dumps(result), flush=True)
finally:
    turn.shutdown_current()
