"""Run a function in a killable child process — engine-free.

The reusable unit behind the web UI's background work: start it, poll its
progress, kill it instantly. The work runs in its own *process group*
(``os.setsid``), so ``kill()`` takes down the whole tree — including any
subprocess a worker shells out to. (Scoring runs pure in-process Python with no
children, so for it this is just a plain process kill; a future bench-run worker
will shell out to an engine, and the group kill reaps that tree too.)

The worker is any module-level ``fn(report, *args)`` — ``report(done, total)``
streams progress back. The wrapper frames completion: a clean return sends
``("done",)``, an exception sends ``("error", message)``. Messages arrive over a
Queue; the caller drains them with :meth:`drain`.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import signal
from typing import Callable

# A worker reports progress through this; the rest of the protocol (done/error)
# is added by _session_wrapper so workers stay free of bookkeeping.
Report = Callable[[int, int], None]


class BackgroundProc:
    def __init__(self, target: Callable[..., None], args: tuple = ()) -> None:
        self._target = target
        self._args = args
        self._q: mp.Queue = mp.Queue()
        self._proc: mp.Process | None = None

    def start(self) -> None:
        self._proc = mp.Process(
            target=_session_wrapper, args=(self._target, self._q, self._args),
            daemon=True)
        self._proc.start()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def drain(self) -> list[tuple]:
        """Pending worker messages, oldest first: ``("progress", done, total)``,
        ``("done",)``, or ``("error", message)``."""
        out: list[tuple] = []
        try:
            while True:
                out.append(self._q.get_nowait())
        except queue.Empty:
            pass
        return out

    def kill(self) -> None:
        """Stop the work immediately: SIGTERM the process group, escalating to
        SIGKILL if it does not exit. No-op if never started or already gone."""
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


def _session_wrapper(target: Callable[..., None], q: mp.Queue, args: tuple) -> None:
    os.setsid()  # own process group, so the parent's killpg reaps any children
    try:
        target(lambda done, total: q.put(("progress", done, total)), *args)
        q.put(("done",))
    except Exception as exc:  # surface the failure to the poller
        q.put(("error", str(exc)))
