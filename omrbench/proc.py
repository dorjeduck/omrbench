"""Run work under a wall-clock budget, killably — engine-free.

One concept, one place: *run a unit of work that may not stop cooperatively
(wedged in a C call, or an external process that ignores signals) and be able to
force-kill it after a time budget.* Two substrates need it, so this module has
two surfaces over a shared POSIX process-group tree-kill (``setsid`` +
``killpg``, SIGTERM→SIGKILL):

1. **A command** — an external program (an OMR engine). ``run_command`` /
   ``capture_command`` shell out; each command gets its own process group, so a
   timeout kills the whole tree (e.g. ``poetry`` -> ``homr``) without touching
   the caller.

2. **A Python function** — engine-free work (scoring) that, to be interruptible
   at all, must run in a child process. ``Job`` runs a module-level
   ``fn(progress, *args)`` in a killable child; ``run_blocking`` drives one to
   completion synchronously (for the CLI). ``progress(done, total)`` streams
   back over a Queue; the wrapper frames completion (``("done", result)``) and
   failure (``("error", message)``).

The two compose: a ``Job`` worker may ``run_command``. The Job child is its own
session, and so is each command, so the Job's group-kill would not reap an
in-flight command. The child therefore tracks its active command group and, on
SIGTERM (which ``Job.kill`` sends before SIGKILL), kills it first — so Stop reaps
the engine tree and per-command timeouts kill the tree, with stdlib only.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import signal
import subprocess
import threading
import time
from typing import Any, Callable

# A worker reports progress through this; the rest of the protocol (done/error)
# is added by _session_wrapper so workers stay free of bookkeeping.
Progress = Callable[[int, int], None]

# The process group of the command the current process is shelling out to, if
# any (set by _run while a command runs). Read by a Job child's SIGTERM handler
# so a Stop/timeout that targets the child also reaps the command tree.
_active_group: int | None = None


# --- shell out to a command -------------------------------------------------

def run_command(cmd: list[str], *, cwd=None, timeout: float | None = None) -> bool:
    """Run ``cmd``, returning True on exit code 0. Stdout/stderr pass through.

    ``timeout`` (seconds), when set, bounds the run: a command that does not
    finish in time has its whole process tree killed and False returned, so a
    hanging engine fails that one sample rather than freezing the run.
    """
    _, ok = _run(cmd, cwd, timeout, capture=False)
    return ok


def capture_command(cmd: list[str], *, cwd=None, timeout: float | None = None) -> str | None:
    """Run ``cmd`` and return its trimmed stdout, or None on failure/timeout.
    Used for cheap metadata probes (e.g. a version string); never raises."""
    out, ok = _run(cmd, cwd, timeout, capture=True)
    if not ok or not out:
        return None
    return out.strip() or None


def _run(cmd, cwd, timeout, capture) -> tuple[str | None, bool]:
    global _active_group
    pipe = subprocess.PIPE if capture else None
    try:
        proc = subprocess.Popen(  # noqa: S603 - cmd is caller-controlled
            cmd, cwd=cwd, start_new_session=True,
            stdout=pipe, stderr=pipe, text=capture or None)
    except OSError:
        return None, False
    _active_group = proc.pid  # new session => process-group id == pid
    try:
        out, _ = proc.communicate(timeout=timeout)
        return (out if isinstance(out, str) else None), proc.returncode == 0
    except subprocess.TimeoutExpired:
        _terminate(proc)
        return None, False
    finally:
        _active_group = None


def _terminate(proc: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL the command's process group, reaping the tree."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            break
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


# --- run a Python function in a killable child ------------------------------

class Job:
    """A module-level ``fn(progress, *args)`` running in a killable child process
    with an optional wall-clock ``timeout``. Poll :meth:`drain` for messages and
    :meth:`alive`; :meth:`kill` stops it (and any command it shelled out to)."""

    def __init__(
        self, target: Callable[..., Any], args: tuple = (),
        timeout: float | None = None,
    ) -> None:
        self._target = target
        self._args = args
        self._timeout = timeout
        self._q: mp.Queue = mp.Queue()
        self._proc: mp.Process | None = None
        self._timed_out = False

    def start(self) -> None:
        self._proc = mp.Process(
            target=_session_wrapper, args=(self._target, self._q, self._args),
            daemon=True)
        self._proc.start()
        if self._timeout is not None:
            threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self) -> None:
        """Enforce the wall-clock budget. Reports the timeout *before* killing so
        a poller's :meth:`drain` sees the cause rather than a bare exit."""
        proc = self._proc
        if proc is None:
            return
        proc.join(self._timeout)
        if proc.is_alive():
            self._timed_out = True
            self._q.put(("error", f"exceeded the {self._timeout:g}s time budget"))
            self.kill()

    @property
    def timed_out(self) -> bool:
        return self._timed_out

    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def drain(self) -> list[tuple]:
        """Pending worker messages, oldest first: ``("progress", done, total)``,
        ``("done", result)``, or ``("error", message)``."""
        out: list[tuple] = []
        try:
            while True:
                out.append(self._q.get_nowait())
        except queue.Empty:
            pass
        return out

    def kill(self) -> None:
        """Stop the work immediately: SIGTERM the process group, escalating to
        SIGKILL if it does not exit. The child's SIGTERM handler reaps any active
        command tree first. No-op if never started or already gone."""
        proc = self._proc
        if proc is None or proc.pid is None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not proc.is_alive():
                return
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except (ProcessLookupError, PermissionError):
                return
            proc.join(timeout=5)


def run_blocking(
    target: Callable[..., Any], args: tuple = (), *,
    timeout: float | None = None, on_progress: Progress | None = None,
) -> Any:
    """Run ``target`` in a killable child and block until it finishes, returning
    its value. Forwards progress to ``on_progress``. Raises ``TimeoutError`` if
    it outlives ``timeout``, ``RuntimeError`` if the worker fails. The synchronous
    counterpart to polling a :class:`Job` (used by the CLI)."""
    job = Job(target, args, timeout=timeout)
    job.start()
    error: str | None = None
    while True:
        for msg in job.drain():
            if msg[0] == "progress":
                if on_progress is not None:
                    on_progress(msg[1], msg[2])
            elif msg[0] == "done":
                return msg[1]
            elif msg[0] == "error":
                error = msg[1]
        if error is not None:
            break
        if not job.alive():
            error = "worker exited unexpectedly"
            continue  # one more drain to catch a terminal message in flight
        time.sleep(0.02)
    if job.timed_out:
        raise TimeoutError(error)
    raise RuntimeError(error)


def _session_wrapper(target: Callable[..., Any], q: mp.Queue, args: tuple) -> None:
    os.setsid()  # own process group, so the parent's killpg reaps any children
    signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        result = target(lambda done, total: q.put(("progress", done, total)), *args)
        q.put(("done", result))
    except Exception as exc:  # surface the failure to the poller
        q.put(("error", str(exc)))


def _on_sigterm(signum, frame) -> None:
    # Reap the command tree this worker is blocked on before we go, then exit;
    # the parent's killpg only reaches our group, not the command's own session.
    if _active_group is not None:
        try:
            os.killpg(_active_group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    os._exit(143)  # 128 + SIGTERM
