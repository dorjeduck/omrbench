"""Corpus discovery.

A corpus is a directory of sample sub-directories. Each sample dir is named by
its id and contains:

    <id>/
        image.png            # the OMR input
        reference.musicxml   # the ground truth (required for scoring)
        meta.yaml            # provenance + license + tier

Tier-1 (synthetic, rendered-from-MusicXML) and Tier-2 (real scans) live in
separate top-level folders so their scores are never silently mixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


@dataclass
class Sample:
    id: str
    dir: Path

    @property
    def image(self) -> Path | None:
        for suffix in IMAGE_SUFFIXES:
            candidate = self.dir / f"image{suffix}"
            if candidate.exists():
                return candidate
        # Fall back to the first image-like file in the dir.
        for child in sorted(self.dir.iterdir()):
            if child.suffix.lower() in IMAGE_SUFFIXES:
                return child
        return None

    @property
    def reference_musicxml(self) -> Path:
        return self.dir / "reference.musicxml"

    @property
    def meta(self) -> dict:
        meta_path = self.dir / "meta.yaml"
        if not meta_path.exists():
            return {}
        return yaml.safe_load(meta_path.read_text()) or {}


def discover(corpus_dir: Path) -> list[Sample]:
    """Return every sample sub-directory under ``corpus_dir``, sorted by id."""
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"corpus dir not found: {corpus_dir}")
    samples = [
        Sample(id=child.name, dir=child)
        for child in sorted(corpus_dir.iterdir())
        if child.is_dir()
    ]
    return samples
