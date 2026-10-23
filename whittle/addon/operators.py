# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators: sketching, views, submitting, and driving the agent by hand."""

import logging
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from .. import chats as chat_store
from .. import formats
from . import bundle, chats, compare, editors, history, sketch, targets, transcript, turn, views

log = logging.getLogger("whittle")


def controller(fake_script: str = "") -> turn.TurnController:
    """The current controller, replaced when it is idle and the fake setting
    changed. An idle agent started with another Python, API key, model or session
    settings is stopped, so the next run starts one with the new settings and
    resumes the conversation from the history."""
    current = turn.current()
    fake = Path(bpy.path.abspath(fake_script)) if fake_script else None
    if current is not None and busy(current):
        return current
    if current is not None and current.process.fake_script != fake:
        current.close()
        current = None
    if current is None:
        folder = chats.current_folder(create=True)
        if folder is None:
            raise RuntimeError("the current chat cannot be opened")
        current = turn.TurnController(folder, fake_script=fake)
        turn.set_current(current)
    elif current.launch_changed:
        log.info("the agent settings changed; restarting the agent")
        current.stop(wait=True)
    return current


def run_bundle(context, fake_script: str = "") -> turn.TurnController:
    """Body of the Run Bundle operator, callable from tests."""
    props = context.scene.whittle
    wm = context.window_manager
    bundle_dir = Path(bpy.path.abspath(wm.whittle_bundle_path))
    ctl = controller(fake_script or wm.whittle_fake_script)
    ctl.run_bundle(bundle_dir, props.prompt or None)
    return ctl


def submit_sketch(context, fake_script: str = "") -> tuple[turn.TurnController, str]:
    """Body of the Send operator, callable from tests. The prompt leaves the
    prompt box once the run is under way (the conversation shows it); the
    controller puts it back if the run never starts."""
    props = context.scene.whittle
    refs = [Path(bpy.path.abspath(r.path)) for r in props.refs if r.path]
    ctl = controller(fake_script or context.window_manager.whittle_fake_script)
    text = props.prompt
    ctl.hold_prompt(context.scene, text)
    try:
        node = ctl.run_sketch(text, targets=targets.resolve(context.scene), refs=refs, scene=context.scene)
    except BaseException:
        ctl.hold_prompt(context.scene, "")
        raise
    if busy(ctl) and props.prompt == text:
        props.prompt = ""
    return ctl, node


def amend(context) -> int:
    """Body of the Amend operator: the amend text and any new strokes go into
    the running turn."""
    ctl = turn.current()
    if ctl is None:
        raise RuntimeError("there is no running turn to amend")
    props = context.scene.whittle
    number = ctl.amend(props.amend_text, scene=context.scene)
    props.amend_text = ""
    return number


def interrupt(mode: str) -> None:
    ctl = turn.current()
    if ctl is not None:
        ctl.interrupt(restore=mode == "RESTORE")


def answer(context, text: str = "") -> bool:
    ctl = turn.current()
    props = context.scene.whittle
    answered = ctl is not None and ctl.answer(text or props.ask_answer)
    if answered:
        props.ask_answer = ""
    return answered


def open_image(context, path: str):
    return editors.show_image(context, bpy.path.abspath(path))


def open_transcript(context):
    ctl = turn.current()
    if ctl is None:
        raise RuntimeError("there is no session yet")
    return transcript.open_transcript(ctl.session, context)


def remove_view(obj, view_id: int) -> None:
    if obj is None:
        raise RuntimeError("there is no sketch")
    if view_id in sketch.used_views(obj):
        raise RuntimeError(f"strokes still use view {view_id}")
    remaining = {v.id for v in views.load_views(obj.data)} - {view_id}
    views.save_views(obj.data, [v for v in views.load_views(obj.data) if v.id in remaining])


def snap_to_view(context, view_id: int) -> formats.View:
    """Body of the Snap to View operator: moves the viewport the operator
    ran in back to a stored view, which new strokes are then tagged with.
    Strokes still waiting for a tag belong to the view before it; the pivot
    goes to the depth of the view's own strokes when it has any."""
    obj = sketch.find_sketch_object()
    if obj is None:
        raise RuntimeError("there is no sketch")
    view = next((v for v in views.load_views(obj.data) if v.id == view_id), None)
    if view is None:
        raise RuntimeError(f"there is no view {view_id}")
    viewport = views.viewport_from_context(context)
    if viewport is None:
        raise RuntimeError("Snap to View needs a 3D viewport")
    current = views.current_view(obj.data)
    if current is not None:
        sketch.tag_strokes(obj, current.id)
    views.snap_viewport(viewport, view, sketch.view_depth(obj, view))
    views.set_current_view(obj.data, view.id)
    return view


def capture_view(context) -> formats.View:
    """Body of the Capture View operator: a new view from the viewport the
    operator ran in, with or without an active sketch session."""
    viewport = views.viewport_from_context(context)
    if viewport is None:
        raise RuntimeError("Capture View needs a 3D viewport")
    session = sketch.current_session() or sketch.SketchSession(context.scene, use_timer=False)
    return session.capture(viewport)


# -- history --------------------------------------------------------------------

busy = turn.busy


def history_idle(ctl) -> bool:
    """History actions change the target, so they wait for the turn and for
    any comparison to end."""
    return not busy(ctl) and compare.active() is None


def can_restore(hist, ctl, node: str) -> bool:
    return hist is not None and history_idle(ctl) and hist.can_restore(node)


def can_branch(hist, ctl, node: str) -> bool:
    if hist is None or hist.tree is None or node not in hist.tree.nodes:
        return False
    found = hist.tree.node(node)
    if found.folded:
        # A folded turn never left its parent: editing it only brings its
        # prompt back, while the scene is still there.
        return history_idle(ctl) and hist.current == found.parent
    return found.parent is not None and can_restore(hist, ctl, found.parent)


def can_compare(hist, ctl, node: str) -> bool:
    return can_restore(hist, ctl, node) and node != hist.current


def switch_target(hist, node: str) -> str | None:
    """Where switching to the branch at node lands: its newest leaf that can
    be restored, else node itself."""
    if hist is None or hist.tree is None or node not in hist.tree.nodes or hist.tree.node(node).folded:
        return None
    for candidate in [*hist.tree.leaves_under(node), node]:
        if hist.can_restore(candidate):
            return candidate
    return None


def can_switch(hist, ctl, node: str) -> bool:
    return history_idle(ctl) and switch_target(hist, node) is not None


def can_retry(hist, ctl, node: str) -> bool:
    """A failed turn can be sent again from where it started: a folded one
    while the scene is still at its parent, a recorded one by branching."""
    if hist is None or hist.tree is None or node not in hist.tree.nodes or not history_idle(ctl):
        return False
    found = hist.tree.node(node)
    if found.status != "failed":
        return False
    if found.folded:
        return hist.current == found.parent
    return can_branch(hist, ctl, node)


def _history_for(context, ctl=None):
    hist = history.active()
    if hist is None or hist.tree is None:
        raise RuntimeError("there is no history yet")
    if busy(ctl if ctl is not None else turn.current()):
        raise RuntimeError("wait for the turn to finish")
    if compare.active() is not None:
        raise RuntimeError("end the comparison first")
    return hist


def restore_node(context, node: str) -> list[str]:
    """Body of the history Restore button: the target as it was at the node."""
    hist = _history_for(context)
    compare.clear_ghost()
    return hist.restore(node, context.scene)


def branch_node(context, node: str) -> str:
    """Body of the history Branch button: restores the node's parent and puts
    the node's prompt back, so the next submit is another take on its turn."""
    hist = _history_for(context)
    found = hist.tree.node(node)
    if found.parent is None:
        raise RuntimeError("the start of the history has no turn to take again")
    if found.folded:
        # Its strokes and references are still pending; only the prompt
        # left the prompt box.
        if hist.current != found.parent:
            raise RuntimeError(f"go back to {found.parent} to edit {node}")
        context.scene.whittle.prompt = found.prompt
        return found.parent
    compare.clear_ghost()
    return hist.branch(node, context.scene)


def switch_branch(context, node: str) -> str:
    """Body of the branch switcher: the scene goes to the newest leaf of the
    branch at node, as one undo step. Returns the node restored."""
    hist = _history_for(context)
    target = switch_target(hist, node)
    if target is None:
        raise RuntimeError(f"there is nothing to restore on the branch at {node}")
    compare.clear_ghost()
    hist.restore(target, context.scene, undo=False)
    history.undo_push(f"{history.UNDO_PREFIX}: switch to {node}")
    return target


def retry(context, node: str, fake_script: str = "") -> tuple[turn.TurnController, str]:
    """Body of Retry: a failed turn's request goes again from the node it
    started at. A recorded failure is branched first, which brings its
    prompt, strokes and references back; a folded one never left its
    parent, and its strokes and references are still pending."""
    hist = _history_for(context)
    found = hist.tree.node(node)
    if found.status != "failed":
        raise RuntimeError(f"{node} did not fail")
    props = context.scene.whittle
    if found.folded:
        if hist.current != found.parent:
            raise RuntimeError(f"go back to {found.parent} to retry {node}")
        if not props.prompt.strip():
            props.prompt = found.prompt
    else:
        branch_node(context, node)
    return submit_sketch(context, fake_script)


def compare_node(context, node: str) -> compare.Compare:
    hist = _history_for(context)
    if node == hist.current:
        raise RuntimeError(f"the scene already shows {node}")
    return compare.start(hist, node, context.scene)


def toggle_ghost(context) -> str | None:
    """Shows the current node's parent as a ghost, or hides the ghost;
    returns the node shown."""
    if compare.ghost_node() is not None:
        compare.clear_ghost()
        return None
    hist = history.active()
    if hist is None or hist.tree is None:
        raise RuntimeError("there is no history yet")
    parent = hist.tree.node(hist.current).parent
    if parent is None:
        raise RuntimeError("the start of the history has no parent to show")
    compare.show_ghost(hist, parent, context.scene)
    return parent


# -- chats ----------------------------------------------------------------------

CHAT_WAIT = "Wait for the turn to end, or stop it"
CHAT_COMPARING = "End the comparison first"
CHAT_NEW_ALREADY = "This chat is new already"
CHAT_GONE = "This chat is no longer in the file"


def chat_blocker(ctl) -> str | None:
    """Why the current chat cannot be left now: a turn runs (or Claude asks),
    or a comparison shows another node of it."""
    if busy(ctl) or getattr(ctl, "question", None) is not None:
        return CHAT_WAIT
    if compare.active() is not None:
        return CHAT_COMPARING
    return None


def can_new_chat(found, ctl) -> str | None:
    """Why New Chat is disabled, or None."""
    reason = chat_blocker(ctl)
    if reason:
        return reason
    if found is None or found.current is None or not found.entry(found.current).turns:
        return CHAT_NEW_ALREADY
    return None


def can_switch_chat(found, ctl, chat: str) -> str | None:
    if found is None or chat not in found:
        return CHAT_GONE
    return chat_blocker(ctl)


def can_delete_chat(found, ctl, chat: str) -> str | None:
    """Another chat can always go; the current one only when it can be left."""
    if found is None or chat not in found:
        return CHAT_GONE
    return chat_blocker(ctl) if chat == found.current else None


def _leave_chat(scene) -> None:
    """The current chat's agent stops and its ghost goes; the scene stays as
    it is. The next run starts a controller on whichever chat is current."""
    compare.clear_ghost()
    ctl = turn.current()
    if ctl is not None:
        ctl.close()
        turn.set_current(None)


def _show_chat(scene, found) -> None:
    """The scene names the chat now current and its node, without an undo
    step: chats are not undone."""
    history.invalidate()
    hist = history.active()
    if scene is not None and hasattr(scene, "whittle"):
        scene.whittle.chat = found.current or ""
        scene.whittle.history_node = hist.current if hist is not None and hist.tree is not None else ""


def new_chat(context) -> str:
    """Body of New Chat: an empty chat becomes current. Its history starts
    when its first turn is sent (or a start point taken), from the scene as
    it is then; the scene is not touched now."""
    found = chats.get()
    reason = can_new_chat(found, turn.current())
    if reason:
        raise RuntimeError(reason)
    _leave_chat(context.scene)
    chat = found.new()
    _show_chat(context.scene, found)
    return chat


def switch_chat(context, chat: str) -> str:
    """Body of a chat's title in the chat menu: that chat becomes current.
    The scene stays exactly as it is; only the conversation shown and the
    Claude session the next turn continues change."""
    found = chats.get()
    reason = can_switch_chat(found, turn.current(), chat)
    if reason:
        raise RuntimeError(reason)
    if chat == found.current:
        return chat
    _leave_chat(context.scene)
    found.switch(chat)
    _show_chat(context.scene, found)
    return chat


def rename_chat(context, title: str) -> str:
    """Body of Rename This Chat; an empty title puts the automatic one back."""
    found = chats.get()
    if found is None or found.current is None:
        raise RuntimeError("there is no chat to rename")
    return found.rename(found.current, title)


def delete_chat(context, chat: str) -> str | None:
    """Body of a chat's delete: it leaves the cache now and the .blend at
    the next save. Deleting the current chat makes the most recent other
    one current, as a switch, or a new empty chat. Returns the current chat."""
    found = chats.get()
    reason = can_delete_chat(found, turn.current(), chat)
    if reason:
        raise RuntimeError(reason)
    current = chat == found.current
    if current:
        _leave_chat(context.scene)
    found.delete(chat, chats.config_dir())
    if current:
        _show_chat(context.scene, found)
    return found.current


def delete_chats(context, which: str) -> list[str]:
    """Body of Delete Other Chats: every listed chat but the current one, or
    those whose last turn is older than the choice. Returns the chats deleted."""
    found = chats.get()
    if found is None:
        return []
    doomed = found.to_delete(which)
    for chat in doomed:
        found.delete(chat, chats.config_dir())
    return doomed


def chat_summary(found, chat: str) -> str:
    entry = found.entry(chat)
    return f"{entry.turns} turn{'' if entry.turns == 1 else 's'}"


def _in_view3d(context) -> bool:
    return context.area is not None and context.area.type == "VIEW_3D"


class WHITTLE_OT_sketch(bpy.types.Operator):
    bl_idname = "whittle.sketch"
    bl_label = "Sketch"
    bl_description = "Draw on the Whittle Sketch object, with strokes placed on surfaces"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _in_view3d(context) and sketch.current_session() is None

    def execute(self, context):
        try:
            sketch.start_session(context)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_sketch_toggle(bpy.types.Operator):
    bl_idname = "whittle.sketch_toggle"
    bl_label = "Toggle Sketch Mode"
    bl_description = "Start sketching on the Whittle Sketch object, or stop"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return sketch.current_session() is not None or _in_view3d(context)

    def execute(self, context):
        if sketch.current_session() is not None:
            sketch.end_session(context)
            return {"FINISHED"}
        try:
            sketch.start_session(context)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_sketch_stop(bpy.types.Operator):
    bl_idname = "whittle.sketch_stop"
    bl_label = "Stop Sketching"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return sketch.current_session() is not None

    def execute(self, context):
        sketch.end_session(context)
        return {"FINISHED"}


STROKE_MEANINGS = {
    "free": "a general mark: an outline or a shape to follow",
    "add": "build material here",
    "carve": "remove material here",
    "crease": "a sharp edge or a bevel along this line",
    "region": "the area this request is about",
    "note": "a written note for Claude",
}


class WHITTLE_OT_stroke_type(bpy.types.Operator):
    bl_idname = "whittle.stroke_type"
    bl_label = "Stroke Type"
    bl_description = "Draw the next strokes as this type"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(
        name="Type",
        items=[(t, t.capitalize(), f"{t.capitalize()}: {STROKE_MEANINGS[t]}") for t in formats.STROKE_TYPES])

    @classmethod
    def description(cls, context, properties):
        # The sketch strip's buttons are icons only, so the tooltip names them.
        return f"{properties.type.capitalize()}: {STROKE_MEANINGS[properties.type]}"

    def execute(self, context):
        obj = sketch.ensure_sketch_layers(context.scene)
        sketch.set_active_type(obj, self.type)
        return {"FINISHED"}


class WHITTLE_OT_next_stroke_type(bpy.types.Operator):
    bl_idname = "whittle.next_stroke_type"
    bl_label = "Next Stroke Type"
    bl_description = "Cycle the stroke type new strokes are drawn as"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = sketch.ensure_sketch_layers(context.scene)
        stroke_type = sketch.next_type(obj)
        sketch.set_active_type(obj, stroke_type)
        self.report({"INFO"}, f"Stroke type: {stroke_type}")
        return {"FINISHED"}


class WHITTLE_OT_capture_view(bpy.types.Operator):
    bl_idname = "whittle.capture_view"
    bl_label = "Capture View"
    bl_description = "Record the current viewport as a sketch view; new strokes are tagged with it"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _in_view3d(context)

    def execute(self, context):
        try:
            view = capture_view(context)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Captured view {view.id}")
        return {"FINISHED"}


class WHITTLE_OT_submit(bpy.types.Operator):
    bl_idname = "whittle.submit"
    bl_label = "Send"
    bl_description = "Send the prompt, the sketch and the references to Claude"

    fake_script: StringProperty(name="Fake Script", default="", subtype="FILE_PATH",
                                description="Play a scripted fake agent instead of Claude")

    @classmethod
    def poll(cls, context):
        if compare.active() is not None:
            # The panel has no line for this: the disabled button's tooltip says it.
            cls.poll_message_set("End the comparison to send")
            return False
        return not busy(turn.current())

    def execute(self, context):
        try:
            _ctl, node = submit_sketch(context, self.fake_script)
        except (bundle.BundleError, RuntimeError, ValueError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Submitted turn {node}")
        return {"FINISHED"}


class WHITTLE_OT_clear_sketch(bpy.types.Operator):
    bl_idname = "whittle.clear_sketch"
    bl_label = "Clear Sketch"
    bl_description = "Remove every stroke and view from the sketch"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return sketch.find_sketch_object() is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        sketch.clear_strokes(sketch.find_sketch_object())
        return {"FINISHED"}


class WHITTLE_OT_ref_add(bpy.types.Operator):
    bl_idname = "whittle.ref_add"
    bl_label = "Add Reference"
    bl_description = "Attach a reference image to the next request"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_image: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    filter_folder: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            return {"CANCELLED"}
        context.scene.whittle.refs.add().path = self.filepath
        return {"FINISHED"}


class WHITTLE_OT_ref_remove(bpy.types.Operator):
    bl_idname = "whittle.ref_remove"
    bl_label = "Remove Reference"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=0, min=0)

    def execute(self, context):
        refs = context.scene.whittle.refs
        if self.index >= len(refs):
            return {"CANCELLED"}
        refs.remove(self.index)
        return {"FINISHED"}


class WHITTLE_OT_run_bundle(bpy.types.Operator):
    bl_idname = "whittle.run_bundle"
    bl_label = "Run Bundle"
    bl_description = "Send a request bundle from disk to the agent"

    fake_script: StringProperty(name="Fake Script", default="", subtype="FILE_PATH",
                                description="Play a scripted fake agent instead of Claude")

    @classmethod
    def poll(cls, context):
        ctl = turn.current()
        return bool(context.window_manager.whittle_bundle_path) and not busy(ctl)

    def execute(self, context):
        try:
            run_bundle(context, self.fake_script)
        except (formats.FormatError, ValueError, RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_agent_start(bpy.types.Operator):
    bl_idname = "whittle.agent_start"
    bl_label = "Start Agent"

    fake_script: StringProperty(name="Fake Script", default="", subtype="FILE_PATH")

    def execute(self, context):
        ctl = controller(self.fake_script or context.window_manager.whittle_fake_script)
        ctl.start()
        if ctl.process.reason and not ctl.process.alive:
            self.report({"ERROR"}, ctl.process.reason)
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_agent_stop(bpy.types.Operator):
    bl_idname = "whittle.agent_stop"
    bl_label = "Stop Agent"

    @classmethod
    def poll(cls, context):
        ctl = turn.current()
        return ctl is not None and ctl.process.alive

    def execute(self, context):
        turn.current().stop()
        return {"FINISHED"}


class WHITTLE_OT_interrupt(bpy.types.Operator):
    bl_idname = "whittle.interrupt"
    bl_label = "Interrupt"
    bl_description = "Stop the turn after the step that is running"

    mode: EnumProperty(
        name="Then",
        items=[("KEEP", "Keep Partial Edit", "Leave the target as the agent left it"),
               ("RESTORE", "Restore Turn Start", "Put the target back as it was when the turn started")])

    @classmethod
    def description(cls, context, properties):
        if properties.mode == "RESTORE":
            return "Stop the turn and put the target back as it was when the turn started"
        return "Stop the turn and keep what the agent has done so far"

    @classmethod
    def poll(cls, context):
        ctl = turn.current()
        return ctl is not None and ctl.running

    def invoke(self, context, event):
        if self.properties.is_property_set("mode"):
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        interrupt(self.mode)
        return {"FINISHED"}


class WHITTLE_OT_amend(bpy.types.Operator):
    bl_idname = "whittle.amend"
    bl_label = "Amend"
    bl_description = "Send the amend text and any strokes drawn since the submit into the running turn"

    @classmethod
    def poll(cls, context):
        ctl = turn.current()
        return ctl is not None and ctl.can_amend

    def execute(self, context):
        try:
            number = amend(context)
        except (RuntimeError, ValueError, bundle.BundleError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        ctl = turn.current()
        sent = ctl is not None and ctl.running and not ctl.queued_amends
        self.report({"INFO"}, f"Sent amendment {number}" if sent
                    else f"Amendment {number} goes in once the turn starts")
        return {"FINISHED"}


class WHITTLE_OT_answer(bpy.types.Operator):
    bl_idname = "whittle.answer"
    bl_label = "Answer"
    bl_description = "Answer the agent's question"

    text: StringProperty(name="Answer", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        ctl = turn.current()
        return ctl is not None and ctl.question is not None

    def execute(self, context):
        if not answer(context, self.text):
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_open_image(bpy.types.Operator):
    bl_idname = "whittle.open_image"
    bl_label = "Open Image"
    bl_description = "Show this render in an Image Editor"

    filepath: StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})

    def execute(self, context):
        try:
            open_image(context, self.filepath)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_open_transcript(bpy.types.Operator):
    bl_idname = "whittle.open_transcript"
    bl_label = "Open Transcript"
    bl_description = "Write the session's full transcript into the Whittle Transcript text and show it"

    @classmethod
    def poll(cls, context):
        return turn.current() is not None

    def execute(self, context):
        try:
            open_transcript(context)
        except (RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_target_from_selection(bpy.types.Operator):
    bl_idname = "whittle.target_from_selection"
    bl_label = "From Selection"
    bl_description = "Make the selected objects the targets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = targets.set_from_selection(context)
        self.report({"INFO"}, f"{count} target{'s' if count != 1 else ''}")
        return {"FINISHED"}


class WHITTLE_OT_target_add(bpy.types.Operator):
    bl_idname = "whittle.target_add"
    bl_label = "Add Selected"
    bl_description = "Add the selected objects to the targets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets.add(context.scene, context.selected_objects)
        return {"FINISHED"}


class WHITTLE_OT_target_remove(bpy.types.Operator):
    bl_idname = "whittle.target_remove"
    bl_label = "Remove Target"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=0, min=0)

    def execute(self, context):
        props = context.scene.whittle
        if self.index >= len(props.targets):
            return {"CANCELLED"}
        props.targets.remove(self.index)
        props.target_index = min(props.target_index, max(len(props.targets) - 1, 0))
        return {"FINISHED"}


class WHITTLE_OT_target_clear(bpy.types.Operator):
    bl_idname = "whittle.target_clear"
    bl_label = "Clear Targets"
    bl_description = "No targets: the agent makes new objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.whittle
        props.targets.clear()
        props.target_collection = None
        props.target_index = 0
        return {"FINISHED"}


class WHITTLE_OT_view_remove(bpy.types.Operator):
    bl_idname = "whittle.view_remove"
    bl_label = "Remove View"
    bl_description = "Forget this sketch view; refused while strokes use it"
    bl_options = {"REGISTER", "UNDO"}

    id: IntProperty(default=0, min=0)

    def execute(self, context):
        try:
            remove_view(sketch.find_sketch_object(), self.id)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_view_snap(bpy.types.Operator):
    bl_idname = "whittle.view_snap"
    bl_label = "Snap to View"
    bl_description = "Move the viewport back to this sketch view; new strokes are tagged with it"
    # Moving the viewport is no undo step, as with Blender's own view operators.
    bl_options = {"REGISTER"}

    id: IntProperty(default=0, min=0)

    @classmethod
    def poll(cls, context):
        return _in_view3d(context)

    def execute(self, context):
        try:
            snap_to_view(context, self.id)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class _HistoryOperator:
    node: StringProperty(name="Node", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        hist = history.active()
        return hist is not None and hist.tree is not None and history_idle(turn.current())

    def run(self, context):
        raise NotImplementedError

    def execute(self, context):
        try:
            message = self.run(context)
        except (RuntimeError, formats.FormatError, OSError, KeyError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if message:
            self.report({"INFO"}, message)
        return {"FINISHED"}


class WHITTLE_OT_history_restore(_HistoryOperator, bpy.types.Operator):
    bl_idname = "whittle.history_restore"
    bl_label = "Go Back to This Turn"
    bl_description = ("Put the target back as it was at this turn; objects Claude made since are "
                      "removed, your own objects are kept")

    @classmethod
    def description(cls, context, properties):
        # Node ids are not shown in the conversation, so the tooltip has it.
        hist = history.active()
        named = properties.node
        if hist is not None and hist.tree is not None and properties.node in hist.tree.nodes:
            named = f"{properties.node} · {hist.tree.node(properties.node).label}"
        return f"{named}\n{cls.bl_description}" if named else cls.bl_description

    def run(self, context):
        restore_node(context, self.node)
        return f"Restored {self.node}"


class WHITTLE_OT_history_branch(_HistoryOperator, bpy.types.Operator):
    bl_idname = "whittle.history_branch"
    bl_label = "Edit & Resend"
    bl_description = ("Another take on this turn: go back to before it and bring its prompt, strokes "
                      "and references back, so Send makes a new branch")

    def run(self, context):
        branch_node(context, self.node)
        return "Edit the prompt and send it as a new branch"


class WHITTLE_OT_history_compare(_HistoryOperator, bpy.types.Operator):
    bl_idname = "whittle.history_compare"
    bl_label = "Compare With Current"
    bl_description = "Show this node in place of the current scene, and toggle between the two"

    def run(self, context):
        compare_node(context, self.node)
        return f"Showing {self.node}"


class WHITTLE_OT_branch_switch(_HistoryOperator, bpy.types.Operator):
    bl_idname = "whittle.branch_switch"
    bl_label = "Switch Branch"
    bl_description = "Go to this branch: the scene as its newest turn left it"

    def run(self, context):
        target = switch_branch(context, self.node)
        return f"Switched to {target}"


class WHITTLE_OT_retry(_HistoryOperator, bpy.types.Operator):
    bl_idname = "whittle.retry"
    bl_label = "Retry"
    bl_description = "Send this failed turn's request again from where it started"

    def run(self, context):
        _ctl, node = retry(context, self.node)
        return f"Sent again as {node}"

    def execute(self, context):
        try:
            message = self.run(context)
        except (bundle.BundleError, RuntimeError, formats.FormatError, OSError, KeyError,
                ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, message)
        return {"FINISHED"}


class WHITTLE_OT_compare_toggle(bpy.types.Operator):
    bl_idname = "whittle.compare_toggle"
    bl_label = "Toggle"
    bl_description = ("Switch between the scene as it was and the compared node. Saving the file "
                      "while comparing saves what is shown")

    @classmethod
    def poll(cls, context):
        return compare.active() is not None

    def execute(self, context):
        try:
            compare.active().toggle(context.scene)
        except (RuntimeError, formats.FormatError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_compare_end(bpy.types.Operator):
    bl_idname = "whittle.compare_end"
    bl_label = "End Comparison"
    bl_description = "Stop comparing"

    keep: BoolProperty(name="Keep", default=False, options={"SKIP_SAVE"},
                       description="Keep the compared node (a Restore) instead of the scene as it was")

    @classmethod
    def description(cls, context, properties):
        if properties.keep:
            return ("Stop comparing and keep the compared node, as a Restore would. Until then, "
                    "saving the file saves what is shown")
        return ("Stop comparing and put the scene back as it was. Until then, saving the file "
                "saves what is shown")

    @classmethod
    def poll(cls, context):
        return compare.active() is not None

    def execute(self, context):
        try:
            compare.active().end(context.scene, keep=self.keep)
        except (RuntimeError, formats.FormatError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_ghost_toggle(bpy.types.Operator):
    bl_idname = "whittle.ghost_toggle"
    bl_label = "Ghost"
    bl_description = "Show the node before the current one as a wireframe ghost, or hide it"

    @classmethod
    def poll(cls, context):
        if compare.ghost_node() is not None:
            return True
        hist = history.active()
        return (hist is not None and hist.tree is not None
                and hist.tree.node(hist.current).parent is not None)

    def execute(self, context):
        try:
            toggle_ghost(context)
        except (RuntimeError, formats.FormatError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_chat_new(bpy.types.Operator):
    bl_idname = "whittle.chat_new"
    bl_label = "New Chat"
    bl_description = ("Start an empty chat: a new conversation and history from the scene as it is, "
                      "with a fresh Claude session. The scene is not changed")

    @classmethod
    def poll(cls, context):
        reason = can_new_chat(chats.get(), turn.current())
        if reason:
            cls.poll_message_set(reason)
        return reason is None

    def execute(self, context):
        try:
            new_chat(context)
        except (RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_chat_switch(bpy.types.Operator):
    bl_idname = "whittle.chat_switch"
    bl_label = "Switch Chat"
    bl_description = ("Go back to this chat: its conversation, and its Claude session for the next "
                      "turn. The scene stays as it is")

    chat: StringProperty(name="Chat", default="", options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, properties):
        found = chats.get()
        if found is None or properties.chat not in found:
            return cls.bl_description
        named = f"{found.entry(properties.chat).title} · {chat_summary(found, properties.chat)}"
        return f"{named}\n{cls.bl_description}"

    @classmethod
    def poll(cls, context):
        reason = chat_blocker(turn.current())
        if reason:
            cls.poll_message_set(reason)
        return reason is None

    def execute(self, context):
        try:
            switch_chat(context, self.chat)
        except (RuntimeError, KeyError, OSError, formats.FormatError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_chat_rename(bpy.types.Operator):
    bl_idname = "whittle.chat_rename"
    bl_label = "Rename Chat"
    bl_description = "Give this chat a title of your own; an empty one puts back the title from its first prompt"

    title: StringProperty(name="Title", default="", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        found = chats.get()
        return found is not None and found.current is not None and bool(found.entry(found.current).turns)

    def invoke(self, context, event):
        found = chats.get()
        self.title = found.entry(found.current).title
        return context.window_manager.invoke_props_dialog(self, title="Rename Chat", confirm_text="Rename")

    def draw(self, context):
        self.layout.prop(self, "title", text="")

    def execute(self, context):
        try:
            rename_chat(context, self.title)
        except (RuntimeError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class WHITTLE_OT_chat_delete(bpy.types.Operator):
    bl_idname = "whittle.chat_delete"
    bl_label = "Delete Chat"
    bl_description = ("Delete this chat: its history, transcripts, renders and Claude session. "
                      "It leaves this file the next time you save. The scene is not changed")

    chat: StringProperty(name="Chat", default="", options={"SKIP_SAVE"})

    def invoke(self, context, event):
        found = chats.get()
        if found is None or self.chat not in found:
            return {"CANCELLED"}
        entry = found.entry(self.chat)
        # Blender does not wrap this dialog's message, so it stays short and
        # the chat goes in the title.
        message = (f"{chat_summary(found, self.chat)}, {chat_store.size_label(entry.size)}. "
                   "It leaves this file the next time you save.")
        return context.window_manager.invoke_confirm(self, event, title=f"Delete \"{entry.title}\"?", message=message,
                                                     confirm_text="Delete", icon="WARNING")

    def execute(self, context):
        try:
            delete_chat(context, self.chat)
        except (RuntimeError, KeyError, OSError, formats.FormatError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


DELETE_CHOICES = [("OTHERS", "All Other Chats", "Every chat but this one"),
                  ("WEEK", "Older Than a Week", "Chats whose last turn is over a week old"),
                  ("MONTH", "Older Than a Month", "Chats whose last turn is over a month old"),
                  ("QUARTER", "Older Than 3 Months", "Chats whose last turn is over three months old")]


class WHITTLE_OT_chat_delete_many(bpy.types.Operator):
    bl_idname = "whittle.chat_delete_many"
    bl_label = "Delete Chats"
    bl_description = "Delete the other chats in this file, or those older than a week, a month or three months"

    which: EnumProperty(name="Which", items=DELETE_CHOICES, default="MONTH")

    @classmethod
    def poll(cls, context):
        found = chats.get()
        return found is not None and bool(found.to_delete("OTHERS"))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, title="Delete Chats", confirm_text="Delete")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "which")
        found = chats.get()
        doomed = found.to_delete(self.which) if found is not None else []
        col = layout.column(align=True)
        col.active = False
        if not doomed:
            col.label(text="No chat is that old.")
            return
        size = sum(found.entry(c).size for c in doomed)
        col.label(text=f"{chat_store.delete_label(len(doomed), size)} This chat stays.")
        col.label(text="They leave this file the next time you save.")

    def execute(self, context):
        try:
            gone = delete_chats(context, self.which)
        except (RuntimeError, KeyError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Deleted {len(gone)} chat{'' if len(gone) == 1 else 's'}")
        return {"FINISHED"}


CLASSES = (WHITTLE_OT_sketch, WHITTLE_OT_sketch_toggle, WHITTLE_OT_sketch_stop, WHITTLE_OT_stroke_type,
           WHITTLE_OT_next_stroke_type, WHITTLE_OT_capture_view, WHITTLE_OT_submit,
           WHITTLE_OT_clear_sketch, WHITTLE_OT_ref_add, WHITTLE_OT_ref_remove,
           WHITTLE_OT_run_bundle, WHITTLE_OT_agent_start, WHITTLE_OT_agent_stop,
           WHITTLE_OT_interrupt, WHITTLE_OT_amend, WHITTLE_OT_answer, WHITTLE_OT_open_image,
           WHITTLE_OT_open_transcript, WHITTLE_OT_target_from_selection, WHITTLE_OT_target_add,
           WHITTLE_OT_target_remove, WHITTLE_OT_target_clear, WHITTLE_OT_view_remove, WHITTLE_OT_view_snap,
           WHITTLE_OT_history_restore, WHITTLE_OT_history_branch, WHITTLE_OT_history_compare,
           WHITTLE_OT_branch_switch, WHITTLE_OT_retry, WHITTLE_OT_compare_toggle, WHITTLE_OT_compare_end, WHITTLE_OT_ghost_toggle,
           WHITTLE_OT_chat_new, WHITTLE_OT_chat_switch, WHITTLE_OT_chat_rename, WHITTLE_OT_chat_delete,
           WHITTLE_OT_chat_delete_many)
