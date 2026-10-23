# SPDX-License-Identifier: GPL-3.0-or-later
"""The chats' cache is the file's own, in Whittle's user folder, named by
the id the file stores: saving, Save As and a copy leave it where it is, so
the controller carries on in the same chat, and nothing is written beside
the .blend."""

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import bpy

from tests.blender.helpers import FAKE_SCRIPTS, REPO, agent_python
from tests.blender.history_helpers import HistoryTurnCase
from whittle import caches, tree
from whittle.addon import chats, paths, turn


class CacheCase(HistoryTurnCase):
    def setUp(self):
        super().setUp()
        self.saved_as(None)
        chats.reset()
        self.session_dir = chats.current_folder(create=True)
        self.chat = self.session_dir.name

    def saved_as(self, blend):
        """As if the open file were now blend (None: never saved)."""
        patcher = mock.patch.object(paths, "blend_path", return_value=blend)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, blend, *, copy=False):
        """The save handlers, as a save to blend runs them."""
        from whittle import addon

        if not copy:
            self.saved_as(blend)
        addon._before_save(str(blend), None)
        addon._after_save(str(blend), None)

    def nodes(self, folder):
        found, _ = tree.read_session(folder / "session.json")
        return found


class SaveTest(CacheCase):
    def test_an_unsaved_file_has_a_cache_of_its_own(self):
        root = chats.root()
        self.assertEqual(root, self.user_dir / "cache" / chats.file_id())
        self.assertTrue(caches.is_file_id(chats.file_id()))
        self.assertEqual(self.session_dir.parents[1], root)
        record = caches.read_record(root)
        self.assertEqual((record["path"], record["base"]), (None, None))
        self.assertEqual(bpy.data.texts[chats.HOLDER][chats.ID_PROP], chats.file_id(),
                         "the file's data names its cache")

    def test_the_first_save_keeps_the_cache_and_the_controller(self):
        ctl = self.controller()
        n1 = self.turn(ctl, "Scale it.")
        root, file_id = chats.root(), chats.file_id()
        blend = self.user_dir / "saved" / "scene.blend"
        self.save(blend)
        self.assertIs(turn.current(), ctl)
        self.assertEqual((chats.root(), chats.file_id()), (root, file_id))
        record = caches.read_record(root)
        self.assertEqual(record["path"], str(blend))
        self.assertIsNotNone(record["base"], "the stamp of what the file now stores")
        self.assertEqual(bpy.data.texts[chats.HOLDER][chats.ID_PROP], file_id)
        n2 = self.turn(ctl, "Add a lid.")
        self.assertEqual((n2, ctl.history.node(n2).parent), ("n0002", n1))

    def test_save_as_records_the_new_name_and_a_copy_does_not(self):
        ctl = self.controller()
        self.turn(ctl, "Scale it.")
        root = chats.root()
        a, b = self.user_dir / "a.blend", self.user_dir / "b.blend"
        self.save(a)
        base = caches.read_record(root)["base"]
        self.save(b)
        self.assertEqual(caches.read_record(root)["path"], str(b))
        self.turn(ctl, "Add a lid.")
        self.save(self.user_dir / "copy.blend", copy=True)
        record = caches.read_record(root)
        self.assertEqual(record["path"], str(b), "a copy is not the open file")
        self.assertEqual(record["base"], base, "nor what it stores")
        self.assertEqual(chats.root(), root)

    def test_a_save_removes_an_earlier_versions_folders_beside_its_name(self):
        ctl = self.controller()
        self.turn(ctl, "Scale it.")
        side = self.user_dir / "b.whittle"
        side.mkdir()
        (side / "chats.json").write_text(json.dumps({"format": "whittle.chats", "version": 1,
                                                     "current": None, "chats": {}}))
        aside = self.user_dir / "b.whittle.replaced-20260101-120000"
        (aside / "chats" / "c12345678").mkdir(parents=True)
        others = [self.user_dir / "b.whittle.notes", self.user_dir / "b.whittle.replaced-later",
                  self.user_dir / "c.whittle"]
        for folder in others:
            folder.mkdir()
        (self.user_dir / "c.whittle" / "chats.json").write_text((side / "chats.json").read_text())
        self.save(self.user_dir / "b.blend")
        self.assertFalse(side.exists())
        self.assertFalse(aside.exists())
        self.assertTrue(all(folder.is_dir() for folder in others), "never anything else")


class SaveAndReopenTest(CacheCase):
    def test_reopened_file_finds_its_history(self):
        """A real Save As and open in a fresh Blender: the cache the turns
        used before the first save is the file's, and nothing is written
        beside it."""
        blend = self.user_dir / "saved" / "scene.blend"
        script = (
            f"import sys, json, os; sys.path.insert(0, {str(REPO)!r})\n"
            "import bpy\n"
            "from tests.blender.helpers import pump\n"
            "from tests.blender.history_helpers import STROKE\n"
            "from tests.blender.sketch_helpers import add_stroke, look_at_view\n"
            "from tests.fixtures.crate.scene import build_scene\n"
            "from whittle import addon\n"
            "from whittle.addon import history, operators, sketch, turn, views\n"
            "addon.register()\n"
            "crate = build_scene()\n"
            "scene = bpy.context.scene\n"
            "scene.whittle.targets.add().object = crate\n"
            "obj = sketch.ensure_sketch_layers(scene)\n"
            "views.add_view(obj.data, lambda i: look_at_view(i, (1.3, -1.5, 1.1), (0, 0, 0.3)))\n"
            "add_stroke(obj, 'free', STROKE, view=1, radius=0.01)\n"
            "scene.whittle.prompt = 'Scale it.'\n"
            f"ctl, n1 = operators.submit_sketch(bpy.context, {str(FAKE_SCRIPTS / 'history.json')!r})\n"
            "pump(ctl, lambda: (ctl.last_finished or {}).get('turn_id') == n1 or ctl.errors, 30, 'turn')\n"
            "first = str(ctl.session.root)\n"
            f"bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n"
            "after = str(turn.current().session.root)\n"
            f"bpy.ops.wm.open_mainfile(filepath={str(blend)!r})\n"
            "h = history.active()\n"
            "print('RESULT', json.dumps({'first': first, 'after': after, 'errors': ctl.errors,\n"
            "    'mirror': bpy.context.scene.whittle.history_node, 'reopened': str(h.session.root),\n"
            "    'current': h.current if h else None, 'nodes': sorted(h.tree.nodes) if h else [],\n"
            f"    'beside': sorted(os.listdir({str(blend.parent)!r}))}}))\n")
        blend.parent.mkdir()
        env = {**os.environ, "WHITTLE_USER_DIR": str(self.user_dir),
               "WHITTLE_AGENT_PYTHON": str(agent_python())}
        out = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python-expr", script],
                             capture_output=True, text=True, timeout=120, env=env)
        line = next((l for l in out.stdout.splitlines() if l.startswith("RESULT ")), None)
        self.assertIsNotNone(line, out.stdout[-2000:] + out.stderr[-2000:])
        result = json.loads(line[len("RESULT "):])
        self.assertEqual(result["errors"], [])
        self.assertEqual(Path(result["first"]).parents[2], self.user_dir / "cache")
        self.assertEqual(result["after"], result["first"], "saving leaves the cache where it is")
        self.assertEqual(result["reopened"], result["first"], "the file's id finds it again")
        self.assertEqual((result["mirror"], result["current"]), ("n0001", "n0001"))
        self.assertEqual(result["nodes"], ["n0000", "n0001"])
        self.assertEqual(result["beside"], ["scene.blend"])
