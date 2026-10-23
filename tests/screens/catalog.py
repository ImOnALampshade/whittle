# SPDX-License-Identifier: GPL-3.0-or-later
"""The screenshot scenarios by name, with the one-line description of the
state each shows. Stdlib only: the driver reads it outside Blender."""

SCENARIOS = {
    "empty": "A fresh file with the crate: nothing picked, no agent, no history yet.",
    "start": "A new file (the default cube scene) offering the start points.",
    "prompt_typed": "The crate selected (so targeted) and a prompt typed, nothing sent yet.",
    "shortcut_popup": "The Shift+Alt+C popup under the pointer, its prompt field editing a half-typed prompt.",
    "prompt_only_done": "One finished prompt-only turn (no sketch): text, tool calls and renders.",
    "sketching": "Sketch mode on with add and carve strokes drawn from two views, prompt typed.",
    "view_markers": "The viewport while sketching: a marker where each of two views was captured, "
                    "the current one in orange (a viewport shot, not the sidebar).",
    "streaming": "Mid-turn: assistant text and finished tool calls, two more calls in flight.",
    "conversation": "Three finished turns with tool calls and render thumbnails.",
    "markdown": "A reply in Markdown: a heading, bold and italic, nested and numbered lists, a quote and code.",
    "markdown_stress": "A Markdown stress test: every heading level, styles, escapes, tasks, quotes, code, "
                       "a table, maths, HTML, emoji, links and footnotes.",
    "branched": "A node with two alternative branches, the second branch current.",
    "branch_edit": "After Edit & Resend on a turn: back before it, its prompt in the prompt box.",
    "asking": "A turn paused on a question from the agent with choices.",
    "interrupted": "A turn interrupted mid-way and kept partial.",
    "error_turn": "A turn whose tool call failed and then recovered, then a turn that failed.",
    "folded_failure": "A turn that failed without changing anything, shown once with Retry.",
    "crashed": "The agent crashed during a turn: the attention box offers Restart and Retry.",
    "setup_needed": "No agent environment: the attention box offers to set one up.",
    "key_needed": "No API key: Send started nothing, the prompt stays and the attention box asks for a key.",
    "comparing": "Comparing the current scene with an earlier turn.",
    "manual_targets": "Auto off: two objects picked by hand as the target, a third selected.",
    "long_session": "Thirteen finished turns, to check the panel does not grow without bound.",
    "history_popover": "The history popover over a 13-turn tree with two branches.",
    "turn_menu": "The menu of an earlier turn, opened from its ⋯ button.",
    "agent_popover": "The agent popover: this file's self-check rounds, palette, bevel style and style notes set, "
                     "its triangle budget and render size the defaults.",
    "references": "Two reference images attached, one of them pinned.",
    "developer": "Developer Extras on, with the development tools shown after a turn.",
    "chat_menu": "The chat menu over three chats, the second-newest current.",
    "chat_menu_many": "The chat menu over 25 chats of every age and size: 20 listed, then Show 5 More.",
    "new_chat": "After New Chat: an empty chat in the header, the start row, the scene as it was.",
    "switched_chat": "Switched back to an earlier chat: its conversation, the scene as the other chat left it.",
    "continue_chat": "A chat made on another machine: read-only, a box asks to Continue it, Send disabled.",
    "open_elsewhere": "The same file open in another Blender: a quiet line says its chats won't merge.",
    "delete_confirm": "The confirmation of deleting a chat from its trash icon.",
    "delete_many": "The Delete Chats dialog on Older Than a Month.",
    "model_menu": ("The model menu from the button beside Send: the newest of each family, Sonnet 5.5 checked, "
                   "and the Effort section with High checked."),
    "hero": ("The whole window: a crate built over three turns in matcap shading, the next request "
             "sketched over it with a stroke of every kind, the sidebar in sketch mode."),
    "model_menu_older": "The Older Models submenu, one column per family, with the chat on Opus 4.6.",
}

# Scenarios also shot with the sidebar widened to this factor of its default
# width, into wide/<scenario>.png.
WIDE = ("conversation", "markdown", "long_session")
WIDE_FACTOR = 1.6

# The window every scenario runs in: tall, so most panels fit without
# scrolling; the harness scrolls and stitches the ones that do not.
WINDOW = (1400, 2000)

# Scenarios shot in a window of their own size, with the sidebar widened to
# a factor of its default width (1.0 leaves it).
WINDOWS = {"hero": ((1600, 1000), 1.5)}


def window(name: str) -> tuple[tuple[int, int], float]:
    """The window size and sidebar factor a scenario runs with."""
    return WINDOWS.get(name, (WINDOW, 1.0))


# The README's images, docs/images/<name>.png, by the shot each is copied
# from (wide/ for the widened sidebar): ./screens.sh --docs makes them.
DOCS = {
    "hero": "hero",
    "conversation": "wide/conversation",
    "sketching": "sketching",
    "markdown": "wide/markdown",
    "chat-menu": "chat_menu",
    "model-menu": "model_menu",
}
