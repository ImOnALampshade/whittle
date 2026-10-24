# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from whittle import venv
from whittle.venv import Step, VenvSetup, VenvStatus

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "agent_env" / "requirements.lock"
PINNED_SDK = "0.2.167"


class LockTest(unittest.TestCase):
    def test_pins(self):
        pins = venv.read_pins(LOCK)
        self.assertEqual(len(pins), 30)
        self.assertEqual(pins["claude-agent-sdk"], PINNED_SDK)

    def test_every_pin_has_a_hash(self):
        hashes = venv.lock_hashes(LOCK)
        self.assertEqual(set(hashes), set(venv.read_pins(LOCK)))
        for name, found in hashes.items():
            with self.subTest(package=name):
                self.assertTrue(found)
                self.assertTrue(all(h.startswith("sha256:") for h in found))

    def test_digest_follows_the_bytes(self):
        tmp = Path(tempfile.mkdtemp(prefix="whittle-lock-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        copy = tmp / "requirements.lock"
        shutil.copyfile(LOCK, copy)
        self.assertEqual(venv.lock_digest(copy), venv.lock_digest(LOCK))
        copy.write_bytes(LOCK.read_bytes() + b"\n")
        self.assertNotEqual(venv.lock_digest(copy), venv.lock_digest(LOCK))


class CommandTest(unittest.TestCase):
    base = Path("/usr/bin/python3.14")
    target = Path("/tmp/whittle-venv")

    def test_install_command_is_exact(self):
        python = venv.venv_python(self.target, "linux")
        self.assertEqual(venv.install_command(python, LOCK), [
            str(python), "-I", "-u", "-m", "pip", "install", "--isolated",
            "--disable-pip-version-check", "--no-input", "--progress-bar", "raw", "--require-hashes",
            "--only-binary", ":all:", "--no-deps", "-r", str(LOCK)])

    def test_install_command_never_upgrades_or_changes_the_index(self):
        argv = venv.install_command(venv.venv_python(self.target), LOCK)
        for banned in ("--upgrade", "-U", "--index-url", "-i", "--extra-index-url", "--pre",
                       "--force-reinstall"):
            self.assertNotIn(banned, argv)
        self.assertFalse([a for a in argv if "git+" in a or "github:" in a])

    def test_create_command(self):
        base, target = str(self.base), str(self.target)
        self.assertEqual(venv.create_command(self.base, self.target),
                         [base, "-I", "-m", "venv", target])
        self.assertEqual(venv.create_command(self.base, self.target, clear=True),
                         [base, "-I", "-m", "venv", "--clear", target])

    def test_verify_command_is_isolated(self):
        argv = venv.verify_command(Path("/v/bin/python"))
        self.assertEqual(argv[:3], [str(Path("/v/bin/python")), "-I", "-c"])
        self.assertIn("claude-agent-sdk", argv[3])

    def test_venv_python(self):
        self.assertEqual(venv.venv_python(Path("/v"), "linux"), Path("/v/bin/python"))
        self.assertEqual(venv.venv_python(Path("/v"), "win32"), Path("/v/Scripts/python.exe"))

    def test_plan(self):
        for reinstall in (False, True):
            with self.subTest(reinstall=reinstall):
                steps = venv.plan(self.base, self.target, LOCK, reinstall=reinstall)
                self.assertEqual([s.name for s in steps], ["create", "install", "verify"])
                self.assertEqual([s.timeout for s in steps], [120.0, 3 * 3600.0, 60.0])
                self.assertEqual([s.stall for s in steps], [None, 300.0, None])
                self.assertEqual(steps[0].argv[0], str(self.base))
                self.assertEqual("--clear" in steps[0].argv, reinstall)
                python = str(venv.venv_python(self.target))
                self.assertEqual(steps[1].argv[0], python)
                self.assertEqual(steps[2].argv[0], python)

    def test_subprocess_env(self):
        env = venv.subprocess_env({
            "PATH": "/usr/bin", "HOME": "/home/u", "HTTPS_PROXY": "http://proxy:3128",
            "SSL_CERT_FILE": "/etc/ca.pem", "PIP_INDEX_URL": "http://evil", "PIP_EXTRA_INDEX_URL": "x",
            "PYTHONPATH": "/x", "PYTHONHOME": "/y", "VIRTUAL_ENV": "/z", "UV_INDEX_URL": "u",
            "UV_PYTHON": "p", "CONDA_PREFIX": "c"})
        self.assertEqual(env, {"PATH": "/usr/bin", "HOME": "/home/u", "HTTPS_PROXY": "http://proxy:3128",
                               "SSL_CERT_FILE": "/etc/ca.pem"})

    def test_compatible(self):
        # platform.machine() says AMD64 on Windows, arm64 on Apple silicon,
        # aarch64 on Linux arm64 (arm64 on some distributions).
        for machine, platform in (("x86_64", "linux"), ("aarch64", "linux"), ("arm64", "linux"),
                                  ("AMD64", "win32"), ("arm64", "darwin")):
            with self.subTest(platform=platform):
                self.assertIsNone(venv.compatible((3, 14, 8), machine, platform))
        self.assertIn("3.14", venv.compatible((3, 13, 1), "x86_64", "linux"))
        self.assertIn("3.14", venv.compatible((3, 15, 0), "arm64", "darwin"))
        for machine, platform in (("armv7l", "linux"), ("riscv64", "linux"), ("ARM64", "win32")):
            with self.subTest(platform=platform, machine=machine):
                reason = venv.compatible((3, 14, 0), machine, platform)
                self.assertIn(machine, reason)
                self.assertIn(venv.SUPPORTED_TEXT, reason)
        self.assertIn("freebsd14", venv.compatible((3, 14, 0), "amd64", "freebsd14"))

    def test_intel_macs_are_refused_with_the_reason(self):
        reason = venv.compatible((3, 14, 0), "x86_64", "darwin")
        self.assertIn("Apple silicon", reason)
        self.assertIn("cryptography", reason)

    def test_bundled_cli_name(self):
        self.assertEqual(venv.bundled_cli_name("linux"), "claude")
        self.assertEqual(venv.bundled_cli_name("darwin"), "claude")
        self.assertEqual(venv.bundled_cli_name("win32"), "claude.exe")

    def test_verify_script_looks_for_the_platform_cli(self):
        tmp = Path(tempfile.mkdtemp(prefix="whittle-verify-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "_bundled").mkdir()
        (tmp / "_bundled" / "claude.exe").write_bytes(b"MZ")
        sdk = types.ModuleType("claude_agent_sdk")
        sdk.__file__ = str(tmp / "__init__.py")
        for platform, cli in (("win32", True), ("linux", False)):
            with self.subTest(platform=platform):
                out = StringIO()
                with mock.patch.dict(sys.modules, {"claude_agent_sdk": sdk}), \
                        mock.patch.object(sys, "platform", platform), \
                        mock.patch("importlib.metadata.version", return_value=PINNED_SDK), \
                        redirect_stdout(out):
                    exec(venv.VERIFY_SCRIPT, {})
                line = out.getvalue().strip()
                self.assertTrue(line.startswith(venv.VERIFY_PREFIX))
                self.assertEqual(json.loads(line[len(venv.VERIFY_PREFIX):]),
                                 {"sdk": PINNED_SDK, "cli": cli})


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-venv-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.venv = self.tmp / "venv"

    def make_python(self):
        python = venv.venv_python(self.venv)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.symlink_to(sys.executable)
        return python

    def test_each_status(self):
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.MISSING)
        self.venv.mkdir()
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.MISSING, "an empty folder")
        (self.venv / "something").write_text("x")
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.FOREIGN)
        venv.write_marker(self.venv, LOCK, sdk=None, base_python=Path(sys.executable), complete=False)
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.BROKEN, "an unfinished setup")
        venv.write_marker(self.venv, LOCK, sdk=PINNED_SDK, base_python=Path(sys.executable))
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.BROKEN, "no python")
        self.make_python()
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.READY)
        other = self.tmp / "other.lock"
        other.write_bytes(LOCK.read_bytes() + b"# changed\n")
        self.assertEqual(venv.status(self.venv, other), VenvStatus.STALE)

    def test_dangling_python_is_broken(self):
        python = venv.venv_python(self.venv)
        python.parent.mkdir(parents=True)
        python.symlink_to(self.tmp / "gone" / "python3.14")
        venv.write_marker(self.venv, LOCK, sdk=PINNED_SDK, base_python=Path(sys.executable))
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.BROKEN)

    def windows_venv(self, home: Path):
        python = venv.venv_python(self.venv, "win32")
        python.parent.mkdir(parents=True)
        python.write_bytes(b"MZ")
        python.chmod(0o755)
        (self.venv / "pyvenv.cfg").write_text(f"home = {home}\ninclude-system-site-packages = false\n"
                                              "version = 3.14.0\n")
        venv.write_marker(self.venv, LOCK, sdk=PINNED_SDK, base_python=home / "python.exe")

    def test_windows_venv_whose_base_python_is_gone_is_broken(self):
        # A Windows venv's python.exe is a copy that stays behind.
        base = self.tmp / "Blender" / "5.2" / "python" / "bin"
        base.mkdir(parents=True)
        self.windows_venv(base)
        self.assertEqual(venv.base_home(self.venv), base)
        self.assertEqual(venv.status(self.venv, LOCK, "win32"), VenvStatus.READY)
        shutil.rmtree(self.tmp / "Blender")
        self.assertEqual(venv.status(self.venv, LOCK, "win32"), VenvStatus.BROKEN)

    def test_pyvenv_home_is_only_read_on_windows(self):
        python = self.make_python()
        (self.venv / "pyvenv.cfg").write_text(f"home = {self.tmp / 'gone'}\n")
        venv.write_marker(self.venv, LOCK, sdk=PINNED_SDK, base_python=python)
        self.assertEqual(venv.status(self.venv, LOCK, "linux"), VenvStatus.READY)

    def test_base_home(self):
        self.venv.mkdir()
        self.assertIsNone(venv.base_home(self.venv))
        (self.venv / "pyvenv.cfg").write_text("version = 3.14.0\n")
        self.assertIsNone(venv.base_home(self.venv))
        (self.venv / "pyvenv.cfg").write_text("Home=C:\\Program Files\\Blender\\python\\bin \n")
        self.assertEqual(venv.base_home(self.venv), Path("C:\\Program Files\\Blender\\python\\bin"))

    def test_marker_is_written_atomically(self):
        self.venv.mkdir()
        venv.write_marker(self.venv, LOCK, sdk=PINNED_SDK, base_python=Path("/usr/bin/python3.14"))
        marker = json.loads((self.venv / venv.MARKER).read_text())
        self.assertEqual(marker["lock_sha256"], venv.lock_digest(LOCK))
        self.assertEqual(marker["sdk"], PINNED_SDK)
        self.assertTrue(marker["complete"])
        self.assertEqual([p.name for p in self.venv.iterdir()], [venv.MARKER])


class FakeProc:
    """A step that exits with `code` after `runs` polls, printing `output`
    into the log it was handed."""

    def __init__(self, argv, stdout, code=0, runs=1, output="", exits_on_terminate=True, trickle=""):
        self.argv = argv
        self.stdout = stdout
        self.code = code
        self.runs = runs
        self.output = output
        # Written on every poll while running, like pip's progress lines.
        self.trickle = trickle
        self.exits_on_terminate = exits_on_terminate
        self.terminated = self.killed = False
        self.returncode = None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if self.runs > 0:
            self.runs -= 1
            if self.trickle:
                self.stdout.write(self.trickle.encode())
                self.stdout.flush()
            return None
        if self.output:
            self.stdout.write(self.output.encode())
            self.stdout.flush()
        self.returncode = self.code
        return self.code

    def terminate(self):
        self.terminated = True
        if self.exits_on_terminate:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode


def verify_output(sdk=PINNED_SDK, cli=True):
    return f"{venv.VERIFY_PREFIX}{json.dumps({'sdk': sdk, 'cli': cli})}\n"


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-setup-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.venv = self.tmp / "venv"
        self.log = self.tmp / "logs" / "venv.log"
        self.now = 0.0
        self.procs = []
        self.behaviour = {}
        self.finished = []

    def clock(self):
        return self.now

    def popen(self, argv, **kwargs):
        name = "create" if "venv" in argv else "install" if "pip" in argv else "verify"
        kw = dict(self.behaviour.get(name, {}))
        if name == "verify":
            kw.setdefault("output", verify_output())
        proc = FakeProc(argv, kwargs["stdout"], **kw)
        proc.kwargs = kwargs
        proc.name = name
        self.procs.append(proc)
        return proc

    def setup(self, *, dry_run=False, env=None, platform="linux"):
        steps = venv.plan(Path(sys.executable), self.venv, LOCK)
        return VenvSetup(steps, venv=self.venv, lock=LOCK, log_path=self.log, dry_run=dry_run,
                         popen=self.popen, clock=self.clock, env=env or {"PATH": "/usr/bin"},
                         on_finish=self.finished.append, platform=platform)

    def until_step(self, setup, name):
        for _ in range(10):
            if setup.step == name:
                return self.procs[-1]
            setup.tick()
        self.fail(f"{name} never started")

    def run_out(self, setup, limit=50):
        for _ in range(limit):
            if setup.tick() is None:
                return
            self.now += 0.25
        self.fail("the setup never finished")

    def test_dry_run_runs_nothing(self):
        setup = self.setup(dry_run=True)
        setup.start()
        self.assertEqual(setup.state, "done")
        self.assertEqual(self.procs, [])
        self.assertFalse(self.venv.exists())
        commands = [line for line in self.log.read_text().splitlines() if line.startswith("$ ")]
        self.assertEqual(len(commands), 3)
        self.assertIn("--require-hashes --only-binary :all: --no-deps -r", commands[1])
        self.assertEqual(self.finished, [setup])

    def test_success(self):
        setup = self.setup(env={"PATH": "/usr/bin", "PIP_INDEX_URL": "http://evil", "PYTHONPATH": "/x"})
        setup.start()
        self.assertEqual(setup.state, "running")
        self.run_out(setup)
        self.assertEqual(setup.state, "done", setup.reason)
        self.assertEqual([p.name for p in self.procs], ["create", "install", "verify"])
        for proc in self.procs:
            self.assertEqual(proc.kwargs["env"], {"PATH": "/usr/bin"})
            self.assertIs(proc.kwargs["stdin"], subprocess.DEVNULL)
            self.assertNotIn("creationflags", proc.kwargs)
        marker = venv.read_marker(self.venv)
        self.assertEqual(marker["lock_sha256"], venv.lock_digest(LOCK))
        self.assertTrue(marker["complete"])
        self.assertEqual(marker["sdk"], PINNED_SDK)
        self.assertEqual(self.finished, [setup])

    def test_windows_steps_open_no_console_window(self):
        setup = self.setup(platform="win32")
        setup.start()
        self.run_out(setup)
        self.assertEqual(setup.state, "done", setup.reason)
        self.assertEqual(len(self.procs), 3)
        for proc in self.procs:
            self.assertEqual(proc.kwargs["creationflags"], 0x08000000)

    def test_verify_mismatch_fails(self):
        for output in (verify_output(sdk="0.2.166"), verify_output(cli=False), "nothing\n"):
            with self.subTest(output=output):
                shutil.rmtree(self.venv, ignore_errors=True)
                self.procs = []
                self.behaviour = {"verify": {"output": output}}
                setup = self.setup()
                setup.start()
                self.run_out(setup)
                self.assertEqual(setup.state, "failed")
                self.assertFalse(venv.read_marker(self.venv)["complete"])
                self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.BROKEN)

    def test_install_failure_stops_before_verify(self):
        self.behaviour = {"install": {"code": 1, "output": "ERROR: hash mismatch for anyio\n"}}
        setup = self.setup()
        setup.start()
        self.run_out(setup)
        self.assertEqual(setup.state, "failed")
        self.assertEqual([p.name for p in self.procs], ["create", "install"])
        self.assertIn("install failed with exit code 1", setup.reason)
        self.assertIn("hash mismatch", setup.reason)

    def test_stall_terminates_then_kills(self):
        self.behaviour = {"install": {"runs": 10_000, "exits_on_terminate": False}}
        setup = self.setup()
        setup.start()
        install = self.until_step(setup, "install")
        stall = venv.STALL_TIMEOUTS["install"]
        self.now += stall - 1
        self.assertEqual(setup.tick(), venv.TICK)
        self.assertFalse(install.terminated)
        self.now += 2
        setup.tick()
        self.assertTrue(install.terminated)
        self.assertFalse(install.killed)
        self.now += 1
        self.assertEqual(setup.tick(), venv.TICK)
        self.assertFalse(install.killed)
        self.now += 1.5
        self.assertIsNone(setup.tick())
        self.assertTrue(install.killed)
        self.assertEqual((setup.state, setup.reason),
                         ("failed", f"install stalled: no progress for {stall:g} s"))

    def test_slow_download_that_keeps_progressing_is_not_cut_off(self):
        # A 114 MB wheel on a slow link (~67 KB/s) takes ~28 minutes, longer
        # than a fixed 15-minute cap would allow.
        self.behaviour = {"install": {"runs": 10_000, "trickle": "Progress 1 of 2\n"}}
        setup = self.setup()
        setup.start()
        install = self.until_step(setup, "install")
        for _ in range(int(3600 / 30)):
            self.now += 30
            self.assertEqual(setup.tick(), venv.TICK)
        self.assertFalse(install.terminated)
        self.assertEqual(setup.state, "running")

    def test_hard_cap_still_applies_while_progressing(self):
        self.behaviour = {"install": {"runs": 10**9, "trickle": "Progress 1 of 2\n"}}
        setup = self.setup()
        setup.start()
        install = self.until_step(setup, "install")
        self.now += venv.STEP_TIMEOUTS["install"] + 1
        setup.tick()
        self.assertTrue(install.terminated)
        self.assertIsNone(setup.tick())
        self.assertIn("install timed out after", setup.reason)

    def test_steps_without_stall_use_only_their_timeout(self):
        self.behaviour = {"create": {"runs": 10_000, "exits_on_terminate": True}}
        setup = self.setup()
        setup.start()
        create = self.procs[-1]
        self.now += venv.STEP_TIMEOUTS["create"] - 1
        setup.tick()
        self.assertFalse(create.terminated)
        self.now += 2
        setup.tick()
        self.assertTrue(create.terminated)

    def test_progress_reports_the_current_download(self):
        setup = self.setup()
        setup.start()
        self.until_step(setup, "install")
        with open(self.log, "a") as log:
            log.write("Collecting claude-agent-sdk==0.2.167 (from -r lock (line 124))\n"
                      "  Downloading claude_agent_sdk-0.2.167-py3-none-manylinux_2_17_x86_64.whl (114.1 MB)\n"
                      "Progress 0 of 114100000\nProgress 43100000 of 114100000\n")
        self.assertEqual(setup.progress(), ("claude_agent_sdk-0.2.167-py3-none-manylinux_2_17_x86_64.whl",
                                            43100000, 114100000))
        self.assertIn("43.1 / 114.1 MB", setup.describe_progress())
        self.assertFalse([line for line in setup.log_tail() if line.startswith("Progress ")])
        with open(self.log, "a") as log:
            log.write("Installing collected packages: claude-agent-sdk\n")
        self.assertIsNone(setup.progress())
        self.assertEqual(setup.describe_progress(), "install")

    def test_cancel(self):
        self.behaviour = {"install": {"runs": 10_000}}
        setup = self.setup()
        setup.start()
        install = self.until_step(setup, "install")
        setup.cancel(wait=1.0)
        self.assertTrue(install.terminated)
        self.assertEqual(setup.state, "cancelled")
        self.assertIsNone(setup.tick())
        self.assertEqual(venv.status(self.venv, LOCK), VenvStatus.BROKEN, "ours to rebuild, not foreign")
        self.assertEqual(self.finished, [setup])

    def test_real_subprocesses(self):
        python = sys.executable
        out = self.tmp / "ran.txt"
        steps = [Step("create", [python, "-I", "-c", f"open({str(out)!r}, 'a').write('create\\n')"], 30),
                 Step("install", [python, "-I", "-c", "print('installing'); import os; "
                                  "print('PIP_INDEX_URL' in os.environ)"], 30),
                 Step("verify", [python, "-I", "-c", f"print({verify_output().strip()!r})"], 30)]
        env = {**os.environ, "PIP_INDEX_URL": "http://evil.invalid"}
        setup = VenvSetup(steps, venv=self.venv, lock=LOCK, log_path=self.log, env=env)
        setup.start()
        deadline = 200
        while setup.tick() is not None and deadline:
            deadline -= 1
            time.sleep(0.05)
        self.assertEqual(setup.state, "done", "\n".join(setup.log_tail()))
        self.assertEqual(out.read_text(), "create\n")
        log = self.log.read_text()
        self.assertIn("installing\nFalse\n", log)
        self.assertEqual(venv.read_marker(self.venv)["sdk"], PINNED_SDK)


if __name__ == "__main__":
    unittest.main()
