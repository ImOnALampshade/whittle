# SPDX-License-Identifier: GPL-3.0-or-later
"""What differs between Linux, Windows and macOS: starting a child process
without a console window, stopping it together with everything it started,
asking whether a pid is alive, and replacing a file another program holds
open.

Stdlib only, so the add-on and the agent-side tests share it. Every function
takes the platform (a `sys.platform` value) and, on Windows, the kernel32
calls it makes as arguments, so the tests cover each branch on any OS. Linux
and macOS share the POSIX branch.
"""

import ctypes
import logging
import os
import signal
import subprocess
import sys
import time

log = logging.getLogger("whittle")

WINDOWS = "win32"

# Process creation flags (winbase.h). subprocess only defines them on Windows.
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

# Process access rights and codes (winnt.h, winerror.h, minwinbase.h).
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5
STILL_ACTIVE = 259

# Job objects (winnt.h).
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

# How long a replace keeps retrying a file that something else has open:
# about a second in all, enough for a virus scanner or indexer to let go.
REPLACE_DELAYS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.4)
TASKKILL_TIMEOUT = 5.0


def is_windows(platform: str = sys.platform) -> bool:
    return platform == WINDOWS


# -- starting a process ------------------------------------------------------------

def hidden_window(platform: str = sys.platform) -> dict:
    """Popen keywords for a helper process (venv, pip): on Windows a console
    program started from Blender's window would flash a console window of
    its own."""
    return {"creationflags": CREATE_NO_WINDOW} if is_windows(platform) else {}


def own_group(platform: str = sys.platform) -> dict:
    """Popen keywords that start a process in a group of its own, so it can
    be stopped together with the processes it starts (ProcessTree). On
    Windows the group only matters to console control events; the Job
    Object does the stopping, and the hidden console is inherited by the
    children, so none of them shows a window."""
    if is_windows(platform):
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}
    return {"start_new_session": True}


# -- kernel32 -----------------------------------------------------------------------

class _BasicLimits(ctypes.Structure):
    # JOBOBJECT_BASIC_LIMIT_INFORMATION
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimits(ctypes.Structure):
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class Kernel32:
    """The kernel32 calls Whittle makes, through ctypes. Handles are ints and
    0 or None means the call failed (last_error() says why). Built only on
    Windows; the tests hand in a fake with the same methods."""

    def __init__(self):
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        self._create_job = _bind(dll.CreateJobObjectW, handle, [ctypes.c_void_p, ctypes.c_wchar_p])
        self._set_job = _bind(dll.SetInformationJobObject, boolean,
                              [handle, ctypes.c_int, ctypes.c_void_p, dword])
        self._assign = _bind(dll.AssignProcessToJobObject, boolean, [handle, handle])
        self._terminate_job = _bind(dll.TerminateJobObject, boolean, [handle, ctypes.c_uint])
        self._open = _bind(dll.OpenProcess, handle, [dword, boolean, dword])
        self._exit_code = _bind(dll.GetExitCodeProcess, boolean, [handle, ctypes.POINTER(dword)])
        self._close = _bind(dll.CloseHandle, boolean, [handle])

    def create_job(self) -> int | None:
        return self._create_job(None, None)

    def kill_on_close(self, job: int) -> bool:
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        return bool(self._set_job(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                  ctypes.byref(limits), ctypes.sizeof(limits)))

    def assign(self, job: int, process: int) -> bool:
        return bool(self._assign(job, process))

    def terminate_job(self, job: int, code: int) -> bool:
        return bool(self._terminate_job(job, code))

    def open_process(self, access: int, pid: int) -> int | None:
        return self._open(access, False, pid)

    def exit_code(self, process: int) -> int | None:
        code = ctypes.c_uint32()
        return code.value if self._exit_code(process, ctypes.byref(code)) else None

    def close(self, handle: int) -> None:
        self._close(handle)

    def last_error(self) -> int:
        return ctypes.get_last_error()


def _bind(function, restype, argtypes):
    function.restype = restype
    function.argtypes = argtypes
    return function


def _kernel32(kernel):
    return kernel if kernel is not None else Kernel32()


# -- is a process alive -----------------------------------------------------------------

def pid_alive(pid: int, platform: str = sys.platform, kernel=None) -> bool:
    """Whether a process with this pid runs on this machine. On Windows
    os.kill(pid, 0) is no probe (signal 0 is CTRL_C_EVENT), so the process
    is opened and asked for its exit code instead."""
    if not is_windows(platform):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except (OverflowError, ValueError):
            return False
        return True
    if not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid < 2 ** 32:
        return False
    try:
        kernel = _kernel32(kernel)
    except (OSError, AttributeError):
        return False
    handle = kernel.open_process(PROCESS_QUERY_LIMITED_INFORMATION, pid)
    if not handle:
        # Another user's process (or a protected one) cannot be opened, but
        # it is there.
        return kernel.last_error() == ERROR_ACCESS_DENIED
    try:
        return kernel.exit_code(handle) == STILL_ACTIVE
    finally:
        kernel.close(handle)


# -- stopping a process with its children --------------------------------------------

class ProcessTree:
    """A child process started with own_group(), and everything it starts.

    POSIX: the child leads its own process group, and terminate() and kill()
    signal the whole group. Windows has no such signals: the child goes into
    a Job Object that kills every process in it when its last handle closes,
    so the processes it starts die with it even when Blender crashes. There
    terminate() is as hard as kill(), since TerminateProcess is all Windows
    offers a process without a console of the caller's; a graceful stop goes
    through the bridge's shutdown call instead. Processes the child starts
    before it is assigned are not in the job, which is why it is assigned
    right after it starts, long before the agent starts the CLI."""

    def __init__(self, popen, *, platform: str = sys.platform, kernel=None, run=subprocess.run):
        self.popen = popen
        self.platform = platform
        self._run = run
        self._kernel = None
        self.job: int | None = None
        if is_windows(platform):
            self._join_job(kernel)

    def terminate(self) -> None:
        if is_windows(self.platform):
            self.kill()
        else:
            self._signal(signal.SIGTERM)

    def kill(self) -> None:
        if not is_windows(self.platform):
            self._signal(signal.SIGKILL)
            return
        if self.job is None or not self._kernel.terminate_job(self.job, 1):
            self._taskkill()
        try:
            self.popen.kill()
        except OSError:
            pass

    def close(self) -> None:
        """Lets go of the job; on Windows anything still in it is killed.
        Call it once the process has exited or must not outlive this."""
        if self.job is not None:
            self._kernel.close(self.job)
            self.job = None

    def _signal(self, sig) -> None:
        try:
            os.killpg(self.popen.pid, sig)
        except (AttributeError, ProcessLookupError, PermissionError):
            self.popen.send_signal(sig)

    def _join_job(self, kernel) -> None:
        try:
            self._kernel = _kernel32(kernel)
        except (OSError, AttributeError) as exc:
            log.warning("no job object for process %d: %s", self.popen.pid, exc)
            return
        job = self._kernel.create_job()
        if not job:
            log.warning("no job object for process %d: error %d", self.popen.pid,
                        self._kernel.last_error())
            return
        process = self._kernel.open_process(PROCESS_SET_QUOTA | PROCESS_TERMINATE, self.popen.pid)
        joined = bool(process) and self._kernel.kill_on_close(job) and self._kernel.assign(job, process)
        error = self._kernel.last_error()
        if process:
            self._kernel.close(process)
        if joined:
            self.job = job
            return
        self._kernel.close(job)
        log.warning("process %d is not in a job object (error %d): stopping it falls back "
                    "to taskkill", self.popen.pid, error)

    def _taskkill(self) -> None:
        # Without a job: taskkill /T stops the child and its descendants.
        try:
            self._run(["taskkill", "/T", "/F", "/PID", str(self.popen.pid)], stdin=subprocess.DEVNULL,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=TASKKILL_TIMEOUT,
                      check=False, **hidden_window(self.platform))
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("taskkill of process %d failed: %s", self.popen.pid, exc)


# -- files ---------------------------------------------------------------------------

def replace(src, dst, *, platform: str = sys.platform, sleep=time.sleep) -> None:
    """os.replace. On Windows a file that another program has open without
    delete sharing (a virus scanner, an indexer, another Blender reading
    it) cannot be replaced for a moment, so that is retried for about a
    second before the error stands."""
    if not is_windows(platform):
        os.replace(src, dst)
        return
    for delay in REPLACE_DELAYS:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            sleep(delay)
    os.replace(src, dst)
