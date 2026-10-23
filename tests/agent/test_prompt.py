# SPDX-License-Identifier: GPL-3.0-or-later
import json
import unittest

from whittle.agent import prompt


class PromptTest(unittest.TestCase):
    def test_every_skill_has_matching_frontmatter(self):
        dirs = sorted(p.name for p in (prompt.PLUGIN_DIR / "skills").iterdir() if p.is_dir())
        self.assertEqual(dirs, sorted(prompt.SKILLS))
        for name in prompt.SKILLS:
            with self.subTest(skill=name):
                meta, body = prompt.parse_skill(prompt.skill_path(name).read_text(encoding="utf-8"))
                self.assertEqual(meta.get("name"), name)
                self.assertGreater(len(meta.get("description", "")), 40)
                self.assertIn("```python", body)
                self.assertNotIn("---", prompt.load_skill(name).splitlines()[0])

    def test_plugin_manifest(self):
        manifest = json.loads((prompt.PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], prompt.PLUGIN_NAME)
        self.assertTrue(manifest["version"])
        self.assertTrue(manifest["description"])

    def test_settings_are_substituted(self):
        text = prompt.build({"poly_budget": 321, "self_check_rounds": 5, "style_notes": "Chunky bevels."})
        self.assertIn("321 triangles", text)
        self.assertIn("at most 5 fix rounds", text)
        self.assertIn("Chunky bevels.", text)
        self.assertNotIn("$", text.replace("$self", ""), "no placeholder left unfilled")

    def test_defaults(self):
        text = prompt.build(None)
        self.assertIn(f"{prompt.DEFAULTS['poly_budget']} triangles", text)
        self.assertIn("No extra style notes", text)

    def test_conventions_are_present(self):
        text = prompt.build({})
        for phrase in ("1 Blender unit is 1 metre", "intent, not exact geometry", "| carve |",
                       "Never touch other objects", "mcp__whittle__request", "Whittle Sketch",
                       "User amendment", "amend=<n>", "Writing to the user", "Don't narrate", "Whittle References",
                       "z = 0", "1 m", "<user_amendment>", "<whittle_context>", "system reminders"):
            self.assertIn(phrase, text)

    def test_modeling_practice_is_present(self):
        text = prompt.build({})
        for phrase in ("whittle.mesh_report(obj)", "whittle.weld(obj)", "one closed shell",
                       "Don't fake a join", "self-intersections", "What stays separate",
                       "live or baked", "Quads where it matters", "Voxel remesh",
                       "loose guide", "whittle:fuse-parts", "whittle:mesh-check"):
            self.assertIn(phrase, text)

    def test_practices_are_judgment_not_shouted_rules(self):
        text = prompt.build({}, inline_skills=True)
        self.assertNotIn("[[Q", text, "no draft question left in")
        for word in ("MUST", "ALWAYS", "NEVER"):
            self.assertNotIn(word, text)
        self.assertNotIn("low-poly, hard-surface", text, "the default style is general purpose")

    def test_mesh_skills_are_registered(self):
        self.assertIn("mesh-check", prompt.SKILLS)
        self.assertIn("fuse-parts", prompt.SKILLS)
        self.assertIn("whittle.mesh_report", prompt.load_skill("mesh-check"))

    def test_inline_mode_contains_every_recipe(self):
        text = prompt.build({}, inline_skills=True)
        for name in prompt.SKILLS:
            self.assertIn(f"## Recipe: {name}", text)
            self.assertIn(prompt.load_skill(name)[:80], text)
        self.assertNotIn("Skill tool", text)
