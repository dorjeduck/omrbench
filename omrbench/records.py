"""Read layer over the on-disk benchmark artifacts — engine-free.

Everything the CLI writes (`results/<engine>/<timestamp>.json`,
`predictions/<engine>/<id>.musicxml`) is read back here, in one place, so the
server (and, later, the CLI) share a single way to list run history and resolve a
case's files. Pure file-reading; imports no OMR engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from omrbench.corpus import Sample

RESULTS_DIR = Path("results")
PREDICTIONS_DIR = Path("predictions")


@dataclass
class RunMeta:
    """The header of a result record, without its per-sample array."""

    engine: str
    run_id: str  # the timestamp stem of the JSON file
    engine_version: str | None
    metric: str
    corpus: str
    tier: str | None
    date: str
    summary: dict


def list_engines() -> list[str]:
    """Engines that have at least one result record."""
    if not RESULTS_DIR.is_dir():
        return []
    return sorted(p.name for p in RESULTS_DIR.iterdir() if p.is_dir())


def list_runs(engine: str | None = None) -> list[RunMeta]:
    """Every result record (optionally for one engine), newest first. Reads only
    the header fields — not the (potentially large) per-sample array."""
    engines = [engine] if engine else list_engines()
    runs: list[RunMeta] = []
    for eng in engines:
        eng_dir = RESULTS_DIR / eng
        if not eng_dir.is_dir():
            continue
        for path in sorted(eng_dir.glob("*.json")):
            record = json.loads(path.read_text())
            runs.append(
                RunMeta(
                    engine=record.get("engine", eng),
                    run_id=path.stem,
                    engine_version=record.get("engine_version"),
                    metric=record.get("metric", ""),
                    corpus=record.get("corpus", ""),
                    tier=record.get("tier"),
                    date=record.get("date", ""),
                    summary=record.get("summary", {}),
                )
            )
    runs.sort(key=lambda r: r.date, reverse=True)
    return runs


def load_run(engine: str, run_id: str) -> dict:
    """The full result record (summary + samples) for one run."""
    path = RESULTS_DIR / engine / f"{run_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no result record: {path}")
    return json.loads(path.read_text())


@dataclass
class CasePaths:
    image: Path | None
    reference: Path | None
    prediction: Path | None


def case_paths(corpus: str, engine: str, sample_id: str) -> CasePaths:
    """Resolve the three files for one case: the source image and reference
    (from the corpus sample dir) and the engine's prediction. Each is None when
    absent. Reuses `corpus.Sample` for the corpus-side path logic."""
    sample = Sample(id=sample_id, dir=Path(corpus) / sample_id)
    reference = sample.reference_musicxml
    prediction = PREDICTIONS_DIR / engine / f"{sample_id}.musicxml"
    # Sample.image walks the sample dir; guard the dir not existing (e.g. an
    # unknown or path-traversing sample_id) so callers get None, not an error.
    image = sample.image if sample.dir.is_dir() else None
    return CasePaths(
        image=image,
        reference=reference if reference.is_file() else None,
        prediction=prediction if prediction.is_file() else None,
    )
