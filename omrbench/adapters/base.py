"""Adapter contract.

An adapter takes a directory of input images and writes one MusicXML file per
image into an output directory, named ``<sample_id>.musicxml``. It must not
require the benchmark to import the engine — shell out instead, so the core
stays installable with no OMR engine present.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from omrbench.corpus import Sample


class Adapter(ABC):
    #: short, stable identifier used on the CLI and in report paths
    name: str

    @abstractmethod
    def predict(self, sample: Sample, out_path: Path) -> bool:
        """Run the engine on ``sample`` and write MusicXML to ``out_path``.

        Returns True on success. A failure (empty/missing output, non-zero
        exit) should return False rather than raise, so one bad sample does
        not abort a whole run.
        """

    def version(self) -> str | None:
        """Best-effort engine version string for run metadata, or None if
        unknown. Must not import the engine — shell out, like ``predict``."""
        return None

    def run_corpus(self, samples: list[Sample], out_dir: Path) -> dict[str, bool]:
        out_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, bool] = {}
        for sample in samples:
            out_path = out_dir / f"{sample.id}.musicxml"
            if out_path.exists() and out_path.stat().st_size > 0:
                results[sample.id] = True  # cached
                continue
            results[sample.id] = self.predict(sample, out_path)
        return results


def run_subprocess(cmd: list[str], cwd: Path | None = None) -> bool:
    """Run ``cmd``, returning True on exit code 0. Stdout/stderr pass through."""
    proc = subprocess.run(cmd, cwd=cwd)  # noqa: S603 - cmd is caller-controlled
    return proc.returncode == 0


def capture_subprocess(cmd: list[str], cwd: Path | None = None) -> str | None:
    """Run ``cmd`` and return its trimmed stdout, or None on failure. Used for
    cheap metadata probes (e.g. a version string); never raises."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)  # noqa: S603
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def move_into(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
