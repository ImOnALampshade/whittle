# SPDX-License-Identifier: GPL-3.0-or-later
"""Shoots the Whittle sidebar in a real GUI Blender, one scenario per
Blender, one Blender at a time: `./screens.sh [scenario ...]`.

Writes build/screens/<scenario>.png (and wide/<scenario>.png for the
scenarios in catalog.WIDE) plus build/screens/index.json, and exits non-zero
when any scenario did not produce its image. Stdlib only."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.screens import catalog  # noqa: E402

OUT = REPO / "build" / "screens"
WORK = REPO / "build" / "screens-work"
HARNESS = REPO / "tests" / "screens" / "harness.py"
AGENT_PYTHON = REPO / ".venv" / "bin" / "python"
SCENARIO_TIMEOUT = 120
# The windows go to a headless nested Wayland session (KWin's virtual
# output), so they never show on the user's desktop. Tall enough for the
# harness's window. WHITTLE_SCREENS_VISIBLE=1 shows them instead; without
# it, a run that cannot have the hidden session stops rather than open
# windows on the desktop.
HIDDEN_SOCKET = "wayland-whittle"
HIDDEN_SIZE = (1600, 2200)


def blender_env(user_dir: Path) -> dict:
    """The Blender user folders point into the work folder, so a GUI run
    (recent files, preferences) never writes to the user's own config. The
    agent is always the fake one from the dev venv."""
    env = dict(os.environ)
    for name in ("WHITTLE_LIVE", "ANTHROPIC_API_KEY"):
        env.pop(name, None)
    # Blender falls back to the real user folder for a folder that does not
    # exist (the recent-files list did), so each one is made first.
    root = WORK / "blender-user"
    env["BLENDER_USER_RESOURCES"] = str(root)
    for kind in ("config", "scripts", "extensions", "datafiles"):
        folder = root / kind
        folder.mkdir(parents=True, exist_ok=True)
        env[f"BLENDER_USER_{kind.upper()}"] = str(folder)
    env["WHITTLE_USER_DIR"] = str(user_dir)
    env["WHITTLE_AGENT_PYTHON"] = str(AGENT_PYTHON)
    hidden = hidden_display()
    if hidden:
        env.pop("DISPLAY", None)
        env["WAYLAND_DISPLAY"] = hidden
    return env


def hidden_display() -> str | None:
    """The socket of the hidden session, started if it is not running; None
    when it is turned off. Exits when it cannot be had."""
    if os.environ.get("WHITTLE_SCREENS_VISIBLE") == "1":
        return None
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    kwin = shutil.which("kwin_wayland")
    if not runtime:
        _no_hidden_session("XDG_RUNTIME_DIR is not set")
    if not kwin:
        _no_hidden_session("kwin_wayland is not installed")
    path = Path(runtime) / HIDDEN_SOCKET
    if path.exists() and not _listening(path):
        # Left by a session that died: every Blender would fail to connect.
        path.unlink(missing_ok=True)
    if not path.exists():
        env = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
        WORK.mkdir(parents=True, exist_ok=True)
        with open(WORK / "kwin.log", "a") as log:
            # Outlives this run on purpose: the next one reuses it.
            subprocess.Popen([kwin, "--virtual", "--width", str(HIDDEN_SIZE[0]),
                              "--height", str(HIDDEN_SIZE[1]), "--socket", HIDDEN_SOCKET,
                              "--no-lockscreen", "--no-global-shortcuts"],
                             env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(40):
            if path.exists():
                break
            time.sleep(0.25)
        else:
            _no_hidden_session(f"the hidden session did not start (see {WORK / 'kwin.log'})")
    return HIDDEN_SOCKET


def _listening(path: Path) -> bool:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        try:
            probe.connect(str(path))
        except OSError:
            return False
    return True


def _no_hidden_session(why: str):
    raise SystemExit(f"screens: {why}, so the windows cannot be hidden. "
                     "Set WHITTLE_SCREENS_VISIBLE=1 to show them on your desktop instead.")


def make_base_blend(path: Path) -> None:
    """A factory-startup file to open: a .blend on the command line skips the
    splash screen. Factory preferences are saved into the work folder's
    config too, since Blender greets a config folder without them with its
    first-run splash, file or not."""
    path.parent.mkdir(parents=True, exist_ok=True)
    code = ("import bpy, sys; bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1]); "
            "bpy.ops.wm.save_userpref()")
    subprocess.run(["timeout", str(SCENARIO_TIMEOUT), "blender", "-b", "--factory-startup",
                    "--python-expr", code, "--", str(path)],
                   env=blender_env(WORK / "user"), check=True, stdout=subprocess.DEVNULL)


def shoot(name: str, wide: bool, base: Path) -> dict | None:
    """Runs one scenario in its own GUI Blender; returns its meta, or None
    when it produced no image."""
    label = f"wide/{name}" if wide else name
    work = WORK / ("wide-" + name if wide else name)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    blend = work / "scene.blend"
    shutil.copyfile(base, blend)
    png = OUT / f"{label}.png"
    png.unlink(missing_ok=True)
    meta = work / "meta.json"
    width, height = catalog.WINDOW
    cmd = ["timeout", str(SCENARIO_TIMEOUT), "blender", "--factory-startup", "--enable-event-simulate",
           "--no-window-focus", "--window-geometry", "0", "0", str(width), str(height),
           str(blend), "--python", str(HARNESS), "--",
           "--scenario", name, "--out", str(png), "--meta", str(meta), "--work", str(work)]
    if wide:
        cmd += ["--wide", str(catalog.WIDE_FACTOR)]
    log = work / "blender.log"
    print(f"screens: {label} ...", flush=True)
    with open(log, "w") as out:
        code = subprocess.run(cmd, env=blender_env(work / "user"), stdout=out, stderr=subprocess.STDOUT,
                              cwd=work).returncode
    if code != 0 or not png.is_file() or not meta.is_file():
        tail = log.read_text(errors="replace").splitlines()[-25:]
        print(f"screens: {label} FAILED (exit {code}); the end of {log}:", file=sys.stderr)
        print("\n".join("    " + line for line in tail), file=sys.stderr)
        return None
    data = json.loads(meta.read_text())
    data["png"] = str(png.relative_to(OUT))
    data["variant"] = "wide" if wide else "default"
    print(f"screens: {label} -> {png.relative_to(REPO)} {data['size'][0]}x{data['size'][1]}"
          f" ({data['pages']} page(s), {data['seconds']} s)", flush=True)
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="screens.sh", description=__doc__.split("\n\n")[0])
    parser.add_argument("scenarios", nargs="*", help="scenarios to shoot (default: all): "
                                                     + ", ".join(catalog.SCENARIOS))
    args = parser.parse_args(argv)
    unknown = [n for n in args.scenarios if n not in catalog.SCENARIOS]
    if unknown:
        parser.error(f"unknown scenario(s): {', '.join(unknown)}")
    names = args.scenarios or list(catalog.SCENARIOS)
    runs = [(n, False) for n in names] + [(n, True) for n in names if n in catalog.WIDE]

    OUT.mkdir(parents=True, exist_ok=True)
    base = WORK / "base.blend"
    make_base_blend(base)
    index_path = OUT / "index.json"
    try:
        index = json.loads(index_path.read_text())["screens"]
    except (OSError, ValueError, KeyError):
        index = []
    failed = []
    for name, wide in runs:
        data = shoot(name, wide, base)
        variant = "wide" if wide else "default"
        index = [e for e in index if (e["scenario"], e["variant"]) != (name, variant)]
        if data is None:
            failed.append(f"wide/{name}" if wide else name)
        else:
            index.append(data)
    # Earlier entries whose image is gone are dropped; the rest keep the
    # catalog's order.
    order = {n: i for i, n in enumerate(catalog.SCENARIOS)}
    index = sorted((e for e in index if (OUT / e["png"]).is_file() and e["scenario"] in order),
                   key=lambda e: (order[e["scenario"]], e["variant"]))
    index_path.write_text(json.dumps({"screens": index}, indent=1) + "\n")
    if failed:
        print(f"screens: {len(failed)} failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"screens: {len(runs)} image(s) in {OUT.relative_to(REPO)}; index in {index_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
