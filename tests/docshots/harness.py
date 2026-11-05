# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs one group of a page's shots inside a GUI Blender, then quits. Started
by tests/docshots/run.py as

    blender --enable-event-simulate ... base.blend --python tests/docshots/harness.py -- PLAN.json

Whittle is the extension installed in the run's own user folders, so the
Preferences show it and every shot is of what a user runs; `whittle` is an
alias of it, as in the GUI checks. The state machine is the screenshot
harness's (tests/screens/harness.py), which this extends: a setup can shoot
several times along the way, and there are more kinds of capture. Each shot
goes to shots/<name>.png in the work folder with a <name>.json beside it, which
is how the driver knows it is complete. Any failure exits with code 1."""

import inspect
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import addon_utils
import bpy

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.docshots import spec as specs  # noqa: E402
from tests.gui.alias import Alias  # noqa: E402

PACKAGE = "bl_ext.user_default.whittle"
# Where the Preferences say Whittle is installed: a run's folder would put
# this checkout's path in the docs, and differ from run to run.
SHOWN_FILE = "/home/you/.config/blender/5.2/extensions/user_default/whittle/__init__.py"
AGENT_VARIABLE = "WHITTLE_AGENT_PYTHON"
AGENT = os.environ[AGENT_VARIABLE]


def refuse(why: str) -> None:
    print(f"docshots: refusing to run: {why}", file=sys.stderr, flush=True)
    os._exit(1)


def use_installed() -> None:
    """Checks that Blender's folders and the add-on running are the run's
    own, then imports it as `whittle` too."""
    config = Path(bpy.utils.user_resource("CONFIG")).resolve()
    own = os.environ.get("BLENDER_USER_CONFIG")
    if not own or config != Path(own).resolve():
        refuse(f"Blender's config is in {config}")
    if bpy.context.preferences.addons.get(PACKAGE) is None or PACKAGE not in sys.modules:
        refuse(f"{PACKAGE} is not enabled (tests/docshots/run.py installs it)")
    where = Path(sys.modules[PACKAGE].__file__).resolve()
    if not where.is_relative_to(Path(os.environ["BLENDER_USER_EXTENSIONS"]).resolve()):
        refuse(f"Whittle was loaded from {where}, not the run's own folders")
    Alias("whittle", PACKAGE).install()


try:
    use_installed()
    from tests.gui import checks  # noqa: E402
    from tests.screens import harness as base  # noqa: E402
    from tests.screens import scenarios  # noqa: E402
except Exception:
    refuse("the harness cannot import the installed Whittle:\n" + traceback.format_exc())

TICK = base.TICK
# What the pages of a stitched Preferences section leave out at each join:
# Blender draws a scroll arrow at a clipped edge.
EDGE = 24


class DocStage(checks.GuiStage):
    """What a setup gets: the screenshot scenarios' stage, the GUI checks'
    simulated input, and a few things of the docs' own."""

    def __init__(self, work: Path, spec: specs.Spec):
        super().__init__(work)
        self.spec = spec

    def fake(self, name: str) -> Path:
        """A fake script from docs/site/shots/fake/<page-slug>/, else from
        tests/fixtures/fake/."""
        path = self.spec.fake(name)
        if not path.is_file():
            raise FileNotFoundError(f"no fake script {name}: looked for {path}")
        return path

    @property
    def preferences(self):
        """Whittle's add-on preferences."""
        return checks.addon_preferences()

    def orbit(self, direction, distance: float, look_at=(0.0, 0.0, 0.28)) -> None:
        """Points the viewport at look_at from direction."""
        scenarios._orbit(self, direction, distance, look_at)

    def chat(self, name: str, prompts: list, new: bool = True):
        """A chat of nudge turns, as the chat scenarios make: yield from it."""
        return (yield from scenarios._chat(self, name, prompts, new=new))

    def age(self, chat: str, seconds: float) -> None:
        """Moves a chat's last turn back in time, so menus show a fixed age."""
        scenarios._age(chat, seconds)

    def agent_ready(self) -> None:
        """Whittle's own folder holds a finished setup, so the Preferences
        say Ready as they do for a user. (No shot installs anything: its
        python links to the dev venv's.)"""
        from whittle import venv
        from whittle.addon import setup

        folder = setup.venv_dir()
        python = venv.venv_python(folder)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.symlink_to(AGENT)
        lock = setup.lock_path()
        venv.write_marker(folder, lock, sdk=venv.read_pins(lock)[venv.SDK], base_python=Path(AGENT))


def window_pixels(win, path: Path):
    """A window's pixels, bottom row first. The Preferences' screen is a
    temporary one, which an override cannot name: the window brings its own."""
    area = max(win.screen.areas, key=lambda a: a.width * a.height)
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.screen.screenshot(filepath=str(path))
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = img.size
        pixels = base.np.empty(width * height * 4, dtype=base.np.float32)
        img.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(img)
    return pixels.reshape(height, width, 4)


def box_of(pixels, box) -> "base.np.ndarray":
    """(x, y, width, height) from the top left corner of pixels, which run
    bottom row first."""
    total_height, total_width = pixels.shape[:2]
    x, y, width, height = specs.clamp(box, total_width, total_height)
    return pixels[total_height - y - height:total_height - y, x:x + width].copy()


def area_of(win, name: str):
    found = [a for a in win.screen.areas if a.type == name]
    if not found:
        raise RuntimeError(f"the window has no {name} area: {sorted({a.type for a in win.screen.areas})}")
    return max(found, key=lambda a: a.width * a.height)


def rectangle(win, thing) -> tuple[int, int, int, int]:
    """An area's or a region's box from the window's top left corner."""
    return thing.x, win.height - thing.y - thing.height, thing.width, thing.height


def window_with(area_type: str):
    for win in bpy.context.window_manager.windows:
        if any(a.type == area_type for a in win.screen.areas):
            return win
    return None


class DocRun(base.Run):
    def __init__(self, plan: dict, spec: specs.Spec, group: specs.Group):
        super().__init__(SimpleNamespace(scenario=f"{spec.slug}/{group.label}", out=plan["shots"],
                                         work=plan["work"], wide=group.wide if group.wide != 1.0 else 0.0))
        self.deadline = plan["deadline"]
        self.spec = spec
        self.group = group
        self.stage = DocStage(self.work, spec)
        self.by_name = {s.name: s for s in group.shots}
        self.pending = list(plan["wanted"])
        self.queue: list[str] = []
        self.shot = None
        self.capture = None
        self.ended = False
        self.snap_popup = None
        self.returned_popup = None
        self.shot_started = 0.0

    def _settle(self):
        result = super()._settle()
        win = view_window()
        want = tuple(self.group.window)
        if (win.width, win.height) != want:
            raise RuntimeError(f"the window is {win.width}x{win.height}, not {want[0]}x{want[1]}")
        return result

    # the setup

    def start_setup(self):
        source = self.group.source
        fn = scenarios.SCENARIOS[source.scenario] if source.scenario else source.setup
        self.flags = fn
        result = fn(self.stage) if fn else None
        if inspect.isgenerator(result):
            return result

        def nothing_more():
            return result
            yield
        return nothing_more()

    def _scenario(self):
        if self.scenario is None:
            self.scenario = self.start_setup()
        if self.condition is not None:
            check, _what = self.condition
            if not check():
                return TICK
            self.condition = None
        if time.monotonic() < self.wait_until:
            return TICK
        try:
            step = next(self.scenario)
        except StopIteration as stop:
            self.ended = True
            self.returned_popup = stop.value if isinstance(stop.value, specs.Popup) else None
            self.queue = list(self.pending)
            return self._next()
        if isinstance(step, specs.Snap):
            unknown = [n for n in step.names if n not in self.by_name]
            if unknown:
                raise RuntimeError(f"Snap names no shot of this setup: {unknown}")
            self.snap_popup = step.popup
            self.queue = [n for n in step.names if n in self.pending]
            return self._next()
        if hasattr(step, "check"):
            self.condition = (step.check, step.what)
        else:
            self.wait_until = time.monotonic() + float(step)
        base.redraw_all()
        return TICK

    def _next(self):
        """The next shot of a Snap, or on with the setup, or the end."""
        if self.queue:
            self.begin(self.queue.pop(0))
        elif not self.pending:
            self.state = "quit"
        else:
            self.state = "scenario"
        return TICK

    def begin(self, name: str) -> None:
        self.shot = self.by_name[name]
        self.shot_started = time.monotonic()
        self.pages = []
        self.first_top = None
        chosen = self.snap_popup or self.returned_popup
        capture = self.shot.capture
        if capture is None:
            kind = ("popup" if chosen else "window" if getattr(self.flags, "window", False)
                    else "viewport" if getattr(self.flags, "viewport", False) else "sidebar")
            capture = specs.Capture(kind)
        self.capture = capture
        self.popup = (capture.popup or chosen) if capture.kind == "popup" else None
        if capture.kind == "popup" and self.popup is None:
            raise RuntimeError(f"{name} is a popup() with nothing to open: name one, or return a Popup")
        self.state = "hold"
        self.wait_until = time.monotonic() + base.HOLD

    # capture

    def _shoot(self):
        kind = self.capture.kind
        if kind == "sidebar":
            return self._shoot_pages()
        if kind == "preferences":
            self.state = "prefs_open"
            return TICK
        if kind == "viewport":
            pixels = base.screenshot_region(self.work / "viewport.png", viewport=True)
        elif kind == "window":
            win = window_with(self.capture.of) if self.capture.of else view_window()
            if win is None:
                raise RuntimeError(f"no window holds a {self.capture.of} area")
            pixels = window_pixels(win, self.work / "window.png")
        else:
            pixels = self.shoot_region()
        self.pages = [(0, pixels)]
        return self._write(pixels)

    def shoot_region(self):
        win = view_window()
        pixels = window_pixels(win, self.work / "window.png")
        capture = self.capture
        if capture.box is not None:
            return box_of(pixels, capture.box)
        area = area_of(win, capture.area)
        region = next((r for r in area.regions if r.type == capture.part), None)
        if region is None:
            raise RuntimeError(f"the {capture.area} area has no {capture.part} region")
        return box_of(pixels, rectangle(win, area if capture.part == "WINDOW" else region))

    # the Preferences window

    def _prefs_open(self):
        section = self.capture.section
        # A user has no agent override: without this the status names the
        # dev venv's path.
        os.environ.pop(AGENT_VARIABLE, None)
        if checks.preferences_window() is None:
            win, area, _main, ui = base.view3d()
            if section == "ADDONS":
                from whittle.addon import prefs

                self.stage.button("preferences.addon_show", module=prefs.PACKAGE)
            else:
                with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=ui):
                    bpy.ops.screen.userpref_show("INVOKE_DEFAULT", section=section)
        self.state = "prefs_wait"
        return TICK

    def _prefs_wait(self):
        if checks.preferences_window() is None:
            return TICK
        bpy.context.preferences.active_section = self.capture.section
        self.prefs_search()
        # What the add-ons section draws its File row from.
        next(m for m in addon_utils.modules(refresh=False) if m.__name__ == PACKAGE).__file__ = SHOWN_FILE
        checks.redraw_all()
        self.state = "prefs_scroll"
        self.wait_until = time.monotonic() + 0.5
        return TICK

    def prefs_search(self) -> None:
        text = self.capture.search
        if not text:
            return
        if self.capture.section == "KEYMAP":
            override = checks.preferences_override()
            override["area"].spaces.active.filter_text = text
        else:
            bpy.context.window_manager.extension_search = text

    def _prefs_scroll(self):
        if time.monotonic() < self.wait_until:
            return TICK
        override = checks.preferences_override()
        with bpy.context.temp_override(**override):
            for _ in range(60):
                bpy.ops.view2d.scroll_up()
            for _ in range(self.capture.scroll):
                bpy.ops.view2d.scroll_down()
        checks.redraw_all()
        self.state = "prefs_shoot"
        self.wait_until = time.monotonic() + base.HOLD
        return TICK

    def _prefs_shoot(self):
        if time.monotonic() < self.wait_until:
            return TICK
        checks.redraw_all()
        win = checks.preferences_window()
        if self.capture.full:
            self.state = "prefs_page"
            self.wait_until = 0.0
            return TICK
        if self.capture.popup is not None:
            return self._prefs_popup(win)
        pixels = window_pixels(win, self.work / "preferences.png")
        self.pages = [(0, pixels)]
        return self._write(pixels)

    def _prefs_page(self):
        """The section's whole length: the main region, a page at a time."""
        if time.monotonic() < self.wait_until:
            return TICK
        override = checks.preferences_override()
        win, main = override["window"], override["region"]
        top = main.view2d.region_to_view(0, main.height)[1]
        if self.first_top is None:
            self.first_top = top
        offset = round(self.first_top - top)
        if self.pages and offset <= self.pages[-1][0]:
            return self._write(base.trim_bottom(stitch_section(self.pages), tabs=0))
        if len(self.pages) >= base.MAX_PAGES:
            raise RuntimeError(f"the section is still not at its end after {base.MAX_PAGES} pages")
        pixels = window_pixels(win, self.work / f"preferences-{len(self.pages)}.png")
        self.pages.append((offset, box_of(pixels, rectangle(win, main))))
        with bpy.context.temp_override(**override):
            bpy.ops.view2d.scroll_down(deltay=-(main.height - 2 * EDGE))
        main.tag_redraw()
        self.wait_until = time.monotonic() + 0.4
        return TICK

    def _prefs_popup(self, win):
        self.before_popup = window_pixels(win, self.work / "preferences-before.png")
        override = checks.preferences_override()
        main = override["region"]
        win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=main.x + main.width // 2,
                           y=main.y + main.height // 2)
        popup = self.capture.popup
        module, name = popup.name.split(".")
        with bpy.context.temp_override(**override):
            getattr(getattr(bpy.ops, module), name)("INVOKE_DEFAULT", **popup.props)
        checks.redraw_all()
        self.state = "prefs_popup_unhover"
        self.wait_until = time.monotonic() + base.HOLD
        return TICK

    def _prefs_popup_unhover(self):
        """As the screenshot harness's _popup_unhover: lets go of the item
        under the pointer."""
        if time.monotonic() < self.wait_until:
            return TICK
        win = checks.preferences_window()
        after = window_pixels(win, self.work / "preferences-after.png")
        x0, _y0, _x1, y1 = base.change_bounds(self.before_popup, after)
        x, y = x0 + 12, y1 - 8
        win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        win.event_simulate(type="WINDOW_DEACTIVATE", value="NOTHING", x=x, y=y)
        checks.redraw_all()
        self.state = "prefs_popup_shoot"
        self.wait_until = time.monotonic() + 0.5
        return TICK

    def _prefs_popup_shoot(self):
        if time.monotonic() < self.wait_until:
            return TICK
        win = checks.preferences_window()
        after = window_pixels(win, self.work / "preferences-after.png")
        pixels = base.crop_to_change(self.before_popup, after)
        self.pages = [(0, pixels)]
        return self._write(pixels)

    # after a capture

    def _write(self, pixels):
        shot, capture = self.shot, self.capture
        if capture.crop is not None:
            pixels = box_of(pixels, capture.crop)
        self.out.mkdir(parents=True, exist_ok=True)
        base.save_png(pixels, self.out / f"{shot.name}.png")
        meta = {"shot": shot.name, "kind": capture.kind, "size": [int(pixels.shape[1]), int(pixels.shape[0])],
                "pages": len(self.pages), "seconds": round(time.monotonic() - self.shot_started, 1)}
        (self.out / f"{shot.name}.json").write_text(json.dumps(meta, indent=1) + "\n")
        print(f"docshots: wrote {shot.name} ({meta['size'][0]}x{meta['size'][1]}, {capture.kind})", flush=True)
        self.pending.remove(shot.name)
        self.state = "after"
        return TICK

    def _after(self):
        """Puts things back, so the setup and the next shot find the window
        as it was: nothing open, the sidebar at its top."""
        kind = self.capture.kind
        self.wait_until = time.monotonic() + 0.3
        if kind == "popup" or (kind == "preferences" and self.capture.popup is not None):
            win = checks.preferences_window() if kind == "preferences" else view_window()
            win.event_simulate(type="ESC", value="PRESS", x=8, y=8)
            win.event_simulate(type="ESC", value="RELEASE", x=8, y=8)
        if kind == "preferences":
            self.state = "close_prefs"
            return TICK
        if kind == "sidebar":
            win, area, _main, ui = base.view3d()
            with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=ui):
                bpy.ops.view2d.scroll_up(deltay=100000)
        base.redraw_all()
        self.state = "continue"
        return TICK

    def _close_prefs(self):
        if time.monotonic() < self.wait_until:
            return TICK
        win = checks.preferences_window()
        if win is not None:
            with bpy.context.temp_override(window=win):
                bpy.ops.wm.window_close()
        os.environ[AGENT_VARIABLE] = AGENT
        self.state = "continue"
        return TICK

    def _continue(self):
        if time.monotonic() < self.wait_until:
            return TICK
        return self._next()


def view_window():
    return base.view3d()[0]


def stitch_section(pages: list) -> "base.np.ndarray":
    """Pages are (pixels scrolled down, the main region's pixels), which
    overlap by 2 * EDGE: each adds what lies between its clipped edges, so
    no scroll arrow lands inside the image."""
    height, width = pages[0][1].shape[:2]
    total = height + max(offset for offset, _ in pages)
    canvas = base.np.zeros((total, width, 4), dtype=base.np.float32)
    last = len(pages) - 1
    for k, (offset, page) in enumerate(pages):
        bottom = total - offset - height
        low = EDGE // 2 if k == last else EDGE
        high = height if k == 0 else height - EDGE
        canvas[bottom + low:bottom + high] = page[low:high]
    return canvas[EDGE // 2:]


def main() -> None:
    plan = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    # Without region overlap the sidebar has a flat background of its own, so
    # the crop holds only the panels and where they end can be found. A popup
    # is opened under the pointer, whose item would show its tooltip.
    bpy.context.preferences.system.use_region_overlap = False
    bpy.context.preferences.view.show_tooltips = False
    spec = specs.load(Path(plan["spec"]))
    group = specs.groups(spec.shots)[plan["group"]]
    base.prune_other_panels()
    if group.open_panels or getattr(scenarios.SCENARIOS.get(group.source.scenario), "open_panels", False):
        base.open_whittle_panels()
    base.view3d()[1].spaces.active.show_region_ui = True
    run = DocRun(plan, spec, group)
    bpy.app.timers.register(run.tick, first_interval=TICK, persistent=True)


if __name__ == "__main__":
    main()
