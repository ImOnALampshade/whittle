# SPDX-License-Identifier: GPL-3.0-or-later
"""The GUI checks by name: what each one confirms, and its phases. Stdlib
only: the driver reads it outside Blender.

A check runs one GUI Blender per phase, one after another, in the same work
folder and Whittle user folder, so a later phase sees what an earlier one
saved, autosaved or left in the cache. Each phase opens a file: "base.blend"
is a copy of the factory startup file; any other name must have been saved
by an earlier phase."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    # The .blend in the work folder the Blender opens.
    open: str = "base.blend"
    # Seconds the phase may take inside Blender before it counts as failed.
    deadline: float = 90.0


@dataclass(frozen=True)
class Check:
    description: str
    phases: tuple = (Phase(),)


CHECKS = {
    "restart_resume": Check(
        "Save and quit after a turn, reopen through File > Open: the conversation and the history "
        "are the saved ones, the title bar has no '*', and the next turn resumes the agent's "
        "session (no context-lost note).",
        (Phase(), Phase())),
    "blank_sketch": Check(
        "Start Blank with the default cube selected: nothing added, the cube deselected and "
        "untouched, no target. Strokes drawn with the real draw tool stick to the cube's surface, "
        "and off it land on the view plane through the 3D cursor; the first turn's new objects "
        "become the targets."),
    "primitive_sketch": Check(
        "Start From Primitive (Cylinder) with the 3D cursor moved: it stands there, is the only "
        "target and is selected, Auto keeps it; a stroke drawn over it sticks to it."),
    "asset_browser": Check(
        "In a real Asset Browser, right-click an object asset from a library: the context menu has "
        "Start Whittle From Asset, which appends it at the 3D cursor as the target and leaves no "
        "library in the file."),
    "references_view": Check(
        "A reference placed Facing the View from a real, orbited viewport faces that view; Front, "
        "Right and Top place it behind the model from that side."),
    "undo_turn": Check(
        "Ctrl+Z pressed in the viewport while a turn runs takes the scene back to the turn's "
        "start, the conversation warns, and the agent is told with its next call's result."),
    "undo_compare": Check(
        "Ctrl+Z pressed during a comparison ends it without touching the scene the undo put back."),
    "modal_wait": Check(
        "While a real transform (G) runs in the viewport, the agent's scene calls wait; once the "
        "transform is confirmed they run, in order, and the turn finishes."),
    "save_as": Check(
        "File > Save As in a GUI session, during and after a turn: the turn carries on, the cache "
        "records the new path and keeps its id, the title bar has no '*', and the file left "
        "behind gets a cache of its own when opened."),
    "recover_autosave": Check(
        "Blender's own autosave after an unsaved turn, then a kill -9: File > Recover > Auto Save "
        "opens it with the original's chats, including the unsaved turn, and leaves the "
        "original's record alone.",
        (Phase(deadline=150.0), Phase())),
    "recover_last_session": Check(
        "Quit after an unsaved turn, then File > Recover > Last Session: quit.blend opens with "
        "the chats, the unsaved turn included.",
        (Phase(), Phase())),
    "crash_keeps_chats": Check(
        "Save, run a turn, kill -9 Blender, open the file again: the unsaved turn is in the "
        "conversation and the agent resumes its session.",
        (Phase(), Phase(open="scene.blend"))),
    "dirty_flag": Check(
        "Saving packs the chats into the file and opening takes them out again: neither leaves "
        "the title bar's '*' (bpy.data.is_dirty) set, in a GUI session.",
        (Phase(), Phase())),
    "sketch_undo": Check(
        "While sketching, Ctrl+Z takes back a stroke drawn with the real draw tool and stays in "
        "Draw Mode; a stroke drawn after it still sticks to the surface and gets its view; Stop "
        "Sketching puts the user's tool settings and Object Mode back."),
    "shortcut": Check(
        "Shift+Alt+C over the viewport opens the sidebar on Whittle's tab and a field under the "
        "pointer: typed text and Enter send a prompt when idle, amend the running turn, and answer "
        "Claude's question."),
    "auto_targets": Check(
        "With Auto on, clicking another object in the viewport makes it the target; clicking empty "
        "space keeps the active one; sketching keeps it; with Auto off a click leaves the list."),
    "branch_undo": Check(
        "Edit & Resend a turn as another branch, switch back to the first branch: its scene is back, "
        "and Ctrl+Z goes to the other branch again, the conversation with it."),
    "agent_crash": Check(
        "The agent process killed during a turn: the attention box offers Restart and Retry, which "
        "starts the agent again and sends the turn again."),
    "chats": Check(
        "New Chat and a turn, then back to the first chat: its conversation, the scene as it was, and "
        "Send resumes its session; Ctrl+S leaves no '*'; deleting the other chat from its trash icon "
        "(confirmed with Return) makes the next save smaller."),
    "file_carries_chats": Check(
        "Save two chats, quit, delete the file's cache, open the file: every chat is back with its "
        "turns, transcripts and pictures, Send resumes, and nothing but the .blend (and .blend1) is "
        "beside it.",
        (Phase(), Phase())),
    "compare_targets": Check(
        "At a turn whose targets are the crate and its lid, compare with an earlier turn without the "
        "lid, Swap, Done: both are targets again and selected, and Auto keeps them."),
    "references_turn": Check(
        "Two references added with the paperclip through the real file browser, one pinned; after a "
        "turn that succeeded only the pinned one stays."),
}

# The window every check runs in.
WINDOW = (1400, 1100)
