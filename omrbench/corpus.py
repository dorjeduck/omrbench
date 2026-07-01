"""Corpus discovery.

A corpus is a directory of sample sub-directories. Each sample dir is named by
its id and contains:

    <id>/
        image.png            # the OMR input
        reference.musicxml   # the ground truth (required for scoring)
        meta.yaml            # provenance + license

Synthetic corpora (rendered-from-MusicXML) and real corpora (scans) live in
separate top-level folders (``synthetic/`` and ``real/``) so their scores are
never silently mixed.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")

# Recognised values for the optional per-sample ``kind`` tag (synthetic ground
# truth rendered from MusicXML, vs. a real scan). Purely informational — nothing
# is enforced on it. Also the folder names used by the seed fetchers, so a kind
# can be inferred from a sample's path when its meta doesn't state one.
KINDS = ("synthetic", "real")
CORPORA_ROOT = Path("corpora")


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

    @cached_property
    def meta(self) -> dict:
        # Cached: readers (kind, corpus listings) hit this repeatedly per sample,
        # and a Sample is built fresh per request, so staleness is not a concern.
        meta_path = self.dir / "meta.yaml"
        if not meta_path.exists():
            return {}
        return yaml.safe_load(meta_path.read_text()) or {}

    @property
    def kind(self) -> str | None:
        """A purely informational tag (e.g. ``synthetic``/``real``): the sample's
        own ``meta.yaml`` value if set, else inferred from a kind folder in its
        path. Not enforced anywhere — for display and optional filtering."""
        return self.meta.get("kind") or kind_of(self.dir)


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


def kind_of(path: str | Path) -> str | None:
    """The kind folder (``synthetic`` / ``real``) a path sits under, or None if
    it sits under neither."""
    for part in Path(path).parts:
        if part in KINDS:
            return part
    return None


# --- the corpus as a managed unit (list + create + edit) -------------------
#
# These mutate the on-disk corpus tree. They are still engine-free (MusicXML
# files only) and live here, not in the read layer, the same way run deletion
# lives in runs.py. Every write is confined under ``root`` and guarded against
# path traversal so a crafted corpus id / sample id can't escape the tree.


@dataclass
class CorpusInfo:
    """One corpus for the listing: its path (the id used everywhere), how many
    samples it holds, and a small summary of their provenance. (kind is a
    per-sample tag, not a corpus-level one — a corpus may mix kinds.)"""

    path: str
    count: int
    sources: list[str] = field(default_factory=list)
    licenses: list[str] = field(default_factory=list)


def _is_sample_dir(d: Path) -> bool:
    return d.is_dir() and (d / "reference.musicxml").is_file()


def _is_corpus_dir(d: Path) -> bool:
    """A corpus is a directory with at least one sample sub-directory."""
    return d.is_dir() and any(_is_sample_dir(c) for c in d.iterdir())


def list_corpora(root: Path = CORPORA_ROOT) -> list[CorpusInfo]:
    """Every corpus under ``root`` (the ``corpora/`` tree), each summarised. A
    directory counts as a corpus once it holds a sample (a child dir with a
    reference.musicxml); we do not descend into a corpus once found."""
    root = Path(root)
    out: list[CorpusInfo] = []
    if not root.is_dir():
        return out

    def is_corpus(d: Path) -> bool:
        # Recognise a corpus by the samples it holds, or — so a freshly created,
        # still-empty corpus shows up — by sitting where corpora are made: a
        # direct child of the corpus root, or under a kind folder. The kind
        # folders themselves are containers, not corpora.
        if _is_corpus_dir(d):
            return True
        if d.parent.name in KINDS:
            return True
        return d.parent == root and d.name not in KINDS

    def walk(d: Path) -> None:
        if is_corpus(d):
            samples = discover(d)
            metas = [s.meta for s in samples]
            out.append(
                CorpusInfo(
                    path=str(d),
                    count=len(samples),
                    sources=sorted({m["source"] for m in metas if m.get("source")}),
                    licenses=sorted({m["license"] for m in metas if m.get("license")}),
                )
            )
            return
        for child in sorted(d.iterdir()):
            if child.is_dir():
                walk(child)

    walk(root)
    return sorted(out, key=lambda c: c.path)


def _confine(path: Path, root: Path) -> Path:
    """Resolve ``path`` and require it to stay under ``root`` — refuse ``..`` and
    absolute escapes. Returns the resolved path."""
    root = root.resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes {root}: {path}")
    return resolved


def check_corpus_path(path: str | Path, root: Path = CORPORA_ROOT) -> Path:
    """Validate that a (client-supplied) corpus path stays under the corpora
    root, returning it *unresolved* so callers keep the relative form used as
    the corpus id everywhere. Raises ValueError on escape — the read-side
    counterpart of the write guards above."""
    _confine(Path(path), Path(root))
    return Path(path)


def create_corpus(name: str, root: Path = CORPORA_ROOT) -> Path:
    """Create an empty corpus ``root/name``. ``name`` must be a safe single path
    segment (and not a reserved kind-folder name). Raises FileExistsError if it
    already exists."""
    if not name or "/" in name or "\\" in name or name in (".", "..") or name in KINDS:
        raise ValueError(f"invalid corpus name: {name!r}")
    corpus_dir = Path(root) / name
    _confine(corpus_dir, Path(root))
    if corpus_dir.exists():
        raise FileExistsError(f"corpus already exists: {corpus_dir}")
    corpus_dir.mkdir(parents=True)
    return corpus_dir


def next_sample_id(corpus_dir: Path) -> str:
    """The next free zero-padded id (``0000`` scheme) for ``corpus_dir``."""
    existing = [int(s.id) for s in discover(corpus_dir) if s.id.isdigit()]
    return f"{(max(existing) + 1) if existing else 0:04d}"


def add_sample(
    corpus_dir: Path,
    *,
    image_bytes: bytes,
    image_suffix: str,
    reference_xml: str,
    meta: dict,
    validate: bool = True,
    root: Path = CORPORA_ROOT,
) -> Sample:
    """Author a new sample into ``corpus_dir`` from an uploaded image + ground
    truth. ``validate`` parses the MusicXML (music21) so an unparseable ground
    truth is rejected before it poisons scoring. Returns the created Sample."""
    corpus_dir = _confine(Path(corpus_dir), Path(root))
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"corpus dir not found: {corpus_dir}")
    suffix = image_suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValueError(f"image suffix must be one of {IMAGE_SUFFIXES}, got {suffix!r}")
    if validate:
        _validate_musicxml(reference_xml)

    sample_id = next_sample_id(corpus_dir)
    sample_dir = corpus_dir / sample_id
    sample_dir.mkdir()
    (sample_dir / f"image{suffix}").write_bytes(image_bytes)
    (sample_dir / "reference.musicxml").write_text(reference_xml)
    (sample_dir / "meta.yaml").write_text(yaml.safe_dump(meta, sort_keys=True))
    return Sample(id=sample_id, dir=sample_dir)


def copy_sample(corpus_dir: Path, src: Sample, root: Path = CORPORA_ROOT) -> Sample:
    """Curate: copy ``src`` (image + reference + meta) into ``corpus_dir`` under a
    fresh id. The meta is copied verbatim so its license/source ride along
    unchanged — eval-only stays eval-only. The source's kind is stamped into the
    copy's meta so the (informational) tag survives the move into any corpus,
    even one outside a kind folder."""
    corpus_dir = _confine(Path(corpus_dir), Path(root))
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"corpus dir not found: {corpus_dir}")
    if not src.reference_musicxml.is_file():
        raise FileNotFoundError(f"source sample has no reference: {src.dir}")

    sample_id = next_sample_id(corpus_dir)
    sample_dir = corpus_dir / sample_id
    sample_dir.mkdir()
    image = src.image
    if image is not None:
        shutil.copy(image, sample_dir / f"image{image.suffix.lower()}")
    shutil.copy(src.reference_musicxml, sample_dir / "reference.musicxml")
    meta = dict(src.meta)
    if src.kind and "kind" not in meta:
        meta["kind"] = src.kind
    (sample_dir / "meta.yaml").write_text(yaml.safe_dump(meta, sort_keys=True))
    return Sample(id=sample_id, dir=sample_dir)


def remove_sample(corpus_dir: Path, sample_id: str, root: Path = CORPORA_ROOT) -> None:
    """Delete one sample directory. Irreversible."""
    sample_dir = _confine(Path(corpus_dir) / sample_id, Path(root))
    if not sample_dir.is_dir():
        raise FileNotFoundError(f"sample not found: {sample_dir}")
    shutil.rmtree(sample_dir)


def delete_corpus(corpus_dir: Path, root: Path = CORPORA_ROOT) -> None:
    """Delete a whole corpus directory. Irreversible."""
    target = _confine(Path(corpus_dir), Path(root))
    if not target.is_dir():
        raise FileNotFoundError(f"corpus not found: {target}")
    shutil.rmtree(target)


def _validate_musicxml(xml: str) -> None:
    """Best-effort: parse with music21 so unparseable ground truth is caught at
    upload. music21 is a core dep but heavy, so import it lazily."""
    from music21 import converter

    try:
        converter.parseData(xml)
    except Exception as exc:  # music21 raises a zoo of types
        raise ValueError(f"reference MusicXML did not parse: {exc}") from exc
