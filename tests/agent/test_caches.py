# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.agent.test_chats import write_session
from whittle import caches, chats

DAY = 86400


class CacheDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-caches-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = self.tmp / "user" / "cache"
        self.files = self.tmp / "files"
        self.files.mkdir()
        self.config = self.tmp / "claude"

    def blend(self, name="scene.blend") -> Path:
        path = self.files / name
        path.write_bytes(b"BLENDER")
        return path

    def lock(self, root, pid, host=None):
        root.mkdir(parents=True, exist_ok=True)
        (root / caches.LOCK_NAME).write_text(json.dumps({"pid": pid, "host": host or caches._host()}))

    def dead_pid(self) -> int:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid


class IdTest(CacheDirCase):
    def test_ids_and_stamps(self):
        a, b = caches.new_file_id(), caches.new_file_id()
        self.assertNotEqual(a, b)
        self.assertTrue(caches.is_file_id(a))
        for bad in ("", "f123", "F" + "0" * 16, "../" + a, None, 3):
            self.assertFalse(caches.is_file_id(bad), bad)
        stamp = caches.state_stamp('{"chats": {}}', {"c1": b"x"})
        self.assertEqual(stamp, caches.state_stamp('{"chats": {}}', {"c1": b"x"}))
        self.assertNotEqual(stamp, caches.state_stamp('{"chats": {}}', {"c1": b"y"}))
        self.assertNotEqual(stamp, caches.state_stamp('{"chats": {} }', {"c1": b"x"}))

    def test_record(self):
        root = self.cache / caches.new_file_id()
        self.assertEqual(caches.read_record(root), {})
        caches.update_record(root, path="/x/a.blend", base="s1")
        caches.update_record(root, used=5.0)
        record = caches.read_record(root)
        self.assertEqual((record["id"], record["path"], record["base"], record["used"]),
                         (root.name, "/x/a.blend", "s1", 5.0))
        (root / caches.RECORD_NAME).write_text("not json")
        self.assertEqual(caches.read_record(root), {})


class FindTest(CacheDirCase):
    def test_the_stored_id_names_the_cache(self):
        blend = self.blend()
        file_id = caches.new_file_id()
        self.assertEqual(caches.find(self.cache, file_id, blend), (file_id, False), "no cache yet")
        caches.update_record(self.cache / file_id, path=str(blend))
        self.assertEqual(caches.find(self.cache, file_id, blend), (file_id, False))

    def test_a_moved_file_keeps_its_cache(self):
        file_id = caches.new_file_id()
        caches.update_record(self.cache / file_id, path=str(self.files / "gone.blend"))
        self.assertEqual(caches.find(self.cache, file_id, self.blend("moved.blend")), (file_id, False))

    def test_a_copy_gets_its_own(self):
        original, copy = self.blend("a.blend"), self.blend("copy.blend")
        file_id = caches.new_file_id()
        caches.update_record(self.cache / file_id, path=str(original))
        found, fresh = caches.find(self.cache, file_id, copy)
        self.assertTrue(fresh)
        self.assertTrue(caches.is_file_id(found))
        self.assertNotEqual(found, file_id)

    def test_a_copy_reuses_the_cache_it_got_until_it_is_saved(self):
        """A copy whose stored id is the original's opened before: the cache
        recording the copy's path comes back, so work since is not lost."""
        original, copy = self.blend("a.blend"), self.blend("copy.blend")
        file_id = caches.new_file_id()
        caches.update_record(self.cache / file_id, path=str(original))
        older, newer = caches.new_file_id(), caches.new_file_id()
        caches.update_record(self.cache / older, path=str(copy), used=time.time() - DAY)
        caches.update_record(self.cache / newer, path=str(copy), used=time.time())
        self.assertEqual(caches.find(self.cache, file_id, copy), (newer, True), "the most recently used")
        self.lock(self.cache / newer, os.getppid())
        self.assertEqual(caches.find(self.cache, file_id, copy), (older, True), "one in use is passed over")
        self.lock(self.cache / older, os.getppid())
        found, fresh = caches.find(self.cache, file_id, copy)
        self.assertTrue(fresh)
        self.assertNotIn(found, (file_id, older, newer), "none left: a fresh id")

    def test_a_cache_in_use_elsewhere_is_not_shared(self):
        blend = self.blend()
        file_id = caches.new_file_id()
        root = self.cache / file_id
        caches.update_record(root, path=str(blend))
        self.lock(root, os.getppid())
        self.assertTrue(caches.find(self.cache, file_id, blend)[1], "a live Blender has it open")
        self.lock(root, self.dead_pid())
        self.assertEqual(caches.find(self.cache, file_id, blend), (file_id, False), "a crashed one does not")
        caches.take(root)
        self.assertEqual(caches.find(self.cache, file_id, blend), (file_id, False), "this one may")
        caches.release(root)
        self.assertFalse((root / caches.LOCK_NAME).exists())
        self.lock(root, 1, host="elsewhere")
        self.assertTrue(caches.in_use_elsewhere(root))
        self.assertFalse(caches.in_use_elsewhere(root, here_only=True))

    def test_in_use_on_windows_asks_kernel32(self):
        # os.kill(pid, 0) is no probe there: it would send Ctrl+C.
        from tests.agent.test_platforms import FakeKernel
        from whittle import platforms

        root = self.cache / caches.new_file_id()
        self.lock(root, 1234)
        probe = platforms.pid_alive
        for kernel, expected in ((FakeKernel(), True), (FakeKernel(exit_code=0), False),
                                 (FakeKernel(fail={"open_process"}, error=87), False)):
            alive = lambda pid, kernel=kernel: probe(pid, "win32", kernel)
            with self.subTest(expected=expected), \
                    mock.patch.object(caches.platforms, "pid_alive", alive), \
                    mock.patch.object(caches.os, "kill", side_effect=AssertionError("os.kill")):
                self.assertEqual(caches.in_use_elsewhere(root), expected)
        caches.release(root)
        self.assertTrue((root / caches.LOCK_NAME).exists(), "another's claim stays")

    def test_a_file_without_an_id_finds_a_cache_by_its_path(self):
        blend = self.blend()
        self.assertEqual(caches.find(self.cache, None, blend), (None, False))
        old, recent, other = (caches.new_file_id() for _ in range(3))
        caches.update_record(self.cache / old, path=str(blend), used=time.time() - DAY)
        caches.update_record(self.cache / recent, path=str(blend))
        caches.update_record(self.cache / other, path=str(self.blend("other.blend")))
        self.assertEqual(caches.find(self.cache, None, blend), (recent, False))
        self.lock(self.cache / recent, os.getppid())
        self.assertEqual(caches.find(self.cache, None, blend), (old, False))
        self.assertEqual(caches.find(self.cache, None, None), (None, False), "never for an unsaved file")


class CleanupTest(CacheDirCase):
    def make(self, days, **record) -> Path:
        root = self.cache / caches.new_file_id()
        caches.update_record(root, used=time.time() - days * DAY, **record)
        return root

    def test_caches_not_used_for_30_days_go(self):
        stale, recent, open_here, held = self.make(31), self.make(29), self.make(90), self.make(90)
        self.lock(held, os.getppid())
        crashed = self.make(60)
        self.lock(crashed, self.dead_pid())
        foreign = self.make(60)
        self.lock(foreign, 1, host="elsewhere")
        chat = stale / "chats" / "c12345678"
        chat.mkdir(parents=True)
        cli = chats.cli_project_dir(chat, self.config)
        cli.mkdir(parents=True)
        mine = self.cache / "notes"
        mine.mkdir()
        gone = caches.cleanup(self.cache, keep=(open_here,), config=self.config)
        self.assertEqual(sorted(gone), sorted([stale.name, crashed.name, foreign.name]))
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()),
                         sorted([recent.name, open_here.name, held.name, "notes"]))
        self.assertFalse(cli.exists(), "the CLI's transcripts of its chats go too")

    def test_a_cache_without_a_record_goes_by_its_age(self):
        root = self.cache / caches.new_file_id()
        root.mkdir(parents=True)
        os.utime(root, (time.time() - 40 * DAY,) * 2)
        self.assertEqual(caches.cleanup(self.cache), [root.name])

    def test_an_earlier_versions_folders_in_the_user_dir(self):
        user = self.cache.parent
        old = user / "dev-sessions" / "20250101-120000"
        new = user / "dev-sessions" / "20261020-120000"
        for folder in (old, new):
            folder.mkdir(parents=True)
        os.utime(old, (time.time() - 40 * DAY,) * 2)
        self.assertEqual(caches.cleanup_old_layout(user), [old])
        self.assertTrue(new.is_dir())
        os.utime(new, (time.time() - 40 * DAY,) * 2)
        caches.cleanup_old_layout(user)
        self.assertFalse((user / "dev-sessions").exists(), "the empty folder goes")


class OldLayoutTest(CacheDirCase):
    def sidecar(self, blend, name=None) -> chats.Chats:
        found = chats.Chats(self.files / (name or f"{blend.stem}.whittle"))
        found.load()
        chat = found.new()
        write_session(found.folder(chat), ("Make a crate.",))
        found.refresh(chat, ended=True)
        found.pack_all()
        return found

    def test_only_whittles_own_folders_for_that_file(self):
        blend = self.blend()
        self.assertIsNone(caches.sidecar(blend))
        self.sidecar(blend)
        self.assertEqual(caches.sidecar(blend), self.files / "scene.whittle")
        aside = self.files / "scene.whittle.replaced-20260101-120000"
        (aside / "chats" / "c12345678").mkdir(parents=True)
        whole = self.files / "scene.whittle.replaced-20260102-120000"
        shutil.copytree(self.files / "scene.whittle", whole)
        for name in ("scene.whittle.replaced-later", "scene.whittle.notes", "scene2.whittle.replaced-20260101-120000"):
            (self.files / name / "chats" / "c12345678").mkdir(parents=True)
        mixed = self.files / "scene.whittle.replaced-20260103-120000"
        (mixed / "chats" / "c12345678").mkdir(parents=True)
        (mixed / "mine.txt").write_text("not Whittle's\n")
        self.assertEqual(caches.replaced(blend), [aside, whole])
        plain = self.files / "plain.whittle"
        plain.mkdir()
        (plain / "chats.json").write_text("{}")
        self.assertIsNone(caches.sidecar(self.blend("plain.blend")), "a folder Whittle did not make")

    def test_a_sidecar_moves_into_the_cache_once(self):
        blend = self.blend()
        old = self.sidecar(blend)
        chat = old.current
        root = self.cache / caches.new_file_id()
        self.assertTrue(caches.migrate_sidecar(self.files / "scene.whittle", root, self.config))
        moved = chats.Chats(root)
        moved.load()
        self.assertEqual(moved.listed(), [chat])
        self.assertTrue((moved.folder(chat) / "session.json").is_file())
        self.assertTrue(moved.packed_paths(chat)[0].is_file())
        self.assertFalse(caches.migrate_sidecar(self.files / "scene.whittle", root, self.config),
                         "never over chats the cache has")

    def test_a_single_session_sidecar_becomes_a_chat(self):
        side = self.files / "scene.whittle"
        side.mkdir()
        write_session(side, ("Make a crate.",), sessions=("s-1",))
        cli = chats.cli_project_dir(side, self.config)
        cli.mkdir(parents=True)
        (cli / "s-1.jsonl").write_text('{"type": "user"}\n')
        root = self.cache / caches.new_file_id()
        self.assertTrue(caches.migrate_sidecar(side, root, self.config))
        moved = chats.Chats(root)
        moved.load()
        (chat,) = moved.listed()
        self.assertTrue((moved.folder(chat) / "sdk" / "s-1.jsonl").is_file(), "its CLI transcript came along")
        caches.remove([side])
        self.assertFalse(side.exists())


if __name__ == "__main__":
    unittest.main()
