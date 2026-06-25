"""The **run** as the on-disk unit. Engine-free read+write layer.

A run lives at ``runs/<run-id>/`` and is self-contained: what was run
(``run.json``), the engine output (``predictions/<id>.musicxml``), and any cached
scores (``scores/<metric>.json``). The run-id is ``<engine>-<version>-<timestamp>``;
engine and corpus are recorded in ``run.json``, so nothing downstream has to
re-state them. This module imports no OMR engine.

See DESIGN.md for the rationale (the run replaces the old per-engine
``predictions/`` and ``results/`` layout).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path("runs")


def _safe(part: str) -> str:
    """Make a string safe for a run-id / directory name."""
    return re.sub(r"[^A-Za-z0-9._]+", "-", part).strip("-")


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
    def status(self) -> str | None:
        """``"running"`` while the run is producing predictions, ``"complete"``
        once it finished. None for legacy runs written before status existed."""
        return self.meta.get("status")

    @property
    def produced(self) -> int | None:
        """How many predictions the engine actually produced (None on legacy
        runs). Less than ``attempted`` means a partial/broken run."""
        return self.meta.get("samples_produced")

    @property
    def attempted(self) -> int | None:
        return self.meta.get("samples_attempted")

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


def make_run_id(engine: str, version: str, when: datetime) -> str:
    """``<engine>-<version>-<timestamp>``, e.g. ``homr-0.6.1-20260619T083012Z``.
    The version is sanitized for the filename."""
    return f"{_safe(engine)}-{_safe(version)}-{when.strftime('%Y%m%dT%H%M%SZ')}"


def create_run_dir(
    engine: str, version: str, when: datetime, runs_dir: Path = RUNS_DIR
) -> Path:
    """Create and return a fresh ``runs/<run-id>/`` (with its ``predictions/``).
    On a same-second collision, append a short suffix (``-b``, ``-c``, …)."""
    runs_dir = Path(runs_dir)
    base = make_run_id(engine, version, when)
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


def delete_run(run_id: str, runs_dir: Path = RUNS_DIR) -> None:
    """Delete a run directory and everything under it (predictions + scores).

    Refuses a ``run_id`` that escapes ``runs_dir`` and a directory that isn't a
    run (no ``run.json``), so this can't be turned into an arbitrary ``rm``."""
    import shutil

    runs_dir = Path(runs_dir).resolve()
    run_dir = (runs_dir / run_id).resolve()
    if runs_dir not in run_dir.parents:
        raise ValueError(f"refusing to delete outside runs dir: {run_id!r}")
    if not (run_dir / "run.json").is_file():
        raise FileNotFoundError(f"no run {run_id!r} under {runs_dir}")
    shutil.rmtree(run_dir)


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
