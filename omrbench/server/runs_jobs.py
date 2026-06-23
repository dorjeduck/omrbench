"""Background engine runs for the web UI.

The run counterpart of server/jobs.py: where jobs.py scores a run, this one
*produces* it — an engine turns a corpus of images into predictions. A run
shells out to an OMR engine and takes minutes, so the server launches it as a
BackgroundProc (server/proc.py) the client polls; stopping kills the process
group instantly, reaping the engine subprocess (see proc.py).

The benchmark core never imports an engine: the worker goes through
engines.load_engine -> adapter -> subprocess, exactly as the CLI's `run` does.

Per the design choice, stopping a run keeps it as a *flagged partial* rather than
deleting it: the predictions produced so far stay on disk (and are resumable,
since run_corpus skips non-empty files) and run.json is rewritten to status
"cancelled" with the partial counts.

Like jobs.py this is an in-memory registry for the life of the (single-process,
local) server; a finished run is durable on disk under runs/<run-id>/. The two
modules deliberately stay parallel rather than sharing a base (see CLAUDE.md /
the run-vs-score lifecycle differences): the shared piece is BackgroundProc.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from omrbench import runs as runs_mod
from omrbench import scoring
from omrbench.corpus import discover
from omrbench.engines import load_engine
from omrbench.score import get_metric
from omrbench.server.proc import BackgroundProc, Report

# run_id -> {status, done, total, error, proc}. proc is the BackgroundProc;
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
    # Write run.json up front with status "running" (mirrors the CLI): the run is
    # a visible, flagged run immediately, and the run_id exists to key the job by.
    runs_mod.write_run_meta(run_dir, {
        "engine": adapter.engine,
        "engine_version": resolved_version,
        "command": " ".join(adapter.cmd),
        "corpus": str(corpus),
        "date": when.isoformat(),
        "status": "running",
    })
    proc = BackgroundProc(_worker, args=(engine, version, str(corpus), run_id))
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
    run = runs_mod.load_run(run_id)
    with _lock:
        job = _jobs.pop(run_id, None)
    if job:
        job["proc"].kill()
    produced = len(run.prediction_ids())
    attempted = (job["total"] if job else None) or run.attempted or produced
    runs_mod.write_run_meta(run.dir, {
        **run.meta,
        "status": "cancelled",
        "samples_attempted": attempted,
        "samples_produced": produced,
    })
    # Score the partial with the cheap default so it shows as a flagged partial
    # in the runs list (the tables list only scored runs). Best-effort: a
    # half-written prediction left by the kill must not make Stop fail.
    if produced:
        try:
            run = runs_mod.load_run(run_id)
            metric = get_metric("music21")
            scoring.write_score(run, scoring.score_run(run, metric))
        except Exception:
            pass
    return {"status": "cancelled"}


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


def _worker(report: Report, engine: str, version: str, corpus: str, run_id: str) -> None:
    # Re-resolve the adapter in the child (engine-free, and avoids pickling it).
    adapter = load_engine(engine, version or None)
    samples = discover(Path(corpus))
    run = runs_mod.load_run(run_id)
    results = adapter.run_corpus(samples, run.predictions_dir, on_progress=report)
    produced = sum(1 for v in results.values() if v)
    failed = sorted(sid for sid, ok in results.items() if not ok)
    base = {k: v for k, v in run.meta.items() if k != "status"}
    runs_mod.write_run_meta(run.dir, {
        **base,
        "status": "complete",
        "samples_attempted": len(results),
        "samples_produced": produced,
        "samples_failed": failed,
    })
    # Auto-score the cheap default metric so the run shows a number immediately
    # (mirrors the CLI); heavy metrics stay opt-in via the scoring jobs.
    run = runs_mod.load_run(run_id)
    metric = get_metric("music21")
    scoring.write_score(run, scoring.score_run(run, metric))
