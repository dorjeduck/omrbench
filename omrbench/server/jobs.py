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

# (run_id, metric) -> {status: "running"|"done"|"error", done, total, error}
_jobs: dict[tuple[str, str], dict] = {}
_lock = threading.Lock()


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
    process never ran it."""
    runs_mod.load_run(run_id)
    get_metric(metric)
    if _is_cached(run_id, metric):
        return {"status": "done", "done": None, "total": None}
    with _lock:
        return dict(_jobs.get((run_id, metric), {"status": "idle"}))


def _run(run_id: str, metric: str) -> None:
    key = (run_id, metric)
    try:
        run = runs_mod.load_run(run_id)
        metric_obj = get_metric(metric)

        def on_progress(done: int, total: int) -> None:
            with _lock:
                _jobs[key].update(done=done, total=total)

        report = scoring.score_run(run, metric_obj, on_progress=on_progress)
        scoring.write_score(run, report)
        with _lock:
            _jobs[key].update(status="done")
    except Exception as exc:  # surface the failure to the poller, don't crash the thread
        with _lock:
            _jobs[key] = {"status": "error", "done": None, "total": None, "error": str(exc)}
