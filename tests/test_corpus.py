"""Tests for corpus discovery and the Sample path/meta accessors."""

from __future__ import annotations

import pytest

from omrbench.corpus import Sample, discover


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
    with_meta = _make_sample_dir(tmp_path, "0000", meta="tier: tier2_real\nlicense: eval-only\n")
    assert Sample(id="0000", dir=with_meta).meta == {"tier": "tier2_real", "license": "eval-only"}

    no_meta = _make_sample_dir(tmp_path, "0001")
    assert Sample(id="0001", dir=no_meta).meta == {}
