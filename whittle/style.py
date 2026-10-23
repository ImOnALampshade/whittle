# SPDX-License-Identifier: GPL-3.0-or-later
"""The style settings a file or the preferences give the agent: the bevel
styles the Bevel Style field suggests, and how the system prompt words the
palette, bevel style and style notes. Stdlib only: the add-on offers the
suggestions, the agent's prompt.build words them.

Bevel Style is free text with suggestions rather than a fixed list: the three
named styles cover most props and each is spelled out for the agent, while a
style of the user's own ("rounded corners only", "2 mm") reaches it as typed."""

# Suggested bevel style -> what the system prompt tells the agent it means.
BEVEL_STYLES = {
    "none": "none: crisp, unbevelled edges",
    "subtle": "subtle: narrow bevels on hard edges, just wide enough to catch the light",
    "chunky": "chunky: wide, clearly visible bevels that round edges and corners off, a stylised look",
}

NO_PALETTE = "none set; pick colours that suit the object and the prompt."
NO_BEVEL_STYLE = "none set; bevel where the shape and the style call for it."
NO_STYLE_NOTES = "none."


def palette_text(palette: str) -> str:
    return palette.strip() or NO_PALETTE


def bevel_text(bevel_style: str) -> str:
    """A suggested style spelled out; anything else as the user typed it."""
    text = bevel_style.strip()
    return BEVEL_STYLES.get(text.lower(), text) or NO_BEVEL_STYLE


def notes_text(style_notes: str) -> str:
    return style_notes.strip() or NO_STYLE_NOTES
