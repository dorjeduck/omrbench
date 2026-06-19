"""Score a run's predictions against its corpus — engine-free.

Shared by the CLI (`omrbench score`) and the server's on-demand scoring. Scoring
is cheap (MusicXML-vs-MusicXML) and imports no OMR engine, which is exactly why
the server can do it live: the first time a run is viewed under a metric it is
computed and cached to `runs/<run-id>/scores/<metric>.json`, reused thereafter.
"""

from __future__ import annotations

import json
from pathlib import Path

from omrbench.corpus import discover
from omrbench.runs import Run
from omrbench.score.base import Metric
from omrbench.score.report import Report


def score_run(run: Run, metric: Metric) -> Report:
    """Score one run's predictions against its corpus. Honours a subset run's
    `samples` selection. Imports no engine."""
    samples = discover(Path(run.corpus))
    if run.samples is not None:
        selection = set(run.samples)
        samples = [s for s in samples if s.id in selection]
    report = Report(metric=metric, corpus=run.corpus)
    for sample in samples:
        reference = sample.reference_musicxml
        if not reference.exists():
            continue
        report.samples.append(metric.score(run.prediction(sample.id), reference, sample.id))
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
