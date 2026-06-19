"""Read layer over the on-disk runs — engine-free.

Everything lives under `runs/<run-id>/` (see DESIGN.md): `run.json` (what was
run), `predictions/<id>.musicxml` (engine output), and `scores/<metric>.json`
(cached score). This module is the one place that reads it back, shared by the
server. A run may have zero, one, or several cached metric scores. Pure
file-reading; imports no OMR engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from omrbench.corpus import Sample
from omrbench.runs import Run, list_runs as _list_runs, load_run as _load_run


def _tier_of(corpus: str) -> str | None:
    for part in Path(corpus).parts:
        if part.startswith("tier"):
            return part
    return None


@dataclass
class RunMeta:
    """A run's header plus which metrics have been scored, with their summaries
    (not the per-sample arrays). One row in the runs list."""

    run_id: str
    engine: str
    engine_version: str | None
    corpus: str
    tier: str | None
    date: str
    metrics: list[str]          # cached metric names for this run
    summaries: dict             # metric -> summary dict


def _cached_scores(run: Run) -> tuple[list[str], dict]:
    metrics: list[str] = []
    summaries: dict = {}
    if run.scores_dir.is_dir():
        for path in sorted(run.scores_dir.glob("*.json")):
            metrics.append(path.stem)
            summaries[path.stem] = json.loads(path.read_text()).get("summary", {})
    return metrics, summaries


def _meta(run: Run) -> RunMeta:
    metrics, summaries = _cached_scores(run)
    return RunMeta(
        run_id=run.run_id,
        engine=run.engine,
        engine_version=run.engine_version,
        corpus=run.corpus,
        tier=_tier_of(run.corpus),
        date=run.date,
        metrics=metrics,
        summaries=summaries,
    )


def list_engines() -> list[str]:
    """Distinct engines that have at least one run."""
    return sorted({run.engine for run in _list_runs()})


def list_runs() -> list[RunMeta]:
    """Every run, newest first, with its cached metric summaries."""
    return [_meta(run) for run in _list_runs()]


def load_run(run_id: str) -> dict:
    """A run's metadata + the list of metrics it has been scored on."""
    run = _load_run(run_id)
    metrics, summaries = _cached_scores(run)
    return {**run.meta, "run_id": run.run_id, "metrics": metrics, "summaries": summaries}


def ensure_score(run_id: str, metric: str) -> dict:
    """The full score record (summary + per-sample) for one run+metric, computed
    and cached on first request. Engine-free; the scoring deps are imported lazily
    so the read layer stays light. Raises KeyError for an unknown metric."""
    from omrbench import scoring
    from omrbench.score import get_metric

    run = _load_run(run_id)
    return scoring.ensure_score(run, get_metric(metric))


@dataclass
class CasePaths:
    image: Path | None
    reference: Path | None
    prediction: Path | None


def case_paths(run_id: str, sample_id: str) -> CasePaths:
    """Resolve the three files for one case: the source image and reference (from
    the run's corpus) and the run's prediction. Each is None when absent."""
    run = _load_run(run_id)
    sample = Sample(id=sample_id, dir=Path(run.corpus) / sample_id)
    reference = sample.reference_musicxml
    prediction = run.prediction(sample_id)
    image = sample.image if sample.dir.is_dir() else None
    return CasePaths(
        image=image,
        reference=reference if reference.is_file() else None,
        prediction=prediction if prediction.is_file() else None,
    )
