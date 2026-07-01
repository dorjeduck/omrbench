"""Fetch the GrandStaff synthetic corpus into omrbench layout.

GrandStaff (Ríos-Vila et al.) is a large set of *engraved* pianoform excerpts
with Humdrum ``**kern`` ground truth and matching rendered images. Because the
images are rendered from the encoding rather than scanned, it is synthetic —
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
sampling).

The raw dataset is read from ``source_dir`` (default ``datasets/grandstaff`` in
the working dir — a visible location, not a hidden cache). If that directory
already holds the extracted dataset (e.g. another project's copy, passed via
``--source-dir``), it is reused and nothing is downloaded. Otherwise the tarball
is downloaded there, extracted, and then removed so only one copy remains.

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


def fetch(dest: Path, limit: int = 200, seed: int = 0, source_dir: Path | None = None) -> int:
    from music21 import converter  # core dep; parses **kern, writes MusicXML

    source = _ensure_source(source_dir or Path("datasets/grandstaff"))
    krn_files = sorted(
        p for p in source.rglob("*.krn")
        if not p.name.startswith("._") and p.with_suffix(".jpg").exists()
    )
    if not krn_files:
        raise RuntimeError(f"no .krn/.jpg pairs found under {source}")

    random.Random(seed).shuffle(krn_files)
    print(f"found {len(krn_files)} kern/image pairs; sampling up to {limit} (seed={seed})")

    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for krn in krn_files:
        if count >= limit:
            break
        try:
            musicxml = Path(converter.parse(str(krn), format="humdrum").write("musicxml"))
        except Exception as exc:  # noqa: BLE001 - skip unconvertible samples, keep going
            print(f"  skip {krn.name}: kern->musicxml failed ({exc})")
            continue

        sample_id = f"{count:04d}"
        sample_dir = dest / sample_id
        sample_dir.mkdir(exist_ok=True)
        (sample_dir / "image.jpg").write_bytes(krn.with_suffix(".jpg").read_bytes())
        (sample_dir / "reference.musicxml").write_text(musicxml.read_text())
        musicxml.unlink()  # music21 wrote it to its scratch dir; don't accumulate copies
        (sample_dir / "meta.yaml").write_text(
            yaml.safe_dump(
                {
                    "kind": "synthetic",
                    "source": "grandstaff",
                    "type": "engraved",
                    "origin": str(krn.relative_to(source)),
                    "license": _LICENSE_NOTE,
                }
            )
        )
        count += 1
    return count


def _ensure_source(source_dir: Path) -> Path:
    """Return a directory holding the extracted GrandStaff `.krn`/`.jpg` tree.

    Handles three states of ``source_dir``, in order:

    1. already holds the extracted dataset -> use it, nothing else to do;
    2. holds only ``grandstaff.tgz`` (e.g. the user dropped the tarball there)
       -> extract it, no download;
    3. neither -> download the tarball, then extract.

    After extraction the tarball is removed so only the extracted tree remains
    (no redundant second copy). The location is visible and printed.
    """
    archive = source_dir / "grandstaff.tgz"

    if source_dir.exists() and any(source_dir.rglob("*.krn")):
        print(f"using existing GrandStaff dataset: {source_dir.resolve()}")
        return source_dir

    source_dir.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        print(f"using existing tarball: {archive.resolve()}")
    else:
        print(f"downloading {_URL}\n  -> {archive.resolve()}")
        urllib.request.urlretrieve(_URL, archive)  # noqa: S310 - fixed, trusted URL
        print(f"downloaded {archive.stat().st_size / 1e6:.0f} MB")

    print(f"extracting {archive.name} -> {source_dir.resolve()}")
    with tarfile.open(archive) as tar:
        tar.extractall(source_dir, filter="data")
    archive.unlink()  # keep only the extracted tree, not a second copy
    return source_dir
