# SPDX-License-Identifier: GPL-3.0-or-later
"""The docs' screenshot tool's pieces that need no Blender: reading and
validating specs, grouping shots into Blenders, and the slots that limit how
many Blenders run at once."""

import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.docshots import run, slots, spec as specs

REPO = Path(__file__).resolve().parents[2]


def setup_a(stage):
    yield 0.1


def setup_b(stage):
    yield 0.1


def errors_of(*shots, slug="guides-history", source="") -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{slug}.py"
        path.write_text(source)
        return specs.validate(specs.Spec(slug, path, list(shots)), scenarios={"chat_menu": "", "hero": ""})


def shot(name="one", description="A shot.", capture=None, **kw) -> specs.Shot:
    if "scenario" not in kw:
        kw.setdefault("setup", setup_a)
    return specs.Shot(name, description, capture if capture is not None else specs.sidebar(), **kw)


class SpecValidationTest(unittest.TestCase):
    def assert_says(self, errors, text):
        self.assertTrue(any(text in e for e in errors), f"{text!r} not in {errors}")

    def test_a_good_spec_has_no_errors(self):
        self.assertEqual(errors_of(
            shot("menu", capture=specs.popup(panel="WHITTLE_PT_history")),
            shot("area", capture=specs.region("OUTLINER")),
            shot("box", capture=specs.region(box=(0, 0, 100, 100))),
            shot("wide", capture=specs.window(crop=(0, 0, 10, 10))),
            specs.Shot("reused", "The chat menu.", scenario="chat_menu"),
            specs.Shot("prefs", "The preferences.", specs.preferences("KEYMAP", search="Whittle"))), [])

    def test_shots_and_their_names(self):
        self.assert_says(errors_of(), "SHOTS is missing")
        self.assert_says(errors_of("not a shot"), "not a Shot")
        self.assert_says(errors_of(shot("Bad_Name")), "a name is")
        self.assert_says(errors_of(shot("same"), shot("same")), "two shots have this name")

    def test_a_shot_describes_itself_in_one_line(self):
        self.assert_says(errors_of(shot(description=" ")), "one line")
        self.assert_says(errors_of(shot(description="two\nlines")), "one line")

    def test_a_shot_says_how_to_reach_its_state(self):
        self.assert_says(errors_of(specs.Shot("x", "X.", specs.sidebar())), "a scenario or a setup")
        self.assert_says(errors_of(shot(scenario="chat_menu", setup=setup_a)), "not both")
        self.assert_says(errors_of(shot(scenario="no_such")), "no scenario 'no_such'")
        self.assert_says(errors_of(specs.Shot("x", "X.", setup=setup_a)), "says what to capture")
        self.assert_says(errors_of(shot(setup=lambda: None)), "one argument")
        self.assert_says(errors_of(shot(setup="setup_a")), "not a function")

    def test_captures(self):
        self.assert_says(errors_of(shot(capture="sidebar")), "is not sidebar()")
        self.assert_says(errors_of(shot(capture=specs.Capture("nothing"))), "capture kind")
        self.assert_says(errors_of(shot(capture=specs.sidebar(crop=(0, 0, 10)))), "4 whole numbers")
        self.assert_says(errors_of(shot(capture=specs.region())), "an area or a box")
        self.assert_says(errors_of(shot(capture=specs.region("OUTLINER", box=(0, 0, 1, 1)))), "an area or a box")
        self.assert_says(errors_of(shot(capture=specs.preferences("NOPE"))), "section 'NOPE'")
        self.assert_says(errors_of(shot(capture=specs.preferences(full=True, menu="M"))), "full or a menu")

    def test_shots_of_one_setup_share_the_sidebars_width(self):
        self.assert_says(errors_of(shot("a", wide=1.5), shot("b", wide=1.6)), "one sidebar width")
        self.assertEqual(errors_of(shot("a", wide=1.5), shot("b")), [])
        self.assert_says(errors_of(shot("a", wide=0.5)), "wide is a factor")

    def test_a_page_is_named_by_its_slug(self):
        self.assertEqual(specs.page_slug("guides/api-key"), "guides-api-key")
        self.assert_says(errors_of(shot(), slug="Bad Name"), "page's slug")
        self.assertEqual(errors_of(shot(), slug="_example"), [])

    def test_literal_names_in_the_source_are_checked(self):
        self.assert_says(errors_of(shot(), source='yield Snap("nope")'), "Snap('nope')")
        self.assertEqual(errors_of(shot("one"), source='yield Snap("one")'), [])
        self.assert_says(errors_of(shot(), source='stage.fake("nope.json")'), "no fake script 'nope.json'")
        self.assert_says(errors_of(shot(), source='turns("nope.json", "Hi.")'), "no fake script 'nope.json'")
        self.assertEqual(errors_of(shot(), source='stage.fake("stream.json")'), [])

    def test_a_pages_fake_scripts_are_read(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(specs, "FAKE_DIR", Path(tmp)):
            folder = Path(tmp) / "guides-history"
            folder.mkdir()
            (folder / "good.json").write_text('{"turns": []}')
            self.assertEqual(errors_of(shot()), [])
            (folder / "list.json").write_text("[]")
            (folder / "torn.json").write_text("{")
            errors = errors_of(shot())
        self.assert_says(errors, "list.json: a fake script")
        self.assert_says(errors, "torn.json: not JSON")

    def test_a_page_s_own_script_comes_before_a_fixture(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(specs, "FAKE_DIR", Path(tmp)):
            spec = specs.Spec("page", Path(tmp) / "page.py", [])
            self.assertEqual(spec.fake("stream.json"), specs.FIXTURES / "stream.json")
            (Path(tmp) / "page").mkdir()
            (Path(tmp) / "page" / "stream.json").write_text("{}")
            self.assertEqual(spec.fake("stream.json"), Path(tmp) / "page" / "stream.json")

    def test_every_spec_in_the_repository_is_valid(self):
        paths = specs.spec_paths(examples=True)
        self.assertTrue(any(p.stem == "_example" for p in paths))
        for path in paths:
            self.assertEqual(specs.validate(specs.load(path)), [], path.name)

    def test_all_leaves_out_examples(self):
        self.assertFalse([p for p in specs.spec_paths() if p.stem.startswith("_")])

    def test_a_spec_that_cannot_be_imported_is_a_problem_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.py"
            path.write_text("import bpy\n")
            self.assert_says(run.problems(path), "cannot be imported")


class GroupsTest(unittest.TestCase):
    def test_a_setup_is_one_blender_in_order_of_appearance(self):
        a, b, c = shot("a"), shot("b", setup=setup_b), shot("c")
        found = specs.groups([a, b, c])
        self.assertEqual([[s.name for s in g.shots] for g in found], [["a", "c"], ["b"]])
        self.assertEqual([g.index for g in found], [0, 1])
        self.assertEqual(found[0].label, "setup_a")

    def test_a_scenario_is_one_blender_and_preferences_share_one(self):
        shots = [specs.Shot("a", "A.", scenario="chat_menu"), specs.Shot("b", "B.", specs.viewport(), scenario="chat_menu"),
                 specs.Shot("c", "C.", specs.preferences()), specs.Shot("d", "D.", specs.preferences("KEYMAP"))]
        self.assertEqual([len(g.shots) for g in specs.groups(shots)], [2, 2])

    def test_the_window_follows_what_is_captured(self):
        def window(*shots):
            return specs.groups(list(shots))[0].window

        self.assertEqual(window(shot()), specs.TALL)
        self.assertEqual(window(shot(capture=specs.popup(panel="P"))), specs.TALL)
        self.assertEqual(window(shot(capture=specs.preferences())), specs.TALL)
        for capture in (specs.viewport(), specs.window(), specs.region("OUTLINER")):
            self.assertEqual(window(shot(), shot("b", capture=capture)), specs.WIDE)
        self.assertEqual(window(specs.Shot("x", "X.", scenario="hero")), (1600, 1000))

    def test_both_windows_fit_the_hidden_session(self):
        for width, height in (specs.TALL, specs.WIDE):
            self.assertLessEqual(width, specs.OUTPUT[0])
            self.assertLessEqual(height, specs.OUTPUT[1])

    def test_a_group_takes_its_sidebar_width_from_a_shot_or_the_scenario(self):
        self.assertEqual(specs.groups([shot(), shot("b", wide=1.6)])[0].wide, 1.6)
        self.assertEqual(specs.groups([shot()])[0].wide, 1.0)
        self.assertEqual(specs.groups([specs.Shot("x", "X.", scenario="hero")])[0].wide, 1.5)

    def test_every_blender_has_a_deadline_it_cannot_raise_for_ever(self):
        self.assertEqual(specs.groups([shot()])[0].deadline, specs.DEFAULT_DEADLINE)
        self.assertEqual(specs.groups([shot(), shot("b")])[0].deadline, specs.DEFAULT_DEADLINE + specs.PER_SHOT)
        self.assertEqual(specs.groups([shot(deadline=60)])[0].deadline, specs.DEFAULT_DEADLINE + 60)
        self.assertEqual(specs.groups([shot(deadline=10000)])[0].deadline, specs.MAX_DEADLINE)

    def test_turns_makes_a_setup_for_one_scene(self):
        calls = []

        class Stage:
            def crate(self, pick):
                calls.append(("crate", pick))

            def fake(self, name):
                return f"fake/{name}"

            def turns(self, prompts, script):
                calls.append((tuple(prompts), script))
                yield 0.1

        list(specs.turns("lid.json", "One.", "Two.")(Stage()))
        self.assertEqual(calls, [("crate", True), (("One.", "Two."), "fake/lid.json")])

    def test_clamp_stops_a_box_at_the_images_edge(self):
        self.assertEqual(specs.clamp((0, 0, 320, 240), 280, 500), (0, 0, 280, 240))
        self.assertEqual(specs.clamp((10, 20, 30, 40), 280, 500), (10, 20, 30, 40))
        with self.assertRaises(ValueError):
            specs.clamp((300, 0, 10, 10), 280, 500)


class SlotsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "slots"

    def test_the_default_follows_the_cores_up_to_four(self):
        self.assertEqual([slots.default_size(n) for n in (1, 3, 4, 8, 12, 16, 32, 128)], [1, 1, 1, 2, 3, 4, 4, 4])

    def test_the_variable_overrides_the_default(self):
        self.assertEqual(slots.size({slots.SIZE_VARIABLE: "7"}), 7)
        self.assertEqual(slots.size({}), slots.default_size())
        for bad in ("0", "-1", "many"):
            with self.assertRaises(ValueError):
                slots.size({slots.SIZE_VARIABLE: bad})

    def test_each_holder_gets_a_slot_of_its_own(self):
        with slots.slot(self.folder, 2, wait=1) as first, slots.slot(self.folder, 2, wait=1) as second:
            self.assertEqual({first, second}, {0, 1})

    def test_a_waiter_gives_up_at_its_deadline(self):
        started = time.monotonic()
        with slots.slot(self.folder, 1, wait=1):
            with self.assertRaises(slots.SlotTimeout):
                with slots.slot(self.folder, 1, wait=0.3):
                    self.fail("got a slot that was held")
        self.assertLess(time.monotonic() - started, 2.0)

    def test_a_waiter_blocks_until_a_slot_comes_free(self):
        got = threading.Event()
        told = []

        def waiter():
            with slots.slot(self.folder, 1, wait=5, waiting=told.append):
                got.set()

        with slots.slot(self.folder, 1, wait=1):
            thread = threading.Thread(target=waiter)
            thread.start()
            self.assertFalse(got.wait(0.4))
        self.assertTrue(got.wait(5))
        thread.join(5)
        self.assertTrue(told, "the waiter never said it was waiting")

    def test_a_stopping_run_stops_waiting(self):
        with slots.slot(self.folder, 1, wait=1):
            with self.assertRaises(slots.SlotTimeout):
                with slots.slot(self.folder, 1, wait=30, stopped=lambda: True):
                    self.fail("got a slot that was held")

    def test_the_limit_holds_under_contention(self):
        lock = threading.Lock()
        running = [0]
        peak = [0]

        def worker():
            with slots.slot(self.folder, 3, wait=20):
                with lock:
                    running[0] += 1
                    peak[0] = max(peak[0], running[0])
                time.sleep(0.05)
                with lock:
                    running[0] -= 1

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(peak[0], 3)

    def test_a_slot_is_shared_between_processes_and_dies_with_its_holder(self):
        code = ("import sys, time\nfrom pathlib import Path\nfrom tests.docshots import slots\n"
                "with slots.slot(Path(sys.argv[1]), 1, wait=5):\n    print('held', flush=True)\n    time.sleep(30)\n")
        holder = subprocess.Popen([sys.executable, "-c", code, str(self.folder)], stdout=subprocess.PIPE, text=True,
                                  cwd=REPO)
        self.addCleanup(holder.wait, 10)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        with self.assertRaises(slots.SlotTimeout):
            with slots.slot(self.folder, 1, wait=0.3):
                self.fail("got a slot another process holds")
        holder.kill()
        holder.wait(10)
        with slots.slot(self.folder, 1, wait=5):
            pass

    def test_exclusive_has_a_deadline_too(self):
        path = self.folder / "profile.lock"
        with slots.exclusive(path, wait=1):
            with self.assertRaises(slots.SlotTimeout):
                with slots.exclusive(path, wait=0.2):
                    self.fail("got a lock that was held")
        with slots.exclusive(path, wait=1):
            pass

    def test_a_held_slot_is_not_inherited_by_children(self):
        fd = slots.try_lock(self.folder.parent / "slot-0.lock")
        self.addCleanup(os.close, fd)
        self.assertFalse(os.get_inheritable(fd))


class DeliverTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_a_new_image_replaces_the_old_and_leaves_no_temporary(self):
        source, target = self.root / "shot.png", self.root / "images" / "page" / "shot.png"
        source.write_bytes(b"one")
        self.assertEqual(run.deliver(source, target), "updated")
        self.assertEqual(target.read_bytes(), b"one")
        self.assertEqual(run.deliver(source, target), "unchanged")
        source.write_bytes(b"two")
        self.assertEqual(run.deliver(source, target), "updated")
        self.assertEqual([p.name for p in target.parent.iterdir()], ["shot.png"])

    def test_an_example_stays_out_of_the_site(self):
        self.assertTrue(run.target(specs.Spec("_example", Path("x"), []), "a").is_relative_to(run.EXAMPLES))
        self.assertEqual(run.target(specs.Spec("guides-undo", Path("x"), []), "a"),
                         run.IMAGES / "guides-undo" / "a.png")


def wl_global(name: bytes) -> bytes:
    """wl_registry.global on object 2, as a compositor sends it."""
    text = name + b"\0"
    body = struct.pack("=II", 1, len(text)) + text + b"\0" * (-len(text) % 4) + struct.pack("=I", 1)
    return struct.pack("=II", 2, (8 + len(body)) << 16) + body


SYNC_DONE = struct.pack("=III", 3, 12 << 16, 0)


class HasShellTest(unittest.TestCase):
    """KWin listens before it offers windows; has_shell tells the two apart."""

    def answers(self, reply: bytes, wait: float = 5.0) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wayland-test"
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path))
                server.listen(1)

                def answer():
                    client, _address = server.accept()
                    with client:
                        client.recv(24)
                        # In pieces, as a socket may deliver it.
                        client.sendall(reply[:5])
                        time.sleep(0.02)
                        client.sendall(reply[5:])
                        client.recv(1)

                thread = threading.Thread(target=answer, daemon=True)
                thread.start()
                found = run.has_shell(path, wait)
                thread.join(5)
                return found

    def test_a_compositor_offering_windows(self):
        self.assertTrue(self.answers(wl_global(b"wl_compositor") + wl_global(b"xdg_wm_base") + SYNC_DONE))

    def test_a_compositor_still_starting(self):
        self.assertFalse(self.answers(wl_global(b"wl_compositor") + SYNC_DONE))

    def test_a_longer_name_is_not_the_shell(self):
        self.assertFalse(self.answers(wl_global(b"zxdg_wm_base_v6") + SYNC_DONE))

    def test_a_silent_compositor(self):
        self.assertFalse(self.answers(b"", wait=0.1))

    def test_nothing_listening(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(run.has_shell(Path(tmp) / "wayland-none", 0.1))


class EnvironmentTest(unittest.TestCase):
    def test_a_blender_keeps_nothing_of_the_users(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                "ANTHROPIC_API_KEY": "sk-ant-not-a-real-key", "WHITTLE_LIVE": "1", "DISPLAY": ":0",
                "WAYLAND_DISPLAY": "wayland-1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "0"}):
            root, work = Path(tmp) / "blender-user", Path(tmp) / "work"
            env = run.blender_env(root, work, "tag", "wayland-whittle-docs-x", Path(tmp) / "cache-1")
        for name in ("ANTHROPIC_API_KEY", "WHITTLE_LIVE", "DISPLAY", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
            self.assertNotIn(name, env)
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-whittle-docs-x")
        self.assertEqual(env[run.TAG], "tag")
        for name in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_EXTENSIONS",
                     "BLENDER_USER_DATAFILES", "BLENDER_USER_RESOURCES"):
            self.assertTrue(env[name].startswith(str(root)), name)
        self.assertTrue(env["WHITTLE_USER_DIR"].startswith(str(work)))
        self.assertTrue(env["TMPDIR"].startswith(str(work)))
        self.assertEqual(env["XDG_CACHE_HOME"], str(Path(tmp) / "cache-1"))

    def test_without_a_session_there_is_no_display_at_all(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}):
            env = run.blender_env(Path(tmp) / "b", Path(tmp) / "w", "tag")
        self.assertNotIn("WAYLAND_DISPLAY", env)


if __name__ == "__main__":
    unittest.main()
