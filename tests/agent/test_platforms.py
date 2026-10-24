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


DAY = 24 * 3600.0
PREFIX = "C--Users-me-AppData-Roaming-Whittle-cache-"


class ResumeFoldersTest(unittest.TestCase):
    """The SDK's claude-resume-* folders a killed Windows agent leaves."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-resume-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.now = time.time()
        self.made = {}

    def folder(self, name, *, age=2 * DAY, made_age=None, project=PREFIX + "abc-chats-c1"):
        """A resume folder as the SDK makes one, unchanged for age seconds and
        made made_age (default age) seconds ago."""
        folder = self.tmp / name
        session = folder / "projects" / project
        session.mkdir(parents=True)
        (session / "0000.jsonl").write_text("{}\n")
        (folder / ".credentials.json").write_text("{}")
        when = self.now - age
        for path in (session / "0000.jsonl", folder / ".credentials.json", session, folder / "projects", folder):
            os.utime(path, (when, when))
        self.made[folder] = self.now - (age if made_age is None else made_age)
        return folder

    def times(self, folder):
        # Linux has no creation time to set: the folder's comes from the test.
        return self.made[folder], platforms.folder_times(folder)[1]

    def clear(self, starts=(), platform="win32"):
        return platforms.clear_stale_resume_folders(self.tmp, PREFIX, list(starts), platform=platform,
                                                    now=self.now, times=self.times)

    def test_removes_a_stale_folder_of_whittles(self):
        stale = self.folder("claude-resume-old")
        self.assertEqual(self.clear(), [stale])
        self.assertFalse(stale.exists())

    def test_posix_does_nothing(self):
        stale = self.folder("claude-resume-old")
        self.assertEqual(self.clear(platform="linux"), [])
        self.assertEqual(self.clear(platform="darwin"), [])
        self.assertTrue(stale.exists())

    def test_keeps_a_folder_changed_within_a_day(self):
        fresh = self.folder("claude-resume-fresh", age=DAY - 600)
        touched = self.folder("claude-resume-touched", made_age=3 * DAY)
        # The CLI wrote to the transcript an hour ago: the folder is in use.
        jsonl = next((touched / "projects").rglob("*.jsonl"))
        os.utime(jsonl, (self.now - 3600, self.now - 3600))
        self.assertEqual(self.clear(), [])
        self.assertTrue(fresh.exists() and touched.exists())

    def test_never_one_a_live_agent_may_own(self):
        """A live agent's folder was made after it started: a folder made
        after the earliest live agent's start (less the slack) stays, however
        long unchanged."""
        before = self.folder("claude-resume-before", age=3 * DAY)
        after = self.folder("claude-resume-after", age=2 * DAY)
        close = self.folder("claude-resume-close", age=2.5 * DAY)
        started = self.now - 2.5 * DAY - platforms.RESUME_SLACK / 2
        self.assertEqual(self.clear([self.now - DAY, started]), [before])
        self.assertTrue(after.exists() and close.exists())
        self.assertEqual(self.clear([]), [after, close], "once no agent runs, both are stale")

    def test_only_whittles_folders(self):
        other = self.folder("claude-resume-other", project="C--Users-me-code-some-other-app")
        empty = self.tmp / "claude-resume-empty"
        empty.mkdir()
        self.made[empty] = self.now - 9 * DAY
        os.utime(empty, (self.now - 9 * DAY,) * 2)
        unrelated = self.folder("something-else")
        self.assertEqual(self.clear(), [])
        self.assertTrue(other.exists() and empty.exists() and unrelated.exists())

    @unittest.skipUnless(POSIX, "symlinks need privileges on Windows")
    def test_never_follows_a_link(self):
        target = self.folder("target")
        (self.tmp / "claude-resume-link").symlink_to(target, target_is_directory=True)
        self.assertEqual(self.clear(), [])
        self.assertTrue(target.exists())

    def test_a_folder_that_cannot_be_removed_is_skipped(self):
        first, second = self.folder("claude-resume-a"), self.folder("claude-resume-b")
        failed = []

        def rmtree(path):
            if path == first:
                failed.append(path)
                raise PermissionError(13, "in use")
            shutil.rmtree(path)

        with self.assertLogs("whittle", "WARNING"):
            removed = platforms.clear_stale_resume_folders(self.tmp, PREFIX, [], platform="win32", now=self.now,
                                                           times=self.times, rmtree=rmtree)
        self.assertEqual((removed, failed), ([second], [first]))
        self.assertTrue(first.exists())

    def test_folder_times(self):
        folder = self.folder("claude-resume-x", age=5 * DAY)
        made, touched = platforms.folder_times(folder)
        self.assertAlmostEqual(touched, self.now - 5 * DAY, delta=1)
        inner = next((folder / "projects").rglob("*.jsonl"))
        os.utime(inner, (self.now, self.now))
        self.assertAlmostEqual(platforms.folder_times(folder)[1], self.now, delta=1, msg="the newest inside counts")
        self.assertLessEqual(made, self.now + 1)


class AgentRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="whittle-agents-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = self.tmp / "agents"

    def test_windows_records_live_agents(self):
        platforms.note_agent(self.folder, 101, 1000.0, platform="win32")
        platforms.note_agent(self.folder, 202, 2000.0, platform="win32")
        (self.folder / "303.json").write_text("not json")
        alive = {101}.__contains__
        self.assertEqual(platforms.live_agent_starts(self.folder, alive=alive, platform="win32"), [1000.0])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["101.json"],
                         "gone agents' and unreadable records go")
        platforms.forget_agent(self.folder, 101, platform="win32")
        self.assertEqual(list(self.folder.iterdir()), [])
        platforms.forget_agent(self.folder, 101, platform="win32")

    def test_posix_records_nothing(self):
        platforms.note_agent(self.folder, 101, 1000.0, platform="linux")
        self.assertFalse(self.folder.exists())
        self.assertEqual(platforms.live_agent_starts(self.folder, alive=lambda pid: True), [])

    def test_windows_probes_with_kernel32_by_default(self):
        platforms.note_agent(self.folder, 101, 1000.0, platform="win32")
        with mock.patch.object(platforms, "pid_alive", return_value=True) as probe:
            self.assertEqual(platforms.live_agent_starts(self.folder, platform="win32"), [1000.0])
        probe.assert_called_once_with(101, "win32")


if __name__ == "__main__":
    unittest.main()
