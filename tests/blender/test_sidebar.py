# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import bpy

from tests.blender.helpers import CRATE_BUNDLE
from tests.blender.sketch_helpers import add_stroke, look_at_view
from tests.blender.ui_helpers import RecordingLayout
from tests.fixtures.crate.scene import build_scene
from whittle import formats, markdown
from whittle.addon import conversation, editors, operators, previews, sketch, stream, targets, transcript, ui
from whittle.addon import views
from whittle.addon.process import AgentState
from whittle.protocol import Event

PNG = str(CRATE_BUNDLE / "views" / "1" / "overlay.png")


# The fake controllers' session folder: empty, and gone when the run ends.
_EMPTY_SESSION = tempfile.TemporaryDirectory(prefix="whittle-sidebar-")


def fake_controller(state=AgentState.READY, *, running=False, phase="running", question=None,
                    reason=None, interrupting=False, turn_number=None, busy=None, active_turn=None,
                    key_problem=None, alive=True, last_folded=None):
    """Enough of a TurnController for the panel to draw."""
    process = SimpleNamespace(state=state, reason=reason, alive=alive, log_tail=lambda n: ["log line"])
    if running and active_turn is None:
        active_turn = ("n0001", "Add a lid and carve a handle slot on each side.")
    return SimpleNamespace(
        process=process, running=running, busy=running if busy is None else busy,
        turn_id=active_turn[0] if running and active_turn else None, model="claude-test",
        status={"phase": phase if running else "idle", "detail": None}, question=question,
        interrupting=interrupting, session=formats.SessionDir(_EMPTY_SESSION.name),
        stream=stream.Stream(), bundle=None, _turn_number=lambda: turn_number, active_turn=active_turn,
        last_folded=last_folded, key_problem=key_problem, can_amend=running and not interrupting,
        commands=SimpleNamespace(targets=lambda: []))


class AddonTestCase(unittest.TestCase):
    def setUp(self):
        self.crate = build_scene()
        old = sketch.find_sketch_object()
        if old is not None:
            bpy.data.objects.remove(old)
        from whittle import addon

        addon.register()
        self.addCleanup(addon.unregister)
        self.scene = bpy.context.scene
        self.props = self.scene.whittle
        self.props.target_auto = False
        self.props.targets.clear()
        self.props.target_collection = None
        self.props.prompt = ""
        self.props.amend_text = ""
        self.props.ask_answer = ""
        self.props.refs.clear()
        conversation.clear_cache()

    def draw(self, ctl=None, hist=None, comparing=None, width=240) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_main(layout, ui.Ctx(scene=self.scene, hist=hist, ctl=ctl, comparing=comparing, width=width))
        return layout

    def no_red(self, layout, what=""):
        red = [c.get("text") or c.get("idname") for c in layout.calls
               if c["kind"] in ("label", "operator") and layout.alerted(c)]
        self.assertEqual(red, [], what)


class DrawTest(AddonTestCase):
    def test_empty_panel(self):
        """Nothing picked, no agent, no history: the start row, the Sketch
        button, an empty prompt and a disabled Send; no placeholders, no
        stroke row, no stroke types and nothing red."""
        layout = self.draw()
        labels = layout.labels()
        self.assertIn("No targets: Claude adds new objects", layout.text(), "Auto is off in these tests")
        self.assertIn("Start from", labels, "the start row says what it is for")
        self.assertFalse([t for t in labels if "stroke" in t.lower()], "no stroke row before a stroke")
        self.assertEqual(layout.operators("whittle.stroke_type"), [], "stroke types only while sketching")
        self.assertEqual(layout.operators("whittle.capture_view"), [])
        self.assertEqual([c["text"] for c in layout.operators("whittle.sketch")], ["Sketch"])
        self.assertFalse([t for t in labels if "No activity" in t or "No history" in t])
        self.assertEqual([c["idname"] for c in layout.operators() if c["idname"].startswith("whittle.start")],
                         ["whittle.start_existing", "whittle.start_blank"])
        self.assertEqual(layout.menus(), ["WHITTLE_MT_start_primitive", "WHITTLE_MT_models"])
        (send,) = layout.operators("whittle.submit")
        self.assertEqual(send["text"], "Send")
        self.assertFalse(layout.is_enabled(send), "nothing to send yet")
        prompt = next(c for c in layout.of("prop") if c["prop"] == "prompt")
        self.assertEqual(prompt["placeholder"], "Ask Claude…")
        self.assertTrue(prompt.get("textbox"), "the prompt is a multi-line box")
        self.assertEqual(prompt["initial_visible_lines"], ui.COMPOSER_LINES)
        self.assertEqual([c["panel"] for c in layout.of("popover")][-1:], ["WHITTLE_PT_history"])
        self.no_red(layout)

    def test_send_needs_something_to_send(self):
        self.props.prompt = "Add a lid."
        layout = self.draw()
        self.assertTrue(layout.is_enabled(layout.operators("whittle.submit")[0]))
        comparing = SimpleNamespace(showing="n0001", other="n0001")
        layout = self.draw(comparing=comparing)
        self.assertFalse(layout.is_enabled(layout.operators("whittle.submit")[0]))
        self.no_red(layout, "a comparison is not an error: Send's tooltip says why it is off")
        self.props.prompt = ""
        self.props.refs.add().path = PNG
        self.assertTrue(layout.is_enabled(self.draw().operators("whittle.submit")[0]), "a reference alone")

    def test_composer_while_running(self):
        ctl = fake_controller(AgentState.BUSY, running=True)
        layout = self.draw(ctl)
        self.assertEqual(layout.operators("whittle.submit"), [])
        field = next(c for c in layout.of("prop") if c["prop"] == "amend_text")
        self.assertEqual(field["placeholder"], "Ask Claude…", "the same placeholder as between turns")
        self.assertTrue(field.get("textbox"), "amending gets the same multi-line box")
        self.assertEqual(layout.operators("whittle.amend"), [], "Amend shows once there is something to send")
        self.assertIn("WHITTLE_MT_stop", layout.menus())
        self.props.amend_text = "taller"
        self.assertTrue(layout.is_enabled(self.draw(ctl).operators("whittle.amend")[0]))
        self.props.amend_text = "taller, and give it a lid that overhangs the sides by a centimetre or so"
        layout = self.draw(ctl)
        self.assertNotIn("overhangs", layout.text(), "a draft shows once, in its field")
        menu = SimpleNamespace(layout=RecordingLayout())
        ui.WHITTLE_MT_stop.draw(menu, bpy.context)
        stops = menu.layout.operators("whittle.interrupt")
        self.assertEqual([(c["props"].mode, c["text"]) for c in stops],
                         [("KEEP", "Stop and Keep Changes"), ("RESTORE", "Stop and Undo This Turn")])
        self.assertEqual([c["panel"] for c in layout.of("popover")][-1:], ["WHITTLE_PT_history"])

    def test_question_in_the_conversation_and_answer_in_the_composer(self):
        question = {"question": "Should the lid overhang the crate by 1 cm, or sit flush with it?",
                    "choices": ["Overhang", "Flush"]}
        ctl = fake_controller(AgentState.BUSY, running=True, phase="waiting_user", question=question)
        layout = self.draw(ctl, width=200)
        choices = [c for c in layout.operators("whittle.answer") if hasattr(c["props"], "text")]
        self.assertEqual([c["props"].text for c in choices], ["Overhang", "Flush"])
        self.assertIn("ask_answer", layout.props())
        self.assertEqual(len(layout.operators("whittle.answer")), 2, "Answer shows once an answer is typed")
        self.props.ask_answer = "Overhang by 5 mm"
        layout = self.draw(ctl, width=200)
        answer = next(c for c in layout.operators("whittle.answer") if not hasattr(c["props"], "text"))
        self.assertEqual(answer["text"], "Answer")
        self.assertIn("Should the lid overhang", layout.text())
        lines = [c for c in layout.of("label") if c["icon"] == "QUESTION"]
        self.assertEqual(len(lines), 1)
        self.no_red(layout, "a question is not an error")

    def test_running_turn_shows_progress(self):
        ctl = fake_controller(AgentState.BUSY, running=True)
        s = ctl.stream
        s.note("Turn n0001: Add a lid", kind="submit", turn_id="n0001")
        s.append(Event.TEXT, {"turn_id": "n0001", "text": "Plan: a lid, then the slots."})
        s.append(Event.TOOL_USE, {"turn_id": "n0001", "tool_use_id": "a", "tool": "exec",
                                  "input": {"label": "add lid", "code": "x = 1"}})
        s.append(Event.TOOL_RESULT, {"turn_id": "n0001", "tool_use_id": "a", "is_error": False,
                                     "summary": "ok", "images": [PNG]})
        self.assertIn("Working…", self.draw(ctl).labels(), "nothing in flight: Claude is thinking")
        s.append(Event.TOOL_USE, {"turn_id": "n0001", "tool_use_id": "b", "tool": "exec",
                                  "input": {"label": "carve handle slots", "code": "y = 2"}})
        layout = self.draw(ctl)
        group = next(c for c in layout.of("label") if c["text"] == "exec · carve handle slots"
                     and c["icon"] == "SORTTIME")
        self.assertTrue(layout.is_active(group))
        self.assertNotIn("Working…", layout.labels(), "the call in flight already shows the hourglass")
        indicator = RecordingLayout()
        ui.draw_indicator(indicator, ctl)
        self.assertEqual(indicator.of("popover")[0]["icon"], "PREFERENCES", "the turn shows its progress")
        self.assertNotIn("Turn n0001: Add a lid", layout.labels(), "the prompt is the bubble, not a note")
        bubble = [c for c in layout.operators("whittle.turn_menu") if c["props"].node == "n0001"]
        self.assertEqual(len(bubble), 1, "one ⋯ per message")
        self.assertFalse(any(layout.is_enabled(c) for c in bubble), "the running turn has no history yet")
        self.assertEqual(layout.operators("whittle.history_branch"), [], "Edit is in the ⋯ menu")
        self.assertIn(PNG, [c["props"].filepath for c in layout.operators("whittle.open_image")])
        lock = next(c for c in layout.of("label") if c["icon"] == "LOCKED")
        self.assertTrue(lock["text"])
        auto = next(c for c in layout.of("prop") if c["prop"] == "target_auto")
        self.assertFalse(layout.is_active(auto), "Auto steps back while the target is locked")
        s.append(Event.TOOL_USE, {"turn_id": "n0001", "tool_use_id": "c", "tool": "render",
                                  "input": {"mode": "shaded"}})
        layout = self.draw(ctl)
        self.assertIn("Running 2 tools", layout.labels(), "two calls in flight are both counted")

    def test_asked_question_is_not_repeated_by_its_call(self):
        question = {"question": "Should the lid overhang?", "choices": ["Yes", "No"]}
        ctl = fake_controller(AgentState.BUSY, running=True, phase="waiting_user", question=question)
        ctl.stream.append(Event.TOOL_USE, {"turn_id": "n0001", "tool_use_id": "q", "tool": "ask",
                                           "input": {"question": "Should the lid overhang?"}})
        layout = self.draw(ctl)
        self.assertFalse([t for t in layout.labels() if t.startswith("ask")])
        self.assertEqual(len([t for t in layout.labels() if "Should the lid" in t]), 1)

    def test_stopping_note_is_left_out(self):
        ctl = fake_controller(AgentState.BUSY, running=True, interrupting=True)
        stream.local_entry(ctl.stream, "interrupt", {"mode": "keep"}, "n0001")
        layout = self.draw(ctl)
        self.assertFalse([t for t in layout.labels() if t.startswith("Stopping:")])
        self.assertIn("Stopping…", layout.labels())

    def test_reference_chips(self):
        self.props.refs.add().path = PNG
        ref = self.props.refs.add()
        ref.path = PNG
        ref.pinned = True
        layout = self.draw()
        chips = layout.operators("whittle.ref_menu")
        self.assertEqual([(c["text"], c["props"].index) for c in chips], [("overlay.png", 0), ("overlay.png", 1)],
                         "each chip opens its reference's menu")
        # A preview's icon id can still be 0 in background Blender.
        self.assertTrue(all(c.get("icon_value") or c.get("icon") == "IMAGE_DATA" for c in chips))
        self.assertEqual(layout.operators("whittle.ref_remove"), [], "remove is in the chip's menu")
        (pin,) = layout.operators("whittle.ref_pin")
        self.assertEqual((pin["icon"], pin["depress"], pin["props"].index), ("PINNED", True, 1),
                         "a pinned chip carries a pressed pin that unpins it")
        field = next(i for i, c in enumerate(layout.calls) if c["kind"] == "prop" and c["prop"] == "prompt")
        last_chip = max(i for i, c in enumerate(layout.calls) if c in chips)
        self.assertLess(last_chip, field, "the chips sit right above the prompt")
        menu = RecordingLayout()
        ui.draw_ref_menu(menu, 1)
        (pin,) = menu.operators("whittle.ref_pin")
        self.assertEqual((pin["text"], pin["props"].index), ("Unpin", 1))
        self.assertEqual(menu.operators("whittle.ref_remove")[0]["props"].index, 1)
        self.assertNotIn("path", layout.props(), "no path field")
        self.assertEqual(len(layout.operators("whittle.ref_add")), 1)

    def test_attention_box_only_when_the_user_must_act(self):
        layout = self.draw(fake_controller())
        self.assertFalse(any(c["kind"] == "box" and c["child"].alert for c in layout.calls))
        crashed = fake_controller(AgentState.CRASHED, reason="the agent exited with code 3", alive=False)
        layout = self.draw(crashed)
        self.assertIn("Claude stopped unexpectedly", layout.labels())
        self.assertNotIn("code 3", layout.text(), "the details are in the agent popover")
        (restart,) = layout.operators("whittle.agent_start")
        self.assertEqual(restart["text"], "Restart")
        self.assertFalse(layout.alerted(restart), "the button is not red")
        popover = RecordingLayout()
        ui.draw_agent(popover, crashed)
        self.assertIn("code 3", popover.text())
        layout = self.draw(fake_controller(key_problem="The API key was refused"))
        self.assertIn("The API key was refused", layout.labels())
        self.assertEqual(len(layout.operators("preferences.addon_show")), 1)
        (link,) = layout.operators("wm.url_open")
        self.assertEqual(link["props"].url, "https://platform.claude.com/settings/keys")

    def test_no_key_asks_for_one(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            layout = self.draw(fake_controller(AgentState.NEEDS_KEY, reason="Add a key", alive=False))
            self.assertIn("Add an API key to start", layout.labels())
            self.assertEqual(len(layout.operators("preferences.addon_show")), 1)
            self.assertEqual(len(layout.operators("wm.url_open")), 1)
            self.assertEqual(layout.operators("whittle.agent_start"), [], "nothing to restart")
            self.assertFalse(any(layout.alerted(c) for c in layout.calls if c["kind"] in ("label", "operator")),
                             "a missing key is not a failure")
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
            layout = self.draw(fake_controller(AgentState.NEEDS_KEY, reason="Add a key", alive=False))
            self.assertNotIn("Add an API key to start", layout.labels(), "a key was found since")

    def test_header_indicator(self):
        for state, icon in ((AgentState.STOPPED, "PREFERENCES"), (AgentState.READY, "PREFERENCES"),
                            (AgentState.STARTING, "SORTTIME"), (AgentState.BUSY, "SORTTIME"),
                            (AgentState.CRASHED, "PREFERENCES"), (AgentState.NEEDS_SETUP, "PREFERENCES")):
            with self.subTest(state=state):
                layout = RecordingLayout()
                # Not in a turn: starting the agent by hand still shows.
                ui.draw_indicator(layout, fake_controller(state))
                (popover,) = layout.of("popover")
                self.assertEqual((popover["panel"], popover["icon"], popover["text"]),
                                 ("WHITTLE_PT_agent", icon, ""))
        layout = RecordingLayout()
        ui.draw_indicator(layout, None)
        self.assertEqual(layout.of("popover")[0]["icon"], "PREFERENCES")

    def test_agent_popover(self):
        layout = RecordingLayout()
        ui.draw_agent(layout, fake_controller())
        self.assertIn("Agent: ready", layout.labels())
        self.assertIn("Model: claude-test", layout.labels())
        self.assertEqual(len(layout.operators("whittle.agent_stop")), 1)
        self.assertTrue(any(t.startswith("Chats: ") for t in layout.labels()))
        layout = RecordingLayout()
        ui.draw_agent(layout, None)
        self.assertIn("Agent: stopped", layout.labels())
        self.assertEqual(len(layout.operators("whittle.agent_start")), 1)

    def test_target_line(self):
        self.props.target_auto = True
        self.props.targets.add().object = self.crate
        layout = self.draw()
        (auto,) = [c for c in layout.of("prop") if c["prop"] == "target_auto"]
        self.assertEqual((auto["text"], auto["toggle"]), ("Auto", True))
        self.assertEqual(layout.of("template_list"), [], "no manual editor while Auto is on")
        self.assertIn("Crate", layout.labels())
        self.props.target_auto = False
        lid = bpy.data.objects.new("Crate_Lid", bpy.data.meshes.new("Crate_Lid"))
        self.scene.collection.objects.link(lid)
        self.addCleanup(bpy.data.objects.remove, lid)
        bpy.ops.object.select_all(action="DESELECT")
        lid.select_set(True)
        layout = self.draw()
        self.assertEqual(layout.of("template_list"), [], "plain rows, not a list widget")
        self.assertEqual([c["props"].index for c in layout.operators("whittle.target_remove")], [0],
                         "one remove button per row")
        (add,) = layout.operators("whittle.target_add")
        self.assertEqual(add["text"], "Add Crate_Lid", "the selection that is not a target yet")
        self.assertEqual([c["panel"] for c in layout.of("popover")], ["WHITTLE_PT_targets", "WHITTLE_PT_history"])
        options = RecordingLayout()
        ui.draw_target_options(options)
        self.assertIn("target_collection", options.props())
        for idname in ("whittle.target_from_selection", "whittle.target_clear"):
            self.assertEqual(len(options.operators(idname)), 1, idname)
        layout = self.draw(fake_controller(AgentState.BUSY, running=True))
        self.assertTrue([c for c in layout.of("label") if c["icon"] == "LOCKED"])

    def test_sketch_strip(self):
        obj = sketch.ensure_sketch_layers(self.scene)
        views.add_view(obj.data, lambda i: look_at_view(i, (0, -2, 0.3), (0, 0, 0.3)))
        add_stroke(obj, "free", [(0, 0, 0), (0.1, 0, 0)], view=1)
        add_stroke(obj, "add", [(0, 0, 0), (0.1, 0, 0)], view=1)
        layout = self.draw()
        self.assertIn("2 strokes · 1 view", layout.labels())
        (current,) = layout.operators("whittle.view_snap")
        self.assertEqual((current["text"], current["props"].id), ("View 1 · 2 strokes", 1),
                         "the row snaps the viewport back to its view")
        self.assertEqual(current["icon"], "VIEW_CAMERA", "the current view is marked by its icon")
        self.assertTrue(layout.is_active(current), "no view is dimmed: dim reads as disabled")
        self.assertIn("current", layout.labels())
        self.assertEqual(layout.operators("whittle.view_remove")[0]["props"].id, 1)
        self.assertIn("whittle_show_view_markers", layout.props(), "the markers can be turned off")
        views.add_view(obj.data, lambda i: look_at_view(i, (2, 0, 0.3), (0, 0, 0.3)))
        views.set_current_view(obj.data, 1)
        rows = {c["props"].id: c["icon"] for c in self.draw().operators("whittle.view_snap")}
        self.assertEqual(rows, {1: "VIEW_CAMERA", 2: "CAMERA_DATA"}, "a view snapped back to is current")
        operators.remove_view(obj, 2)
        self.assertEqual(layout.operators("whittle.stroke_type"), [], "stroke types only while sketching")
        from unittest import mock

        with mock.patch.object(sketch, "current_session", return_value=object()):
            layout = self.draw()
        self.assertIn("Free", layout.labels(), "the active type is named")
        (stop,) = layout.operators("whittle.sketch_stop")
        self.assertEqual((stop["text"], stop["depress"]), ("Sketch", True), "Sketch stays pressed")
        (capture,) = layout.operators("whittle.capture_view")
        self.assertEqual(capture["text"], "Capture View", "set apart from the stroke types, and named")
        types = layout.operators("whittle.stroke_type")
        self.assertEqual([c["props"].type for c in types], list(formats.STROKE_TYPES))
        self.assertTrue(all(c["text"] == "" for c in types), "the type buttons are icons")
        self.assertEqual([c["props"].type for c in types if c.get("depress")], ["free"])
        self.assertEqual(len(layout.operators("whittle.capture_view")), 1)
        self.assertTrue(layout.is_enabled(layout.operators("whittle.clear_sketch")[0]))
        (views_panel,) = [c for c in layout.of("panel") if c["idname"] == "whittle_show_views"]
        self.assertTrue(views_panel["default_closed"], "the view list starts closed")
        self.assertTrue(layout.is_enabled(layout.operators("whittle.submit")[0]), "strokes alone can be sent")
        sketch.stamp_strokes(obj, 1)
        add_stroke(obj, "free", [(0, 0, 0), (0.1, 0, 0)], view=1)
        layout = self.draw(fake_controller(AgentState.BUSY, running=True, turn_number=1))
        self.assertIn("2 sent · 1 new", layout.labels())
        layout = self.draw(fake_controller(AgentState.BUSY, running=True, turn_number=7))
        self.assertIn("0 sent · 1 new", layout.labels())
        sketch.clear_strokes(obj)
        layout = self.draw(fake_controller(AgentState.BUSY, running=True, turn_number=1))
        self.assertFalse([t for t in layout.labels() if "sent" in t], "nothing sent, nothing new: no row")

    def test_clear_and_views_reachable_without_pending_strokes(self):
        """A stopped or failed sketch turn leaves its sent strokes shown, and
        a view can be captured before any stroke: Clear and the view list
        stay in reach either way."""
        obj = sketch.ensure_sketch_layers(self.scene)
        views.add_view(obj.data, lambda i: look_at_view(i, (0, -2, 0.3), (0, 0, 0.3)))
        layout = self.draw()
        self.assertIn("1 view", layout.labels())
        self.assertEqual(len(layout.operators("whittle.clear_sketch")), 1)
        self.assertEqual([c["props"].id for c in layout.operators("whittle.view_remove")], [1])
        add_stroke(obj, "free", [(0, 0, 0), (0.1, 0, 0)], view=1)
        sketch.stamp_strokes(obj, 1)
        layout = self.draw()
        self.assertIn("1 stroke sent · 1 view", layout.labels())
        self.assertEqual(len(layout.operators("whittle.clear_sketch")), 1)
        self.assertEqual(len(layout.operators("whittle.view_remove")), 1)
        add_stroke(obj, "add", [(0, 0, 0), (0.1, 0, 0)], view=1)
        self.assertIn("1 stroke · 1 sent · 1 view", self.draw().labels())

    def test_stroke_type_tooltips_name_the_type(self):
        describe = operators.WHITTLE_OT_stroke_type.description
        self.assertEqual(describe(bpy.context, SimpleNamespace(type="carve")), "Carve: remove material here")
        for stroke_type in formats.STROKE_TYPES:
            self.assertTrue(describe(bpy.context, SimpleNamespace(type=stroke_type))
                            .startswith(stroke_type.capitalize() + ": "))

    def test_development_panel_needs_developer_extras(self):
        view = bpy.context.preferences.view
        before = view.show_developer_ui
        self.addCleanup(setattr, view, "show_developer_ui", before)
        view.show_developer_ui = False
        self.assertFalse(ui.WHITTLE_PT_debug.poll(bpy.context))
        view.show_developer_ui = True
        self.assertTrue(ui.WHITTLE_PT_debug.poll(bpy.context))

    def test_tool_body_lists_code_and_result(self):
        entry = stream.Entry(id=1, kind="tool", turn_id="n1", text="exec · lid", tool="exec",
                             input={"code": "a = 1\nb = 2", "label": "lid"}, status="ok", result="stdout: 3")
        self.assertEqual(stream.tool_detail(entry), ["a = 1", "b = 2", "→ ok:", "  stdout: 3"])
        long = stream.Entry(id=2, kind="tool", turn_id="n1", text="", tool="exec",
                            input={"code": "\n".join(f"x{i}" for i in range(100))}, status="pending")
        detail = stream.tool_detail(long, max_lines=10)
        self.assertEqual(len(detail), 10)
        self.assertTrue(detail[-1].startswith("… 91 more"))


def event(name, **data) -> dict:
    return {"v": 1, "type": "event", "name": name, "data": data}


def local(name, **data) -> dict:
    return {"v": 1, "type": "local", "name": name, "data": data}


class HistoryCase(AddonTestCase):
    """A history on disk: nodes with their transcripts, as finished turns
    leave them."""

    def setUp(self):
        super().setUp()
        from whittle.addon import history

        tmp = tempfile.TemporaryDirectory(prefix="whittle-conversation-")
        self.addCleanup(tmp.cleanup)
        self.hist = history.History(formats.SessionDir(tmp.name))
        self.hist.ensure_root([self.crate], self.scene)

    def turn(self, node, prompt, *, parent=None, records=(), failed=False, folded=False, text=None):
        """A finished node under parent (default the current node) with a
        transcript: some text and one tool call, then its end."""
        if parent is not None:
            self.hist.tree.current = parent
        self.hist.begin(node, prompt)
        records = list(records) or [
            event("text", turn_id=node, text=text or f"Working on: {prompt}"),
            event("tool_use", turn_id=node, tool_use_id=f"{node}a", tool="exec",
                  input={"label": "edit", "code": "x = 1"}),
            event("tool_result", turn_id=node, tool_use_id=f"{node}a", is_error=False, summary="ok"),
            event("text", turn_id=node, text="Done."),
        ]
        records = [local("submit", node=node, prompt=prompt), *records,
                   event("turn_finished", turn_id=node, is_error=failed, interrupted=False, num_turns=3,
                         cost_usd=0.002, subtype="error_during_execution" if failed else "success",
                         errors=["the scene could not be saved"] if failed else [])]
        path = self.hist.session.transcript_path(node)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        data = {"session_id": "S", "message_uuid": f"u{node}", "is_error": failed, "interrupted": False}
        if folded:
            self.hist.fold(node, data)
        else:
            self.hist.finish(node, [self.crate], data, scene=self.scene)
        return node

    def chain(self, count, start=1):
        return [self.turn(formats.node_id(k), f"Step {k}: nudge the crate.") for k in range(start, start + count)]


class ConversationDrawTest(HistoryCase):

    def test_the_current_branch_older_turns_collapsed(self):
        self.chain(3)
        layout = self.draw(fake_controller(), self.hist)
        self.assertFalse([t for t in layout.labels() if t.startswith("Start")], "the start is in the popover")
        collapsed = [c["idname"] for c in layout.of("panel") if c["idname"].startswith("whittle_turn_")]
        self.assertEqual(collapsed, ["whittle_turn_n0001"])
        self.assertTrue(all(c["default_closed"] for c in layout.of("panel")
                            if c["idname"].startswith(("whittle_turn_", "whittle_tools_"))))
        bubbles = [c["props"].node for c in layout.operators("whittle.turn_menu")
                   if not layout.in_panel(c, ("whittle_turn_", "whittle_earlier"))]
        self.assertEqual(bubbles, ["n0002", "n0003"], "the last two turns are expanded, each with ⋯")
        self.assertFalse([c for c in layout.operators("whittle.open_image")
                          if not layout.in_panel(c, ("whittle_turn_", "whittle_tools_"))],
                         "the turn's picture has no button: Open Render is in the ⋯ menu")
        self.assertIn("Working on: Step 3: nudge the crate.", layout.text())
        self.assertIn("Used 1 tool", layout.labels())
        self.assertIn("3 steps · $0.0020", layout.labels())
        self.assertFalse([t for t in layout.labels() if "n000" in t], "no node ids in the conversation")
        self.no_red(layout)

    def test_recovered_tool_error_is_quiet_and_a_failed_turn_is_red(self):
        self.turn("n0001", "Add a lid.", records=[
            event("text", turn_id="n0001", text="Adding a lid."),
            event("tool_use", turn_id="n0001", tool_use_id="a", tool="exec", input={"label": "lid"}),
            event("tool_result", turn_id="n0001", tool_use_id="a", is_error=True, summary="SyntaxError"),
            event("text", turn_id="n0001", text="Fixed it."),
        ])
        self.turn("n0002", "Give it feet.", failed=True)
        layout = self.draw(fake_controller(), self.hist)
        failed_call = next(c for c in layout.of("label") if c["text"] == "exec · lid")
        self.assertEqual(failed_call["icon"], "CANCEL")
        self.assertFalse(layout.alerted(failed_call), "a recovered tool error is not red")
        self.assertNotIn("Failed", layout.labels(), "the reason says it")
        reason = next(c for c in layout.of("label") if c["text"].startswith("the scene could not"))
        self.assertIn("the scene could not be saved", layout.text())
        self.assertTrue(layout.alerted(reason), "the failure is its reason, in red")
        self.assertEqual(reason["icon"], "CANCEL")
        (retry,) = layout.operators("whittle.retry")
        self.assertEqual(retry["props"].node, "n0002")
        self.assertFalse(layout.alerted(retry), "the button is not red")

    def test_branch_switcher(self):
        self.turn("n0001", "Add a lid.")
        self.turn("n0002", "Add metal handles.")
        self.turn("n0003", "Add rope handles.", parent="n0001")
        layout = self.draw(fake_controller(), self.hist)
        self.assertIn("2/2", layout.labels())
        switches = layout.operators("whittle.branch_switch")
        self.assertEqual([(c["icon"], c["props"].node) for c in switches], [("TRIA_LEFT", "n0002")])
        ends = [c for c in layout.of("label") if c["icon"] == "TRIA_RIGHT"]
        self.assertEqual(len(ends), 1, "an arrow leading nowhere is drawn dim")
        self.assertFalse(layout.is_active(ends[0]))
        boxes = {id(c["child"]) for c in layout.calls if c["kind"] == "box"}
        parents = {id(c[key]): c["layout"] for c in layout.calls for key in ("child", "body") if key in c}

        def in_box(record):
            node = record["layout"]
            while node is not None:
                if id(node) in boxes:
                    return True
                node = parents.get(id(node))
            return False

        self.assertTrue(in_box(switches[0]), "the switcher is in the bubble's row, not a row of its own")
        layout = self.draw(fake_controller(AgentState.BUSY, running=True,
                                           active_turn=("n0004", "More.")), self.hist)
        self.assertEqual(layout.operators("whittle.branch_switch"), [], "no switching during a turn")
        self.assertIn("2/2", layout.labels())

    def test_off_the_end_of_a_branch(self):
        self.turn("n0001", "Add a lid.")
        self.turn("n0002", "Add handles.")
        self.hist.tree.current = "n0001"
        layout = self.draw(fake_controller(), self.hist)
        self.assertIn("1 later turn", layout.labels())
        (back,) = [c for c in layout.operators("whittle.branch_switch") if c["text"] == "Return to Latest"]
        self.assertEqual(back["props"].node, "n0002")
        self.assertEqual(layout.operators("whittle.submit")[0]["text"], "Branch",
                         "the default sidebar's Send has no room for Send as Branch")
        self.assertNotIn("Add handles.", layout.labels(), "the conversation ends at the current turn")
        layout = self.draw(fake_controller(), self.hist, width=400)
        self.assertEqual(layout.operators("whittle.submit")[0]["text"], "Send as Branch", "a wide sidebar")

    def test_a_long_session_folds(self):
        self.chain(13)
        layout = self.draw(fake_controller(), self.hist)
        panels = [c["idname"] for c in layout.of("panel")]
        self.assertIn("whittle_earlier", panels)
        self.assertIn("8 earlier turns", layout.labels())
        collapsed = [p for p in panels if p.startswith("whittle_turn_")]
        self.assertEqual(len(collapsed), 11)
        self.assertEqual([c["props"].node for c in layout.operators("whittle.turn_menu")
                          if not layout.in_panel(c, ("whittle_turn_", "whittle_earlier"))],
                         ["n0012", "n0013"], "collapsed turns have no buttons")

    def test_folded_failure_shows_once_with_retry(self):
        self.turn("n0001", "Add a lid.")
        self.turn("n0002", "Add brass hinges.", failed=True, folded=True)
        layout = self.draw(fake_controller(last_folded="n0002"), self.hist)
        self.assertIn("Add brass hinges.", layout.labels())
        self.assertEqual([c["props"].node for c in layout.operators("whittle.retry")], ["n0002"])
        self.assertTrue(operators.can_branch(self.hist, None, "n0002"), "editing a folded turn refills the prompt")
        menu = RecordingLayout()
        ui.draw_turn_menu(menu, self.hist, fake_controller(), "n0002")
        self.assertEqual([c["text"] for c in menu.operators()], ["Edit & Resend", "Open Transcript"])
        from unittest import mock

        from whittle.addon import history

        with mock.patch.object(history, "active", return_value=self.hist):
            self.assertEqual(operators.branch_node(bpy.context, "n0002"), "n0001")
        self.assertEqual(self.props.prompt, "Add brass hinges.")
        layout = self.draw(fake_controller(), self.hist)
        self.assertNotIn("Add brass hinges.", layout.labels(), "gone once it is not the latest thing")

    def test_a_crash_is_reported_once(self):
        """The attention box offers to restart and send the turn again; the
        turn the crash ended is a dim line with no Retry of its own."""
        self.turn("n0001", "Add a lid.", failed=True, folded=True)
        ctl = fake_controller(AgentState.CRASHED, reason="the agent exited with code 3", alive=False,
                              last_folded="n0001")
        layout = self.draw(ctl, self.hist)
        (retry,) = layout.operators("whittle.retry")
        self.assertEqual((retry["text"], retry["props"].node), ("Restart and Retry", "n0001"))
        self.assertIn("Interrupted", layout.labels(), "the box above says why")
        self.assertNotIn("Failed", layout.labels())
        red = [c["text"] for c in layout.of("label") if layout.alerted(c)]
        self.assertEqual(red, ["Claude stopped unexpectedly"])

    def test_start_points_after_a_folded_first_turn(self):
        """The panel stays on the failure; the popover offers the start."""
        self.turn("n0001", "Add a lid.", failed=True, folded=True)
        ctl = fake_controller(last_folded="n0001")
        self.assertEqual(self.draw(ctl, self.hist).menus(), ["WHITTLE_MT_models"])
        layout = RecordingLayout()
        ui.draw_history(layout, ui.Ctx(scene=self.scene, hist=self.hist, ctl=ctl, comparing=None))
        self.assertEqual(layout.menus(), ["WHITTLE_MT_start_primitive"])
        self.assertEqual(len(layout.operators("whittle.start_blank")), 1)

    def test_comparison_bar(self):
        self.turn("n0001", "Add a lid.")
        self.turn("n0002", "Darker wood.")
        from unittest import mock

        from whittle.addon import compare

        comparing = SimpleNamespace(showing="n0001", other="n0001")
        with mock.patch.object(compare, "active", return_value=comparing):
            layout = self.draw(fake_controller(), self.hist, comparing)
        self.assertIn("Showing: Add a lid", layout.labels())
        self.assertFalse([t for t in layout.labels() if "n000" in t], "no node ids")
        self.assertEqual([(c["text"], c["props"].keep) for c in layout.operators("whittle.compare_end")],
                         [("Keep This", True), ("Done", False)])
        self.assertEqual([c["text"] for c in layout.operators("whittle.compare_toggle")], ["Swap"])
        marks = [c for c in layout.of("label") if c["icon"] == "ARROW_LEFTRIGHT" and not c["text"]]
        self.assertEqual(len(marks), 1, "the compared turn's bubble is marked")
        live = SimpleNamespace(showing=compare.LIVE, other="n0001")
        with mock.patch.object(compare, "active", return_value=live):
            layout = self.draw(fake_controller(), self.hist, live)
        self.assertIn("Showing: the current scene", layout.labels())
        self.assertEqual([c["text"] for c in layout.operators("whittle.compare_end")], ["Done"],
                         "keeping the current scene is just Done")
        self.assertFalse(any(layout.is_enabled(c) for c in layout.operators("whittle.history_branch")))

    def test_turn_menu(self):
        self.turn("n0001", "Add a lid.")
        self.turn("n0002", "Darker wood.", records=[
            event("tool_use", turn_id="n0002", tool_use_id="r", tool="render", input={"mode": "shaded"}),
            event("tool_result", turn_id="n0002", tool_use_id="r", is_error=False, summary="ok", images=[PNG]),
        ])
        layout = RecordingLayout()
        ui.draw_turn_menu(layout, self.hist, fake_controller(), "n0001")
        self.assertEqual([c["text"] for c in layout.operators()],
                         ["Edit & Resend", "Go Back to This Turn", "Compare With Current", "Open Transcript"])
        layout = RecordingLayout()
        ui.draw_turn_menu(layout, self.hist, fake_controller(), "n0002")
        texts = [c["text"] for c in layout.operators()]
        self.assertIn("Ghost of Previous Turn", texts)
        self.assertEqual(layout.operators("whittle.open_image")[0]["props"].filepath, PNG)
        compare = next(c for c in layout.operators("whittle.history_compare"))
        self.assertFalse(layout.is_enabled(compare), "the current turn is not compared with itself")
        layout = RecordingLayout()
        ui.draw_turn_menu(layout, self.hist, fake_controller(), "n0000")
        self.assertEqual([c["text"] for c in layout.operators()], ["Go Back to the Start", "Compare With Current"])


class HistoryPopoverTest(HistoryCase):
    """The history popover: n0000 -> n0001 -> (n0002 -> n0003, n0004), where
    n0004 failed before its snapshot was written."""

    def setUp(self):
        super().setUp()
        self.chain(3)
        self.hist.tree.current = "n0001"
        self.hist.begin("n0004", "Another take")
        self.hist.tree.finish("n0004", status="failed")
        self.hist.tree.current = "n0001"
        self.hist.save()

    def popover(self, ctl=None, comparing=None) -> RecordingLayout:
        layout = RecordingLayout()
        ui.draw_history(layout, ui.Ctx(scene=self.scene, hist=self.hist, ctl=ctl or fake_controller(),
                                       comparing=comparing, width=300))
        return layout

    def rows(self, layout):
        """(node, {button: enabled}) per row, in drawing order."""
        out = []
        for c in layout.operators("whittle.history_restore"):
            node = c["props"].node
            buttons = {b["idname"].split(".")[1]: layout.is_enabled(b) for b in layout.operators()
                       if getattr(b["props"], "node", None) == node}
            out.append((node, buttons))
        return out

    def test_rows_and_buttons(self):
        layout = self.popover()
        rows = self.rows(layout)
        self.assertEqual([r[0] for r in rows], ["n0000", "n0001", "n0002", "n0003", "n0004"])
        buttons = dict(rows)
        self.assertEqual(buttons["n0000"], {"history_restore": True, "turn_menu": True})
        self.assertEqual(buttons["n0004"], {"history_restore": False, "turn_menu": True})
        titles = layout.operators("whittle.history_restore")
        self.assertEqual([c["depress"] for c in titles], [False, True, False, False, False],
                         "the current row is highlighted")
        self.assertFalse([c for c in layout.of("label") if c["icon"].startswith("RADIOBUT")])
        self.assertEqual(len(layout.of("template_icon")), 4, "a thumbnail for each snapshot")
        self.assertEqual(layout.operators("whittle.ghost_toggle"), [], "Ghost is in the turn's menu")
        self.assertEqual(len(layout.operators("whittle.open_transcript")), 1)
        self.assertNotIn("No history yet: it starts with the first turn", layout.labels())

    def test_indentation_follows_branches_only(self):
        """Siblings line up whatever was drawn before them, and a line of
        turns without branches stays flat."""
        self.assertEqual(ui.branch_levels(self.hist.tree),
                         {"n0000": 0, "n0001": 0, "n0002": 1, "n0003": 1, "n0004": 1})
        layout = self.popover()
        starts = [c for c in layout.of("label") if c["text"] == ui.BRANCH_MARK]
        self.assertEqual(len(starts), 2, "n0002 and n0004 each start a branch")
        self.assertFalse([c for c in layout.of("label") if c["icon"].startswith("TRIA")],
                         "no disclosure triangles: nothing here folds")
        self.assertEqual([t for t in layout.labels() if "branches" in t], ["2 branches"],
                         "the row a branch leaves from says so")
        self.assertEqual(layout.of("separator")[:-1], [], "no separators: indentation is a fixed width")

    def test_buttons_disabled_during_a_turn(self):
        layout = self.popover(fake_controller(AgentState.BUSY, running=True, active_turn=("n0005", "x")))
        self.assertTrue(all(not buttons["history_restore"] for _n, buttons in self.rows(layout)))

    def test_compare_box(self):
        comparing = SimpleNamespace(showing="n0002", other="n0002")
        layout = self.popover(comparing=comparing)
        self.assertIn("Showing: Step 2: nudge the crate", layout.labels())
        self.assertEqual([c["props"].keep for c in layout.operators("whittle.compare_end")], [True, False])

    def test_no_history(self):
        layout = RecordingLayout()
        ui.draw_history(layout, ui.Ctx(scene=self.scene, hist=None, ctl=None, comparing=None))
        self.assertEqual(layout.operators(), [])

    def test_restore_tooltip_names_the_node(self):
        from unittest import mock

        from whittle.addon import history

        with mock.patch.object(history, "active", return_value=self.hist):
            text = operators.WHITTLE_OT_history_restore.description(bpy.context, SimpleNamespace(node="n0002"))
        self.assertTrue(text.startswith("n0002 · Step 2: nudge the crate."), text)


class TargetsTest(AddonTestCase):
    def test_resolve_list_and_collection(self):
        props_coll = bpy.data.collections.new("Props")
        self.scene.collection.children.link(props_coll)
        self.addCleanup(bpy.data.collections.remove, props_coll)
        lid = bpy.data.objects.new("Lid", bpy.data.meshes.new("Lid"))
        props_coll.objects.link(lid)
        props_coll.objects.link(self.crate)
        cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        props_coll.objects.link(cam)
        gone = bpy.data.objects.new("Gone", bpy.data.meshes.new("Gone"))
        self.scene.collection.objects.link(gone)
        sketch_obj = sketch.ensure_sketch_layers(self.scene)
        self.props.targets.add().object = self.crate
        self.props.targets.add().object = gone
        self.props.target_collection = props_coll
        bpy.data.objects.remove(gone)
        names = [o.name for o in targets.resolve(self.scene)]
        self.assertEqual(names, ["Crate", "Lid"])
        self.assertNotIn(sketch_obj.name, names)
        self.assertEqual(targets.describe(self.scene), "Crate + Props (2)")
        self.assertEqual(targets.add(self.scene, [self.crate, lid, cam, sketch_obj]), 1)

    def test_set_from_selection(self):
        sketch_obj = sketch.ensure_sketch_layers(self.scene)
        other = bpy.data.objects.new("Other", bpy.data.meshes.new("Other"))
        self.scene.collection.objects.link(other)
        bpy.ops.object.select_all(action="DESELECT")
        self.crate.select_set(True)
        sketch_obj.select_set(True)
        self.props.targets.add().object = other
        self.assertEqual(targets.set_from_selection(bpy.context), 1)
        self.assertEqual([t.object.name for t in self.props.targets], ["Crate"])

    def test_describe(self):
        self.assertEqual(targets.describe(self.scene), "New objects")
        self.props.targets.add().object = self.crate
        for i in range(3):
            plank = bpy.data.objects.new(f"Plank_{i}", bpy.data.meshes.new(f"Plank_{i}"))
            self.scene.collection.objects.link(plank)
            self.addCleanup(bpy.data.objects.remove, plank)
            self.props.targets.add().object = plank
        self.assertEqual(targets.describe(self.scene), "Crate, Plank_0, Plank_1, Plank_2")
        self.assertEqual(targets.describe(self.scene, 20), "Crate + 3 more")
        self.assertEqual(targets.describe(self.scene, names=["Crate_Lid"]), "Crate_Lid",
                         "a running turn's own targets")
        self.props.targets.clear()
        empty = bpy.data.collections.new("Whittle Target")
        self.scene.collection.children.link(empty)
        self.addCleanup(bpy.data.collections.remove, empty)
        self.props.target_collection = empty
        self.assertEqual(targets.describe(self.scene), "New objects in Whittle Target")

    def test_target_operators(self):
        self.crate.select_set(True)
        self.assertEqual(bpy.ops.whittle.target_from_selection(), {"FINISHED"})
        self.assertEqual(len(self.props.targets), 1)
        self.assertEqual(bpy.ops.whittle.target_remove(index=0), {"FINISHED"})
        self.assertEqual(len(self.props.targets), 0)
        self.assertEqual(bpy.ops.whittle.target_add(), {"FINISHED"})
        self.assertEqual(bpy.ops.whittle.target_clear(), {"FINISHED"})
        self.assertEqual(len(self.props.targets), 0)

    def test_view_remove_is_refused_while_strokes_use_it(self):
        from whittle.addon import operators

        obj = sketch.ensure_sketch_layers(self.scene)
        views.add_view(obj.data, lambda i: look_at_view(i, (0, -2, 0.3), (0, 0, 0.3)))
        views.add_view(obj.data, lambda i: look_at_view(i, (2, 0, 0.3), (0, 0, 0.3)))
        add_stroke(obj, "free", [(0, 0, 0), (0.1, 0, 0)], view=1)
        with self.assertRaises(RuntimeError):
            operators.remove_view(obj, 1)
        operators.remove_view(obj, 2)
        self.assertEqual([v.id for v in views.load_views(obj.data)], [1])


class StreamModelTest(unittest.TestCase):
    def test_results_merge_into_their_call(self):
        s = stream.Stream()
        s.append(Event.TOOL_USE, {"turn_id": "n1", "tool_use_id": "a", "tool": "exec",
                                  "input": {"code": "print(1)", "label": "probe"}})
        s.append(Event.TEXT, {"turn_id": "n1", "text": "thinking aloud\nsecond line"})
        entry = s.append(Event.TOOL_RESULT, {"turn_id": "n1", "tool_use_id": "a", "is_error": True,
                                             "summary": "boom", "images": ["/x.png"]})
        self.assertEqual([e.kind for e in s.entries()], ["tool", "text"])
        self.assertEqual((entry.status, entry.result, entry.images), ("error", "boom", ["/x.png"]))
        self.assertEqual(s.lines(), ["> exec · probe [error]", "thinking aloud"])
        self.assertEqual(s.images(), ["/x.png"])
        self.assertIsNone(s.append(Event.STATUS, {"state": "running"}))
        orphan = s.append(Event.TOOL_RESULT, {"tool_use_id": "zz", "summary": "late"})
        self.assertEqual(orphan.kind, "tool")

    def test_titles(self):
        def title(tool, inp):
            return stream.tool_title(stream.Entry(id=0, kind="tool", turn_id=None, text="", tool=tool, input=inp))

        self.assertEqual(title("exec", {"code": "x = 1\ny = 2"}), "exec · x = 1")
        self.assertEqual(title("render", {"mode": "shaded", "camera": {}}), "render · shaded")
        self.assertEqual(title("render", {"mode": "shaded", "camera": {"location": [0, 0, 0]}}),
                         "render · shaded camera")
        self.assertEqual(title("inspect", {"query": "object", "name": "Crate"}), "inspect · object Crate")
        self.assertEqual(title("request", {"amend": 2}), "request · amendment 2")
        self.assertEqual(title("ask", {"question": "Sure?"}), "ask · Sure?")
        self.assertEqual(title("checkpoint", {}), "checkpoint")

    def test_old_entries_fall_off(self):
        s = stream.Stream(maxlen=3)
        for i in range(5):
            s.append(Event.TOOL_USE, {"tool_use_id": f"t{i}", "tool": "exec", "input": {}})
        self.assertEqual(len(s.entries()), 3)
        self.assertEqual(sorted(s._tools), ["t2", "t3", "t4"])
        self.assertEqual([e.id for e in s.entries(2)], [4, 5])

    def test_wrap(self):
        lines = stream.wrap("word " * 50 + "\n\nnext", 140)
        self.assertTrue(all(len(line) <= int(140 / stream.CHAR_PX) for line in lines))
        self.assertIn("", lines, "blank lines are kept")
        self.assertEqual(lines[-1], "next")
        self.assertEqual(stream.wrap("x" * 40, 70, scale=2.0)[0], "x" * 12)


class TranscriptTest(unittest.TestCase):
    RECORDS = [
        {"type": "local", "name": "submit", "data": {"node": "n0001", "prompt": "Add a lid.", "targets": ["Crate"]}},
        {"type": "event", "name": "turn_started", "data": {"turn_id": "n0001"}},
        {"type": "event", "name": "text", "data": {"text": "Plan: a lid."}},
        {"type": "event", "name": "tool_use", "data": {"tool_use_id": "a", "tool": "exec",
                                                       "input": {"code": "make_lid()", "label": "lid"}}},
        {"type": "event", "name": "tool_result", "data": {"tool_use_id": "a", "is_error": False,
                                                          "summary": "stdout: ok", "images": ["/r/1.png"]}},
        {"type": "local", "name": "amend", "data": {"amend": 1, "text": "taller", "bundle_dir": "/s/amend-1"}},
        {"type": "local", "name": "answer", "data": {"question": "Bevel?", "answer": "yes"}},
        {"type": "local", "name": "target_edited", "data": {"edits": [{"name": "Crate", "kind": "transform"}]}},
        {"type": "local", "name": "interrupt", "data": {"mode": "restore"}},
        {"type": "event", "name": "turn_finished", "data": {"interrupted": True, "num_turns": 3, "cost_usd": 0.0123,
                                                            "errors": []}},
        {"type": "local", "name": "restored", "data": {"objects": ["Crate"]}},
    ]

    def test_format(self):
        text = transcript.format_transcript(self.RECORDS)
        for part in ("Turn n0001", "Prompt: Add a lid.", "Target: Crate", "Plan: a lid.", "> exec (lid)",
                     "    make_lid()", "  < ok:", "    image: /r/1.png", "Amendment 1: taller",
                     "Question: Bevel?", "Answer: yes", "You edited the target: Crate (transform)",
                     "Interrupted (restore the turn start)", "Turn interrupted: 3 steps, $0.0123",
                     "Restored the turn start: Crate"):
            self.assertIn(part, text)

    def test_session_records_in_node_order(self):
        import json
        import shutil

        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        session = formats.SessionDir(root)
        for node, text in (("n0002", "second"), ("n0001", "first")):
            path = session.transcript_path(node)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"type": "event", "name": "text", "data": {"text": text}}) + "\nnot json\n")
        with self.assertLogs("whittle", "WARNING"):
            records = transcript.session_records(session)
        self.assertEqual([r["data"].get("text") or r["data"].get("node") for r in records],
                         ["n0001", "first", "n0002", "second"])


class EditorsTest(AddonTestCase):
    def test_show_image_loads_without_opening_anything(self):
        windows = len(bpy.context.window_manager.windows)
        image = editors.show_image(bpy.context, PNG)
        self.assertEqual(Path(bpy.path.abspath(image.filepath)), Path(PNG))
        self.assertIs(editors.show_image(bpy.context, PNG), image, "an image is loaded once")
        self.assertEqual(len(bpy.context.window_manager.windows), windows)
        bpy.data.images.remove(image)

    def test_previews(self):
        icon = previews.icon(PNG)
        self.assertIsInstance(icon, int)
        loaded = previews.preview(PNG)
        self.assertEqual(tuple(loaded.image_size), (256, 192))
        self.assertIs(previews.preview(PNG), loaded)
        self.assertEqual(previews.icon("/nonexistent/whittle.png"), 0)
        previews.clear()



class MarkdownTest(unittest.TestCase):
    def draw(self, text: str, width=240) -> RecordingLayout:
        ctx = ui.Ctx(scene=bpy.context.scene, hist=None, ctl=None, comparing=None, width=width)
        layout = RecordingLayout()
        ui.draw_markdown(layout, ui.markdown_lines(text, ctx, width), ctx, width)
        return layout

    def test_markers_never_show(self):
        layout = self.draw("## Done\n\nI added **two horns**, *curved*:\n- left\n- right\n> careful")
        text = layout.text()
        for marker in ("**", "##", "> ", "- "):
            self.assertNotIn(marker, text)
        self.assertIn("𝗗𝗼𝗻𝗲", layout.labels(), "the heading is bold")
        self.assertIn("𝘁𝘄𝗼", text)
        self.assertEqual(layout.labels().count("•"), 2, "each item's bullet in its own margin")
        self.assertTrue(any(c["kind"] == "separator" for c in layout.calls), "paragraphs have a gap")

    def test_code_goes_in_one_box_and_lines_fit(self):
        layout = self.draw("```\nx = 1\ny = 2\n```\nok")
        self.assertEqual(len(layout.of("box")), 1)
        ctx = ui.Ctx(scene=bpy.context.scene, hist=None, ctl=None, comparing=None, width=240)
        lines = ui.markdown_lines("word " * 80, ctx, 240)
        self.assertGreater(len(lines), 3)
        self.assertTrue(all(ctx.measure(line.text) <= 240 for line in lines))

    def test_headings_quotes_and_footnotes(self):
        layout = self.draw("# One\n## Two\n### Three\n##### Five\n> quoted\n>> deeper\n\nSee[^1].\n\n[^1]: A note.")
        rules = [c for c in layout.of("separator") if c.get("type") == "LINE"]
        self.assertEqual(len(rules), 4, "H1 double underlined, H2 underlined, and the rule above the footnotes")
        dim = {c["text"] for c in layout.of("label") if not layout.is_active(c)}
        self.assertTrue({"𝗙𝗶𝘃𝗲", "quoted", "deeper", "A note."} <= dim, dim)
        self.assertTrue(layout.is_active(next(c for c in layout.of("label") if c["text"] == "𝗧𝗵𝗿𝗲𝗲")))
        self.assertIn("¹", layout.labels(), "the footnote's number in its margin")
        self.assertNotIn(">", layout.text())

    def test_a_table_is_a_box_of_columns(self):
        layout = self.draw("| Name | Size |\n|:--|--:|\n| crate lid with a long name | 2 |", width=240)
        self.assertEqual(len(layout.of("box")), 1)
        labels = layout.labels()
        self.assertIn("𝗡𝗮𝗺𝗲", labels, "the header is bold")
        self.assertIn("2", labels)
        aligned = {c["layout"].alignment for c in layout.of("label") if c["text"] in ("2", "𝗦𝗶𝘇𝗲")}
        self.assertEqual(aligned, {"RIGHT"})
        self.assertTrue(any(c.get("type") == "LINE" for c in layout.of("separator")), "a line under the header")
        ctx = ui.Ctx(scene=bpy.context.scene, hist=None, ctl=None, comparing=None, width=240)
        table = ui.markdown_lines("| a | b |\n|---|---|\n| " + "long words " * 12 + "| x |", ctx, 240)[0].table
        self.assertLessEqual(sum(table.widths) + ui.BOX_PAD, 240, "the table fits the panel")
        self.assertGreater(len(table.rows[1][0]), 1, "its cell wraps")

    def test_details_are_a_closed_section(self):
        layout = self.draw("<details><summary>Steps</summary>\n\nHidden **text**\n</details>")
        panel = layout.of("panel")[0]
        self.assertTrue(panel["idname"].startswith("whittle_md_"))
        self.assertTrue(panel["default_closed"])
        self.assertEqual([c["text"] for c in layout.of("label") if c["layout"] is panel["child"]], ["Steps"])
        hidden = next(c for c in layout.of("label") if c["text"] == "Hidden 𝘁𝗲𝘅𝘁")
        self.assertTrue(layout.in_panel(hidden, "whittle_md_"))

    def test_a_line_with_a_link_ends_with_its_button(self):
        layout = self.draw("Read [the manual](https://docs.blender.org) first.\nNo link.")
        buttons = layout.operators("whittle.open_link")
        self.assertEqual(len(buttons), 1)
        self.assertEqual((buttons[0]["props"].url, buttons[0]["props"].text),
                         ("https://docs.blender.org", "the manual"))
        self.assertEqual(buttons[0]["icon"], "URL")
        self.assertEqual(buttons[0]["layout"].emboss, "NONE")
        self.assertIn("“the manual”", ui.WHITTLE_OT_open_link.description(None, buttons[0]["props"]))

    def test_a_line_with_several_links_opens_a_menu_of_them(self):
        layout = self.draw("Read [a](https://a.com) and [b](https://b.com/x) now.")
        self.assertEqual(layout.operators("whittle.open_link"), [])
        menu = layout.operators("whittle.link_menu")
        self.assertEqual(len(menu), 1)
        self.assertEqual(json.loads(menu[0]["props"].links), [["a", "https://a.com"], ["b", "https://b.com/x"]])
        self.assertEqual(ui.link_entry("b", "https://b.com/x"), "b · b.com")
        self.assertEqual(ui.link_entry("https://b.com/x", "https://b.com/x"), "b.com")

    def test_quotes_have_a_bar_per_level(self):
        layout = self.draw("> one\n>> two\n>>> three\n\nafter")
        bars = [c for c in layout.of("label") if c["text"] == ui.QUOTE_BAR]
        self.assertEqual(len(bars), 6, "one, two and three bars")
        self.assertTrue(all(not layout.is_active(c) for c in bars), "dim")
        layout = self.draw("> ```\n> x\n> y\n> ```")
        self.assertEqual(layout.labels().count(ui.QUOTE_BAR), 2,
                         "beside a quoted code box's lines (no language, so no head row)")

    def test_a_code_block_without_a_language_has_no_empty_head(self):
        layout = self.draw("```\nx = 1\ny = 2\n```")
        self.assertEqual(layout.labels(), ["𝚡 = 𝟷", "𝚢 = 𝟸"], "no blank head row")
        (copy,) = layout.operators("whittle.copy_code")
        self.assertEqual(copy["props"].text, "x = 1\ny = 2", "the copy button sits on the first row")

    def test_a_code_block_has_its_language_and_a_copy_button(self):
        layout = self.draw("```python\nx = 1\n```")
        self.assertEqual(len(layout.of("box")), 1)
        self.assertIn("python", layout.labels())
        copy = layout.operators("whittle.copy_code")
        self.assertEqual(len(copy), 1)
        self.assertEqual((copy[0]["props"].text, copy[0]["icon"]), ("x = 1", "COPYDOWN"))
        context = SimpleNamespace(window_manager=SimpleNamespace(clipboard=""))
        op = SimpleNamespace(text="x = 1", report=lambda *_args: None)
        self.assertEqual(ui.WHITTLE_OT_copy_code.execute(op, context), {"FINISHED"})
        self.assertEqual(context.window_manager.clipboard, "x = 1")


if __name__ == "__main__":
    unittest.main()
