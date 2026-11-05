# SPDX-License-Identifier: GPL-3.0-or-later
"""Shoots the docs site's screenshots: `./docs_shots.sh <page-slug> [shot ...]`,
`--all`, `--list` or `--check`. Specs are docs/site/shots/<page-slug>.py; the
images go to docs/site/images/<page-slug>/<shot>.png.

Many of these may run at once. Each Blender gets a hidden nested Wayland
session of its own (kwin_wayland --virtual, on its own socket and with its
own KDE folders) and its own Blender and Whittle folders under
build/docs-shots/<run>/, and holds one of a machine-wide number of slots. An
image is replaced only by a complete shot. Stdlib only."""

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.docshots import slots, spec as specs  # noqa: E402
from tests.screens.run import _listening  # noqa: E402

WORK = REPO / "build" / "docs-shots"
SLOTS = WORK / "slots"
IMAGES = REPO / "docs" / "site" / "images"
# Pages named _* are examples: their images stay out of the site.
EXAMPLES = WORK / "images"
HARNESS = REPO / "tests" / "docshots" / "harness.py"
AGENT_PYTHON = REPO / ".venv" / "bin" / "python"
BLENDER_FOLDERS = ("config", "scripts", "extensions", "datafiles")
# Every process a run starts carries this in its environment, whatever it
# spawned from or however it detached, so all of them can be found.
TAG = "WHITTLE_DOCSHOTS_RUN"
# Startup, loading the add-on and quitting, on top of the harness's deadline.
OVERHEAD = 45
SESSION_START = 30.0
PROFILE_STEP = 300
# A run's folder (kept after a failure, for its logs) and a superseded
# profile go after a day.
STALE = 86400.0

stopping = threading.Event()


def log(message: str) -> None:
    print(f"docshots: {message}", flush=True)


# -- processes ----------------------------------------------------------------

def tagged_processes(tag: str) -> dict[int, str]:
    """Every process whose run tag equals tag or lies under it."""
    wanted = f"{TAG}={tag}".encode()
    found = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            environ = (proc / "environ").read_bytes().split(b"\0")
            if any(item == wanted or item.startswith(wanted + b"/") for item in environ):
                found[int(proc.name)] = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
    return found


def stop_processes(tag: str, patience: float = 3.0) -> list[str]:
    """Ends every process of a run: TERM, then KILL for what is left.
    Returns what had to be stopped."""
    left = tagged_processes(tag)
    stopped = [f"{pid}: {cmd[:120]}" for pid, cmd in left.items()]
    for sig, wait in ((signal.SIGTERM, patience), (signal.SIGKILL, 2.0)):
        for pid in left:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        deadline = time.monotonic() + wait
        while (left := tagged_processes(tag)) and time.monotonic() < deadline:
            time.sleep(0.05)
        if not left:
            break
    return stopped


def reap_orphans() -> None:
    """Stops what a run killed outright left behind: a tag names its
    driver's pid."""
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            environ = (proc / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        for item in environ:
            if item.startswith(f"{TAG}=".encode()):
                run = item.split(b"=", 1)[1].decode(errors="replace").split("/")[0]
                pid = run.rsplit("-", 2)[-2] if run.count("-") >= 2 else ""
                if pid.isdigit() and not Path(f"/proc/{pid}").exists():
                    stop_processes(run)
                break


# A virtual output has no input devices, so KWin's seat would have no pointer,
# and Blender dies on the first pointer grab (the sidebar's edge being dragged).
# A button rebind makes KWin add a device of its own for it to send, which gives
# the seat its pointer; nothing presses the button.
KWIN_INPUT = "[ButtonRebinds][Mouse]\nExtraButton3=Key,Ctrl++\n"


def has_shell(path: Path, wait: float = 2.0) -> bool:
    """Whether the compositor on this socket offers windows yet: wl_display's
    get_registry and sync, then read what it announces. KWin listens well
    before it has xdg_wm_base, and a Blender that connects in that gap gives up
    or hangs."""
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(wait)
        try:
            client.connect(str(path))
            client.sendall(struct.pack("=IIIIII", 1, 12 << 16 | 1, 2, 1, 12 << 16, 3))
            data = b""
            while True:
                while len(data) >= 8:
                    target, word = struct.unpack_from("=II", data)
                    if len(data) < word >> 16:
                        break
                    if target == 2 and b"xdg_wm_base\0" in data[:word >> 16]:
                        return True
                    if target == 3:
                        return False
                    data = data[word >> 16:]
                chunk = client.recv(65536)
                if not chunk:
                    return False
                data += chunk
        except OSError:
            return False


class HiddenSession:
    """A nested KWin no one can see, on a socket of its own, with KDE's
    config and cache folders its own and off the session bus, so it shares
    nothing with the desktop or with any other session."""

    def __init__(self, work: Path, tag: str, limit: float):
        self.work = work
        self.tag = tag
        self.limit = limit
        self.socket = f"wayland-whittle-docs-{uuid.uuid4().hex[:12]}"
        self.path = Path(os.environ.get("XDG_RUNTIME_DIR", "")) / self.socket
        self.log = work / "kwin.log"
        self.process = None

    def __enter__(self):
        kwin = shutil.which("kwin_wayland")
        if not kwin:
            raise SystemExit("kwin_wayland is not installed: the windows cannot be hidden, so nothing was shot")
        if not os.environ.get("XDG_RUNTIME_DIR"):
            raise SystemExit("XDG_RUNTIME_DIR is not set: the windows cannot be hidden, so nothing was shot")
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
        env[TAG] = self.tag
        for variable, folder in (("XDG_CONFIG_HOME", "kde-config"), ("XDG_CACHE_HOME", "kde-cache"),
                                 ("XDG_DATA_HOME", "kde-data")):
            env[variable] = str(self.work / folder)
            (self.work / folder).mkdir(parents=True, exist_ok=True)
        (self.work / "kde-config" / "kcminputrc").write_text(KWIN_INPUT)
        width, height = specs.OUTPUT
        with open(self.log, "w") as out:
            self.process = subprocess.Popen(
                ["timeout", "-s", "KILL", str(int(self.limit)), kwin, "--virtual", "--width", str(width),
                 "--height", str(height), "--socket", self.socket, "--no-lockscreen", "--no-global-shortcuts"],
                env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                cwd=self.work)
        deadline = time.monotonic() + SESSION_START
        while not (self.path.exists() and _listening(self.path) and has_shell(self.path)):
            if time.monotonic() > deadline or self.process.poll() is not None:
                self.close()
                raise RuntimeError(f"the hidden session did not start (see {self.log})")
            time.sleep(0.05)
        return self

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for path in (self.path, self.path.with_name(self.path.name + ".lock")):
            path.unlink(missing_ok=True)

    def __exit__(self, *exc) -> None:
        self.close()


def run_bounded(cmd: list, limit: float, **kwargs) -> int:
    """Runs a command under timeout, in a process group of its own; 137 means
    it ran out of time. (timeout kills it even if this process is gone.)"""
    process = subprocess.Popen(["timeout", "-s", "KILL", str(int(limit))] + [str(c) for c in cmd],
                               stdin=subprocess.DEVNULL, start_new_session=True, **kwargs)
    try:
        return process.wait(timeout=limit + 10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        return 137


# -- Blender's folders --------------------------------------------------------

def blender_env(root: Path, work: Path, tag: str, display: str | None = None, cache: Path | None = None) -> dict:
    """Blender's user folders at root, made first (Blender falls back to the
    real one for a folder that does not exist), and everything else a run
    writes in work. No key or live setting of the user's comes along, the
    agent is the fake one from the dev venv, and without a display of its
    own there is none at all, so no window can reach the desktop.

    cache is one Blender's alone: Blender keeps compiled GPU programs in its
    cache folder, and one reading a file another is writing crashes in the
    driver. A slot's folder stays warm from run to run."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("WHITTLE_LIVE", "DISPLAY", "WAYLAND_DISPLAY")
           and not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_"))}
    env["BLENDER_USER_RESOURCES"] = str(root)
    for kind in BLENDER_FOLDERS:
        folder = root / kind
        folder.mkdir(parents=True, exist_ok=True)
        env[f"BLENDER_USER_{kind.upper()}"] = str(folder)
    tmp = work / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for name in ("TMPDIR", "TEMP", "TMP"):
        env[name] = str(tmp)
    env["WHITTLE_USER_DIR"] = str(work / "user")
    env["WHITTLE_AGENT_PYTHON"] = str(AGENT_PYTHON)
    cache = cache or work / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    env["XDG_CACHE_HOME"] = str(cache)
    env["__GL_SHADER_DISK_CACHE_PATH"] = str(cache)
    env["LC_ALL"] = "C.UTF-8"
    env["TZ"] = "UTC"
    env[TAG] = tag
    if display:
        env["WAYLAND_DISPLAY"] = display
    return env


def source_digest() -> str:
    """What the installed extension depends on, so an edit makes a new one."""
    digest = hashlib.sha256()
    files = [p for p in (REPO / "whittle").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    for path in sorted(files + [REPO / "build.sh"]):
        digest.update(str(path.relative_to(REPO)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build_profile(folder: Path, tag: str) -> None:
    """Blender's user folders as every shot starts from them: factory
    preferences and Whittle installed as a user would, with build.sh's zip
    and Blender's own extension command, into the default local repository
    (whose place follows the user folders, so copies of it work), and the
    factory startup file to open (a .blend on the command line skips the
    splash screen). One shader worker: by default a Blender makes a GPU context
    per core or so, and four of them at once on a 32-core machine crash in the
    NVIDIA driver on the first Grease Pencil draw."""
    root = folder / "blender-user"
    env = blender_env(root, folder, tag)
    quiet = {"env": env, "stdout": subprocess.DEVNULL, "cwd": REPO}
    code = ("import bpy, sys; bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1]); "
            "bpy.context.preferences.system.gpu_shader_workers = 1; bpy.ops.wm.save_userpref()")
    steps = [
        ["blender", "-b", "--factory-startup", "--python-expr", code, "--", folder / "base.blend"],
        [REPO / "build.sh", folder / "package"],
    ]
    for step in steps:
        if run_bounded(step, PROFILE_STEP, **quiet) != 0:
            raise RuntimeError(f"preparing Whittle failed at: {' '.join(str(s) for s in step)}")
    (archive,) = (folder / "package").glob("whittle-*.zip")
    step = ["blender", "--command", "extension", "install-file", "--repo", "user_default", "--enable", archive]
    if run_bounded(step, PROFILE_STEP, **quiet) != 0:
        raise RuntimeError(f"installing {archive.name} failed")
    if not (root / "extensions" / "user_default" / "whittle" / "blender_manifest.toml").is_file():
        raise RuntimeError(f"Whittle was not installed into {root}")
    shutil.rmtree(folder / "package")
    shutil.rmtree(folder / "tmp", ignore_errors=True)
    shutil.rmtree(folder / "cache", ignore_errors=True)


def ensure_profile(run: str) -> Path:
    """The profile for the current source, built once however many runs
    want it at the same moment."""
    digest = source_digest()
    folder = WORK / f"profile-{digest}"
    if (folder / "ready").is_file():
        return folder
    wait = slots.wait_limit()
    with slots.exclusive(WORK / "profile.lock", wait, stopping.is_set, lambda _s: log("waiting for Whittle to be built")):
        if (folder / "ready").is_file():
            return folder
        with slots.slot(SLOTS, slots.size(), wait, stopping.is_set):
            log(f"building and installing Whittle into a profile ({digest})")
            scratch = WORK / f"profile-{digest}.{run}"
            shutil.rmtree(scratch, ignore_errors=True)
            scratch.mkdir(parents=True)
            try:
                build_profile(scratch, f"{run}/profile")
                (scratch / "ready").write_text("")
                scratch.rename(folder)
            except BaseException:
                stop_processes(f"{run}/profile")
                shutil.rmtree(scratch, ignore_errors=True)
                raise
    return folder


def remove_stale() -> None:
    """Old profiles, and runs whose driver is gone, after a day."""
    if not WORK.is_dir():
        return
    now = time.time()
    for path in WORK.iterdir():
        try:
            old = now - path.stat().st_mtime > STALE
        except OSError:
            continue
        if old and path.is_dir() and path.name not in ("slots", "images"):
            shutil.rmtree(path, ignore_errors=True)


# -- shooting -----------------------------------------------------------------

def target(spec: specs.Spec, shot: str) -> Path:
    images = EXAMPLES if spec.slug.startswith("_") else IMAGES
    return images / spec.slug / f"{shot}.png"


def deliver(source: Path, destination: Path) -> str:
    """Puts a finished shot in place in one step, leaving an identical image
    alone."""
    data = source.read_bytes()
    if destination.is_file() and destination.read_bytes() == data:
        return "unchanged"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.stem}-", suffix=".tmp",
                                     delete=False) as out:
        out.write(data)
    Path(out.name).chmod(0o644)
    os.replace(out.name, destination)
    return "updated"


def _tail(path: Path, lines: int = 20) -> str:
    try:
        text = path.read_text(errors="replace").splitlines()[-lines:]
    except OSError:
        return "    (no log)"
    return "\n".join("    " + line for line in text)


def shoot_group(spec: specs.Spec, group: specs.Group, wanted: list, run_dir: Path, run: str, profile: Path) -> list:
    """Runs one group's Blender. Returns a (shot, error or None, line) per
    wanted shot; every shot that finished is delivered, whatever the rest did."""
    tag = f"{run}/{spec.slug}-{group.index}"
    work = run_dir / f"{spec.slug}-{group.index}"
    work.mkdir(parents=True)
    blender_log = work / "blender.log"
    deadline = group.deadline
    limit = deadline + OVERHEAD
    width, height = group.window
    started = time.monotonic()
    label = f"{spec.slug}/{group.label}"

    def waiting(seconds: float) -> None:
        log(f"{label}: waiting for a slot ({seconds:.0f} s so far; {slots.size()} Blenders at a time)")

    try:
        with slots.slot(SLOTS, slots.size(), slots.wait_limit(), stopping.is_set, waiting) as number:
            got_slot = time.monotonic()
            log(f"{label}: shooting {', '.join(wanted)}")
            root = work / "blender-user"
            shutil.copytree(profile / "blender-user", root, symlinks=True)
            blend = work / "scene.blend"
            shutil.copyfile(profile / "base.blend", blend)
            plan = {"spec": str(spec.path), "group": group.index, "wanted": wanted, "work": str(work),
                    "shots": str(work / "shots"), "deadline": deadline}
            (work / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
            with HiddenSession(work, tag, limit + 30) as session:
                env = blender_env(root, work, tag, session.socket, SLOTS / f"cache-{number}")
                cmd = ["blender", "--enable-event-simulate", "--no-window-focus", "--window-geometry", "0", "0",
                       width, height, blend, "--python", HARNESS, "--", work / "plan.json"]
                with open(blender_log, "w") as out:
                    code = run_bounded(cmd, limit, env=env, stdout=out, stderr=subprocess.STDOUT, cwd=work)
                stop_processes(tag)
    except (slots.SlotTimeout, RuntimeError) as exc:
        stop_processes(tag)
        return [(name, str(exc), "") for name in wanted]
    seconds = time.monotonic() - got_slot
    results = []
    for name in wanted:
        png, meta = work / "shots" / f"{name}.png", work / "shots" / f"{name}.json"
        if meta.is_file() and png.is_file():
            data = json.loads(meta.read_text())
            how = deliver(png, target(spec, name))
            where = target(spec, name).relative_to(REPO)
            results.append((name, None, f"{spec.slug}/{name} -> {where} {data['size'][0]}x{data['size'][1]} ({how})"))
        else:
            why = "ran out of time" if code in (137, -9) else f"exit {code}"
            results.append((name, f"no image ({why}); log: {blender_log}", ""))
    if code != 0 and not any(error for _n, error, _l in results):
        results[-1] = (results[-1][0], f"Blender exited {code} after the shots; log: {blender_log}", results[-1][2])
    log(f"{label}: {seconds:.1f} s for {len(wanted)} shot(s) in one Blender")
    return results


def plan_shots(args, parser) -> list:
    """(spec, group, wanted shots) for what the arguments ask for."""
    if args.all:
        paths = specs.spec_paths()
        if args.page:
            parser.error("--all takes no page")
    else:
        if not args.page:
            parser.error("name a page, or use --all, --list or --check")
        paths = [specs.SHOTS_DIR / f"{args.page}.py"]
        if not paths[0].is_file():
            known = ", ".join(p.stem for p in specs.spec_paths(examples=True))
            parser.error(f"no spec {paths[0].relative_to(REPO)}; there are: {known or 'none yet'}")
    plan = []
    for path in paths:
        spec = checked(path)
        names = [s.name for s in spec.shots]
        unknown = [n for n in args.shots if n not in names]
        if unknown:
            parser.error(f"{spec.slug} has no shot {', '.join(unknown)}; it has: {', '.join(names)}")
        for group in specs.groups(spec.shots):
            wanted = [s.name for s in group.shots if not args.shots or s.name in args.shots]
            if wanted:
                plan.append((spec, group, wanted))
    return plan


def checked(path: Path) -> specs.Spec:
    errors = problems(path)
    if errors:
        raise SystemExit("\n".join(f"docshots: {path.name}: {e}" for e in errors))
    return specs.load(path)


def problems(path: Path) -> list:
    """What is wrong with a spec, an import error included."""
    try:
        return specs.validate(specs.load(path))
    except Exception as exc:
        return [f"cannot be imported: {type(exc).__name__}: {exc}"]


def check_all() -> int:
    paths = specs.spec_paths(examples=True)
    failed = 0
    total = 0
    for path in paths:
        errors = problems(path)
        if errors:
            failed += 1
            for error in errors:
                print(f"docshots: {path.name}: {error}", file=sys.stderr)
        else:
            shots = specs.load(path).shots
            total += len(shots)
            print(f"docshots: {path.stem}: {len(shots)} shot(s) ok")
    if failed:
        print(f"docshots: {failed} of {len(paths)} spec(s) have problems", file=sys.stderr)
        return 1
    print(f"docshots: {len(paths)} spec(s), {total} shot(s) ok; nothing was launched")
    return 0


def list_all() -> int:
    for path in specs.spec_paths(examples=True):
        errors = problems(path)
        if errors:
            print(f"{path.stem}: has problems, see --check")
            continue
        spec = specs.load(path)
        for shot in spec.shots:
            kind = shot.capture.kind if shot.capture else "(the scenario's own)"
            how = f"scenario {shot.scenario}" if shot.scenario else f"setup {getattr(shot.setup, '__name__', '?')}"
            print(f"{spec.slug}/{shot.name}\t{kind}\t{how}\t{shot.description}")
    return 0


def on_signal(signum, _frame):
    stopping.set()
    raise KeyboardInterrupt(signal.Signals(signum).name)


def shoot_all(plan: list, keep: bool) -> int:
    pages = {spec.slug for spec, _group, _wanted in plan}
    run = f"{pages.pop() if len(pages) == 1 else 'all'}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    run_dir = WORK / run
    run_dir.mkdir(parents=True)
    results = []
    executor = ThreadPoolExecutor(max_workers=max(1, min(len(plan), slots.size())))
    started = time.monotonic()
    try:
        profile = ensure_profile(run)
        futures = [(spec, group, executor.submit(shoot_group, spec, group, wanted, run_dir, run, profile))
                   for spec, group, wanted in plan]
        for spec, group, future in futures:
            for name, error, line in future.result():
                results.append((spec.slug, name, error))
                if error:
                    print(f"docshots: {spec.slug}/{name} FAILED: {error}", file=sys.stderr, flush=True)
                    log_path = run_dir / f"{spec.slug}-{group.index}" / "blender.log"
                    print(_tail(log_path), file=sys.stderr, flush=True)
                else:
                    log(line)
    except (KeyboardInterrupt, SystemExit, RuntimeError, slots.SlotTimeout) as exc:
        stopping.set()
        print(f"docshots: stopped: {exc}; logs in {run_dir}", file=sys.stderr, flush=True)
        stop_processes(run)
        return 1
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        stop_processes(run)
    failed = [r for r in results if r[2]]
    seconds = time.monotonic() - started
    if failed:
        print(f"docshots: {len(failed)} of {len(results)} failed; existing images kept; logs in {run_dir}",
              file=sys.stderr)
        return 1
    if not keep:
        shutil.rmtree(run_dir, ignore_errors=True)
    log(f"{len(results)} shot(s) in {seconds:.1f} s")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="docs_shots.sh", description=__doc__.split("\n\n")[0])
    parser.add_argument("page", nargs="?", default="", help="the page's slug (guides/api-key is guides-api-key)")
    parser.add_argument("shots", nargs="*", help="only these of its shots")
    parser.add_argument("--all", action="store_true", help="every page's shots (not specs named _*)")
    parser.add_argument("--list", action="store_true", help="list every shot, launching nothing")
    parser.add_argument("--check", action="store_true", help="import and validate every spec, launching nothing")
    parser.add_argument("--keep", action="store_true", help="keep the run's folder after a success")
    args = parser.parse_args(argv)
    if args.check:
        return check_all()
    if args.list:
        return list_all()
    plan = plan_shots(args, parser)
    if not plan:
        parser.error("nothing to shoot")
    try:
        slots.size()
    except ValueError as exc:
        parser.error(str(exc))
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, on_signal)
    WORK.mkdir(parents=True, exist_ok=True)
    reap_orphans()
    remove_stale()
    return shoot_all(plan, args.keep)


if __name__ == "__main__":
    sys.exit(main())
