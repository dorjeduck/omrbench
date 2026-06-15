"""Fetch the GrandStaff Tier-1 synthetic corpus into omrbench layout.

GrandStaff (Ríos-Vila et al.) is a large set of *engraved* pianoform excerpts
with Humdrum ``**kern`` ground truth and matching rendered images. Because the
images are rendered from the encoding rather than scanned, it lands in Tier 1 —
optimistic, cheap, and large.

The ground truth ships as ``**kern`` only. The default ``music21`` metric
compares MusicXML-vs-MusicXML, so the kern is converted to MusicXML *once here,
at fetch time, on the ground truth*. The fragile cross-format step thus stays on
the reference and never enters ``score/`` or the engine output path.

Caveat for the user (omrbench does not enforce it): GrandStaff is the training
data of some engines (e.g. homr). Benchmarking such an engine against it
measures in-distribution performance — optimistic and not predictive. Choosing
an appropriate source for a given engine is the user's call.

The full archive holds tens of thousands of kern/image pairs; this fetcher
writes a reproducible subset (``--limit``, default 200; ``--seed`` for the
sampling). The download is large and is cached so re-fetching does not
re-download (the actual size is printed once downloaded).

Source: https://grfia.dlsi.ua.es/musicdocs/grandstaff.tgz
"""

from __future__ import annotations

import random
import tarfile
import urllib.request
from pathlib import Path

import yaml

_URL = "https://grfia.dlsi.ua.es/musicdocs/grandstaff.tgz"

_LICENSE_NOTE = (
    "GrandStaff dataset (Ríos-Vila et al., University of Alicante); "
    "see https://sites.google.com/view/multiscore-project/datasets for terms"
)


def fetch(dest: Path, limit: int = 200, seed: int = 0) -> int:
    from music21 import converter  # core dep; parses **kern, writes MusicXML

    cache = _ensure_archive()
    krn_files = sorted(
        p for p in cache.rglob("*.krn")
        if not p.name.startswith("._") and p.with_suffix(".jpg").exists()
    )
    if not krn_files:
        raise RuntimeError(f"no .krn/.jpg pairs found under {cache}")

    random.Random(seed).shuffle(krn_files)
    print(f"found {len(krn_files)} kern/image pairs; sampling up to {limit} (seed={seed})")

    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for krn in krn_files:
        if count >= limit:
            break
        try:
            musicxml = converter.parse(str(krn), format="humdrum").write("musicxml")
        except Exception as exc:  # noqa: BLE001 - skip unconvertible samples, keep going
            print(f"  skip {krn.name}: kern->musicxml failed ({exc})")
            continue

        sample_id = f"{count:04d}"
        sample_dir = dest / sample_id
        sample_dir.mkdir(exist_ok=True)
        (sample_dir / "image.jpg").write_bytes(krn.with_suffix(".jpg").read_bytes())
        (sample_dir / "reference.musicxml").write_text(Path(musicxml).read_text())
        (sample_dir / "reference.krn").write_text(krn.read_text(errors="ignore"))
        (sample_dir / "meta.yaml").write_text(
            yaml.safe_dump(
                {
                    "tier": "tier1_synthetic",
                    "source": "grandstaff",
                    "type": "engraved",
                    "origin": str(krn.relative_to(cache)),
                    "license": _LICENSE_NOTE,
                }
            )
        )
        count += 1
    return count


def _ensure_archive() -> Path:
    """Download + extract the GrandStaff tarball into a cache dir, once."""
    cache_root = Path.home() / ".cache" / "omrbench" / "grandstaff"
    if any(cache_root.rglob("*.krn")) if cache_root.exists() else False:
        return cache_root

    cache_root.mkdir(parents=True, exist_ok=True)
    archive = cache_root / "grandstaff.tgz"
    if not archive.exists():
        print(f"downloading {_URL} ...")
        urllib.request.urlretrieve(_URL, archive)  # noqa: S310 - fixed, trusted URL
        print(f"downloaded {archive.stat().st_size / 1e6:.0f} MB")
    print(f"extracting {archive.name} ...")
    with tarfile.open(archive) as tar:
        tar.extractall(cache_root, filter="data")
    return cache_root
