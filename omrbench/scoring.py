"""Score a run's predictions against its corpus — engine-free.

Shared by the CLI (`omrbench score`) and the server's on-demand scoring. Scoring
is cheap (MusicXML-vs-MusicXML) and imports no OMR engine, which is exactly why
the server can do it live: the first time a run is viewed under a metric it is
computed and cached to `runs/<run-id>/scores/<metric>.json`, reused thereafter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from omrbench.corpus import discover
from omrbench.runs import Run
from omrbench.score.base import Metric, SampleResult
from omrbench.score.report import Report


def score_run(
    run: Run,
    metric: Metric,
    on_progress: Callable[[int, int], None] | None = None,
) -> Report:
    """Score one run's predictions against its corpus. Honours a subset run's
    `samples` selection. Imports no engine. ``on_progress(done, total)`` is called
    after each sample (the CLI uses it for a counter; the server passes None)."""
    samples = discover(Path(run.corpus))
    if run.samples is not None:
        selection = set(run.samples)
        samples = [s for s in samples if s.id in selection]
    total = len(samples)
    report = Report(metric=metric, corpus=run.corpus)
    for done, sample in enumerate(samples, 1):
        reference = sample.reference_musicxml
        if reference.exists():
            prediction = run.prediction(sample.id)
            if prediction.exists():
                report.samples.append(metric.score(prediction, reference, sample.id))
            else:
                # The engine produced no prediction for this sample. That is not
                # the same as a *wrong* prediction: scoring a missing file as
                # 100%-wrong would let a broken/incomplete run masquerade as a
                # real (bad) result. Mark it ok=False so it is excluded from
                # samples_scored and the aggregates, keeping the gap visible.
                report.samples.append(SampleResult(sample.id, ok=False, fields={}))
        if on_progress is not None:
            on_progress(done, total)
    return report


def write_score(run: Run, report: Report) -> dict:
    """Persist a report as the run's cached score for its metric, returning the
    record."""
    record = report.to_score_record()
    path = run.score_path(report.metric.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    return record


def ensure_score(run: Run, metric: Metric) -> dict:
    """The run's cached score for `metric`, computing and caching it on first
    request. This is the server's on-demand path."""
    path = run.score_path(metric.name)
    if path.is_file():
        return json.loads(path.read_text())
    return write_score(run, score_run(run, metric))
