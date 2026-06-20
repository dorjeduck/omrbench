"""The **run** as the on-disk unit. Engine-free read+write layer.

A run lives at ``runs/<run-id>/`` and is self-contained: what was run
(``run.json``), the engine output (``predictions/<id>.musicxml``), and any cached
scores (``scores/<metric>.json``). The run-id is ``<engine>-<timestamp>``; engine
and corpus are recorded in ``run.json``, so nothing downstream has to re-state
them. This module imports no OMR engine.

See DESIGN.md for the rationale (the run replaces the old per-engine
``predictions/`` and ``results/`` layout).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path("runs")


@dataclass
class Run:
    """A run directory, with its ``run.json`` metadata loaded."""

    run_id: str
    dir: Path
    meta: dict

    @property
    def engine(self) -> str:
        return self.meta.get("engine", "")

    @property
    def engine_version(self) -> str | None:
        return self.meta.get("engine_version")

    @property
    def corpus(self) -> str:
        return self.meta.get("corpus", "")

    @property
    def date(self) -> str:
        return self.meta.get("date", "")

    @property
    def samples(self) -> list[str] | None:
        """The sample ids this run covered, or None for a full-corpus run
        (the field is written only on a subset run)."""
        return self.meta.get("samples")

    @property
    def predictions_dir(self) -> Path:
        return self.dir / "predictions"

    def prediction(self, sample_id: str) -> Path:
        return self.predictions_dir / f"{sample_id}.musicxml"

    def prediction_ids(self) -> set[str]:
        """The sample ids this run produced predictions for — the authoritative
        'what this run covered', independent of scoring."""
        if not self.predictions_dir.is_dir():
            return set()
        return {p.stem for p in self.predictions_dir.glob("*.musicxml")}

    @property
    def scores_dir(self) -> Path:
        return self.dir / "scores"

    def score_path(self, metric: str) -> Path:
        return self.scores_dir / f"{metric}.json"


def make_run_id(engine: str, when: datetime) -> str:
    """``<engine>-<timestamp>``, e.g. ``homr-20260619T083012Z``."""
    return f"{engine}-{when.strftime('%Y%m%dT%H%M%SZ')}"


def create_run_dir(engine: str, when: datetime, runs_dir: Path = RUNS_DIR) -> Path:
    """Create and return a fresh ``runs/<run-id>/`` (with its ``predictions/``).
    On a same-second collision, append a short suffix (``-b``, ``-c``, …)."""
    runs_dir = Path(runs_dir)
    base = make_run_id(engine, when)
    run_id = base
    suffix = ord("b")
    while (runs_dir / run_id).exists():
        run_id = f"{base}-{chr(suffix)}"
        suffix += 1
    run_dir = runs_dir / run_id
    (run_dir / "predictions").mkdir(parents=True)
    return run_dir


def write_run_meta(run_dir: Path, meta: dict) -> None:
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2))


def load_run(run_id: str, runs_dir: Path = RUNS_DIR) -> Run:
    run_dir = Path(runs_dir) / run_id
    meta_path = run_dir / "run.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"no run.json for run {run_id!r}: {meta_path}")
    return Run(run_id=run_id, dir=run_dir, meta=json.loads(meta_path.read_text()))


def list_runs(runs_dir: Path = RUNS_DIR) -> list[Run]:
    """Every run under ``runs_dir`` (a subdir with a ``run.json``), newest first."""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    runs = [
        Run(run_id=child.name, dir=child, meta=json.loads((child / "run.json").read_text()))
        for child in sorted(runs_dir.iterdir())
        if child.is_dir() and (child / "run.json").is_file()
    ]
    runs.sort(key=lambda r: r.date, reverse=True)
    return runs
