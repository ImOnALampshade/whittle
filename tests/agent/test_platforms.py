# SPDX-License-Identifier: GPL-3.0-or-later
"""The Windows branches run here on any OS: the platform is passed in and
kernel32 is a fake that records its calls."""

import ctypes
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from whittle import platforms

POSIX = sys.platform != "win32"


class FakeKernel:
    """kernel32 as platforms uses it. Handles are small ints; `fail` names
    calls that fail, with `error` as the last error."""

    def __init__(self, *, fail=(), error=0, exit_code=platforms.STILL_ACTIVE):
        self.fail = set(fail)
        self.error = error
        self.code = exit_code
        self.calls = []
        self.open_handles = set()
        self._next = 100

    def _handle(self):
        self._next += 1
        self.open_handles.add(self._next)
        return self._next

    def create_job(self):
        self.calls.append(("create_job",))
        return None if "create_job" in self.fail else self._handle()

    def kill_on_close(self, job):
        self.calls.append(("kill_on_close", job))
        return "kill_on_close" not in self.fail

    def assign(self, job, process):
        self.calls.append(("assign", job, process))
        return "assign" not in self.fail

    def terminate_job(self, job, code):
        self.calls.append(("terminate_job", job, code))
        return "terminate_job" not in self.fail

    def open_process(self, access, pid):
        self.calls.append(("open_process", access, pid))
        return None if "open_process" in self.fail else self._handle()

    def exit_code(self, process):
        return self.code

    def close(self, handle):
        self.calls.append(("close", handle))
        self.open_handles.discard(handle)

    def last_error(self):
        return self.error


class FakePopen:
    pid = 4242

    def __init__(self):
        self.killed = 0
        self.signals = []

    def kill(self):
        self.killed += 1

    def send_signal(self, sig):
        self.signals.append(sig)


class SpawnOptionsTest(unittest.TestCase):
    def test_posix_starts_a_session_and_shows_no_flags(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                self.assertEqual(platforms.own_group(platform), {"start_new_session": True})
                self.assertEqual(platforms.hidden_window(platform), {})

    def test_windows_hides_the_console_and_makes_a_group(self):
        self.assertEqual(platforms.hidden_window("win32"), {"creationflags": 0x08000000})
        self.assertEqual(platforms.own_group("win32"), {"creationflags": 0x08000000 | 0x00000200})
        if sys.platform == "win32":
            self.assertEqual(platforms.CREATE_NO_WINDOW, subprocess.CREATE_NO_WINDOW)
            self.assertEqual(platforms.CREATE_NEW_PROCESS_GROUP, subprocess.CREATE_NEW_PROCESS_GROUP)

    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, "64-bit layout")
    def test_extended_limits_has_the_x64_layout(self):
        # sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION) on Windows x64.
        self.assertEqual(ctypes.sizeof(platforms.ExtendedLimits), 144)
        self.assertEqual(platforms.ExtendedLimits.BasicLimitInformation.offset, 0)
        self.assertEqual(platforms.ExtendedLimits.IoInfo.offset, 64)


class PidAliveTest(unittest.TestCase):
    @unittest.skipUnless(POSIX, "POSIX probe")
    def test_posix(self):
        self.assertTrue(platforms.pid_alive(os.getpid(), "linux"))
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        self.assertFalse(platforms.pid_alive(proc.pid, "linux"))
        self.assertFalse(platforms.pid_alive(2 ** 80, "linux"))

    def test_windows_running(self):
        kernel = FakeKernel()
        self.assertTrue(platforms.pid_alive(1234, "win32", kernel))
        self.assertEqual(kernel.calls[0], ("open_process", platforms.PROCESS_QUERY_LIMITED_INFORMATION, 1234))
        self.assertEqual(kernel.open_handles, set(), "the handle is closed")

    def test_windows_exited(self):
        kernel = FakeKernel(exit_code=0)
        self.assertFalse(platforms.pid_alive(1234, "win32", kernel))
        self.assertEqual(kernel.open_handles, set())

    def test_windows_access_denied_is_alive(self):
        kernel = FakeKernel(fail={"open_process"}, error=platforms.ERROR_ACCESS_DENIED)
        self.assertTrue(platforms.pid_alive(1234, "win32", kernel))

    def test_windows_no_such_process(self):
        kernel = FakeKernel(fail={"open_process"}, error=87)
        self.assertFalse(platforms.pid_alive(1234, "win32", kernel))

    def test_windows_out_of_range(self):
        kernel = FakeKernel()
        for pid in (0, -1, 2 ** 32, True):
            with self.subTest(pid=pid):
                self.assertFalse(platforms.pid_alive(pid, "win32", kernel))
        self.assertEqual(kernel.calls, [])


class PosixTreeTest(unittest.TestCase):
    def test_signals_go_to_the_group(self):
        popen = FakePopen()
        tree = platforms.ProcessTree(popen, platform="linux")
        with mock.patch.object(platforms.os, "killpg", create=True) as killpg:
            tree.terminate()
            tree.kill()
        self.assertEqual(killpg.call_args_list, [mock.call(4242, signal.SIGTERM),
                                                 mock.call(4242, getattr(signal, "SIGKILL", 9))])
        self.assertEqual(popen.signals, [])

    def test_falls_back_to_the_process(self):
        popen = FakePopen()
        tree = platforms.ProcessTree(popen, platform="darwin")
        with mock.patch.object(platforms.os, "killpg", create=True, side_effect=ProcessLookupError):
            tree.terminate()
        self.assertEqual(popen.signals, [signal.SIGTERM])

    @unittest.skipUnless(POSIX, "process groups")
    def test_kill_reaches_the_grandchild(self):
        tmp = Path(tempfile.mkdtemp(prefix="whittle-tree-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        pidfile = tmp / "grandchild"
        script = ("import subprocess, sys, time; "
                  "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                  f"open({str(pidfile)!r}, 'w').write(str(p.pid)); time.sleep(60)")
        popen = subprocess.Popen([sys.executable, "-c", script], **platforms.own_group())
        self.addCleanup(popen.wait, 10)
        deadline = time.monotonic() + 10
        while not pidfile.exists() or not pidfile.read_text():
            self.assertLess(time.monotonic(), deadline, "the grandchild never started")
            time.sleep(0.02)
        grandchild = int(pidfile.read_text())
        platforms.ProcessTree(popen).kill()
        popen.wait(timeout=10)
        deadline = time.monotonic() + 10
        while platforms.pid_alive(grandchild) and not _zombie(grandchild):
            self.assertLess(time.monotonic(), deadline, "the grandchild outlived the kill")
            time.sleep(0.02)


def _zombie(pid: int) -> bool:
    # A killed grandchild whose parent died first waits for init to reap it.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] == "Z"
    except OSError:
        return False


class WindowsTreeTest(unittest.TestCase):
    def test_joins_a_kill_on_close_job(self):
        kernel = FakeKernel()
        tree = platforms.ProcessTree(FakePopen(), platform="win32", kernel=kernel)
        self.assertIsNotNone(tree.job)
        names = [call[0] for call in kernel.calls]
        self.assertEqual(names, ["create_job", "open_process", "kill_on_close", "assign", "close"])
        self.assertEqual(kernel.calls[1], ("open_process",
                                           platforms.PROCESS_SET_QUOTA | platforms.PROCESS_TERMINATE, 4242))
        self.assertEqual(kernel.open_handles, {tree.job}, "only the job stays open")

    def test_terminate_and_kill_end_the_job(self):
        for method in ("terminate", "kill"):
            with self.subTest(method=method):
                kernel, popen = FakeKernel(), FakePopen()
                run = mock.Mock()
                tree = platforms.ProcessTree(popen, platform="win32", kernel=kernel, run=run)
                getattr(tree, method)()
                self.assertIn(("terminate_job", tree.job, 1), kernel.calls)
                self.assertEqual(popen.killed, 1)
                self.assertEqual(popen.signals, [])
                run.assert_not_called()

    def test_close_releases_the_job(self):
        kernel = FakeKernel()
        tree = platforms.ProcessTree(FakePopen(), platform="win32", kernel=kernel)
        job = tree.job
        tree.close()
        tree.close()
        self.assertIsNone(tree.job)
        self.assertEqual(kernel.calls.count(("close", job)), 1)
        self.assertEqual(kernel.open_handles, set())

    def test_without_a_job_kill_uses_taskkill(self):
        for fail in ("create_job", "open_process", "assign"):
            with self.subTest(fail=fail):
                kernel, popen = FakeKernel(fail={fail}), FakePopen()
                run = mock.Mock()
                with self.assertLogs("whittle", "WARNING"):
                    tree = platforms.ProcessTree(popen, platform="win32", kernel=kernel, run=run)
                self.assertIsNone(tree.job)
                self.assertEqual(kernel.open_handles, set(), "nothing is left open")
                tree.kill()
                argv = run.call_args.args[0]
                self.assertEqual(argv, ["taskkill", "/T", "/F", "/PID", "4242"])
                self.assertEqual(run.call_args.kwargs["creationflags"], platforms.CREATE_NO_WINDOW)
                self.assertEqual(run.call_args.kwargs["timeout"], platforms.TASKKILL_TIMEOUT)
                self.assertEqual(popen.killed, 1)

    def test_a_failed_taskkill_still_kills_the_process(self):
        popen = FakePopen()
        run = mock.Mock(side_effect=subprocess.TimeoutExpired("taskkill", 5))
        with self.assertLogs("whittle", "WARNING"):
            tree = platforms.ProcessTree(popen, platform="win32", kernel=FakeKernel(fail={"create_job"}),
                                         run=run)
            tree.kill()
        self.assertEqual(popen.killed, 1)


class ReplaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-replace-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src, self.dst = self.tmp / "new", self.tmp / "old"
        self.src.write_text("new")
        self.dst.write_text("old")
        self.sleeps = []

    def test_replaces(self):
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform):
                self.src.write_text("new")
                platforms.replace(self.src, self.dst, platform=platform, sleep=self.sleeps.append)
                self.assertEqual(self.dst.read_text(), "new")
                self.assertFalse(self.src.exists())
        self.assertEqual(self.sleeps, [])

    def test_posix_does_not_retry(self):
        with mock.patch.object(platforms.os, "replace", side_effect=PermissionError) as replace:
            with self.assertRaises(PermissionError):
                platforms.replace(self.src, self.dst, platform="linux", sleep=self.sleeps.append)
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_windows_retries_a_held_file(self):
        real = os.replace
        outcomes = [PermissionError(13, "in use"), PermissionError(13, "in use"), None]

        def flaky(src, dst):
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome
            real(src, dst)

        with mock.patch.object(platforms.os, "replace", side_effect=flaky):
            platforms.replace(self.src, self.dst, platform="win32", sleep=self.sleeps.append)
        self.assertEqual(self.dst.read_text(), "new")
        self.assertEqual(self.sleeps, list(platforms.REPLACE_DELAYS[:2]))

    def test_windows_gives_up(self):
        with mock.patch.object(platforms.os, "replace", side_effect=PermissionError) as replace:
            with self.assertRaises(PermissionError):
                platforms.replace(self.src, self.dst, platform="win32", sleep=self.sleeps.append)
        self.assertEqual(replace.call_count, len(platforms.REPLACE_DELAYS) + 1)
        self.assertEqual(self.sleeps, list(platforms.REPLACE_DELAYS))
        self.assertLess(sum(self.sleeps), 1.5)

    def test_other_errors_are_not_retried(self):
        with mock.patch.object(platforms.os, "replace", side_effect=FileNotFoundError) as replace:
            with self.assertRaises(FileNotFoundError):
                platforms.replace(self.src, self.dst, platform="win32", sleep=self.sleeps.append)
        self.assertEqual(replace.call_count, 1)


if __name__ == "__main__":
    unittest.main()
