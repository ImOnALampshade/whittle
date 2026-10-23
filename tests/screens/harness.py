# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs one screenshot scenario inside a GUI Blender, then quits. Started by
tests/screens/run.py as

    blender --factory-startup --enable-event-simulate ... scene.blend \
        --python tests/screens/harness.py -- --scenario NAME --out PNG --meta JSON [--wide F]

The scenario reaches its state through the add-on's own controller and
operator functions on real timers; the harness then screenshots the 3D
viewport, crops the sidebar (or, for a viewport scenario, the viewport; a window
scenario keeps the whole window) out of it with Blender's image API (scrolling
and stitching when the panels are taller than the sidebar) and writes the
PNG plus a small JSON of what it shot. Any failure exits with code 1."""

import argparse
import json
import os
import struct
import sys
import time
import traceback
import zlib
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402  (bundled with Blender)

from tests.screens import catalog, scenarios  # noqa: E402

TICK = 0.1
# The window needs a moment to get its real size before anything is measured.
SETTLE = 1.5
# Long enough for preview icons (thumbnails) to load and the panels to redraw.
HOLD = 2.0
DEADLINE = 95.0
MAX_PAGES = 20
# The sidebar's tab strip on its right edge, left out when finding where the
# panels end.
TAB_STRIP = 30
# The window's status bar along its bottom, left out when finding what a
# popup changed: a menu puts its hints (Space: Search) there.
STATUS_BAR = 30


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="harness.py")
    parser.add_argument("--scenario", required=True, choices=sorted(catalog.SCENARIOS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--wide", type=float, default=0.0,
                        help="widen the sidebar to this factor of its default width")
    return parser.parse_args(argv)


# -- the window ---------------------------------------------------------------

def view3d():
    """The window, the largest 3D viewport, its main and its sidebar region."""
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    main = next(r for r in area.regions if r.type == "WINDOW")
    ui = next(r for r in area.regions if r.type == "UI")
    return win, area, main, ui


def redraw_all() -> None:
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()


def prune_other_panels() -> None:
    """Every other Python-defined sidebar tab goes, so Whittle is the tab
    shown when the sidebar first draws (Region.active_panel_category can
    only be set once it has drawn its categories) and the tab strip stays
    short."""
    for cls in list(bpy.types.Panel.__subclasses__()):
        if (getattr(cls, "bl_space_type", "") == "VIEW_3D" and getattr(cls, "bl_region_type", "") == "UI"
                and getattr(cls, "bl_category", "") != "Whittle"):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass


def open_whittle_panels() -> None:
    """Re-registers Whittle's closed-by-default panels open. Panel open state
    has no Python API either; a panel takes its type's default when the
    region first draws it, which has not happened yet."""
    for cls in list(bpy.types.Panel.__subclasses__()):
        if getattr(cls, "bl_category", "") == "Whittle" and "DEFAULT_CLOSED" in getattr(cls, "bl_options", ()):
            bpy.utils.unregister_class(cls)
            cls.bl_options = set(cls.bl_options) - {"DEFAULT_CLOSED"}
            bpy.utils.register_class(cls)


# -- capture ------------------------------------------------------------------

def screenshot_region(path: Path, *, viewport: bool = False) -> np.ndarray:
    """The sidebar region's pixels (or, with viewport, the viewport's own),
    bottom row first, as (h, w, 4) floats."""
    win, area, main, ui = view3d()
    region = main if viewport else ui
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=ui):
        bpy.ops.screen.screenshot_area(filepath=str(path))
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = img.size
        if (width, height) != (area.width, area.height):
            raise RuntimeError(f"screenshot is {width}x{height}, the area {area.width}x{area.height}")
        pixels = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(img)
    pixels = pixels.reshape(height, width, 4)
    x0, y0 = region.x - area.x, region.y - area.y
    return pixels[y0:y0 + region.height, x0:x0 + region.width].copy()


def screenshot_window(path: Path) -> np.ndarray:
    """The whole window's pixels, bottom row first, popups included."""
    win, area, _main, _ui = view3d()
    with bpy.context.temp_override(window=win, screen=win.screen, area=area):
        bpy.ops.screen.screenshot(filepath=str(path))
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = img.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(img)
    return pixels.reshape(height, width, 4)


def crop_to_change(before: np.ndarray, after: np.ndarray, margin: int = 8, status: int = 0) -> np.ndarray:
    """The part of after that differs from before: the popup that opened,
    with a little of what it covers around it. The bottom status rows are
    not looked at."""
    if before.shape != after.shape:
        raise RuntimeError("the window changed size while the popup opened")
    changed = np.abs(after[..., :3] - before[..., :3]).max(axis=2) > 1e-3
    changed[:status] = False
    rows, cols = np.nonzero(changed.any(axis=1))[0], np.nonzero(changed.any(axis=0))[0]
    if len(rows) == 0:
        raise RuntimeError("nothing opened: the window looks the same")
    y0, y1 = max(0, rows[0] - margin), min(after.shape[0], rows[-1] + 1 + margin)
    x0, x1 = max(0, cols[0] - margin), min(after.shape[1], cols[-1] + 1 + margin)
    return after[y0:y1, x0:x1].copy()


def view_top() -> float:
    _win, _area, _main, ui = view3d()
    return ui.view2d.region_to_view(0, ui.height)[1]


def scroll_page_down() -> None:
    win, area, _main, ui = view3d()
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=ui):
        bpy.ops.view2d.scroll_down(page=True)


def stitch(pages: list[tuple[int, np.ndarray]]) -> np.ndarray:
    """Pages are (pixels scrolled down from the first page, region pixels);
    images run bottom row first, so the first page ends up at the top. Each
    page only adds what lies below the one before it: drawn last to first,
    the sidebar's fixed tab strip is not repeated at every page's top."""
    height, width = pages[0][1].shape[:2]
    total = height + max(offset for offset, _ in pages)
    canvas = np.zeros((total, width, 4), dtype=np.float32)
    for offset, page in reversed(pages):
        bottom = total - offset - height
        canvas[bottom:bottom + height] = page
    return canvas


def trim_bottom(pixels: np.ndarray, tabs: int = TAB_STRIP, margin: int = 12) -> np.ndarray:
    """Drops the empty sidebar below the last panel: rows that are one flat
    colour once the tab strip on the right is left out."""
    band = pixels[:, :max(1, pixels.shape[1] - tabs), :3]
    flat = (band.max(axis=1) - band.min(axis=1)).max(axis=1) < 1e-3
    used = np.nonzero(~flat)[0]
    if len(used) == 0:
        return pixels
    return pixels[max(0, used[0] - margin):]


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png_rows(rows: np.ndarray, bpp: int) -> bytes:
    """The image rows (top first), each with the PNG filter whose output
    sums smallest, libpng's own heuristic, its filter byte first."""
    x = rows.astype(np.int16)
    left = np.zeros_like(x)
    left[:, bpp:] = x[:, :-bpp]
    up = np.zeros_like(x)
    up[1:] = x[:-1]
    corner = np.zeros_like(x)
    corner[1:, bpp:] = x[:-1, :-bpp]
    guess = left + up - corner
    da, db, dc = np.abs(guess - left), np.abs(guess - up), np.abs(guess - corner)
    paeth = np.where((da <= db) & (da <= dc), left, np.where(db <= dc, up, corner))
    options = np.stack([x, x - left, x - up, x - (left + up) // 2, x - paeth]) & 0xFF
    cost = np.where(options > 127, 256 - options, options).sum(axis=2)
    best = cost.argmin(axis=0)
    out = np.empty((x.shape[0], x.shape[1] + 1), dtype=np.uint8)
    out[:, 0] = best
    out[:, 1:] = options[best, np.arange(x.shape[0])]
    return out.tobytes()


def save_png(pixels: np.ndarray, path: Path) -> None:
    """Writes pixels (bottom row first) as a small, lossless 8-bit PNG
    without alpha: indexed when it holds 256 colours or fewer, else RGB.
    Written here rather than by Blender, whose writer keeps the alpha and
    whose save of a render would apply the scene's view transform."""
    rgb = np.clip(np.round(pixels[::-1, :, :3] * 255.0), 0, 255).astype(np.uint8)
    height, width = rgb.shape[:2]
    flat = rgb.reshape(-1, 3).astype(np.uint32)
    colours, index = np.unique((flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2], return_inverse=True)
    if len(colours) <= 256:
        palette = np.stack([colours >> 16, colours >> 8, colours], axis=1) & 0xFF
        header = struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)
        body = (_png_chunk(b"PLTE", palette.astype(np.uint8).tobytes())
                + _png_chunk(b"IDAT", zlib.compress(_png_rows(index.reshape(height, width).astype(np.uint8), 1), 9)))
    else:
        header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        body = _png_chunk(b"IDAT", zlib.compress(_png_rows(rgb.reshape(height, width * 3), 3), 9))
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + body + _png_chunk(b"IEND", b""))


# -- the run ------------------------------------------------------------------

class Run:
    """A state machine on one timer: settle, widen the sidebar, play the
    scenario, hold for the redraw, then shoot page by page and quit."""

    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        self.work = Path(args.work)
        self.started = time.monotonic()
        self.state = "settle"
        self.wait_until = self.started + SETTLE
        self.condition = None
        self.scenario = None
        self.pages: list[tuple[int, np.ndarray]] = []
        self.first_top = None
        self.widen_steps = None
        self.default_width = None
        self.popup = None
        self.before_popup = None

    def tick(self):
        try:
            if time.monotonic() - self.started > DEADLINE:
                raise TimeoutError(f"gave up after {DEADLINE:g} s in state {self.state}"
                                   + (f" waiting for {self.condition[1]}" if self.condition else ""))
            return getattr(self, f"_{self.state}")()
        except Exception:
            self.fail(traceback.format_exc())
            return None

    def _settle(self):
        if time.monotonic() < self.wait_until:
            return TICK
        _win, area, _main, ui = view3d()
        self.default_width = ui.width
        print(f"screens: area {area.width}x{area.height}, sidebar {ui.width}x{ui.height}", flush=True)
        self.state = "widen" if self.args.wide else "scenario"
        return TICK

    def _widen(self):
        """Drags the sidebar's edge with simulated events: its width has no
        Python setter."""
        win, _area, _main, ui = view3d()
        if self.widen_steps is None:
            grow = round(self.default_width * (self.args.wide - 1.0))
            x, y = ui.x + 1, ui.y + ui.height // 2
            self.widen_steps = [("MOUSEMOVE", "NOTHING", x, y), ("LEFTMOUSE", "PRESS", x, y)]
            self.widen_steps += [("MOUSEMOVE", "NOTHING", x - grow * k // 8, y) for k in range(1, 9)]
            self.widen_steps += [("LEFTMOUSE", "RELEASE", x - grow, y)]
        if self.widen_steps:
            kind, value, x, y = self.widen_steps.pop(0)
            win.event_simulate(type=kind, value=value, x=x, y=y)
            return TICK
        wanted = round(self.default_width * self.args.wide)
        if abs(ui.width - wanted) > max(8, wanted // 20):
            raise RuntimeError(f"could not widen the sidebar: {ui.width} px, wanted {wanted}")
        print(f"screens: sidebar widened to {ui.width} px", flush=True)
        self.state = "scenario"
        return TICK

    def _scenario(self):
        if self.scenario is None:
            stage = scenarios.Stage(self.work)
            self.scenario = scenarios.SCENARIOS[self.args.scenario](stage)
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
            if isinstance(stop.value, scenarios.Popup):
                self.popup = stop.value
            self.state = "hold"
            self.wait_until = time.monotonic() + HOLD
            return TICK
        if isinstance(step, scenarios.Until):
            self.condition = (step.check, step.what)
        else:
            self.wait_until = time.monotonic() + float(step)
        redraw_all()
        return TICK

    def _hold(self):
        _win, _area, _main, ui = view3d()
        # Item's Transform panel is built into Blender and cannot be
        # unregistered; it takes the sidebar whenever an object is active.
        # The tab can be picked once the sidebar has drawn its categories.
        if ui.active_panel_category != "Whittle":
            try:
                ui.active_panel_category = "Whittle"
            except (TypeError, ValueError):
                pass
        redraw_all()
        if time.monotonic() < self.wait_until:
            return TICK
        self.state = "open_popup" if self.popup is not None else "shoot"
        return TICK

    def _open_popup(self):
        """Puts the pointer over the sidebar's lower part (simulated, so no
        real input is involved), shoots the window, opens the popup there
        and lets it draw."""
        win, area, _main, ui = view3d()
        x, y = ui.x + 60, ui.y + ui.height // 3
        win.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        redraw_all()
        self.before_popup = None
        self.state = "popup_before"
        self.wait_until = time.monotonic() + 0.5
        return TICK

    def _popup_before(self):
        if time.monotonic() < self.wait_until:
            return TICK
        self.before_popup = screenshot_window(self.work / "window-before.png")
        win, area, _main, ui = view3d()
        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=ui):
            if self.popup.kind == "panel":
                bpy.ops.wm.call_panel(name=self.popup.name, keep_open=True)
            else:
                module, name = self.popup.name.split(".")
                getattr(getattr(bpy.ops, module), name)("INVOKE_DEFAULT", **self.popup.props)
        redraw_all()
        self.state = "popup_shoot"
        self.wait_until = time.monotonic() + HOLD
        return TICK

    def _popup_shoot(self):
        if time.monotonic() < self.wait_until:
            return TICK
        after = screenshot_window(self.work / "window-after.png")
        pixels = crop_to_change(self.before_popup, after, status=STATUS_BAR)
        self.pages = [(0, pixels)]
        return self._write(pixels)

    def _shoot(self):
        if getattr(scenarios.SCENARIOS[self.args.scenario], "window", False):
            # The whole window, as Blender draws it: no desktop around it.
            pixels = screenshot_window(self.work / "window.png")
            self.pages = [(0, pixels)]
            return self._write(pixels)
        if getattr(scenarios.SCENARIOS[self.args.scenario], "viewport", False):
            # One shot of the viewport, for what the scenario shows there.
            pixels = screenshot_region(self.work / "viewport.png", viewport=True)
            self.pages = [(0, pixels)]
            return self._write(pixels)
        _win, _area, _main, ui = view3d()
        if ui.active_panel_category != "Whittle":
            raise RuntimeError(f"the sidebar shows the {ui.active_panel_category!r} tab, not Whittle")
        top = view_top()
        if self.first_top is None:
            self.first_top = top
        offset = round(self.first_top - top)
        if self.pages and offset <= self.pages[-1][0]:
            return self._finish()
        if len(self.pages) >= MAX_PAGES:
            raise RuntimeError(f"the panels are still not at their end after {MAX_PAGES} pages")
        page = self.work / f"page-{len(self.pages)}.png"
        self.pages.append((offset, screenshot_region(page)))
        scroll_page_down()
        redraw_all()
        # The scrolled region is drawn on the next redraw.
        self.state = "after_scroll"
        self.wait_until = time.monotonic() + 0.3
        return TICK

    def _after_scroll(self):
        if time.monotonic() < self.wait_until:
            return TICK
        self.state = "shoot"
        return TICK

    def _finish(self):
        return self._write(trim_bottom(stitch(self.pages)))

    def _write(self, pixels):
        self.out.parent.mkdir(parents=True, exist_ok=True)
        save_png(pixels, self.out)
        _win, _area, _main, ui = view3d()
        meta = {"scenario": self.args.scenario, "png": str(self.out),
                "description": catalog.SCENARIOS[self.args.scenario],
                "size": [int(pixels.shape[1]), int(pixels.shape[0])],
                "sidebar": [ui.width, ui.height], "pages": len(self.pages),
                "seconds": round(time.monotonic() - self.started, 1)}
        Path(self.args.meta).write_text(json.dumps(meta, indent=1) + "\n")
        print(f"screens: wrote {self.out} ({meta['size'][0]}x{meta['size'][1]}, "
              f"{len(self.pages)} page(s))", flush=True)
        self.state = "quit"
        return TICK

    def _quit(self):
        bpy.ops.wm.quit_blender()
        return None

    def fail(self, message: str) -> None:
        print(f"screens: {self.args.scenario} failed:\n{message}", file=sys.stderr, flush=True)
        try:
            from whittle.addon import sketch, turn

            sketch.end_session()
            turn.shutdown_current()
        finally:
            # quit_blender always exits 0, so a failure leaves this way.
            sys.stderr.flush()
            os._exit(1)


def main() -> None:
    args = parse_args()
    # The GUI writes its recent-files list on load: it must go to the run's
    # own config folder, never the user's.
    config = Path(bpy.utils.user_resource("CONFIG")).resolve()
    own = os.environ.get("BLENDER_USER_CONFIG")
    if not own or config != Path(own).resolve():
        print(f"screens: refusing to run with Blender's config in {config}", file=sys.stderr, flush=True)
        os._exit(1)
    # Nothing this run changes may reach the preferences on disk.
    bpy.context.preferences.use_preferences_save = False
    # Without region overlap the sidebar has a flat background of its own, so
    # the crop holds only the panels and where they end can be found.
    bpy.context.preferences.system.use_region_overlap = False
    # A popup is opened under the pointer, whose item would show its tooltip.
    bpy.context.preferences.view.show_tooltips = False
    from whittle import addon

    addon.register()
    prune_other_panels()
    scenario = scenarios.SCENARIOS[args.scenario]
    if getattr(scenario, "open_panels", False):
        open_whittle_panels()
    _win, area, _main, _ui = view3d()
    area.spaces.active.show_region_ui = True
    run = Run(args)
    bpy.app.timers.register(run.tick, first_interval=TICK)


if __name__ == "__main__":
    main()
