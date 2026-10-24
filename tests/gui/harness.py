# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs one phase of one GUI check inside a GUI Blender, then quits. Started
by tests/gui/run.py as

    blender --factory-startup --enable-event-simulate ... FILE.blend \
        --python tests/gui/harness.py -- --check NAME --phase N --work DIR --deadline S

The phase is a generator (tests/gui/checks.py) stepped on a persistent
timer, so it carries on across the file loads it makes. It yields a number
to wait that many seconds, or an Until to wait for a condition; simulated
input is sent by the stage's helpers in between. When it returns, the
harness writes phase-N.ok in the work folder and quits (or, when the phase
returned KILL, kills its own Blender as a crash would). Any exception
prints the traceback and exits with code 1, without the marker.

Whittle is the extension the run installed, which Blender enabled at
startup from the run's preferences; `whittle` is an alias of it
(tests/gui/alias.py), so the checks use the installed modules."""

import argparse
import os
import signal
import sys
import time
import traceback
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.gui import catalog  # noqa: E402
from tests.gui.alias import Alias  # noqa: E402

# The installed extension's module.
PACKAGE = f"bl_ext.{catalog.REPOSITORY}.whittle"
# Imported once the alias is in place.
checks = None

TICK = 0.05
# The window needs a moment to get its real size before anything is measured.
SETTLE = 1.0


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="harness.py")
    parser.add_argument("--check", required=True, choices=sorted(catalog.CHECKS))
    parser.add_argument("--phase", required=True, type=int)
    parser.add_argument("--work", required=True)
    parser.add_argument("--deadline", type=float, default=90.0)
    return parser.parse_args(argv)


class Run:
    def __init__(self, args):
        self.args = args
        self.label = f"{args.check}[{args.phase}]"
        self.started = time.monotonic()
        self.wait_until = self.started + SETTLE
        self.condition = None
        self.stage = checks.GuiStage(Path(args.work))
        self.phase = None

    def tick(self):
        try:
            return self._tick()
        except Exception:
            self.fail(traceback.format_exc())
            return None

    def _tick(self):
        now = time.monotonic()
        if now - self.started > self.args.deadline:
            what = f" waiting for {self.condition.what}" if self.condition else ""
            raise TimeoutError(f"gave up after {self.args.deadline:g} s{what}")
        if self.condition is not None:
            if not self.condition.check():
                if self.condition.expired():
                    raise TimeoutError(f"timed out after {self.condition.timeout:g} s waiting for "
                                       f"{self.condition.what}")
                return TICK
            self.condition = None
        if now < self.wait_until:
            return TICK
        if self.phase is None:
            self.phase = checks.PHASES[self.args.check][self.args.phase](self.stage)
        try:
            step = next(self.phase)
        except StopIteration as stop:
            self.finish(stop.value)
            return None
        if hasattr(step, "check"):
            self.condition = checks.Until.of(step).start()
        else:
            self.wait_until = time.monotonic() + float(step)
        return TICK

    def finish(self, how) -> None:
        seconds = round(time.monotonic() - self.started, 1)
        (Path(self.args.work) / f"phase-{self.args.phase}.ok").write_text(f"{seconds}\n")
        print(f"gui: {self.label} passed in {seconds} s", flush=True)
        if how is checks.KILL:
            # As a crash would: no exit handlers, no quit.blend.
            sys.stdout.flush()
            os.kill(os.getpid(), signal.SIGKILL)
        bpy.app.timers.register(_quit, first_interval=TICK)

    def fail(self, message: str) -> None:
        print(f"gui: {self.label} failed:\n{message}", file=sys.stderr, flush=True)
        try:
            from whittle.addon import sketch, turn

            sketch.end_session()
            turn.shutdown_current()
        finally:
            # quit_blender always exits 0, so a failure leaves this way.
            sys.stderr.flush()
            os._exit(1)


def _quit():
    bpy.ops.wm.quit_blender()
    return None


def refuse(why: str) -> None:
    print(f"gui: refusing to run: {why}", file=sys.stderr, flush=True)
    os._exit(1)


def use_installed() -> None:
    """Checks that the add-on running is the one the run installed, from its
    own repository, then imports it as `whittle` too."""
    global checks
    if bpy.context.preferences.addons.get(PACKAGE) is None or PACKAGE not in sys.modules:
        refuse(f"{PACKAGE} is not enabled (tests/gui/run.py installs it)")
    where = Path(sys.modules[PACKAGE].__file__).resolve()
    own = (REPO / "build" / "gui-checks" / catalog.REPOSITORY).resolve()
    if not where.is_relative_to(own):
        refuse(f"Whittle was loaded from {where}, not the run's repository {own}")
    try:
        Alias("whittle", PACKAGE).install()
        from tests.gui import checks as loaded
    except Exception:
        refuse("the checks cannot import the installed Whittle:\n" + traceback.format_exc())
    checks = loaded


def main() -> None:
    args = parse_args()
    # The GUI writes its recent-files list on load: it must go to the run's
    # own config folder, never the user's.
    config = Path(bpy.utils.user_resource("CONFIG")).resolve()
    own = os.environ.get("BLENDER_USER_CONFIG")
    if not own or config != Path(own).resolve():
        refuse(f"Blender's config is in {config}")
    # Nothing a check changes, a fake API key above all, may reach the
    # preferences on disk.
    bpy.context.preferences.use_preferences_save = False
    use_installed()
    run = Run(args)
    bpy.app.timers.register(run.tick, first_interval=TICK, persistent=True)


if __name__ == "__main__":
    main()
