# SPDX-License-Identifier: GPL-3.0-or-later
"""Sphinx configuration for Whittle's documentation site.

The build runs offline and without Blender: everything the source imports that
is not in the standard library is mocked, and intersphinx stays off.
"""

import dataclasses
import re
import sys
import tomllib
from pathlib import Path

from sphinx.ext.autodoc.mock import _MockObject

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

MANIFEST = tomllib.loads((REPO / "whittle" / "blender_manifest.toml").read_text(encoding="utf-8"))

project = "Whittle"
author = MANIFEST["maintainer"]
copyright = f"2026, {author}. Licensed GPL-3.0-or-later"
version = release = MANIFEST["version"]

extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.napoleon", "sphinx.ext.viewcode"]

source_suffix = {".md": "markdown"}
root_doc = "index"
# shots/ holds the screenshot specs and their README, which are not pages.
exclude_patterns = ["shots", "requirements.*"]

myst_enable_extensions = ["attrs_inline", "colon_fence", "deflist", "tasklist"]
myst_heading_anchors = 3

html_theme = "sphinx_book_theme"
html_title = "Whittle"
html_theme_options = {
    "repository_url": MANIFEST["website"],
    "path_to_docs": "docs/site",
    "use_repository_button": True,
    "show_toc_level": 2,
    # The sidebar has its own search box; this would add a second above it.
    "navbar_persistent": [],
}

autodoc_mock_imports = ["bpy", "bmesh", "mathutils", "gpu", "gpu_extras", "blf", "bpy_extras",
                        "claude_agent_sdk", "numpy"]
autodoc_typehints = "description"
autodoc_member_order = "bysource"
# The API pages hold over a thousand objects: their sidebars list the modules.
toc_object_entries = False

# Docstrings in the source use single backticks for code.
default_role = "code"
# They also quote JSON and command-line flags in plain prose, which smart quotes
# would turn into curly quotes and dashes that no longer work when copied.
smartquotes = False
# A block names its language; one that does not is plain text, not Python.
highlight_language = "text"


def literal_blocks(app, what, name, obj, options, lines):
    """Show a module docstring's hand-aligned tables as preformatted text.

    The source lays out file formats and script steps in plain text, which
    reStructuredText would take for block quotes and definition lists. An
    indented run under a paragraph becomes a literal block, unless it only
    continues a list item.
    """
    if what != "module":
        return
    i = 0
    while i < len(lines):
        if not lines[i].startswith(" "):
            i += 1
            continue
        blank_before = not lines[i - 1].strip()
        lead = i - 2 if blank_before else i - 1
        end = i
        while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
            end += 1
        if re.match(r"(-|\*|\d+\.) ", lines[lead]):
            i = end
            continue
        if end < len(lines) and lines[end - 1].strip():
            lines.insert(end, "")
        if not blank_before:
            lines.insert(i, "")
            end += 1
        lines[lead] = lines[lead].rstrip() + (":" if lines[lead].rstrip().endswith(":") else " ::")
        i = end + 1


def drop_mock_constructor(app, what, name, obj, options, args, retann):
    """Show a class built on a mocked Blender type without the mock's constructor.

    Such a class inherits `(*args, **kwargs)` and its type hints from the mock,
    which describe nothing about the class. Blender makes these itself.
    """
    if what in ("class", "exception") and obj.__init__ is _MockObject.__init__:
        app.env.current_document.autodoc_annotations.pop(name, None)
        return "", None
    return None


def short_dataclass_signature(app, what, name, obj, options, args, retann):
    """Name a dataclass's required fields; the full list is the entries under it.

    The generated signature prints every default, with memory addresses for
    the factories, so it reads badly and differs from build to build.
    """
    if what != "class" or not dataclasses.is_dataclass(obj):
        return None
    fields = [f for f in dataclasses.fields(obj) if f.init]
    required = [f.name for f in fields if f.default is dataclasses.MISSING
                and f.default_factory is dataclasses.MISSING]
    return f"({', '.join(required + (['...'] if len(required) < len(fields) else []))})", None


def drop_dataclass_doc(app, what, name, obj, options, lines):
    """Drop the signature dataclass writes as __doc__ when a class has no docstring."""
    if what == "class" and dataclasses.is_dataclass(obj) and "".join(lines).startswith(f"{obj.__name__}("):
        lines.clear()


def setup(app):
    app.connect("autodoc-process-docstring", literal_blocks)
    app.connect("autodoc-process-signature", short_dataclass_signature)
    app.connect("autodoc-process-docstring", drop_dataclass_doc)
    # After autodoc's own handler, which records the annotations this drops.
    app.connect("autodoc-process-signature", drop_mock_constructor, priority=900)
