"""Tests for corpus discovery and the Sample path/meta accessors."""

from __future__ import annotations

import pytest

from omrbench.corpus import (
    Sample,
    add_sample,
    copy_sample,
    create_corpus,
    delete_corpus,
    discover,
    list_corpora,
    next_sample_id,
    remove_sample,
)

# A tiny well-formed MusicXML score music21 can parse (used by add_sample's
# validation). One pitch is enough.
_MINIMAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Music</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
      <time><beats>4</beats><beat-type>4</beat-type></time>
      <clef><sign>G</sign><line>2</line></clef></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>
"""


def _make_sample_dir(root, sample_id, *, image=None, reference=True, meta=None):
    d = root / sample_id
    d.mkdir()
    if image:
        (d / image).write_bytes(b"\x89PNG\r\n")
    if reference:
        (d / "reference.musicxml").write_text("<score/>")
    if meta is not None:
        (d / "meta.yaml").write_text(meta)
    return d


def test_discover_returns_sorted_sample_dirs(tmp_path):
    _make_sample_dir(tmp_path, "0002")
    _make_sample_dir(tmp_path, "0000")
    _make_sample_dir(tmp_path, "0001")
    (tmp_path / "notes.txt").write_text("ignored: only dirs are samples")

    samples = discover(tmp_path)
    assert [s.id for s in samples] == ["0000", "0001", "0002"]
    assert all(isinstance(s, Sample) for s in samples)


def test_discover_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover(tmp_path / "nope")


def test_sample_image_prefers_image_png(tmp_path):
    d = _make_sample_dir(tmp_path, "0000", image="image.png")
    (d / "extra.jpg").write_bytes(b"\xff\xd8")  # also present, but image.png wins
    sample = Sample(id="0000", dir=d)
    assert sample.image == d / "image.png"


def test_sample_image_falls_back_to_first_image_like(tmp_path):
    d = _make_sample_dir(tmp_path, "0000", image="scan.jpeg")
    sample = Sample(id="0000", dir=d)
    assert sample.image == d / "scan.jpeg"


def test_sample_image_none_when_absent(tmp_path):
    d = _make_sample_dir(tmp_path, "0000")
    assert Sample(id="0000", dir=d).image is None


def test_sample_reference_path(tmp_path):
    d = _make_sample_dir(tmp_path, "0000")
    assert Sample(id="0000", dir=d).reference_musicxml == d / "reference.musicxml"


def test_sample_meta_parsed_and_empty_defaults(tmp_path):
    with_meta = _make_sample_dir(tmp_path, "0000", meta="type: real_scan\nlicense: eval-only\n")
    assert Sample(id="0000", dir=with_meta).meta == {"type": "real_scan", "license": "eval-only"}

    no_meta = _make_sample_dir(tmp_path, "0001")
    assert Sample(id="0001", dir=no_meta).meta == {}


# --- corpus management (list + create + edit) ------------------------------


def test_create_corpus_makes_dir(tmp_path):
    path = create_corpus("myset", root=tmp_path)
    assert path == tmp_path / "myset"
    assert path.is_dir()


def test_create_corpus_rejects_bad_name(tmp_path):
    # bad segments, and the reserved kind-folder names
    for bad in ("", "..", "a/b", "a\\b", "synthetic", "real"):
        with pytest.raises(ValueError):
            create_corpus(bad, root=tmp_path)


def test_create_corpus_refuses_existing(tmp_path):
    create_corpus("dup", root=tmp_path)
    with pytest.raises(FileExistsError):
        create_corpus("dup", root=tmp_path)


def test_next_sample_id_increments(tmp_path):
    assert next_sample_id(tmp_path) == "0000"
    _make_sample_dir(tmp_path, "0000")
    _make_sample_dir(tmp_path, "0003")
    assert next_sample_id(tmp_path) == "0004"


def test_add_sample_writes_files_and_increments(tmp_path):
    s0 = add_sample(tmp_path, image_bytes=b"\x89PNG\r\n", image_suffix=".png",
                    reference_xml=_MINIMAL_XML, meta={"source": "hand", "type": "engraved"},
                    root=tmp_path)
    assert s0.id == "0000"
    assert (tmp_path / "0000" / "image.png").is_file()
    assert s0.reference_musicxml.read_text() == _MINIMAL_XML
    assert s0.meta == {"source": "hand", "type": "engraved"}

    s1 = add_sample(tmp_path, image_bytes=b"\xff\xd8", image_suffix=".jpg",
                    reference_xml=_MINIMAL_XML, meta={}, root=tmp_path)
    assert s1.id == "0001"
    assert (tmp_path / "0001" / "image.jpg").is_file()


def test_add_sample_rejects_unparseable_reference(tmp_path):
    with pytest.raises(ValueError):
        add_sample(tmp_path, image_bytes=b"x", image_suffix=".png",
                   reference_xml="not musicxml at all", meta={}, root=tmp_path)
    assert not (tmp_path / "0000").exists()  # nothing written on rejection


def test_add_sample_rejects_bad_image_suffix(tmp_path):
    with pytest.raises(ValueError):
        add_sample(tmp_path, image_bytes=b"x", image_suffix=".gif",
                   reference_xml=_MINIMAL_XML, meta={}, validate=False, root=tmp_path)


def test_add_sample_guards_traversal(tmp_path):
    # a corpus dir outside the corpora root is refused before anything is written
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "corpora"
    root.mkdir()
    with pytest.raises(ValueError):
        add_sample(outside, image_bytes=b"x", image_suffix=".png",
                   reference_xml=_MINIMAL_XML, meta={}, validate=False, root=root)
    assert not (outside / "0000").exists()


def test_copy_sample_preserves_meta_verbatim(tmp_path):
    src_corpus = tmp_path / "src"
    src_corpus.mkdir()
    _make_sample_dir(src_corpus, "0000", image="image.png",
                     meta="type: real_scan\nlicense: evaluation only — do not train\nsource: polish\n")
    src = Sample(id="0000", dir=src_corpus / "0000")

    dst = tmp_path / "dst"
    dst.mkdir()
    copied = copy_sample(dst, src, root=tmp_path)
    assert copied.id == "0000"
    assert (dst / "0000" / "image.png").is_file()
    # The eval-only license rides along unchanged.
    assert copied.meta == {"type": "real_scan", "license": "evaluation only — do not train", "source": "polish"}


def test_remove_sample_and_delete_corpus(tmp_path):
    corpus_dir = tmp_path / "synthetic" / "c"
    corpus_dir.mkdir(parents=True)
    _make_sample_dir(corpus_dir, "0000")
    remove_sample(corpus_dir, "0000", root=tmp_path)
    assert not (corpus_dir / "0000").exists()

    _make_sample_dir(corpus_dir, "0001")
    delete_corpus(corpus_dir, root=tmp_path)
    assert not corpus_dir.exists()


def test_remove_sample_guards_traversal(tmp_path):
    (tmp_path / "secret.txt").write_text("keep me")
    corpus_dir = tmp_path / "c"
    corpus_dir.mkdir()
    with pytest.raises(ValueError):
        remove_sample(corpus_dir, "../..", root=tmp_path)


def test_list_corpora_finds_leaf_corpus_dirs(tmp_path):
    a = tmp_path / "synthetic" / "alpha"
    a.mkdir(parents=True)
    _make_sample_dir(a, "0000", meta="source: alpha-src\n")
    _make_sample_dir(a, "0001", meta="source: alpha-src\n")
    b = tmp_path / "real" / "beta"
    b.mkdir(parents=True)
    _make_sample_dir(b, "0000")

    found = list_corpora(root=tmp_path)
    by_path = {c.path: c for c in found}
    assert set(by_path) == {str(a), str(b)}
    assert by_path[str(a)].count == 2
    assert by_path[str(a)].sources == ["alpha-src"]


def test_list_corpora_includes_empty_just_created(tmp_path):
    empty = create_corpus("fresh", root=tmp_path)
    found = list_corpora(root=tmp_path)
    assert [c.path for c in found] == [str(empty)]
    assert found[0].count == 0


def test_sample_kind_from_meta_or_path(tmp_path):
    (tmp_path / "anywhere").mkdir()
    (tmp_path / "synthetic" / "c").mkdir(parents=True)
    (tmp_path / "plain").mkdir()
    # explicit meta kind wins
    d = _make_sample_dir(tmp_path / "anywhere", "0000", meta="kind: real\n")
    assert Sample(id="0000", dir=d).kind == "real"
    # else inferred from a kind folder in the path
    sd = _make_sample_dir(tmp_path / "synthetic" / "c", "0000")
    assert Sample(id="0000", dir=sd).kind == "synthetic"
    # else None
    nd = _make_sample_dir(tmp_path / "plain", "0000")
    assert Sample(id="0000", dir=nd).kind is None


def test_copy_sample_stamps_kind_so_it_travels(tmp_path):
    # source under a synthetic folder, no kind in meta
    src_corpus = tmp_path / "synthetic" / "src"
    src_corpus.mkdir(parents=True)
    _make_sample_dir(src_corpus, "0000", image="image.png", meta="source: s\n")
    src = Sample(id="0000", dir=src_corpus / "0000")
    # copied into a kind-less corpus, the inferred kind is recorded in meta
    dst = create_corpus("mixed", root=tmp_path)
    copied = copy_sample(dst, src, root=tmp_path)
    assert copied.meta["kind"] == "synthetic"
    assert copied.meta["source"] == "s"


def test_copy_sample_guards_traversal(tmp_path):
    src_corpus = tmp_path / "src"
    src_corpus.mkdir()
    _make_sample_dir(src_corpus, "0000")
    src = Sample(id="0000", dir=src_corpus / "0000")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "corpora"
    root.mkdir()
    with pytest.raises(ValueError):
        copy_sample(outside, src, root=root)
    assert not (outside / "0000").exists()
