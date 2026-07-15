"""
Windows Job Objects give us what pytest-timeout's thread-mode kill cannot:
a guaranteed kill of the *entire* process tree (worker interpreter +
Chromium + any Node helper processes Playwright spawns), even if the
worker is stuck mid-teardown holding stdout/stderr handles.

Any process created by a process that's already assigned to the Job
Object automatically becomes part of the job (unless it explicitly uses
CREATE_BREAKAWAY_FROM_JOB), so as long as we assign the worker's PID to
the job *before* it launches a browser, terminating the job kills
everything underneath it in one shot.
"""

import contextlib
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import win32api
    import win32con
    import win32job

    class JobObject:
        def __init__(self):
            self.handle = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(
                self.handle, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                self.handle, win32job.JobObjectExtendedLimitInformation, info
            )

        def assign(self, pid: int):
            # Least privilege: AssignProcessToJobObject only needs the
            # rights to set quota/limits and to terminate the process, so
            # open the worker with just those instead of PROCESS_ALL_ACCESS.
            access = win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE
            proc_handle = win32api.OpenProcess(access, False, pid)
            win32job.AssignProcessToJobObject(self.handle, proc_handle)

        def terminate(self):
            """Hard-kills every process currently in the job."""
            win32job.TerminateJobObject(self.handle, 1)

        def close(self):
            win32api.CloseHandle(self.handle)

else:
    # POSIX fallback (dev/testing off Windows): real process-group kill.
    # Not used in the CI path described in the brief, but keeps the engine
    # runnable/testable on non-Windows machines.
    import os
    import signal

    class JobObject:
        def __init__(self):
            self._pid = None

        def assign(self, pid: int):
            # The worker puts ITSELF in a new process group (pgid ==
            # its own pid) as the very first thing it does, before it
            # can launch any browser/node helper -- see
            # worker.run_worker()'s os.setpgid(0, 0) call. That has to
            # happen from inside the worker: POSIX only allows
            # setpgid() on a *different* process if that process hasn't
            # exec'd yet, and by the time this parent-side assign() runs
            # (right after Process.start() returns), the spawned
            # interpreter has already exec'd -- calling os.setpgid(pid,
            # pid) from here reliably raises EACCES. So this side just
            # records the pid; terminate() below relies on the worker's
            # own self-assigned pgid (== pid) to target the whole tree.
            self._pid = pid

        def terminate(self):
            if self._pid is None:
                return
            try:
                os.killpg(self._pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # The worker's own os.setpgid(0, 0) hasn't happened yet
                # (killed extremely early, before it got to run) or
                # isn't supported in this sandboxed environment -- fall
                # back to killing just the leader rather than raising
                # out of a hard-kill path.
                with contextlib.suppress(ProcessLookupError):
                    os.kill(self._pid, signal.SIGKILL)

        def close(self):
            pass
