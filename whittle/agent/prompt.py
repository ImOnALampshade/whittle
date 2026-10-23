# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the system prompt from system_prompt.md and the session settings."""

import re
from pathlib import Path
from string import Template

HERE = Path(__file__).parent
PLUGIN_DIR = HERE / "plugin"
PLUGIN_NAME = "whittle"
SKILLS = [
    "mesh-check",
    "fuse-parts",
    "blockout-silhouette",
    "extrude-along-stroke",
    "boolean-carve",
    "bevel-crease",
    "mirror-array",
    "lathe-profile",
    "vertex-colour-paint",
    "gn-scatter",
]

DEFAULTS = {"self_check_rounds": 3, "poly_budget": 2000, "style_notes": "", "render_size": 512}

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def skill_path(name: str) -> Path:
    return PLUGIN_DIR / "skills" / name / "SKILL.md"


def parse_skill(text: str) -> tuple[dict, str]:
    """Splits SKILL.md into its frontmatter (simple key: value lines) and body."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, text[m.end():]


def load_skill(name: str) -> str:
    return parse_skill(skill_path(name).read_text(encoding="utf-8"))[1].strip()


def build(settings: dict | None = None, *, inline_skills: bool = False) -> str:
    values = {**DEFAULTS, **{k: v for k, v in (settings or {}).items() if v is not None}}
    style = values["style_notes"].strip() or "No extra style notes for this file."
    text = Template((HERE / "system_prompt.md").read_text(encoding="utf-8")).safe_substitute(
        self_check_rounds=values["self_check_rounds"],
        poly_budget=values["poly_budget"],
        render_size=values["render_size"],
        style_notes=style,
    )
    if inline_skills:
        recipes = "\n\n".join(f"## Recipe: {name}\n\n{load_skill(name)}" for name in SKILLS)
        text += ("\n\n# bpy recipes\n\nWorking code and pitfalls for one technique each, which you "
                 "would otherwise load as skills.\n\n" + recipes)
    else:
        text += ("\n\n# bpy recipes\n\nRecipe skills, loaded with the Skill tool, hold working code "
                 "and the pitfalls of one technique each: "
                 + ", ".join(f"{PLUGIN_NAME}:{n}" for n in SKILLS)
                 + ". Load the matching one before using a technique whose details you are unsure of; "
                 "it stays in the conversation once loaded.")
    return text + "\n"
