"""Background engine runs for the web UI.

The run counterpart of server/jobs.py: where jobs.py scores a run, this one
*produces* it — an engine turns a corpus of images into predictions. A run
shells out to an OMR engine and takes minutes, so the server launches it as a
proc.Job (omrbench/proc.py) the client polls; stopping kills the process group
instantly, reaping the engine subprocess (see proc.py).

The benchmark core never imports an engine: the worker goes through
engines.load_engine -> adapter -> subprocess, exactly as the CLI's `run` does.

Per the design choice, stopping a run keeps it as a *flagged partial* rather than
deleting it: the predictions produced so far stay on disk (and are resumable,
since run_corpus skips non-empty files) and run.json is rewritten to status
"cancelled" with the partial counts.

Like jobs.py this is an in-memory registry for the life of the (single-process,
local) server; a finished run is durable on disk under runs/<run-id>/. The two
modules deliberately stay parallel rather than sharing a base (see CLAUDE.md /
the run-vs-score lifecycle differences): the shared piece is proc.Job.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from omrbench import runs as runs_mod
from omrbench import scoring
from omrbench.corpus import discover
from omrbench.engines import load_engine
from omrbench.proc import Job, Progress

# run_id -> {status, done, total, error, proc}. proc is the proc.Job;
# _public() strips it for the API.
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _public(job: dict) -> dict:
    return {k: job[k] for k in ("status", "done", "total", "error")}


def start(engine: str, version: str, corpus: str) -> dict:
    """Create a run for ``engine`` (+ ``version``) over ``corpus`` and produce its
    predictions in the background. Returns ``{run_id, ...job state}``. Raises
    FileNotFoundError (no config / missing corpus), KeyError (unknown engine or
    version), or ValueError (no resolvable version / empty corpus)."""
    adapter = load_engine(engine, version or None)  # validates engine + version
    resolved_version = adapter.resolved_version()
    if not resolved_version:
        raise ValueError(f"cannot determine a version for engine {engine!r}; declare 'version'")
    samples = discover(Path(corpus))  # validates the corpus exists
    if not samples:
        raise ValueError(f"corpus {corpus!r} has no samples")

    when = datetime.now(timezone.utc)
    run_dir = runs_mod.create_run_dir(adapter.engine, resolved_version, when)
    run_id = run_dir.name
    # Write run.json up front with status "running" (same helper as the CLI): the
    # run is a visible, flagged run immediately, and the run_id keys the job.
    runs_mod.write_run_meta(run_dir, runs_mod.start_meta(
        adapter.engine, resolved_version, " ".join(adapter.cmd), str(corpus), when
    ))
    proc = Job(_worker, args=(engine, version, str(corpus), run_id))
    proc.start()
    with _lock:
        _jobs[run_id] = {"status": "running", "done": 0, "total": len(samples),
                         "error": None, "proc": proc}
        return {"run_id": run_id, **_public(_jobs[run_id])}


def status(run_id: str) -> dict:
    """Current job state. With no in-memory job (e.g. after a server restart, or
    once a finished run is only on disk) it reports the run's on-disk status."""
    run = runs_mod.load_run(run_id)
    with _lock:
        job = _jobs.get(run_id)
        if not job:
            return {"status": run.status or "complete", "done": None, "total": None}
        _apply(job)
        if job["status"] == "running" and not job["proc"].alive():
            # Exited without a terminal message -> crashed/killed out of band.
            job["status"] = "error"
            job["error"] = job["error"] or "run process exited unexpectedly"
        return _public(job)


def cancel(run_id: str) -> dict:
    """Stop a running run immediately and keep it as a flagged partial: kill the
    process group, then rewrite run.json to status "cancelled" with the counts
    produced so far. The predictions already on disk stay (and are resumable)."""
    runs_mod.load_run(run_id)  # validate the run exists
    with _lock:
        job = _jobs.pop(run_id, None)
    if job:
        job["proc"].kill()
    # Re-read run.json after the kill: the worker may have finished (writing
    # status "complete") in the meantime — keep that rather than overwriting a
    # completed run as a cancelled partial with stale counts.
    run = runs_mod.load_run(run_id)
    status = run.status if run.status == "complete" else "cancelled"
    produced = len(run.prediction_ids())
    if status == "cancelled":
        attempted = (job["total"] if job else None) or run.attempted or produced
        runs_mod.write_run_meta(run.dir, {
            **run.meta,
            "status": "cancelled",
            "samples_attempted": attempted,
            "samples_produced": produced,
        })
    # Score with the cheap default so the run shows in the runs list (the tables
    # list only scored runs) — under the [scoring] budget, and best-effort: a
    # half-written prediction left by the kill must not make Stop fail. Also
    # covers a run that completed but was killed before its own auto-score.
    if produced and not run.score_path(scoring.DEFAULT_METRIC).exists():
        try:
            scoring.score_default(run_id)
        except Exception:
            pass
    return {"status": status}


def _apply(job: dict) -> None:
    """Fold the worker's pending messages into the job record. ``("done",)`` maps
    to status "complete" so the API status matches the run's on-disk status."""
    for msg in job["proc"].drain():
        if msg[0] == "progress":
            job["done"], job["total"] = msg[1], msg[2]
        elif msg[0] == "done":
            job["status"] = "complete"
        elif msg[0] == "error":
            job["status"], job["error"] = "error", msg[1]


def _worker(report: Progress, engine: str, version: str, corpus: str, run_id: str) -> None:
    # Re-resolve the adapter in the child (engine-free, and avoids pickling it).
    adapter = load_engine(engine, version or None)
    samples = discover(Path(corpus))
    run = runs_mod.load_run(run_id)
    results = adapter.run_corpus(samples, run.predictions_dir, on_progress=report)
    runs_mod.write_run_meta(run.dir, runs_mod.complete_meta(run.meta, results))
    # Auto-score the cheap default metric so the run shows a number immediately
    # (mirrors the CLI); heavy metrics stay opt-in via the scoring jobs. Scored
    # in-process rather than via scoring.score_default: this worker is a daemonic
    # Job child, which may not spawn the scoring child that helper uses — and it
    # is already killable as a whole (Stop reaps it, scoring included).
    scoring.score_to_cache(lambda done, total: None, run_id, scoring.DEFAULT_METRIC)
