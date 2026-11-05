# SPDX-License-Identifier: GPL-3.0-or-later
"""What a docs page's shot spec is written with, and how it is read. A spec
is docs/site/shots/<page-slug>.py and declares SHOTS. docs/site/shots/README.md
is the guide. Stdlib only: the driver and --check import specs outside
Blender, so a spec keeps its bpy imports inside its setup functions.

Shots with the same setup run in one Blender, on one continuing scene. A
setup is a generator over a stage (tests/docshots/harness.py's DocStage):
it yields a number to wait, an Until to wait for a condition, or a Snap to
shoot named shots there and then; a shot no Snap names is shot when the
setup ends."""

import importlib.util
import inspect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from tests.screens import catalog
from tests.screens.steps import (BEVEL_AND_LID, DARKEN, DARKER_WOOD_LIGHTER_LID, HORNS, LID,  # noqa: F401
                                 METAL_BANDS, METAL_HANDLES, ROPE_HANDLES, SLOT, Popup, Until, done, exec_,
                                 render, say)

REPO = Path(__file__).resolve().parents[2]
SHOTS_DIR = REPO / "docs" / "site" / "shots"
FAKE_DIR = SHOTS_DIR / "fake"
FIXTURES = REPO / "tests" / "fixtures" / "fake"

# The two windows every shot runs in. Tall suits the sidebar, whose panels
# then mostly fit without scrolling; wide is a desktop's proportions, for
# what shows the viewport.
TALL = catalog.WINDOW
WIDE = (1600, 1000)
# The hidden session must have room for them.
OUTPUT = (1600, 2200)

KINDS = ("sidebar", "viewport", "window", "region", "popup", "preferences")
SECTIONS = ("INTERFACE", "VIEWPORT", "LIGHTS", "EDITING", "ANIMATION", "EXTENSIONS", "ADDONS", "THEMES", "ASSETS",
            "INPUT", "NAVIGATION", "KEYMAP", "SYSTEM", "SAVE_LOAD", "FILE_PATHS", "DEVELOPER_TOOLS", "EXPERIMENTAL")
DEFAULT_DEADLINE = 150.0
PER_SHOT = 30.0
MAX_DEADLINE = 900.0

SHOT_NAME = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
PAGE_SLUG = re.compile(r"_?[a-z0-9][a-z0-9-]*\Z")


# -- what to capture ----------------------------------------------------------

@dataclass(frozen=True)
class Capture:
    kind: str
    # (x, y, width, height) in pixels from the image's top left corner.
    crop: tuple | None = None
    # region: an area's type, one of its regions, or a box in window pixels.
    area: str = ""
    part: str = "WINDOW"
    box: tuple | None = None
    # window: the window holding an area of this type, not the main one.
    of: str = ""
    # popup and preferences: what to open.
    popup: Popup | None = None
    # preferences
    section: str = "ADDONS"
    scroll: int = 0
    full: bool = False
    search: str = ""


def sidebar(crop=None) -> Capture:
    """The Whittle sidebar, scrolled and stitched to its whole length."""
    return Capture("sidebar", crop=crop)


def viewport(crop=None) -> Capture:
    """The 3D viewport's main region."""
    return Capture("viewport", crop=crop)


def window(crop=None, of: str = "") -> Capture:
    """The whole window; with of, the window holding that kind of area
    (FILE_BROWSER, say) once a setup has opened it."""
    return Capture("window", crop=crop, of=of)


def region(area: str = "", part: str = "WINDOW", box=None) -> Capture:
    """A piece of the window: an area by its type (OUTLINER, PROPERTIES,
    DOPESHEET_EDITOR, ...), one of its regions (part: HEADER, ...), or box,
    (x, y, width, height) from the window's top left corner."""
    return Capture("region", area=area, part=part, box=box)


def _popup(panel, menu, operator, props) -> Popup | None:
    if panel:
        return Popup("panel", panel)
    if menu:
        return Popup("operator", "wm.call_menu", {"name": menu})
    if operator:
        return Popup("operator", operator, props)
    return None


def popup(panel: str = "", menu: str = "", operator: str = "", props=None, crop=None) -> Capture:
    """A popover, menu or dialog opened over the sidebar, cropped to it. With
    none named, the setup says: Snap(name, popup=...), or return a Popup."""
    return Capture("popup", crop=crop, popup=_popup(panel, menu, operator, props))


def preferences(section: str = "ADDONS", scroll: int = 0, full: bool = False, search: str = "", crop=None,
                menu: str = "", operator: str = "", props=None) -> Capture:
    """The Preferences window on a section. ADDONS shows Whittle's own
    preferences, expanded, as the sidebar's Preferences... button does. By
    default the window as Blender opens it, scrolled down scroll wheel steps;
    with full the section's whole length without the navigation column; with
    menu or operator what that opens over the window, cropped to it. search
    goes in the section's search field (KEYMAP and EXTENSIONS)."""
    return Capture("preferences", crop=crop, section=section, scroll=scroll, full=full, search=search,
                   popup=_popup("", menu, operator, props))


def clamp(box, width: int, height: int) -> tuple[int, int, int, int]:
    """A box inside a width x height image: one running off the image's right
    or bottom edge stops at it, one that starts outside it is an error."""
    x, y, w, h = box
    if x >= width or y >= height or w < 1 or h < 1:
        raise ValueError(f"the box {tuple(box)} is outside the {width}x{height} image")
    return x, y, min(w, width - x), min(h, height - y)


class Snap:
    """Yielded by a setup: shoot these shots now, then carry on. popup, for
    a popup() capture, says what to open."""

    def __init__(self, *names: str, popup: Popup | None = None):
        self.names = names
        self.popup = popup


# -- shots --------------------------------------------------------------------

@dataclass(frozen=True)
class Shot:
    name: str
    description: str
    capture: Capture | None = None
    # How to reach the state: one of the two (preferences() needs neither).
    scenario: str = ""
    setup: object = None
    # The sidebar's width as a factor of its default.
    wide: float = 0.0
    # Whittle's closed-by-default panels start open.
    open_panels: bool = False
    # Seconds the Blender may take, beyond the default for its shots.
    deadline: float = 0.0


def turns(script: str, *prompts: str, pick: bool = True):
    """A setup: the crate, then each prompt as a turn of the fake script."""
    def setup(stage):
        stage.crate(pick=pick)
        yield from stage.turns(list(prompts), stage.fake(script))
    return setup


@dataclass
class Group:
    """The shots that run in one Blender."""
    index: int
    label: str
    shots: list = field(default_factory=list)

    @property
    def source(self) -> Shot:
        return self.shots[0]

    @property
    def window(self) -> tuple[int, int]:
        if self.source.scenario in catalog.WINDOWS:
            return catalog.WINDOWS[self.source.scenario][0]
        wide = any(s.capture is not None and s.capture.kind in ("viewport", "window", "region") for s in self.shots)
        return WIDE if wide else TALL

    @property
    def wide(self) -> float:
        for shot in self.shots:
            if shot.wide:
                return shot.wide
        return catalog.window(self.source.scenario)[1]

    @property
    def open_panels(self) -> bool:
        return any(s.open_panels for s in self.shots)

    @property
    def deadline(self) -> float:
        extra = sum(s.deadline for s in self.shots)
        return min(MAX_DEADLINE, DEFAULT_DEADLINE + PER_SHOT * (len(self.shots) - 1) + extra)


def groups(shots) -> list[Group]:
    """The spec's shots by the Blender each runs in, in order of appearance."""
    found: dict = {}
    for shot in shots:
        key = shot.scenario or id(shot.setup)
        if key not in found:
            label = shot.scenario or getattr(shot.setup, "__name__", "preferences")
            found[key] = Group(len(found), label)
        found[key].shots.append(shot)
    return list(found.values())


# -- specs --------------------------------------------------------------------

@dataclass
class Spec:
    slug: str
    path: Path
    shots: list

    def fake(self, name: str) -> Path:
        """A fake script: the page's own, else one of tests/fixtures/fake."""
        own = FAKE_DIR / self.slug / name
        return own if own.is_file() or not (FIXTURES / name).is_file() else FIXTURES / name


def page_slug(doc: str) -> str:
    """The page's slug: guides/api-key is guides-api-key."""
    return doc.replace("/", "-")


def spec_paths(folder: Path = SHOTS_DIR, examples: bool = False) -> list[Path]:
    """Every spec in folder; those named _* only with examples."""
    paths = sorted(p for p in Path(folder).glob("*.py") if p.stem != "__init__")
    return paths if examples else [p for p in paths if not p.stem.startswith("_")]


def load(path: Path) -> Spec:
    """Imports a spec; what is wrong with it is left to validate()."""
    path = Path(path)
    module_spec = importlib.util.spec_from_file_location(f"docshots_{path.stem.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return Spec(path.stem, path, list(getattr(module, "SHOTS", [])))


def _size(value, what: str, length: int = 4) -> list[str]:
    ok = (isinstance(value, (tuple, list)) and len(value) == length
          and all(isinstance(n, int) and n >= 0 for n in value))
    return [] if ok else [f"{what} must be {length} whole numbers, not {value!r}"]


def _check_capture(capture: Capture) -> list[str]:
    errors = []
    if capture.kind not in KINDS:
        errors.append(f"capture kind {capture.kind!r} is not one of {', '.join(KINDS)}")
    if capture.crop is not None:
        errors += _size(capture.crop, "crop")
    if capture.kind == "region":
        if bool(capture.area) == (capture.box is not None):
            errors.append("region() takes an area or a box, one of the two")
        if capture.box is not None:
            errors += _size(capture.box, "box")
    if capture.kind == "preferences":
        if capture.section not in SECTIONS:
            errors.append(f"section {capture.section!r} is not one of {', '.join(SECTIONS)}")
        if capture.full and capture.popup is not None:
            errors.append("preferences() takes full or a menu, not both")
    return errors


def _check_shot(shot, scenarios) -> list[str]:
    if not isinstance(shot, Shot):
        return [f"{shot!r} is not a Shot"]
    errors = []
    if not SHOT_NAME.match(str(shot.name)):
        errors.append("a name is lower-case letters, digits and hyphens")
    description = shot.description
    if not isinstance(description, str) or not description.strip() or "\n" in description:
        errors.append("the description is one line of text")
    plain = isinstance(shot.capture, Capture) and shot.capture.kind == "preferences"
    if shot.scenario and shot.setup is not None:
        errors.append("a shot has a scenario or a setup, not both")
    if not shot.scenario and shot.setup is None and not plain:
        errors.append("a shot says how to reach its state: a scenario or a setup")
    if shot.scenario and shot.scenario not in scenarios:
        errors.append(f"there is no scenario {shot.scenario!r} (tests/screens/catalog.py)")
    if shot.setup is not None:
        if not callable(shot.setup):
            errors.append(f"setup {shot.setup!r} is not a function")
        elif len(inspect.signature(shot.setup).parameters) != 1:
            errors.append("a setup takes one argument, the stage")
        if shot.capture is None:
            errors.append("a setup's shot says what to capture")
    if shot.capture is not None:
        errors += _check_capture(shot.capture) if isinstance(shot.capture, Capture) else \
            [f"capture {shot.capture!r} is not sidebar(), viewport(), window(), region(), popup() or preferences()"]
    if not isinstance(shot.wide, (int, float)) or not (shot.wide == 0 or 1.0 <= shot.wide <= 3.0):
        errors.append(f"wide is a factor from 1 to 3, not {shot.wide!r}")
    if not isinstance(shot.deadline, (int, float)) or shot.deadline < 0:
        errors.append(f"deadline {shot.deadline!r} is not a number of seconds")
    return [f"{shot.name}: {e}" for e in errors] if hasattr(shot, "name") else errors


def _check_group(group: Group) -> list[str]:
    errors = []
    factors = {s.wide for s in group.shots if s.wide}
    if len(factors) > 1:
        errors.append(f"{group.label}: the shots of one setup share one sidebar width, not {sorted(factors)}")
    return errors


def _check_script(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return [f"{path.name}: not JSON: {exc}"]
    if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
        return [f"{path.name}: a fake script is an object with a list of turns"]
    return []


def validate(spec: Spec, scenarios=None) -> list[str]:
    """What is wrong with a spec, without starting Blender."""
    scenarios = catalog.SCENARIOS if scenarios is None else scenarios
    errors = []
    if not PAGE_SLUG.match(spec.slug):
        errors.append(f"{spec.path.name}: the file is named after the page's slug")
    if not spec.shots:
        errors.append("SHOTS is missing or empty")
    for shot in spec.shots:
        errors += _check_shot(shot, scenarios)
    names = [s.name for s in spec.shots if isinstance(s, Shot)]
    errors += [f"{name}: two shots have this name" for name in sorted({n for n in names if names.count(n) > 1})]
    if not errors:
        for group in groups(spec.shots):
            errors += _check_group(group)
    source = spec.path.read_text() if spec.path.is_file() else ""
    # Names a setup uses as literals, caught before a Blender is started.
    for name in re.findall(r"\bSnap\(\s*[\"']([^\"']+)", source):
        if name not in names:
            errors.append(f"Snap({name!r}) names no shot in SHOTS")
    for name in re.findall(r"(?:\.fake|\bturns)\(\s*[\"']([^\"']+)", source):
        if not spec.fake(name).is_file():
            errors.append(f"there is no fake script {name!r} in {FAKE_DIR.relative_to(REPO) / spec.slug}")
    for path in sorted((FAKE_DIR / spec.slug).glob("*.json")):
        errors += _check_script(path)
    return errors
