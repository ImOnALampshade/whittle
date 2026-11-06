# SPDX-License-Identifier: GPL-3.0-or-later
"""Real saves of Style Notes paths in one fresh Blender, for
tests/blender/test_file_settings.py:

    blender -b --factory-startup --python tests/blender/style_path_file.py -- ROOT

ROOT holds a guide in style/ and folders for .blend files. A file with several
scenes goes through a first save, a plain save, Save As in its folder, a Save
Copy, a failed Save As, a Save As into another folder and an undo; a file linking
a scene from it through a Save As of its own; then each file saved is opened to
see what it carries. Then undo and redo across two moves, where a guide of the
same name waits in the new folder, and saves through a symlink and out of a folder
with a backslash in its name. Then first saves of files never saved, each
followed by what it left, and what happens to approvals on the way. Prints one
RESULT line of JSON."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import bpy  # noqa: E402

from whittle import addon, style  # noqa: E402
from whittle.addon import prefs, props  # noqa: E402

ROOT = Path(sys.argv[sys.argv.index("--") + 1])
STORE = props.FILE_SETTINGS["style_file"]
SCENES = {"Scene": "//../style/base.md", "Windows": "//..\\style\\base.md", "Inside": "//local.md",
          "Picked": str(ROOT / "style" / "base.md"), "Cleared": ""}
reads = []
during_saves = []


def values() -> dict:
    """What each scene stores: None where nothing is set."""
    return {scene.name: scene.whittle.get(STORE) for scene in bpy.data.scenes}


def guide(scene: str) -> str:
    return prefs.read_style_guide(bpy.data.scenes[scene].whittle.style_file).text


def counted(function):
    def wrapper(*args):
        reads.append(args)
        return function(*args)
    return wrapper


@bpy.app.handlers.persistent
def forget_reads(*_args):
    # First in save_pre.
    reads.clear()


@bpy.app.handlers.persistent
def note_reads(*_args):
    # First in save_post, so before the add-on's own read after a save.
    during_saves.append(len(reads))


def saved(function, **kwargs) -> dict:
    function(**kwargs)
    return values()


def fresh_file(blend: Path, path: str) -> None:
    """A new file saved at blend, with Style Notes set to path."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    blend.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.data.scenes.new("Scene") if not bpy.data.scenes else bpy.data.scenes[0]
    scene.name = "Scene"
    scene.whittle.style_file = path
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def state(scene: str = "Scene") -> dict:
    found = prefs.read_style_guide(bpy.data.scenes[scene].whittle.style_file)
    return {"path": bpy.data.scenes[scene].whittle.get(STORE), "guide": found.text, "problems": list(found.problems)}


def step_back_and_forth() -> None:
    """Undo steps from before what comes next, with the scene changed since."""
    bpy.ops.ed.undo_push(message="Before")
    bpy.data.scenes["Scene"].frame_current += 1
    bpy.ops.ed.undo_push(message="Moved")


def undo_across_moves() -> dict:
    result = {}
    write(ROOT / "p" / "style" / "a.md", "Right.")
    # What the old text names when it is counted from the new folders.
    write(ROOT / "q" / "x" / "style" / "a.md", "Other project's guide.")
    write(ROOT / "q" / "style" / "a.md", "Other project's guide.")
    write(ROOT / "q" / "z" / "local.md", "Set after the moves.")
    fresh_file(ROOT / "p" / "props" / "a.blend", "//../style/a.md")
    step_back_and_forth()
    save_as = bpy.ops.wm.save_as_mainfile
    (ROOT / "q" / "x" / "y").mkdir()
    save_as(filepath=str(ROOT / "q" / "x" / "y" / "a.blend"))
    moved = ROOT / "q" / "z" / "a.blend"
    save_as(filepath=str(moved))
    result["moved"] = state()
    bpy.ops.ed.undo()
    result["undone"] = state()
    bpy.ops.ed.redo()
    result["redone"] = state()
    bpy.ops.wm.save_mainfile()

    # Set in the new folder, so that is where it counts from.
    bpy.data.scenes.new("Later").whittle.style_file = "//local.md"
    bpy.ops.ed.undo_push(message="Set")
    bpy.data.scenes["Later"].whittle.style_file = "//other.md"
    bpy.ops.ed.undo_push(message="Changed")
    bpy.ops.ed.undo()
    result["set_after_the_moves"] = state("Later")

    # Undo keeps a scene that differs in neither step, rewritten as it is.
    bpy.data.scenes.new("Elsewhere")
    bpy.ops.ed.undo_push(message="Scene added")
    bpy.data.scenes["Elsewhere"].frame_current = 9
    bpy.ops.ed.undo_push(message="Elsewhere")
    (ROOT / "q" / "deep" / "w").mkdir(parents=True)
    save_as(filepath=str(ROOT / "q" / "deep" / "w" / "a.blend"))
    bpy.ops.ed.undo()
    result["untouched_by_the_undo"] = state()

    bpy.ops.wm.open_mainfile(filepath=str(moved))
    result["on_disk"] = state()
    # Opened again, it counts from here, whatever stamps it was saved with.
    step_back_and_forth()
    save_as(filepath=str(ROOT / "p" / "props" / "b.blend"))
    bpy.ops.ed.undo()
    result["after_reopening"] = state()
    return result


def through_a_symlink() -> dict | None:
    write(ROOT / "work" / "repo" / "style" / "a.md", "Right.")
    (ROOT / "nas" / "deep" / "shots").mkdir(parents=True)
    try:
        (ROOT / "work" / "shots").symlink_to(ROOT / "nas" / "deep" / "shots", target_is_directory=True)
    except OSError:
        return None  # Windows without the right to make one.
    fresh_file(ROOT / "work" / "repo" / "props" / "a.blend", "//../style/a.md")
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "work" / "shots" / "a.blend"))
    result = {"into": state()}
    (ROOT / "work" / "repo" / "chars").mkdir()
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "work" / "repo" / "chars" / "a.blend"))
    result["out_of"] = state()
    return result


def out_of_a_backslash_folder() -> dict | None:
    if os.sep != "/":
        return None
    write(ROOT / "odd\\name" / "g.md", "Beside.")
    fresh_file(ROOT / "odd\\name" / "a.blend", "//g.md")
    (ROOT / "other").mkdir()
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "other" / "b.blend"))
    return state()


def unsaved_file(path: str, stored: bool = False) -> None:
    """A new file with Style Notes set to path, or holding it as if it had
    come with something appended, which no setter saw."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.data.scenes.new("Scene") if not bpy.data.scenes else bpy.data.scenes[0]
    scene.name = "Scene"
    if stored:
        scene.whittle[STORE] = path
    else:
        scene.whittle.style_file = path


def stored_path() -> str:
    return bpy.data.scenes["Scene"].whittle.get(STORE)


def held() -> str:
    return prefs.held_guide(bpy.data.scenes["Scene"])


def first_saves() -> dict:
    result = {}
    save_as = bpy.ops.wm.save_as_mainfile
    root = ROOT / "first"
    guide = root / "style" / "g.md"
    write(guide, "First.")
    (root / "props").mkdir()

    # An undo after the first save brings back the text from before it.
    unsaved_file(str(guide))
    step_back_and_forth()
    blend = root / "props" / "a.blend"
    save_as(filepath=str(blend))
    result["saved"] = stored_path()
    result["saved_held"] = held()
    bpy.ops.ed.undo()
    result["undone"] = stored_path()
    bpy.ops.ed.redo()
    result["redone"] = stored_path()

    # A later save, and an absolute path set in the saved file, are left alone.
    bpy.ops.wm.save_mainfile()
    result["plain_save"] = stored_path()
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    result["on_disk"] = stored_path()
    bpy.data.scenes["Scene"].whittle.style_file = str(guide)
    bpy.ops.ed.undo_push(message="Set absolute")
    bpy.data.scenes["Scene"].frame_current = 30
    bpy.ops.ed.undo_push(message="Later")
    bpy.ops.wm.save_mainfile()
    result["set_in_a_saved_file"] = stored_path()
    bpy.ops.ed.undo()
    result["set_in_a_saved_file_undone"] = stored_path()

    # A Save As after it: the undo goes back past both.
    unsaved_file(str(guide))
    step_back_and_forth()
    save_as(filepath=str(blend))
    (root / "chars" / "orc").mkdir(parents=True)
    save_as(filepath=str(root / "chars" / "orc" / "a.blend"))
    result["moved_after"] = stored_path()
    bpy.ops.ed.undo()
    result["moved_after_undone"] = stored_path()

    # A copy of a file never saved, and a save that fails.
    unsaved_file(str(guide))
    copy = root / "props" / "copy.blend"
    save_as(filepath=str(copy), copy=True)
    result["copy_open"] = (bpy.data.filepath, stored_path())
    try:
        save_as(filepath=str(root / "missing" / "folder" / "a.blend"))
    except RuntimeError:
        result["failed"] = (bpy.data.filepath, stored_path())
    bpy.ops.wm.open_mainfile(filepath=str(copy))
    result["copy_on_disk"] = stored_path()
    result["copy_held"] = held()

    # A path nothing approved stays so, and a save does not read it.
    other = root / "style" / "other.md"
    write(other, "Unasked.")
    unsaved_file(str(other), stored=True)
    reads.clear()
    save_as(filepath=str(root / "props" / "b.blend"))
    result["unapproved"] = {"path": stored_path(), "held": held(), "reads": len(reads)}

    # A // path set before there was a folder to count from was still set here.
    write(root / "props" / "beside.md", "Beside.")
    unsaved_file("//beside.md")
    result["relative_before"] = held()
    save_as(filepath=str(root / "props" / "c.blend"))
    result["relative_after"] = {"path": stored_path(), "held": held()}
    return result


def approvals() -> dict:
    result = {}
    save_as = bpy.ops.wm.save_as_mainfile
    root = ROOT / "approvals"
    guide = root / "style" / "g.md"
    write(guide, "Approved.")
    (root / "props").mkdir()
    (root / "chars" / "orc").mkdir(parents=True)

    # Through Save As, Save Copy and undo, set once.
    fresh_file(root / "props" / "a.blend", "//../style/g.md")
    step_back_and_forth()
    save_as(filepath=str(root / "chars" / "orc" / "a.blend"))
    result["save_as"] = {"path": stored_path(), "held": held()}
    bpy.ops.ed.undo()
    result["undo"] = {"path": stored_path(), "held": held()}
    save_as(filepath=str(root / "props" / "b.blend"), copy=True)
    bpy.ops.wm.open_mainfile(filepath=str(root / "props" / "b.blend"))
    result["copy"] = {"path": stored_path(), "held": held()}

    # What was never approved is not approved by moving it.
    other = root / "style" / "other.md"
    write(other, "Unasked.")
    bpy.ops.wm.open_mainfile(filepath=str(root / "props" / "a.blend"))
    bpy.data.scenes["Scene"].whittle[STORE] = "//../style/other.md"
    reads.clear()
    save_as(filepath=str(root / "chars" / "orc" / "c.blend"))
    result["unapproved"] = {"path": stored_path(), "held": held(), "reads": len(reads)}

    # Text that a symlinked folder makes lead somewhere else as a string: the
    # approval goes with what the path names, not with the old text.
    (root / "nas" / "deep" / "shots").mkdir(parents=True)
    try:
        (root / "work").mkdir()
        (root / "work" / "shots").symlink_to(root / "nas" / "deep" / "shots", target_is_directory=True)
    except OSError:
        return result  # Windows without the right to make one.
    fresh_file(root / "props" / "d.blend", "//../style/g.md")
    save_as(filepath=str(root / "work" / "shots" / "d.blend"))
    result["symlink_save_as"] = {"path": stored_path(), "held": held(), "guide": state()["guide"]}
    unsaved_file(str(guide))
    save_as(filepath=str(root / "work" / "shots" / "e.blend"))
    result["symlink_first_save"] = {"path": stored_path(), "held": held(), "guide": state()["guide"]}
    return result


def main() -> dict:
    result = {}
    (ROOT / "props").mkdir(parents=True)
    (ROOT / "style").mkdir()
    (ROOT / "chars" / "orc").mkdir(parents=True)
    (ROOT / "style" / "base.md").write_text("Worn edges.")
    (ROOT / "props" / "local.md").write_text("Local.")
    bpy.context.scene.name = "Scene"
    for name in list(SCENES)[1:] + ["Absolute", "Unset"]:
        bpy.data.scenes.new(name)
    for name, path in SCENES.items():
        bpy.data.scenes[name].whittle.style_file = path

    blend = ROOT / "props" / "scene.blend"
    save_as = bpy.ops.wm.save_as_mainfile
    result["unsaved"] = values()
    result["first_save"] = saved(save_as, filepath=str(blend))
    # Set absolute once the file is saved, so that is what the user wants.
    bpy.data.scenes["Absolute"].whittle.style_file = str(ROOT / "style" / "base.md")
    result["set"] = values()
    result["plain_save"] = saved(bpy.ops.wm.save_mainfile)
    beside = ROOT / "props" / "beside.blend"
    result["same_folder"] = saved(save_as, filepath=str(beside))

    result["guide"] = guide("Scene")
    result["guide_windows"] = guide("Windows")
    result["cached_windows"] = prefs.style_guide(bpy.data.scenes["Windows"].whittle.style_file).text

    copy = ROOT / "chars" / "copy.blend"
    open_before = bpy.data.filepath
    result["copy"] = saved(save_as, filepath=str(copy), copy=True)
    result["copy_kept_the_open_file"] = bpy.data.filepath == open_before

    try:
        save_as(filepath=str(ROOT / "missing" / "folder" / "scene.blend"))
        result["failed"] = "saved"
    except RuntimeError:
        result["failed"] = values()
    result["failed_kept_the_open_file"] = bpy.data.filepath == open_before

    # An undo step from before the Save As, and the scene changed since it.
    bpy.ops.ed.undo_push(message="Before")
    bpy.context.scene.frame_current = 7
    bpy.ops.ed.undo_push(message="Moved")
    moved = ROOT / "chars" / "orc" / "scene.blend"
    result["save_as"] = saved(save_as, filepath=str(moved))
    result["guide_after_save_as"] = guide("Scene")
    result["guide_windows_after_save_as"] = guide("Windows")
    result["local_after_save_as"] = guide("Inside")
    result["preference_default"] = bpy.data.scenes["Unset"].whittle.style_file
    bpy.ops.ed.undo()
    result["after_undo"] = {"frame": bpy.context.scene.frame_current, "values": values()}
    bpy.ops.ed.redo()
    result["after_redo"] = {"frame": bpy.context.scene.frame_current, "values": values()}
    result["reads_during_saves"] = list(during_saves[:5])

    # A scene linked from another file is that file's to rewrite.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(blend), link=True) as (_source, linked):
        linked.scenes = ["Inside"]
    bpy.data.scenes.new("Zed").whittle.style_file = "//local.md"
    save_as(filepath=str(ROOT / "props" / "holder.blend"))
    save_as(filepath=str(ROOT / "chars" / "holder.blend"))
    result["local_beside_linked"] = bpy.data.scenes["Zed"].whittle.get(STORE)
    props.follow_style_paths()
    result["linked"] = next(scene for scene in bpy.data.scenes if scene.library).whittle.get(STORE)

    result["on_disk"] = {}
    for name, path in (("first", blend), ("beside", beside), ("copy", copy), ("moved", moved)):
        bpy.ops.wm.open_mainfile(filepath=str(path))
        result["on_disk"][name] = {"values": values(), "guide": guide("Scene")}

    result["undo_across_moves"] = undo_across_moves()
    result["symlink"] = through_a_symlink()
    result["backslash_folder"] = out_of_a_backslash_folder()
    result["first_saves"] = first_saves()
    result["approvals"] = approvals()
    return result


addon.register()
bpy.app.handlers.save_pre.insert(0, forget_reads)
bpy.app.handlers.save_post.insert(0, note_reads)
defaults = SimpleNamespace(**{**prefs.DEFAULTS, "style_file": "//preference.md"})
with mock.patch.object(prefs, "get", return_value=defaults), \
        mock.patch.object(style, "load_guide", counted(style.load_guide)):
    print("RESULT " + json.dumps(main()), flush=True)
