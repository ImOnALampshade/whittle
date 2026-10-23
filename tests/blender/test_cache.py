# SPDX-License-Identifier: GPL-3.0-or-later
"""A file's chats' cache over its life, each step in a fresh Blender
(tests/blender/cache_file.py): a new file saved and reopened, moved, copied
while its cache is another's, a crash with work newer than the last save,
a cache older than the file, and cleanup by age. Nothing is ever written
beside a .blend."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import bpy

from tests.blender.helpers import FAKE_SCRIPTS, REPO, AgentTestCase, agent_python
from whittle import caches

FAKE = str(FAKE_SCRIPTS / "history.json")
DAY = 86400


class CacheFileTest(AgentTestCase):
    def setUp(self):
        super().setUp()
        self.files = self.user_dir / "files"
        self.files.mkdir()
        self.cache = self.user_dir / "cache"

    def step(self, *args) -> dict:
        env = {**os.environ, "WHITTLE_USER_DIR": str(self.user_dir), "WHITTLE_AGENT_PYTHON": str(agent_python())}
        out = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python",
                              str(REPO / "tests" / "blender" / "cache_file.py"), "--", *map(str, args)],
                             capture_output=True, text=True, timeout=240, env=env)
        line = next((l for l in out.stdout.splitlines() if l.startswith("RESULT ")), None)
        self.assertIsNotNone(line, out.stdout[-3000:] + out.stderr[-3000:])
        result = json.loads(line[len("RESULT "):])
        self.assertEqual(result.get("errors"), [])
        return result

    def open(self, blend, *flags) -> dict:
        return self.step("open", blend, FAKE, *flags)

    def old_cache(self, name: str, days: float, *, lock_pid: int | None = None) -> Path:
        folder = self.cache / name
        caches.update_record(folder, path=str(self.files / "gone.blend"), used=time.time() - days * DAY)
        if lock_pid is not None:
            (folder / caches.LOCK_NAME).write_text(json.dumps({"pid": lock_pid, "host": caches._host()}))
        return folder

    def test_a_files_life(self):
        blend = self.files / "a" / "scene.blend"
        blend.parent.mkdir()
        r = self.step("new", blend, FAKE)
        file_id = r["unsaved"]["id"]
        root = self.cache / file_id
        self.assertEqual(Path(r["unsaved"]["root"]), root, "an unsaved file's cache is in the user folder")
        self.assertIsNone(r["unsaved"]["record"]["path"])
        for name in ("first_save", "second_save", "reopened", "third_save"):
            self.assertEqual((r[name]["id"], Path(r[name]["root"])), (file_id, root), f"{name}: the same cache")
            self.assertEqual(r[name]["record"]["path"], str(blend), name)
        self.assertEqual(r["first_save"]["beside"], ["scene.blend"])
        for name in ("second_save", "reopened", "third_save"):
            self.assertEqual(r[name]["beside"], ["scene.blend", "scene.blend1"], f"{name}: nothing beside the file")
        self.assertEqual(r["reopened"]["nodes"], ["n0000", "n0001", "n0002"])
        self.assertEqual(r["third_save"]["nodes"], ["n0000", "n0001", "n0002", "n0003"])

        # Moved and renamed, with its backup: the id finds the same cache.
        moved = self.files / "b" / "moved.blend"
        moved.parent.mkdir()
        os.rename(blend, moved)
        os.rename(blend.with_suffix(".blend1"), moved.with_suffix(".blend1"))
        r = self.open(moved)["opened"]
        self.assertEqual((r["id"], Path(r["root"])), (file_id, root))
        self.assertEqual(r["record"]["path"], str(moved))
        self.assertEqual(r["nodes"], ["n0000", "n0001", "n0002", "n0003"])
        self.assertEqual(r["beside"], ["moved.blend", "moved.blend1"])

        # A copy, while the original's cache records the original: one of its own.
        copy = self.files / "c" / "copy.blend"
        copy.parent.mkdir()
        shutil.copy2(moved, copy)
        r = self.open(copy)["opened"]
        self.assertNotEqual(r["id"], file_id)
        self.assertEqual(Path(r["root"]).parent, self.cache)
        self.assertEqual(r["record"]["path"], str(copy))
        self.assertEqual(r["nodes"], ["n0000", "n0001", "n0002", "n0003"], "filled from the copy")
        self.assertEqual(r["beside"], ["copy.blend"])
        self.assertEqual(caches.read_record(root)["path"], str(moved), "the original's cache untouched")
        self.assertEqual(self.open(moved)["opened"]["id"], file_id)

        # The copy, still unsaved with its own id, opened again: the same
        # cache, so a crash before its first save keeps its work.
        copy_id = r["id"]
        self.assertEqual(self.open(copy)["opened"]["id"], copy_id, "the copy keeps its id until saved")
        r = self.open(copy, "turn", "crash")
        self.assertEqual(r["opened"]["id"], copy_id)
        self.assertEqual(r["after_turn"]["nodes"], ["n0000", "n0001", "n0002", "n0003", "n0004"])
        r = self.open(copy)["opened"]
        self.assertEqual(r["id"], copy_id)
        self.assertEqual(r["nodes"], ["n0000", "n0001", "n0002", "n0003", "n0004"],
                         "the copy's unsaved work survives the crash")
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), sorted([file_id, copy_id]),
                         "no stray caches")
        self.assertEqual(r["beside"], ["copy.blend"])

        # The original's cache open in another Blender: a fresh one.
        (root / caches.LOCK_NAME).write_text(json.dumps({"pid": os.getpid(), "host": caches._host()}))
        r = self.open(moved)["opened"]
        self.assertNotEqual(r["id"], file_id)
        self.assertEqual(r["nodes"], ["n0000", "n0001", "n0002", "n0003"])
        (root / caches.LOCK_NAME).unlink()

        # Cleanup by age, on open: never the open file's, nor one in use.
        stale = self.old_cache("f00000000000000a1", 31)
        recent = self.old_cache("f00000000000000a2", 29)
        held = self.old_cache("f00000000000000a3", 90, lock_pid=os.getpid())
        caches.update_record(root, used=time.time() - 400 * DAY)

        # A crash after a turn that was not saved: the cache kept it.
        r = self.open(moved, "turn", "crash")
        self.assertEqual(r["after_turn"]["nodes"], ["n0000", "n0001", "n0002", "n0003", "n0004"])
        self.assertFalse(stale.exists(), "not used for 31 days")
        self.assertTrue(recent.is_dir())
        self.assertTrue(held.is_dir(), "in use by a live Blender")
        self.assertTrue((root / caches.LOCK_NAME).is_file(), "still claimed by the crashed Blender")
        r = self.open(moved)["opened"]
        self.assertEqual(r["id"], file_id, "a crashed Blender's claim does not count")
        self.assertEqual(r["nodes"], ["n0000", "n0001", "n0002", "n0003", "n0004"],
                         "work newer than the save, built on it, survives the crash")
        self.assertEqual(r["beside"], ["moved.blend", "moved.blend1"])

        # The file is the older save now: the cache was not built on it, and the file wins.
        os.replace(moved.with_suffix(".blend1"), moved)
        r = self.open(moved)["opened"]
        self.assertEqual(r["id"], file_id)
        self.assertEqual(r["nodes"], ["n0000", "n0001", "n0002"], "the cache's later turns are gone")
        self.assertEqual(r["beside"], ["moved.blend"])
        self.assertEqual([stale.exists(), recent.is_dir(), held.is_dir()], [False, True, True])
