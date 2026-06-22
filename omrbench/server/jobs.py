"""Background scoring jobs for the web UI — engine-free.

Scoring a run with a heavy metric (omr-ned) takes minutes, so the web UI can't
compute it inside one request. Instead the server runs it on a daemon thread and
the client polls for progress. State lives in-memory for the life of the process
(a local, single-process server); a finished score is durable in its cache file,
so the in-memory record is only needed while a job runs.

The work itself is the same engine-free `scoring.score_run`; this module only
adds the run-in-background + progress bookkeeping.
"""

from __future__ import annotations

import threading

from omrbench import runs as runs_mod
from omrbench import scoring
from omrbench.score import get_metric

# (run_id, metric) -> {status: "running"|"done"|"error", done, total, error, cancel}
_jobs: dict[tuple[str, str], dict] = {}
_lock = threading.Lock()


class _Cancelled(Exception):
    """Raised inside the scoring loop to abort a job on request."""


def _is_cached(run_id: str, metric: str) -> bool:
    return runs_mod.load_run(run_id).score_path(metric).exists()


def start(run_id: str, metric: str) -> dict:
    """Begin scoring ``run_id`` with ``metric`` in the background (idempotent).
    Returns the current job state. Raises FileNotFoundError for an unknown run,
    KeyError for an unknown metric."""
    runs_mod.load_run(run_id)  # validate run exists
    get_metric(metric)          # validate metric exists
    key = (run_id, metric)
    if _is_cached(run_id, metric):
        return {"status": "done", "done": None, "total": None}
    with _lock:
        existing = _jobs.get(key)
        if existing and existing["status"] == "running":
            return dict(existing)
        _jobs[key] = {"status": "running", "done": 0, "total": None, "error": None}
    threading.Thread(target=_run, args=(run_id, metric), daemon=True).start()
    return {"status": "running", "done": 0, "total": None}


def status(run_id: str, metric: str) -> dict:
    """Current job state. A score already on disk reports ``done`` even if this
    process never ran it; a running job awaiting cancellation reports
    ``cancelling``; with no job and no cache it's ``idle``."""
    runs_mod.load_run(run_id)
    get_metric(metric)
    if _is_cached(run_id, metric):
        return {"status": "done", "done": None, "total": None}
    with _lock:
        job = _jobs.get((run_id, metric))
        if not job:
            return {"status": "idle"}
        out = dict(job)
        if job.get("cancel"):
            out["status"] = "cancelling"
        return out


def cancel(run_id: str, metric: str) -> dict:
    """Ask a running job to stop. It aborts at the next sample boundary, writes
    nothing (so the metric stays unscored), and the job record is dropped."""
    runs_mod.load_run(run_id)
    get_metric(metric)
    with _lock:
        job = _jobs.get((run_id, metric))
        if job and job["status"] == "running":
            job["cancel"] = True
            return {"status": "cancelling"}
    return {"status": "idle"}


def _run(run_id: str, metric: str) -> None:
    key = (run_id, metric)
    try:
        run = runs_mod.load_run(run_id)
        metric_obj = get_metric(metric)

        def on_progress(done: int, total: int) -> None:
            # Check the cancel flag each sample; abort before recording more. The
            # raise happens outside the lock so the handler can re-acquire it.
            with _lock:
                cancelled = _jobs[key].get("cancel")
                if not cancelled:
                    _jobs[key].update(done=done, total=total)
            if cancelled:
                raise _Cancelled()

        report = scoring.score_run(run, metric_obj, on_progress=on_progress)
        scoring.write_score(run, report)
        with _lock:
            _jobs[key].update(status="done")
    except _Cancelled:
        # Nothing was written (write_score runs only on completion), so the metric
        # is simply unscored. Drop the record -> status() reports "idle".
        with _lock:
            _jobs.pop(key, None)
    except Exception as exc:  # surface the failure to the poller, don't crash the thread
        with _lock:
            _jobs[key] = {"status": "error", "done": None, "total": None, "error": str(exc)}
