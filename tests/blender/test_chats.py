# SPDX-License-Identifier: GPL-3.0-or-later
"""Chats: New Chat, switching (the scene stays, the next turn resumes that
chat's session), deleting one or many, the chat menu, a chat made on
another machine, the same file open twice, and keeping every chat in the
.blend."""

import json
import os
import shutil
import subprocess
import time
from unittest import mock

import bpy

from tests.blender.helpers import FAKE_SCRIPTS, REPO, agent_python
from tests.blender.history_helpers import STROKE, HistoryTurnCase
from tests.blender.sketch_helpers import add_stroke
from tests.blender.ui_helpers import RecordingLayout
from whittle import caches
from whittle import chats as chat_store
from whittle import tree
from whittle.addon import chats, conversation, history, operators, paths, turn, ui


def scene_state() -> dict:
    """Every object as the scene has it: what switching must not touch."""
    out = {}
    for obj in bpy.context.scene.objects:
        data = obj.data
        out[obj.name] = (tuple(round(v, 6) for v in obj.location), tuple(round(v, 6) for v in obj.scale),
                         len(data.vertices) if hasattr(data, "vertices") else None)
    return out


class ChatCase(HistoryTurnCase):
    """An unsaved file whose turns go through the operators, so each chat
    gets its controller the way the sidebar's buttons make one."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(paths, "blend_path", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"WHITTLE_AGENT_PYTHON": str(agent_python())})
        env.start()
        self.addCleanup(env.stop)
        chats.reset()
        self.addCleanup(chats.reset)
        self.addCleanup(turn.shutdown_current)
        self.fake = str(FAKE_SCRIPTS / "history.json")

    def send(self, prompt: str) -> tuple:
        """Types the prompt, draws a stroke and presses Send; waits for the turn."""
        add_stroke(self.obj, "free", STROKE, view=1, radius=0.01)
        self.props.prompt = prompt
        ctl, node = operators.submit_sketch(bpy.context, self.fake)
        if ctl not in self.controllers:
            self.controllers.append(ctl)
        self.wait(ctl, node)
        return ctl, node

    @property
    def store(self) -> chat_store.Chats:
        return chats.get()

    def two_chats(self):
        """Chat A with two turns (scale, then a lid), then chat B with one."""
        ctl, a1 = self.send("Make the crate bigger.")
        _ctl, a2 = self.send("Add a lid.")
        a = self.store.current
        operators.new_chat(bpy.context)
        _ctl, b1 = self.send("Make it bigger again.")
        b = self.store.current
        return a, (a1, a2), b, b1


class NewChatTest(ChatCase):
    def test_new_chat_starts_a_fresh_history_and_session(self):
        found = chats.get()
        self.assertIsNone(found, "nothing is made before the first run")
        self.assertEqual(operators.can_new_chat(found, None), operators.CHAT_NEW_ALREADY)
        ctl, n1 = self.send("Make the crate bigger.")
        a = self.store.current
        self.assertEqual(ctl.session.root, self.store.folder(a))
        self.assertEqual(ctl.session.root.parents[2], self.user_dir / "cache", "an unsaved file")
        self.assertEqual(self.store.entry(a).title, "Make the crate bigger")
        self.assertEqual(self.store.entry(a).turns, 1)
        self.assertEqual(ctl.session_starts[0]["store_dir"], str(self.store.folder(a) / "sdk"))
        self.assertEqual(self.props.chat, a)
        self.assertIsNone(operators.can_new_chat(self.store, ctl))

        before = scene_state()
        self.assertEqual(bpy.ops.whittle.chat_new(), {"FINISHED"})
        b = self.store.current
        self.assertNotEqual(b, a)
        self.assertEqual(scene_state(), before, "New Chat leaves the scene alone")
        self.assertIsNone(turn.current(), "the old chat's agent stopped")
        self.assertEqual(ctl.process.state, "stopped")
        self.assertIsNone(history.active(), "the new chat has no history yet")
        self.assertEqual((self.props.chat, self.props.history_node), (b, ""))
        self.assertEqual(self.store.listed(), [b, a])
        self.assertEqual(operators.can_new_chat(self.store, None), operators.CHAT_NEW_ALREADY)
        self.assertFalse(bpy.ops.whittle.chat_new.poll())

        ctl2, m1 = self.send("Add a lid.")
        self.assertIsNot(ctl2, ctl)
        self.assertEqual(ctl2.session.root, self.store.folder(b))
        self.assertEqual([(s["resume"], s["fork"]) for s in ctl2.session_starts], [(None, False)],
                         "a fresh SDK session")
        hist = history.active()
        self.assertEqual((hist.tree.root, hist.tree.node(m1).parent), ("n0000", "n0000"), "its own node 0")
        self.assertEqual(m1, "n0001", "node numbers start again in each chat")
        self.assertEqual(self.context_lines(ctl2, m1), [])
        self.assertNotEqual(hist.node(m1).agent_session_id, ctl.history.node(n1).agent_session_id)
        self.assertEqual(self.store.entry(b).title, "Add a lid")

    def test_new_chat_waits_for_the_turn(self):
        add_stroke(self.obj, "free", STROKE, view=1, radius=0.01)
        self.props.prompt = "Make the crate bigger."
        self.fake = str(FAKE_SCRIPTS / "history_interrupt.json")
        ctl, node = operators.submit_sketch(bpy.context, self.fake)
        self.controllers.append(ctl)
        self.assertEqual(operators.can_new_chat(self.store, ctl), operators.CHAT_WAIT)
        self.assertEqual(operators.can_switch_chat(self.store, ctl, self.store.current), operators.CHAT_WAIT)
        self.assertFalse(bpy.ops.whittle.chat_new.poll())
        with self.assertRaises(RuntimeError):
            operators.new_chat(bpy.context)
        with self.assertRaises(RuntimeError):
            operators.delete_chat(bpy.context, self.store.current)
        ctl.interrupt(restore=False)
        self.wait(ctl, node)
        self.assertIsNone(operators.can_new_chat(self.store, ctl))

    def test_new_chat_twice_leaves_no_empty_chat(self):
        self.send("Make the crate bigger.")
        operators.new_chat(bpy.context)
        empty = self.store.current
        a = self.store.listed()[1]
        operators.switch_chat(bpy.context, a)
        self.assertNotIn(empty, self.store)
        self.assertFalse(self.store.folder(empty).exists())


class SwitchTest(ChatCase):
    def test_switching_leaves_the_scene_and_resumes_that_chats_session(self):
        a, (a1, a2), b, b1 = self.two_chats()
        a_session = chats.get().folder(a)
        found, _ = tree.read_session(a_session / "session.json")
        session = found.node(a2).agent_session_id
        before = scene_state()
        self.assertIn("Crate_Lid", before)

        self.assertEqual(bpy.ops.whittle.chat_switch(chat=a), {"FINISHED"})
        self.assertEqual(scene_state(), before, "switching never touches the scene")
        self.assertIsNone(turn.current())
        hist = history.active()
        self.assertEqual(hist.session.root, a_session)
        self.assertEqual(hist.current, a2, "the chat's own current turn")
        self.assertEqual((self.props.chat, self.props.history_node), (a, a2))
        conv = conversation.build(hist, None)
        self.assertEqual([t.prompt for t in conv.path_turns], ["Make the crate bigger.", "Add a lid."])

        layout = RecordingLayout()
        ui.draw_main(layout, ui.Ctx(scene=self.scene, hist=hist, ctl=None, comparing=None, width=240,
                                    chats=self.store))
        self.assertIn(ui.SWITCHED_NOTE, layout.text())

        ctl, a3 = self.send("Nudge it.")
        start = ctl.session_starts[0]
        self.assertEqual((start["resume"], start["fork"]), (session, False), "that chat's session resumes")
        self.assertEqual(start["store_dir"], str(a_session / "sdk"))
        self.assertIn(chats.SWITCH_NOTE, self.context_lines(ctl, a3))
        logs = [e["data"]["message"] for e in ctl.events if e["name"] == "log"]
        self.assertTrue(any("stored_lines=2" in line for line in logs), "its transcript is in its store")
        self.assertEqual(ctl.history.node(a3).parent, a2)
        self.assertIsNone(self.store.switched, "said once")
        _ctl, a4 = self.send("Nudge it again.")
        self.assertEqual(self.context_lines(ctl, a4), [])
        self.assertEqual(self.store.listed()[0], a)

    def test_the_history_of_a_switched_to_chat_can_be_restored(self):
        a, (a1, a2), b, b1 = self.two_chats()
        operators.switch_chat(bpy.context, a)
        operators.restore_node(bpy.context, a1)
        self.assertNotIn("Crate_Lid", bpy.data.objects, "a restore in A removes what A's agent made")
        self.assertEqual(history.active().current, a1)
        self.assertEqual(self.props.chat, a)

    def test_undo_never_changes_the_chat(self):
        from whittle import addon

        a, (a1, a2), b, b1 = self.two_chats()
        operators.switch_chat(bpy.context, a)
        # An undo step from before the switch: the scene showed B's turn.
        self.props.chat, self.props.history_node = b, b1
        addon._after_undo()
        self.assertEqual(self.store.current, a)
        self.assertEqual(history.active().current, a2, "another chat's node is not applied")
        self.props.chat, self.props.history_node = a, a1
        addon._after_undo()
        self.assertEqual(history.active().current, a1, "the current chat's own undo still works")

    def test_switching_waits_while_comparing(self):
        a, (a1, a2), b, b1 = self.two_chats()
        operators.compare_node(bpy.context, "n0000")
        self.assertEqual(operators.can_switch_chat(self.store, turn.current(), a), operators.CHAT_COMPARING)
        with self.assertRaises(RuntimeError):
            operators.switch_chat(bpy.context, a)
        from whittle.addon import compare

        compare.active().end(self.scene, keep=False)


class DeleteTest(ChatCase):
    def test_delete_another_chat_and_the_current_one(self):
        a, (a1, a2), b, b1 = self.two_chats()
        operators.new_chat(bpy.context)
        _ctl, c1 = self.send("A third.")
        c = self.store.current
        cli = chat_store.cli_project_dir(self.store.folder(a), chats.config_dir())
        cli.mkdir(parents=True)
        self.assertTrue(str(cli).startswith(str(self.user_dir)), "the tests' own CLI folder")

        self.assertEqual(bpy.ops.whittle.chat_delete(chat=a), {"FINISHED"})
        self.assertNotIn(a, self.store)
        self.assertFalse((self.store.root / "chats" / a).exists())
        self.assertFalse(cli.exists())
        self.assertEqual(self.store.current, c, "deleting another chat keeps this one")
        self.assertIsNotNone(turn.current())

        before = scene_state()
        operators.delete_chat(bpy.context, c)
        self.assertEqual(self.store.current, b, "the most recent other chat")
        self.assertEqual(scene_state(), before, "as a switch: the scene stays")
        self.assertEqual(history.active().session.root, self.store.folder(b))
        self.assertEqual(self.props.chat, b)
        self.assertEqual(self.store.switched, b)

        operators.delete_chat(bpy.context, b)
        (only,) = self.store.listed()
        self.assertEqual(self.store.entry(only).turns, 0, "none left: an empty new chat")
        self.assertIsNone(history.active())

    def test_delete_many(self):
        a, (a1, a2), b, b1 = self.two_chats()
        operators.new_chat(bpy.context)
        self.send("A third.")
        store = self.store
        store.entry(a).updated = chat_store.iso(time.time() - 100 * 86400)
        store.entry(b).updated = chat_store.iso(time.time() - 10 * 86400)
        store.save()
        self.assertEqual(delete_count(bpy.ops.whittle.chat_delete_many, "QUARTER"), 1)
        self.assertEqual(store.listed(), [store.current, b])
        self.assertEqual(operators.delete_chats(bpy.context, "MONTH"), [])
        self.assertEqual(operators.delete_chats(bpy.context, "OTHERS"), [b])
        self.assertEqual(store.listed(), [store.current])
        self.assertFalse(bpy.ops.whittle.chat_delete_many.poll(), "no other chats")


def delete_count(op, which) -> int:
    before = len(chats.get().listed())
    op(which=which)
    return before - len(chats.get().listed())


class ChatMenuTest(ChatCase):
    def menu(self, ctl=None) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_chats(layout, ui.Ctx(scene=self.scene, hist=None, ctl=ctl, comparing=None, width=336,
                                     chats=chats.get()))
        return layout

    def test_the_menu_lists_every_chat(self):
        a, (a1, a2), b, b1 = self.two_chats()
        layout = self.menu()
        ops = layout.operators()
        self.assertEqual(ops[0]["idname"], "whittle.chat_new", "New Chat first")
        self.assertIn("Conversations", layout.labels())
        switches = layout.operators("whittle.chat_switch")
        self.assertEqual([(c["props"].chat, c.get("depress", False)) for c in switches], [(b, False), (a, False)],
                         "the check mark alone marks the current chat")
        self.assertEqual([c["text"] for c in switches], ["Make it bigger again", "Make the crate bigger"])
        self.assertEqual([c["props"].chat for c in layout.operators("whittle.chat_delete")][:1], [a],
                         "a trash icon on the others")
        self.assertEqual(len([c for c in layout.of("label") if c["icon"] == "CHECKMARK"]), 1)
        lines = [t for t in layout.labels() if " turn" in t]
        self.assertRegex(lines[0], r"^1 turn · just now · \d+\.\d MB$")
        self.assertRegex(lines[1], r"^2 turns · ")
        self.assertTrue(any(t.startswith("2 chats · ") and t.endswith("when saved") for t in layout.labels()))
        footer = [c["text"] for c in layout.operators() if c["idname"] != "whittle.chat_switch"
                  and c["text"]]
        self.assertEqual(footer, ["New Chat", "Rename This Chat…", "Delete This Chat…", "Delete Other Chats…"])
        self.no_red(layout)

        busy = self.menu(ctl=mock.Mock(busy=True, running=True, question=None))
        (delete_this,) = [c for c in busy.operators("whittle.chat_delete") if c["text"]]
        self.assertFalse(busy.is_enabled(delete_this), "not while a turn runs in it")

        title = RecordingLayout()
        ui.draw_chat_title(title, ui.Ctx(scene=self.scene, hist=None, ctl=None, comparing=None, width=240,
                                         chats=chats.get()))
        (popover,) = title.of("popover")
        self.assertEqual((popover["panel"], popover["text"]), ("WHITTLE_PT_chats", "Make it bigger again"))

    def test_many_chats(self):
        self.send("Make the crate bigger.")
        store = self.store
        first = store.current
        now = time.time()
        for i in range(24):
            chat = store.new()
            shutil.rmtree(store.folder(chat))
            shutil.copytree(store.folder(first), store.folder(chat))
            store.refresh(chat)
            store.entry(chat).title = f"Chat number {i} with a title long enough to be cut somewhere"
            store.entry(chat).updated = chat_store.iso(now - i * 86400)
        store.save()
        layout = self.menu()
        self.assertEqual(len(layout.operators("whittle.chat_switch")), ui.CHATS_SHOWN)
        (more,) = [c for c in layout.of("prop") if c["prop"] == "whittle_show_all_chats"]
        self.assertEqual(more["text"], "Show 5 More")
        titles = [c["text"] for c in layout.operators("whittle.chat_switch") if c["text"].startswith("Chat")]
        self.assertTrue(titles and all(t.endswith("…") for t in titles), titles)
        bpy.context.window_manager.whittle_show_all_chats = True
        self.addCleanup(setattr, bpy.context.window_manager, "whittle_show_all_chats", False)
        self.assertEqual(len(self.menu().operators("whittle.chat_switch")), 25)

    def no_red(self, layout):
        red = [c.get("text") or c.get("idname") for c in layout.calls
               if c["kind"] in ("label", "operator") and layout.alerted(c)]
        self.assertEqual(red, [])


class RenameTest(ChatCase):
    def test_rename_and_back(self):
        self.send("Make the crate bigger.")
        chat = self.store.current
        self.assertEqual(operators.rename_chat(bpy.context, "Crate"), "Crate")
        self.assertEqual(self.store.entry(chat).title, "Crate")
        self.assertEqual(operators.rename_chat(bpy.context, ""), "Make the crate bigger")


class ForeignChatTest(ChatCase):
    """A chat made by another install reads, but sends nothing until
    Continue; this install's chats never ask."""

    def draw(self) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_main(layout, ui.Ctx(scene=self.scene, hist=history.active(), ctl=turn.current(),
                                    comparing=None, width=240, chats=self.store))
        return layout

    def test_continue_this_chat(self):
        _ctl, n1 = self.send("Make the crate bigger.")
        found, chat = self.store, self.store.current
        self.assertEqual(found.origin, chats.install_id())
        self.assertEqual(found.entry(chat).origin, chats.install_id(), "made here")
        self.assertNotIn(ui.FOREIGN_TITLE, self.draw().labels())

        # As if the file came from another machine.
        found.entry(chat).origin = "i00000000000000ff"
        found.save()
        self.assertTrue(chats.current_foreign())
        self.props.prompt = "Add a lid."
        layout = self.draw()
        self.assertIn(ui.FOREIGN_TITLE, layout.labels())
        self.assertIn(ui.FOREIGN_NOTE, layout.text())
        (cont,) = layout.operators("whittle.chat_continue")
        self.assertEqual(cont["text"], "Continue")
        (send,) = layout.operators("whittle.submit")
        self.assertFalse(layout.is_enabled(send), "read-only until continued")
        self.assertFalse(bpy.ops.whittle.submit.poll(), "its tooltip says why")
        with self.assertRaises(RuntimeError):
            operators.submit_sketch(bpy.context, self.fake)
        self.assertEqual(self.props.prompt, "Add a lid.", "the draft stays")
        self.assertTrue(bpy.ops.whittle.chat_new.poll(), "New Chat stays available")

        self.assertEqual(bpy.ops.whittle.chat_continue(), {"FINISHED"})
        self.assertFalse(chats.current_foreign())
        self.assertEqual(found.entry(chat).adopted, [chats.install_id()])
        self.assertEqual(found.read_chat(chat)["adopted"], [chats.install_id()], "stored with the chat")
        self.assertNotIn(ui.FOREIGN_TITLE, self.draw().labels())
        self.assertFalse(bpy.ops.whittle.chat_continue.poll(), "never asked again")
        _ctl, n2 = self.send("Add a lid.")
        self.assertEqual(history.active().tree.node(n2).parent, n1)

    def test_chats_from_before_origins_never_ask(self):
        self.send("Make the crate bigger.")
        found = self.store
        found.entry(found.current).origin = None
        found.save()
        self.assertFalse(chats.current_foreign())
        self.assertTrue(bpy.ops.whittle.submit.poll())


class ElsewhereTest(ChatCase):
    def test_a_line_while_another_blender_has_the_file(self):
        self.send("Make the crate bigger.")
        blend = self.user_dir / "scene.blend"
        blend.write_bytes(b"BLENDER")
        other = self.user_dir / "cache" / caches.new_file_id()
        caches.update_record(other, path=str(blend))
        (other / caches.LOCK_NAME).write_text(json.dumps({"pid": os.getppid(), "host": caches._host()}))
        layout = RecordingLayout()
        ctx = ui.Ctx(scene=self.scene, hist=history.active(), ctl=None, comparing=None, width=240,
                     chats=self.store)
        ui.draw_main(layout, ctx)
        self.assertNotIn(ui.ELSEWHERE_NOTE, layout.text(), "an unsaved file")
        with mock.patch.object(paths, "blend_path", return_value=blend):
            self.assertFalse(chats.open_elsewhere(), "checked at most every few seconds")
            self.assertTrue(chats.open_elsewhere(now=time.monotonic() + chats.ELSEWHERE_EVERY))
            layout = RecordingLayout()
            ui.draw_main(layout, ctx)
            self.assertIn(ui.ELSEWHERE_NOTE, layout.text())
            (line,) = [c for c in layout.of("label") if ui.ELSEWHERE_NOTE.startswith(c["text"]) and c["text"]][:1]
            self.assertFalse(layout.is_active(line), "a quiet line")
            (other / caches.LOCK_NAME).unlink()
            self.assertFalse(chats.open_elsewhere(now=time.monotonic() + 2 * chats.ELSEWHERE_EVERY),
                             "only while the other claim is live")


class SaveTest(ChatCase):
    def test_the_payload_is_in_the_data_only_while_saving(self):
        a, (a1, a2), b, b1 = self.two_chats()
        chats.before_save(self.scene)
        holder = bpy.data.texts[chats.HOLDER]
        self.assertTrue(holder.use_fake_user)
        index = json.loads(holder[chats.INDEX_PROP])
        self.assertEqual((index["current"], set(index["chats"])), (b, {a, b}))
        self.assertEqual({k: len(bytes(v)) for k, v in holder[chats.PAYLOAD_PROP].items()},
                         {a: index["chats"][a]["size"], b: index["chats"][b]["size"]})
        self.assertEqual(self.props.chat, b)
        chats.after_save()
        self.assertNotIn(chats.INDEX_PROP, holder)
        self.assertNotIn(chats.PAYLOAD_PROP, holder)
        bpy.data.texts.remove(holder)

    def test_a_failed_save_or_load_puts_things_back(self):
        from whittle import addon
        from whittle import caches

        self.two_chats()
        self.assertIn((bpy.app.handlers.save_post_fail, addon._save_failed), addon.HANDLERS)
        self.assertIn((bpy.app.handlers.load_post_fail, addon._load_failed), addon.HANDLERS)
        chats.before_save(self.scene)
        holder = bpy.data.texts[chats.HOLDER]
        addon._save_failed()
        self.assertNotIn(chats.INDEX_PROP, holder)
        self.assertNotIn(chats.PAYLOAD_PROP, holder)
        self.assertIsNone(chats._saving)
        chats.release()
        self.assertFalse((chats.root() / caches.LOCK_NAME).is_file())
        addon._load_failed()
        self.assertTrue((chats.root() / caches.LOCK_NAME).is_file(), "the open file holds its cache again")
        bpy.data.texts.remove(holder)

    def test_chats_can_stay_out_of_the_file(self):
        from types import SimpleNamespace

        from whittle.addon import prefs

        self.two_chats()
        off = SimpleNamespace(**{**prefs.DEFAULTS, "store_chats": False})
        with mock.patch.object(prefs, "get", return_value=off):
            chats.before_save(self.scene)
        holder = bpy.data.texts[chats.HOLDER]
        self.assertNotIn(chats.INDEX_PROP, holder)
        self.assertNotIn(chats.PAYLOAD_PROP, holder)
        self.assertEqual(holder[chats.ID_PROP], chats.file_id(), "the file still names its cache")
        chats.after_save()
        bpy.data.texts.remove(holder)

    def test_a_file_without_chats_gets_no_holder(self):
        chats.before_save(self.scene)
        self.assertNotIn(chats.HOLDER, bpy.data.texts)


class FileTest(ChatCase):
    """A real save, a missing cache, a reopen and a delete in a fresh
    Blender: tests/blender/chats_file.py does the steps."""

    def test_save_delete_the_cache_reopen_and_shrink(self):
        blend = self.user_dir / "saved" / "scene.blend"
        blend.parent.mkdir()
        env = {**os.environ, "WHITTLE_USER_DIR": str(self.user_dir), "WHITTLE_AGENT_PYTHON": str(agent_python())}
        out = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python",
                              str(REPO / "tests" / "blender" / "chats_file.py"), "--", str(blend),
                              str(FAKE_SCRIPTS / "history.json")],
                             capture_output=True, text=True, timeout=240, env=env)
        line = next((l for l in out.stdout.splitlines() if l.startswith("RESULT ")), None)
        self.assertIsNotNone(line, out.stdout[-3000:] + out.stderr[-3000:])
        r = json.loads(line[len("RESULT "):])
        self.assertEqual(r["errors"], [])
        a, b = r["a"], r["b"]
        self.assertEqual(r["in_memory_after_save"], [], "the chats leave the data once saved")
        self.assertEqual(set(r["in_file"]), {a, b}, "the saved file holds both chats")
        self.assertFalse(r["cache_after_delete"])
        self.assertTrue(r["cache_in_user_dir"])
        self.assertEqual(r["beside"], ["scene.blend", "scene.blend1"], "nothing beside the file")

        reopened = r["reopened"]
        self.assertEqual(reopened["listed"], [b, a])
        self.assertEqual(reopened["current"], b)
        self.assertEqual(reopened["titles"], {a: "Make the crate bigger", b: "Recolour it"})
        self.assertEqual(reopened["nodes"], {a: ["n0000", "n0001", "n0002"], b: ["n0000", "n0001"]})
        self.assertTrue(reopened["thumbs"], "thumbnails came back")
        self.assertEqual(reopened["restored"], {"lid": False, "scale": 1.2},
                         "an old node of a chat restores from what the file carried")

        sizes = r["sizes"]
        self.assertGreater(sizes["packed_a"], 50_000)
        self.assertLessEqual(sizes["after_delete"], sizes["before_delete"] - 0.99 * sizes["packed_a"],
                             "deleting a chat shrinks the next save by its packed size")
        self.assertEqual(r["after_delete_listed"], [b])
