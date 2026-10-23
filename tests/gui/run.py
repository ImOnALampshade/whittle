# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the GUI checks in real GUI Blenders, one phase per Blender, one
Blender at a time: `./gui_checks.sh [check ...]`.

Each Blender runs in the hidden nested session (the screenshot harness's),
with --enable-event-simulate, so the checks drive it with simulated input
and real input cannot reach it; its user folders, temporary folder and
Whittle user folder are the run's own. Exits non-zero when any check
failed. Stdlib only."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.gui import catalog  # noqa: E402
from tests.screens.run import hidden_display  # noqa: E402

WORK = REPO / "build" / "gui-checks"
HARNESS = REPO / "tests" / "gui" / "harness.py"
AGENT_PYTHON = REPO / ".venv" / "bin" / "python"
# Startup, loading the add-on and quitting, on top of the phase's own deadline.
OVERHEAD = 40


def blender_env(work: Path) -> dict:
    """Blender's user folders point into the run's own folder (Blender
    falls back to the real one for a folder that does not exist, so each is
    made first), its temporary folder (autosave, quit.blend) into the
    check's, and the agent is the fake one from the dev venv."""
    env = dict(os.environ)
    for name in ("WHITTLE_LIVE", "ANTHROPIC_API_KEY"):
        env.pop(name, None)
    root = WORK / "blender-user"
    env["BLENDER_USER_RESOURCES"] = str(root)
    for kind in ("config", "scripts", "extensions", "datafiles"):
        folder = root / kind
        folder.mkdir(parents=True, exist_ok=True)
        env[f"BLENDER_USER_{kind.upper()}"] = str(folder)
    tmp = work / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for name in ("TMPDIR", "TEMP", "TMP"):
        env[name] = str(tmp)
    env["WHITTLE_USER_DIR"] = str(work / "user")
    env["WHITTLE_AGENT_PYTHON"] = str(AGENT_PYTHON)
    hidden = hidden_display(WORK, visible="WHITTLE_GUI_VISIBLE")
    if hidden:
        env.pop("DISPLAY", None)
        env["WAYLAND_DISPLAY"] = hidden
    return env


def make_base_blend(path: Path) -> None:
    """The factory startup file, to open (a .blend on the command line skips
    the splash screen), and factory preferences in the run's config folder,
    since Blender greets a config folder without them with its first-run
    splash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    code = ("import bpy, sys; bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1]); "
            "bpy.ops.wm.save_userpref()")
    subprocess.run(["timeout", "120", "blender", "-b", "--factory-startup",
                    "--python-expr", code, "--", str(path)],
                   env=blender_env(WORK / "base"), check=True, stdout=subprocess.DEVNULL)


def run_phase(name: str, index: int, phase: catalog.Phase, work: Path) -> str | None:
    """Runs one phase; returns None when it passed, else why not."""
    blend = work / phase.open
    if not blend.is_file():
        return f"phase {index} opens {phase.open}, which no earlier phase saved"
    width, height = catalog.WINDOW
    ok = work / f"phase-{index}.ok"
    ok.unlink(missing_ok=True)
    cmd = ["timeout", "-s", "KILL", str(int(phase.deadline + OVERHEAD)), "blender", "--factory-startup",
           "--enable-event-simulate", "--no-window-focus", "--window-geometry", "0", "0", str(width),
           str(height), str(blend), "--python", str(HARNESS), "--",
           "--check", name, "--phase", str(index), "--work", str(work), "--deadline", str(phase.deadline)]
    log = work / f"phase-{index}.log"
    with open(log, "w") as out:
        code = subprocess.run(cmd, env=blender_env(work), stdout=out, stderr=subprocess.STDOUT,
                              cwd=work).returncode
    left = leftover_processes(work)
    # A phase that ends in a kill -9 of its own Blender (a crash check)
    # writes its marker first.
    if ok.is_file() and code in (0, -9, 137) and not left:
        return None
    if left:
        return f"phase {index}: processes outlived their Blender: " + "; ".join(left)
    tail = log.read_text(errors="replace").splitlines()[-30:]
    return f"phase {index} failed (exit {code}); the end of {log}:\n" + "\n".join("    " + l for l in tail)


def leftover_processes(work: Path, wait: float = 5.0) -> list[str]:
    """Processes still running from this check (an agent started from its
    folder outlives a killed Blender only if it misses the closed socket).
    Given a few seconds to go, then killed and listed."""
    def find() -> dict[int, str]:
        found = {}
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if str(work) in cmd and "harness.py" not in cmd:
                found[int(proc.name)] = cmd.strip()
        return found

    deadline = time.monotonic() + wait
    while (left := find()) and time.monotonic() < deadline:
        time.sleep(0.2)
    for pid in left:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    return [f"{pid}: {cmd[:160]}" for pid, cmd in left.items()]


def run_check(name: str) -> dict:
    check = catalog.CHECKS[name]
    work = WORK / name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    shutil.copyfile(WORK / "base" / "base.blend", work / "base.blend")
    started = time.monotonic()
    print(f"gui: {name} ...", flush=True)
    for index, phase in enumerate(check.phases):
        failure = run_phase(name, index, phase, work)
        if failure:
            print(f"gui: {name} FAILED, {failure}", file=sys.stderr, flush=True)
            return {"check": name, "passed": False, "detail": failure}
    seconds = round(time.monotonic() - started, 1)
    print(f"gui: {name} passed ({seconds} s)", flush=True)
    return {"check": name, "passed": True, "seconds": seconds}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gui_checks.sh", description=__doc__.split("\n\n")[0])
    parser.add_argument("checks", nargs="*", help="checks to run (default: all): " + ", ".join(catalog.CHECKS))
    args = parser.parse_args(argv)
    unknown = [n for n in args.checks if n not in catalog.CHECKS]
    if unknown:
        parser.error(f"unknown check(s): {', '.join(unknown)}")
    names = args.checks or list(catalog.CHECKS)
    make_base_blend(WORK / "base" / "base.blend")
    results = [run_check(name) for name in names]
    (WORK / "report.json").write_text(json.dumps({"checks": results}, indent=1) + "\n")
    failed = [r["check"] for r in results if not r["passed"]]
    if failed:
        print(f"gui: {len(failed)} of {len(results)} failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"gui: all {len(results)} passed; report in {(WORK / 'report.json').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
