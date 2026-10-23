# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from claude_agent_sdk import project_key_for_directory

from whittle import chats, formats, tree
from whittle.chats import Chats


def write_session(folder: Path, prompts=("Make a crate with rope handles on both sides, please",),
                  sessions=()) -> tree.Tree:
    """A session folder with a root and one finished turn per prompt."""
    t = tree.Tree.new()
    parent = t.root
    for i, prompt in enumerate(prompts, 1):
        node = formats.node_id(i)
        t.add(node, parent, prompt=prompt)
        session = sessions[i - 1] if i <= len(sessions) else None
        t.finish(node, status="complete", agent_session_id=session, snapshot=True)
        t.current = parent = node
    tree.write_session(folder / "session.json", t)
    for node in t.nodes:
        nodes = folder / "nodes" / node
        (nodes / "checkpoints").mkdir(parents=True, exist_ok=True)
        (nodes / "target.blend").write_bytes(os.urandom(2048))
        (nodes / "thumb.png").write_bytes(b"\x89PNG" + os.urandom(512))
        (nodes / "transcript.jsonl").write_text('{"v": 1}\n' * 20)
        (nodes / "checkpoints" / "start.blend").write_bytes(os.urandom(4096))
    return t


class TempRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-chats-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "scene.whittle"
        self.config = self.tmp / "claude"

    def chats(self, root=None) -> Chats:
        found = Chats(root or self.root)
        found.load()
        return found

    def chat_with_turns(self, found: Chats, prompts=("Make a crate.",), sessions=()) -> str:
        chat = found.new()
        write_session(found.folder(chat), prompts, sessions)
        found.began(chat, prompts[0])
        found.refresh(chat, ended=True)
        return chat


class WordsTest(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(chats.title_for("Add a lid."), "Add a lid")
        self.assertEqual(chats.title_for("\n  Add a lid.\nAnd hinges."), "Add a lid")
        self.assertEqual(chats.title_for("Horns?"), "Horns?", "only a full stop goes")
        self.assertEqual(chats.title_for("Wait..."), "Wait...")
        long = chats.title_for("Make a wooden crate with rope handles on both sides and a hinged lid")
        self.assertEqual(long, "Make a wooden crate with rope handles…")
        self.assertLessEqual(len(long), chats.TITLE_CHARS)
        self.assertEqual(chats.title_for("x" * 60), "x" * 39 + "…", "no space to cut at")
        self.assertEqual(chats.title_for("", "Crate"), "Sketch of Crate")
        self.assertEqual(chats.title_for("  \n"), "Sketch")

    def test_ages(self):
        cases = [(5, "just now"), (60, "1 minute ago"), (300, "5 minutes ago"), (3600, "1 hour ago"),
                 (7200, "2 hours ago"), (86400, "yesterday"), (3 * 86400, "3 days ago"),
                 (8 * 86400, "over a week ago"), (40 * 86400, "over a month ago"),
                 (400 * 86400, "over a year ago"), (-5, "just now")]
        for seconds, label in cases:
            self.assertEqual(chats.age_label(seconds), label, seconds)

    def test_sizes_and_times(self):
        self.assertEqual(chats.size_label(1_870_000), "1.9 MB")
        self.assertEqual(chats.size_label(1200), "0.1 MB")
        stamp = tree.now_iso()
        self.assertAlmostEqual(chats.epoch(stamp), time.time(), delta=2)
        self.assertAlmostEqual(chats.epoch(chats.iso(1.7e9)), 1.7e9, delta=1)
        self.assertEqual(chats.epoch("not a time"), 0.0)

    def test_project_key_matches_the_sdk(self):
        tmp = Path(tempfile.mkdtemp(prefix="whittle key é "))
        self.addCleanup(shutil.rmtree, tmp, True)
        long = tmp / ("chat-folder-" * 20)
        long.mkdir()
        for folder in (tmp, long):
            self.assertEqual(chats.project_key(folder), project_key_for_directory(folder))
        self.assertGreater(len(chats.project_key(long)), chats.MAX_PROJECT_KEY)
        self.assertEqual(chats.cli_project_dir(tmp, "/cfg"), Path("/cfg/projects") / chats.project_key(tmp))


class PackTest(TempRoot):
    def test_round_trip_leaves_scratch_out(self):
        folder = self.tmp / "chat"
        write_session(folder)
        (folder / "compare").mkdir()
        (folder / "compare" / "live.blend").write_bytes(b"live")
        (folder / ".session.json.abc.tmp").write_text("partial")
        (folder / "sdk").mkdir()
        (folder / "sdk" / "s1.jsonl").write_text('{"a": 1}\n{"b": 2}\n{"c"')
        data = chats.pack(folder)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            kinds = {i.filename: i.compress_type for i in zf.infolist()}
        self.assertIn("nodes/n0001/target.blend", names)
        self.assertFalse([n for n in names if "checkpoints" in n or n.startswith("compare") or n.endswith(".tmp")],
                         names)
        self.assertEqual(kinds["nodes/n0001/thumb.png"], zipfile.ZIP_STORED)
        self.assertEqual(kinds["nodes/n0001/target.blend"], zipfile.ZIP_STORED)
        self.assertEqual(kinds["session.json"], zipfile.ZIP_DEFLATED)
        self.assertEqual(chats.packed_size(folder), len(data))

        out = self.tmp / "out"
        chats.unpack(data, out)
        self.assertEqual((out / "session.json").read_bytes(), (folder / "session.json").read_bytes())
        self.assertEqual((out / "nodes/n0001/target.blend").read_bytes(),
                         (folder / "nodes/n0001/target.blend").read_bytes())
        self.assertEqual((out / "sdk" / "s1.jsonl").read_text(), '{"a": 1}\n{"b": 2}\n',
                         "a line being written is left out")
        self.assertFalse((out / "compare").exists())
        with self.assertRaises(FileExistsError):
            chats.unpack(data, out)

    def test_unsafe_members_are_refused(self):
        for name in ("../escape.txt", "/abs.txt", "a/../../b.txt", "c:/x.txt", "a\\b.txt"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("session.json", "{}")
                zf.writestr(name, "x")
            with self.assertRaises(formats.FormatError, msg=name):
                chats.unpack(buf.getvalue(), self.tmp / "out")
            self.assertFalse((self.tmp / "out").exists())
            self.assertFalse((self.tmp / "escape.txt").exists())
        with self.assertRaises(formats.FormatError):
            chats.unpack(b"not a zip", self.tmp / "out")

    def test_fingerprint_follows_writes(self):
        folder = self.tmp / "chat"
        write_session(folder)
        before = chats.fingerprint(folder)
        self.assertEqual(chats.fingerprint(folder), before)
        (folder / "nodes" / "n0001" / "checkpoints" / "c1.blend").write_bytes(b"x")
        self.assertEqual(chats.fingerprint(folder), before, "checkpoints are not packed")
        (folder / "nodes" / "n0001" / "transcript.jsonl").write_text("{}\n")
        self.assertNotEqual(chats.fingerprint(folder), before)


class IndexTest(TempRoot):
    def test_round_trip_and_validation(self):
        index = chats.Index(current="c0000abcd", chats={"c0000abcd": chats.Entry(
            title="Crate", created="2026-01-01T10:00:00+0000", updated="2026-01-02T10:00:00+0000",
            turns=3, size=12345, digest="ab")})
        path = self.tmp / "chats.json"
        chats.write_index(path, index)
        self.assertEqual(chats.read_index(path), index)
        good = index.to_json()
        for bad in ({**good, "format": "x"}, {**good, "current": "c1234567f"}, {**good, "chats": []},
                    {**good, "chats": {"nope": good["chats"]["c0000abcd"]}},
                    {**good, "chats": {"c0000abcd": {**good["chats"]["c0000abcd"], "turns": "3"}}},
                    {**good, "chats": {"c0000abcd": {**good["chats"]["c0000abcd"], "size": True}}}):
            with self.assertRaises(formats.FormatError):
                chats.validate_index(bad)

    def test_a_lost_index_is_rebuilt_from_the_folders(self):
        found = self.chats()
        chat = self.chat_with_turns(found, ("Make a crate.", "Add a lid."))
        found.index_path().unlink()
        again = self.chats()
        self.assertEqual(list(again.index.chats), [chat])
        self.assertEqual(again.current, chat)
        self.assertEqual((again.entry(chat).title, again.entry(chat).turns), ("Make a crate", 2))


class ChatsTest(TempRoot):
    def test_new_switch_and_titles(self):
        found = self.chats()
        self.assertIsNone(found.current)
        first = found.ensure_current()
        self.assertEqual(found.entry(first).title, chats.NEW_TITLE)
        self.assertEqual(found.new(), found.current)
        self.assertNotIn(first, found, "an empty chat is dropped when another becomes current")
        self.assertFalse(found.folder(first).exists())

        crate = found.current
        write_session(found.folder(crate))
        found.began(crate, "Make a wooden crate with rope handles on both sides", "Crate")
        found.refresh(crate, ended=True)
        entry = found.entry(crate)
        self.assertEqual((entry.title, entry.turns), ("Make a wooden crate with rope handles…", 1))
        self.assertGreater(entry.size, 2048)
        found.began(crate, "Something else")
        self.assertEqual(found.entry(crate).title, "Make a wooden crate with rope handles…",
                         "a title never changes by itself")

        barrel = found.new()
        found.began(barrel, "", "Barrel")
        self.assertEqual(found.entry(barrel).title, "Sketch of Barrel")
        write_session(found.folder(barrel), ("",))
        found.refresh(barrel, ended=True)
        self.assertEqual(found.listed()[0], barrel, "most recently active first")

        found.switch(crate)
        self.assertEqual((found.current, found.switched), (crate, crate))
        self.assertIn(barrel, found, "a chat with turns stays")
        found.new()
        self.assertIsNone(found.switched, "the next chat made current forgets the switch")
        self.assertEqual(self.chats().index, found.index, "every change is written at once")

    def test_a_chat_whose_only_turn_failed_goes_like_an_empty_one(self):
        found = self.chats()
        crate = self.chat_with_turns(found)
        failed = found.new()
        t = tree.Tree.new()
        t.add("n0001", t.root, prompt="Make a barrel.")
        t.finish("n0001", status="failed", folded=True)
        tree.write_session(found.folder(failed) / "session.json", t)
        found.refresh(failed, ended=True)
        self.assertEqual(found.entry(failed).turns, 0)
        found.switch(crate)
        self.assertNotIn(failed, found, "not listed, so not kept unseen in every save")
        self.assertFalse(found.folder(failed).exists())

    def test_a_chat_whose_history_cannot_be_read_is_kept(self):
        found = self.chats()
        crate = self.chat_with_turns(found)
        (found.folder(crate) / "session.json").write_text("{not json")
        (found.folder(crate) / "session.json.bad-x").write_text("kept for a person")
        found.new()
        self.assertIn(crate, found, "an unreadable history is not an empty one")
        self.assertTrue((found.folder(crate) / "session.json.bad-x").is_file())

    def test_a_chat_still_only_packed_is_kept(self):
        found = self.chats()
        crate = self.chat_with_turns(found)
        found.pack_all()
        shutil.rmtree(found.folder(crate))
        found.new()
        self.assertIn(crate, found)
        self.assertTrue(found.packed_paths(crate)[0].is_file())

    def test_rename(self):
        found = self.chats()
        chat = self.chat_with_turns(found, ("Make a crate.",))
        self.assertEqual(found.rename(chat, "  My   crate "), "My crate")
        self.assertTrue(found.read_chat(chat)["title_custom"])
        found.began(chat, "Another first prompt")
        self.assertEqual(found.entry(chat).title, "My crate")
        self.assertEqual(found.rename(chat, ""), "Make a crate", "empty puts the automatic title back")
        self.assertFalse(found.read_chat(chat)["title_custom"])

    def test_delete(self):
        found = self.chats()
        old = self.chat_with_turns(found, ("Old.",))
        found.entry(old).updated = chats.iso(time.time() - 40 * 86400)
        mid = self.chat_with_turns(found, ("Middle.",))
        found.entry(mid).updated = chats.iso(time.time() - 8 * 86400)
        new = self.chat_with_turns(found, ("New.",))
        cli = chats.cli_project_dir(found.folder(old), self.config)
        cli.mkdir(parents=True)
        (cli / "s.jsonl").write_text("{}\n")
        other_cli = chats.cli_project_dir(found.folder(mid), self.config)
        other_cli.mkdir(parents=True)

        self.assertEqual(found.to_delete("MONTH"), [old])
        self.assertEqual(found.to_delete("WEEK"), [mid, old])
        self.assertEqual(found.to_delete("QUARTER"), [])
        self.assertEqual(found.to_delete("OTHERS"), [mid, old])

        found.pack_all()
        self.assertEqual(found.delete(old, self.config), new)
        self.assertNotIn(old, found)
        self.assertFalse(found.folder(old).exists())
        self.assertFalse(any(p.exists() for p in found.packed_paths(old)))
        self.assertFalse(cli.exists(), "the CLI's transcripts of its cwd go")
        self.assertTrue(other_cli.exists(), "and only those")

        self.assertEqual(found.delete(new, self.config), mid, "the most recent other chat becomes current")
        self.assertEqual(found.switched, mid)
        last = found.delete(mid, self.config)
        self.assertNotIn(mid, found)
        self.assertEqual(list(found.index.chats), [last])
        self.assertEqual(found.entry(last).turns, 0, "with none left, an empty new chat")


class BlendTest(TempRoot):
    """What save_pre packs and load_post makes of it in another cache."""

    def saved(self):
        found = self.chats()
        crate = self.chat_with_turns(found, ("Make a crate.", "Add a lid."))
        barrel = self.chat_with_turns(found, ("Make a barrel.",))
        payload = found.pack_all()
        return found, crate, barrel, json.loads(chats.index_json(found.index)), payload

    def test_pack_all_repacks_only_what_changed(self):
        found, crate, barrel, index, payload = self.saved()
        self.assertEqual(set(payload), {crate, barrel})
        self.assertEqual(index["current"], barrel)
        self.assertEqual(index["chats"][crate]["size"], len(payload[crate]))
        stamp = found.packed_paths(crate)[0].stat().st_mtime_ns
        again = found.pack_all()
        self.assertEqual(again[crate], payload[crate])
        self.assertEqual(found.packed_paths(crate)[0].stat().st_mtime_ns, stamp, "unchanged, not packed again")
        (found.folder(crate) / "nodes" / "n0001" / "transcript.jsonl").write_text("{}\n")
        self.assertNotEqual(found.pack_all()[crate], payload[crate])

    def test_a_missing_cache_is_rebuilt(self):
        _found, crate, barrel, index, payload = self.saved()
        other = self.chats(self.tmp / "copy" / "scene.whittle")
        report = other.reconcile(index, payload)
        self.assertEqual(sorted(report["written"]), sorted([crate, barrel]))
        self.assertEqual(other.current, barrel)
        self.assertTrue((other.folder(barrel) / "session.json").is_file(), "the current chat is unpacked")
        self.assertFalse(other.folder(crate).exists(), "the others when first used")
        other.switch(crate)
        found, _ = tree.read_session(other.folder(crate) / "session.json")
        self.assertEqual(len(found.nodes), 3)
        self.assertTrue((other.folder(crate) / "nodes" / "n0002" / "thumb.png").is_file())
        self.assertEqual(other.pack_all()[barrel], payload[barrel], "an untouched chat goes back as it came")

    def test_a_cache_in_step_is_left_alone(self):
        found, crate, barrel, index, payload = self.saved()
        report = self.chats().reconcile(index, payload)
        self.assertEqual(sorted(report["in_step"]), sorted([crate, barrel]))
        self.assertEqual(report["discarded"], [])

    def test_the_blend_wins(self):
        found, crate, barrel, index, payload = self.saved()
        # After that save: a turn in crate, and a new chat, neither saved.
        (found.folder(crate) / "nodes" / "n0002" / "transcript.jsonl").write_text("changed\n")
        late = self.chat_with_turns(found, ("Made after the save.",))
        with self.assertLogs("whittle", "INFO"):
            report = self.chats().reconcile(index, payload)
        self.assertEqual(sorted(report["discarded"]), sorted([crate, late]))
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["scene.whittle"], "nothing moved aside")
        self.assertFalse(found.folder(late).exists())
        self.assertFalse(any(p.stem == late for p in (self.root / "packed").iterdir()))
        reopened = self.chats()
        self.assertEqual(set(reopened.index.chats), {crate, barrel})
        reopened.switch(crate)
        self.assertNotEqual((reopened.folder(crate) / "nodes" / "n0002" / "transcript.jsonl").read_text(),
                            "changed\n")

    def test_newer_work_on_the_files_chats_is_kept(self):
        found, crate, barrel, index, payload = self.saved()
        (found.folder(crate) / "nodes" / "n0002" / "transcript.jsonl").write_text("changed\n")
        late = self.chat_with_turns(found, ("Made after the save.",))
        report = self.chats().reconcile(index, payload, keep_newer=True)
        self.assertEqual(report["kept"], sorted([crate, barrel, late]))
        reopened = self.chats()
        self.assertEqual(set(reopened.index.chats), {crate, barrel, late})
        self.assertEqual((reopened.folder(crate) / "nodes" / "n0002" / "transcript.jsonl").read_text(),
                         "changed\n")

    def test_built_on(self):
        found, crate, barrel, index, payload = self.saved()
        self.chat_with_turns(found, ("Made after the save.",))
        (found.folder(crate) / "nodes" / "n0002" / "transcript.jsonl").write_text("changed\n")
        self.assertTrue(self.chats().built_on(index, payload), "newer work on exactly the file's chats")
        other = self.chats(self.tmp / "other.whittle")
        self.assertFalse(other.built_on(index, payload), "a cache without the file's chats")
        changed = dict(payload, **{crate: payload[barrel]})
        self.assertFalse(self.chats().built_on(index, changed), "a chat the file has otherwise")

    def test_a_history_the_file_does_not_have_goes(self):
        found = self.chats()
        crate = self.chat_with_turns(found, ("Make a crate.",))
        empty = found.new()
        index, payload = json.loads(chats.index_json(found.index)), found.pack_all()
        # After that save, a turn in the empty chat; then the saved file again.
        write_session(found.folder(empty), ("Made after the save.",))
        found.refresh(empty, ended=True)
        report = self.chats().reconcile(index, payload)
        self.assertIn(empty, report["discarded"])
        reopened = self.chats()
        self.assertFalse((reopened.folder(empty) / "session.json").exists(), "the file stores it empty")
        self.assertEqual(reopened.entry(empty).turns, 0)
        self.assertIn(crate, reopened)

    def test_an_empty_current_chat_comes_back(self):
        found = self.chats()
        crate = self.chat_with_turns(found, ("Make a crate.",))
        empty = found.new()
        payload = found.pack_all()
        self.assertEqual(set(payload), {crate})
        other = self.chats(self.tmp / "copy.whittle")
        other.reconcile(json.loads(chats.index_json(found.index)), payload)
        self.assertEqual(other.current, empty)
        self.assertEqual(other.listed(), [empty, crate])


class ModelTest(TempRoot):
    def test_a_chat_follows_the_default_until_its_first_turn(self):
        found = self.chats()
        chat = found.new()
        self.assertIsNone(found.model(chat))
        found.began(chat, "Make a crate.", model="claude-sonnet-5-5")
        self.assertEqual(found.model(chat), "claude-sonnet-5-5", "the first turn keeps its model")
        found.began(chat, "Add a lid.", model="claude-opus-5-5")
        self.assertEqual(found.model(chat), "claude-sonnet-5-5", "a later default does not move it")
        found.set_model(chat, " claude-opus-4-6 ")
        self.assertEqual(found.model(chat), "claude-opus-4-6")
        self.assertEqual(found.read_chat(chat)["model"], "claude-opus-4-6")
        self.assertEqual(self.chats().model(chat), "claude-opus-4-6", "kept in the index")
        found.set_model(chat, "")
        self.assertIsNone(found.model(chat))
        self.assertIsNone(found.model(None))

    def test_the_model_survives_a_lost_index_and_the_blend(self):
        found = self.chats()
        chat = self.chat_with_turns(found)
        found.set_model(chat, "claude-haiku-5-5")
        empty = found.new(model="claude-fable-5-1")
        payload = found.pack_all()
        index = json.loads(chats.index_json(found.index))
        other = self.chats(self.tmp / "copy.whittle")
        other.reconcile(index, payload)
        self.assertEqual((other.model(chat), other.model(empty)), ("claude-haiku-5-5", "claude-fable-5-1"))
        found.index_path().unlink()
        self.assertEqual(self.chats().model(chat), "claude-haiku-5-5")

    def test_an_index_from_before_models_reads(self):
        found = self.chats()
        chat = self.chat_with_turns(found)
        obj = json.loads(chats.index_json(found.index))
        del obj["chats"][chat]["model"]
        self.assertIsNone(chats.index_from_json(obj).chats[chat].model)
        obj["chats"][chat]["model"] = 4
        with self.assertRaises(formats.FormatError):
            chats.validate_index(obj)


class MigrateTest(TempRoot):
    def test_a_single_session_folder_becomes_the_first_chat(self):
        self.root.mkdir()
        write_session(self.root, ("Make a crate.", "Add a lid."), sessions=("s-1", "s-1"))
        (self.root / "compare").mkdir()
        cli = chats.cli_project_dir(self.root, self.config)
        (cli / "s-1" / "subagents").mkdir(parents=True)
        (cli / "s-1.jsonl").write_text('{"type": "user"}\n')
        (cli / "s-1" / "subagents" / "agent-1.jsonl").write_text('{"type": "user"}\n')
        (cli / "other.jsonl").write_text("{}\n")
        found = self.chats()
        chat = found.migrate(self.config)
        self.assertEqual(found.current, chat)
        folder = found.folder(chat)
        self.assertFalse((self.root / "session.json").exists())
        self.assertFalse((self.root / "nodes").exists())
        found_tree, _ = tree.read_session(folder / "session.json")
        self.assertEqual(found_tree.current, "n0002")
        self.assertTrue((folder / "nodes" / "n0002" / "target.blend").is_file())
        self.assertEqual(sorted(p.relative_to(folder / "sdk").as_posix() for p in (folder / "sdk").rglob("*.jsonl")),
                         ["s-1.jsonl", "s-1/subagents/agent-1.jsonl"],
                         "the CLI transcripts of its sessions, in the store's layout")
        entry = found.entry(chat)
        self.assertEqual((entry.title, entry.turns), ("Make a crate", 2))
        self.assertEqual(found.read_chat(chat)["created"], found_tree.created)
        self.assertIsNone(found.migrate(self.config), "nothing left to migrate")
        self.assertEqual(self.chats().index, found.index)
