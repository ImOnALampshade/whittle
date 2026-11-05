# SPDX-License-Identifier: GPL-3.0-or-later
"""The documentation site's source stays whole: every module is documented,
every page is reachable, and what the pages point at exists. Reads the files
only, so it needs no Sphinx; ./docs.sh --strict checks what they render to."""
import re
import unittest
from pathlib import Path

from tests.docshots import spec as shots

REPO = Path(__file__).resolve().parents[2]
SITE = REPO / "docs" / "site"
REFERENCE_PAGES = ("addon", "agent", "shared")
API_MARKER = "<!-- api -->"
AUTOMODULE = re.compile(r"\.\. automodule:: (\S+)((?:\n +:[\w-]+:.*)*)")
TOCTREE = re.compile(r"^(`{3,}|:{3,})\{toctree\}[^\n]*\n(.*?)^\1\s*$", re.M | re.S)
IMAGES = (re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)"),
          re.compile(r"^ *(?:`{3,}|:{3,})\{(?:image|figure)\} +(\S+)", re.M),
          re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)"))
REQUIREMENT = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)==([^\s=]+)((?: +--hash=sha256:[0-9a-f]{64})+)")


def pages() -> dict[str, Path]:
    """Every page by its doc name; shots/ is excluded in conf.py."""
    found = {}
    for path in SITE.rglob("*.md"):
        doc = path.relative_to(SITE).with_suffix("").as_posix()
        if not doc.startswith("shots/"):
            found[doc] = path
    return found


def module_name(path: Path) -> str:
    parts = path.relative_to(REPO).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def toctree_entries(doc: str, text: str) -> list[str]:
    """The docs a page's toctrees name, resolved from the page's folder."""
    folder = Path(doc).parent
    entries = []
    for _fence, body in TOCTREE.findall(text):
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            target = re.search(r"<([^>]+)>$", line)
            target = target.group(1) if target else line
            target = target.removesuffix(".md")
            entries.append(target.lstrip("/") if target.startswith("/") else (folder / target).as_posix())
    return entries


def image_paths(path: Path) -> list[Path]:
    """The local files a page shows, resolved the way Sphinx does."""
    text = path.read_text(encoding="utf-8")
    found = []
    for pattern in IMAGES:
        for target in pattern.findall(text):
            if not re.match(r"[a-z]+:", target):
                base = SITE if target.startswith("/") else path.parent
                found.append((base / target.lstrip("/")).resolve())
    return found


def requirements(path: Path) -> list[str]:
    """The lock's or the .in's requirements, one string each."""
    text = re.sub(r"\\\n", " ", path.read_text(encoding="utf-8"))
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


class ReferenceTest(unittest.TestCase):
    def automodules(self) -> dict[str, list[tuple[str, str]]]:
        found = {}
        for name in REFERENCE_PAGES:
            found[name] = AUTOMODULE.findall((SITE / "reference" / f"{name}.md").read_text(encoding="utf-8"))
        return found

    def test_every_module_is_in_a_reference_page_once(self):
        modules = {module_name(p) for p in (REPO / "whittle").rglob("*.py")}
        listed = [module for entries in self.automodules().values() for module, _options in entries]
        self.assertEqual(sorted(listed), sorted(modules))

    def test_every_module_shows_all_its_members(self):
        for entries in self.automodules().values():
            for module, options in entries:
                for option in (":members:", ":undoc-members:", ":show-inheritance:"):
                    self.assertIn(option, options, module)

    def test_the_marker_separates_the_intro_from_the_api(self):
        for name in ("index", *REFERENCE_PAGES):
            text = (SITE / "reference" / f"{name}.md").read_text(encoding="utf-8")
            self.assertEqual(text.count(API_MARKER), 1, name)
            self.assertNotIn("automodule", text.split(API_MARKER)[0], name)


class PagesTest(unittest.TestCase):
    def test_every_page_is_in_a_toctree(self):
        found = pages()
        linked = set()
        for doc, path in found.items():
            linked.update(toctree_entries(doc, path.read_text(encoding="utf-8")))
        self.assertEqual(sorted(set(found) - linked - {"index"}), [])

    def test_every_toctree_entry_is_a_page(self):
        found = pages()
        for doc, path in found.items():
            for entry in toctree_entries(doc, path.read_text(encoding="utf-8")):
                self.assertIn(entry, found, f"{doc} lists it")

    def test_every_image_a_page_shows_exists(self):
        for doc, path in pages().items():
            for image in image_paths(path):
                self.assertTrue(image.is_file(), f"{doc} shows {image}")

    def test_every_shot_is_shown_on_its_page(self):
        by_slug = {shots.page_slug(doc): path for doc, path in pages().items()}
        for spec_path in shots.spec_paths():
            spec = shots.load(spec_path)
            self.assertIn(spec.slug, by_slug, f"{spec_path.name} is named after no page")
            shown = image_paths(by_slug[spec.slug])
            for shot in spec.shots:
                image = SITE / "images" / spec.slug / f"{shot.name}.png"
                self.assertIn(image.resolve(), shown, f"{spec.slug} never shows {shot.name}")


class LockTest(unittest.TestCase):
    def test_every_package_is_an_exact_pin_with_hashes(self):
        lines = requirements(SITE / "requirements.lock")
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, f"^{REQUIREMENT.pattern}$")

    def test_each_package_is_pinned_once(self):
        names = [REQUIREMENT.match(line).group(1) for line in requirements(SITE / "requirements.lock")]
        self.assertEqual(len(names), len(set(names)))

    def test_the_direct_packages_are_pinned_to_the_locked_versions(self):
        locked = {m.group(1): m.group(2) for m in map(REQUIREMENT.match, requirements(SITE / "requirements.lock"))}
        direct = requirements(SITE / "requirements.in")
        self.assertTrue(direct)
        for line in direct:
            name, _, version = line.partition("==")
            self.assertEqual(locked.get(name), version, line)

    def test_docs_packages_stay_out_of_the_agents_lock(self):
        agent = (REPO / "agent_env" / "requirements.lock").read_text(encoding="utf-8")
        for line in requirements(SITE / "requirements.in"):
            self.assertNotIn(f"\n{line.partition('==')[0]}==", agent)
