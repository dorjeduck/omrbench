"""Background scoring jobs for the web UI — engine-free.

Scoring a run with a heavy metric (omr-ned) takes minutes, so the web UI can't
compute it inside one request. Instead the server runs it as a BackgroundProc
(see server/proc.py) and the client polls for progress. State lives in-memory
for the life of the process (a local, single-process server); a finished score
is durable in its cache file, so the in-memory record is only needed while a job
runs.

A child process — not a thread — because cancellation must be instant: omr-ned
spends minutes inside a single synchronous `metric.score()` call (holding the
GIL), so a cancel flag could only take effect at the next sample boundary. We
never keep a half-finished score (`write_score` runs only on completion), so
killing the process outright loses nothing.

This module is just the scoring-specific layer: the (run_id, metric) registry,
the score-cache idempotency check, and the worker. The run-in-background and
kill mechanics live in BackgroundProc.
"""

from __future__ import annotations

import threading

from omrbench import runs as runs_mod
from omrbench import scoring
from omrbench.score import get_metric
from omrbench.server.proc import BackgroundProc, Report

# (run_id, metric) -> {status, done, total, error, proc}. proc is the
# BackgroundProc; _public() strips it for the API.
_jobs: dict[tuple[str, str], dict] = {}
_lock = threading.Lock()


def _public(job: dict) -> dict:
    return {k: job[k] for k in ("status", "done", "total", "error")}


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
        if existing and existing["proc"].alive():
            return _public(existing)
        proc = BackgroundProc(_worker, args=(run_id, metric))
        proc.start()
        _jobs[key] = {"status": "running", "done": 0, "total": None,
                      "error": None, "proc": proc}
        return _public(_jobs[key])


def status(run_id: str, metric: str) -> dict:
    """Current job state. A score already on disk reports ``done`` even if this
    process never ran it; with no job and no cache it's ``idle``."""
    runs_mod.load_run(run_id)
    get_metric(metric)
    key = (run_id, metric)
    if _is_cached(run_id, metric):
        return {"status": "done", "done": None, "total": None}
    with _lock:
        job = _jobs.get(key)
        if not job:
            return {"status": "idle"}
        _apply(job)
        if job["status"] == "running" and not job["proc"].alive():
            # Exited without a terminal message and left no cache -> crashed/killed.
            job["status"] = "error"
            job["error"] = job["error"] or "scoring process exited unexpectedly"
        return _public(job)


def cancel(run_id: str, metric: str) -> dict:
    """Kill a running job immediately (mid-sample). Nothing is written
    (write_score runs only on completion), so the metric stays unscored and the
    job record is dropped -> status() reports ``idle``."""
    runs_mod.load_run(run_id)
    get_metric(metric)
    key = (run_id, metric)
    with _lock:
        job = _jobs.pop(key, None)
    if job:
        job["proc"].kill()
    return {"status": "idle"}


def _apply(job: dict) -> None:
    """Fold the worker's pending messages into the job record."""
    for msg in job["proc"].drain():
        if msg[0] == "progress":
            job["done"], job["total"] = msg[1], msg[2]
        elif msg[0] == "done":
            job["status"] = "done"
        elif msg[0] == "error":
            job["status"], job["error"] = "error", msg[1]


def _worker(report: Report, run_id: str, metric: str) -> None:
    run = runs_mod.load_run(run_id)
    metric_obj = get_metric(metric)
    report_obj = scoring.score_run(run, metric_obj, on_progress=report)
    scoring.write_score(run, report_obj)
